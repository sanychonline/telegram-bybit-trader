import json
import os
import sqlite3
import threading
import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from uuid import uuid4
from config import (
    DATA_DIR,
    DATA_TRADES_PATH,
    DATA_BALANCE_HISTORY_PATH,
    DATA_TRANSACTION_HISTORY_PATH,
    DATA_HISTORY_DB_PATH,
    DATA_SECRETS_KEY_PATH,
    TZ,
    BYBIT_API_KEY,
    BYBIT_API_SECRET,
    BYBIT_TESTNET,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_CHAT_ID,
    INTERNAL_API_TOKEN,
    DASHBOARD_REFRESH_SEC,
    MAX_POSITION_MULTIPLIER,
    MAX_ENTRY_DEVIATION_PCT,
    MAX_SIGNAL_DESYNC_PCT,
    EMERGENCY_TP_PCT,
    PENDING_ENTRY_TIMEOUT_SEC,
)

BALANCE_HISTORY_LIMIT = 10000
TRANSACTION_HISTORY_LIMIT = 50000
APP_SETTINGS_SCHEMA = {
    "tz": {"type": "str", "default": TZ},
    "dashboard_refresh_sec": {"type": "int", "default": DASHBOARD_REFRESH_SEC},
    "bybit_testnet": {"type": "bool", "default": BYBIT_TESTNET},
    "telegram_chat_id": {"type": "int", "default": TELEGRAM_CHAT_ID},
    "max_position_multiplier": {"type": "float", "default": MAX_POSITION_MULTIPLIER},
    "max_entry_deviation_pct": {"type": "float", "default": MAX_ENTRY_DEVIATION_PCT},
    "max_signal_desync_pct": {"type": "float", "default": MAX_SIGNAL_DESYNC_PCT},
    "emergency_tp_pct": {"type": "float", "default": EMERGENCY_TP_PCT},
    "pending_entry_timeout_sec": {"type": "int", "default": PENDING_ENTRY_TIMEOUT_SEC},
}
APP_SECRETS_SCHEMA = {
    "bybit_api_key": {"type": "str", "default": BYBIT_API_KEY},
    "bybit_api_secret": {"type": "str", "default": BYBIT_API_SECRET},
    "telegram_api_id": {"type": "int", "default": TELEGRAM_API_ID},
    "telegram_api_hash": {"type": "str", "default": TELEGRAM_API_HASH},
    "internal_api_token": {"type": "str", "default": INTERNAL_API_TOKEN},
}


class Storage:
    SETTINGS_REVISION_KEY = "settings.revision"

    def __init__(self, path=DATA_TRADES_PATH):
        self.path = path
        self.balance_history_path = DATA_BALANCE_HISTORY_PATH
        self.transaction_history_path = DATA_TRANSACTION_HISTORY_PATH
        self.history_db_path = DATA_HISTORY_DB_PATH
        self.secrets_key_path = DATA_SECRETS_KEY_PATH
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(self.path) or DATA_DIR, exist_ok=True)
        self.lock = threading.RLock()

        self.transaction_history = []
        self.transaction_history_meta = {}

        self._ensure_secrets_key()
        self._ensure_history_db()
        self.load()

    def _ensure_secrets_key(self):
        if os.path.exists(self.secrets_key_path):
            return

        key_bytes = secrets.token_bytes(32)
        encoded = base64.urlsafe_b64encode(key_bytes).decode("ascii")
        fd = os.open(self.secrets_key_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            try:
                os.chmod(self.secrets_key_path, 0o600)
            except Exception:
                pass

    def _load_secrets_key(self):
        with open(self.secrets_key_path, "r") as handle:
            raw = handle.read().strip()
        return base64.urlsafe_b64decode(raw.encode("ascii"))

    def _normalize_secret(self, key, value):
        schema = APP_SECRETS_SCHEMA.get(key)
        if not schema:
            raise ValueError(f"Unknown app secret: {key}")
        if value is None:
            return None
        if schema["type"] == "int":
            return int(value)
        return str(value)

    def _encrypt_secret_value(self, value):
        if value is None:
            return None

        plaintext = str(value).encode("utf-8")
        master = self._load_secrets_key()
        nonce = secrets.token_bytes(16)
        enc_key = hashlib.sha256(master + b":enc").digest()
        mac_key = hashlib.sha256(master + b":mac").digest()

        ciphertext = bytearray()
        counter = 0
        while len(ciphertext) < len(plaintext):
            block = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
            ciphertext.extend(block)
            counter += 1
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, ciphertext[:len(plaintext)]))
        tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()

        return ":".join([
            "v1",
            base64.urlsafe_b64encode(nonce).decode("ascii"),
            base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            base64.urlsafe_b64encode(tag).decode("ascii"),
        ])

    def _decrypt_secret_value(self, payload):
        if not payload:
            return None

        version, nonce_b64, cipher_b64, tag_b64 = str(payload).split(":", 3)
        if version != "v1":
            raise ValueError("Unsupported secret payload version")

        nonce = base64.urlsafe_b64decode(nonce_b64.encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(cipher_b64.encode("ascii"))
        expected_tag = base64.urlsafe_b64decode(tag_b64.encode("ascii"))

        master = self._load_secrets_key()
        enc_key = hashlib.sha256(master + b":enc").digest()
        mac_key = hashlib.sha256(master + b":mac").digest()
        actual_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_tag, actual_tag):
            raise ValueError("Secret payload authentication failed")

        plaintext = bytearray()
        counter = 0
        while len(plaintext) < len(ciphertext):
            block = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
            plaintext.extend(block)
            counter += 1
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, plaintext[:len(ciphertext)]))
        return plaintext.decode("utf-8")

    def _db_connect(self):
        conn = sqlite3.connect(self.history_db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _has_transaction_events_in_db(self):
        conn = self._db_connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM transaction_events LIMIT 1"
            ).fetchone()
            return bool(row)
        finally:
            conn.close()

    def _ensure_history_db(self):
        with self.lock:
            conn = self._db_connect()
            try:
                conn.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS sync_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS transaction_events (
                        event_key TEXT PRIMARY KEY,
                        id TEXT,
                        symbol TEXT,
                        category TEXT,
                        side TEXT,
                        type TEXT,
                        currency TEXT,
                        transaction_time INTEGER,
                        cash_balance REAL,
                        change_value REAL,
                        cash_flow REAL,
                        funding REAL,
                        fee REAL,
                        trade_price REAL,
                        qty REAL,
                        size REAL,
                        order_id TEXT,
                        order_link_id TEXT,
                        trade_id TEXT,
                        trans_sub_type TEXT,
                        raw_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_transaction_time
                    ON transaction_events(transaction_time);
                    CREATE INDEX IF NOT EXISTS idx_transaction_symbol_time
                    ON transaction_events(symbol, transaction_time);
                    CREATE TABLE IF NOT EXISTS execution_events (
                        exec_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        side TEXT,
                        exec_time INTEGER NOT NULL,
                        order_id TEXT,
                        order_link_id TEXT,
                        order_type TEXT,
                        stop_order_type TEXT,
                        create_type TEXT,
                        exec_price REAL,
                        exec_qty REAL,
                        exec_value REAL,
                        closed_size REAL,
                        exec_fee REAL,
                        is_maker INTEGER,
                        raw_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_execution_time
                    ON execution_events(exec_time);
                    CREATE INDEX IF NOT EXISTS idx_execution_symbol_time
                    ON execution_events(symbol, exec_time);
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS app_secrets (
                        key TEXT PRIMARY KEY,
                        value_enc TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS signal_events (
                        signal_key TEXT PRIMARY KEY,
                        message_id TEXT,
                        symbol TEXT,
                        side TEXT,
                        source TEXT,
                        created_at TEXT NOT NULL,
                        raw_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_signal_created_at
                    ON signal_events(created_at);
                    CREATE TABLE IF NOT EXISTS telegram_message_registry (
                        message_id TEXT PRIMARY KEY,
                        kind TEXT,
                        trade_id TEXT,
                        source TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_telegram_message_registry_updated
                    ON telegram_message_registry(updated_at);
                    CREATE TABLE IF NOT EXISTS bot_trades (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT,
                        side TEXT,
                        status TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        message_id TEXT,
                        order_id TEXT,
                        raw_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_bot_trades_created_at
                    ON bot_trades(created_at);
                    CREATE INDEX IF NOT EXISTS idx_bot_trades_symbol_status
                    ON bot_trades(symbol, status);
                    CREATE INDEX IF NOT EXISTS idx_bot_trades_message_id
                    ON bot_trades(message_id);
                    CREATE TABLE IF NOT EXISTS balance_snapshots (
                        captured_at TEXT PRIMARY KEY,
                        wallet_balance REAL NOT NULL,
                        available_balance REAL NOT NULL,
                        equity REAL NOT NULL,
                        raw_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_balance_snapshots_captured_at
                    ON balance_snapshots(captured_at);
                    CREATE TABLE IF NOT EXISTS exchange_closed_trades (
                        trade_key TEXT PRIMARY KEY,
                        trade_id TEXT,
                        symbol TEXT NOT NULL,
                        side TEXT,
                        opened_at TEXT,
                        closed_at TEXT,
                        entry_price REAL,
                        exit_price REAL,
                        qty REAL,
                        pnl REAL,
                        close_reason TEXT,
                        tp_hits INTEGER,
                        be_moved INTEGER,
                        message_id TEXT,
                        order_id TEXT,
                        sl_initial REAL,
                        sl_final REAL,
                        source TEXT,
                        executions_json TEXT,
                        context_json TEXT,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_exchange_closed_time
                    ON exchange_closed_trades(closed_at);
                    CREATE INDEX IF NOT EXISTS idx_exchange_closed_symbol_time
                    ON exchange_closed_trades(symbol, closed_at);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def load(self):
        with self.lock:
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r") as f:
                        raw = json.load(f)

                        if isinstance(raw, dict):
                            self._import_trades_json_if_needed(raw)
                except Exception as e:
                    print(f"Storage load error: {e}")
                    self._backup_corrupted_file()

            if os.path.exists(self.balance_history_path):
                try:
                    with open(self.balance_history_path, "r") as f:
                        raw = json.load(f)
                        if isinstance(raw, list):
                            self._import_balance_history_json_if_needed(
                                [item for item in raw if isinstance(item, dict)]
                            )
                except Exception as e:
                    print(f"Balance history load error: {e}")

            if os.path.exists(self.transaction_history_path):
                try:
                    with open(self.transaction_history_path, "r") as f:
                        raw = json.load(f)
                        if isinstance(raw, dict):
                            events = raw.get("events", [])
                            meta = raw.get("meta", {})
                            self.transaction_history = [item for item in events if isinstance(item, dict)]
                            self.transaction_history_meta = meta if isinstance(meta, dict) else {}
                        elif isinstance(raw, list):
                            self.transaction_history = [item for item in raw if isinstance(item, dict)]
                            self.transaction_history_meta = {}
                        else:
                            self.transaction_history = []
                            self.transaction_history_meta = {}
                except Exception as e:
                    print(f"Transaction history load error: {e}")
                    self.transaction_history = []
                    self.transaction_history_meta = {}

            if self.transaction_history and not self._has_transaction_events_in_db():
                self._upsert_transaction_events_to_db(self.transaction_history)
                if self.transaction_history_meta:
                    self._save_sync_state_to_db()

        self._seed_app_settings()
        self._seed_app_secrets()
        self._backfill_signal_events_from_trades()
        self._backfill_signal_event_statuses_from_trades()
        self._backfill_telegram_registry_from_existing_data()

    def _save_sync_state_to_db(self):
        if not self.transaction_history_meta:
            return
        conn = self._db_connect()
        try:
            rows = [
                (str(key), json.dumps(value))
                for key, value in self.transaction_history_meta.items()
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO sync_state(key, value) VALUES(?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def _touch_settings_revision(self):
        conn = self._db_connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sync_state(key, value) VALUES(?, ?)",
                (self.SETTINGS_REVISION_KEY, datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_settings_revision(self):
        conn = self._db_connect()
        try:
            row = conn.execute(
                "SELECT value FROM sync_state WHERE key = ? LIMIT 1",
                (self.SETTINGS_REVISION_KEY,),
            ).fetchone()
        finally:
            conn.close()

        return str(row["value"]) if row and row["value"] else ""

    def get_named_sync_state(self, prefix):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                "SELECT key, value FROM sync_state WHERE key LIKE ?",
                (f"{prefix}.%",),
            ).fetchall()
        finally:
            conn.close()

        payload = {}
        for row in rows:
            key = str(row["key"] or "")
            short_key = key.split(".", 1)[1] if "." in key else key
            try:
                payload[short_key] = json.loads(row["value"])
            except Exception:
                payload[short_key] = row["value"]
        return payload

    def update_named_sync_state(self, prefix, **values):
        if not values:
            return

        rows = [(f"{prefix}.{key}", json.dumps(value)) for key, value in values.items()]
        conn = self._db_connect()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO sync_state(key, value) VALUES(?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def get_telegram_message_ids(self):
        conn = self._db_connect()
        try:
            registry_rows = conn.execute(
                """
                SELECT message_id
                FROM telegram_message_registry
                WHERE message_id IS NOT NULL AND message_id != ''
                """
            ).fetchall()
            signal_rows = conn.execute(
                """
                SELECT message_id
                FROM signal_events
                WHERE message_id IS NOT NULL AND message_id != ''
                """
            ).fetchall()
            trade_rows = conn.execute(
                """
                SELECT message_id
                FROM bot_trades
                WHERE message_id IS NOT NULL AND message_id != ''
                """
            ).fetchall()
        finally:
            conn.close()

        message_ids = set()
        for rows in (registry_rows, signal_rows, trade_rows):
            for row in rows:
                try:
                    message_ids.add(int(row["message_id"]))
                except Exception:
                    continue
        return message_ids

    def get_latest_telegram_message_id(self):
        latest = 0
        for message_id in self.get_telegram_message_ids():
            try:
                latest = max(latest, int(message_id))
            except Exception:
                continue
        return latest

    def record_telegram_message(self, message_id, kind=None, trade_id=None, source=None):
        if message_id in (None, ""):
            return None

        try:
            message_id = int(message_id)
        except Exception:
            return None

        now = datetime.utcnow().isoformat()
        conn = self._db_connect()
        try:
            existing = conn.execute(
                """
                SELECT created_at
                FROM telegram_message_registry
                WHERE message_id = ?
                LIMIT 1
                """,
                (str(message_id),),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT OR REPLACE INTO telegram_message_registry(
                    message_id, kind, trade_id, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message_id),
                    kind,
                    str(trade_id) if trade_id not in (None, "") else None,
                    source,
                    created_at,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return message_id

    def clear_telegram_message_registry(self):
        conn = self._db_connect()
        try:
            conn.execute("DELETE FROM telegram_message_registry")
            conn.commit()
        finally:
            conn.close()

    def _normalize_app_setting(self, key, value):
        schema = APP_SETTINGS_SCHEMA.get(key)
        if not schema:
            raise ValueError(f"Unknown app setting: {key}")

        setting_type = schema["type"]
        if setting_type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "on"}:
                    return True
                if lowered in {"false", "0", "no", "off"}:
                    return False
            return bool(value)
        if setting_type == "int":
            return int(value)
        if setting_type == "float":
            return float(value)
        return str(value)

    def _seed_app_settings(self):
        conn = self._db_connect()
        try:
            rows = conn.execute("SELECT key FROM app_settings").fetchall()
            existing_keys = {str(row["key"]) for row in rows}
            now = datetime.utcnow().isoformat()
            inserts = []
            for key, schema in APP_SETTINGS_SCHEMA.items():
                if key in existing_keys:
                    continue
                inserts.append((key, json.dumps(schema["default"]), now))
            if inserts:
                conn.executemany(
                    """
                    INSERT INTO app_settings(key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    inserts,
                )
                conn.commit()
        finally:
            conn.close()

    def _seed_app_secrets(self):
        conn = self._db_connect()
        try:
            rows = conn.execute("SELECT key FROM app_secrets").fetchall()
            existing_keys = {str(row["key"]) for row in rows}
            now = datetime.utcnow().isoformat()
            inserts = []
            for key, schema in APP_SECRETS_SCHEMA.items():
                if key in existing_keys:
                    continue
                default_value = schema.get("default")
                if default_value in [None, ""]:
                    continue
                normalized = self._normalize_secret(key, default_value)
                encrypted = self._encrypt_secret_value(normalized)
                inserts.append((key, encrypted, now))
            if inserts:
                conn.executemany(
                    """
                    INSERT INTO app_secrets(key, value_enc, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    inserts,
                )
                conn.commit()
        finally:
            conn.close()

    def get_app_settings(self):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT key, value_json, updated_at
                FROM app_settings
                ORDER BY key ASC
                """
            ).fetchall()
        finally:
            conn.close()

        payload = {}
        for row in rows:
            key = str(row["key"])
            try:
                value = json.loads(row["value_json"])
            except Exception:
                value = row["value_json"]
            payload[key] = {
                "value": value,
                "updated_at": row["updated_at"],
            }
        return payload

    def get_app_setting(self, key, default=None):
        schema = APP_SETTINGS_SCHEMA.get(key)
        fallback = schema["default"] if schema else default

        conn = self._db_connect()
        try:
            row = conn.execute(
                """
                SELECT value_json
                FROM app_settings
                WHERE key = ?
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return fallback

        try:
            value = json.loads(row["value_json"])
        except Exception:
            value = row["value_json"]

        if not schema:
            return value

        try:
            return self._normalize_app_setting(key, value)
        except Exception:
            return fallback

    def get_app_secret(self, key, default=None):
        schema = APP_SECRETS_SCHEMA.get(key)
        fallback = schema["default"] if schema else default

        conn = self._db_connect()
        try:
            row = conn.execute(
                """
                SELECT value_enc
                FROM app_secrets
                WHERE key = ?
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return fallback

        try:
            decrypted = self._decrypt_secret_value(row["value_enc"])
            return self._normalize_secret(key, decrypted) if schema else decrypted
        except Exception:
            return fallback

    def get_app_secrets_meta(self):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT key, updated_at
                FROM app_secrets
                ORDER BY key ASC
                """
            ).fetchall()
        finally:
            conn.close()

        meta = {
            key: {
                "configured": False,
                "updated_at": None,
                "source": "missing",
            }
            for key in APP_SECRETS_SCHEMA
        }
        for row in rows:
            key = str(row["key"])
            if key in meta:
                meta[key] = {
                    "configured": True,
                    "updated_at": row["updated_at"],
                    "source": "db",
                }
        return meta

    def update_app_settings(self, updates):
        if not isinstance(updates, dict) or not updates:
            return {}

        now = datetime.utcnow().isoformat()
        rows = []
        normalized = {}
        for key, value in updates.items():
            if key not in APP_SETTINGS_SCHEMA:
                continue
            normalized_value = self._normalize_app_setting(key, value)
            normalized[key] = normalized_value
            rows.append((key, json.dumps(normalized_value), now))

        if not rows:
            return {}

        conn = self._db_connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO app_settings(key, value_json, updated_at)
                VALUES (?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        self._touch_settings_revision()
        return normalized

    def update_app_secrets(self, updates):
        if not isinstance(updates, dict) or not updates:
            return {}

        now = datetime.utcnow().isoformat()
        rows = []
        normalized = {}
        for key, value in updates.items():
            if key not in APP_SECRETS_SCHEMA:
                continue
            if value in [None, ""]:
                continue
            normalized_value = self._normalize_secret(key, value)
            normalized[key] = normalized_value
            rows.append((key, self._encrypt_secret_value(normalized_value), now))

        if not rows:
            return {}

        conn = self._db_connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO app_secrets(key, value_enc, updated_at)
                VALUES (?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        self._touch_settings_revision()
        return normalized

    def _backup_corrupted_file(self):
        if not os.path.exists(self.path):
            return

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        backup_path = f"{self.path}.corrupt.{timestamp}"

        try:
            os.replace(self.path, backup_path)
            print(f"Corrupted storage moved to {backup_path}")
        except Exception as e:
            print(f"Storage backup error: {e}")

    def _has_bot_trades_in_db(self):
        conn = self._db_connect()
        try:
            row = conn.execute("SELECT 1 FROM bot_trades LIMIT 1").fetchone()
            return bool(row)
        finally:
            conn.close()

    def _has_balance_snapshots_in_db(self):
        conn = self._db_connect()
        try:
            row = conn.execute("SELECT 1 FROM balance_snapshots LIMIT 1").fetchone()
            return bool(row)
        finally:
            conn.close()

    def _upsert_bot_trade(self, trade):
        if not isinstance(trade, dict):
            return None

        trade_id = str(trade.get("id") or trade.get("trade_id") or "")
        if not trade_id:
            return None

        created_at = trade.get("created_at") or datetime.utcnow().isoformat()
        updated_at = trade.get("updated_at") or created_at
        payload = dict(trade)
        payload["id"] = trade_id
        payload["created_at"] = created_at
        payload["updated_at"] = updated_at

        conn = self._db_connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO bot_trades(
                    trade_id, symbol, side, status, created_at, updated_at, message_id, order_id, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_id,
                    payload.get("symbol"),
                    payload.get("side"),
                    payload.get("status"),
                    created_at,
                    updated_at,
                    str(payload.get("message_id") or ""),
                    payload.get("order_id"),
                    json.dumps(payload),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return trade_id

    def _import_trades_json_if_needed(self, trades):
        if self._has_bot_trades_in_db():
            return
        for trade in trades.values():
            if isinstance(trade, dict):
                self._upsert_bot_trade(trade)

    def _get_trade_row(self, trade_id):
        conn = self._db_connect()
        try:
            row = conn.execute(
                """
                SELECT raw_json
                FROM bot_trades
                WHERE trade_id = ?
                LIMIT 1
                """,
                (str(trade_id),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return json.loads(row["raw_json"])
        except Exception:
            return None

    def _query_bot_trades(self, where_clause="", params=()):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                f"""
                SELECT raw_json
                FROM bot_trades
                {where_clause}
                ORDER BY created_at ASC, trade_id ASC
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
        return [json.loads(row["raw_json"]) for row in rows]

    def _import_balance_history_json_if_needed(self, items):
        if self._has_balance_snapshots_in_db():
            return
        for item in items:
            if isinstance(item, dict):
                self._upsert_balance_snapshot(item)

    def _upsert_balance_snapshot(self, snapshot):
        if not isinstance(snapshot, dict):
            return
        captured_at = snapshot.get("captured_at")
        if not captured_at:
            return
        wallet_balance = float(snapshot.get("wallet_balance", 0.0) or 0.0)
        available_balance = float(snapshot.get("available_balance", 0.0) or 0.0)
        equity = float(snapshot.get("equity", 0.0) or 0.0)
        payload = {
            "captured_at": captured_at,
            "wallet_balance": round(wallet_balance, 8),
            "available_balance": round(available_balance, 8),
            "equity": round(equity, 8),
        }

        conn = self._db_connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO balance_snapshots(
                    captured_at, wallet_balance, available_balance, equity, raw_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    captured_at,
                    payload["wallet_balance"],
                    payload["available_balance"],
                    payload["equity"],
                    json.dumps(payload),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _get_last_balance_snapshot(self):
        conn = self._db_connect()
        try:
            row = conn.execute(
                """
                SELECT raw_json
                FROM balance_snapshots
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return json.loads(row["raw_json"])
        except Exception:
            return None

    def create_trade(self, trade_dict):
        with self.lock:
            trade_id = str(uuid4())

            if "sl" in trade_dict and "sl_initial" not in trade_dict:
                trade_dict = {
                    **trade_dict,
                    "sl_initial": trade_dict.get("sl")
                }

            trade = {
                **trade_dict,
                "id": trade_id,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            return self._upsert_bot_trade(trade)

    def update_trade(self, trade_id, updates: dict):
        with self.lock:
            trade = self.get_trade(trade_id)

            if not isinstance(trade, dict):
                return

            trade.update(updates)
            trade["updated_at"] = datetime.utcnow().isoformat()
            self._upsert_bot_trade(trade)

    def get_trade(self, trade_id):
        with self.lock:
            trade = self._get_trade_row(trade_id)
            return dict(trade) if isinstance(trade, dict) else None

    def record_signal_event(self, payload):
        if not isinstance(payload, dict):
            return

        message_id = payload.get("message_id")
        symbol = payload.get("symbol")
        side = payload.get("side")
        source = payload.get("source") or "telegram"
        created_at = payload.get("created_at") or datetime.utcnow().isoformat()
        signal_key = str(message_id or f"{symbol}|{side}|{created_at}")

        conn = self._db_connect()
        try:
            existing = conn.execute(
                """
                SELECT raw_json
                FROM signal_events
                WHERE signal_key = ? OR message_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (signal_key, str(message_id or "")),
            ).fetchone()
            if existing:
                try:
                    merged_payload = json.loads(existing["raw_json"])
                except Exception:
                    merged_payload = {}
                merged_payload.update({k: v for k, v in payload.items() if v is not None})
                payload = merged_payload
                created_at = payload.get("created_at") or created_at

            conn.execute(
                """
                INSERT OR REPLACE INTO signal_events(
                    signal_key, message_id, symbol, side, source, created_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_key,
                    str(message_id or ""),
                    payload.get("symbol"),
                    payload.get("side"),
                    payload.get("source") or source,
                    created_at,
                    json.dumps(payload),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        if message_id not in (None, ""):
            self.record_telegram_message(
                message_id,
                kind=str(payload.get("status") or "signal").strip().lower() or "signal",
                source=payload.get("source") or source,
            )

    def update_signal_event(self, message_id, updates):
        if message_id in (None, "") or not isinstance(updates, dict) or not updates:
            return

        signal_key = str(message_id)
        conn = self._db_connect()
        try:
            row = conn.execute(
                """
                SELECT raw_json
                FROM signal_events
                WHERE signal_key = ? OR message_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (signal_key, signal_key),
            ).fetchone()
            if not row:
                return

            payload = json.loads(row["raw_json"])
            payload.update(updates)
            conn.execute(
                """
                UPDATE signal_events
                SET raw_json = ?
                WHERE signal_key = ? OR message_id = ?
                """,
                (json.dumps(payload), signal_key, signal_key),
            )
            conn.commit()
        finally:
            conn.close()

    def get_signal_events(self):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT raw_json
                FROM signal_events
                ORDER BY created_at DESC, signal_key DESC
                """
            ).fetchall()
        finally:
            conn.close()

        return [json.loads(row["raw_json"]) for row in rows]

    def get_latest_signal_message_id(self):
        latest = 0

        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT message_id
                FROM signal_events
                WHERE message_id IS NOT NULL AND message_id != ''
                """
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            try:
                latest = max(latest, int(row["message_id"]))
            except Exception:
                continue

        for trade in self.get_all_trades():
            try:
                latest = max(latest, int(trade.get("message_id") or 0))
            except Exception:
                continue

        return latest

    def _backfill_signal_events_from_trades(self):
        conn = self._db_connect()
        try:
            existing = conn.execute("SELECT COUNT(*) AS count FROM signal_events").fetchone()
            if existing and int(existing["count"] or 0) > 0:
                return

            rows = []
            for trade in self.get_all_trades():
                if not isinstance(trade, dict):
                    continue
                message_id = trade.get("message_id")
                if message_id in (None, ""):
                    continue
                created_at = trade.get("created_at") or datetime.utcnow().isoformat()
                payload = {
                    "message_id": message_id,
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "source": "telegram",
                    "created_at": created_at,
                    "status": "accepted",
                    "backfilled_from": "legacy_trade_storage",
                }
                rows.append((
                    str(message_id),
                    str(message_id),
                    trade.get("symbol"),
                    trade.get("side"),
                    "telegram",
                    created_at,
                    json.dumps(payload),
                ))

            if rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO signal_events(
                        signal_key, message_id, symbol, side, source, created_at, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
        finally:
            conn.close()

    def _backfill_signal_event_statuses_from_trades(self):
        message_ids = {
            str(trade.get("message_id"))
            for trade in self.get_all_trades()
            if isinstance(trade, dict) and trade.get("message_id") not in (None, "")
        }
        if not message_ids:
            return

        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT signal_key, message_id, raw_json
                FROM signal_events
                """
            ).fetchall()

            updates = []
            for row in rows:
                message_id = str(row["message_id"] or "")
                if not message_id or message_id not in message_ids:
                    continue

                try:
                    payload = json.loads(row["raw_json"])
                except Exception:
                    continue

                if str(payload.get("status") or "").strip().lower() == "accepted":
                    continue

                payload["status"] = "accepted"
                if "backfilled_from" not in payload:
                    payload["backfilled_from"] = "legacy_trade_storage"
                updates.append((json.dumps(payload), row["signal_key"]))

            if updates:
                conn.executemany(
                    "UPDATE signal_events SET raw_json = ? WHERE signal_key = ?",
                    updates,
                )
                conn.commit()
        finally:
            conn.close()

    def _backfill_telegram_registry_from_existing_data(self):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT message_id, source, created_at
                FROM signal_events
                WHERE message_id IS NOT NULL AND message_id != ''
                """
            ).fetchall()
            trade_rows = conn.execute(
                """
                SELECT message_id, created_at
                FROM bot_trades
                WHERE message_id IS NOT NULL AND message_id != ''
                """
            ).fetchall()

            now = datetime.utcnow().isoformat()
            inserts = []
            for row in rows:
                message_id = str(row["message_id"] or "").strip()
                if not message_id:
                    continue
                inserts.append((
                    message_id,
                    "signal",
                    None,
                    row["source"] or "signal_events",
                    row["created_at"] or now,
                    now,
                ))
            for row in trade_rows:
                message_id = str(row["message_id"] or "").strip()
                if not message_id:
                    continue
                inserts.append((
                    message_id,
                    "trade",
                    None,
                    "bot_trades",
                    row["created_at"] or now,
                    now,
                ))

            if inserts:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO telegram_message_registry(
                        message_id, kind, trade_id, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    inserts,
                )
                conn.commit()
        finally:
            conn.close()

    def get_all_trades(self):
        with self.lock:
            return [dict(trade) for trade in self._query_bot_trades()]

    def get_active_trades(self):
        with self.lock:
            return [
                dict(t) for t in self._query_bot_trades()
                if isinstance(t, dict) and t.get("status") in ["PENDING", "FILLED"]
            ]

    def find_active_by_symbol(self, symbol):
        with self.lock:
            for t in self._query_bot_trades("WHERE symbol = ?", (symbol,)):
                if isinstance(t, dict) and t.get("symbol") == symbol and t.get("status") != "CLOSED":
                    return dict(t)
            return None

    def find_last_by_symbol(self, symbol):
        with self.lock:
            trades = [
                dict(t) for t in self._query_bot_trades("WHERE symbol = ?", (symbol,))
                if isinstance(t, dict) and t.get("symbol") == symbol
            ]

            if not trades:
                return None

            return sorted(trades, key=lambda x: x["created_at"], reverse=True)[0]

    def find_by_message_id(self, message_id):
        with self.lock:
            for t in self._query_bot_trades("WHERE message_id = ?", (str(message_id),)):
                if (
                    isinstance(t, dict)
                    and t.get("message_id") == message_id
                    and t.get("status") != "CLOSED"
                ):
                    return dict(t)
            return None

    def close_trade(self, trade_id, exit_price, pnl, reason):
        with self.lock:
            trade = self.get_trade(trade_id)

            if not isinstance(trade, dict):
                return False

            if trade.get("status") == "CLOSED":
                return False

            trade.update({
                "status": "CLOSED",
                "exit": exit_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "close_reason": reason,
                "exit_reason": reason,
                "closed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            })

            self._upsert_bot_trade(trade)
            return True

    def delete_trade(self, trade_id):
        conn = self._db_connect()
        try:
            conn.execute("DELETE FROM bot_trades WHERE trade_id = ?", (str(trade_id),))
            conn.commit()
        finally:
            conn.close()

    def record_balance_snapshot(self, summary, captured_at=None):
        with self.lock:
            try:
                wallet_balance = float(summary.get("wallet_balance", 0.0) or 0.0)
                available_balance = float(summary.get("available_balance", 0.0) or 0.0)
                equity = float(summary.get("equity", 0.0) or 0.0)
            except Exception:
                return

            captured_at = captured_at or datetime.utcnow().isoformat()
            snapshot = {
                "captured_at": captured_at,
                "wallet_balance": round(wallet_balance, 8),
                "available_balance": round(available_balance, 8),
                "equity": round(equity, 8),
            }

            last = self._get_last_balance_snapshot()
            if last:
                same_values = (
                    abs(float(last.get("wallet_balance", 0.0) or 0.0) - snapshot["wallet_balance"]) < 1e-9
                    and abs(float(last.get("available_balance", 0.0) or 0.0) - snapshot["available_balance"]) < 1e-9
                    and abs(float(last.get("equity", 0.0) or 0.0) - snapshot["equity"]) < 1e-9
                )
                if same_values:
                    snapshot["captured_at"] = captured_at
                    self._upsert_balance_snapshot(snapshot)
                    return

            self._upsert_balance_snapshot(snapshot)

    def get_balance_history(self):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT raw_json
                FROM balance_snapshots
                ORDER BY captured_at ASC
                """
            ).fetchall()
        finally:
            conn.close()
        return [json.loads(row["raw_json"]) for row in rows]

    def _transaction_event_key(self, item):
        return "|".join([
            str(item.get("id") or ""),
            str(item.get("transaction_time") or ""),
            str(item.get("currency") or ""),
            str(item.get("type") or ""),
            str(item.get("order_id") or ""),
            str(item.get("trade_id") or ""),
            str(item.get("change") or ""),
            str(item.get("cash_balance") or ""),
        ])

    def record_transaction_events(self, events, **meta_updates):
        with self.lock:
            for key, value in meta_updates.items():
                self.transaction_history_meta[key] = value

            self._upsert_transaction_events_to_db(events or [])
            self._save_sync_state_to_db()

    def get_transaction_history(self):
        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT raw_json
                FROM transaction_events
                ORDER BY transaction_time ASC, id ASC
                """
            ).fetchall()
        finally:
            conn.close()

        if rows:
            return [json.loads(row["raw_json"]) for row in rows]

        with self.lock:
            return [dict(item) for item in self.transaction_history if isinstance(item, dict)]

    def get_transaction_history_meta(self):
        conn = self._db_connect()
        try:
            rows = conn.execute("SELECT key, value FROM sync_state").fetchall()
        finally:
            conn.close()

        if rows:
            payload = {}
            for row in rows:
                try:
                    payload[row["key"]] = json.loads(row["value"])
                except Exception:
                    payload[row["key"]] = row["value"]
            return payload

        with self.lock:
            return dict(self.transaction_history_meta)

    def record_execution_events(self, events, **meta_updates):
        self._upsert_execution_events_to_db(events or [])
        if meta_updates:
            self.update_named_sync_state("execution_history", **meta_updates)

    def get_execution_events(self, before_ms=None):
        query = """
            SELECT raw_json
            FROM execution_events
        """
        params = []
        if before_ms is not None:
            query += " WHERE exec_time < ?"
            params.append(int(before_ms))
        query += " ORDER BY exec_time ASC, exec_id ASC"

        conn = self._db_connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        return [json.loads(row["raw_json"]) for row in rows]

    def get_execution_events_by_order_id(self, order_id):
        if not order_id:
            return []

        conn = self._db_connect()
        try:
            rows = conn.execute(
                """
                SELECT raw_json
                FROM execution_events
                WHERE order_id = ?
                ORDER BY exec_time ASC, exec_id ASC
                """,
                (str(order_id),),
            ).fetchall()
        finally:
            conn.close()

        return [json.loads(row["raw_json"]) for row in rows]

    def _upsert_transaction_events_to_db(self, events):
        if not events:
            return

        rows = []
        for item in events:
            if not isinstance(item, dict):
                continue
            rows.append((
                self._transaction_event_key(item),
                item.get("id"),
                item.get("symbol"),
                item.get("category"),
                item.get("side"),
                item.get("type"),
                item.get("currency"),
                int(item.get("transaction_time", 0) or 0),
                float(item.get("cash_balance", 0.0) or 0.0),
                float(item.get("change", 0.0) or 0.0),
                float(item.get("cash_flow", 0.0) or 0.0),
                float(item.get("funding", 0.0) or 0.0),
                float(item.get("fee", 0.0) or 0.0),
                float(item.get("trade_price", 0.0) or 0.0),
                float(item.get("qty", 0.0) or 0.0),
                float(item.get("size", 0.0) or 0.0),
                item.get("order_id"),
                item.get("order_link_id"),
                item.get("trade_id"),
                item.get("trans_sub_type"),
                json.dumps(item),
            ))

        conn = self._db_connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO transaction_events(
                    event_key, id, symbol, category, side, type, currency,
                    transaction_time, cash_balance, change_value, cash_flow,
                    funding, fee, trade_price, qty, size, order_id,
                    order_link_id, trade_id, trans_sub_type, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def _upsert_execution_events_to_db(self, events):
        if not events:
            return

        rows = []
        for item in events:
            if not isinstance(item, dict):
                continue
            rows.append((
                str(item.get("execId") or ""),
                item.get("symbol"),
                item.get("side"),
                int(item.get("execTime", 0) or 0),
                item.get("orderId"),
                item.get("orderLinkId"),
                item.get("orderType"),
                item.get("stopOrderType"),
                item.get("createType"),
                float(item.get("execPrice", 0.0) or 0.0),
                float(item.get("execQty", 0.0) or 0.0),
                float(item.get("execValue", 0.0) or 0.0),
                float(item.get("closedSize", 0.0) or 0.0),
                float(item.get("execFee", 0.0) or 0.0),
                1 if bool(item.get("isMaker")) else 0,
                json.dumps(item),
            ))

        conn = self._db_connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO execution_events(
                    exec_id, symbol, side, exec_time, order_id, order_link_id,
                    order_type, stop_order_type, create_type, exec_price, exec_qty,
                    exec_value, closed_size, exec_fee, is_maker, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def get_exchange_closed_trades(self, source=None):
        query = """
            SELECT *
            FROM exchange_closed_trades
        """
        params = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY closed_at DESC, updated_at DESC"

        conn = self._db_connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        result = []
        for row in rows:
            result.append({
                "trade_key": row["trade_key"],
                "trade_id": row["trade_id"],
                "symbol": row["symbol"],
                "side": row["side"],
                "opened_at": row["opened_at"],
                "closed_at": row["closed_at"],
                "entry": row["entry_price"],
                "exit": row["exit_price"],
                "qty": row["qty"],
                "pnl": row["pnl"],
                "close_reason": row["close_reason"],
                "tp_hits": row["tp_hits"],
                "be_moved": bool(row["be_moved"]),
                "message_id": row["message_id"],
                "order_id": row["order_id"],
                "sl_initial": row["sl_initial"],
                "sl": row["sl_final"],
                "updated_at": row["updated_at"],
            })
        return result

    def upsert_exchange_closed_trades(self, source, trades):
        if not trades:
            return

        rows = []
        for trade in trades:
            rows.append((
                trade.get("trade_key"),
                str(trade.get("trade_id") or ""),
                trade.get("symbol"),
                trade.get("side"),
                trade.get("opened_at"),
                trade.get("closed_at"),
                float(trade.get("entry_price", 0) or 0),
                float(trade.get("exit_price", 0) or 0),
                float(trade.get("qty", 0) or 0),
                float(trade.get("pnl", 0) or 0),
                trade.get("close_reason"),
                int(trade.get("tp_hits", 0) or 0),
                1 if trade.get("be_moved") else 0,
                str(trade.get("message_id") or ""),
                str(trade.get("order_id") or ""),
                float(trade.get("sl_initial", 0) or 0),
                float(trade.get("sl_final", 0) or 0),
                source,
                json.dumps(trade.get("executions", [])),
                json.dumps(trade.get("context", {})),
                datetime.utcnow().isoformat(),
            ))

        conn = self._db_connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO exchange_closed_trades(
                    trade_key, trade_id, symbol, side, opened_at, closed_at,
                    entry_price, exit_price, qty, pnl, close_reason, tp_hits,
                    be_moved, message_id, order_id, sl_initial, sl_final,
                    source, executions_json, context_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
