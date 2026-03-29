from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import TZ


class DashboardDataService:
    def __init__(self, bybit, storage):
        self.bybit = bybit
        self.storage = storage

    @property
    def local_tz(self):
        try:
            return ZoneInfo(self.storage.get_app_setting("tz", TZ))
        except Exception:
            return ZoneInfo(TZ)

    def _closed_summary_exchange(self, trades):
        wins = 0
        losses = 0
        breakevens = 0
        realized = 0.0
        closed_rows = []

        for trade in trades:
            pnl = float(trade.get("pnl", 0) or 0)
            reason = trade.get("close_reason")
            realized += pnl

            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            else:
                breakevens += 1

            closed_rows.append({
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "reason": reason,
                "tp_hits": int(trade.get("tp_hits", 0) or 0),
                "pnl": round(pnl, 4),
                "updated_at": trade.get("closed_at") or trade.get("updated_at"),
            })

        closed_rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return wins, losses, breakevens, realized, closed_rows

    def _range_bounds(self, range_key):
        now = datetime.now(self.local_tz)
        if range_key == "today":
            return datetime(now.year, now.month, now.day, tzinfo=self.local_tz), None
        if range_key == "current_month":
            return datetime(now.year, now.month, 1, tzinfo=self.local_tz), None
        if range_key == "month":
            return now - timedelta(days=30), None
        if range_key == "quarter":
            return now - timedelta(days=91), None
        if range_key == "previous_month":
            current_month_start = datetime(now.year, now.month, 1, tzinfo=self.local_tz)
            previous_month_end = current_month_start
            previous_month_start = datetime(
                previous_month_end.year - (1 if previous_month_end.month == 1 else 0),
                12 if previous_month_end.month == 1 else previous_month_end.month - 1,
                1,
                tzinfo=self.local_tz,
            )
            return previous_month_start, previous_month_end
        if range_key == "half_year":
            return now - timedelta(days=183), None
        if range_key == "year":
            return now - timedelta(days=365), None
        if range_key == "previous_year":
            return (
                datetime(now.year - 1, 1, 1, tzinfo=self.local_tz),
                datetime(now.year, 1, 1, tzinfo=self.local_tz),
            )
        return None, None

    def _filter_exchange_closed_trades(self, trades, range_key):
        start, end = self._range_bounds(range_key)
        if start is None and end is None:
            return list(trades)

        filtered = []
        for trade in trades:
            raw = trade.get("closed_at") or trade.get("updated_at")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                dt = dt.astimezone(self.local_tz)
            except Exception:
                continue
            if start is not None and dt < start:
                continue
            if end is not None and dt >= end:
                continue
            filtered.append(trade)
        return filtered

    def _filter_signal_events(self, events, range_key):
        start, end = self._range_bounds(range_key)
        if start is None and end is None:
            return list(events)

        filtered = []
        for event in events:
            raw = event.get("created_at")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                dt = dt.astimezone(self.local_tz)
            except Exception:
                continue
            if start is not None and dt < start:
                continue
            if end is not None and dt >= end:
                continue
            filtered.append(event)
        return filtered

    def _filter_local_trades(self, trades, range_key):
        start, end = self._range_bounds(range_key)
        if start is None and end is None:
            return list(trades)

        filtered = []
        for trade in trades:
            raw = trade.get("created_at") or trade.get("updated_at")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                dt = dt.astimezone(self.local_tz)
            except Exception:
                continue
            if start is not None and dt < start:
                continue
            if end is not None and dt >= end:
                continue
            filtered.append(trade)
        return filtered

    def _active_summary(self):
        positions = []
        for position in self.bybit.get_all_positions():
            try:
                size = float(position.get("size", 0) or 0)
            except Exception:
                size = 0.0
            if size <= 0:
                continue
            positions.append(position)

        realized_total = 0.0
        unrealized_total = 0.0
        active_rows = []

        for position in positions:
            symbol = position.get("symbol")
            side = "LONG" if str(position.get("side") or "").upper() == "BUY" else "SHORT"
            entry = float(position.get("avgPrice", 0) or 0)

            stop_loss = position.get("stopLoss")
            try:
                sl = float(stop_loss or 0) if stop_loss not in (None, "") else 0.0
            except Exception:
                sl = 0.0

            open_orders = self.bybit.get_open_orders(symbol) if symbol else []
            tp_candidates = []
            for order in open_orders:
                try:
                    reduce_only = bool(order.get("reduceOnly"))
                    order_type = str(order.get("orderType") or "")
                    order_price = float(order.get("price", 0) or 0)
                    status = str(order.get("orderStatus") or order.get("status") or "")
                except Exception:
                    continue

                if not reduce_only or order_type != "Limit" or order_price <= 0:
                    continue
                if status not in {"New", "PartiallyFilled", "Untriggered"}:
                    continue
                tp_candidates.append(order_price)

            if side == "LONG":
                tp_candidates = [price for price in tp_candidates if price > entry]
                next_tp = min(tp_candidates) if tp_candidates else None
            else:
                tp_candidates = [price for price in tp_candidates if price < entry]
                next_tp = max(tp_candidates) if tp_candidates else None

            try:
                realized = float(
                    position.get("curRealisedPnl")
                    or position.get("cumRealisedPnl")
                    or 0
                )
            except Exception:
                realized = 0.0

            try:
                unrealized = float(position.get("unrealisedPnl", 0) or 0)
            except Exception:
                unrealized = 0.0

            try:
                size = float(position.get("size", 0) or 0)
            except Exception:
                size = 0.0

            last_price = None
            for key in ["markPrice", "lastPrice"]:
                raw = position.get(key)
                try:
                    if raw not in (None, ""):
                        last_price = float(raw)
                        break
                except Exception:
                    continue
            if last_price is None and symbol:
                last_price = self.bybit.get_last_price(symbol)

            realized_total += realized
            unrealized_total += unrealized
            updated_raw = position.get("updatedTime") or position.get("createdTime")
            updated_at = updated_raw
            try:
                updated_ms = int(updated_raw or 0)
                if updated_ms > 0:
                    updated_at = datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc).isoformat()
            except Exception:
                updated_at = updated_raw

            active_rows.append({
                "symbol": symbol,
                "side": side,
                "status": "FILLED",
                "tp_hits": 0,
                "entry": entry,
                "sl": sl,
                "sl_initial": sl,
                "be_moved": bool(entry > 0 and sl > 0 and abs(entry - sl) < 0.00000001),
                "next_tp": next_tp,
                "last_price": last_price,
                "realized_pnl": round(realized, 4),
                "unrealized_pnl": round(unrealized, 4),
                "updated_at": updated_at,
            })

        active_rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return realized_total, unrealized_total, active_rows

    def build_stats(self, range_key="all"):
        exchange_closed = self.storage.get_exchange_closed_trades(source="exchange_closed_pnl")
        filtered_exchange_closed = self._filter_exchange_closed_trades(exchange_closed, range_key)
        signal_events = self.storage.get_signal_events()
        filtered_signal_events = self._filter_signal_events(signal_events, range_key)
        local_trades = self.storage.get_all_trades()
        filtered_local_trades = self._filter_local_trades(local_trades, range_key)
        sync_meta = self.storage.get_named_sync_state("closed_pnl_history")
        sync_in_progress = bool(sync_meta) and not bool(sync_meta.get("full_sync_completed"))
        wins, losses, breakevens, _, closed_rows = self._closed_summary_exchange(filtered_exchange_closed)
        closed_source_name = "exchange"
        active_realized_total, unrealized_total, active_rows = self._active_summary()
        account = self.bybit.get_account_summary()
        closed_source = filtered_exchange_closed
        tp_hits_total = sum(int(trade.get("tp_hits", 0) or 0) for trade in closed_source)
        sl_hits_total = sum(
            1 for trade in closed_source
            if (trade.get("close_reason") or "").upper() in {"STOP_LOSS", "SL"}
        )
        profit_pnl = sum(
            float(trade.get("pnl", 0) or 0)
            for trade in closed_source
            if float(trade.get("pnl", 0) or 0) > 0
        )
        loss_pnl = abs(sum(
            float(trade.get("pnl", 0) or 0)
            for trade in closed_source
            if float(trade.get("pnl", 0) or 0) < 0
        ))

        resolved = wins + losses
        winrate = (wins / resolved * 100) if resolved else 0.0
        lossrate = (losses / resolved * 100) if resolved else 0.0
        net_profit_pnl = profit_pnl - loss_pnl
        accepted_trades = len(filtered_local_trades)
        rejected_trades = 0

        for event in filtered_signal_events:
            status = str(event.get("status") or "").strip().lower()
            if status == "rejected":
                rejected_trades += 1

        return {
            "summary": {
                "available_balance": round(account.get("available_balance", 0.0), 4),
                "wallet_balance": round(account.get("wallet_balance", 0.0), 4),
                "equity": round(account.get("equity", 0.0), 4),
                "range": range_key,
                "total_trades": len(closed_source) + len(active_rows),
                "suggested_trades": len(filtered_signal_events),
                "accepted_trades": accepted_trades,
                "rejected_trades": rejected_trades,
                "open_trades": len(active_rows),
                "closed_trades": len(closed_rows),
                "wins": wins,
                "losses": losses,
                "breakevens": breakevens,
                "tp_hits_total": tp_hits_total,
                "sl_hits_total": sl_hits_total,
                "winrate": round(winrate, 2),
                "lossrate": round(lossrate, 2),
                "profit_pnl": round(profit_pnl, 4),
                "loss_pnl": round(loss_pnl, 4),
                "net_profit_pnl": round(net_profit_pnl, 4),
                "unrealized_pnl": round(unrealized_total, 4),
                "sync_in_progress": sync_in_progress,
                "closed_trades_source": closed_source_name,
                "exchange_closed_ready": bool(filtered_exchange_closed),
                "exchange_summary_only": True,
            },
            "active_trades": active_rows[:25],
            "closed_trades": closed_rows[:25],
        }

    def _parse_trade_time(self, trade):
        raw = trade.get("closed_at") or trade.get("updated_at") or trade.get("created_at")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.astimezone(self.local_tz)
        except Exception:
            return None

    def _filter_equity_points(self, points, range_key):
        if range_key == "all":
            return points

        start, end = self._range_bounds(range_key)
        if start is None and end is None:
            return points

        filtered = [
            point for point in points
            if (start is None or point["dt"] >= start)
            and (end is None or point["dt"] < end)
        ]
        if filtered:
            previous = None
            for point in points:
                if start is not None and point["dt"] < start:
                    previous = point
                else:
                    break
            if previous:
                filtered.insert(0, previous)
        return filtered

    def build_equity_curve(self, range_key="all"):
        account = self.bybit.get_account_summary()
        current_wallet = float(account.get("wallet_balance", 0.0) or 0.0)
        current_equity = float(account.get("equity", 0.0) or 0.0)
        transaction_history = self.storage.get_transaction_history()
        balance_history = self.storage.get_balance_history()
        sync_meta = self.storage.get_transaction_history_meta()
        sync_in_progress = bool(sync_meta) and not bool(sync_meta.get("full_sync_completed"))

        transaction_points = []
        for item in transaction_history:
            try:
                ts = int(item.get("transaction_time", 0) or 0)
            except Exception:
                ts = 0
            if ts <= 0:
                continue

            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(self.local_tz)
            label = item.get("symbol") or item.get("type") or "transaction"
            transaction_points.append({
                "dt": dt,
                "label": label,
                "balance": round(float(item.get("cash_balance", 0.0) or 0.0), 4),
            })

        transaction_points.sort(key=lambda item: item["dt"])
        if transaction_points:
            filtered = self._filter_equity_points(transaction_points, range_key)
            return {
                "range": range_key,
                "history_source": "exchange",
                "sync_in_progress": sync_in_progress,
                "points": [
                    {
                        "time": point["dt"].isoformat(),
                        "label": point["label"],
                        "balance": point["balance"],
                    }
                    for point in filtered
                ],
                "current_wallet_balance": round(current_wallet, 4),
                "current_equity_balance": round(current_equity, 4),
            }

        history_points = []
        for item in balance_history:
            raw = item.get("captured_at")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
            except Exception:
                continue
            history_points.append({
                "dt": dt.astimezone(self.local_tz),
                "label": "snapshot",
                "balance": round(float(item.get("wallet_balance", 0.0) or 0.0), 4),
                "wallet_balance": round(float(item.get("wallet_balance", 0.0) or 0.0), 4),
                "equity": round(float(item.get("equity", 0.0) or 0.0), 4),
            })

        history_points.sort(key=lambda item: item["dt"])
        if history_points:
            filtered = self._filter_equity_points(history_points, range_key)
            return {
                "range": range_key,
                "history_source": "local_fallback",
                "sync_in_progress": sync_in_progress,
                "points": [
                    {
                        "time": point["dt"].isoformat(),
                        "label": point["label"],
                        "balance": point["balance"],
                    }
                    for point in filtered
                ],
                "current_wallet_balance": round(current_wallet, 4),
                "current_equity_balance": round(current_equity, 4),
            }

        closed_trades = [
            trade for trade in self.storage.get_all_trades()
            if trade.get("status") == "CLOSED"
        ]

        enriched = []
        total_realized = 0.0
        for trade in closed_trades:
            dt = self._parse_trade_time(trade)
            if dt is None:
                continue
            pnl = float(trade.get("pnl", 0) or 0)
            total_realized += pnl
            enriched.append({
                "dt": dt,
                "symbol": trade.get("symbol"),
                "pnl": pnl,
            })

        enriched.sort(key=lambda item: item["dt"])

        start_balance = current_wallet - total_realized
        running_balance = start_balance
        points = [{
            "dt": enriched[0]["dt"] if enriched else datetime.now(self.local_tz),
            "label": "start",
            "balance": round(start_balance, 4),
        }]

        for item in enriched:
            running_balance += item["pnl"]
            points.append({
                "dt": item["dt"],
                "label": item["symbol"] or "trade",
                "balance": round(running_balance, 4),
            })

        filtered = self._filter_equity_points(points, range_key)
        return {
            "range": range_key,
            "history_source": "pnl_fallback",
            "sync_in_progress": sync_in_progress,
            "points": [
                {
                    "time": point["dt"].isoformat(),
                    "label": point["label"],
                    "balance": point["balance"],
                }
                for point in filtered
            ],
            "current_wallet_balance": round(current_wallet, 4),
            "current_equity_balance": round(current_equity, 4),
        }
