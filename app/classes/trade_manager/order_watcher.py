import asyncio
from datetime import datetime, timezone
from classes.trade_manager.close_reason import classify_close_reason
from config import (
    MAX_ENTRY_DEVIATION_PCT,
    MAX_SIGNAL_DESYNC_PCT,
    EMERGENCY_TP_PCT,
    PENDING_ENTRY_TIMEOUT_SEC,
)
from classes.reporting.health_state import touch


MAX_CLOSE_PENDING_CHECKS = 15
MAX_PROTECTION_FAILURES = 3


class OrderWatcher:
    def __init__(self, bybit, storage, logger):
        self.bybit = bybit
        self.storage = storage
        self.logger = logger

    def _max_entry_deviation_pct(self):
        return float(self.storage.get_app_setting("max_entry_deviation_pct", MAX_ENTRY_DEVIATION_PCT))

    def _max_signal_desync_pct(self):
        return float(self.storage.get_app_setting("max_signal_desync_pct", MAX_SIGNAL_DESYNC_PCT))

    def _emergency_tp_pct(self):
        return float(self.storage.get_app_setting("emergency_tp_pct", EMERGENCY_TP_PCT))

    def _pending_entry_timeout_sec(self):
        return int(self.storage.get_app_setting("pending_entry_timeout_sec", PENDING_ENTRY_TIMEOUT_SEC))

    async def watch(self):
        while True:
            try:
                touch("watcher")
                trades = self.storage.get_active_trades()

                for trade in trades:
                    if not isinstance(trade, dict):
                        continue
                    await asyncio.to_thread(self._process_trade, trade)

                await asyncio.sleep(2)

            except Exception as e:
                self.logger.error(f"Watcher error: {str(e)}")
                await asyncio.sleep(2)

    def _process_trade(self, trade):
        symbol = trade.get("symbol")
        status = trade.get("status")

        if not symbol or not status:
            return

        position = self.bybit.get_position(symbol)

        if status == "PENDING":
            self._handle_pending(trade, position)
            return

        if status == "FILLED":
            self._handle_filled(trade, position)
            return

    def _handle_pending(self, trade, position):
        symbol = trade["symbol"]
        order_id = trade.get("order_id")
        order = None
        order_status = None
        entry = float(trade.get("entry", 0) or 0)
        side = trade.get("side")

        if order_id:
            order = self.bybit.get_order(symbol, order_id)

            if isinstance(order, dict):
                order_status = order.get("orderStatus") or order.get("status")

                if order_status in ["Cancelled", "Canceled"] and float(position.get("size", 0) or 0) <= 0:
                    self.logger.info(f"{symbol} ORDER CANCELLED")

                    self.storage.close_trade(
                        trade["id"],
                        exit_price=0,
                        pnl=0,
                        reason="CANCELLED"
                    )
                    return

        current_size = float(position.get("size", 0) or 0) if isinstance(position, dict) else 0.0

        if order_status in ["Rejected", "Deactivated"] and current_size <= 0:
            self.logger.warning(f"{symbol} ORDER REJECTED | status={order_status}")
            self.storage.close_trade(
                trade["id"],
                exit_price=0,
                pnl=0,
                reason="ORDER_REJECTED"
            )
            return

        if order_status in ["Cancelled", "Canceled"] and current_size <= 0:
            self.logger.info(f"{symbol} ORDER CANCELLED")
            self.storage.close_trade(
                trade["id"],
                exit_price=0,
                pnl=0,
                reason="ORDER_CANCELLED"
            )
            return

        pending_age_sec = self._trade_age_seconds(trade)
        if (
            current_size <= 0
            and pending_age_sec is not None
            and pending_age_sec >= self._pending_entry_timeout_sec()
        ):
            if order_id and order_status in ["New", "PartiallyFilled", "Untriggered", None]:
                try:
                    self.bybit.cancel_order(symbol, order_id)
                except Exception as e:
                    self.logger.warning(
                        f"{symbol} pending timeout cancel failed | order_id={order_id} | error={e}"
                    )

            self.logger.debug(
                f"{symbol} pending entry expired by timeout | age_sec={pending_age_sec} "
                f"entry={entry} status={order_status or 'unknown'}"
            )
            self.storage.close_trade(
                trade["id"],
                exit_price=0,
                pnl=0,
                reason="ENTRY_TIMEOUT"
            )
            return

        market_price = self.bybit.get_last_price(symbol)
        if market_price and entry > 0:
            if side == "LONG":
                deviation = (market_price - entry) / entry
                favorable_move = market_price > entry and deviation >= self._max_entry_deviation_pct()
            else:
                deviation = (entry - market_price) / entry
                favorable_move = market_price < entry and deviation >= self._max_entry_deviation_pct()

            if favorable_move and current_size <= 0:
                if order_id:
                    try:
                        self.bybit.cancel_order(symbol, order_id)
                    except Exception as e:
                        self.logger.warning(f"{symbol} pending cancel failed | order_id={order_id} | error={e}")

                self.logger.debug(
                    f"{symbol} pending entry cancelled: market already moved too far | "
                    f"entry={entry} market={market_price} deviation_pct={deviation * 100:.2f}"
                )
                self.storage.close_trade(
                    trade["id"],
                    exit_price=0,
                    pnl=0,
                    reason="ENTRY_EXPIRED"
                )
                return

        size = current_size

        if size > 0:
            actual_entry = float(position.get("avgPrice", 0) or 0)

            if order_status in ["New", "PartiallyFilled"]:
                previous_partial_size = float(trade.get("pending_filled_size", 0) or 0)
                updates = {
                    "pending_filled_size": size,
                    "entry": actual_entry
                }
                needs_protection_sync = (
                    size > previous_partial_size
                    or not self._has_exchange_protection(trade, position, size)
                )

                if size > previous_partial_size:
                    self.logger.debug(
                        f"{symbol} ENTRY PARTIALLY FILLED | size={size} avg_price={actual_entry} "
                        f"order_status={order_status}"
                    )

                if needs_protection_sync:
                    self._sync_partial_fill_protection(trade, size)
                self.storage.update_trade(trade["id"], updates)
                return

            self.logger.info(f"{symbol} ORDER FILLED")
            self.logger.info(f"{symbol} FILLED size={size} avg_price={actual_entry}")

            self.storage.update_trade(trade["id"], {
                "status": "FILLED",
                "filled_size": size,
                "remaining_size": size,
                "pending_filled_size": size,
                "entry": actual_entry
            })

            trade = self.storage.get_trade(trade["id"]) or trade
            desynced, desync_reason = self._is_signal_desynced(trade, actual_entry)
            if desynced:
                self.logger.warning(
                    f"{symbol} desynced from signal on fill | reason={desync_reason} | "
                    f"signal_entry={trade.get('signal_entry', trade.get('entry'))} actual_entry={actual_entry}"
                )
                self._abort_desynced_position(trade, size, desync_reason)
                return

            self._sync_tp_sl(trade, size)

    def _trade_age_seconds(self, trade):
        created_at = trade.get("created_at")
        if not created_at:
            return None

        try:
            created = datetime.fromisoformat(created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return int((datetime.now(timezone.utc) - created).total_seconds())
        except Exception:
            return None

    def _handle_filled(self, trade, position):
        symbol = trade["symbol"]

        size = 0
        current_entry = 0
        if isinstance(position, dict):
            size = float(position.get("size", 0))
            current_entry = float(position.get("avgPrice", 0) or 0)

        if size == 0:
            self._handle_close(trade)
            return

        if trade.get("close_reason_hint") == "PROTECTION_ABORT":
            if not trade.get("protection_abort_logged"):
                self.logger.warning(
                    f"{symbol} waiting for emergency close after protection abort | size={size}"
                )
                self.storage.update_trade(trade["id"], {
                    "protection_abort_logged": True
                })
            return

        desynced, desync_reason = self._is_signal_desynced(trade, current_entry)
        if desynced:
            self._abort_desynced_position(trade, size, desync_reason)
            return

        prev_size = float(trade.get("remaining_size", 0))
        if prev_size <= 0:
            self.storage.update_trade(trade["id"], {
                "remaining_size": size
            })
            return

        if size > prev_size:
            self.logger.debug(
                f"{symbol} POSITION GREW | old_size={prev_size} → new_size={size}"
            )

            self.storage.update_trade(trade["id"], {
                "filled_size": size,
                "remaining_size": size
            })
            trade = self.storage.get_trade(trade["id"]) or trade
            if int(trade.get("tp_hits", 0) or 0) == 0:
                self.logger.debug(
                    f"{symbol} position growth detected | resyncing SL/TP from signal"
                )
                self._sync_tp_sl(trade, size)
            else:
                self.logger.warning(
                    f"{symbol} protection was left untouched after position growth | "
                    f"manual review required"
                )
            return

        if size < prev_size:
            prev_hits = int(trade.get("tp_hits", 0))
            new_hits = self._count_completed_tps(trade, size)

            updates = {
                "remaining_size": size
            }

            if new_hits > prev_hits:
                updates["tp_hits"] = new_hits
                updates["tps"] = self._mark_hit_tps(trade.get("tps", []), new_hits)

                self.logger.info(
                    f"{symbol} TP HIT | tp={prev_hits + 1} | old_size={prev_size} → new_size={size}"
                )

            self.storage.update_trade(trade["id"], updates)
            return

        if not self._has_signal_protection_data(trade):
            if not trade.get("missing_signal_context_logged"):
                self.logger.warning(
                    f"{symbol} position has no signal SL/TP context | "
                    f"bot will not resync protection automatically"
                )
                self.storage.update_trade(trade["id"], {
                    "missing_signal_context_logged": True
                })
            return

        if not self._tp_orders_cover_size(trade, size):
            trade = self.storage.get_trade(trade["id"]) or trade
            if int(trade.get("tp_hits", 0) or 0) == 0:
                self.logger.warning(
                    f"{symbol} TP coverage mismatch | size={size} | resyncing SL/TP from signal"
                )
                self._sync_tp_sl(trade, size)
            else:
                self.logger.warning(
                    f"{symbol} TP coverage mismatch | size={size} | "
                    f"bot left protection untouched"
                )

    def _handle_close(self, trade):
        symbol = trade["symbol"]

        if trade.get("status") == "CLOSED":
            return

        close_summary = self.bybit.summarize_trade_close(trade)
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
                return

            self.logger.warning(
                f"{symbol} closing with partial exchange data after {pending_checks} checks | "
                f"closed_qty={close_summary.get('closed_qty', 0)} "
                f"target_qty={trade.get('filled_size', 0)}"
            )

        exit_price = close_summary.get("exit_price")
        if not exit_price:
            exit_price = float(trade.get("entry", 0))
        close_executions = close_summary.get("executions", [])
        pnl = close_summary.get("pnl")
        if pnl is None:
            pnl = self._calculate_pnl(trade, exit_price)
        reason = self._detect_reason(trade, exit_price, close_executions, close_summary)

        updates = {}
        if close_summary.get("tp_hits") is not None:
            updates["tp_hits"] = int(close_summary.get("tp_hits", 0) or 0)
            updates["tps"] = self._mark_hit_tps(trade.get("tps", []), updates["tp_hits"])
        if updates:
            self.storage.update_trade(trade["id"], updates)
            trade = self.storage.get_trade(trade["id"]) or trade

        self.storage.update_trade(trade["id"], {
            "close_pending_checks": 0
        })

        self.logger.info(f"{symbol} CLOSED (exchange confirmed)")
        self.logger.info(
            f"{symbol} FINAL CLOSE | exit={exit_price} | reason={reason}"
        )

        self.storage.close_trade(
            trade["id"],
            exit_price,
            pnl,
            reason
        )

    def _build_tp_distribution(self, trade, size):
        symbol = trade["symbol"]
        tps = trade["tps"]

        if not tps:
            return []

        raw_qty = size / len(tps)
        new_tps = []

        for index, tp in enumerate(tps):
            if index == len(tps) - 1:
                allocated = sum(item["qty"] for item in new_tps)
                qty = float(f"{size - allocated:.10f}")
            else:
                qty = self.bybit.normalize_qty(symbol, raw_qty)

            if qty <= 0:
                continue

            new_tps.append({
                "price": tp["price"],
                "qty": qty,
                "hit": False,
                "order_id": tp.get("order_id")
            })

        total = sum(tp["qty"] for tp in new_tps)
        filters = self.bybit.get_symbol_filters(symbol)
        residual = float(f"{size - total:.10f}")
        tolerance = max(filters["step"] / 2, 1e-9)

        if abs(residual) > tolerance and new_tps:
            self.logger.warning(
                f"{symbol} TP allocation residual too large | target={size} allocated={total} residual={residual}"
            )

        self.logger.debug(
            f"{symbol} TP allocation | target={size} allocated={total} residual={residual}"
        )

        return new_tps

    def _cancel_reduce_only_tps(self, trade):
        symbol = trade["symbol"]
        open_orders = self.bybit.get_open_orders(symbol)

        for order in open_orders:
            if not order.get("reduceOnly"):
                continue

            order_id = order.get("orderId")
            if not order_id:
                continue

            try:
                self.bybit.cancel_order(symbol, order_id)
            except Exception as e:
                self.logger.warning(f"{symbol} TP cancel failed | order_id={order_id} | error={e}")

    def _tp_orders_cover_size(self, trade, size):
        symbol = trade["symbol"]
        open_orders = self.bybit.get_open_orders(symbol)
        reduce_only_orders = [order for order in open_orders if order.get("reduceOnly")]

        if not reduce_only_orders:
            return False

        covered_qty = 0.0
        for order in reduce_only_orders:
            qty = float(order.get("qty", 0) or 0)
            leaves_qty = float(order.get("leavesQty", qty) or qty)
            covered_qty += leaves_qty if leaves_qty > 0 else qty

        step = self.bybit.get_symbol_filters(symbol)["step"]
        tolerance = max(step / 2, 1e-9)
        return covered_qty + tolerance >= size

    def _sync_tp_sl(self, trade, size):
        self._cancel_reduce_only_tps(trade)
        self._place_tp_sl(trade, size)

    def _sync_partial_fill_protection(self, trade, size):
        symbol = trade["symbol"]

        if size <= 0:
            return

        trade = self.storage.get_trade(trade["id"]) or trade

        if not self._has_signal_protection_data(trade):
            self._ensure_emergency_protection(
                trade,
                size,
                "partial_fill_without_signal_context"
            )
            return

        self.logger.debug(
            f"{symbol} partial fill protection sync | size={size}"
        )
        self._sync_tp_sl(trade, size)

    def _abort_desynced_position(self, trade, size, reason):
        symbol = trade["symbol"]

        try:
            self._cancel_reduce_only_tps(trade)
        except Exception as e:
            self.logger.warning(f"{symbol} failed to cancel stale TP orders before exit | error={e}")

        try:
            self.bybit.close_position_market(symbol, trade["side"], size)
        except Exception as e:
            self.logger.critical(
                f"{symbol} failed to close desynced position immediately | reason={reason} | error={e}"
            )
            return

        self.storage.update_trade(trade["id"], {
            "close_reason_hint": "DESYNC_ABORT",
            "desync_reason": reason,
            "close_pending_checks": 0
        })
        self.logger.warning(
            f"{symbol} desynced position is being closed immediately | reason={reason}"
        )

    def _ensure_emergency_protection(self, trade, size, reason):
        symbol = trade["symbol"]
        stop_price, emergency_used = self._resolve_stop_loss_price(trade)
        tp_price = self._resolve_emergency_tp_price(trade)

        last_attempt_price = float(trade.get("last_emergency_sl_price", 0) or 0)
        last_tp_price = float(trade.get("last_emergency_tp_price", 0) or 0)
        if (
            last_attempt_price == stop_price
            and last_tp_price == tp_price
            and trade.get("desynced")
            and self._tp_orders_cover_size(trade, size)
        ):
            return

        self._cancel_reduce_only_tps(trade)

        if not stop_price:
            self.logger.critical(f"{symbol} emergency protection failed: no valid stop price")
            return

        emergency_tps = []
        if tp_price:
            tp_order_id = self.bybit.place_limit_tp(
                symbol,
                trade["side"],
                size,
                tp_price
            )
            emergency_tps.append({
                "price": tp_price,
                "qty": size,
                "hit": False,
                "order_id": tp_order_id,
                "emergency": True
            })

        stop_result = self.bybit.place_stop_loss(
            symbol,
            trade["side"],
            size,
            stop_price
        )

        updates = {
            "desynced": True,
            "desync_reason": reason,
            "sl": stop_price,
            "sl_emergency": emergency_used,
            "last_emergency_sl_price": stop_price,
            "last_emergency_tp_price": tp_price,
            "remaining_size": size,
            "filled_size": size,
            "tps": emergency_tps,
        }
        self.storage.update_trade(trade["id"], updates)

        if stop_result:
            self.logger.warning(
                f"{symbol} emergency-only protection mode | "
                f"reason={reason} emergency_sl={stop_price} emergency_tp={tp_price}"
            )
        else:
            self.logger.warning(
                f"{symbol} emergency-only protection mode could not confirm SL | "
                f"reason={reason} attempted_sl={stop_price} emergency_tp={tp_price}"
            )

    def _has_exchange_protection(self, trade, position, size):
        symbol = trade["symbol"]
        stop_loss = ""
        if isinstance(position, dict):
            stop_loss = str(position.get("stopLoss", "") or "").strip()

        has_sl = stop_loss not in {"", "0", "0.0"}
        has_tp = self._tp_orders_cover_size(trade, size)
        return has_sl and has_tp

    def _has_complete_close_data(self, trade, close_summary):
        executions = close_summary.get("executions", [])
        closed_qty = float(close_summary.get("closed_qty", 0) or 0)
        target_qty = float(trade.get("filled_size", 0) or 0)

        if not executions or target_qty <= 0:
            return False

        step = self.bybit.get_symbol_filters(trade["symbol"])["step"]
        tolerance = max(step / 2, 1e-9)
        return closed_qty + tolerance >= target_qty

    def _place_tp_grid(self, trade, size):
        symbol = trade["symbol"]
        new_tps = self._build_tp_distribution(trade, size)

        for tp in new_tps:
            self.logger.debug(f"{symbol} TP -> {tp['price']} qty={tp['qty']}")
            tp_order_id = self.bybit.place_limit_tp(
                symbol,
                trade["side"],
                tp["qty"],
                tp["price"]
            )
            tp["order_id"] = tp_order_id

        updates = {
            "tps": new_tps
        }
        self.storage.update_trade(trade["id"], updates)
        return new_tps

    def _place_tp_sl(self, trade, size):
        symbol = trade["symbol"]
        self._cancel_reduce_only_tps(trade)
        new_tps = self._place_tp_grid(trade, size)

        stop_price = self._resolve_signal_stop_loss_price(trade)
        stop_result = self.bybit.place_stop_loss(
            symbol,
            trade["side"],
            size,
            stop_price
        )

        updates = {}
        if stop_price:
            updates["sl"] = stop_price
        if updates:
            self.storage.update_trade(trade["id"], updates)

        if stop_result:
            self.storage.update_trade(trade["id"], {
                "protection_sync_failures": 0,
                "protection_abort_logged": False,
            })
            self.logger.info(f"{symbol} protection synced")
        else:
            self.logger.warning(f"{symbol} TP synced, but SL was not confirmed")
            self._handle_protection_sync_failure(trade, size, stop_price)

    def _handle_protection_sync_failure(self, trade, size, stop_price):
        symbol = trade["symbol"]
        failures = int(trade.get("protection_sync_failures", 0) or 0) + 1
        self.storage.update_trade(trade["id"], {
            "protection_sync_failures": failures,
            "last_failed_sl_price": stop_price,
        })

        if failures < MAX_PROTECTION_FAILURES:
            self.logger.warning(
                f"{symbol} protection sync failed | attempt={failures}/{MAX_PROTECTION_FAILURES} "
                f"sl={stop_price}"
            )
            return

        self.logger.critical(
            f"{symbol} protection sync failed too many times | aborting trade | "
            f"attempts={failures} sl={stop_price}"
        )
        self._abort_unprotected_trade(trade, size)

    def _abort_unprotected_trade(self, trade, size):
        symbol = trade["symbol"]
        order_id = trade.get("order_id")

        try:
            self._cancel_reduce_only_tps(trade)
        except Exception as e:
            self.logger.warning(f"{symbol} failed to cancel TP orders before abort | error={e}")

        if order_id:
            try:
                self.bybit.cancel_order(symbol, order_id)
            except Exception as e:
                self.logger.warning(f"{symbol} failed to cancel entry order during abort | error={e}")

        position = self.bybit.get_position(symbol)
        current_size = float(position.get("size", 0) or 0) if isinstance(position, dict) else 0.0

        if current_size <= 0:
            self.storage.close_trade(
                trade["id"],
                exit_price=0,
                pnl=0,
                reason="PROTECTION_ABORT_NO_FILL"
            )
            self.logger.warning(f"{symbol} aborted before fill because protection could not be set")
            return

        try:
            self.bybit.close_position_market(symbol, trade["side"], current_size)
        except Exception as e:
            self.logger.critical(
                f"{symbol} failed to emergency-close unprotected position | size={current_size} | error={e}"
            )
            return

        self.storage.update_trade(trade["id"], {
            "status": "FILLED",
            "filled_size": current_size,
            "remaining_size": current_size,
            "close_reason_hint": "PROTECTION_ABORT",
            "close_pending_checks": 0,
        })
        self.logger.warning(
            f"{symbol} unprotected position is being closed immediately | size={current_size}"
        )

    def _resolve_signal_stop_loss_price(self, trade):
        symbol = trade["symbol"]
        intended_sl = float(trade.get("sl_initial", trade.get("sl", 0)) or 0)

        if intended_sl <= 0:
            return intended_sl

        return self.bybit.normalize_price(symbol, intended_sl)

    def _has_signal_protection_data(self, trade):
        intended_sl = float(trade.get("sl_initial", trade.get("sl", 0)) or 0)
        tps = trade.get("tps", []) or []
        return intended_sl > 0 and any(float(tp.get("price", 0) or 0) > 0 for tp in tps)

    def _resolve_emergency_tp_price(self, trade):
        symbol = trade["symbol"]
        side = trade["side"]
        position = self.bybit.get_position(symbol)
        avg_price = float(position.get("avgPrice", 0) or 0) if isinstance(position, dict) else 0.0
        last_price = float(self.bybit.get_last_price(symbol) or 0)
        reference_price = avg_price or last_price or float(trade.get("entry", 0) or 0)

        if reference_price <= 0:
            return None

        if side == "LONG":
            tp_base = max(reference_price, last_price) if last_price > 0 else reference_price
            return self.bybit.normalize_price(symbol, tp_base * (1 + self._emergency_tp_pct()))

        tp_base = min(reference_price, last_price) if last_price > 0 else reference_price
        return self.bybit.normalize_price(symbol, tp_base * (1 - self._emergency_tp_pct()))

    def _is_signal_desynced(self, trade, current_entry):
        symbol = trade["symbol"]
        side = trade["side"]
        signal_entry = float(trade.get("signal_entry", trade.get("entry", 0)) or 0)
        sl_initial = float(trade.get("sl_initial", trade.get("sl", 0)) or 0)
        tps = trade.get("tps", []) or []

        if current_entry <= 0:
            return False, None

        if signal_entry > 0:
            if side == "LONG":
                unfavorable_move = current_entry > signal_entry
                deviation = (current_entry - signal_entry) / signal_entry
            else:
                unfavorable_move = current_entry < signal_entry
                deviation = (signal_entry - current_entry) / signal_entry

            if unfavorable_move and deviation >= self._max_signal_desync_pct():
                return True, f"unfavorable entry deviation {deviation * 100:.2f}%"

        if side == "LONG":
            if sl_initial > 0 and sl_initial >= current_entry:
                return True, f"signal SL {sl_initial} invalid for actual entry {current_entry}"
            if any(float(tp.get('price', 0) or 0) <= current_entry for tp in tps):
                return True, f"signal TP invalid for actual entry {current_entry}"
        else:
            if sl_initial > 0 and sl_initial <= current_entry:
                return True, f"signal SL {sl_initial} invalid for actual entry {current_entry}"
            if any(float(tp.get('price', 0) or 0) >= current_entry and float(tp.get('price', 0) or 0) > 0 for tp in tps):
                return True, f"signal TP invalid for actual entry {current_entry}"

        return False, None

    def _count_completed_tps(self, trade, current_size):
        filled_size = float(trade.get("filled_size", 0))
        tps = trade.get("tps", [])

        if filled_size <= 0 or not tps:
            return int(trade.get("tp_hits", 0))

        reduced_size = max(0.0, filled_size - current_size)
        symbol = trade["symbol"]
        step = self.bybit.get_symbol_filters(symbol)["step"]
        tolerance = max(step / 2, 1e-9)

        completed = 0
        cumulative = 0.0

        for tp in tps:
            cumulative += float(tp.get("qty", 0))
            if reduced_size + tolerance >= cumulative:
                completed += 1

        return completed

    def _mark_hit_tps(self, tps, completed_hits):
        updated_tps = []

        for index, tp in enumerate(tps):
            updated_tp = dict(tp)
            updated_tp["hit"] = index < completed_hits
            updated_tps.append(updated_tp)

        return updated_tps

    def _calculate_pnl(self, trade, exit_price):
        entry = float(trade.get("entry", 0))
        side = trade.get("side")
        size = float(trade.get("filled_size", 0))

        if side == "LONG":
            return (exit_price - entry) * size
        else:
            return (entry - exit_price) * size

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
