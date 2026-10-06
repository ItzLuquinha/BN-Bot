import hashlib
import secrets

def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def new_state() -> str:
    return secrets.token_urlsafe(32)
