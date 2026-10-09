import os
from enum import Enum
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("APP_SECRET_KEY", "fallback-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 dias

class SystemRole(str, Enum):
    USER = "user"           
    MODERATOR = "moderator" 
    ADMIN = "admin"         


def get_system_role(user_id: int | str) -> SystemRole:
    """Verifica se o ID do Discord pertence à staff do sistema."""
    uid = str(user_id)
    admin_ids = [i.strip() for i in os.getenv("SYSTEM_ADMIN_IDS", "").split(",") if i.strip()]
    mod_ids = [i.strip() for i in os.getenv("SYSTEM_MOD_IDS", "").split(",") if i.strip()]

    if uid in admin_ids:
        return SystemRole.ADMIN
    if uid in mod_ids:
        return SystemRole.MODERATOR
    return SystemRole.USER


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None