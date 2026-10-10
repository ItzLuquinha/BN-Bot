import os
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from api.core.security import create_access_token, get_system_role
from api.dependencies import get_current_user
from app.core.security import consume_oauth_state, new_state, store_oauth_state

load_dotenv()

router = APIRouter()
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback").strip()
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:5173").strip().rstrip("/")
DISCORD_API_URL = "https://discord.com/api/v10"


@router.get("/login", summary="Login com Discord")
async def discord_login(request: Request):
    if not CLIENT_ID or not REDIRECT_URI:
        raise HTTPException(status_code=503, detail="Login com Discord não está configurado")
    state = new_state()
    store_oauth_state(request.session, state)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "identify guilds",
        "state": state,
    }
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{urlencode(params)}", status_code=302)


@router.get("/callback", summary="Callback OAuth2 do Discord")
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if not consume_oauth_state(request.session, state or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estado OAuth inválido ou expirado. Reinicie o login.")
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O login com Discord foi cancelado ou recusado")
    if not code or not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST if not code else status.HTTP_503_SERVICE_UNAVAILABLE, detail="Callback OAuth incompleto ou login não configurado")
    try:
        async with httpx.AsyncClient(base_url=DISCORD_API_URL, timeout=10) as client:
            token_response = await client.post(
                "/oauth2/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falha na autorização com Discord")
            token_payload = token_response.json()
            access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not isinstance(access_token, str) or not access_token:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resposta OAuth inválida do Discord")
            authorization = {"Authorization": f"Bearer {access_token}"}
            user_response = await client.get("/users/@me", headers=authorization)
            if user_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível confirmar a conta Discord")
            user_data = user_response.json()
            if not isinstance(user_data, dict) or not str(user_data.get("id", "")).isdigit():
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Perfil inválido retornado pelo Discord")
            guilds_response = await client.get("/users/@me/guilds", headers=authorization)
            if guilds_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível verificar as permissões nos servidores")
            response_guilds = guilds_response.json()
            if not isinstance(response_guilds, list):
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Lista de servidores inválida retornada pelo Discord")
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="O serviço de autenticação do Discord excedeu o tempo limite") from None
    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço de autenticação do Discord indisponível") from None
    manageable_guild_ids = []
    for guild in response_guilds:
        if not isinstance(guild, dict) or not str(guild.get("id", "")).isdigit():
            continue
        try:
            permissions = int(guild.get("permissions", 0))
        except (TypeError, ValueError):
            permissions = 0
        if guild.get("owner") or permissions & 8 or permissions & 32:
            manageable_guild_ids.append(str(guild["id"]))
    user_id = str(user_data["id"])
    role = get_system_role(user_id)
    jwt_token = create_access_token({
        "id": user_id,
        "username": str(user_data.get("username", "Discord User"))[:200],
        "avatar": user_data.get("avatar"),
        "system_role": role.value,
        "guilds": manageable_guild_ids,
    })
    request.session.clear()
    return RedirectResponse(f"{DASHBOARD_URL}/#token={jwt_token}", status_code=303)


@router.get("/me", summary="Obter dados do usuário autenticado")
async def get_me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout", summary="Encerrar autenticação do dashboard")
async def logout(request: Request):
    request.session.clear()
    return {"status": "logged_out"}
