from datetime import datetime, timezone
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.dependencies import (
    get_current_user, 
    require_guild_manager, 
    require_system_moderator
)
from api.core.security import SystemRole
from app.models import Guild, GuildSettings

router = APIRouter()

class GuildSettingsUpdateSchema(BaseModel):
    timezone: Optional[str] = Field(None, description="Fuso horário (ex: America/Sao_Paulo)")
    locale: Optional[str] = Field(None, description="Idioma (ex: pt-BR, en-US)")
    economy_enabled: Optional[bool] = Field(None, description="Ativar/desativar Economia")
    levels_enabled: Optional[bool] = Field(None, description="Ativar/desativar Níveis e XP")
    analytics_enabled: Optional[bool] = Field(None, description="Ativar/desativar Analytics")
    automod_enabled: Optional[bool] = Field(None, description="Ativar/desativar o AutoMod")
    config: Optional[dict[str, Any]] = Field(None, description="Configurações em JSON")

class GuildStatusUpdateSchema(BaseModel):
    active: bool = Field(..., description="Ativar ou desativar o bot no servidor")
    reason: Optional[str] = Field(None, description="Motivo da desativação (auditoria)")


@router.get("", summary="Listar servidores acessíveis ao usuário")
async def list_guilds(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user) 
):
    """
    Retorna apenas os servidores que o usuário logado tem permissão para gerenciar.
    Se for Moderador ou Admin do sistema, lista todos os servidores ativos da aplicação.
    """
    role = user.get("system_role")
    is_system_staff = role in {SystemRole.ADMIN.value, SystemRole.MODERATOR.value}

    if is_system_staff:
        query = select(Guild).where(Guild.active.is_(True))
    else:
        user_id = int(user["id"])
        user_guild_ids = [int(gid) for gid in user.get("guilds", []) if str(gid).isdigit()]
        
        query = select(Guild).where(
            Guild.active.is_(True),
            or_(
                Guild.owner_id == user_id,
                Guild.id.in_(user_guild_ids)
            )
        )

    result = await db.execute(query)
    guilds = result.scalars().all()
    
    return [
        {
            "id": str(guild.id),
            "name": guild.name,
            "icon_url": guild.icon_url,
            "owner_id": str(guild.owner_id) if guild.owner_id else None,
            "active": guild.active,
            "created_at": guild.created_at.isoformat() if guild.created_at else None,
            "updated_at": guild.updated_at.isoformat() if guild.updated_at else None,
        }
        for guild in guilds
    ]


@router.get("/{guild_id}", summary="Obter detalhes de um servidor")
async def get_guild(
    guild_id: int, 
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager)  
):
    """Retorna os dados cadastrais de um servidor específico."""
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": guild.icon_url,
        "owner_id": str(guild.owner_id) if guild.owner_id else None,
        "active": guild.active,
        "created_at": guild.created_at.isoformat() if guild.created_at else None,
        "updated_at": guild.updated_at.isoformat() if guild.updated_at else None,
    }


@router.get("/{guild_id}/settings", summary="Obter configurações do servidor")
async def get_guild_settings(
    guild_id: int, 
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager) 
):
    """Retorna as configurações do servidor."""
    settings = await db.get(GuildSettings, guild_id)
    if not settings:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configurações não encontradas")
    
    return {
        "guild_id": str(settings.guild_id),
        "timezone": settings.timezone,
        "locale": settings.locale,
        "economy_enabled": settings.economy_enabled,
        "levels_enabled": settings.levels_enabled,
        "analytics_enabled": settings.analytics_enabled,
        "automod_enabled": settings.automod_enabled,
        "config": settings.config or {},
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


@router.patch("/{guild_id}/settings", summary="Atualizar configurações do servidor")
async def update_guild_settings(
    guild_id: int, 
    payload: GuildSettingsUpdateSchema, 
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager)  
):
    """Atualiza as configurações do servidor via Dashboard."""
    settings = await db.get(GuildSettings, guild_id)
    if not settings:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configurações não encontradas")
    
    if payload.timezone is not None:
        settings.timezone = payload.timezone
    if payload.locale is not None:
        settings.locale = payload.locale
    if payload.economy_enabled is not None:
        settings.economy_enabled = payload.economy_enabled
    if payload.levels_enabled is not None:
        settings.levels_enabled = payload.levels_enabled
    if payload.analytics_enabled is not None:
        settings.analytics_enabled = payload.analytics_enabled
    if payload.automod_enabled is not None:
        settings.automod_enabled = payload.automod_enabled
    if payload.config is not None:
        current_config = dict(settings.config or {})
        current_config.update(payload.config)
        settings.config = current_config
        
    settings.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(settings)
    
    return {
        "guild_id": str(settings.guild_id),
        "timezone": settings.timezone,
        "locale": settings.locale,
        "economy_enabled": settings.economy_enabled,
        "levels_enabled": settings.levels_enabled,
        "analytics_enabled": settings.analytics_enabled,
        "automod_enabled": settings.automod_enabled,
        "config": settings.config,
        "updated_at": settings.updated_at.isoformat()
    }


@router.patch("/{guild_id}/status", summary="Moderação Global: Ativar ou Desativar servidor")
async def toggle_guild_status(
    guild_id: int,
    payload: GuildStatusUpdateSchema,
    db: AsyncSession = Depends(get_db),
    moderator: dict = Depends(require_system_moderator)
):
    """
    Permite à staff do sistema suspender ou reativar o bot em um servidor.
    """
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    
    guild.active = payload.active
    guild.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(guild)
    
    return {
        "guild_id": str(guild.id),
        "active": guild.active,
        "updated_at": guild.updated_at.isoformat(),
        "action_by": moderator["username"],
        "reason": payload.reason
    }