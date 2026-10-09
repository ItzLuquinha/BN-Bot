# Commands

## Utilidades

`/ping`, `/uptime`, `/botinfo`, `/serverinfo`, `/userinfo` e `/avatar` mostram informações rápidas. `/history` exibe até 50 comandos recentes e exige Manage Server.

`/purge` aceita de 1 a 1000 mensagens a analisar/remover. O Discord exclui em lotes de até 100; mensagens com mais de 14 dias podem exigir exclusão individual e demorar mais.

`/tutorial`, `/remind` e `/dashboard` cobrem instruções, lembretes e gerenciamento do servidor.

## Economia e progressão

`/balance`, `/bank`, `/deposit`, `/withdraw`, `/pay`, `/daily`, `/weekly`, `/shop`, `/buy`, `/sell`, `/inventory`, `/transactions`, `/jobs`, `/job`, `/work`, `/profile`, `/rep`, `/reps` e `/leaderboard` cobrem economia e progressão.

## Moderação

`/warn`, `/t-warn`, `/warns`, `/unwarn`, `/clearwarns`, `/timeout`, `/untimeout`, `/unmute`, `/kick`, `/ban`, `/unban` e `/purge` exigem as permissões correspondentes do Discord.


## AutoMod

`/automod setup` creates the default protection policy and activates AutoMod.

`/automod enable` and `/automod disable` control the module.

`/automod rules` lists configured rules.

`/automod rule-add` creates a rule with JSON configuration, priority and optional channel or role scope.

`/automod rule-update` changes action, configuration, priority, scope or enabled state.

`/automod rule-delete` removes a rule.

`/automod list-add`, `/automod list-remove` and `/automod lists` manage whitelist and blacklist entries for users, channels, roles, words and domains.

`/automod list-action` controls the action taken for a blacklist match.

## Anti-Raid

/antiraid setup
/antiraid enable
/antiraid disable
/antiraid configure
/antiraid status
/antiraid unlock


## Community

`/ticket` opens a private support channel. `/ticket-close`, `/ticket-reopen` and `/ticket-claim` operate tickets. `/ticket-config` configures the ticket category, staff roles and transcript channel.

`/suggest` publishes a suggestion with persistent community voting. `/suggestion-status` moves a suggestion through pending, analysis, approved, rejected or implemented.

`/report` registers a report with optional evidence. `/report-status` moves it through open, investigating, resolved or rejected. `/community-config` configures the suggestion and report channels.

`/giveaway create` creates a giveaway with duration, winner count, role requirements, minimum level and minimum messages. `/giveaway end` ends it immediately. `/giveaway reroll` selects another winner without reusing previous winners. `/giveaway cancel` cancels an active giveaway.

`/poll create` creates an interactive poll with 2 to 10 options. `/poll end` closes it immediately.

`/admin job-remove` remove uma vaga com autocomplete e confirmação. `/praise` homenageia os três membros configurados pelo BN Bot.


## Economy

`/transactions` mostra o histórico financeiro do membro com filtros por entradas, saídas, transferências e compras. `/daily` e `/weekly` usam os valores configurados pelo administrador em `/admin rewards`, incluindo bônus de sequência. `/shop`, `/buy`, `/sell` e `/inventory` usam paginação e autocomplete para catálogos maiores.

## Administration

`/admin rewards` configura os valores base de daily e weekly e o bônus de sequência. `/admin shop-add` pode definir descrição, raridade, limite por membro, cooldown e janela de disponibilidade.
