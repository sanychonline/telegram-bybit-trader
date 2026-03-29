from classes.webui.assets.trader_dashboard_css import TRADER_DASHBOARD_CSS
from classes.webui.assets.trader_dashboard_js import build_trader_dashboard_js
from classes.webui.i18n.registry import LANGUAGE_OPTIONS


def render_trader_dashboard_html(refresh_ms):
    options_html = "\n".join(
        f'            <option value="{code}">{label}</option>'
        for code, label in LANGUAGE_OPTIONS
    )
    script = build_trader_dashboard_js(refresh_ms)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trader Bot</title>
  <style>
{TRADER_DASHBOARD_CSS}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <h1>Trader Bot Dashboard</h1>
      <div class="controls">
        <button id="settings-toggle" class="settings-toggle" type="button" aria-label="Settings">⚙</button>
        <label class="lang-control" for="lang-select">
          <span>🌐</span>
          <select id="lang-select" class="lang-select" aria-label="Language">
{options_html}
          </select>
        </label>
        <button id="theme-toggle" class="icon-toggle" type="button" aria-label="Theme" title="Theme"></button>
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
    <div class="signal-meta" id="signal-meta"></div>
    <div class="exchange-status" id="exchange-status"></div>
    <div class="settings-modal" id="settings-modal" hidden>
      <div class="settings-backdrop" id="settings-backdrop"></div>
      <div class="settings-panel">
        <div class="settings-header">
          <h3 id="settings-title">Settings</h3>
          <button id="settings-close" class="settings-close" type="button" aria-label="Close">×</button>
        </div>
        <div class="settings-body">
          <div class="settings-section">
            <h4 id="settings-general-title">General Settings</h4>
            <div class="settings-grid" id="settings-general"></div>
          </div>
          <div class="settings-section">
            <h4 id="settings-trading-title">Trading Settings</h4>
            <div class="settings-grid" id="settings-trading"></div>
          </div>
          <div class="settings-section">
            <h4 id="settings-bybit-title">Bybit</h4>
            <div class="settings-grid" id="settings-bybit"></div>
          </div>
          <div class="settings-section">
            <h4 id="settings-telegram-title">Telegram</h4>
            <div class="settings-grid" id="settings-telegram"></div>
          </div>
        </div>
        <div class="settings-footer">
          <div class="settings-note" id="settings-note"></div>
          <div class="settings-actions">
            <button id="settings-cancel" class="theme-toggle" type="button">Cancel</button>
            <button id="settings-save" class="theme-toggle primary" type="button">Save</button>
          </div>
        </div>
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
        <div class="table-pager" id="active-pager"></div>
      </div>
      <div class="panel">
        <h3>Closed Trades</h3>
        <table>
          <thead><tr><th>Symbol</th><th>Reason</th><th>Realized</th><th>Updated</th></tr></thead>
          <tbody id="closed-body"></tbody>
        </table>
        <div class="table-pager" id="closed-pager"></div>
      </div>
    </div>
      <div class="panel chart-panel">
      <h3>Balance History</h3>
      <div class="chart-wrap">
        <svg id="equity-chart" viewBox="0 0 1000 280" preserveAspectRatio="none"></svg>
        <div id="equity-hover" class="chart-hover"></div>
      </div>
      <div class="chart-caption" id="equity-caption">Loading balance history...</div>
    </div>
  </div>
  <script>
{script}
  </script>
</body>
</html>"""
