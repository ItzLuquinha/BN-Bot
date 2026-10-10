# Brasil Novo Bot

## API Backend

```bat
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

## Dashboard react

```bat
set VITE_API_URL=http://127.0.0.1:8000
npm --prefix web run dev -- --host 127.0.0.1
```

## Ligar o bot

```bat
.\.venv\Scripts\python.exe main.py
```

Se PostgreSQL ou Redis não estiverem iniciados, execute antes:

```bat
docker compose up -d postgres redis
```
