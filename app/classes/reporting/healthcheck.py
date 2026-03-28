import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import DATA_STORAGE_DIR


HEALTHCHECK_PATH = Path(DATA_STORAGE_DIR) / "healthcheck.json"
MAX_APP_AGE_SECONDS = 30
MAX_TELEGRAM_AGE_SECONDS = 90
MAX_BYBIT_AGE_SECONDS = 90
MAX_WATCHER_AGE_SECONDS = 30
MAX_RECONCILIATION_AGE_SECONDS = 30


def _parse_iso(value):
    updated_at = datetime.fromisoformat(value)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return updated_at


def _ensure_fresh(payload, field, max_age_seconds):
    if field not in payload:
        sys.exit(1)

    updated_at = _parse_iso(payload[field])
    if datetime.now(timezone.utc) - updated_at > timedelta(seconds=max_age_seconds):
        sys.exit(1)


def main():
    if not HEALTHCHECK_PATH.exists():
        sys.exit(1)

    try:
        payload = json.loads(HEALTHCHECK_PATH.read_text())
    except Exception:
        sys.exit(1)

    _ensure_fresh(payload, "updated_at", MAX_APP_AGE_SECONDS)
    _ensure_fresh(payload, "telegram_alive_at", MAX_TELEGRAM_AGE_SECONDS)
    _ensure_fresh(payload, "bybit_alive_at", MAX_BYBIT_AGE_SECONDS)
    _ensure_fresh(payload, "watcher_alive_at", MAX_WATCHER_AGE_SECONDS)
    _ensure_fresh(payload, "reconciliation_alive_at", MAX_RECONCILIATION_AGE_SECONDS)

    sys.exit(0)


if __name__ == "__main__":
    main()
