from classes.config import MAX_POSITION_MULTIPLIER, MAX_ENTRY_DEVIATION_PCT


class ExecutionService:
    def __init__(self, bybit, storage, logger):
        self.bybit = bybit
        self.storage = storage
        self.logger = logger
        self.MAX_POSITION_MULTIPLIER = MAX_POSITION_MULTIPLIER
        self.MAX_ENTRY_DEVIATION_PCT = MAX_ENTRY_DEVIATION_PCT
        self.last_reject_reason = "execution_rejected"

    def calculate_rr(self, entry, sl, tp, side):
        if side == "LONG":
            risk = entry - sl
            reward = tp - entry
        else:
            risk = sl - entry
            reward = entry - tp

        if risk <= 0:
            return 0

        return reward / risk

    def prepare_order(self, signal, balance):
        self.last_reject_reason = "execution_rejected"
        symbol = signal["symbol"]
        side = signal["side"]
        entry = float(signal["entry"])
        sl = float(signal["sl"])
        tps = signal.get("tps", [])

        if not tps:
            self.last_reject_reason = "no_tp"
            self.logger.warning(f"{symbol}: no TP")
            return None

        if side == "LONG" and sl >= entry:
            self.last_reject_reason = "invalid_long_sl"
            return None

        if side == "SHORT" and sl <= entry:
            self.last_reject_reason = "invalid_short_sl"
            return None

        risk_pct = float(signal.get("risk", 0.01) or 0)
        risk_amount = balance * risk_pct
        if risk_amount <= 0:
            self.last_reject_reason = "invalid_risk"
            self.logger.warning(
                f"{symbol}: invalid risk configuration | balance={balance} risk_pct={risk_pct}"
            )
            return None

        distance = abs(entry - sl)
        if distance == 0:
            self.last_reject_reason = "invalid_stop_distance"
            return None

        raw_qty = risk_amount / distance
        max_notional = balance * self.MAX_POSITION_MULTIPLIER

        try:
            max_qty_by_notional = self.bybit.normalize_qty(symbol, max_notional / entry)
        except Exception as e:
            self.last_reject_reason = "symbol_unavailable_on_exchange"
            self.logger.warning(
                f"{symbol}: symbol unavailable or unsupported on current exchange source | error={e}"
            )
            return None

        if max_qty_by_notional == 0:
            self.last_reject_reason = "size_below_exchange_minimum"
            self.logger.warning(
                f"{symbol}: size below exchange minimum | balance={balance} "
                f"max_notional={max_notional} entry={entry}"
            )
            return None

        capped_qty = min(raw_qty, max_qty_by_notional)
        qty = self.bybit.normalize_qty(symbol, capped_qty)

        if qty == 0:
            self.last_reject_reason = "size_below_exchange_minimum"
            self.logger.warning(
                f"{symbol}: size below exchange minimum | raw_qty={raw_qty:.10f} "
                f"capped_qty={capped_qty:.10f}"
            )
            return None

        raw_notional = raw_qty * entry
        final_notional = qty * entry

        if qty < raw_qty:
            self.logger.debug(
                f"{symbol}: position capped | raw_notional={raw_notional:.4f} "
                f"max_notional={max_notional:.4f} final_notional={final_notional:.4f}"
            )

        return {
            "symbol": symbol,
            "side": side,
            "price": entry,
            "size": qty,
            "tps": tps,
            "sl": sl
        }

    def has_excessive_favorable_move(self, symbol, side, entry):
        market_price = self.bybit.get_last_price(symbol)
        if not market_price or entry <= 0:
            return False, market_price, 0.0

        if side == "LONG":
            deviation = (market_price - entry) / entry
            too_far = market_price > entry and deviation >= self.MAX_ENTRY_DEVIATION_PCT
        else:
            deviation = (entry - market_price) / entry
            too_far = market_price < entry and deviation >= self.MAX_ENTRY_DEVIATION_PCT

        return too_far, market_price, deviation

    def place_entry(self, order):
        symbol = order["symbol"]
        side = order["side"]
        price = order["price"]
        size = order["size"]

        self.logger.info(f"{symbol} placing LIMIT {size} @ {price}")

        res = self.bybit.client.place_order(
            category="linear",
            symbol=symbol,
            side="Buy" if side == "LONG" else "Sell",
            orderType="Limit",
            qty=str(size),
            price=str(price),
            timeInForce="GTC"
        )

        return res["result"]["orderId"]

    def _build_tp_distribution(self, symbol, size, tps):
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

    def on_filled(self, trade_id, trade):
        symbol = trade["symbol"]

        position = self.bybit.get_position(symbol)

        real_size = float(position.get("size", 0))
        avg_price = float(position.get("avgPrice", 0))

        if real_size <= 0:
            self.logger.warning(f"{symbol}: no position on fill")
            return

        self.logger.info(f"{symbol} FILLED size={real_size} avg_price={avg_price}")

        tps = trade.get("tps", [])
        if not tps:
            return

        new_tps = self._build_tp_distribution(symbol, real_size, tps)

        for tp in new_tps:
            self.logger.debug(f"{symbol} TP -> {tp['price']} qty={tp['qty']}")
            tp_order_id = self.bybit.place_limit_tp(symbol, trade["side"], tp["qty"], tp["price"])
            tp["order_id"] = tp_order_id

        self.bybit.place_stop_loss(symbol, trade["side"], real_size, trade["sl"])

        self.storage.update_trade(trade_id, {
            "status": "FILLED",
            "entry": avg_price,
            "filled_size": real_size,
            "remaining_size": real_size,
            "tps": new_tps
        })

        self.logger.info(f"{symbol} protection placed")
