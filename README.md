# BN Bot

Bot para Discord com moderação, Anti-Raid, AutoMod, economia, níveis, sorteios, enquetes, sugestões, tickets e painel web com login pelo Discord.

## Antes de iniciar

- Python 3.12
- Docker Desktop com o mecanismo Linux iniciado
- Aplicação criada no [Discord Developer Portal](https://discord.com/developers/applications)

## Instalação no Windows

Na pasta do projeto, copie `.env.example` para `.env` e preencha as variáveis. Não envie o `.env` para o GitHub nem compartilhe seu conteúdo. Para gerar uma chave de sessão, rode:

```powershell
py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Inicie o PostgreSQL e o Redis:

```powershell
docker compose up -d
docker compose ps
```

Crie o ambiente Python e instale as dependências:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Confira as dependências e aplique as migrações:

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Inicie o bot:

```powershell
.\.venv\Scripts\python.exe main.py
```

Para usar o painel web, abra outro terminal na mesma pasta e execute:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.dashboard.main:app --reload
```

O painel ficará no endereço local informado pelo Uvicorn, normalmente `http://127.0.0.1:8000`. O valor de `DISCORD_REDIRECT_URI` no `.env` deve ser exatamente igual ao redirect cadastrado no Developer Portal. Em produção, configure HTTPS e URLs públicas corretas.

## Intents do Discord

Ative no Developer Portal os intents exigidos pelo projeto, em especial **Server Members** e **Message Content**. Eles são usados por recursos de membros, automoderação e atividade.

## Testes

Execute os comandos abaixo a partir da raiz do repositório:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.audit
.\.venv\Scripts\python.exe -m scripts.security_audit
.\.venv\Scripts\python.exe scripts\command_matrix.py
```

## Problemas comuns

### `failed to connect to the docker API ... dockerDesktopLinuxEngine`

O comando não conseguiu encontrar o mecanismo Linux do Docker Desktop. Abra o Docker Desktop, espere o estado indicar que o mecanismo está em execução e rode `docker info`. Quando esse comando mostrar os dados do servidor, tente novamente `docker compose up -d`. Se os contêineres já estiverem iniciados, confira com `docker compose ps`.

### Avisos `PyNaCl is not installed` ou `davey is not installed`

Esses pacotes são usados pelo suporte a conexões de voz do Discord.py. O projeto usa eventos de estado de voz para registrar atividade, mas não precisa entrar em um canal para iniciar. O `requirements.txt` agora inclui os extras de voz; para instalar e remover esses avisos, rode novamente `python -m pip install -r requirements.txt` dentro da `.venv`.

### Comandos slash ausentes ou aviso de sincronização

Depois de iniciar uma versão nova, leia o log de sincronização. O verificador reconhece subcomandos como `/admin credit` e `/antiraid configure` dentro do objeto principal do comando. Se o Discord devolver um erro HTTP 429, deixe o bot respeitar o tempo de espera informado e evite reiniciar repetidamente.

## Documentos do projeto

- `docs/SETUP_WINDOWS.md`: configuração detalhada no Windows
- `docs/ARCHITECTURE.md`: organização do código
- `docs/SECURITY.md`: autenticação e controles de segurança
- `docs/AUDIT_REPORT.md`: relatório da auditoria anterior
