from classes.webui.assets.trader_dashboard_css import TRADER_DASHBOARD_CSS
from classes.webui.assets.trader_dashboard_js import build_trader_dashboard_js
from classes.webui.i18n.registry import LANGUAGE_OPTIONS


def render_trader_dashboard_html(brand_name, refresh_ms):
    options_html = "\n".join(
        f'            <option value="{code}">{label}</option>'
        for code, label in LANGUAGE_OPTIONS
    )
    script = build_trader_dashboard_js(brand_name, refresh_ms)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{brand_name} Trader</title>
  <style>
{TRADER_DASHBOARD_CSS}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <h1>Trader Bot Dashboard</h1>
      <div class="controls">
        <label class="lang-control" for="lang-select">
          <span>🌐</span>
          <select id="lang-select" class="lang-select" aria-label="Language">
{options_html}
          </select>
        </label>
        <button id="theme-toggle" class="theme-toggle" type="button">Theme: auto</button>
      </div>
    </div>
    <div class="subbar">
      <div class="range-switch range-switch-top">
        <span class="range-label">Stats Period</span>
        <select id="range-select" class="range-select">
          <option value="today">today</option>
          <option value="current_month">current month</option>
          <option value="month">month</option>
          <option value="quarter">quarter</option>
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
    <div class="footer">
      <div class="footer-brand">{brand_name} © 2026</div>
      <div class="footer-note" id="footer-disclaimer">For informational purposes only. Not financial advice.</div>
    </div>
  </div>
  <script>
{script}
  </script>
</body>
</html>"""
