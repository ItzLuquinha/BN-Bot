import asyncio
import logging
import sys
from importlib import import_module
from pathlib import Path


def runtime_preflight() -> None:
    if sys.version_info < (3, 12):
        raise SystemExit(f"Python 3.12+ é obrigatório. Versão atual: {sys.version.split()[0]}")
    project_venv = Path(__file__).resolve().parent / ".venv"
    executable = Path(sys.executable).resolve()
    if project_venv.exists() and project_venv.resolve() not in executable.parents:
        activation = r".\.venv\Scripts\Activate.ps1"
        direct_python = r".\.venv\Scripts\python.exe main.py"
        raise SystemExit(f"A .venv do projeto não está em uso. Executável atual: {executable}. Ativar o PowerShell pode exigir uma política de execução; use diretamente `{direct_python}` para evitar esse bloqueio.")
    try:
        import_module("greenlet")
    except Exception as exc:
        raise SystemExit(
            "Dependência ausente: greenlet. Execute `python -m pip install -r requirements.txt` usando o Python da .venv e tente novamente."
        ) from exc
    command_modules = (
        "app.discord.cogs.utility",
        "app.discord.cogs.economy",
        "app.discord.cogs.progression",
        "app.discord.cogs.moderation",
        "app.discord.cogs.community",
        "app.discord.cogs.automod",
        "app.discord.cogs.admin",
        "app.discord.cogs.antiraid",
    )
    try:
        for module_name in command_modules:
            import_module(module_name)
    except Exception as exc:
        raise SystemExit(
            f"Falha ao carregar definições dos comandos em {module_name}: {type(exc).__name__}: {exc}"
        ) from exc


runtime_preflight()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings
from app.core.logging import configure_logging
from app.discord.bot import BNBot


async def main() -> None:
    configure_logging()
    logger = logging.getLogger("bn_bot")
    bot = BNBot()
    logger.info("starting %s", get_settings().app_name)
    try:
        await bot.start(get_settings().discord_token)
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
