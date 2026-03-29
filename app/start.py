import asyncio
import time

from classes.bybit_client.bybit_client import BybitClient
from config import DASHBOARD_ENABLED
from classes.logging.logger import setup_logger, get_source_logger
from classes.reporting.health_state import touch
from classes.reporting.storage import Storage
from classes.telegram.telegram_client import TelegramService
from classes.trade_manager.execution import ExecutionService
from classes.trade_manager.order_watcher import OrderWatcher
from classes.trade_manager.reconciliation import Reconciliation
from classes.trade_manager.worker import Worker
from classes.webui.ui import DashboardService

HEARTBEAT_INTERVAL_SEC = 10
SYNC_LOOP_INTERVAL_SEC = 5
BALANCE_SNAPSHOT_INTERVAL_SEC = 15
EXCHANGE_HISTORY_SYNC_INTERVAL_SEC = 300


async def main():
    base_logger = setup_logger()
    bot_logger = get_source_logger(base_logger, "Bot")
    telegram_logger = get_source_logger(base_logger, "Telegram")

    storage = Storage()
    bybit = BybitClient(logger=bot_logger, storage=storage)
    execution = ExecutionService(bybit, storage, bot_logger)

    worker = Worker(bybit, storage, execution, bot_logger)
    watcher = OrderWatcher(bybit, storage, bot_logger)

    reconciliation = Reconciliation(bybit, storage, bot_logger)

    telegram = TelegramService(worker, telegram_logger, storage=storage)
    dashboard = DashboardService(bybit, storage, bot_logger) if DASHBOARD_ENABLED else None
    last_settings_revision = storage.get_settings_revision()
    runtime_ready = bool(getattr(bybit, "client", None) is not None and telegram.is_enabled)
    restart_requested = asyncio.Event()
    bot_logger.info("Bot started")
    if not runtime_ready:
        bot_logger.warning(
            "Bot is paused because required settings are incomplete; fill Bybit and Telegram settings in the UI to start runtime"
        )
        touch(
            "app",
            telegram_enabled=telegram.is_enabled,
            scanner_enabled=False,
        )

    async def heartbeat_loop():
        while True:
            try:
                await asyncio.to_thread(touch, "app", telegram_enabled=telegram.is_enabled)
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            except Exception as e:
                bot_logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

    async def sync_loop():
        last_balance_snapshot_at = 0.0
        last_transaction_sync_at = 0.0
        while True:
            try:
                if not runtime_ready:
                    await asyncio.sleep(SYNC_LOOP_INTERVAL_SEC)
                    continue
                current_settings_revision = storage.get_settings_revision()
                if current_settings_revision and current_settings_revision != last_settings_revision:
                    bot_logger.warning("Settings changed; restarting bot to apply updates")
                    restart_requested.set()
                    return

                await asyncio.to_thread(bybit.ping)
                await asyncio.to_thread(reconciliation.sync)
                now = time.monotonic()
                if now - last_balance_snapshot_at >= BALANCE_SNAPSHOT_INTERVAL_SEC:
                    summary = await asyncio.to_thread(bybit.get_account_summary)
                    await asyncio.to_thread(storage.record_balance_snapshot, summary)
                    last_balance_snapshot_at = now
                if now - last_transaction_sync_at >= EXCHANGE_HISTORY_SYNC_INTERVAL_SEC:
                    await asyncio.to_thread(bybit.sync_transaction_history, storage)
                    await asyncio.to_thread(bybit.sync_execution_history, storage)
                    await asyncio.to_thread(bybit.sync_closed_pnl_history, storage)
                    last_transaction_sync_at = now
                await asyncio.sleep(SYNC_LOOP_INTERVAL_SEC)
            except Exception as e:
                bot_logger.error(str(e))
                await asyncio.sleep(SYNC_LOOP_INTERVAL_SEC)

    tasks = [
        asyncio.create_task(heartbeat_loop()),
    ]

    if runtime_ready:
        tasks.append(asyncio.create_task(watcher.watch()))
        tasks.append(asyncio.create_task(sync_loop()))
    else:
        bot_logger.warning("Trading runtime is paused until the UI settings are completed")

    if telegram.is_enabled and runtime_ready:
        tasks.append(asyncio.create_task(telegram.start()))
    else:
        if not telegram.is_enabled:
            bot_logger.warning("Telegram task disabled; running without Telegram integration")

    if dashboard:
        tasks.append(asyncio.create_task(dashboard.run()))
        bot_logger.info("Dashboard enabled")

    await restart_requested.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return


if __name__ == "__main__":
    bootstrap_logger = get_source_logger(setup_logger(), "Bot")
    try:
        asyncio.run(main())
    except Exception as e:
        bootstrap_logger.critical(f"Bot crashed at top level: {e}")
        raise
