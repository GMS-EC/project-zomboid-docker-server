import hmac
import hashlib
import base64
import time
from typing import Optional, Dict, Any, Tuple
from fastapi import Request, HTTPException, status
from app.config import settings

SESSION_COOKIE_NAME = "pz_session"
SESSION_DURATION_SECONDS = 60 * 60  # 60 minutos de caducidad de sesión

def create_session_token(username: str) -> str:
    """Genera un token de sesión criptográficamente firmado."""
    issued_at = int(time.time())
    payload = f"{username}:{issued_at}"
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()

def verify_session_token(token: str) -> Optional[str]:
    """Verifica la validez y firma de un token de sesión, respetando caducidad."""
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
            hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(expected_sig, signature):
            return username
    except Exception:
        return None
    return None

def verify_admin_credentials(username: str, password: str) -> bool:
    """Comprueba las credenciales del panel."""
    if not settings.admin_password:
        return True
    valid_user = hmac.compare_digest(username.strip(), settings.admin_user.strip())
    valid_pass = hmac.compare_digest(password.strip(), settings.admin_password.strip())
    return valid_user and valid_pass

def is_authenticated(request: Request) -> bool:
    if not settings.admin_password:
        return True
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
    if not token:
        return False
    return verify_session_token(token) is not None

def require_auth(request: Request):
    """Dependencia de FastAPI para proteger endpoints."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado. Inicie sesión en el panel."
        )
