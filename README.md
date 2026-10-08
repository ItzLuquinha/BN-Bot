# BN Bot

Discord bot for server management, moderation, community features, economy and entertainment.

## Discord App Install

The BN Bot supports two Discord installation modes. Guild Install adds the bot as a member of a server and enables server-dependent features. User Install adds the app to a user's account and exposes the commands that can operate without the bot being installed as a server member.

Safe User Install commands are `/ping`, `/uptime`, `/botinfo`, `/avatar`, `/tutorial`, `/coinflip`, `/dice`, `/rps` and `/eightball`. Moderation, administration, tickets, AutoMod, Anti-Raid and server-dependent economy commands remain Guild Install only.

To enable User Install in Discord, open the application's Installation settings in the Developer Portal and enable User Install. Keep Guild Install enabled for normal bot installation. Use the Discord-provided install link or configure the default install settings for both contexts.

When a user sends the bot a DM, BN Bot answers with an installation card containing links for adding the bot to a server or installing the application directly to the user's account. The DM flow is rate limited per user.

## Running

Use Python 3.12 or newer and install the dependencies from `requirements.txt`. Configure the environment variables described by `.env.example`.
