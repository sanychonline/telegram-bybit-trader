# Trader Bot

## What this project is

`trader-bot` is a standalone Telegram-to-Bybit execution bot.

It is responsible for:
- listening to a Telegram channel with trading signals;
- parsing `LONG/SHORT`, `entry`, `SL`, and `TP`;
- validating and sizing trusted signals;
- placing orders on Bybit;
- managing trades after entry;
- reacting to follow-up events such as `TP` replies and `BE` / breakeven moves;
- storing local trade state;
- writing logs and CSV reports;
- exposing an optional live dashboard for account and trade monitoring.

Main entry point:
- `app/main.py`

Runtime data layout:
- `data/caches` — rebuildable caches
- `data/reports` — logs and CSV reports
- `data/storage` — `trades`, `session`, healthcheck, local state

## Setup

### 1. Create `.env`

The project includes:
- `.env.default`

Create your working config:

```bash
cp .env.default .env
```

Then fill in:
- `BYBIT_API_KEY`
- `BYBIT_API_SECRET`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_CHAT_ID`
- `BRAND_NAME` — your project / dashboard brand label, for example `DUMMY PROJECT`

### 2. Telegram session

Telethon stores the session here:
- `data/storage/session.session`

On first successful login the file will be created automatically.

### 3. Important `.env` variables

- `DATA_DIR` — container path for mounted local `./data`
- `TZ` — timezone used in logs
- `BRAND_NAME` — your visible project brand used in the dashboard title, footer, and browser tab label
- `LOG_TO_FILE` — whether to write `data/reports/bot.log`
- `LOG_LEVEL` — `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`
- `LOG_MAX_BYTES` — max size of a single log file before rotation
- `LOG_BACKUP_COUNT` — number of rotated log files to keep
- `BYBIT_TESTNET` — `true` for testnet, `false` for prod
- `DASHBOARD_ENABLED` — enable built-in trader dashboard
- `DASHBOARD_HOST` — bind address for the dashboard web server
- `DASHBOARD_PORT` — dashboard port, default `1002`
- `DASHBOARD_REFRESH_SEC` — auto-refresh interval for dashboard data
- `MAX_POSITION_MULTIPLIER` — exposure cap relative to balance

## Run

Start:

```bash
docker compose up --build -d
```

Stop:

```bash
docker compose down
```

Logs:

```bash
docker compose logs -f bot
```

Dashboard:

```bash
http://localhost:1002/
```

The UI container starts together with the backend. The actual dashboard must still be enabled with:
- `DASHBOARD_ENABLED=true` in `.env`

## How it works

Flow:
- Telegram messages enter through `app/classes/telegram/telegram_client.py`
- parsing is handled in `app/classes/telegram/parser.py`
- messages are processed in `app/classes/trade_manager/worker.py`
- signal validation and sizing happen in `app/classes/trade_manager/execution.py`
- orders are sent through `app/classes/bybit_client/bybit_client.py`
- trade lifecycle handling is done in `app/classes/trade_manager/order_watcher.py`
- reconciliation is done in `app/classes/trade_manager/reconciliation.py`
- local state is stored in `app/classes/reporting/storage.py`

Behavior notes:
- the bot only processes new live Telegram messages after startup; it does not replay old chat history;
- the same symbol is locked while an entry order or open position already exists;
- partial fills are protected immediately, without waiting for full fill;
- repeated protection failures escalate into an emergency abort to avoid leaving positions unprotected;
- the project is split into separate backend and UI containers, so restarting the dashboard no longer restarts the trading bot itself.

## Runtime outputs

- bot log: `data/reports/bot.log`
  size-based rotation is enabled through `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT`
- closed trade report: `data/reports/report.csv`
- local active/history state: `data/storage/trades.json`
- functional health state: `data/storage/healthcheck.json`
- Telethon session: `data/storage/session.session`

## Dashboard

When `DASHBOARD_ENABLED=true`, the project runs:
- `bot` — trade execution backend
- `ui` — dashboard container that proxies requests to the backend API

The trader dashboard on `DASHBOARD_PORT` shows:
- account metrics: available balance, wallet balance, equity;
- trade metrics: open trades, closed trades, wins, losses, winrate, non-loss rate, total `TP hits`, and `SL hits`;
- PnL metrics: realized and unrealized PnL;
- active and closed trade tables;
- balance curve with a shared range filter:
  `today`, `current month`, `month`, `previous month`, `half of year`, `year`, `previous year`, `all time`.

The page auto-refreshes without full reload using the internal JSON API.

Current dashboard behavior:
- desktop and mobile layouts are handled automatically;
- tables collapse into mobile-friendly card rows on narrow screens;
- the balance chart supports hover inspection with a moving marker, vertical guide line, and balance/time tooltip;
- the default stats period is `current month`;
- active trades include a compact `Health` indicator:
  `SL -> BE -> next TP`, with a moving dot based on the latest price;
- active trades show both already realized profit and still-floating unrealized profit;
- trades that are not yet open show `PENDING` instead of a live health rail.

## Logging

Recommended levels:
- `DEBUG` — full routing, skip reasons, sync details, and diagnostics
- `INFO` — business events such as accepted signals, fills, protection syncs, and closes
- `WARNING` — events that need attention but do not stop the service
- `ERROR` — operation-level failures
- `CRITICAL` — top-level crashes or dangerous states such as failed emergency exits

If `LOG_TO_FILE=true`, the bot writes both to Docker logs and to `data/reports/bot.log`.

## Disclaimer

This project is provided "as is", without any warranty of correctness, profitability, or fitness for a particular purpose.

Using this bot for exchange trading involves financial risk, including partial or total loss of funds. All decisions regarding setup, launch, testnet or production use, and all trading results are entirely the responsibility of the person running the system.

The authors, contributors, and anyone involved in development or setup are not responsible for:
- financial losses;
- missed profits;
- order execution errors;
- failures of the exchange, Telegram, network, Docker, VPS/NAS, or local environment;
- incorrect user configuration, credentials, or runtime setup.

Before using the bot with real funds, it is strongly recommended to:
- validate the logic on testnet;
- test the system with small amounts;
- independently verify signal quality, risk management, and runtime behavior.
