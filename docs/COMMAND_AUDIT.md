# Auditoria individual dos comandos BN Bot

A matriz audita individualmente todos os handlers executáveis do código, atualmente 89 comandos. A matriz verifica decorador, escopo, resposta, defer antes de I/O, proteção de permissão quando aplicável e contrato funcional definido para cada comando.

| Comando | Arquivo | Params | Escopo | Permissão |
|---|---|---:|---|---|
| `/admin credit` | `admin.py` | 3 | guild | OK |
| `/admin debit` | `admin.py` | 3 | guild | OK |
| `/admin job-add` | `admin.py` | 3 | guild | OK |
| `/admin job-remove` | `admin.py` | 1 | guild | OK |
| `/admin rewards` | `admin.py` | 4 | guild | OK |
| `/admin shop-add` | `admin.py` | 10 | guild | OK |
| `/admin timezone` | `admin.py` | 1 | guild | OK |
| `/antiraid configure` | `antiraid.py` | 8 | guild | OK |
| `/antiraid disable` | `antiraid.py` | 0 | guild | OK |
| `/antiraid enable` | `antiraid.py` | 0 | guild | OK |
| `/antiraid setup` | `antiraid.py` | 0 | guild | OK |
| `/antiraid status` | `antiraid.py` | 0 | guild | OK |
| `/antiraid unlock` | `antiraid.py` | 0 | guild | OK |
| `/automod disable` | `automod.py` | 0 | guild | OK |
| `/automod enable` | `automod.py` | 0 | guild | OK |
| `/automod list-action` | `automod.py` | 1 | guild | OK |
| `/automod list-add` | `automod.py` | 4 | guild | OK |
| `/automod list-remove` | `automod.py` | 3 | guild | OK |
| `/automod lists` | `automod.py` | 0 | guild | OK |
| `/automod rule-add` | `automod.py` | 7 | guild | OK |
| `/automod rule-delete` | `automod.py` | 1 | guild | OK |
| `/automod rule-update` | `automod.py` | 7 | guild | OK |
| `/automod rules` | `automod.py` | 0 | guild | OK |
| `/automod setup` | `automod.py` | 0 | guild | OK |
| `/automod status` | `automod.py` | 0 | guild | OK |
| `/avatar` | `utility.py` | 1 | DM/guild | - |
| `/balance` | `economy.py` | 1 | guild | - |
| `/ban` | `moderation.py` | 2 | guild | OK |
| `/bank` | `economy.py` | 0 | guild | - |
| `/botinfo` | `utility.py` | 0 | DM/guild | - |
| `/buy` | `economy.py` | 2 | guild | - |
| `/clearwarns` | `moderation.py` | 1 | guild | OK |
| `/coinflip` | `fun.py` | 0 | guild | - |
| `/community-config` | `community.py` | 2 | guild | OK |
| `/daily` | `economy.py` | 0 | guild | - |
| `/dashboard` | `dashboard.py` | 0 | guild | - |
| `/deposit` | `economy.py` | 1 | guild | - |
| `/dice` | `fun.py` | 0 | guild | - |
| `/eightball` | `fun.py` | 1 | guild | - |
| `/giveaway cancel` | `community.py` | 1 | guild | OK |
| `/giveaway create` | `community.py` | 6 | guild | OK |
| `/giveaway end` | `community.py` | 1 | guild | OK |
| `/giveaway reroll` | `community.py` | 1 | guild | OK |
| `/history` | `utility.py` | 1 | guild | OK |
| `/inventory` | `economy.py` | 0 | guild | - |
| `/job` | `economy.py` | 0 | guild | - |
| `/jobs` | `economy.py` | 0 | guild | - |
| `/kick` | `moderation.py` | 2 | guild | OK |
| `/kiss` | `fun.py` | 1 | guild | - |
| `/leaderboard` | `progression.py` | 2 | guild | - |
| `/pay` | `economy.py` | 2 | guild | - |
| `/ping` | `utility.py` | 0 | DM/guild | - |
| `/poll create` | `community.py` | 12 | guild | OK |
| `/poll end` | `community.py` | 1 | guild | OK |
| `/praise` | `fun.py` | 0 | guild | - |
| `/profile` | `progression.py` | 1 | guild | - |
| `/purge` | `moderation.py` | 2 | guild · 1–1000 | OK |
| `/remind` | `utility.py` | 3 | guild | - |
| `/rep` | `progression.py` | 2 | guild | - |
| `/report` | `community.py` | 3 | guild | - |
| `/report-status` | `community.py` | 3 | guild | - |
| `/reps` | `progression.py` | 1 | guild | - |
| `/rps` | `fun.py` | 0 | guild | - |
| `/sell` | `economy.py` | 2 | guild | - |
| `/serverinfo` | `utility.py` | 0 | guild | - |
| `/shop` | `economy.py` | 0 | guild | - |
| `/suggest` | `community.py` | 1 | guild | - |
| `/suggestion-status` | `community.py` | 3 | guild | - |
| `/t-warn` | `moderation.py` | 3 | guild | OK |
| `/testall` | `utility.py` | 0 | guild | OK |
| `/ticket` | `community.py` | 3 | guild | - |
| `/ticket-claim` | `community.py` | 1 | guild | - |
| `/ticket-close` | `community.py` | 1 | guild | - |
| `/ticket-config` | `community.py` | 3 | guild | OK |
| `/ticket-reopen` | `community.py` | 1 | guild | - |
| `/timeout` | `moderation.py` | 3 | guild | OK |
| `/transactions` | `economy.py` | 1 | guild | - |
| `/tutorial` | `utility.py` | 0 | DM/guild | - |
| `/unban` | `moderation.py` | 1 | guild | OK |
| `/unmute` | `moderation.py` | 2 | guild | OK |
| `/untimeout` | `moderation.py` | 2 | guild | OK |
| `/unwarn` | `moderation.py` | 1 | guild | OK |
| `/uptime` | `utility.py` | 0 | DM/guild | - |
| `/userinfo` | `utility.py` | 1 | guild | - |
| `/warn` | `moderation.py` | 2 | guild | OK |
| `/warns` | `moderation.py` | 1 | guild | OK |
| `/weekly` | `economy.py` | 0 | guild | - |
| `/withdraw` | `economy.py` | 1 | guild | - |
| `/work` | `economy.py` | 0 | guild | - |


