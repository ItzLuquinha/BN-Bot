# Relatório de auditoria técnica: BN Bot

**Data:** 9 de outubro de 2026  
**Escopo:** código Python, comandos e eventos Discord, painel FastAPI, OAuth/sessões, frontend estático, workers, serviços, modelos SQLAlchemy, migrações, scripts, documentação e testes. Arquivos `.env` e variantes com segredos não foram abertos nem incluídos no pacote corrigido.

## Resumo

Foram corrigidos problemas identificados na inspeção estática e nos testes. As mudanças principais reduzem chamadas repetidas à API do Discord, tornam as tentativas após falhas finitas e consertam o ciclo de vida do Anti-Raid para impedir que o worker remova um lockdown antes de expirar.

## Bugs encontrados e correções aplicadas

### 1. Anti-Raid podia desfazer o lockdown antes do prazo configurado

O worker de manutenção considerava todo servidor com registros de canais bloqueados como candidato a restauração, mesmo quando `active_until` ainda estava no futuro. Como o worker roda a cada 30 segundos, isso podia restaurar canais pouco depois do início de um lockdown que deveria durar muito mais.

**Correção:** o worker agora só processa servidores cujo lockdown expirou, cujo desbloqueio foi solicitado ou que não possuem mais registro de proteção ativo. A consulta também só agenda restaurações cujo horário de retry já chegou. Um desbloqueio manual limpa `active_until`, inclusive quando ainda há canais aguardando restauração.

### 2. Estado de restauração de canais podia ser perdido

O estado original das permissões era persistido ao fim do loop. Se o processo terminasse inesperadamente depois de modificar várias permissões, mas antes do `commit`, os canais poderiam permanecer bloqueados sem um registro que permitisse restaurá-los.

**Correção:** o estado original de cada canal agora é gravado antes da chamada que modifica as permissões. Falhas conhecidas de permissão ou rate limit removem o registro recém-criado; falhas HTTP ambíguas conservam o estado original para permitir restauração posterior.

### 3. Retentativas de restauração precisavam de agendamento persistente

Falhas durante a restauração de permissões não tinham um agendamento persistente para recuperação e podiam deixar canais presos no estado de lockdown.

**Correção:** foi adicionada uma política de retry com atraso exponencial e respeito ao `retry_after` devolvido pelo Discord. Erros de permissão têm intervalo maior; erros 429 suspendem o lote e adiam a continuação. A migração `0013_lockdown_restore_retry.py` adiciona contador, próximo horário, último erro e índice para consultar restaurações pendentes.

### 4. Lembretes podiam falhar indefinidamente a cada 15 segundos

Uma entrega de lembrete com falha podia ser tentada continuamente, inclusive quando o destino era inválido ou o bot não tinha acesso.

**Correção:** as tentativas são limitadas a cinco, com atrasos crescentes. Quando o Discord retorna `RateLimited`, o worker respeita `retry_after`. Erros permanentes são encerrados e o banco preserva contador, horário e mensagem de erro. A migração `0012_reminder_delivery_retries.py` acrescenta os campos e o índice de entregas pendentes.

### 5. Sincronização de comandos slash podia ser repetida desnecessariamente

Sincronizar comandos em todo `on_ready` ou refazer servidores que já tinham sido sincronizados aumentava o volume de requisições para endpoints de comandos de aplicação.

**Correção:** os comandos locais e remotos são comparados antes do `sync`. Servidores sincronizados com sucesso são memorizados durante a execução do processo; falhas temporárias são repetidas com limite de cinco tentativas, respeitando `Retry-After` e usando espera crescente com teto de 15 minutos. As tarefas de retry são canceladas no encerramento. A falha de sincronização não impede o bootstrap do banco, e uma falha de persistência no evento de entrada de servidor não impede a tentativa de preparar os comandos.

### 6. Painel web podia consultar repetidamente a lista de servidores do Discord

Após OAuth, a próxima chamada do painel podia consultar novamente `/users/@me/guilds`. Requisições simultâneas, quando o cache expirava, também podiam causar várias consultas concorrentes.

**Correção:** o callback OAuth prepara o cache de servidores autorizados; a lista fica em cache Redis por 30 segundos. Um lock Redis com expiração faz apenas uma requisição renovar o cache por vez. Payloads de cache inválidos são removidos. Erros 429 preservam o prazo de retry no cabeçalho `Retry-After`.

### 7. Ações de comunidade geravam edições repetidas da mesma mensagem

Votos em sugestões/enquetes e entradas de sorteio podiam buscar a mensagem pública e editá-la em cada interação, mesmo em uma rajada de cliques.

**Correção:** cooldowns por usuário limitam interações repetidas; atualizações de mensagens são agrupadas por publicação e adiadas por dois segundos; a atualização usa mensagens parciais do cache do Discord, evitando um `fetch_message` extra. Tarefas pendentes são canceladas quando o cog é descarregado.

### 8. Arquivos antigos/backup

Os módulos antigos de bump dependiam de uma tabela removida por migração anterior e o projeto já tinha testes que exigiam que esses arquivos não existissem. Também foi confirmado que `app/discord/theme.py.new` estava vazio. Esses arquivos não fazem parte do pacote corrigido.

## Correções após os logs do Windows

### 9. O verificador acusava subcomandos existentes como ausentes

O log local mostrava oito subcomandos ausentes em `/admin` e `/antiraid`, apesar de o bot já ter tentado sincronizá-los. A causa era a leitura do tipo da raiz: o Discord retorna os grupos slash como comandos de tipo `1`; os tipos `1` e `2` que identificam subcomandos e grupos de subcomandos ficam nas opções internas. O verificador olhava apenas o tipo raiz e tratava `/admin` como um comando simples.

**Correção:** o parser agora detecta opções internas dos tipos `1` e `2`, monta nomes qualificados como `admin credit` e `antiraid configure` e continua reconhecendo comandos simples e comandos de contexto. Foi adicionado teste usando o formato do payload retornado pelo Discord. Isso evita sincronizações extras e elimina o falso erro de verificação mostrado no terminal.

### 10. `/ping` e aparência dos embeds

**Correção:** `/ping` responde apenas `Pong! X ms`. O padrão dos embeds não inclui GIFs, timestamps ou rodapés decorativos; os comandos mantêm somente os dados úteis à ação executada. GIFs só podem aparecer quando um comando os solicitar explicitamente com `show_gif=True`.

### 11. Avisos de suporte a voz

O aviso de `PyNaCl` e `davey` era causado pela instalação de `discord.py` sem os extras opcionais de voz. `requirements.txt` e `pyproject.toml` agora usam `discord.py[voice]==2.7.1`. Depois de atualizar o projeto, execute novamente a instalação das dependências dentro da `.venv`.

O primeiro erro do Docker mostrava que o mecanismo Linux do Docker Desktop ainda não estava disponível. A execução seguinte iniciou PostgreSQL e Redis, portanto não havia falha persistente no `docker-compose.yml`. O README agora explica como esperar o mecanismo iniciar e confirmar com `docker info`.


### 12. `/history` falhava por um helper não importado

Os logs do Windows registravam `NameError: name 'defer' is not defined` em `app/discord/cogs/utility.py`. O comando chamava `defer()` antes da consulta ao banco, mas não importava o helper. O mesmo módulo usava `respond()` em `/remind` sem importar o helper correspondente.

**Correção:** ambos os helpers são importados explicitamente. `/history` agora retorna uma lista compacta, por servidor e da mais recente para a mais antiga; falhas de consulta são registradas no log e mostradas ao usuário em uma resposta curta.

### 13. `/purge` e sincronização dos limites de opções

O limite local de `/purge` agora é de 1 a 1000 mensagens. O comando confirma as permissões `View Channel`, `Read Message History` e `Manage Messages`; falhas 429, 403 e HTTP recebem respostas curtas e registram detalhes técnicos no log. O resultado pode ser parcial se o Discord recusar a operação depois de algumas exclusões.

A causa do limite antigo no menu slash era adicional: o comparador entre comandos locais e remotos ignorava `min_value` e `max_value` dos parâmetros. Por isso, uma alteração de 100 para 1000 podia parecer “inalterada” e nunca ser sincronizada.

**Correção:** o contrato de sincronização agora compara descrição, limites numéricos, limites de texto, autocomplete, choices e tipos de canal. Uma alteração de `max_value=100` para `max_value=1000` torna a assinatura diferente e dispara sincronização.

A API permite no máximo 100 mensagens por chamada de exclusão em massa, e mensagens com mais de 14 dias não podem usar esse endpoint; o `purge` pode precisar excluir mensagens antigas individualmente. Isso significa que selecionar 1000 é um limite de mensagens a analisar/remover, não uma única chamada ao Discord. Referências: [Discord API](https://discord.com/developers/docs/resources/message#bulk-delete-messages) e [discord.py](https://discordpy.readthedocs.io/en/stable/api.html#discord.abc.Messageable.purge).

## Autenticação e autorização: verificações realizadas

- O estado OAuth é conferido e consumido no callback; a sessão usa um identificador opaco armazenado no Redis e a chave é removida quando expira ou é inválida.
- O painel verifica acesso à guilda e permissões do Discord antes de devolver dados.
- Rotas de mutação do painel verificam o token CSRF.
- A configuração de sessão usa cookie assinado, `SameSite=Lax` e `Secure` em produção; URLs de redirect/dashboard precisam de HTTPS quando `APP_ENV=production`.
- O código distingue sessão OAuth expirada, falta de permissão, indisponibilidade do Discord e rate limit.
- As políticas de permissões dos comandos e os limites de superfície de comando foram auditados; as verificações de hierarquia de cargos devem falhar de forma segura se não puderem ser confirmadas.

Não foi realizado login contra uma aplicação Discord real; portanto, a revisão de autenticação foi estática e não comprova a configuração externa do Developer Portal, scopes, intents ou URLs de produção.

## Rate limits: o que foi reduzido

- `sync()` de comandos slash só ocorre quando as assinaturas divergem.
- Retry de sincronização, restauração do Anti-Raid e entrega de lembretes é limitado e respeita `retry_after` quando disponível.
- Atualizações de mensagens de comunidade são agrupadas.
- A lista de servidores do painel recebe cache e proteção contra renovações concorrentes.
- Os cooldowns existentes usam Redis; quando Redis falha, há fallback local. Esse fallback protege uma única instância, mas não coordena várias réplicas.

O projeto não pode garantir que jamais receberá HTTP 429: os limites dependem do uso global, dos buckets da rota e de outras operações da aplicação. A recomendação é continuar usando as abstrações oficiais do `discord.py`, respeitar seus atrasos e não implementar retries imediatos fora dessas políticas. Referência: [documentação oficial de rate limits do Discord](https://discord.com/developers/docs/topics/rate-limits).

## Validação executada

- `python -m compileall -q app scripts tests`: **passou**.
- `pytest -q`: **275 testes aprovados após a limpeza**.
- `python scripts/audit.py`: **passou**.
- `python scripts/security_audit.py`: **passou**; as políticas de comandos protegidos e superfícies com rate limit foram verificadas.
- `python scripts/command_matrix.py`: **passou**, com 89 handlers auditados individualmente.
- `python -m alembic upgrade head --sql`: **passou**, gerando SQL de atualização para a cadeia completa de 13 revisões, incluindo as migrações novas.
- Importação das 54 tabelas SQLAlchemy e verificação do índice Anti-Raid: **passou**.

### Limitação do ambiente de teste

A validação estática e a suíte automatizada não substituem um teste de inicialização conectado ao Discord e aos serviços reais.

## Melhorias recomendadas

1. **CI com serviços reais:** incluir um job com PostgreSQL e Redis para aplicar todas as migrações desde a primeira revisão e testar rollback/consulta de pendências; manter outro job com as versões exatas de `requirements.txt`.
2. **Observabilidade de rate limits:** registrar endpoint/bucket, guilda, operação, status 429 e prazo de retry; criar alertas para a frequência de 429 em command sync, Anti-Raid, lembretes e mensagens de comunidade.
3. **Fila de tarefas Discord:** retirar operações de envio de dentro de transações longas do banco. Reivindicar cada lembrete em uma transação curta, enviar fora dela e persistir o resultado em outra transação, com idempotência para reduzir risco de entrega duplicada.
4. **HTTPX com ciclo de vida FastAPI:** reutilizar um `AsyncClient` por processo para OAuth e chamadas ao Discord, com fechamento no shutdown, em vez de criar um cliente para cada operação. Isso reduz conexões e handshakes; não substitui rate limiting.
5. **Cooldowns distribuídos:** se forem adicionadas várias réplicas do bot, manter cooldowns e fila de atualizações no Redis com locks distribuídos; o fallback local atual não coordena instâncias diferentes.
6. **Proteção de login:** aplicar rate limit a `/auth/login` e registrar tentativas anômalas, considerando o proxy confiável da hospedagem antes de usar IP como chave.
7. **Testes de contrato de APIs:** usar mocks HTTP explícitos para respostas 401, 403, 429, 5xx, JSON inválido, expiração de sessão e recuperação de cache; manter testes de permissões em comandos de moderação.
8. **Retenção e privacidade:** definir políticas de expiração/remoção para auditoria, denúncias, transcrições de tickets e metadados da comunidade.
