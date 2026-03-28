import asyncio

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
                await asyncio.sleep(10)
            except Exception as e:
                bot_logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(10)

    async def sync_loop():
        while True:
            try:
                await asyncio.to_thread(bybit.ping)
                await asyncio.to_thread(reconciliation.sync)
                await asyncio.sleep(5)
            except Exception as e:
                bot_logger.error(str(e))
                await asyncio.sleep(5)

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
