from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.database import get_db
from api.routers import guilds, auth

app = FastAPI(
    title="Dashboard REST API",
    description="API independente para alimentar o Dashboard Web",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Autenticação"])
app.include_router(guilds.router, prefix="/api/v1/guilds", tags=["Guilds & Configurações"])

@app.get("/health", tags=["Status"])
async def health():
    return {"status": "online"}

@app.get("/health/db", tags=["Status"])
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT current_database();"))
    db_name = result.scalar()
    return {
        "status": "connected",
        "database": db_name
    }