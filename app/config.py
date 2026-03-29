import os


def get_env(name, default=None, required=False, cast=None):
    value = os.getenv(name, default)

    if required and value is None:
        raise ValueError(f"Missing required env variable: {name}")

    if cast and value is not None:
        try:
            return cast(value)
        except Exception:
            raise ValueError(f"Invalid value for {name}: {value}")

    return value


DATA_DIR = get_env("DATA_DIR", "/opt/bot/data")
DATA_CACHES_DIR = f"{DATA_DIR}/caches"
DATA_REPORTS_DIR = f"{DATA_DIR}/reports"
DATA_STORAGE_DIR = f"{DATA_DIR}/storage"

TZ = get_env("TZ", "UTC")
BRAND_NAME = get_env("BRAND_NAME", required=True)
DISCLAIMER_TEXT = get_env("DISCLAIMER_TEXT", required=True)
LOG_TO_FILE = get_env("LOG_TO_FILE", "false").lower() == "true"
LOG_LEVEL = get_env("LOG_LEVEL", "INFO").upper()
LOG_MAX_BYTES = get_env("LOG_MAX_BYTES", 20 * 1024 * 1024, cast=int)
LOG_BACKUP_COUNT = get_env("LOG_BACKUP_COUNT", 10, cast=int)

BYBIT_API_KEY = get_env("BYBIT_API_KEY", required=True)
BYBIT_API_SECRET = get_env("BYBIT_API_SECRET", required=True)
BYBIT_TESTNET = get_env("BYBIT_TESTNET", "true").lower() == "true"

TELEGRAM_API_ID = get_env("TELEGRAM_API_ID", required=True, cast=int)
TELEGRAM_API_HASH = get_env("TELEGRAM_API_HASH", required=True)
TELEGRAM_CHAT_ID = get_env("TELEGRAM_CHAT_ID", required=True, cast=int)

DASHBOARD_ENABLED = get_env("DASHBOARD_ENABLED", "false").lower() == "true"
DASHBOARD_HOST = get_env("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = 1002
DASHBOARD_REFRESH_SEC = get_env("DASHBOARD_REFRESH_SEC", 5, cast=int)

MAX_POSITION_MULTIPLIER = get_env("MAX_POSITION_MULTIPLIER", 1.0, cast=float)
MAX_ENTRY_DEVIATION_PCT = get_env("MAX_ENTRY_DEVIATION_PCT", 0.03, cast=float)
MAX_SIGNAL_DESYNC_PCT = get_env("MAX_SIGNAL_DESYNC_PCT", 0.015, cast=float)
EMERGENCY_TP_PCT = get_env("EMERGENCY_TP_PCT", 0.03, cast=float)
PENDING_ENTRY_TIMEOUT_SEC = get_env("PENDING_ENTRY_TIMEOUT_SEC", 900, cast=int)
