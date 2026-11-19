import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.config import settings
from app.core.process_manager import process_manager


class DiagnosticManager:
    """Analiza console.txt, logs en vivo y códigos de salida para detectar problemas de Project Zomboid."""

    def _read_tail(self, path: Path, max_lines: int = 400, max_bytes: int = 512 * 1024) -> str:
        if not path.exists() or path.is_symlink():
            return ""
        try:
            size = path.stat().st_size
            with open(path, "rb") as f:
                f.seek(max(0, size - max_bytes))
                data = f.read()
            lines = data.decode("utf-8", errors="replace").splitlines()
            return "\n".join(lines[-max_lines:])
        except Exception:
            return ""

    def _get_latest_pz_log(self) -> Optional[Path]:
        logs_dir = settings.data_dir / "Logs"
        if logs_dir.is_dir():
            candidates = sorted(
                (f for f in logs_dir.rglob("*.txt") if f.is_file() and "DebugLog" in f.name),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0]
        return None

    @staticmethod
    def _extract_excerpt(text: str, pattern: str, max_lines: int = 12) -> str:
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                start = max(0, idx - 2)
                end = min(len(lines), idx + max_lines)
                return "\n".join(lines[start:end])
        return "\n".join(lines[-max_lines:])

    def analyze_diagnostics(self, exit_code: Optional[int] = None) -> Dict[str, Any]:
        if exit_code is None:
            exit_code = process_manager.last_exit_code

        sources: List[tuple] = []
        if process_manager.log_buffer:
            sources.append(("Consola en Vivo", "\n".join(list(process_manager.log_buffer)[-400:])))

        console_txt = settings.console_log
        if console_txt.is_file():
            txt = self._read_tail(console_txt, max_lines=400)
            if txt.strip():
                sources.append(("console.txt", txt))

        latest_dbg = self._get_latest_pz_log()
        if latest_dbg:
            txt = self._read_tail(latest_dbg, max_lines=300)
            if txt.strip():
                sources.append((f"Logs/{latest_dbg.name}", txt))

        if not sources:
            if exit_code in (-9, 137):
                return {
                    "has_issue": True,
                    "severity": "critical",
                    "category": "system",
                    "title": f"Terminación Forzosa por el Sistema (Código {exit_code})",
                    "cause": "El proceso fue detenido mediante SIGKILL (-9 / 137). Suele ocurrir cuando Docker agota la memoria RAM asignada (OOM Killer).",
                    "recommendation": "Aumenta MEM_LIMIT en docker-compose.yml / .env o reduce el Heap Máximo (-Xmx) en Ajustes > Motor & RAM.",
                    "source": "Process Supervisor",
                    "excerpt": f"Process terminated with exit code {exit_code} (SIGKILL).",
                }
            return {
                "has_issue": False,
                "severity": "ok",
                "category": "none",
                "title": "Sin registros de errores",
                "cause": "",
                "recommendation": "No se detectaron fallos recientes en console.txt ni en la consola en vivo.",
                "source": None,
                "excerpt": "",
            }

        combined_text = "\n".join(txt for _, txt in sources)
        source_name = sources[0][0]

        # 1. OutOfMemoryError / Heap Space
        if re.search(r"(OutOfMemoryError|Java heap space|GC overhead limit exceeded)", combined_text, re.IGNORECASE):
            return {
                "has_issue": True,
                "severity": "critical",
                "category": "memory",
                "title": "Falta de Memoria RAM en la JVM (OutOfMemoryError)",
                "cause": "El servidor de Project Zomboid agotó la memoria heap máxima (-Xmx).",
                "recommendation": "Aumenta -Xmx en Ajustes > Motor & RAM (p. ej. 6g u 8g si usas muchos mods) y verifica MEM_LIMIT en Docker.",
                "source": source_name,
                "excerpt": self._extract_excerpt(combined_text, r"OutOfMemoryError|Java heap space|GC overhead"),
            }

        # 2. Puerto ocupado (16261 / 16262 / BindException)
        if re.search(r"(BindException|Address already in use|port\s*(?:16261|16262)\s*.*(?:in use|failed))", combined_text, re.IGNORECASE):
            return {
                "has_issue": True,
                "severity": "critical",
                "category": "network",
                "title": "Puerto UDP en Uso (16261 / 16262)",
                "cause": "Otro proceso o contenedor ya está utilizando los puertos de Project Zomboid (DefaultPort / UDPPort).",
                "recommendation": "Detén instancias duplicadas del servidor o cambia DefaultPort/UDPPort en Ajustes > Servidor & Acceso.",
                "source": source_name,
                "excerpt": self._extract_excerpt(combined_text, r"BindException|Address already in use|16261|16262"),
            }

        # 3. Errores de Workshop / SteamCMD / DownloadPending
        if re.search(r"(DownloadPending|Workshop item.*failed|Missing configuration|Failed to install app 380870|SteamWorkshop.*(?:fail|error))", combined_text, re.IGNORECASE):
            return {
                "has_issue": True,
                "severity": "warning",
                "category": "workshop",
                "title": "Error de Descarga en Steam Workshop o SteamCMD",
                "cause": "El servidor tuvo problemas descargando un ítem de Steam Workshop o los binarios de Steam.",
                "recommendation": "Verifica los IDs en la pestaña Mods, revisa la conectividad a Steam o usa DepotDownloader/modo No-Steam si corresponde.",
                "source": source_name,
                "excerpt": self._extract_excerpt(combined_text, r"DownloadPending|Workshop|Missing configuration|380870"),
            }

        # 4. Errores de Lua / KahluaException / Mods
        if re.search(r"(KahluaException|LuaManager|Syntax error.*SandboxVars\.lua|STACK TRACE)", combined_text, re.IGNORECASE):
            return {
                "has_issue": True,
                "severity": "warning",
                "category": "lua_mod",
                "title": "Error de Script Lua o Mod Incompatible",
                "cause": "Se produjo una excepción en el motor Lua (KahluaException) o en SandboxVars.lua / un mod.",
                "recommendation": "Revisa el stack trace para identificar el mod causante o valida la sintaxis de SandboxVars.lua en Ajustes > Editor Directo.",
                "source": source_name,
                "excerpt": self._extract_excerpt(combined_text, r"KahluaException|LuaManager|SandboxVars\.lua|STACK TRACE"),
            }

        # 5. SIGKILL OOM
        if exit_code in (-9, 137):
            return {
                "has_issue": True,
                "severity": "critical",
                "category": "system",
                "title": f"Terminación Forzosa por el Sistema (Código {exit_code})",
                "cause": "El proceso fue detenido mediante SIGKILL (probable OOM Killer de Linux/Docker).",
                "recommendation": "Verifica la RAM disponible en el host y el límite MEM_LIMIT del contenedor.",
                "source": "Process Supervisor",
                "excerpt": f"Process exited with code {exit_code} (SIGKILL).",
            }

        # 6. Errores / Excepciones genéricas
        m_err = re.search(r"(?m)^.*\b(?:FATAL|ERROR|Exception)\b.*$", combined_text)
        if m_err:
            return {
                "has_issue": True,
                "severity": "warning",
                "category": "general",
                "title": "Advertencia o Error Detectado en Registros",
                "cause": "Se registró al menos un mensaje ERROR o Exception durante la ejecución.",
                "recommendation": "Revisa el extracto adjunto o descarga el log completo desde la pestaña Consola.",
                "source": source_name,
                "excerpt": self._extract_excerpt(combined_text, r"\b(?:FATAL|ERROR|Exception)\b"),
            }

        return {
            "has_issue": False,
            "severity": "ok",
            "category": "none",
            "title": "Servidor saludable — sin errores detectados",
            "cause": "",
            "recommendation": "No se encontraron errores críticos ni excepciones Lua/JVM recientes.",
            "source": source_name,
            "excerpt": "",
        }


diagnostic_manager = DiagnosticManager()
