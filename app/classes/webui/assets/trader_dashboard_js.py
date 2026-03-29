import json

from classes.webui.i18n.registry import TRANSLATIONS


def build_trader_dashboard_js(refresh_ms):
    translations_json = json.dumps(TRANSLATIONS, ensure_ascii=False)
    return f"""
    const refreshMs = {refresh_ms};
    const baseTitle = "Trader Bot";
    const pageSize = 10;
    const langCookie = 'ui_lang';
    let currentRange = 'current_month';
    let currentLang = 'en';
    let chartState = [];
    let activeTradesData = [];
    let closedTradesData = [];
    let activePage = 1;
    let closedPage = 1;
    let exchangeStatusTimer = null;
    let lastExchangeStatusKey = '';
    let settingsPayload = null;
    const translations = {translations_json};
    const settingsGroups = {{
      general: ['tz', 'dashboard_refresh_sec'],
      bybit: ['bybit_testnet'],
      telegram: ['telegram_chat_id'],
      trading: ['max_position_multiplier', 'max_entry_deviation_pct', 'max_signal_desync_pct', 'emergency_tp_pct', 'pending_entry_timeout_sec'],
    }};
    const timezones = [
      'UTC',
      'Europe/Kyiv',
      'Europe/Warsaw',
      'Europe/Berlin',
      'Europe/Paris',
      'Europe/London',
      'Europe/Madrid',
      'Europe/Rome',
      'Europe/Athens',
      'Europe/Istanbul',
      'America/New_York',
      'America/Chicago',
      'America/Denver',
      'America/Los_Angeles',
      'America/Toronto',
      'America/Sao_Paulo',
      'Asia/Dubai',
      'Asia/Kolkata',
      'Asia/Bangkok',
      'Asia/Singapore',
      'Asia/Hong_Kong',
      'Asia/Tokyo',
      'Asia/Seoul',
      'Australia/Sydney',
    ];
    const settingsLabels = {{
      tz: 'Timezone',
      dashboard_refresh_sec: 'Dashboard Refresh Sec',
      bybit_testnet: 'Bybit Testnet',
      telegram_chat_id: 'Telegram Chat ID',
      max_position_multiplier: 'Max Position Multiplier',
      max_entry_deviation_pct: 'Max Entry Deviation Pct',
      max_signal_desync_pct: 'Max Signal Desync Pct',
      emergency_tp_pct: 'Emergency TP Pct',
      pending_entry_timeout_sec: 'Pending Entry Timeout Sec',
      bybit_api_key: 'Bybit API Key',
      bybit_api_secret: 'Bybit API Secret',
      telegram_api_id: 'Telegram API ID',
      telegram_api_hash: 'Telegram API Hash',
    }};
    function tr(text) {{
      const dict = translations[currentLang] || translations.en;
      return dict[text] || translations.en[text] || text;
    }}
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
    function displayStat(value, formatter=null) {{
      if (value === null || value === undefined || value === '') return '—';
      return formatter ? formatter(value) : value;
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
    function detectLanguage() {{
      const supported = ['en', 'de', 'es', 'pl', 'uk', 'fr'];
      const fromCookie = getCookie(langCookie);
      if (supported.includes(fromCookie)) return fromCookie;
      const langs = Array.isArray(navigator.languages) && navigator.languages.length ? navigator.languages : [navigator.language || 'en'];
      for (const item of langs) {{
        const base = String(item || '').toLowerCase().split('-')[0];
        if (supported.includes(base)) return base;
      }}
      return 'en';
    }}
    function detectAutoTheme() {{
      const hour = new Date().getHours();
      return hour >= 7 && hour < 20 ? 'day' : 'night';
    }}
    function applyTheme(mode) {{
      const effective = mode === 'auto' ? detectAutoTheme() : mode;
      document.documentElement.classList.toggle('day-theme', effective === 'day');
      const button = document.getElementById('theme-toggle');
      if (button) button.textContent = `${{tr('theme')}}: ${{tr(mode)}}`;
    }}
    function applyLanguage(lang) {{
      currentLang = translations[lang] ? lang : 'en';
      setCookie(langCookie, currentLang);
      const select = document.getElementById('lang-select');
      if (select) select.value = currentLang;
      document.querySelector('.topbar h1').textContent = tr('Trader Bot Dashboard');
      document.querySelector('.range-label').textContent = tr('statsPeriod');
      const settingsTitle = document.getElementById('settings-title');
      if (settingsTitle) settingsTitle.textContent = tr('Settings');
      const settingsGeneralTitle = document.getElementById('settings-general-title');
      if (settingsGeneralTitle) settingsGeneralTitle.textContent = tr('General Settings');
      const settingsTradingTitle = document.getElementById('settings-trading-title');
      if (settingsTradingTitle) settingsTradingTitle.textContent = tr('Trading Settings');
      const settingsBybitTitle = document.getElementById('settings-bybit-title');
      if (settingsBybitTitle) settingsBybitTitle.textContent = tr('Bybit');
      const settingsTelegramTitle = document.getElementById('settings-telegram-title');
      if (settingsTelegramTitle) settingsTelegramTitle.textContent = tr('Telegram');
      const settingsCancel = document.getElementById('settings-cancel');
      if (settingsCancel) settingsCancel.textContent = tr('Cancel');
      const settingsSave = document.getElementById('settings-save');
      if (settingsSave) settingsSave.textContent = tr('Save');
      document.querySelectorAll('#range-select option').forEach(option => {{
        option.textContent = rangeLabel(option.value);
      }});
      const panelTitles = document.querySelectorAll('.panel h3');
      if (panelTitles[0]) panelTitles[0].textContent = tr('Active Trades');
      if (panelTitles[1]) panelTitles[1].textContent = tr('Closed Trades');
      if (panelTitles[2]) panelTitles[2].textContent = tr('Balance History');
      document.getElementById('equity-caption').textContent = tr('Loading balance history...');
      document.querySelectorAll('th').forEach(th => {{
        th.textContent = tr(th.textContent.trim());
      }});
      if (settingsPayload) renderSettings();
      applyTheme(getCookie('ui_theme') || 'auto');
    }}
    function applyEmbedMode() {{
      const params = new URLSearchParams(window.location.search);
      if (params.get('embed') !== '1') return;
      const button = document.getElementById('theme-toggle');
      if (button) button.style.display = 'none';
      const lang = document.getElementById('lang-select')?.closest('.lang-control');
      if (lang) lang.style.display = 'none';
      const footer = document.querySelector('.footer');
      if (footer) footer.style.display = 'none';
    }}
    function initThemeToggle() {{
      const order = ['auto', 'day', 'night'];
      let mode = getCookie('ui_theme') || 'auto';
      if (!order.includes(mode)) mode = 'auto';
      applyTheme(mode);
      window.addEventListener('message', (event) => {{
        if (event.origin !== window.location.origin) return;
        const data = event.data || {{}};
        if (data.type === 'ui-theme-change' && order.includes(data.mode)) {{
          mode = data.mode;
          setCookie('ui_theme', mode);
          applyTheme(mode);
        }}
        if (data.type === 'ui-language-change' && data.lang) {{
          applyLanguage(data.lang);
        }}
      }});
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
      const beAfterTp = raw.match(/^BE_AFTER_TP(\d+)$/);
      if (beAfterTp) {{
        return `BE TP${{beAfterTp[1]}}`;
      }}
      const labels = {{
        TAKE_PROFIT: 'TP',
        TP: 'TP',
        STOP_LOSS: 'SL',
        SL: 'SL',
        BREAKEVEN: 'BE',
        BE: 'BE',
        NO_ENTRY_TIMEOUT: 'NO ENTRY',
      }};
      return labels[raw] || raw.replaceAll('_', ' ');
    }}
    function formatStatus(value) {{
      const raw = String(value || '').trim().toUpperCase();
      const labels = {{
        FILLED: tr('FILLED'),
        OPEN: tr('OPEN'),
        PUBLISHED: tr('PUBLISHED'),
        PENDING: tr('PENDING'),
        LIVE: tr('LIVE'),
        BE_UPDATED: 'BE',
        CLOSED: tr('CLOSED'),
      }};
      return labels[raw] || raw.replaceAll('_', ' ');
    }}
    function tradeHealth(t) {{
      if (t.status !== 'FILLED') {{
        return `<span class="health-pending">${{tr('PENDING')}}</span>`;
      }}
      const entry = safeNum(t.entry);
      const sl = safeNum(t.sl);
      const slInitial = safeNum(t.sl_initial);
      const last = safeNum(t.last_price);
      const nextTp = safeNum(t.next_tp);
      if (entry === null || sl === null || last === null || nextTp === null || entry === nextTp) {{
        return `<span class="health-pending">${{tr('LIVE')}}</span>`;
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
        <div class="health-labels"><span>${{tr('SL')}}</span><span>${{tr('BE')}}</span><span>${{nextTpLabel}}</span></div>
      `;
    }}
    function activeRow(t) {{
      return `<tr>
        <td data-label="Symbol">${{t.symbol}} ${{t.side}}</td>
        <td data-label="Status"><span class="badge">${{formatStatus(t.status)}}</span></td>
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
    function slicePage(items, page) {{
      const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
      const safePage = Math.max(1, Math.min(page, totalPages));
      const start = (safePage - 1) * pageSize;
      return {{
        page: safePage,
        totalPages,
        items: items.slice(start, start + pageSize),
      }};
    }}
    function renderPager(containerId, page, totalPages, onSelect) {{
      const container = document.getElementById(containerId);
      if (!container) return;
      if (totalPages <= 1) {{
        container.style.display = 'none';
        container.innerHTML = '';
        return;
      }}
      container.style.display = 'flex';
      const pages = [];
      for (let i = 1; i <= totalPages; i += 1) pages.push(i);
      container.innerHTML = [
        `<button class="pager-btn" data-page="${{page - 1}}" ${{page <= 1 ? 'disabled' : ''}}>‹</button>`,
        ...pages.map((value) => `<button class="pager-btn ${{value === page ? 'active' : ''}}" data-page="${{value}}">${{value}}</button>`),
        `<button class="pager-btn" data-page="${{page + 1}}" ${{page >= totalPages ? 'disabled' : ''}}>›</button>`,
      ].join('');
      container.querySelectorAll('.pager-btn[data-page]').forEach((button) => {{
        if (button.disabled) return;
        button.addEventListener('click', () => onSelect(Number(button.dataset.page || page)));
      }});
    }}
    function renderActiveTrades() {{
      const state = slicePage(activeTradesData, activePage);
      activePage = state.page;
      document.getElementById('active-body').innerHTML = state.items.map(activeRow).join('') || `<tr><td colspan="6">${{tr('noActive')}}</td></tr>`;
      renderPager('active-pager', state.page, state.totalPages, (nextPage) => {{
        activePage = nextPage;
        renderActiveTrades();
      }});
    }}
    function renderClosedTrades() {{
      const state = slicePage(closedTradesData, closedPage);
      closedPage = state.page;
      document.getElementById('closed-body').innerHTML = state.items.map(closedRow).join('') || `<tr><td colspan="4">${{tr('noClosed')}}</td></tr>`;
      renderPager('closed-pager', state.page, state.totalPages, (nextPage) => {{
        closedPage = nextPage;
        renderClosedTrades();
      }});
    }}
    function renderExchangeStatus(summary) {{
      const node = document.getElementById('exchange-status');
      if (!node || !summary) return;
      const ready = Boolean(summary.exchange_closed_ready);
      const syncing = Boolean(summary.sync_in_progress);
      let variant = 'syncing';
      let message = tr('No exchange closed trades found for this period.');

      if (ready) {{
        variant = 'exchange';
        message = tr('Closed trades and stats are loaded from exchange history.');
      }} else if (syncing) {{
        message = tr('Exchange closed trades are still syncing for this period.');
      }}

      const statusKey = `${{summary.range || currentRange}}|${{variant}}|${{message}}`;
      if (statusKey === lastExchangeStatusKey) return;
      lastExchangeStatusKey = statusKey;

      if (exchangeStatusTimer) {{
        clearTimeout(exchangeStatusTimer);
        exchangeStatusTimer = null;
      }}

      node.className = `exchange-status visible ${{variant}}`;
      node.textContent = message;
      exchangeStatusTimer = window.setTimeout(() => {{
        node.className = `exchange-status ${{variant}}`;
      }}, 3200);
    }}
    function applyDeviceMode() {{
      const isMobile = window.matchMedia('(max-width: 820px)').matches || window.matchMedia('(pointer: coarse)').matches;
      document.body.classList.toggle('mobile', isMobile);
    }}
    function settingLabel(key) {{
      return tr(settingsLabels[key] || key);
    }}
    function settingInput(key, value, type) {{
      if (key === 'tz') {{
        const selected = String(value ?? 'UTC');
        return `<select data-setting="${{key}}">
          ${{timezones.map((zone) => `<option value="${{zone}}" ${{zone === selected ? 'selected' : ''}}>${{zone}}</option>`).join('')}}
        </select>`;
      }}
      if (type === 'bool') {{
        return `<select data-setting="${{key}}">
          <option value="true" ${{value ? 'selected' : ''}}>${{tr('Enabled')}}</option>
          <option value="false" ${{!value ? 'selected' : ''}}>${{tr('Disabled')}}</option>
        </select>`;
      }}
      const inputType = type === 'int' || type === 'float' ? 'number' : 'text';
      const step = type === 'float' ? 'any' : '1';
      return `<input data-setting="${{key}}" type="${{inputType}}" step="${{step}}" value="${{value ?? ''}}">`;
    }}
    function renderSettingsGroup(containerId, keys, values, schema) {{
      const container = document.getElementById(containerId);
      if (!container) return;
      container.innerHTML = keys.map((key) => {{
        const meta = schema[key] || {{ type: 'str' }};
        const value = values[key];
        return `<div class="settings-field">
          <label>${{settingLabel(key)}}</label>
          ${{settingInput(key, value, meta.type)}}
        </div>`;
      }}).join('');
    }}
    function secretInputType(key, type) {{
      if (type === 'int') return 'number';
      if (key.includes('secret') || key.includes('hash')) return 'password';
      return 'text';
    }}
    function renderSecretFields(containerId, entries) {{
      const container = document.getElementById(containerId);
      if (!container) return;
      container.insertAdjacentHTML('beforeend', entries.map(([key, item]) => `
        <div class="settings-field">
          <label>${{settingLabel(key)}}</label>
          <input
            data-secret="${{key}}"
            type="${{secretInputType(key, (((settingsPayload || {{}}).secret_schema || {{}})[key] || {{}}).type || 'str')}}"
            value=""
            placeholder="${{item.configured ? item.masked : 'Not set'}}"
            autocomplete="off"
          >
          <div class="settings-hint">${{tr('Stored encrypted in DB. Leave blank to keep current value.')}}</div>
        </div>
      `).join(''));
    }}
    function renderSecrets(secrets) {{
      const entries = Object.entries(secrets || {{}});
      renderSecretFields('settings-bybit', entries.filter(([key]) => key.startsWith('bybit_')));
      renderSecretFields('settings-telegram', entries.filter(([key]) => key.startsWith('telegram_')));
      const note = document.getElementById('settings-note');
      if (note) note.textContent = tr('Secrets are stored encrypted in DB.');
    }}
    function renderSettings() {{
      if (!settingsPayload) return;
      renderSettingsGroup('settings-general', settingsGroups.general, settingsPayload.settings || {{}}, settingsPayload.schema || {{}});
      renderSettingsGroup('settings-bybit', settingsGroups.bybit, settingsPayload.settings || {{}}, settingsPayload.schema || {{}});
      renderSettingsGroup('settings-telegram', settingsGroups.telegram, settingsPayload.settings || {{}}, settingsPayload.schema || {{}});
      renderSettingsGroup('settings-trading', settingsGroups.trading, settingsPayload.settings || {{}}, settingsPayload.schema || {{}});
      renderSecrets(settingsPayload.secrets || {{}});
    }}
    async function loadSettings() {{
      const res = await fetch('api/settings', {{ cache: 'no-store' }});
      settingsPayload = await res.json();
      renderSettings();
    }}
    function openSettings() {{
      const modal = document.getElementById('settings-modal');
      if (!modal) return;
      loadSettings().then(() => {{
        modal.hidden = false;
      }});
    }}
    function closeSettings() {{
      const modal = document.getElementById('settings-modal');
      if (modal) modal.hidden = true;
    }}
    async function saveSettings() {{
      const payload = {{ settings: {{}} }};
      document.querySelectorAll('[data-setting]').forEach((node) => {{
        const key = node.getAttribute('data-setting');
        const type = ((settingsPayload || {{}}).schema || {{}})[key]?.type || 'str';
        let value = node.value;
        if (type === 'bool') value = value === 'true';
        if (type === 'int') value = Number.parseInt(value || '0', 10);
        if (type === 'float') value = Number.parseFloat(value || '0');
        payload.settings[key] = value;
      }});
      payload.secrets = {{}};
      document.querySelectorAll('[data-secret]').forEach((node) => {{
        const key = node.getAttribute('data-secret');
        const rawValue = String(node.value || '').trim();
        if (!rawValue) return;
        const type = ((settingsPayload || {{}}).secret_schema || {{}})[key]?.type || 'str';
        let value = rawValue;
        if (type === 'int') value = Number.parseInt(rawValue, 10);
        payload.secrets[key] = value;
      }});
      const res = await fetch('api/settings', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload),
      }});
      const data = await res.json();
      if (!res.ok || !data.ok) {{
        throw new Error(data.error || 'save_failed');
      }}
      settingsPayload = {{
        ...(settingsPayload || {{}}),
        settings: data.settings || payload.settings,
      }};
      closeSettings();
      window.location.reload();
    }}
    function rangeLabel(value) {{
      const labels = {{
        today: 'today',
        current_month: 'current month',
        month: 'month',
        quarter: 'quarter',
        previous_month: 'previous month',
        half_year: 'half of year',
        year: 'year',
        previous_year: 'previous year',
        all: 'all time',
      }};
      return tr(labels[value] || value);
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
        caption.textContent = tr('noClosedYet');
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
      caption.textContent = `${{tr('rangePrefix')}}: ${{rangeLabel(currentRange)}} | ${{tr('points')}}: ${{points.length}} | ${{tr('lastBalance')}}: ${{fmt(last)}} | ${{tr('currentWallet')}}: ${{fmt(currentWallet)}}`;
    }}
    function setEquitySyncCaption(data) {{
      const caption = document.getElementById('equity-caption');
      if (!caption || !data || !data.sync_in_progress) return;
      const suffix = tr('Exchange history sync in progress...');
      if (!Array.isArray(data.points) || !data.points.length) {{
        caption.textContent = suffix;
        return;
      }}
      if (data.history_source === 'local_fallback' || data.history_source === 'pnl_fallback') {{
        caption.textContent += ` | ${{tr('Showing local data until exchange sync completes.')}}`;
        return;
      }}
      caption.textContent += ` | ${{suffix}}`;
    }}
    function bindChartHover() {{
      const svg = document.getElementById('equity-chart');
      const hover = document.getElementById('equity-hover');
      const hoverLine = () => document.getElementById('hover-line');
      const hoverDot = () => document.getElementById('hover-dot');

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
        const pointLabel = tr(String(best.label || 'trade').toLowerCase());
        hover.innerHTML = `<strong>${{fmt(best.balance)}}</strong><br>${{pointLabel}}<br>${{(best.time || '').replace('T', ' ').slice(0, 16)}}`;
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
      drawEquity(data.points || [], data.current_wallet_balance ?? data.current_equity_balance ?? 0);
      setEquitySyncCaption(data);
      bindChartHover();
      syncRangeSelect();
    }}
    async function refresh() {{
      const res = await fetch(`api/stats?range=${{currentRange}}`, {{ cache: 'no-store' }});
      const data = await res.json();
      const s = data.summary;
      renderExchangeStatus(s);
      document.getElementById('cards').innerHTML = [
        card(tr('Profit PnL'), displayStat(s.profit_pnl, fmt), cls(s.profit_pnl)),
        card(tr('Loss PnL'), displayStat(s.loss_pnl, fmt), cls(-(Number(s.loss_pnl || 0)))),
        card(tr('Available Balance'), fmt(s.available_balance), cls(s.available_balance)),
        card(tr('Wallet Balance'), fmt(s.wallet_balance), cls(s.wallet_balance)),
        card(tr('Equity'), fmt(s.equity), cls(s.equity)),
        card(tr('Suggested Trades'), s.suggested_trades),
        card(tr('Accepted Trades'), s.accepted_trades),
        card(tr('Rejected Trades'), s.rejected_trades),
        card(tr('Active Trades'), s.open_trades),
        card(tr('Closed Trades'), s.closed_trades),
        card(tr('Winrate'), displayStat(s.winrate, (value) => `${{fmt(value)}}%`)),
        card(tr('Unrealized PnL'), displayStat(s.unrealized_pnl, fmt), cls(s.unrealized_pnl)),
        card(tr('Wins'), s.wins),
        card(tr('Losses'), s.losses),
        card(tr('TP hits'), displayStat(s.tp_hits_total)),
        card(tr('SL hits'), displayStat(s.sl_hits_total)),
      ].join('');
      setPnlTitle(s.unrealized_pnl);
      activeTradesData = Array.isArray(data.active_trades) ? data.active_trades : [];
      closedTradesData = Array.isArray(data.closed_trades) ? data.closed_trades : [];
      renderActiveTrades();
      renderClosedTrades();
      await refreshEquity();
    }}
    const rangeSelect = document.getElementById('range-select');
    if (rangeSelect) {{
      rangeSelect.addEventListener('change', async () => {{
        currentRange = rangeSelect.value;
        await refresh();
      }});
    }}
    const langSelect = document.getElementById('lang-select');
    if (langSelect) {{
      langSelect.addEventListener('change', async () => {{
        applyLanguage(langSelect.value || 'en');
        await refresh();
      }});
    }}
    const settingsToggle = document.getElementById('settings-toggle');
    if (settingsToggle) settingsToggle.addEventListener('click', openSettings);
    const settingsClose = document.getElementById('settings-close');
    if (settingsClose) settingsClose.addEventListener('click', closeSettings);
    const settingsCancel = document.getElementById('settings-cancel');
    if (settingsCancel) settingsCancel.addEventListener('click', closeSettings);
    const settingsBackdrop = document.getElementById('settings-backdrop');
    if (settingsBackdrop) settingsBackdrop.addEventListener('click', closeSettings);
    const settingsSave = document.getElementById('settings-save');
    if (settingsSave) {{
      settingsSave.addEventListener('click', async () => {{
        try {{
          await saveSettings();
        }} catch (error) {{
          const node = document.getElementById('settings-note');
          if (node) node.textContent = `${{tr('Save failed')}}: ${{error.message || error}}`;
        }}
      }});
    }}
    applyEmbedMode();
    applyLanguage(detectLanguage());
    initThemeToggle();
    applyDeviceMode();
    window.addEventListener('resize', applyDeviceMode);
    refresh();
    setInterval(refresh, refreshMs);
"""
