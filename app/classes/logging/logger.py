import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
from config import DATA_REPORTS_DIR, TZ, LOG_TO_FILE, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT
import pytz


class TZFormatter(logging.Formatter):
    def __init__(self, tz):
        super().__init__()
        try:
            self.tz = pytz.timezone(tz)
        except Exception:
            self.tz = pytz.UTC

    def format(self, record):
        dt = datetime.fromtimestamp(record.created, self.tz)
        record.asctime = dt.strftime("%Y-%m-%d %H:%M:%S")
        source = getattr(record, "source", "Bot")
        return f"{record.asctime} | {record.levelname} | {source} | {record.getMessage()}"


def get_source_logger(logger, source):
    return logging.LoggerAdapter(logger, {"source": source})


def _resolve_log_level():
    return getattr(logging, LOG_LEVEL, logging.INFO)


def setup_logger():
    logger = logging.getLogger("bot")
    logger.setLevel(_resolve_log_level())
    logger.propagate = False

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = TZFormatter(TZ)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(_resolve_log_level())
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if LOG_TO_FILE:
        os.makedirs(DATA_REPORTS_DIR, exist_ok=True)

        file_handler = RotatingFileHandler(
            f"{DATA_REPORTS_DIR}/bot.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(_resolve_log_level())
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
