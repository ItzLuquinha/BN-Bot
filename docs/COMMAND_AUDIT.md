# Auditoria individual dos comandos BN Bot

Foram auditados individualmente 76 handlers. A matriz verifica decorador, escopo, resposta, defer antes de I/O, proteção de permissão quando aplicável e contrato funcional definido para cada comando.

| Comando | Arquivo | Params | Escopo | Permissão | Resposta | Defer | Contrato |
|---|---|---:|---|---|---|---|---|
| `/admin credit` | `admin.py` | 3 | guild | OK | OK | OK | OK |
| `/admin debit` | `admin.py` | 3 | guild | OK | OK | OK | OK |
| `/admin job-add` | `admin.py` | 4 | guild | OK | OK | OK | OK |
| `/admin shop-add` | `admin.py` | 4 | guild | OK | OK | OK | OK |
| `/admin timezone` | `admin.py` | 1 | guild | OK | OK | OK | OK |
| `/antiraid configure` | `antiraid.py` | 8 | guild | OK | OK | OK | OK |
| `/antiraid disable` | `antiraid.py` | 0 | guild | OK | OK | OK | OK |
| `/antiraid enable` | `antiraid.py` | 0 | guild | OK | OK | OK | OK |
| `/antiraid setup` | `antiraid.py` | 0 | guild | OK | OK | OK | OK |
| `/antiraid status` | `antiraid.py` | 0 | guild | OK | OK | OK | OK |
| `/antiraid unlock` | `antiraid.py` | 0 | guild | OK | OK | OK | OK |
| `/automod disable` | `automod.py` | 0 | guild | OK | OK | OK | OK |
| `/automod enable` | `automod.py` | 0 | guild | OK | OK | OK | OK |
| `/automod list-action` | `automod.py` | 1 | guild | OK | OK | OK | OK |
| `/automod list-add` | `automod.py` | 4 | guild | OK | OK | OK | OK |
| `/automod list-remove` | `automod.py` | 3 | guild | OK | OK | OK | OK |
| `/automod lists` | `automod.py` | 0 | guild | OK | OK | OK | OK |
| `/automod rule-add` | `automod.py` | 7 | guild | OK | OK | OK | OK |
| `/automod rule-delete` | `automod.py` | 1 | guild | OK | OK | OK | OK |
| `/automod rule-update` | `automod.py` | 7 | guild | OK | OK | OK | OK |
| `/automod rules` | `automod.py` | 0 | guild | OK | OK | OK | OK |
| `/automod setup` | `automod.py` | 0 | guild | OK | OK | OK | OK |
| `/automod status` | `automod.py` | 0 | guild | OK | OK | OK | OK |
| `/avatar` | `utility.py` | 1 | DM/guild | - | OK | OK | OK |
| `/balance` | `economy.py` | 1 | guild | - | OK | OK | OK |
| `/ban` | `moderation.py` | 2 | guild | OK | OK | OK | OK |
| `/bank` | `economy.py` | 0 | guild | - | OK | OK | OK |
| `/botinfo` | `utility.py` | 0 | DM/guild | - | OK | OK | OK |
| `/buy` | `economy.py` | 2 | guild | - | OK | OK | OK |
| `/clearwarns` | `moderation.py` | 1 | guild | OK | OK | OK | OK |
| `/community-config` | `community.py` | 2 | guild | OK | OK | OK | OK |
| `/daily` | `economy.py` | 0 | guild | - | OK | OK | OK |
| `/dashboard` | `dashboard.py` | 0 | guild | - | OK | OK | OK |
| `/deposit` | `economy.py` | 1 | guild | - | OK | OK | OK |
| `/giveaway cancel` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/giveaway create` | `community.py` | 6 | guild | OK | OK | OK | OK |
| `/giveaway end` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/giveaway reroll` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/help` | `utility.py` | 0 | DM/guild | - | OK | OK | OK |
| `/inventory` | `economy.py` | 0 | guild | - | OK | OK | OK |
| `/job` | `economy.py` | 1 | guild | - | OK | OK | OK |
| `/jobs` | `economy.py` | 0 | guild | - | OK | OK | OK |
| `/kick` | `moderation.py` | 2 | guild | OK | OK | OK | OK |
| `/leaderboard` | `progression.py` | 1 | guild | - | OK | OK | OK |
| `/pay` | `economy.py` | 2 | guild | - | OK | OK | OK |
| `/ping` | `utility.py` | 0 | DM/guild | - | OK | OK | OK |
| `/poll create` | `community.py` | 12 | guild | OK | OK | OK | OK |
| `/poll end` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/profile` | `progression.py` | 1 | guild | - | OK | OK | OK |
| `/purge` | `moderation.py` | 2 | guild | OK | OK | OK | OK |
| `/remind` | `utility.py` | 3 | guild | - | OK | OK | OK |
| `/rep` | `progression.py` | 2 | guild | - | OK | OK | OK |
| `/report` | `community.py` | 3 | guild | - | OK | OK | OK |
| `/report-status` | `community.py` | 3 | guild | OK | OK | OK | OK |
| `/reps` | `progression.py` | 1 | guild | - | OK | OK | OK |
| `/sell` | `economy.py` | 2 | guild | - | OK | OK | OK |
| `/serverinfo` | `utility.py` | 0 | guild | - | OK | OK | OK |
| `/shop` | `economy.py` | 0 | guild | - | OK | OK | OK |
| `/suggest` | `community.py` | 1 | guild | - | OK | OK | OK |
| `/suggestion-status` | `community.py` | 3 | guild | OK | OK | OK | OK |
| `/testall` | `utility.py` | 0 | guild | OK | OK | OK | OK |
| `/ticket` | `community.py` | 3 | guild | - | OK | OK | OK |
| `/ticket-claim` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/ticket-close` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/ticket-config` | `community.py` | 3 | guild | OK | OK | OK | OK |
| `/ticket-reopen` | `community.py` | 1 | guild | OK | OK | OK | OK |
| `/timeout` | `moderation.py` | 3 | guild | OK | OK | OK | OK |
| `/unban` | `moderation.py` | 1 | guild | OK | OK | OK | OK |
| `/unwarn` | `moderation.py` | 1 | guild | OK | OK | OK | OK |
| `/uptime` | `utility.py` | 0 | DM/guild | - | OK | OK | OK |
| `/userinfo` | `utility.py` | 1 | guild | - | OK | OK | OK |
| `/warn` | `moderation.py` | 2 | guild | OK | OK | OK | OK |
| `/warns` | `moderation.py` | 1 | guild | OK | OK | OK | OK |
| `/weekly` | `economy.py` | 0 | guild | - | OK | OK | OK |
| `/withdraw` | `economy.py` | 1 | guild | - | OK | OK | OK |
| `/work` | `economy.py` | 0 | guild | - | OK | OK | OK |
