from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import SystemRole, decode_access_token, get_system_role
from api.database import get_db
from app.models import Guild

security = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado", headers={"WWW-Authenticate": "Bearer"})
    payload["system_role"] = get_system_role(payload["id"]).value
    return payload


async def require_guild_manager(
    guild_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    guild = await db.get(Guild, guild_id)
    if guild is None or getattr(guild, "active", True) is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    if current_user.get("system_role") == SystemRole.ADMIN.value:
        return current_user
    user_id = int(current_user["id"])
    if guild.owner_id == user_id:
        return current_user
    manageable = {str(item) for item in current_user.get("guilds", []) if str(item).isdigit()}
    if str(guild_id) in manageable:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem permissão para gerenciar este servidor.")


async def require_system_moderator(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("system_role") in {SystemRole.MODERATOR.value, SystemRole.ADMIN.value}:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito à equipe de moderação do sistema.")


async def require_system_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("system_role") == SystemRole.ADMIN.value:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito aos administradores do sistema.")
