import json
import os
import csv
import threading
from datetime import datetime
from uuid import uuid4
from pathlib import Path
from config import DATA_DIR, DATA_REPORTS_DIR, DATA_STORAGE_DIR


class Storage:
    def __init__(self, path=f"{DATA_STORAGE_DIR}/trades.json"):
        self.path = path
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(DATA_REPORTS_DIR, exist_ok=True)
        os.makedirs(DATA_STORAGE_DIR, exist_ok=True)
        self.lock = threading.RLock()

        self.data = {}
        self.report_path = f"{DATA_REPORTS_DIR}/report.csv"

        self._ensure_report_header()
        self.load()

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
