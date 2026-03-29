import json
import os
import csv
import sqlite3
import threading
from datetime import datetime
from uuid import uuid4
from pathlib import Path
from config import DATA_DIR, DATA_REPORTS_DIR, DATA_STORAGE_DIR

BALANCE_HISTORY_LIMIT = 10000
TRANSACTION_HISTORY_LIMIT = 50000


class Storage:
    def __init__(self, path=f"{DATA_STORAGE_DIR}/trades.json"):
        self.path = path
        self.balance_history_path = f"{DATA_STORAGE_DIR}/balance_history.json"
        self.transaction_history_path = f"{DATA_STORAGE_DIR}/transaction_history.json"
        self.history_db_path = f"{DATA_STORAGE_DIR}/history.sqlite3"
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(DATA_REPORTS_DIR, exist_ok=True)
        os.makedirs(DATA_STORAGE_DIR, exist_ok=True)
        self.lock = threading.RLock()

        self.data = {}
        self.balance_history = []
        self.transaction_history = []
        self.transaction_history_meta = {}
        self.report_path = f"{DATA_REPORTS_DIR}/report.csv"

        self._ensure_report_header()
        self._ensure_history_db()
        self.load()

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
                            self.data = raw
                        else:
                            self.data = {}
                except Exception as e:
                    print(f"Storage load error: {e}")
                    self._backup_corrupted_file()
                    self.data = {}

            if os.path.exists(self.balance_history_path):
                try:
                    with open(self.balance_history_path, "r") as f:
                        raw = json.load(f)
                        if isinstance(raw, list):
                            self.balance_history = [item for item in raw if isinstance(item, dict)]
                        else:
                            self.balance_history = []
                except Exception as e:
                    print(f"Balance history load error: {e}")
                    self.balance_history = []

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

            self._backfill_signal_events_from_trades()
            self._backfill_signal_event_statuses_from_trades()

    def save(self):
        with self.lock:
            try:
                path = Path(self.path)
                tmp_path = path.with_suffix(f"{path.suffix}.tmp")

                with open(tmp_path, "w") as f:
                    json.dump(self.data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, path)
            except Exception as e:
                print(f"Storage save error: {e}")
                try:
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

    def save_balance_history(self):
        with self.lock:
            try:
                path = Path(self.balance_history_path)
                tmp_path = path.with_suffix(f"{path.suffix}.tmp")

                with open(tmp_path, "w") as f:
                    json.dump(self.balance_history, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, path)
            except Exception as e:
                print(f"Balance history save error: {e}")
                try:
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

    def save_transaction_history(self):
        with self.lock:
            try:
                path = Path(self.transaction_history_path)
                tmp_path = path.with_suffix(f"{path.suffix}.tmp")
                payload = {
                    "events": self.transaction_history,
                    "meta": self.transaction_history_meta,
                }

                with open(tmp_path, "w") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, path)
            except Exception as e:
                print(f"Transaction history save error: {e}")
                try:
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

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

    def _ensure_report_header(self):
        with self.lock:
            if not os.path.exists(self.report_path) or os.path.getsize(self.report_path) == 0:
                with open(self.report_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "time",
                        "symbol",
                        "side",
                        "entry",
                        "exit",
                        "size",
                        "pnl",
                        "pnl_pct",
                        "reason",
                        "sl_initial",
                        "sl_final",
                        "tp1_price",
                        "tp2_price",
                        "tp3_price",
                        "tp1_hit",
                        "be_moved",
                        "duration_sec"
                    ])

    def _append_to_report(self, trade):
        with self.lock:
            try:
                entry = float(trade.get("entry", 0) or 0)
                exit_price = trade.get("exit")
                if exit_price is None:
                    exit_price = trade.get("exit_price")
                exit_price = float(exit_price or 0)
                size = float(trade.get("filled_size", 0) or 0)
                pnl = float(trade.get("pnl", 0) or 0)
                side = trade.get("side")
                reason = trade.get("close_reason") or trade.get("exit_reason")
                tps = trade.get("tps", [])

                if entry > 0 and exit_price > 0:
                    if side == "LONG":
                        pnl_pct = ((exit_price - entry) / entry) * 100
                    else:
                        pnl_pct = ((entry - exit_price) / entry) * 100
                else:
                    pnl_pct = 0

                duration = 0
                created_at = trade.get("created_at")
                closed_at = trade.get("closed_at")
                if created_at and closed_at:
                    try:
                        duration = int(
                            (
                                datetime.fromisoformat(closed_at)
                                - datetime.fromisoformat(created_at)
                            ).total_seconds()
                        )
                    except Exception:
                        duration = 0

                tp1 = tps[0]["price"] if len(tps) > 0 else None
                tp2 = tps[1]["price"] if len(tps) > 1 else None
                tp3 = tps[2]["price"] if len(tps) > 2 else None
                tp1_hit = bool(trade.get("tp_hits", 0) > 0 or (tps and tps[0].get("hit")))

                with open(self.report_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        closed_at or datetime.utcnow().isoformat(),
                        trade.get("symbol"),
                        side,
                        round(entry, 4),
                        round(exit_price, 4),
                        round(size, 4),
                        round(pnl, 4),
                        round(pnl_pct, 4),
                        reason,
                        trade.get("sl_initial"),
                        trade.get("sl"),
                        tp1,
                        tp2,
                        tp3,
                        tp1_hit,
                        trade.get("be_moved", False),
                        duration
                    ])
            except Exception as e:
                print(f"Report write error: {e}")

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

            self.data[trade_id] = trade
            self.save()

            return trade_id

    def update_trade(self, trade_id, updates: dict):
        with self.lock:
            trade = self.data.get(trade_id)

            if not isinstance(trade, dict):
                return

            trade.update(updates)
            trade["updated_at"] = datetime.utcnow().isoformat()

            self.save()

    def get_trade(self, trade_id):
        with self.lock:
            trade = self.data.get(trade_id)
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
            conn.execute(
                """
                INSERT OR REPLACE INTO signal_events(
                    signal_key, message_id, symbol, side, source, created_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_key,
                    str(message_id or ""),
                    symbol,
                    side,
                    source,
                    created_at,
                    json.dumps(payload),
                ),
            )
            conn.commit()
        finally:
            conn.close()

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

    def _backfill_signal_events_from_trades(self):
        conn = self._db_connect()
        try:
            existing = conn.execute("SELECT COUNT(*) AS count FROM signal_events").fetchone()
            if existing and int(existing["count"] or 0) > 0:
                return

            rows = []
            for trade in self.data.values():
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
                    "backfilled_from": "trades.json",
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
            for trade in self.data.values()
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
                    payload["backfilled_from"] = "trades.json"
                updates.append((json.dumps(payload), row["signal_key"]))

            if updates:
                conn.executemany(
                    "UPDATE signal_events SET raw_json = ? WHERE signal_key = ?",
                    updates,
                )
                conn.commit()
        finally:
            conn.close()

    def get_all_trades(self):
        with self.lock:
            return [dict(trade) for trade in self.data.values() if isinstance(trade, dict)]

    def get_active_trades(self):
        with self.lock:
            return [
                dict(t) for t in self.data.values()
                if isinstance(t, dict) and t.get("status") in ["PENDING", "FILLED"]
            ]

    def find_active_by_symbol(self, symbol):
        with self.lock:
            for t in self.data.values():
                if isinstance(t, dict) and t.get("symbol") == symbol and t.get("status") != "CLOSED":
                    return dict(t)
            return None

    def find_last_by_symbol(self, symbol):
        with self.lock:
            trades = [
                dict(t) for t in self.data.values()
                if isinstance(t, dict) and t.get("symbol") == symbol
            ]

            if not trades:
                return None

            return sorted(trades, key=lambda x: x["created_at"], reverse=True)[0]

    def find_by_message_id(self, message_id):
        with self.lock:
            for t in self.data.values():
                if (
                    isinstance(t, dict)
                    and t.get("message_id") == message_id
                    and t.get("status") != "CLOSED"
                ):
                    return dict(t)
            return None

    def close_trade(self, trade_id, exit_price, pnl, reason):
        with self.lock:
            trade = self.data.get(trade_id)

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

            self.save()
            self._append_to_report(dict(trade))
            return True

    def delete_trade(self, trade_id):
        with self.lock:
            if trade_id in self.data:
                del self.data[trade_id]
                self.save()

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

            last = self.balance_history[-1] if self.balance_history else None
            if last:
                same_values = (
                    abs(float(last.get("wallet_balance", 0.0) or 0.0) - snapshot["wallet_balance"]) < 1e-9
                    and abs(float(last.get("available_balance", 0.0) or 0.0) - snapshot["available_balance"]) < 1e-9
                    and abs(float(last.get("equity", 0.0) or 0.0) - snapshot["equity"]) < 1e-9
                )
                if same_values:
                    last["captured_at"] = captured_at
                    self.save_balance_history()
                    return

            self.balance_history.append(snapshot)
            if len(self.balance_history) > BALANCE_HISTORY_LIMIT:
                self.balance_history = self.balance_history[-BALANCE_HISTORY_LIMIT:]
            self.save_balance_history()

    def get_balance_history(self):
        with self.lock:
            return [dict(item) for item in self.balance_history if isinstance(item, dict)]

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
            existing = {
                self._transaction_event_key(item): dict(item)
                for item in self.transaction_history
                if isinstance(item, dict)
            }

            for item in events or []:
                if not isinstance(item, dict):
                    continue
                existing[self._transaction_event_key(item)] = dict(item)

            self.transaction_history = sorted(
                existing.values(),
                key=lambda item: (
                    int(item.get("transaction_time", 0) or 0),
                    str(item.get("id") or ""),
                ),
            )

            if len(self.transaction_history) > TRANSACTION_HISTORY_LIMIT:
                self.transaction_history = self.transaction_history[-TRANSACTION_HISTORY_LIMIT:]

            for key, value in meta_updates.items():
                self.transaction_history_meta[key] = value

            self.save_transaction_history()
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
