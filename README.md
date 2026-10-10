# BN Bot

## Instalação

Execute na raiz do projeto, no PowerShell.

```powershell
py -3.12 -m venv .venv
```
Cria o ambiente Python.

```powershell
.\.venv\Scripts\Activate.ps1
```
Ativa o ambiente Python.

```powershell
python -m pip install -e ".[dev]"
```
Instala as dependências Python.

```powershell
npm --prefix web ci
```
Instala as dependências do dashboard.

Configure as variáveis de ambiente necessárias antes de iniciar os serviços.

## Inicialização

```powershell
docker compose up -d postgres redis
```
Inicia PostgreSQL e Redis.

```powershell
alembic upgrade head
```
Aplica as migrações do banco.

Execute cada serviço em um terminal separado.

```powershell
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```
Inicia a API.

```powershell
$env:VITE_API_URL = "http://localhost:8000"
npm --prefix web run dev -- --host 127.0.0.1
```
Inicia o dashboard React.

```powershell
python main.py
```
Inicia o bot Discord.

## Verificações

```powershell
python -m pytest -q
```
Executa os testes Python.

```powershell
python scripts/audit.py
```
Executa a auditoria do repositório.

```powershell
npm --prefix web run lint
```
Executa o ESLint.

```powershell
npm --prefix web run build
```
Gera o build de produção do dashboard.
