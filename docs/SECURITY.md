# Segurança

O BN Bot usa verificações de permissão no nível do Application Command e também validações internas para ações sensíveis. Moderation commands remain protected by Discord permissions and server-side target hierarchy checks. Administrative groups require Manage Server, and ticket staff actions require the configured staff role or the specific channel management permission defined by the command.

Rate limits use the shared cooldown service with Redis and a local fallback. Sensitive and abuse-prone commands have per-user or per-guild buckets where appropriate.

User Install is intentionally restricted. Only commands that do not require the bot to be installed as a server member are marked as user-installable. The default CommandTree policy is Guild Install plus guild context, so a newly added command is not accidentally exposed through User Install. Discord documents that user-installed apps cannot take server actions and have reduced access to server data, so moderation and server management remain Guild Install only.

DM installation prompts are rate limited and contain no user-controlled mentions. OAuth2 links use the application client ID and do not expose secrets.
