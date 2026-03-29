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
- local encryption key for app secrets;
- healthcheck timestamps;
- Telethon session files;
- runtime logs;
- runtime exchange-sync and dashboard state.

Important note:
- dashboard balances, active trades, closed trades, and performance metrics are exchange-first;
- SQLite is the primary local storage layer for runtime flow and enrichment.

What to do with it:
- keep it out of git;
- treat session files and runtime data as private;
- back up only if you need to preserve local bot state;
- deleting these files may reset local context or require Telegram re-login.

Git hygiene:
- `data/*` is ignored by the repository except for this README;
- do not add `traderbot.sqlite3`, `secrets.key`, `*.session`, or logs to commits;
- if you need to export state, do it outside the repository tree.
