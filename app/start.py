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

    bybit = BybitClient(logger=bot_logger)
    storage = Storage()
    execution = ExecutionService(bybit, storage, bot_logger)

    worker = Worker(bybit, storage, execution, bot_logger)
    watcher = OrderWatcher(bybit, storage, bot_logger)

    reconciliation = Reconciliation(bybit, storage, bot_logger)

    telegram = TelegramService(worker, telegram_logger)
    dashboard = DashboardService(bybit, storage, bot_logger) if DASHBOARD_ENABLED else None
    bot_logger.info("Bot started")

    async def heartbeat_loop():
        while True:
            try:
                await asyncio.to_thread(touch, "app")
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            except Exception as e:
                bot_logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

    async def sync_loop():
        last_balance_snapshot_at = 0.0
        last_transaction_sync_at = 0.0
        while True:
            try:
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
        heartbeat_loop(),
        telegram.start(),
        watcher.watch(),
        sync_loop(),
    ]

    if dashboard:
        tasks.append(dashboard.run())
        bot_logger.info("Dashboard enabled")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    bootstrap_logger = get_source_logger(setup_logger(), "Bot")
    try:
        asyncio.run(main())
    except Exception as e:
        bootstrap_logger.critical(f"Bot crashed at top level: {e}")
        raise
