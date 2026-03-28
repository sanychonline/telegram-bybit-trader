import asyncio
import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from classes.config import BRAND_NAME, DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_REFRESH_SEC


class DashboardService:
    def __init__(self, bybit, storage, logger):
        self.bybit = bybit
        self.storage = storage
        self.logger = logger
        self.host = DASHBOARD_HOST
        self.port = DASHBOARD_PORT
        self.refresh_sec = max(2, DASHBOARD_REFRESH_SEC)
        self._server = None
        self._thread = None

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
        now = datetime.utcnow()
        if range_key == "today":
            return datetime(now.year, now.month, now.day), None
        if range_key == "current_month":
            return datetime(now.year, now.month, 1), None
        if range_key == "month":
            return now - timedelta(days=30), None
        if range_key == "previous_month":
            current_month_start = datetime(now.year, now.month, 1)
            previous_month_end = current_month_start
            previous_month_start = datetime(
                previous_month_end.year - (1 if previous_month_end.month == 1 else 0),
                12 if previous_month_end.month == 1 else previous_month_end.month - 1,
                1,
            )
            return previous_month_start, previous_month_end
        if range_key == "half_year":
            return now - timedelta(days=183), None
        if range_key == "year":
            return now - timedelta(days=365), None
        if range_key == "previous_year":
            return datetime(now.year - 1, 1, 1), datetime(now.year, 1, 1)
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

    def _build_stats(self, range_key="all"):
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
            return datetime.fromisoformat(raw)
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

    def _build_equity_curve(self, range_key="all"):
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
            "dt": enriched[0]["dt"] if enriched else datetime.utcnow(),
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

    def _html(self):
        refresh_ms = self.refresh_sec * 1000
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{BRAND_NAME} Trader</title>
  <style>
    :root {{
      --bg: #08111a;
      --panel: #101b27;
      --panel2: #142333;
      --line: #26415a;
      --text: #ebf3f9;
      --muted: #94aabf;
      --green: #2fc97f;
      --red: #ef6464;
      --amber: #efbe53;
      --accent: #56a6ff;
      --bg-top: rgba(86,166,255,0.18);
      --body-start: #071019;
      --body-end: #08111a;
      --panel-shadow: none;
    }}
    html.day-theme {{
      --bg: #ffffff;
      --panel: #ffffff;
      --panel2: #eef6ff;
      --line: #c9dcef;
      --text: #16314d;
      --muted: #587492;
      --green: #1f9f63;
      --red: #d95454;
      --amber: #d39c17;
      --accent: #0a66c2;
      --bg-top: rgba(10,102,194,0.16);
      --body-start: #ffffff;
      --body-end: #f4f9ff;
      --panel-shadow: 0 12px 32px rgba(10, 102, 194, 0.10);
      --chart-bg: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: Menlo, Monaco, Consolas, monospace;
      background:
        radial-gradient(circle at top, var(--bg-top), transparent 30%),
        linear-gradient(180deg, var(--body-start) 0%, var(--body-end) 100%);
    }}
    .wrap {{ max-width: 1380px; margin: 0 auto; padding: 24px; }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .subbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .sub {{ color: var(--muted); }}
    .theme-toggle {{
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      border-radius: 999px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card, .panel {{
      background: linear-gradient(180deg, var(--panel) 0%, var(--panel2) 100%);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      box-shadow: var(--panel-shadow);
    }}
    .label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; text-transform: uppercase; }}
    .value {{ font-size: 26px; font-weight: 700; }}
    .green {{ color: var(--green); }}
    .red {{ color: var(--red); }}
    .amber {{ color: var(--amber); }}
    .tables {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .chart-panel {{ margin-top: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 10px 8px;
      text-align: left;
      font-size: 12px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .badge {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 11px;
    }}
    .health-cell {{ min-width: 180px; }}
    .health-pending {{
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .health-track {{
      position: relative;
      width: 100%;
      max-width: 168px;
      height: 14px;
    }}
    .health-rail {{
      position: absolute;
      inset: 50% 0 auto 0;
      height: 4px;
      transform: translateY(-50%);
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(239,100,100,0.95) 0%, rgba(239,190,83,0.9) 50%, rgba(47,201,127,0.95) 100%);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
    }}
    .health-mid {{
      position: absolute;
      top: 50%;
      left: 50%;
      width: 2px;
      height: 14px;
      transform: translate(-50%, -50%);
      background: rgba(255,255,255,0.55);
      border-radius: 2px;
    }}
    .health-dot {{
      position: absolute;
      top: 50%;
      width: 12px;
      height: 12px;
      transform: translate(-50%, -50%);
      border-radius: 50%;
      background: #f5fbff;
      border: 2px solid #56a6ff;
      box-shadow: 0 0 0 2px rgba(86,166,255,0.16);
    }}
    .health-labels {{
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      color: var(--muted);
      font-size: 9px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .range-switch {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
      align-items: center;
    }}
    .range-switch-top {{
      margin-left: auto;
    }}
    .range-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .range-select {{
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 8px 12px;
      font: inherit;
      min-width: 170px;
    }}
    .chart-wrap {{
      position: relative;
      width: 100%;
      height: 280px;
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 14px;
      overflow: hidden;
      background: var(--chart-bg, rgba(0,0,0,0.12));
    }}
    .chart-wrap svg {{
      width: 100%;
      height: 100%;
      display: block;
    }}
    .chart-hover {{
      position: absolute;
      pointer-events: none;
      min-width: 120px;
      max-width: 180px;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel2) 92%, var(--panel));
      color: var(--text);
      font-size: 11px;
      line-height: 1.35;
      transform: translate(-50%, -120%);
      display: none;
      z-index: 2;
      box-shadow: 0 10px 24px color-mix(in srgb, var(--accent) 12%, rgba(0, 0, 0, 0.18));
      white-space: nowrap;
    }}
    .chart-hover.visible {{ display: block; }}
    .chart-caption {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }}
    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}
    body.mobile .wrap {{ padding: 14px; }}
    body.mobile .topbar {{
      align-items: stretch;
      flex-direction: column;
      gap: 8px;
    }}
    body.mobile .topbar > div:first-child {{
      width: 100%;
    }}
    body.mobile .theme-toggle {{
      align-self: flex-end;
    }}
    body.mobile h1 {{ font-size: 22px; }}
    body.mobile .subbar {{
      align-items: stretch;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 14px;
    }}
    body.mobile .range-switch-top {{
      margin-left: 0;
      width: 100%;
      justify-content: flex-end;
    }}
    body.mobile .range-label {{
      width: 100%;
      text-align: right;
    }}
    body.mobile .range-select {{
      min-width: 0;
      width: min(220px, 100%);
    }}
    body.mobile .sub {{ font-size: 12px; }}
    body.mobile .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    body.mobile .card, body.mobile .panel {{ padding: 12px; border-radius: 14px; }}
    body.mobile .value {{ font-size: 19px; }}
    body.mobile .tables {{ grid-template-columns: 1fr; gap: 12px; }}
    body.mobile table, body.mobile thead, body.mobile tbody, body.mobile th, body.mobile td, body.mobile tr {{ display: block; width: 100%; }}
    body.mobile thead {{ display: none; }}
    body.mobile tbody tr {{
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    body.mobile td {{
      border-bottom: none;
      padding: 4px 0;
      font-size: 12px;
    }}
    body.mobile td::before {{
      content: attr(data-label);
      display: block;
      color: var(--muted);
      font-size: 10px;
      margin-bottom: 2px;
      text-transform: uppercase;
    }}
    body.mobile .health-cell {{
      min-width: 0;
      width: 100%;
    }}
    body.mobile .health-track {{
      max-width: 100%;
    }}
    body.mobile .chart-wrap {{ height: 220px; }}
    @media (max-width: 980px) {{ .tables {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <h1>Trader Bot Dashboard</h1>
      <button id="theme-toggle" class="theme-toggle" type="button">Theme: auto</button>
    </div>
    <div class="subbar">
      <div class="range-switch range-switch-top">
        <span class="range-label">Stats Period</span>
        <select id="range-select" class="range-select">
          <option value="today">today</option>
          <option value="current_month">current month</option>
          <option value="month">month</option>
          <option value="previous_month">previous month</option>
          <option value="half_year">half of year</option>
          <option value="year">year</option>
          <option value="previous_year">previous year</option>
          <option value="all">all time</option>
        </select>
      </div>
    </div>
    <div class="cards" id="cards"></div>
    <div class="tables">
      <div class="panel">
        <h3>Active Trades</h3>
        <table>
          <thead><tr><th>Symbol</th><th>Status</th><th>Last</th><th>Health</th><th>Realized</th><th>Unrealized</th></tr></thead>
          <tbody id="active-body"></tbody>
        </table>
      </div>
      <div class="panel">
        <h3>Closed Trades</h3>
        <table>
          <thead><tr><th>Symbol</th><th>Reason</th><th>Realized</th><th>Updated</th></tr></thead>
          <tbody id="closed-body"></tbody>
        </table>
      </div>
    </div>
    <div class="panel chart-panel">
      <h3>Balance Curve</h3>
      <div class="chart-wrap">
        <svg id="equity-chart" viewBox="0 0 1000 280" preserveAspectRatio="none"></svg>
        <div id="equity-hover" class="chart-hover"></div>
      </div>
      <div class="chart-caption" id="equity-caption">Loading balance curve...</div>
    </div>
    <div class="footer">{BRAND_NAME}</div>
  </div>
  <script>
    const refreshMs = {refresh_ms};
    const baseTitle = '{BRAND_NAME} Trader';
    let currentRange = 'current_month';
    let chartState = [];
    function fmt(n) {{ return Number(n || 0).toFixed(2); }}
    function cls(n) {{
      const v = Number(n || 0);
      if (v > 0) return 'green';
      if (v < 0) return 'red';
      return 'amber';
    }}
    function card(label, value, klass='') {{
      return `<div class="card"><div class="label">${{label}}</div><div class="value ${{klass}}">${{value}}</div></div>`;
    }}
    function setPnlTitle(value) {{
      const pnl = Number(value || 0);
      const arrow = pnl > 0 ? '▲' : pnl < 0 ? '▼' : '•';
      const signed = pnl > 0 ? `+${{fmt(pnl)}}` : fmt(pnl);
      document.title = `${{arrow}} ${{baseTitle}} ${{signed}}`;
    }}
    function getCssVar(name, fallback='') {{
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return value || fallback;
    }}
    function getCookie(name) {{
      const match = document.cookie.split('; ').find(row => row.startsWith(`${{name}}=`));
      return match ? decodeURIComponent(match.split('=')[1]) : null;
    }}
    function setCookie(name, value, days=365) {{
      const expires = new Date(Date.now() + days * 86400000).toUTCString();
      document.cookie = `${{name}}=${{encodeURIComponent(value)}}; expires=${{expires}}; path=/; SameSite=Lax`;
    }}
    function detectAutoTheme() {{
      const hour = new Date().getHours();
      return hour >= 7 && hour < 20 ? 'day' : 'night';
    }}
    function applyTheme(mode) {{
      const effective = mode === 'auto' ? detectAutoTheme() : mode;
      document.documentElement.classList.toggle('day-theme', effective === 'day');
      const button = document.getElementById('theme-toggle');
      if (button) button.textContent = `Theme: ${{mode}}`;
    }}
    function initThemeToggle() {{
      const order = ['auto', 'day', 'night'];
      let mode = getCookie('ui_theme') || 'auto';
      if (!order.includes(mode)) mode = 'auto';
      applyTheme(mode);
      const button = document.getElementById('theme-toggle');
      if (!button) return;
      button.addEventListener('click', () => {{
        const next = order[(order.indexOf(mode) + 1) % order.length];
        mode = next;
        setCookie('ui_theme', mode);
        applyTheme(mode);
      }});
    }}
    function safeNum(v) {{
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    }}
    function formatTime(value) {{
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ').split('.')[0];
      return date.toLocaleString([], {{
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      }});
    }}
    function formatReason(value) {{
      const raw = String(value || 'CLOSED').trim().toUpperCase();
      const labels = {{
        TAKE_PROFIT: 'TAKE PROFIT',
        STOP_LOSS: 'STOP LOSS',
        BREAKEVEN: 'BREAKEVEN',
        NO_ENTRY_TIMEOUT: 'NO ENTRY',
        SL: 'SL',
      }};
      return labels[raw] || raw.replaceAll('_', ' ');
    }}
    function tradeHealth(t) {{
      if (t.status !== 'FILLED') {{
        return `<span class="health-pending">PENDING</span>`;
      }}
      const entry = safeNum(t.entry);
      const sl = safeNum(t.sl);
      const slInitial = safeNum(t.sl_initial);
      const last = safeNum(t.last_price);
      const nextTp = safeNum(t.next_tp);
      if (entry === null || sl === null || last === null || nextTp === null || entry === nextTp) {{
        return `<span class="health-pending">LIVE</span>`;
      }}

      let ratio;
      const beMoved = Boolean(t.be_moved) || Math.abs(entry - sl) < 0.00000001;
      const effectiveSl = slInitial !== null && slInitial > 0 ? slInitial : sl;
      if (t.side === 'LONG') {{
        if (beMoved) {{
          ratio = Math.max(0, last - entry) / Math.max(nextTp - entry, 0.00000001);
        }} else {{
          ratio = last >= entry
            ? (last - entry) / Math.max(nextTp - entry, 0.00000001)
            : -((entry - last) / Math.max(entry - effectiveSl, 0.00000001));
        }}
      }} else {{
        if (beMoved) {{
          ratio = Math.max(0, entry - last) / Math.max(entry - nextTp, 0.00000001);
        }} else {{
          ratio = last <= entry
            ? (entry - last) / Math.max(entry - nextTp, 0.00000001)
            : -((last - entry) / Math.max(effectiveSl - entry, 0.00000001));
        }}
      }}

      const clamped = Math.max(-1, Math.min(1, ratio));
      const left = ((clamped + 1) / 2) * 100;
      const nextTpLabel = `TP${{Math.max(1, Number(t.tp_hits || 0) + 1)}}`;
      return `
        <div class="health-track" title="SL ${{fmt(effectiveSl)}} | BE ${{fmt(entry)}} | TP ${{fmt(nextTp)}} | Last ${{fmt(last)}}">
          <div class="health-rail"></div>
          <div class="health-mid"></div>
          <div class="health-dot" style="left:${{left.toFixed(1)}}%"></div>
        </div>
        <div class="health-labels"><span>SL</span><span>BE</span><span>${{nextTpLabel}}</span></div>
      `;
    }}
    function activeRow(t) {{
      return `<tr>
        <td data-label="Symbol">${{t.symbol}} ${{t.side}}</td>
        <td data-label="Status"><span class="badge">${{t.status}}</span></td>
        <td data-label="Last">${{t.last_price ?? ''}}</td>
        <td data-label="Health" class="health-cell">${{tradeHealth(t)}}</td>
        <td data-label="Realized" class="${{cls(t.realized_pnl)}}">${{fmt(t.realized_pnl)}}</td>
        <td data-label="Unrealized" class="${{cls(t.unrealized_pnl)}}">${{fmt(t.unrealized_pnl)}}</td>
      </tr>`;
    }}
    function closedRow(t) {{
      return `<tr>
        <td data-label="Symbol">${{t.symbol}} ${{t.side}}</td>
        <td data-label="Reason"><span class="badge">${{formatReason(t.reason)}}</span></td>
        <td data-label="Realized" class="${{cls(t.pnl)}}">${{fmt(t.pnl)}}</td>
        <td data-label="Updated">${{formatTime(t.updated_at)}}</td>
      </tr>`;
    }}
    function applyDeviceMode() {{
      const isMobile = window.matchMedia('(max-width: 820px)').matches || window.matchMedia('(pointer: coarse)').matches;
      document.body.classList.toggle('mobile', isMobile);
    }}
    function rangeLabel(value) {{
      const labels = {{
        today: 'today',
        current_month: 'current month',
        month: 'month',
        previous_month: 'previous month',
        half_year: 'half of year',
        year: 'year',
        previous_year: 'previous year',
        all: 'all time',
      }};
      return labels[value] || value;
    }}
    function syncRangeSelect() {{
      const select = document.getElementById('range-select');
      if (select) select.value = currentRange;
    }}
    function drawEquity(points, currentWallet) {{
      const svg = document.getElementById('equity-chart');
      const hover = document.getElementById('equity-hover');
      const caption = document.getElementById('equity-caption');
      if (!points.length) {{
        svg.innerHTML = '';
        hover.classList.remove('visible');
        chartState = [];
        caption.textContent = 'No closed trades yet.';
        return;
      }}

      const width = 1000;
      const height = 280;
      const padX = 24;
      const padY = 20;
      const values = points.map(p => Number(p.balance || 0));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = Math.max(max - min, 1);

      chartState = points.map((point, index) => {{
        const x = padX + ((width - padX * 2) * (points.length === 1 ? 0.5 : index / (points.length - 1)));
        const y = height - padY - (((Number(point.balance || 0) - min) / span) * (height - padY * 2));
        return {{
          x,
          y,
          time: point.time,
          label: point.label,
          balance: Number(point.balance || 0),
        }};
      }});
      const path = chartState.map((point, index) => `${{index === 0 ? 'M' : 'L'}}${{point.x.toFixed(2)}},${{point.y.toFixed(2)}}`).join(' ');

      const last = values[values.length - 1];
      svg.innerHTML = `
        <line x1="24" y1="${{height - 20}}" x2="${{width - 24}}" y2="${{height - 20}}" stroke="rgba(255,255,255,0.08)" />
        <line id="hover-line" x1="0" y1="20" x2="0" y2="${{height - 20}}" stroke="rgba(255,255,255,0.18)" stroke-dasharray="4 4" opacity="0" />
        <path d="${{path}}" fill="none" stroke="${{getCssVar('--accent', '#56a6ff')}}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />
        <circle id="hover-dot" cx="0" cy="0" r="5" fill="${{getCssVar('--accent', '#56a6ff')}}" stroke="#ffffff" stroke-width="2" opacity="0" />
      `;
      caption.textContent = `Range: ${{rangeLabel(currentRange)}} | points: ${{points.length}} | last balance: ${{fmt(last)}} | current wallet: ${{fmt(currentWallet)}}`;
    }}
    function bindChartHover() {{
      const svg = document.getElementById('equity-chart');
      const hover = document.getElementById('equity-hover');
      const hoverLine = () => document.getElementById('hover-line');
      const hoverDot = () => document.getElementById('hover-dot');
      const wrap = svg.closest('.chart-wrap');

      function hide() {{
        hover.classList.remove('visible');
        if (hoverLine()) hoverLine().setAttribute('opacity', '0');
        if (hoverDot()) hoverDot().setAttribute('opacity', '0');
      }}

      function showAt(clientX) {{
        if (!chartState.length) {{
          hide();
          return;
        }}
        const rect = svg.getBoundingClientRect();
        const ratio = 1000 / rect.width;
        const x = (clientX - rect.left) * ratio;
        let best = chartState[0];
        let dist = Math.abs(best.x - x);
        for (const point of chartState) {{
          const candidate = Math.abs(point.x - x);
          if (candidate < dist) {{
            best = point;
            dist = candidate;
          }}
        }}
        if (hoverLine()) {{
          hoverLine().setAttribute('x1', best.x.toFixed(2));
          hoverLine().setAttribute('x2', best.x.toFixed(2));
          hoverLine().setAttribute('opacity', '1');
        }}
        if (hoverDot()) {{
          hoverDot().setAttribute('cx', best.x.toFixed(2));
          hoverDot().setAttribute('cy', best.y.toFixed(2));
          hoverDot().setAttribute('opacity', '1');
        }}
        hover.innerHTML = `<strong>${{fmt(best.balance)}}</strong><br>${{best.label}}<br>${{(best.time || '').replace('T', ' ').slice(0, 16)}}`;
        const rawLeft = (best.x / 1000) * rect.width;
        const rawTop = (best.y / 280) * rect.height;
        const hoverWidth = hover.offsetWidth || 140;
        const hoverHeight = hover.offsetHeight || 52;
        const clampedLeft = Math.max((hoverWidth / 2) + 8, Math.min(rect.width - (hoverWidth / 2) - 8, rawLeft));
        const clampedTop = Math.max(hoverHeight + 12, Math.min(rect.height - 12, rawTop));
        hover.style.left = `${{clampedLeft}}px`;
        hover.style.top = `${{clampedTop}}px`;
        hover.classList.add('visible');
      }}

      svg.onmousemove = (e) => showAt(e.clientX);
      svg.onmouseleave = hide;
      svg.ontouchstart = (e) => {{
        if (e.touches[0]) showAt(e.touches[0].clientX);
      }};
      svg.ontouchmove = (e) => {{
        if (e.touches[0]) showAt(e.touches[0].clientX);
      }};
      svg.ontouchend = hide;
    }}
    async function refreshEquity() {{
      const res = await fetch(`api/equity?range=${{currentRange}}`, {{ cache: 'no-store' }});
      const data = await res.json();
      drawEquity(data.points || [], data.current_wallet_balance || 0);
      bindChartHover();
      syncRangeSelect();
    }}
    async function refresh() {{
      const res = await fetch(`api/stats?range=${{currentRange}}`, {{ cache: 'no-store' }});
      const data = await res.json();
      const s = data.summary;
      document.getElementById('cards').innerHTML = [
        card('Available Balance', fmt(s.available_balance), cls(s.available_balance)),
        card('Wallet Balance', fmt(s.wallet_balance), cls(s.wallet_balance)),
        card('Equity', fmt(s.equity), cls(s.equity)),
        card('Open Trades', s.open_trades),
        card('Closed Trades', s.closed_trades),
        card('Winrate', `${{fmt(s.winrate)}}%`),
        card('Non-Loss Rate', `${{fmt(s.non_loss_rate)}}%`),
        card('Realized PnL', fmt(s.realized_pnl), cls(s.realized_pnl)),
        card('Unrealized PnL', fmt(s.unrealized_pnl), cls(s.unrealized_pnl)),
        card('Wins', s.wins),
        card('Losses', s.losses),
        card('TP hits', s.tp_hits_total),
        card('SL hits', s.sl_hits_total),
      ].join('');
      setPnlTitle(s.unrealized_pnl);
      document.getElementById('active-body').innerHTML = data.active_trades.map(activeRow).join('') || '<tr><td colspan="5">No active trades</td></tr>';
      document.getElementById('closed-body').innerHTML = data.closed_trades.map(closedRow).join('') || '<tr><td colspan="5">No closed trades</td></tr>';
      await refreshEquity();
    }}
    const rangeSelect = document.getElementById('range-select');
    if (rangeSelect) {{
      rangeSelect.addEventListener('change', async () => {{
        currentRange = rangeSelect.value;
        await refresh();
      }});
    }}
    initThemeToggle();
    applyDeviceMode();
    window.addEventListener('resize', applyDeviceMode);
    refresh();
    setInterval(refresh, refreshMs);
  </script>
</body>
</html>"""

    def _make_handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path in ["/", "/index.html"]:
                    body = service._html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path.startswith("/api/stats"):
                    range_key = "all"
                    if "?" in self.path:
                        query = self.path.split("?", 1)[1]
                        for item in query.split("&"):
                            if item.startswith("range="):
                                value = item.split("=", 1)[1].strip().lower()
                                if value in ["today", "current_month", "month", "previous_month", "half_year", "year", "previous_year", "all"]:
                                    range_key = value
                                break
                    payload = json.dumps(service._build_stats(range_key)).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path.startswith("/api/equity"):
                    range_key = "all"
                    if "?" in self.path:
                        query = self.path.split("?", 1)[1]
                        for item in query.split("&"):
                            if item.startswith("range="):
                                value = item.split("=", 1)[1].strip().lower()
                                if value in ["today", "current_month", "month", "previous_month", "half_year", "year", "previous_year", "all"]:
                                    range_key = value
                                break
                    payload = json.dumps(service._build_equity_curve(range_key)).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/health":
                    payload = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                self.send_response(404)
                self.end_headers()

        return Handler

    async def run(self):
        if self._thread and self._thread.is_alive():
            while True:
                await asyncio.sleep(3600)

        self._server = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.logger.info(f"Dashboard started | host={self.host} port={self.port}")

        while True:
            await asyncio.sleep(3600)
