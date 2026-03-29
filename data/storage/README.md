# storage

This directory stores runtime state, exchange sync caches, and Telegram session data.

Typical contents:
- `trades.json`
- `balance_history.json`
- `transaction_history.json`
- `history.sqlite3`
- `healthcheck.json`
- `session.session`

What goes here:
- local bot trade state used for execution and reconciliation;
- local balance/equity snapshots;
- imported Bybit transaction history;
- SQLite cache for exchange-backed dashboard history;
- healthcheck timestamps;
- Telethon session files.

Important note:
- dashboard balances, active trades, closed trades, and performance metrics are exchange-first;
- local files here support runtime flow and enrichment, but are no longer the portfolio source of truth.

What to do with it:
- keep it out of git;
- treat session files and runtime data as private;
- back up only if you need to preserve local bot state;
- deleting these files may reset local context or require Telegram re-login.

This directory is intentionally kept in git only as a documented placeholder.
