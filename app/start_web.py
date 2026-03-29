import asyncio

from classes.bybit_client.bybit_client import BybitClient
from classes.logging.logger import get_source_logger, setup_logger
from classes.reporting.storage import Storage
from classes.webui.ui import DashboardService


async def main():
    base_logger = setup_logger()
    web_logger = get_source_logger(base_logger, "Web")

    storage = Storage()
    bybit = BybitClient(logger=web_logger, storage=storage)
    dashboard = DashboardService(bybit, storage, web_logger)

    web_logger.info("Trader web started")
    await dashboard.run()


if __name__ == "__main__":
    bootstrap_logger = get_source_logger(setup_logger(), "Web")
    try:
        asyncio.run(main())
    except Exception as e:
        bootstrap_logger.critical(f"Trader web crashed at top level: {e}")
        raise
