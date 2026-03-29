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
- runtime bot state
- execution/order enrichment
- healthchecks and logs
- encrypted app secrets

It is no longer treated as the source of truth for portfolio history or closed-trade statistics.

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

## Data Directory Guide

`data`
- `history.sqlite3`
  - primary local storage for bot trades, signal events, exchange sync history, balance snapshots, runtime settings, and encrypted secrets metadata
- `trades.json`
  - legacy-compatible trade state snapshot used by the storage layer
- `balance_history.json`
  - exchange-backed balance history exported for the dashboard
- `transaction_history.json`
  - exchange-backed transaction history exported for the dashboard
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
