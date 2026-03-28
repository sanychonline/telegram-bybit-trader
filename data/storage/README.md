# storage

This directory stores local runtime state and Telegram-related data.

Typical contents:
- `messages.json`
- `trades.json`
- `healthcheck.json`
- `session.session`

What goes here:
- exported Telegram channel history;
- local bot trade state;
- healthcheck state files;
- Telethon session files.

What to do with it:
- treat session files and message exports as private data;
- do not commit personal runtime data;
- back up only if you explicitly need to preserve local state;
- deleting these files may reset bot state or require Telegram re-login.

This directory is intentionally kept in git only as a documented placeholder.
