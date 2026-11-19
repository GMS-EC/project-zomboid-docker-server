import json
import hmac
import hashlib
import base64
import ipaddress
import time
from typing import Optional, Dict, Any, Tuple, Set
from fastapi import Request, HTTPException, status

from app.config import settings
from app.core.fs_utils import atomic_write_text

SESSION_COOKIE_NAME = "pz_session"
SESSION_DURATION_SECONDS = 60 * 60  # 60 minutos de caducidad de sesión
_MAX_REVOKED_TOKENS = 5000


def _load_revoked_tokens() -> Set[str]:
    revoked_file = getattr(settings, "_revoked_tokens_file", None)
    if not revoked_file or not revoked_file.is_file():
        return set()
    try:
        data = json.loads(revoked_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(tok) for tok in data if isinstance(tok, str)}
    except Exception:
        pass
    return set()


def _save_revoked_tokens() -> None:
    revoked_file = getattr(settings, "_revoked_tokens_file", None)
    if not revoked_file:
        return
    try:
        atomic_write_text(revoked_file, json.dumps(sorted(_revoked_tokens)), mode=0o600)
    except Exception:
        pass


_revoked_tokens: Set[str] = _load_revoked_tokens()


class LoginRateLimiter:
    """Limitador de intentos fallidos de inicio de sesión por IP (estilo Dockraft)."""

    def __init__(self, max_attempts: int = 5, cooldown_seconds: int = 600):
        self.max_attempts = max_attempts
        self.cooldown_seconds = cooldown_seconds
        self.records: Dict[str, Dict[str, Any]] = {}
        self._cleanup_counter: int = 0

    def is_locked(self, ip: str) -> Tuple[bool, int]:
        now = time.time()
        self._cleanup_counter += 1
        if self._cleanup_counter >= 50:
            self.cleanup_expired()
            self._cleanup_counter = 0

        record = self.records.get(ip)
        if not record:
            return False, 0

        lockout_until = record.get("lockout_until", 0)
        if now < lockout_until:
            return True, max(1, int(lockout_until - now))
        if lockout_until > 0 and now >= lockout_until:
            del self.records[ip]
            return False, 0
        return False, 0

    def cleanup_expired(self) -> None:
        now = time.time()
        stale_threshold = max(self.cooldown_seconds, 900)
        expired = [
            ip for ip, rec in self.records.items()
            if (rec.get("lockout_until", 0) > 0 and now >= rec["lockout_until"])
            or (rec.get("lockout_until", 0) == 0 and (now - rec.get("last_attempt", 0)) > stale_threshold)
        ]
        for ip in expired:
            del self.records[ip]

    def record_failure(self, ip: str) -> Tuple[int, int]:
        now = time.time()
        record = self.records.setdefault(ip, {"attempts": 0, "lockout_until": 0, "last_attempt": now})
        if record["lockout_until"] > 0 and now >= record["lockout_until"]:
            record["attempts"] = 0
            record["lockout_until"] = 0
        record["attempts"] += 1
        record["last_attempt"] = now
        if record["attempts"] >= self.max_attempts:
            record["lockout_until"] = now + self.cooldown_seconds
            return 0, self.cooldown_seconds
        return max(0, self.max_attempts - record["attempts"]), 0

    def record_success(self, ip: str) -> None:
        self.records.pop(ip, None)


login_limiter = LoginRateLimiter(
    max_attempts=getattr(settings, "login_max_attempts", 5),
    cooldown_seconds=getattr(settings, "login_cooldown_seconds", 600),
)


def _is_trusted_proxy(ip_str: str) -> bool:
    if not ip_str:
        return False
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False
    for entry in getattr(settings, "trusted_proxies", ["127.0.0.1", "::1"]):
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    peer_ip = request.client.host if request.client else "unknown"
    if getattr(settings, "trust_proxy_headers", False) and _is_trusted_proxy(peer_ip):
        xff = request.headers.get("X-Forwarded-For", "").strip()
        if xff:
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            for hop in reversed(hops):
                try:
                    ipaddress.ip_address(hop)
                    if not _is_trusted_proxy(hop):
                        return hop
                except ValueError:
                    continue
        x_real = request.headers.get("X-Real-IP", "").strip()
        if x_real:
            try:
                ipaddress.ip_address(x_real)
                return x_real
            except ValueError:
                pass
    return peer_ip


def create_session_token(username: str = "admin") -> str:
    """Genera un token de sesión criptográficamente firmado."""
    issued_at = int(time.time())
    payload = f"{username}:{issued_at}"
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_session_token(token: str) -> Optional[str]:
    """Verifica la validez, firma, caducidad y no-revocación de un token de sesión."""
    if not token or token in _revoked_tokens:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        username, issued_at_str, signature = parts
        issued_at = int(issued_at_str)
        if time.time() - issued_at > SESSION_DURATION_SECONDS:
            return None
        expected_sig = hmac.new(
            settings.secret_key.encode(),
            f"{username}:{issued_at_str}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected_sig, signature):
            return username
    except Exception:
        return None
    return None


def revoke_token(token: Optional[str]) -> None:
    if not token or not verify_session_token(token):
        return
    _revoked_tokens.add(token)
    if len(_revoked_tokens) > _MAX_REVOKED_TOKENS:
        trimmed = list(_revoked_tokens)[-(_MAX_REVOKED_TOKENS // 2):]
        _revoked_tokens.clear()
        _revoked_tokens.update(trimmed)
    _save_revoked_tokens()


def verify_admin_credentials(username: str, password: str) -> bool:
    """Comprueba las credenciales del panel."""
    if not settings.admin_password:
        return True
    valid_user = hmac.compare_digest(username.strip(), settings.admin_user.strip())
    valid_pass = hmac.compare_digest(password.strip(), settings.admin_password.strip())
    return valid_user and valid_pass


def extract_token_from_request(request: Request) -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    return token


def is_authenticated(request: Request) -> bool:
    if not settings.admin_password:
        return True
    token = extract_token_from_request(request)
    if not token:
        return False
    return verify_session_token(token) is not None


def require_auth(request: Request):
    """Dependencia de FastAPI para proteger endpoints."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado. Inicie sesión en el panel.",
        )
