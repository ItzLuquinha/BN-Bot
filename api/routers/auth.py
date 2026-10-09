import os
from urllib.parse import urlencode
from typing import Any
import httpx
from fastapi import APIRouter, HTTPException, status, Depends
from dotenv import load_dotenv

from api.core.security import create_access_token, get_system_role
from api.dependencies import get_current_user

load_dotenv()

router = APIRouter()

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback")

DISCORD_API_URL = "https://discord.com/api/v10"

@router.get("/login", summary="Gerar URL de Login com Discord")
async def discord_login():
    """Gera a URL para redirecionar o usuário para autorização do Discord."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "identify guilds",
    }
    return {
        "url": f"https://discord.com/oauth2/authorize?{urlencode(params)}"
    }


@router.get("/callback", summary="Callback OAuth2 do Discord")
async def discord_callback(code: str):
    """
    Recebe o código do Discord, busca perfil e servidores,
    e retorna o JWT de acesso para o Frontend.
    """
    async with httpx.AsyncClient(base_url=DISCORD_API_URL, timeout=10) as client:
        token_res = await client.post(
            "/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if token_res.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falha na autorização com Discord")
        
        discord_tokens = token_res.json()
        access_token = discord_tokens["access_token"]

        user_res = await client.get("/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if user_res.status_code != 200:
            raise HTTPException(status_code=502, detail="Erro ao buscar dados do usuário no Discord")
        user_data = user_res.json()

 
        guilds_res = await client.get("/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
        manageable_guild_ids = []
        if guilds_res.status_code == 200:
            for g in guilds_res.json():
                perms = int(g.get("permissions", 0))
                is_admin = bool(perms & 8) or bool(perms & 32) or bool(g.get("owner"))
                if is_admin:
                    manageable_guild_ids.append(str(g["id"]))

    user_id = str(user_data["id"])
    role = get_system_role(user_id)

    jwt_token = create_access_token({
        "id": user_id,
        "username": user_data["username"],
        "avatar": user_data.get("avatar"),
        "system_role": role.value,      
        "guilds": manageable_guild_ids    
    })

    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "username": user_data["username"],
            "avatar": user_data.get("avatar"),
            "system_role": role.value
        },
        "manageable_guilds": manageable_guild_ids
    }


@router.get("/me", summary="Obter dados do usuário logado")
async def get_me(user: dict = Depends(get_current_user)):
    """Retorna os dados do usuário a partir do token Bearer enviado."""
    return user