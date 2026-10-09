# Diagnóstico de `/instagram` e `/tiktok`

Os extratores de Instagram e TikTok mudam quando as plataformas atualizam a entrega de mídia. O bot não acessa publicações privadas nem contorna uma exigência de autenticação.

## Atualizar o extrator

Na raiz do projeto, execute no PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --upgrade --pre "yt-dlp[default,curl-cffi]"
.\.venv\Scripts\python.exe -m yt_dlp --version
```

O parâmetro `--pre` permite instalar o canal nightly do `yt-dlp`, que recebe alterações antes da próxima versão estável. Isso pode corrigir mudanças recentes no site, mas não garante acesso a publicações que exigem login ou que a plataforma bloqueia.

## Testar fora do Discord

Use um link público que abra no navegador:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_social_video.py instagram "https://www.instagram.com/reel/ID_PUBLICO/"
.\.venv\Scripts\python.exe scripts\smoke_social_video.py tiktok "https://www.tiktok.com/@USUARIO/video/ID"
```

O teste tenta obter o arquivo e o salva na pasta atual. O terminal mostra a versão do `yt-dlp` e um detalhe sanitizado da falha, quando houver. O programa remove URLs dos trechos registrados para evitar expor identificadores e parâmetros do link.

## Como interpretar o resultado

- `O extrator não encontrou um formato compatível`: atualize para nightly e tente uma única vez novamente.
- `A plataforma não liberou o vídeo sem autenticação`: o site exige login ou não disponibilizou o conteúdo para uma sessão anônima; o bot não tenta contornar isso.
- `A plataforma limitou os pedidos`: pare de testar repetidamente e aguarde o limite passar.
- `Não foi possível acessar a plataforma pela rede`: verifique DNS, firewall, proxy e conectividade da máquina onde o bot roda.
- `Faltam dependências de download`: repita a instalação de `requirements.txt` dentro da `.venv` correta.

O `/testall` valida o registro dos comandos, as dependências e o formato das URLs sem fazer downloads automáticos. Para testar o acesso real ao site, use o script de smoke test acima.
