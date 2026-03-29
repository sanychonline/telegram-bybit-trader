from classes.trade_manager.close_reason import classify_close_reason
from classes.reporting.health_state import touch


MAX_CLOSE_PENDING_CHECKS = 15


class Reconciliation:
    def __init__(self, bybit, storage, logger):
        self.bybit = bybit
        self.storage = storage
        self.logger = logger

        self.known_positions = {}

    def sync(self):
        try:
            positions = self.bybit.client.get_positions(
                category="linear",
                settleCoin="USDT"
            )["result"]["list"]
            touch("reconciliation")
            touch("bybit")
        except Exception as e:
            self.logger.error(f"Reconciliation error: {e}")
            return

        current_symbols = set()

        for pos in positions:
            size = float(pos["size"])
            symbol = pos["symbol"]

            if size > 0:
                current_symbols.add(symbol)

                if symbol not in self.known_positions:
                    self.logger.debug(f"Detected existing position: {symbol}")
                    self.known_positions[symbol] = True

                    existing = self.storage.find_active_by_symbol(symbol)

                    if not existing:
                        self.logger.warning(f"{symbol} restoring trade from exchange")

                        side = "LONG" if pos["side"] == "Buy" else "SHORT"
                        entry = float(pos["avgPrice"])

                        self.storage.create_trade({
                            "symbol": symbol,
                            "side": side,
                            "status": "FILLED",
                            "entry": entry,
                            "sl": None,
                            "tps": [],
                            "filled_size": size,
                            "remaining_size": size,
                            "tp1_done": False,
                            "be_moved": False,
                            "restored_from_exchange": True,
                            "signal_context_missing": True
                        })

        for symbol in list(self.known_positions.keys()):
            if symbol not in current_symbols:
                self.logger.debug(f"{symbol} closed on exchange")

                trade = self.storage.find_last_by_symbol(symbol)

                if trade and trade.get("status") == "CLOSED":
                    self.logger.debug(f"{symbol} already closed in storage → skip")
                    del self.known_positions[symbol]
                    continue

                if not trade:
                    self.logger.warning(f"{symbol} no trade in storage → skip")
                    del self.known_positions[symbol]
                    continue

                entry = float(trade.get("entry", 0))
                size = float(trade.get("filled_size", 0))

                if size <= 0:
                    del self.known_positions[symbol]
                    continue

                try:
                    close_summary = self.bybit.summarize_trade_close(trade)
                except Exception as e:
                    self.logger.error(f"{symbol} exit fetch error: {e}")
                    close_summary = {}

                if not self._has_complete_close_data(trade, close_summary):
                    pending_checks = int(trade.get("close_pending_checks", 0) or 0) + 1
                    self.storage.update_trade(trade["id"], {
                        "close_pending_checks": pending_checks
                    })

                    if pending_checks < MAX_CLOSE_PENDING_CHECKS:
                        self.logger.debug(
                            f"{symbol} waiting for exchange close executions | "
                            f"attempt={pending_checks} "
                            f"closed_qty={close_summary.get('closed_qty', 0)} "
                            f"target_qty={trade.get('filled_size', 0)}"
                        )
                        continue

                    self.logger.warning(
                        f"{symbol} closing with partial exchange data after {pending_checks} checks | "
                        f"closed_qty={close_summary.get('closed_qty', 0)} "
                        f"target_qty={trade.get('filled_size', 0)}"
                    )

                exit_price = close_summary.get("exit_price")
                if not exit_price:
                    exit_price = entry
                close_executions = close_summary.get("executions", [])

                pnl = close_summary.get("pnl")
                if pnl is None:
                    pnl = self._calculate_real_pnl(trade, exit_price)

                reason = self._detect_reason(trade, exit_price, close_executions, close_summary)

                self.logger.info(
                    f"{symbol} CLOSED | entry={entry} exit={exit_price} size={size} pnl={pnl} reason={reason}"
                )
                updates = {}
                if close_summary.get("tp_hits") is not None:
                    updates["tp_hits"] = int(close_summary.get("tp_hits", 0) or 0)
                    updates["tps"] = self._mark_hit_tps(trade.get("tps", []), updates["tp_hits"])
                updates["close_pending_checks"] = 0
                if updates:
                    self.storage.update_trade(trade["id"], updates)
                    trade = self.storage.get_trade(trade["id"]) or trade
                self.storage.close_trade(
                    trade["id"],
                    exit_price,
                    pnl,
                    reason
                )

                del self.known_positions[symbol]

    def _detect_reason(self, trade, exit_price, close_executions=None, close_summary=None):
        if trade.get("close_reason_hint") == "DESYNC_ABORT":
            tp_hits = int((close_summary or {}).get("tp_hits", trade.get("tp_hits", 0)) or 0)
            if tp_hits > 0:
                return f"DESYNC_ABORT_AFTER_TP{tp_hits}"
            return "DESYNC_ABORT"
        if trade.get("close_reason_hint") == "PROTECTION_ABORT":
            tp_hits = int((close_summary or {}).get("tp_hits", trade.get("tp_hits", 0)) or 0)
            if tp_hits > 0:
                return f"PROTECTION_ABORT_AFTER_TP{tp_hits}"
            return "PROTECTION_ABORT"
        return classify_close_reason(trade, exit_price, close_executions, close_summary=close_summary)

    def _mark_hit_tps(self, tps, completed_hits):
        updated_tps = []

        for index, tp in enumerate(tps):
            updated_tp = dict(tp)
            updated_tp["hit"] = index < completed_hits
            updated_tps.append(updated_tp)

        return updated_tps

    def _calculate_real_pnl(self, trade, exit_price):
        try:
            entry = trade.get("entry", 0)
            side = trade.get("side")
            tps = trade.get("tps", [])

            pnl = 0

            if trade.get("tp1_done") and tps:
                tp1 = tps[0]

                if side == "LONG":
                    pnl += (tp1["price"] - entry) * tp1["qty"]
                else:
                    pnl += (entry - tp1["price"]) * tp1["qty"]

                remaining = trade.get("remaining_size", 0)

                if side == "LONG":
                    pnl += (exit_price - entry) * remaining
                else:
                    pnl += (entry - exit_price) * remaining

                return pnl

            size = trade.get("filled_size", 0)

            if side == "LONG":
                return (exit_price - entry) * size
            else:
                return (entry - exit_price) * size

        except:
            return 0

    def _has_complete_close_data(self, trade, close_summary):
        executions = close_summary.get("executions", [])
        closed_qty = float(close_summary.get("closed_qty", 0) or 0)
        target_qty = float(trade.get("filled_size", 0) or 0)

        if not executions or target_qty <= 0:
            return False

        step = self.bybit.get_symbol_filters(trade["symbol"])["step"]
        tolerance = max(step / 2, 1e-9)
        return closed_qty + tolerance >= target_qty
