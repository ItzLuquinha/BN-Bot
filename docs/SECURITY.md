# Security model

## Authentication

The dashboard uses Discord OAuth2 with a server-generated state value. The browser stores only an opaque dashboard session identifier inside the signed Starlette session cookie. The Discord access token is stored server-side in Redis and expires with the OAuth token lifetime.

## Authorization

Dashboard requests resolve the requested guild against Discord guild permissions before reading or mutating persistent server data. Discord commands also use Discord permission checks at the interaction layer.

## CSRF

The dashboard issues a per-session CSRF token. Logout checks it through a form field. JSON mutations check it through the `X-CSRF-Token` header.

## Economy integrity

Financial operations use PostgreSQL transactions. Sender and receiver accounts are locked in deterministic ID order for transfers. Purchase operations lock the shop item, account and inventory row before changing balances and stock.

## Secrets

Secrets belong in environment variables. Source files contain no token values. Logging excludes authentication secrets by design.

## Privacy

Message analytics stores message identifiers and content length, not message bodies. Retention policies should be configured before storing expanded moderation or message content in later modules.


## Anti-Raid safety rules

Anti-Raid never acts on the server owner, configured bypass users or configured trusted roles. Risk scoring is deterministic and combines entry bursts with the proportion and age of recent accounts. A score alone does not permanently ban members. The `block` response is an explicit server configuration. Lockdown stores the prior @everyone overwrite before changing `send_messages` and restores that stored state when the protection window ends.
