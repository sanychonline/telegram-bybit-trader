import math
from datetime import datetime, timezone
from pybit.unified_trading import HTTP
from classes.config import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET
from classes.reporting.health_state import touch


class BybitClient:
    def __init__(self, logger=None):
        self.client = HTTP(
            testnet=BYBIT_TESTNET,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )
        self.logger = logger
        self.instrument_cache = {}
        self.filters_cache = {}

    def get_balance(self):
        res = self.client.get_wallet_balance(accountType="UNIFIED")
        touch("bybit")
        return float(res["result"]["list"][0]["totalAvailableBalance"])

    def get_account_summary(self):
        try:
            res = self.client.get_wallet_balance(accountType="UNIFIED")
            account = res["result"]["list"][0]
            touch("bybit")
            return {
                "available_balance": float(account.get("totalAvailableBalance", 0) or 0),
                "wallet_balance": float(account.get("totalWalletBalance", 0) or 0),
                "equity": float(account.get("totalEquity", 0) or 0),
            }
        except Exception:
            return {
                "available_balance": 0.0,
                "wallet_balance": 0.0,
                "equity": 0.0,
            }

    def get_last_price(self, symbol):
        try:
            res = self.client.get_tickers(
                category="linear",
                symbol=symbol
            )
            tickers = res["result"]["list"]
            if not tickers:
                return None
            touch("bybit")
            return float(tickers[0]["lastPrice"])
        except Exception:
            return None

    def get_instrument(self, symbol):
        if symbol in self.instrument_cache:
            return self.instrument_cache[symbol]

        res = self.client.get_instruments_info(
            category="linear",
            symbol=symbol
        )

        info = res["result"]["list"][0]
        touch("bybit")
        self.instrument_cache[symbol] = info
        return info

    def get_symbol_filters(self, symbol):
        if symbol in self.filters_cache:
            return self.filters_cache[symbol]

        info = self.get_instrument(symbol)

        filters = {
            "min_qty": float(info["lotSizeFilter"]["minOrderQty"]),
            "step": float(info["lotSizeFilter"]["qtyStep"]),
            "tick": float(info["priceFilter"]["tickSize"])
        }

        self.filters_cache[symbol] = filters
        return filters

    def normalize_qty(self, symbol, qty):
        filters = self.get_symbol_filters(symbol)

        step = filters["step"]
        min_qty = filters["min_qty"]

        normalized = math.floor(qty / step) * step
        normalized = float(f"{normalized:.10f}")

        if normalized < min_qty:
            return 0

        return normalized

    def normalize_price(self, symbol, price):
        filters = self.get_symbol_filters(symbol)

        tick = filters["tick"]

        normalized = math.floor(price / tick) * tick
        return float(f"{normalized:.10f}")

    def place_market_order(self, symbol, side, qty):
        qty = self.normalize_qty(symbol, qty)

        if qty == 0:
            raise ValueError("Qty too small")

        return self.client.place_order(
            category="linear",
            symbol=symbol,
            side="Buy" if side == "LONG" else "Sell",
            orderType="Market",
            qty=str(qty)
        )

    def close_position_market(self, symbol, side, qty):
        qty = self.normalize_qty(symbol, qty)

        if qty == 0:
            raise ValueError("Qty too small")

        return self.client.place_order(
            category="linear",
            symbol=symbol,
            side="Sell" if side == "LONG" else "Buy",
            orderType="Market",
            qty=str(qty),
            reduceOnly=True
        )

    def place_limit_tp(self, symbol, side, qty, price):
        qty = self.normalize_qty(symbol, qty)
        price = self.normalize_price(symbol, price)

        if qty == 0:
            return None

        res = self.client.place_order(
            category="linear",
            symbol=symbol,
            side="Sell" if side == "LONG" else "Buy",
            orderType="Limit",
            qty=str(qty),
            price=str(price),
            reduceOnly=True,
            timeInForce="GTC"
        )

        return res["result"].get("orderId")

    def place_stop_loss(self, symbol, side, qty, price):
        try:
            price = self.normalize_price(symbol, price)
            res = self.client.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=str(price)
            )

            if self.logger:
                self.logger.debug(
                    f"{symbol} STOP LOSS UPDATED | side={side} qty={qty} price={price}"
                )

            return res

        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"{symbol} STOP LOSS UPDATE FAILED | side={side} qty={qty} price={price} | error={e}"
                )
            else:
                print(f"SL error: {e}")
            return None

    def get_order(self, symbol, order_id):
        try:
            res = self.client.get_open_orders(
                category="linear",
                symbol=symbol,
                orderId=order_id
            )

            orders = res["result"]["list"]

            if orders:
                return orders[0]

            res = self.client.get_order_history(
                category="linear",
                symbol=symbol,
                orderId=order_id
            )

            history = res["result"]["list"]

            if history:
                return history[0]

            return None

        except Exception as e:
            print(f"get_order error: {e}")
            return None

    def cancel_all_orders(self, symbol):
        return self.client.cancel_all_orders(
            category="linear",
            symbol=symbol
        )

    def cancel_order(self, symbol, order_id):
        return self.client.cancel_order(
            category="linear",
            symbol=symbol,
            orderId=order_id
        )

    def get_position(self, symbol):
        try:
            res = self.client.get_positions(
                category="linear",
                symbol=symbol
            )

            positions = res["result"]["list"]
            touch("bybit")

            if not positions:
                return {"size": 0}

            return positions[0]

        except Exception:
            return {"size": 0}

    def get_all_positions(self):
        try:
            res = self.client.get_positions(category="linear")
            touch("bybit")
            return res["result"]["list"]
        except Exception:
            return []

    def get_open_orders(self, symbol):
        try:
            res = self.client.get_open_orders(
                category="linear",
                symbol=symbol
            )
            touch("bybit")
            return res["result"]["list"]
        except Exception:
            return []

    def has_open_entry_or_position(self, symbol):
        position = self.get_position(symbol)
        size = float(position.get("size", 0) or 0) if isinstance(position, dict) else 0.0
        if size > 0:
            return True, "position"

        open_orders = self.get_open_orders(symbol)
        for order in open_orders:
            if order.get("reduceOnly"):
                continue

            status = order.get("orderStatus") or order.get("status")
            if status in ["New", "PartiallyFilled", "Untriggered"]:
                return True, "entry_order"

        return False, None

    def get_all_open_orders(self):
        try:
            res = self.client.get_open_orders(category="linear")
            touch("bybit")
            return res["result"]["list"]
        except Exception:
            return []

    def ping(self):
        self.client.get_wallet_balance(accountType="UNIFIED")
        touch("bybit")
        return True

    def get_last_execution_price(self, symbol):
        try:
            closes = self.get_close_executions(symbol)

            if not closes:
                return None

            total_qty = 0
            total_value = 0

            for e in closes:
                price = float(e["execPrice"])
                qty = float(e["execQty"])

                total_qty += qty
                total_value += price * qty

            if total_qty > 0:
                return total_value / total_qty

            return None

        except Exception as e:
            print(f"Execution fetch error: {e}")
            return None

    def _parse_trade_time(self, value):
        if not value:
            return None

        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    def _parse_exec_time(self, execution):
        raw = execution.get("execTime")

        if raw in (None, ""):
            return None

        try:
            return int(raw)
        except Exception:
            return None

    def get_trade_close_executions(self, trade, limit=100):
        symbol = trade.get("symbol")
        if not symbol:
            return []

        executions = self.get_close_executions(symbol, limit=limit)
        created_at_ms = self._parse_trade_time(trade.get("created_at"))

        filtered = []
        for execution in executions:
            exec_time = self._parse_exec_time(execution)
            if created_at_ms and exec_time and exec_time < created_at_ms:
                continue
            filtered.append(execution)

        return filtered

    def get_trade_exit_price(self, trade, limit=100):
        executions = self.get_trade_close_executions(trade, limit=limit)

        if not executions:
            return None

        target_qty = float(trade.get("filled_size", 0) or 0)
        total_qty = 0.0
        total_value = 0.0

        for execution in sorted(executions, key=lambda item: self._parse_exec_time(item) or 0):
            exec_qty = float(execution.get("execQty", 0) or 0)
            exec_price = float(execution.get("execPrice", 0) or 0)

            if exec_qty <= 0 or exec_price <= 0:
                continue

            remaining = target_qty - total_qty if target_qty > 0 else exec_qty
            used_qty = min(exec_qty, remaining) if target_qty > 0 else exec_qty

            if used_qty <= 0:
                continue

            total_qty += used_qty
            total_value += exec_price * used_qty

            if target_qty > 0 and total_qty >= target_qty:
                break

        if total_qty <= 0:
            return None

        return total_value / total_qty

    def summarize_trade_close(self, trade, limit=100, tolerance=0.003):
        executions = self.get_trade_close_executions(trade, limit=limit)

        if not executions:
            return {
                "executions": [],
                "exit_price": None,
                "pnl": None,
                "closed_qty": 0.0,
                "tp_hits": 0,
                "tp_hit_indices": [],
                "stop_exit_qty": 0.0,
                "manual_exit_qty": 0.0,
                "reduce_only_exit_qty": 0.0,
            }

        entry = float(trade.get("entry", 0) or 0)
        side = trade.get("side")
        target_qty = float(trade.get("filled_size", 0) or 0)
        tps = trade.get("tps", []) or []
        tp_order_ids = {
            str(tp.get("order_id"))
            for tp in tps
            if tp.get("order_id")
        }

        total_qty = 0.0
        total_value = 0.0
        total_pnl = 0.0
        stop_exit_qty = 0.0
        manual_exit_qty = 0.0
        reduce_only_exit_qty = 0.0
        tp_hit_indices = set()
        used_executions = []

        for execution in sorted(executions, key=lambda item: self._parse_exec_time(item) or 0):
            exec_qty = float(execution.get("execQty", 0) or 0)
            exec_price = float(execution.get("execPrice", 0) or 0)

            if exec_qty <= 0 or exec_price <= 0:
                continue

            remaining = target_qty - total_qty if target_qty > 0 else exec_qty
            used_qty = min(exec_qty, remaining) if target_qty > 0 else exec_qty

            if used_qty <= 0:
                continue

            total_qty += used_qty
            total_value += exec_price * used_qty

            if side == "LONG":
                total_pnl += (exec_price - entry) * used_qty
            else:
                total_pnl += (entry - exec_price) * used_qty

            stop_order_type = str(execution.get("stopOrderType", "") or "")
            order_type = str(execution.get("orderType", "") or "")
            exec_type = str(execution.get("execType", "") or "")
            reduce_only = bool(execution.get("reduceOnly"))

            is_stop_exit = stop_order_type in {"StopLoss", "Stop", "TrailingStop"} or exec_type in {
                "BustTrade",
                "SessionSettlePnL",
                "Settle",
            }

            matched_tp = None
            exec_order_id = str(execution.get("orderId", "") or "")
            for index, tp in enumerate(tps, start=1):
                tp_order_id = str(tp.get("order_id", "") or "")
                if tp_order_id and exec_order_id and tp_order_id == exec_order_id:
                    matched_tp = index
                    break
                tp_price = float(tp.get("price", 0) or 0)
                if tp_price and abs(exec_price - tp_price) / tp_price < tolerance:
                    matched_tp = index
                    break

            if matched_tp:
                tp_hit_indices.add(matched_tp)

            if is_stop_exit:
                stop_exit_qty += used_qty
            elif exec_order_id and exec_order_id in tp_order_ids:
                reduce_only_exit_qty += used_qty
            elif order_type in {"Market", "Limit"} and not reduce_only:
                manual_exit_qty += used_qty
            elif reduce_only:
                reduce_only_exit_qty += used_qty

            used_execution = dict(execution)
            used_execution["_usedQty"] = used_qty
            used_execution["_matchedTp"] = matched_tp
            used_execution["_isStopExit"] = is_stop_exit
            used_execution["_isManualExit"] = order_type in {"Market", "Limit"} and not reduce_only
            used_execution["_isReduceOnlyExit"] = reduce_only
            used_executions.append(used_execution)

            if target_qty > 0 and total_qty >= target_qty:
                break

        exit_price = (total_value / total_qty) if total_qty > 0 else None

        return {
            "executions": used_executions,
            "exit_price": exit_price,
            "pnl": total_pnl if total_qty > 0 else None,
            "closed_qty": total_qty,
            "tp_hits": len(tp_hit_indices),
            "tp_hit_indices": sorted(tp_hit_indices),
            "stop_exit_qty": stop_exit_qty,
            "manual_exit_qty": manual_exit_qty,
            "reduce_only_exit_qty": reduce_only_exit_qty,
        }

    def get_close_executions(self, symbol, limit=50):
        try:
            res = self.client.get_executions(
                category="linear",
                symbol=symbol,
                limit=limit
            )

            executions = res["result"]["list"]

            return [
                e for e in executions
                if e.get("reduceOnly") or float(e.get("closedSize", 0) or 0) > 0
            ]

        except Exception as e:
            print(f"Close executions fetch error: {e}")
            return []
