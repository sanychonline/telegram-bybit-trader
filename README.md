# Trader Bot

`trader-bot` reads trading signals from Telegram, executes them on Bybit, manages protection orders, and exposes a web dashboard.

## Current Architecture

The project now has a clear split:
- bot execution flow is local:
  - Telegram parsing
  - signal validation
  - order placement
  - trade lifecycle management
- account state and dashboard metrics are exchange-first:
  - balances and equity come from Bybit wallet/account endpoints
  - active trades come from Bybit open positions and open reduce-only orders
  - closed trades and performance stats come from Bybit `closed-pnl`
  - TP/SL hit counts are enriched from Bybit execution history

Local storage is still used for:
- Telegram session state
- Telegram message registry and history sync metadata
- runtime bot state
- execution/order enrichment
- healthchecks and logs
- encrypted app secrets

It is no longer treated as the source of truth for portfolio history or closed-trade statistics.
Telegram history sync now uses a two-layer approach:
- first it inventories known Telegram message IDs into SQLite;
- then it backfills only the missing messages on startup.

## Services

`docker compose` starts two services:
- `bot`
  - Telegram listener, trade execution, reconciliation, exchange sync loops
- `web`
  - dashboard HTTP server

## Important Files

Main entrypoints:
- `app/start.py`
- `app/start_web.py`

Core modules:
- `app/classes/bybit_client/bybit_client.py`
- `app/classes/trade_manager/worker.py`
- `app/classes/trade_manager/order_watcher.py`
- `app/classes/trade_manager/reconciliation.py`
- `app/classes/reporting/dashboard_data.py`
- `app/classes/reporting/storage.py`

Runtime data:
- `data`

## Quick Start

1. Create `.env` from `.env.default`

```bash
cp .env.default .env
```

2. Keep only bootstrap settings in `.env`
- `DATA_DIR`
- `TZ`
- logging settings such as `LOG_LEVEL`

3. Start the stack once:

```bash
docker compose up --build -d
```

4. Open the dashboard settings and fill integrations there:
- Bybit API key / secret
- Bybit testnet toggle
- Telegram API id / hash
- Telegram chat id
- execution and dashboard settings

All runtime settings are stored in SQLite. Secrets are stored encrypted in the DB, with a local encryption key file in `data/secrets.key`.
If the required settings are still empty at startup, the bot stays in maintenance mode and logs a warning until you complete the UI form.

5. Watch the bot:

```bash
docker compose logs -f bot
```

6. Open the dashboard:

```text
http://<host>:1002/
```

## Dashboard Truth Model

The dashboard is intentionally exchange-driven.

Exchange-sourced:
- balances
- equity
- balance history
- active trades
- closed trades
- wins / losses / breakevens
- realized / unrealized PnL
- winrate / non-loss rate

Exchange-derived from multiple Bybit endpoints:
- close reason
- TP hits
- SL hits

Bot-local only:
- Telegram processing
- signal parsing
- trade execution flow
- local reconciliation and enrichment context

The dashboard also includes a live signal ticker:
- shows the last 10 signals from the local signal event log
- displays only the time, not the date
- uses `🟢` / `🔴` for LONG / SHORT
- shows `👍` if the related trade closed in profit
- shows `😢` if the related trade closed in loss
- keeps the ticker moving right-to-left in a continuous loop at a fixed speed
- does not pause on hover, so the motion stays smooth during inspection

Active trades keep the order in which they first appeared, so the table does not reshuffle on every refresh.

The dashboard theme toggle follows the system `prefers-color-scheme` setting in real time when `auto` is selected.
In the compact control block, `auto` is shown as a simple `A` so the theme and language buttons keep the same visual weight across layouts.

The Telegram sync state is tracked in SQLite too:
- `telegram.history_sync.status`
- `telegram.history_sync.started_at`
- `telegram.history_sync.finished_at`
- `telegram.history_sync.synced_count`
- `telegram.history_sync.processed_count`
The startup sync is user-session aware, while live Telegram runtime keeps running through the configured integration once settings are complete.

## Internal Backtest API

`trader-bot` exposes bearer-protected read-only endpoints for workspace tooling:
- `GET /api/backtest/telegram-messages`
- `GET /api/backtest/signal-events`
- `GET /api/backtest/exchange-closed-trades`
- `GET /api/backtest/bot-trades`

All endpoints require the shared `internal_api_token` stored in `app_secrets` and sent as `Authorization: Bearer <token>`.
The token itself is managed in the dashboard settings and persisted encrypted in SQLite.
`/api/backtest/telegram-messages` is the full Telegram archive used as the knowledge source for API-only backtests.

## Data Directory Guide

`data`
- `traderbot.sqlite3`
  - primary local storage for bot trades, signal events, exchange sync history, balance snapshots, runtime settings, and encrypted secrets metadata
  - includes `telegram_message_registry` and `sync_state` metadata for Telegram history sync
- `secrets.key`
  - local encryption key for app secrets stored in SQLite
- `healthcheck.json`
  - liveness state for container healthchecks
- `session.session`
  - Telegram session
- `session.session-journal`
  - Telethon session journal
- `bot.log`
  - runtime logs

## Healthchecks

The `bot` container healthcheck runs:

```bash
python -m classes.reporting.healthcheck
```

It validates recent heartbeats from:
- app loop
- Telegram
- Bybit
- watcher
- reconciliation

## Notes

- Start with Bybit testnet enabled in the dashboard settings if you are validating a new setup.
- The dashboard may briefly show sync-in-progress states while exchange history is being backfilled.
- Legacy JSON files can be imported once during migration, but the live app now persists runtime state in SQLite.
- Runtime secrets, sessions, logs, and SQLite files are ignored by git and should stay out of commits.
- If the dashboard settings are incomplete, the bot intentionally logs that it is in maintenance mode and waits for configuration before starting the runtime loops.
