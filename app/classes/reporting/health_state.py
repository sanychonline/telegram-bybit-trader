import json
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_HEALTHCHECK_PATH

HEALTHCHECK_PATH = Path(DATA_HEALTHCHECK_PATH)


def touch(component, **extra):
    HEALTHCHECK_PATH.parent.mkdir(parents=True, exist_ok=True)

    payload = {}
    if HEALTHCHECK_PATH.exists():
        try:
            payload = json.loads(HEALTHCHECK_PATH.read_text())
        except Exception:
            payload = {}

    now = datetime.now(timezone.utc).isoformat()
    payload["status"] = "ok"
    payload["updated_at"] = now
    payload[f"{component}_alive_at"] = now

    for key, value in extra.items():
        payload[key] = value

    HEALTHCHECK_PATH.write_text(json.dumps(payload))
