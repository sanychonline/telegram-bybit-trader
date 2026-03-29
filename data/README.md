# data

This directory stores all runtime state for `trader-bot` directly in the root.

Typical files:
- `traderbot.sqlite3`
- `secrets.key`
- `healthcheck.json`
- `session.session`
- `session.session-journal`
- `bot.log`

What goes here:
- SQLite storage for local bot trade state, balance snapshots, signal events, exchange sync history, runtime settings, and encrypted secrets;
- Telegram message registry and history sync metadata used for startup backfill and cleanup;
- `telegram_messages` table - full Telegram archive used as the knowledge source for backtests and history sync;
- `internal_api_token` in `app_secrets` - bearer token for workspace backtest and other internal API reads;
- local encryption key for app secrets;
- healthcheck timestamps;
- Telethon session files;
- runtime logs;
- runtime exchange-sync and dashboard state.

Important note:
- dashboard balances, active trades, closed trades, and performance metrics are exchange-first;
- SQLite is the primary local storage layer for runtime flow and enrichment.
- Telegram startup sync is two-layered: first we track known message IDs, then we backfill only missing messages.
- If required UI settings are missing, the bot starts in maintenance mode and waits for configuration before runtime loops begin.

What to do with it:
- keep it out of git;
- treat session files and runtime data as private;
- back up only if you need to preserve local bot state;
- deleting these files may reset local context or require Telegram re-login.

Git hygiene:
- `data/*` is ignored by the repository except for this README;
- do not add `traderbot.sqlite3`, `secrets.key`, `*.session`, or logs to commits;
- do not add Telegram registry exports or sync artifacts to commits;
- if you need to export state, do it outside the repository tree.
