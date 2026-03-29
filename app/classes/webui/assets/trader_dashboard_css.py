TRADER_DASHBOARD_CSS = r"""
    :root {
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
    }
    html.day-theme {
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
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: Menlo, Monaco, Consolas, monospace;
      background:
        radial-gradient(circle at top, var(--bg-top), transparent 30%),
        linear-gradient(180deg, var(--body-start) 0%, var(--body-end) 100%);
    }
    .wrap { max-width: 1380px; margin: 0 auto; padding: 24px; }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }
    .subbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
    }
    h1 { margin: 0 0 6px; font-size: 28px; }
    .sub { color: var(--muted); }
    .icon-toggle, .settings-toggle {
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      border-radius: 999px;
      width: 42px;
      height: 42px;
      padding: 0;
      font: inherit;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      white-space: nowrap;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    .icon-toggle:hover, .settings-toggle:hover {
      transform: translateY(-1px);
      border-color: color-mix(in srgb, var(--accent) 44%, var(--line));
    }
    .icon-toggle:active, .settings-toggle:active {
      transform: translateY(0);
    }
    .icon-toggle:focus-visible, .settings-toggle:focus-visible {
      outline: 2px solid color-mix(in srgb, var(--accent) 60%, white);
      outline-offset: 2px;
    }
    .icon-toggle svg {
      width: 22px;
      height: 22px;
      display: block;
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .lang-control {
      display: inline-flex;
      align-items: center;
      gap: 0;
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      border-radius: 999px;
      padding: 9px 10px;
      width: 46px;
      justify-content: center;
      overflow: hidden;
      position: relative;
    }
    .lang-select {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: 0;
      background: transparent;
      color: transparent;
      font-size: 16px;
      outline: none;
      cursor: pointer;
      opacity: 0;
    }
    .lang-select option {
      color: #111;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }
    .exchange-status {
      display: block;
      margin-bottom: 0;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, var(--panel) 0%, var(--panel2) 100%);
      color: var(--muted);
      font-size: 13px;
      box-shadow: var(--panel-shadow);
      position: fixed;
      top: 18px;
      left: 50%;
      transform: translate(-50%, -8px);
      width: min(720px, calc(100vw - 32px));
      z-index: 50;
      opacity: 0;
      pointer-events: none;
      transition: opacity 180ms ease, transform 180ms ease;
    }
    .exchange-status.visible {
      opacity: 1;
      transform: translate(-50%, 0);
    }
    .exchange-status.exchange {
      color: var(--green);
    }
    .exchange-status.syncing {
      color: var(--amber);
    }
    .settings-modal[hidden] { display: none; }
    .settings-modal {
      position: fixed;
      inset: 0;
      z-index: 60;
    }
    .settings-backdrop {
      position: absolute;
      inset: 0;
      background: rgba(2, 8, 14, 0.55);
      backdrop-filter: blur(4px);
    }
    .settings-panel {
      position: relative;
      width: min(920px, calc(100vw - 28px));
      max-height: calc(100vh - 28px);
      margin: 14px auto;
      overflow: auto;
      background: linear-gradient(180deg, var(--panel) 0%, var(--panel2) 100%);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--panel-shadow);
    }
    .settings-header, .settings-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
    }
    .settings-footer {
      border-top: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
      border-bottom: 0;
    }
    .settings-header h3, .settings-section h4 {
      margin: 0;
    }
    .settings-body {
      padding: 18px;
      display: grid;
      gap: 18px;
    }
    .settings-section {
      display: grid;
      gap: 12px;
    }
    .settings-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      align-items: start;
    }
    .settings-field {
      display: grid;
      gap: 8px;
      grid-template-rows: auto minmax(44px, auto) minmax(16px, auto);
      align-content: start;
    }
    .settings-field label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }
    .settings-field input,
    .settings-field textarea,
    .settings-field select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      font: inherit;
      padding: 10px 12px;
      min-height: 44px;
    }
    .settings-field textarea {
      min-height: 92px;
      resize: vertical;
    }
    .settings-readonly {
      display: flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      color: var(--text);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      min-height: 44px;
    }
    .settings-hint {
      color: var(--muted);
      font-size: 12px;
      min-height: 16px;
    }
    .settings-close {
      border: 1px solid var(--line);
      background: transparent;
      color: var(--text);
      border-radius: 999px;
      width: 36px;
      height: 36px;
      font-size: 20px;
      cursor: pointer;
    }
    .settings-actions {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .settings-note {
      color: var(--muted);
      font-size: 12px;
    }
    .card, .panel {
      background: linear-gradient(180deg, var(--panel) 0%, var(--panel2) 100%);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      box-shadow: var(--panel-shadow);
    }
    .label { color: var(--muted); font-size: 11px; margin-bottom: 6px; text-transform: uppercase; }
    .value { font-size: 23px; font-weight: 700; line-height: 1.05; }
    .green { color: var(--green); }
    .red { color: var(--red); }
    .amber { color: var(--amber); }
    .tables { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .tables .panel { min-height: 560px; }
    .chart-panel { margin-top: 16px; }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 10px 8px;
      text-align: left;
      font-size: 12px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
    }
    th { color: var(--muted); font-weight: 600; }
    .badge {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 11px;
    }
    .table-pager {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      margin-top: 12px;
      flex-wrap: wrap;
    }
    .pager-btn {
      min-width: 34px;
      height: 34px;
      padding: 0 10px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }
    .pager-btn.active {
      background: color-mix(in srgb, var(--accent) 22%, var(--panel));
      border-color: color-mix(in srgb, var(--accent) 52%, var(--line));
    }
    .pager-btn:disabled {
      opacity: 0.45;
      cursor: default;
    }
    .health-cell { min-width: 180px; }
    .health-pending {
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .health-track {
      position: relative;
      width: 100%;
      max-width: 168px;
      height: 14px;
    }
    .health-rail {
      position: absolute;
      inset: 50% 0 auto 0;
      height: 4px;
      transform: translateY(-50%);
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(239,100,100,0.95) 0%, rgba(239,190,83,0.9) 50%, rgba(47,201,127,0.95) 100%);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
    }
    .health-mid {
      position: absolute;
      top: 50%;
      left: 50%;
      width: 2px;
      height: 14px;
      transform: translate(-50%, -50%);
      background: rgba(255,255,255,0.55);
      border-radius: 2px;
    }
    .health-dot {
      position: absolute;
      top: 50%;
      width: 12px;
      height: 12px;
      transform: translate(-50%, -50%);
      border-radius: 50%;
      background: #f5fbff;
      border: 2px solid #56a6ff;
      box-shadow: 0 0 0 2px rgba(86,166,255,0.16);
    }
    .health-labels {
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      color: var(--muted);
      font-size: 9px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .range-switch {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
      align-items: center;
    }
    .range-switch-top {
      margin-left: auto;
    }
    .range-label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }
    .range-select {
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 8px 12px;
      font: inherit;
      min-width: 170px;
    }
    .chart-wrap {
      position: relative;
      width: 100%;
      height: 280px;
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 14px;
      overflow: hidden;
      background: var(--chart-bg, rgba(0,0,0,0.12));
    }
    .chart-wrap svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .chart-hover {
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
    }
    .chart-hover.visible { display: block; }
    .chart-caption {
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    body.mobile .wrap { padding: 14px; }
    body.mobile .topbar {
      align-items: stretch;
      flex-direction: column;
      gap: 8px;
    }
    body.mobile .topbar > div:first-child {
      width: 100%;
    }
    body.mobile .icon-toggle {
      align-self: flex-end;
    }
    body.mobile h1 { font-size: 22px; }
    body.mobile .subbar {
      align-items: stretch;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 14px;
    }
    body.mobile .range-switch-top {
      margin-left: 0;
      width: 100%;
      justify-content: flex-end;
    }
    body.mobile .range-label {
      width: 100%;
      text-align: right;
    }
    body.mobile .range-select {
      min-width: 0;
      width: min(220px, 100%);
    }
    body.mobile .sub { font-size: 12px; }
    body.mobile .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    body.mobile .card, body.mobile .panel { padding: 12px; border-radius: 14px; }
    body.mobile .value { font-size: 19px; }
    body.mobile .tables { grid-template-columns: 1fr; gap: 12px; }
    body.mobile .tables .panel { min-height: 420px; }
    body.mobile .table-pager { justify-content: center; }
    body.mobile table, body.mobile thead, body.mobile tbody, body.mobile th, body.mobile td, body.mobile tr { display: block; width: 100%; }
    body.mobile thead { display: none; }
    body.mobile tbody tr {
      padding: 8px 0;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
    }
    body.mobile td {
      border-bottom: none;
      padding: 4px 0;
      font-size: 12px;
    }
    body.mobile td::before {
      content: attr(data-label);
      display: block;
      color: var(--muted);
      font-size: 10px;
      margin-bottom: 2px;
      text-transform: uppercase;
    }
    body.mobile .health-cell {
      min-width: 0;
      width: 100%;
    }
    body.mobile .health-track {
      max-width: 100%;
    }
    body.mobile .chart-wrap { height: 220px; }
    @media (max-width: 1220px) {
      .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 980px) { .tables { grid-template-columns: 1fr; } }
"""
