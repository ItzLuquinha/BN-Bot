# Setup on Windows

## Requirements

Install Python 3.12 or newer, Docker Desktop and a Discord application with a bot user.

## Environment

Copy `.env.example` to `.env`.

Set the Discord bot token, application client ID, application client secret, dashboard redirect URI and application secret. Do not commit `.env`.

## Infrastructure

From the project directory run:

`docker compose up -d`

This starts PostgreSQL and Redis.

## Python environment

Create a virtual environment:

`py -3.12 -m venv .venv`

Install dependencies:

`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`

Verifique o ambiente com `.\.venv\Scripts\python.exe scripts\doctor.py` antes de iniciar o bot.

For development dependencies use:

`.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`

## Database

Run:

`.\.venv\Scripts\python.exe -m alembic upgrade head`

Run `.\.venv\Scripts\python.exe scripts\doctor.py` before starting the bot.

Run `.\.venv\Scripts\python.exe -m alembic upgrade head` after installing a newer BN Bot version.

Seed one Discord guild:

`.\.venv\Scripts\python.exe -m scripts.seed`

## Dashboard

Set the Discord OAuth2 redirect URI in the Developer Portal to the exact value configured in `.env`.

Run:

`.\.venv\Scripts\python.exe -m uvicorn app.dashboard.main:app --reload`

Open the configured dashboard URL and authenticate with Discord.

## Bot

Run in a separate terminal:

`.\.venv\Scripts\python.exe main.py`

Enable the required Discord intents in the Developer Portal before using message analytics or member activity collection.


### Sincronização de comandos em desenvolvimento

Defina `DISCORD_GUILD_ID` no `.env` para que o BN Bot publique a árvore atual diretamente na sua guild durante o desenvolvimento. Isso evita o uso de uma assinatura global antiga enquanto o Discord propaga alterações globais.
