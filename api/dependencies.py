from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db
from api.core.security import decode_access_token, SystemRole
from app.models import Guild

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Extrai e valida o token Bearer."""
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado"
        )
    return payload


# --- TRAVA 1: Dono/Admin do Servidor (OU Admin do Sistema) ---
async def require_guild_manager(
    guild_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Permite acesso se:
    1. O usuário for Admin Geral do Sistema.
    2. O usuário for o Dono da Guild no banco.
    3. O usuário for Admin da Guild no Discord.
    """
    role = current_user.get("system_role")
    if role == SystemRole.ADMIN.value:
        return current_user  

    user_id = int(current_user["id"])
    guild = await db.get(Guild, guild_id)

    if guild and guild.owner_id == user_id:
        return current_user

    manageable = current_user.get("guilds", [])
    if str(guild_id) in manageable or guild_id in manageable:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Você não tem permissão para gerenciar este servidor."
    )


async def require_system_moderator(current_user: dict = Depends(get_current_user)) -> dict:
    """Permite acesso a Moderadores ou Administradores do Sistema."""
    role = current_user.get("system_role")
    if role in {SystemRole.MODERATOR.value, SystemRole.ADMIN.value}:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acesso restrito à equipe de moderação do sistema."
    )


async def require_system_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Permite acesso EXCLUSIVO a Administradores do Sistema."""
    role = current_user.get("system_role")
    if role == SystemRole.ADMIN.value:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acesso restrito aos administradores do sistema."
    )