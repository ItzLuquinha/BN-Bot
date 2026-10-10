# Dashboard

Execute na raiz do projeto.

```powershell
npm --prefix web ci
```
Instala as dependências.

```powershell
$env:VITE_API_URL = "http://localhost:8000"
npm --prefix web run dev -- --host 127.0.0.1
```
Inicia o dashboard. A API deve estar ativa na porta 8000.

```powershell
npm --prefix web run lint
```
Executa o ESLint.

```powershell
npm --prefix web run build
```
Gera o build de produção.
