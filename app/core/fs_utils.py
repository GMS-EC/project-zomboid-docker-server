import os
import json
import stat
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional, Set, Union

PROTECTED_INTERNAL_FILES: Set[str] = {
    "pz_panel_config.json",
    "activity.json",
    "activity_logs.json",
    "players_history.json",
    "mods_catalog.json",
    "tasks.json",
    "webhooks.json",
    ".revoked_tokens.json",
    ".secret_key",
}


def atomic_write_text(
    file_path: Union[str, Path],
    content: str,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
) -> None:
    """Escribe un archivo de texto atómicamente para prevenir corrupción."""
    path = Path(file_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp.{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp_path, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None and os.name != "nt":
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_json(file_path: Union[str, Path], data: Any, indent: int = 2, encoding: str = "utf-8") -> None:
    """Escribe un archivo JSON atómicamente."""
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write_text(file_path, content, encoding=encoding)


def safe_extract_zip(
    zip_path: Union[str, Path],
    dest_dir: Union[str, Path],
    skip_member_fn: Optional[Callable[[zipfile.ZipInfo], bool]] = None,
    max_entries: int = 20000,
    max_total_bytes: int = 2 * 1024 * 1024 * 1024,
    max_ratio: float = 100.0,
) -> int:
    """Valida un archivo ZIP contra ZipSlip, enlaces simbólicos y ZipBomb antes de extraer."""
    dest_resolved = Path(dest_dir).resolve()
    total_extracted = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > max_entries:
            raise ValueError(f"Zip exceeds maximum entry limit ({max_entries})")

        for member in members:
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Zip contains unsafe symbolic links")
            member_path = (dest_resolved / member.filename).resolve()
            if not member_path.is_relative_to(dest_resolved):
                raise ValueError("Zip contains unsafe paths (ZipSlip)")
            if member.compress_size > 0 and (member.file_size / member.compress_size) > max_ratio:
                raise ValueError("Zip compression ratio exceeds safe limit (ZipBomb)")

        for member in members:
            if skip_member_fn and skip_member_fn(member):
                continue
            member_path = (dest_resolved / member.filename).resolve()
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue

            member_path.parent.mkdir(parents=True, exist_ok=True)
            member_bytes = 0
            with zf.open(member, "r") as src, open(member_path, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    member_bytes += len(chunk)
                    total_extracted += len(chunk)
                    if total_extracted > max_total_bytes:
                        raise ValueError("Zip extracted size exceeds safe limit (ZipBomb)")
                    if (
                        member.compress_size > 0
                        and member_bytes > 10 * 1024 * 1024
                        and (member_bytes / member.compress_size) > max_ratio
                    ):
                        raise ValueError("Zip compression ratio exceeds safe limit (ZipBomb)")
                    dst.write(chunk)
    return total_extracted


def format_size(size_bytes: int) -> str:
    """Formatea un tamaño en bytes a B/KB/MB/GB legible."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
