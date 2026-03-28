from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import TZ


class DashboardDataService:
    def __init__(self, bybit, storage):
        self.bybit = bybit
        self.storage = storage
        self.local_tz = ZoneInfo(TZ)

    def _closed_summary(self, trades):
        wins = 0
        losses = 0
        breakevens = 0
        realized = 0.0
        closed_rows = []

        for trade in trades:
            if trade.get("status") != "CLOSED":
                continue

            pnl = float(trade.get("pnl", 0) or 0)
            reason = trade.get("close_reason") or trade.get("exit_reason")
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
                "updated_at": trade.get("updated_at"),
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

    def _filter_closed_trades(self, trades, range_key):
        start, end = self._range_bounds(range_key)
        if start is None and end is None:
            return [trade for trade in trades if trade.get("status") == "CLOSED"]
        filtered = []
        for trade in trades:
            if trade.get("status") != "CLOSED":
                continue
            dt = self._parse_trade_time(trade)
            if dt is None:
                continue
            if start is not None and dt < start:
                continue
            if end is not None and dt >= end:
                continue
            filtered.append(trade)
        return filtered

    def _active_summary(self, trades):
        realized_total = 0.0
        unrealized_total = 0.0
        active_rows = []

        for trade in trades:
            if trade.get("status") not in ["PENDING", "FILLED"]:
                continue

            symbol = trade.get("symbol")
            side = trade.get("side")
            entry = float(trade.get("entry", 0) or 0)
            sl = float(trade.get("sl", 0) or 0)
            tp_hits = int(trade.get("tp_hits", 0) or 0)
            tps = trade.get("tps") or []
            realized = 0.0

            for tp in tps[:tp_hits]:
                try:
                    target_price = float(tp.get("price", 0) or 0)
                    target_qty = float(tp.get("qty", 0) or 0)
                except Exception:
                    continue

                if target_price <= 0 or target_qty <= 0 or entry <= 0:
                    continue

                if side == "LONG":
                    realized += (target_price - entry) * target_qty
                else:
                    realized += (entry - target_price) * target_qty

            next_tp = None
            if tp_hits < len(tps):
                target = tps[tp_hits].get("price")
                try:
                    next_tp = float(target) if target is not None else None
                except Exception:
                    next_tp = None
            size = float(
                trade.get("remaining_size")
                or trade.get("filled_size")
                or trade.get("pending_filled_size")
                or 0
            )
            last_price = self.bybit.get_last_price(symbol) if symbol else None

            if last_price is not None and entry > 0 and size > 0:
                if side == "LONG":
                    unrealized = (last_price - entry) * size
                else:
                    unrealized = (entry - last_price) * size
            else:
                unrealized = 0.0

            realized_total += realized
            unrealized_total += unrealized
            active_rows.append({
                "symbol": symbol,
                "side": side,
                "status": trade.get("status"),
                "tp_hits": tp_hits,
                "entry": entry,
                "sl": sl,
                "sl_initial": float(trade.get("sl_initial", sl) or sl),
                "be_moved": bool(trade.get("be_moved")),
                "next_tp": next_tp,
                "last_price": last_price,
                "realized_pnl": round(realized, 4),
                "unrealized_pnl": round(unrealized, 4),
                "updated_at": trade.get("updated_at"),
            })

        active_rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return realized_total, unrealized_total, active_rows

    def build_stats(self, range_key="all"):
        trades = self.storage.get_all_trades()
        filtered_closed = self._filter_closed_trades(trades, range_key)
        wins, losses, breakevens, realized_total, closed_rows = self._closed_summary(filtered_closed)
        active_realized_total, unrealized_total, active_rows = self._active_summary(trades)
        realized_total += active_realized_total
        account = self.bybit.get_account_summary()
        active_trade_map = {
            (trade.get("symbol"), trade.get("created_at"), trade.get("updated_at")): trade
            for trade in trades
            if trade.get("status") in ["PENDING", "FILLED"]
        }

        tp_hits_total = 0
        sl_hits_total = 0

        for trade in filtered_closed:
            hits = int(trade.get("tp_hits", 0) or 0)
            tp_hits_total += hits
            reason = trade.get("close_reason") or trade.get("exit_reason")
            if reason in ["STOP_LOSS", "SL"]:
                sl_hits_total += 1

        for trade in active_trade_map.values():
            hits = int(trade.get("tp_hits", 0) or 0)
            tp_hits_total += hits

        resolved = wins + losses
        winrate = (wins / resolved * 100) if resolved else 0.0
        non_loss_rate = ((wins + breakevens) / len(closed_rows) * 100) if closed_rows else 0.0

        return {
            "summary": {
                "available_balance": round(account.get("available_balance", 0.0), 4),
                "wallet_balance": round(account.get("wallet_balance", 0.0), 4),
                "equity": round(account.get("equity", 0.0), 4),
                "range": range_key,
                "total_trades": len(filtered_closed) + len(active_rows),
                "open_trades": len(active_rows),
                "closed_trades": len(closed_rows),
                "wins": wins,
                "losses": losses,
                "breakevens": breakevens,
                "tp_hits_total": tp_hits_total,
                "sl_hits_total": sl_hits_total,
                "winrate": round(winrate, 2),
                "non_loss_rate": round(non_loss_rate, 2),
                "realized_pnl": round(realized_total, 4),
                "unrealized_pnl": round(unrealized_total, 4),
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
            "points": [
                {
                    "time": point["dt"].isoformat(),
                    "label": point["label"],
                    "balance": point["balance"],
                }
                for point in filtered
            ],
            "current_wallet_balance": round(current_wallet, 4),
        }
