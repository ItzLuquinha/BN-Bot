# BN Bot

## Requisitos

- Python 3.12+
- Docker
- PostgreSQL
- Redis

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d redis
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\doctor.py
```

## Rodar

Bot:

```powershell
.\.venv\Scripts\python.exe main.py
```

Dashboard:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.dashboard.main:app --reload
```
https://supabase.com/dashboard/join?token=bqo8x-ulkct-q6lbo-ovx68&slug=oggldajzryhcrfjdenyg
