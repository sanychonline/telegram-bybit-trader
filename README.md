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
- dashboard sync caches

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
- `data/reports`
- `data/storage`
- `data/caches`

## Quick Start

1. Create `.env` from `.env.default`

```bash
cp .env.default .env
```

2. Fill required secrets:
- `BYBIT_API_KEY`
- `BYBIT_API_SECRET`
- `BYBIT_TESTNET`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_CHAT_ID`

3. Start the stack:

```bash
docker compose up --build -d
```

4. Watch the bot:

```bash
docker compose logs -f bot
```

5. Open the dashboard:

```text
http://<host>:1002/
```

## Dashboard Truth Model

The dashboard is intentionally exchange-driven.

Exchange-sourced:
- balances
- equity
- balance curve
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

`data/storage`
- `trades.json`
  - local runtime trade state used by the bot
- `transaction_history.json`
  - imported Bybit transaction history used for balance history reconstruction
- `balance_history.json`
  - local balance/equity snapshots
- `history.sqlite3`
  - exchange history cache for dashboard analytics
- `healthcheck.json`
  - liveness state for container healthchecks
- `session.session`
  - Telegram session

`data/reports`
- `bot.log`
  - runtime logs
- `report.csv`
  - local execution report; useful for debugging, but not the dashboard source of truth

`data/caches`
- rebuildable caches and temporary historical artifacts

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

- Start with `BYBIT_TESTNET=true` if you are validating a new setup.
- The dashboard may briefly show sync-in-progress states while exchange history is being backfilled.
- Runtime JSON files are still useful operationally, but portfolio truth for the UI now comes from Bybit.
