from classes.telegram.parser import parse_signal, parse_tp_hit
import asyncio
import threading


class Worker:
    def __init__(self, bybit, storage, execution, logger):
        self.bybit = bybit
        self.storage = storage
        self.execution = execution
        self.logger = logger
        self._message_lock = threading.Lock()
        self._inflight_message_ids = set()
        self._symbol_lock_guard = threading.Lock()
        self._symbol_locks = {}

    def _get_symbol_lock(self, symbol):
        with self._symbol_lock_guard:
            lock = self._symbol_locks.get(symbol)
            if lock is None:
                lock = threading.Lock()
                self._symbol_locks[symbol] = lock
            return lock

    async def handle_message(self, message, source="telegram"):
        text = message.text or ""
        preview = text.splitlines()[0][:120] if text else "<empty>"
        self.logger.debug(
            f"message received | source={source} | message_id={getattr(message, 'id', None)} | preview={preview}"
        )

        signal = parse_signal(text)
        if signal:
            self.logger.debug(
                f"message classified | source={source} | message_id={getattr(message, 'id', None)} | type=signal | "
                f"symbol={signal['symbol']} side={signal['side']} entry={signal['entry']}"
            )
            await asyncio.to_thread(self.handle_signal, signal, message.id, source)
            return

        tp_event = parse_tp_hit(text)
        if tp_event:
            self.logger.debug(
                f"message classified | source={source} | message_id={getattr(message, 'id', None)} | type=tp_event | "
                f"symbol={tp_event.get('symbol')} tp_index={tp_event.get('tp_index')} move_to_be={tp_event.get('move_to_be')}"
            )
            await self._handle_tp_event(message, tp_event)
            return

        self.logger.debug(
            f"message classified | source={source} | message_id={getattr(message, 'id', None)} | type=ignored"
        )

    def handle_signal(self, signal, message_id, source="telegram"):
        symbol = signal["symbol"]

        with self._message_lock:
            if message_id in self._inflight_message_ids:
                self.logger.warning(
                    f"{symbol} signal rejected | source={source} | message_id={message_id} | "
                    f"reason=message_already_processing"
                )
                return
            self._inflight_message_ids.add(message_id)

        try:
            symbol_lock = self._get_symbol_lock(symbol)
            with symbol_lock:
                existing_by_message = self.storage.find_by_message_id(message_id)
                if existing_by_message:
                    self.logger.warning(
                        f"{symbol} signal rejected | source={source} | message_id={message_id} | "
                        f"reason=duplicate_message_id | existing_trade_id={existing_by_message.get('id')}"
                    )
                    return

                existing = self.storage.find_active_by_symbol(symbol)
                if existing:
                    self.logger.warning(
                        f"{symbol} signal rejected | source={source} | message_id={message_id} | reason=active_trade_exists"
                    )
                    return

                exchange_locked, exchange_lock_reason = self.bybit.has_open_entry_or_position(symbol)
                if exchange_locked:
                    self.logger.warning(
                        f"{symbol} signal rejected | source={source} | message_id={message_id} | "
                        f"reason=exchange_symbol_locked | lock={exchange_lock_reason}"
                    )
                    return

                balance = self.bybit.get_balance()

                order = self.execution.prepare_order(signal, balance)
                if not order:
                    reason = getattr(self.execution, "last_reject_reason", "execution_rejected")
                    self.logger.warning(
                        f"{symbol} signal rejected | source={source} | message_id={message_id} | reason={reason}"
                    )
                    return

                too_far, market_price, deviation = self.execution.has_excessive_favorable_move(
                    symbol,
                    order["side"],
                    order["price"]
                )
                if too_far:
                    self.logger.warning(
                        f"{symbol} signal rejected | source={source} | message_id={message_id} | "
                        f"reason=market_moved_too_far | entry={order['price']} market={market_price} "
                        f"deviation_pct={deviation * 100:.2f}"
                    )
                    return

                try:
                    order_id = self.execution.place_entry(order)
                except Exception as e:
                    self.logger.error(
                        f"{self._format_exchange_error(symbol, e)} | source={source} | message_id={message_id}"
                    )
                    return

                trade_id = self.storage.create_trade({
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "status": "PENDING",
                    "entry": order["price"],
                    "signal_entry": order["price"],
                    "sl": order["sl"],
                    "tps": [
                        {"price": tp, "qty": order["size"] / len(order["tps"]), "hit": False}
                        for tp in order["tps"]
                    ],
                    "filled_size": 0,
                    "remaining_size": 0,
                    "order_id": order_id,
                    "tp_hits": 0,
                    "be_moved": False,
                    "message_id": message_id
                })

                self.logger.info(
                    f"{symbol} signal accepted | source={source} | message_id={message_id} | "
                    f"trade_id={trade_id} order_id={order_id} size={order['size']} entry={order['price']}"
                )
        finally:
            with self._message_lock:
                self._inflight_message_ids.discard(message_id)

    def _format_exchange_error(self, symbol, error):
        text = str(error)
        lowered = text.lower()

        if "110007" in text or "ab not enough for new order" in lowered:
            return (
                f"{symbol} order rejected by exchange: insufficient available balance or margin "
                f"for a new order"
            )

        return f"{symbol} order rejected by exchange: {text}"

    async def _handle_tp_event(self, message, tp_event):
        reply = await message.get_reply_message()

        if not reply:
            self.logger.warning("TP event without reply → skip")
            return

        trade = self.storage.find_by_message_id(reply.id)

        if not trade:
            self.logger.warning("No trade found for reply → skip")
            return

        tp_index = tp_event.get("tp_index")
        if tp_index is not None:
            tp_hits = max(int(trade.get("tp_hits", 0) or 0), tp_index + 1)
            tps = self._mark_hit_tps(trade.get("tps", []), tp_hits)
            filled_size = float(trade.get("filled_size", 1) or 1)
            remaining_fraction = max(0.0, 1 - (tp_hits / max(len(tps), 1)))
            self.storage.update_trade(trade["id"], {
                "tp_hits": tp_hits,
                "tps": tps,
                "remaining_size": round(filled_size * remaining_fraction, 8),
            })
            self.logger.debug(
                f"{trade['symbol']} TP event recorded | trade_id={trade['id']} | tp={tp_hits}"
            )

        if tp_event.get("move_to_be") and not trade.get("be_moved"):
            self._move_sl_to_be(trade)

    def _move_sl_to_be(self, trade):
        symbol = trade["symbol"]
        entry = trade["entry"]

        be_price = self.bybit.normalize_price(symbol, entry)

        result = self.bybit.place_stop_loss(
            symbol,
            trade["side"],
            trade.get("remaining_size") or trade.get("filled_size"),
            be_price
        )

        if result:
            self.logger.info(
                f"{symbol} MOVE SL → BE (signal) | entry={entry} | new_sl={be_price}"
            )
            self.storage.update_trade(trade["id"], {
                "be_moved": True,
                "sl": be_price
            })
            return

        self.logger.warning(
            f"{symbol} MOVE SL → BE skipped: exchange did not confirm update"
        )

    def _mark_hit_tps(self, tps, completed_hits):
        updated_tps = []

        for index, tp in enumerate(tps):
            updated_tp = dict(tp)
            updated_tp["hit"] = index < completed_hits
            updated_tps.append(updated_tp)

        return updated_tps
