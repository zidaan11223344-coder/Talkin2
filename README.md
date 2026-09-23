# TalkinChat V22 - Giant assets + points + masters + VIP + publishing

Railway variables (required):
- BOT_ID
- BOT_PWD
- GROUP_TO_JOIN

Optional:
- BOT_MASTER
- YOUTUBE_COOKIES (optional but recommended for YouTube)
- PUBLIC_BASE_URL (optional; RAILWAY_PUBLIC_DOMAIN is preferred automatically)
- GIFT_PUBLIC_BASE_URL (optional fallback public URL)
- PIPED_APIS (optional comma-separated Piped API instances; auto-discovery is attempted)
- MUSIC_MAX_SECONDS=900
- MUSIC_COOLDOWN=15

Local data files:
- `verified_users.json` — verified accounts allowed to use normal commands.
- `vip_users.json` — VIP accounts, also treated as verified.
- `auto_replies.json` — persistent automatic replies.
- `custom_welcomes.json` — persistent custom welcomes.

Commands:
- .sa SONG NAME
- sa@GIFT_NUMBER@USERNAME
- دخول ROOM
- خروج ROOM
- خروج
- انشر
- انشر@DESCRIPTION (then send image)
- sb@USERNAME@POINTS (master)
- mas@USERNAME (owner)
- umas@USERNAME (owner)
- s@USERNAME (master)
- ازالة توثيق@USERNAME (master)
- Vip@USERNAME (master)
- unVip@USERNAME (master)
- اوامر
- نقاطي / توب
- i@USERNAME — send a private invitation to one user (master only)
- توثيق الكل — verify users found in all connected rooms (BOT_MASTER only)

The Giant Chat messages.json is included and used for message templates. Giant assets are copied verbatim under assets/.
