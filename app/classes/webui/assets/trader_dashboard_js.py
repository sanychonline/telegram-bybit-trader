import json

from classes.webui.i18n.registry import TRANSLATIONS


def build_trader_dashboard_js(brand_name, refresh_ms):
    translations_json = json.dumps(TRANSLATIONS, ensure_ascii=False)
    return f"""
    const refreshMs = {refresh_ms};
    const baseTitle = {json.dumps(f"{brand_name} Trader", ensure_ascii=False)};
    const langCookie = 'ui_lang';
    let currentRange = 'current_month';
    let currentLang = 'en';
    let chartState = [];
    const translations = {translations_json};
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
      document.querySelectorAll('#range-select option').forEach(option => {{
        option.textContent = rangeLabel(option.value);
      }});
      const panelTitles = document.querySelectorAll('.panel h3');
      if (panelTitles[0]) panelTitles[0].textContent = tr('Active Trades');
      if (panelTitles[1]) panelTitles[1].textContent = tr('Closed Trades');
      if (panelTitles[2]) panelTitles[2].textContent = tr('Balance Curve');
      document.getElementById('equity-caption').textContent = tr('Loading balance curve...');
      document.querySelectorAll('th').forEach(th => {{
        th.textContent = tr(th.textContent.trim());
      }});
      applyTheme(getCookie('ui_theme') || 'auto');
    }}
    function applyEmbedMode() {{
      const params = new URLSearchParams(window.location.search);
      if (params.get('embed') !== '1') return;
      const button = document.getElementById('theme-toggle');
      if (button) button.style.display = 'none';
      const lang = document.getElementById('lang-select')?.closest('.lang-control');
      if (lang) lang.style.display = 'none';
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
      drawEquity(data.points || [], data.current_wallet_balance || 0);
      bindChartHover();
      syncRangeSelect();
    }}
    async function refresh() {{
      const res = await fetch(`api/stats?range=${{currentRange}}`, {{ cache: 'no-store' }});
      const data = await res.json();
      const s = data.summary;
      document.getElementById('cards').innerHTML = [
        card(tr('Available Balance'), fmt(s.available_balance), cls(s.available_balance)),
        card(tr('Wallet Balance'), fmt(s.wallet_balance), cls(s.wallet_balance)),
        card(tr('Equity'), fmt(s.equity), cls(s.equity)),
        card(tr('Open Trades'), s.open_trades),
        card(tr('Closed Trades'), s.closed_trades),
        card(tr('Winrate'), `${{fmt(s.winrate)}}%`),
        card(tr('Non-Loss Rate'), `${{fmt(s.non_loss_rate)}}%`),
        card(tr('Realized PnL'), fmt(s.realized_pnl), cls(s.realized_pnl)),
        card(tr('Unrealized PnL'), fmt(s.unrealized_pnl), cls(s.unrealized_pnl)),
        card(tr('Wins'), s.wins),
        card(tr('Losses'), s.losses),
        card(tr('TP hits'), s.tp_hits_total),
        card(tr('SL hits'), s.sl_hits_total),
      ].join('');
      setPnlTitle(s.unrealized_pnl);
      document.getElementById('active-body').innerHTML = data.active_trades.map(activeRow).join('') || `<tr><td colspan="6">${{tr('noActive')}}</td></tr>`;
      document.getElementById('closed-body').innerHTML = data.closed_trades.map(closedRow).join('') || `<tr><td colspan="4">${{tr('noClosed')}}</td></tr>`;
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
    applyEmbedMode();
    applyLanguage(detectLanguage());
    initThemeToggle();
    applyDeviceMode();
    window.addEventListener('resize', applyDeviceMode);
    refresh();
    setInterval(refresh, refreshMs);
"""
