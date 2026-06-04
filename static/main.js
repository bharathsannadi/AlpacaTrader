/* SPY Auto Trader — Dashboard JS */

// socket.io auto-detects ws:// vs wss:// from the page origin — no options needed.
const socket = io();
let logEl     = document.getElementById("log-output");
let lineCount = 0;

// ── Credential cache (sessionStorage — clears on tab close, never persisted to disk) ──
// Used for silent re-auth after a network blip: the server reconnects the WS and
// emits login_required; we re-submit the cached credentials automatically so the
// user doesn't see the login modal for a transient disconnect.
const _CRED_KEY = "at_creds";
function _saveCreds(apiKey, apiSecret, paper) {
  try { sessionStorage.setItem(_CRED_KEY, JSON.stringify({ apiKey, apiSecret, paper })); }
  catch(e) { /* sessionStorage blocked (e.g. private mode) — ignore */ }
}
function _clearCreds() {
  try { sessionStorage.removeItem(_CRED_KEY); } catch(e) {}
}
function _loadCreds() {
  try { return JSON.parse(sessionStorage.getItem(_CRED_KEY) || "null"); }
  catch(e) { return null; }
}

// ── Socket events ─────────────────────────────────────────────────────────────
// Server emits state automatically on connect — no need to call refresh.
// Refresh is auth-required, so calling it before login causes a disconnect.
socket.on("state", updateUI);

// EOD analysis + learning report
socket.on("eod_report", (r) => {
  // Compact card: just stamp "last run". The full analysis (stats + narrative +
  // recommendations) is printed to the Log by the server (operator 2026-06-04).
  const w = document.getElementById("eod-when");
  if (w) { const t = (r.ts || "").slice(11, 16); w.textContent = t ? `last run ${t}` : ""; }
});

// Server tells us we need to re-authenticate (e.g. after a reconnect).
// Try silent re-auth first using sessionStorage credentials.
socket.on("login_required", () => {
  const creds = _loadCreds();
  if (creds && creds.apiKey) {
    // Silent re-auth — submit cached credentials without showing the login modal.
    appendLog("Reconnecting…", "INFO");
    socket.emit("login", { api_key: creds.apiKey, api_secret: creds.apiSecret, paper: creds.paper });
  } else if (!_guestCharts) {
    // No cached credentials — show the login modal (skip in guest charts mode).
    document.getElementById("login-overlay").classList.remove("hidden");
    appendLog("Session expired — please log in again.", "WARNING");
  }
});

let _gridInitialised = false;

socket.on("login_result", (r) => {
  const btn = document.getElementById("login-btn");
  btn.disabled    = false;
  btn.textContent = "Connect to Alpaca";
  if (r.success) {
    document.getElementById("login-overlay").classList.add("hidden");
    appendLog("Connected successfully.", "INFO");
    socket.emit("refresh");
    // Only build the chart grid once — reconnects reuse the existing panes.
    if (!_gridInitialised) {
      gridManager.init();
      _gridInitialised = true;
    }
    requestExecBrief();           // Load exec narrative on login
  } else {
    // Bad credentials (or server rejected silent re-auth) — clear cache & show modal.
    _clearCreds();
    document.getElementById("login-overlay").classList.remove("hidden");
    document.getElementById("login-error").textContent = r.error || "Login failed.";
  }
});

// ── Exec Brief ────────────────────────────────────────────────────────────────
function requestExecBrief() {
  const el = document.getElementById("exec-narrative");
  if (el) el.textContent = "Thinking…";
  socket.emit("get_exec_brief");
}

socket.on("exec_brief", (d) => {
  const el    = document.getElementById("exec-narrative");
  const chips = document.getElementById("exec-chips");
  if (el) el.textContent = d.narrative || "—";
  if (chips && d.stats) {
    const s = d.stats;
    chips.innerHTML = "";
    if (s.closed > 0) {
      chips.innerHTML += `<span class="exec-chip ${s.wins > s.losses ? 'green' : s.losses > s.wins ? 'red' : ''}">${s.wins}W ${s.losses}L</span>`;
    }
    if (s.open > 0) {
      chips.innerHTML += `<span class="exec-chip cyan">${s.open} open</span>`;
    }
    if (s.watching && s.watching !== "none") {
      chips.innerHTML += `<span class="exec-chip">${s.watching}</span>`;
    }
  }
});

socket.on("log", (d) => {
  appendLog(d.message, d.level);
  if (d.message.includes("SIGNAL [")) {
    document.getElementById("signal-banner").classList.add("show");
    document.getElementById("signal-text").textContent =
      d.message.replace(/^\d{2}:\d{2}:\d{2}\s+/, "");
  }
});

// ── Trade signal — show approval modal with sound + countdown ────────────────
let tradeTimer       = null;
let tradeTimeoutId   = null;

socket.on("trade_signal", (d) => {
  // When Auto-Trade is ON, the backend (TradeApproval.request) auto-approves
  // and submits the order without waiting for a user click. The signal is still
  // emitted so the chart marker / trade log update — we just shouldn't pop the
  // modal that asks for an approval the bot has already given itself.
  if (d.auto_trade) {
    appendLog(
      `✓ Auto-trade ${d.direction.toUpperCase()} ${d.symbol} ${d.contracts}× $${d.strike} ${(d.type || '').toUpperCase()} @ $${d.mid_price.toFixed(2)}`,
      "INFO"
    );
    return;
  }
  showTradeModal(d);
  playAlertSound();
});

function showTradeModal(d) {
  const card  = document.getElementById("trade-card");
  const tag   = document.getElementById("trade-tag");
  const cls   = d.direction === "bull" ? "bull" : "bear";

  card.className = "trade-card " + cls;
  tag.className  = "trade-tag "  + cls;
  tag.textContent = d.direction === "bull" ? "▲ BULLISH SIGNAL" : "▼ BEARISH SIGNAL";

  const dryTag = document.getElementById("trade-dry-tag");
  dryTag.style.display = d.dry_run ? "inline-block" : "none";

  const optType = (d.type || "").toUpperCase();
  const sym     = d.symbol || "SPY";
  document.getElementById("trade-title").textContent =
    `${sym} ${d.expiry} $${d.strike} ${optType}`;

  document.getElementById("trade-reason").textContent = d.reason || "—";

  document.getElementById("trade-contracts").textContent = `${d.contracts}×`;
  document.getElementById("trade-mid").textContent       = `$${d.mid_price.toFixed(2)}`;
  document.getElementById("trade-limit").textContent     = `$${d.limit_price.toFixed(2)}`;
  document.getElementById("trade-max-loss").textContent  =
    "$" + d.max_loss.toLocaleString("en-US", { minimumFractionDigits: 2 });
  document.getElementById("trade-stop").textContent      = `$${d.stop_price.toFixed(2)}`;
  document.getElementById("trade-target").textContent    = `$${d.target_50.toFixed(2)} / $${d.target_75.toFixed(2)}`;

  // Countdown
  let remaining = d.timeout || 60;
  document.getElementById("trade-timer").textContent = remaining;
  clearInterval(tradeTimer);
  clearTimeout(tradeTimeoutId);

  tradeTimer = setInterval(() => {
    remaining -= 1;
    document.getElementById("trade-timer").textContent = remaining;
    if (remaining <= 0) clearInterval(tradeTimer);
  }, 1000);

  // Hard auto-close fallback (server times out at d.timeout — match it client-side)
  tradeTimeoutId = setTimeout(() => closeTradeModal(), (d.timeout || 60) * 1000);

  // Show the modal
  document.getElementById("trade-modal").classList.add("show");
}

function closeTradeModal() {
  document.getElementById("trade-modal").classList.remove("show");
  clearInterval(tradeTimer);
  clearTimeout(tradeTimeoutId);
}

function respondTrade(approved) {
  socket.emit("trade_response", { approved });
  closeTradeModal();
}

// Generate a 2-tone alert beep using Web Audio API (no external file needed)
function playAlertSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const playTone = (freq, start, dur) => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type    = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + start);
      gain.gain.exponentialRampToValueAtTime(0.25,   ctx.currentTime + start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + start);
      osc.stop(ctx.currentTime + start + dur);
    };
    playTone(880,  0,    0.18);   // A5
    playTone(1320, 0.20, 0.18);   // E6
    playTone(1760, 0.40, 0.30);   // A6
  } catch (e) {
    /* audio context may need user interaction first */
  }
}

// Guest charts mode: /charts is viewable WITHOUT Alpaca login (bars come from
// yfinance via the ungated get_chart_data handler — no TradingClient needed).
let _guestCharts = false;

// ── UI update ─────────────────────────────────────────────────────────────────
function updateUI(s) {
  if (!s.logged_in && !_guestCharts) {
    document.getElementById("login-overlay").classList.remove("hidden");
  }

  // Price ticker (active symbol)
  if (s.spy_price) {
    const chg  = s.spy_change_pct ?? 0;
    const cls  = chg > 0 ? "up" : chg < 0 ? "down" : "neutral";
    const sign = chg > 0 ? "+" : "";
    setEl("spy-price", `$${s.spy_price.toFixed(2)}`, `ticker-price ${cls}`);
    setEl("spy-chg",   `${sign}${chg.toFixed(2)}%`,  `ticker-chg ${cls}`);
  }
  // Market session badge
  if (s.market_session) {
    const badge = document.getElementById("session-badge");
    if (badge) {
      const labels = { pre: "PRE", regular: "OPEN", after: "AFTER", closed: "CLOSED" };
      badge.textContent = labels[s.market_session] ?? s.market_session.toUpperCase();
      badge.className   = `session-badge ${s.market_session}`;
    }
  }

  // VIX
  if (s.vix != null) {
    const cls = s.vix > 28 ? "down" : s.vix > 20 ? "neutral" : "up";
    setEl("hdr-vix", s.vix.toFixed(1), `value ${cls}`);
  }

  // Data freshness panel — per-source age with green/yellow/red dots
  if (s.data_freshness) renderFreshness(s.data_freshness);

  if (s.equity_curve) renderEquityCurve(s.equity_curve);
  if (s.slippage) renderSlippage(s.slippage);
  if (s.daily_positions != null) renderDailyPositions(s.daily_positions);
  if (s.incubation) renderIncubation(s.incubation);

  // Sync max-portfolio-risk input to the active value (unless user is editing it)
  if (s.max_portfolio_risk_pct != null) {
    const mpr = document.getElementById("max-portfolio-risk");
    if (mpr && document.activeElement !== mpr) mpr.value = s.max_portfolio_risk_pct;
  }

  // Account
  if (s.account_value) {
    const fmt = v => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2 });
    setEl("hdr-account", fmt(s.account_value));
    setEl("hdr-bp",      fmt(s.buying_power ?? 0));
    // Risk per Trade control was removed; guard the (now-optional) element so a
    // missing #risk-pct can't throw and abort the rest of updateUI (which would
    // blank the Positions tab and stop other state updates).
    const _riskEl = document.getElementById("risk-pct");
    if (_riskEl) setEl("hdr-risk", fmt(s.account_value * (parseFloat(_riskEl.value) / 100)));
  }

  // Active symbol — sync ticker display
  if (s.active_symbol) {
    currentSymbol = s.active_symbol;
    setEl("ticker-symbol", s.active_symbol);
  }

  // Per-symbol session dots in tab bar + Start/Stop All button enable-state
  if (s.sessions) {
    const entries = Object.entries(s.sessions);
    let anyRunning = false;
    let allRunning = entries.length > 0;
    entries.forEach(([sym, running]) => {
      const dot = document.getElementById(`tab-dot-${sym}`);
      if (dot) dot.className = `tab-dot${running ? " running" : ""}`;
      if (running) anyRunning = true;
      else         allRunning = false;
    });
    // Start All disabled when every symbol is already running.
    // Stop All disabled when nothing is running.
    const startAll = document.getElementById("btn-start-all");
    const stopAll  = document.getElementById("btn-stop-all");
    if (startAll) {
      startAll.disabled = allRunning;
      startAll.title    = allRunning ? "All sessions already running" : "";
    }
    if (stopAll) {
      stopAll.disabled = !anyRunning;
      stopAll.title    = anyRunning ? "" : "No sessions running";
    }
  }

  // Mode pill — shows paper/live + risk mode (3R-A.4)
  const pill = document.getElementById("mode-pill");
  if (pill) {
    const riskMode = s.risk_mode || (s.paper_mode ? "paper_aggressive" : "live_disciplined");
    let pillText;
    if (s.paper_mode) {
      pillText = "PAPER (max-risk)";
    } else if (riskMode === "live_disciplined") {
      pillText = "LIVE (disciplined)";
    } else {
      pillText = "LIVE";
    }
    if (s.dry_run) pillText += " · DRY RUN";
    pill.textContent = pillText;
    pill.className = "mode-pill" +
      (!s.paper_mode ? " live" : " paper-on");
    pill.title = s.paper_mode
      ? "Paper mode: max-risk settings active for learning. Paper P&L ≠ edge validation."
      : "Live mode: disciplined profile forced (4%/20%/20%). UI risk overrides ignored.";
  }

  document.getElementById("dry-run-toggle").checked = !!s.dry_run;

  setStreamButtons(s.streaming);

  // Automation toggles
  syncToggleBtn("btn-auto-schedule", s.auto_schedule !== false);
  syncToggleBtn("btn-news-filter",   s.news_filter_enabled !== false);
  syncToggleBtn("btn-trade-memory",  s.trade_memory_enabled !== false);
  syncToggleBtn("btn-debate",        s.debate_enabled === true);
  syncToggleBtn("btn-auto-trade",    s.auto_trade === true);
  _autoTrade = s.auto_trade === true;  // mirror for screener execute confirm gate
  _updateAutoExecBtn(s.auto_execute_options === true, s.auto_exec_today);

  // Session end time input
  if (s.session_end) {
    const el = document.getElementById("session-end");
    if (el && document.activeElement !== el) el.value = s.session_end;
  }

  // Stepper values
  if (s.vix_max != null)       setEl("val-vix-max",       s.vix_max);
  if (s.stop_loss != null)     setEl("val-stop-loss",     `-${s.stop_loss}%`);
  if (s.profit_target != null) setEl("val-profit-target", `+${s.profit_target}%`);
  if (s.dte_min != null)       setEl("val-dte-min",       s.dte_min);
  if (s.dte_max != null)       setEl("val-dte-max",       s.dte_max);

  if (s.timestamp) setEl("hdr-time", s.timestamp);

  // Open positions card
  if (s.open_positions !== undefined) renderPositions(s.open_positions, s.auto_positions);

  // Positions tab (#24): cache + re-render if it's the active view
  if (s.open_positions !== undefined || s.auto_positions !== undefined ||
      s.account_positions !== undefined || s.account_options !== undefined) {
    _lastPositions = { open:    s.open_positions    || _lastPositions.open,
                       auto:    s.auto_positions    || _lastPositions.auto,
                       account: s.account_positions || _lastPositions.account,
                       options: s.account_options   || _lastPositions.options };
    if (document.body.classList.contains("view-positions")) _renderPositionsTable();
  }

  // Exit config inputs — only sync when there are NO pending edits (Save disabled),
  // so a state push can't clobber what the user is typing.
  if (s.exit_config) _lastExitCfg = s.exit_config;   // live exit settings for the Positions exit column
  const _saveBtn = document.getElementById("btn-save-exit");
  if (s.exit_config && (!_saveBtn || _saveBtn.disabled)) {
    const ec = s.exit_config;
    const set = (id, v) => { const el = document.getElementById(id); if (el && document.activeElement !== el && v != null) el.value = v; };
    set("ex-stock-tp", ec.stock_tp_pct); set("ex-stock-sl", ec.stock_sl_pct); set("ex-stock-stall", ec.stock_stall_days);
    set("ex-opt-tp", ec.opt_tp_pct);     set("ex-opt-sl", ec.opt_sl_pct);     set("ex-opt-stall", ec.opt_stall_min);
    set("ex-cap", ec.time_cap_days);
  }
  // Notes panel retired 2026-06-04 — closed trades now appear in the Log.

  // Refresh exec brief when trade count changes
  const newCount = (s.trades_today || []).length;
  if (newCount !== (updateUI._lastTradeCount ?? -1)) {
    updateUI._lastTradeCount = newCount;
    if (s.logged_in && newCount > 0) requestExecBrief();
  }
}

function syncToggleBtn(id, on) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.textContent = on ? "ON" : "OFF";
  btn.classList.toggle("off", !on);
}

// ── Equity Curve card ──────────────────────────────────────────────────────
function renderEquityCurve(ec) {
  const empty = document.getElementById("equity-empty");
  const body  = document.getElementById("equity-body");
  if (!empty || !body) return;
  const pts = ec.points || [];
  if (!pts.length) { empty.style.display = ""; body.style.display = "none"; return; }
  empty.style.display = "none"; body.style.display = "";

  const setTxt = (id, txt, cls) => {
    const el = document.getElementById(id); if (!el) return;
    el.textContent = txt;
    el.style.color = cls === "g" ? "var(--green)" : cls === "r" ? "var(--red)" : "var(--text)";
  };
  setTxt("eq-current", "$" + (ec.current ?? 0).toLocaleString("en-US", {minimumFractionDigits:2}));
  setTxt("eq-ret", (ec.total_ret_pct>=0?"+":"") + (ec.total_ret_pct ?? 0) + "%", (ec.total_ret_pct>=0)?"g":"r");
  const ddCls = v => (v >= 8 ? "r" : "");
  setTxt("eq-dd5",  (ec.dd5_pct ?? 0)  + "%", ddCls(ec.dd5_pct));
  setTxt("eq-dd20", (ec.dd20_pct ?? 0) + "%", ddCls(ec.dd20_pct));
  setTxt("eq-dd30", (ec.dd30_pct ?? 0) + "%", ddCls(ec.dd30_pct));
  setTxt("eq-n", String(ec.n ?? pts.length));

  // Sparkline (300x48 viewBox, padded)
  const svg = document.getElementById("equity-spark");
  if (svg) {
    const eqs = pts.map(p => p.equity);
    const lo = Math.min(...eqs), hi = Math.max(...eqs), span = (hi - lo) || 1;
    const W = 300, H = 48, pad = 3;
    const xs = i => pad + (i / Math.max(1, pts.length - 1)) * (W - 2*pad);
    const ys = v => H - pad - ((v - lo) / span) * (H - 2*pad);
    const d = eqs.map((v,i) => (i?"L":"M") + xs(i).toFixed(1) + " " + ys(v).toFixed(1)).join(" ");
    const up = eqs[eqs.length-1] >= eqs[0];
    const col = up ? "#00e5a0" : "#ff3d68";
    svg.innerHTML =
      `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.5"/>` +
      `<path d="${d} L ${xs(pts.length-1).toFixed(1)} ${H-pad} L ${pad} ${H-pad} Z" fill="${col}" opacity="0.10"/>`;
  }
}

// ── Fill Slippage card ─────────────────────────────────────────────────────
function renderSlippage(sl) {
  const empty = document.getElementById("slip-empty");
  const body  = document.getElementById("slip-body");
  if (!empty || !body) return;
  if (!sl || !sl.n) { empty.style.display = ""; body.style.display = "none"; return; }
  empty.style.display = "none"; body.style.display = "";
  const sign = v => (v >= 0 ? "+" : "") + v + " bps";
  const col  = v => (v > 10 ? "var(--red)" : v > 3 ? "var(--yellow)" : "var(--green)");
  const set  = (id, v, c) => { const e=document.getElementById(id); if(e){e.textContent=v; if(c)e.style.color=c;} };
  set("slip-avg",  sign(sl.avg_bps),  col(sl.avg_bps));
  set("slip-last", sign(sl.last_bps), col(sl.last_bps));
  set("slip-worst",sign(sl.worst_bps),col(sl.worst_bps));
  const tcol = sl.trend === "worsening" ? "var(--red)" : sl.trend === "improving" ? "var(--green)" : "var(--muted)";
  set("slip-trend", sl.trend + (sl.trend==="worsening"?" ▲":sl.trend==="improving"?" ▼":" —"), tcol);
  // vs-model delta (3R-C.2)
  if (sl.avg_delta_vs_model != null) {
    const d = sl.avg_delta_vs_model;
    set("slip-delta", sign(d), d > 3 ? "var(--red)" : d > 0 ? "var(--yellow)" : "var(--green)");
    const alertEl = document.getElementById("slip-alert");
    if (alertEl) alertEl.style.display = sl.model_alert ? "" : "none";
  }
}

// ── Daily positions panel (PA-UI) ─────────────────────────────────────────
function renderDailyPositions(positions) {
  const el = document.getElementById("daily-positions-list");
  if (!el) return;
  if (!positions || !positions.length) {
    el.innerHTML = '<div class="pos-empty" style="color:var(--muted);font-size:var(--fs-xs);padding:4px 0;">No active daily positions</div>';
    return;
  }
  el.innerHTML = positions.map(p => {
    const pnl = p.pnl_usd != null ? (p.pnl_usd >= 0 ? `<span style="color:var(--green)">+$${p.pnl_usd.toFixed(0)}</span>` : `<span style="color:var(--red)">-$${Math.abs(p.pnl_usd).toFixed(0)}</span>`) : "—";
    const instr = p.structure || p.instrument || "—";
    const debit = p.entry_debit || p.est_debit || "—";
    return `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:11px">
      <div>
        <span style="font-weight:700;color:var(--blue)">${p.sym}</span>
        <span style="color:var(--muted);margin-left:4px">${instr}</span>
      </div>
      <div style="text-align:right">
        <div style="color:var(--muted)">${p.entry_date || "—"}</div>
        <div>debit=${debit} &nbsp; ${pnl}</div>
        <div style="color:var(--muted)">[${p.status}]</div>
      </div>
    </div>`;
  }).join("");
}

// ── Paper incubation tracker (PA-UI) ──────────────────────────────────────
function renderIncubation(inc) {
  if (!inc || !inc.start_date) return;
  const days = inc.days_running || 0;
  const target = inc.target_days || 28;
  const pct = Math.min(100, Math.round(days / target * 100));
  const set = (id, v) => { const e=document.getElementById(id); if(e) e.textContent=v; };
  set("incub-days",   days);
  set("incub-trades", inc.trade_count || 0);
  set("incub-wins",   inc.wins || 0);
  set("incub-losses", inc.losses || 0);
  const fill = document.getElementById("incub-progress-fill");
  if (fill) fill.style.width = pct + "%";
}

// ── Data Freshness panel ───────────────────────────────────────────────────
// Server sends s.data_freshness = { "bars:SPY": {age_sec, max_age, stale, source}, ... }
// We render rows sorted by source, with a green/yellow/red dot per row:
//   green  = age < 50% of max
//   yellow = age < max
//   red    = age > max (stale)
function renderFreshness(snap) {
  const empty = document.getElementById("freshness-empty");
  const table = document.getElementById("freshness-table");
  const body  = document.getElementById("freshness-body");
  if (!empty || !table || !body) return;

  const keys = Object.keys(snap);
  if (keys.length === 0) {
    empty.style.display = "";
    table.style.display = "none";
    return;
  }
  empty.style.display = "none";
  table.style.display = "";

  // Sort: critical (option_quote, bars, vix) first, then alphabetical
  const priority = { option_quote: 0, bars: 1, vix: 2, price: 3, news: 4 };
  keys.sort((a, b) => {
    const pa = priority[a.split(":")[0]] ?? 9;
    const pb = priority[b.split(":")[0]] ?? 9;
    return pa - pb || a.localeCompare(b);
  });

  const rows = keys.map(key => {
    const f       = snap[key];
    const age     = f.age_sec;
    const maxAge  = f.max_age;
    const stale   = f.stale;
    const ratio   = maxAge > 0 ? age / maxAge : 0;
    const dotCls  = stale ? "red" : ratio > 0.5 ? "yellow" : "green";
    const ageStr  = age < 60 ? `${age.toFixed(0)}s` : `${(age / 60).toFixed(1)}m`;
    const rowCls  = stale ? "freshness-row stale" : "freshness-row";
    // Escape user-visible text fields to be safe (key/source come from trader).
    const keyEsc  = escapeHtml(key);
    const srcEsc  = escapeHtml(f.source || "");
    return `
      <tr class="${rowCls}">
        <td><span class="fresh-dot ${dotCls}"></span><span class="freshness-key">${keyEsc}</span></td>
        <td><span class="freshness-source">${srcEsc}</span></td>
        <td class="age-col">${ageStr}</td>
      </tr>`;
  });
  body.innerHTML = rows.join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function setEl(id, text, className) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  if (className !== undefined) el.className = className;
}

function setSession(_name, _running) { /* legacy stub — unused */ }

function setStreamButtons(streaming) {
  const dot   = document.getElementById("dot-stream");
  const start = document.getElementById("btn-start-stream");
  const stop  = document.getElementById("btn-stop-stream");
  if (dot)   dot.className  = `stream-dot ${streaming ? "live" : ""}`;
  if (start) start.disabled = !!streaming;
  if (stop)  stop.disabled  = !streaming;
}

// ── Log terminal ──────────────────────────────────────────────────────────────
const MAX_LOG_LINES = 500;
const TIME_RE       = /^(\d{2}:\d{2}:\d{2})\s*/;

function appendLog(msg, level) {
  // Build with createElement + textContent (no innerHTML — XSS-safe)
  const line     = document.createElement("span");
  const isSignal = msg.includes("SIGNAL") || msg.includes("─");
  const cls      = isSignal             ? "log-SIGNAL"
                 : level === "WARNING"  ? "log-WARNING"
                 : level === "ERROR"    ? "log-ERROR"
                 : "log-INFO";
  line.className = `log-line ${cls}`;

  const m = msg.match(TIME_RE);
  if (m) {
    const ts = document.createElement("span");
    ts.className   = "log-time";
    ts.textContent = m[1];
    line.appendChild(ts);
    line.appendChild(document.createTextNode(" " + msg.slice(m[0].length) + "\n"));
  } else {
    line.textContent = msg + "\n";
  }

  logEl.appendChild(line);
  lineCount++;
  if (lineCount > MAX_LOG_LINES) {
    logEl.removeChild(logEl.firstChild);
    lineCount--;
  }
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() {
  while (logEl.firstChild) logEl.removeChild(logEl.firstChild);
  lineCount = 0;
}

// ── Controls ──────────────────────────────────────────────────────────────────
function doLogin() {
  const btn       = document.getElementById("login-btn");
  const apiKey    = document.getElementById("login-api-key").value.trim();
  const apiSecret = document.getElementById("login-api-secret").value.trim();
  const paper     = document.getElementById("login-paper").checked;
  document.getElementById("login-error").textContent = "";

  if (!apiKey || !apiSecret) {
    document.getElementById("login-error").textContent = "Please enter API key and secret.";
    return;
  }

  // Cache credentials for silent reconnect (sessionStorage — cleared on tab close).
  _saveCreds(apiKey, apiSecret, paper);

  btn.disabled    = true;
  btn.textContent = "Connecting...";
  socket.emit("login", { api_key: apiKey, api_secret: apiSecret, paper });
}

function doLogout() {
  _clearCreds();          // wipe session cache on explicit logout
  _gridInitialised = false;
  socket.emit("logout");
}
function startStream()       { socket.emit("start_stream");         }
function stopStream()        { socket.emit("stop_stream");          }
function toggleAutoSchedule(){ socket.emit("toggle_auto_schedule"); }
function toggleNewsFilter()  { socket.emit("toggle_news_filter");   }
function toggleTradeMemory() { socket.emit("toggle_trade_memory");  }
function toggleDebate()      { socket.emit("toggle_debate");        }
function toggleAutoTrade()   { socket.emit("toggle_auto_trade");    }

// Per-symbol session controls
function startSession(sym) {
  socket.emit("start_session", { symbol: sym || currentSymbol });
}
function stopSession(sym) {
  socket.emit("stop_session", { symbol: sym || currentSymbol });
}
function startAllSessions() { socket.emit("start_all_sessions"); }
function stopAllSessions()  { socket.emit("stop_all_sessions");  }

function syncPositions() {
  const btn = document.getElementById("btn-sync-positions");
  if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
  socket.emit("sync_positions");
}
socket.on("sync_positions_done", (data) => {
  const btn = document.getElementById("btn-sync-positions");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "⟳ Sync Positions";
    const added = data && data.added ? data.added : 0;
    if (added > 0) btn.title = `Last sync: +${added} position(s) added`;
  }
});

function setSessionEnd() {
  socket.emit("set_session_end", {
    session_end: document.getElementById("session-end").value,
  });
}

// Adjust a numeric parameter by `delta`, clamped to [min, max]
function adjustParam(field, delta, min, max) {
  const idMap = {
    vix_max:       "val-vix-max",
    stop_loss:     "val-stop-loss",
    profit_target: "val-profit-target",
    dte_min:       "val-dte-min",
    dte_max:       "val-dte-max",
  };
  const el = document.getElementById(idMap[field]);
  if (!el) return;
  // Strip non-numeric characters (e.g. "-50%" → 50, "+75%" → 75)
  const current = parseInt(el.textContent.replace(/[^0-9]/g, ""), 10) || 0;
  const next    = Math.max(min, Math.min(max, current + delta));
  if (next === current) return;
  socket.emit("set_param", { field, value: next });
}

function formatTime12h(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const ampm   = h >= 12 ? "PM" : "AM";
  const h12    = h % 12 || 12;
  return `${h12}:${m.toString().padStart(2, "0")} ${ampm}`;
}

function setDryRun() {
  socket.emit("set_dry_run", { dry_run: document.getElementById("dry-run-toggle").checked });
}

function setRisk() {
  const val = parseFloat(document.getElementById("risk-pct").value);
  if (!isNaN(val) && val > 0) socket.emit("set_risk", { risk_pct: val });
}

function setMaxPortfolioRisk() {
  const val = parseFloat(document.getElementById("max-portfolio-risk").value);
  if (!isNaN(val) && val >= 0.5) socket.emit("set_max_portfolio_risk", { pct: val });
}

// ── Enter key on login ────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Open the view that matches the URL path (/charts, /screener, /log), else Settings
  const _path = window.location.pathname.replace(/\/+$/, "");
  if (_path === "/charts") {
    // Guest charts — no login required (yfinance data). Hide the modal + build the grid.
    _guestCharts = true;
    const ov = document.getElementById("login-overlay");
    if (ov) ov.classList.add("hidden");
    if (!_gridInitialised) { gridManager.init(); _gridInitialised = true; }
    showCharts();
  }
  else if (_path === "/screener") { showScreener(); }
  else if (_path === "/log")      { showLog(); }
  else                            { _setViewMode("settings"); }

  // Charts live on the standalone charts server (:5001). On the trading app
  // (not guest-charts mode) hide the Charts tab + pane-count dropdown.
  if (!_guestCharts) {
    document.querySelectorAll("[data-charts-only]").forEach(el => { el.style.display = "none"; });
  }


  ["login-api-key", "login-api-secret"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
  });

  // Drag-drop layout (reorder within / between panels)
  restoreCardOrder();
  restoreCardSizes();
  initDragDrop();
  initCardResize();
  updateGridLayout();

  // Panel resize divider
  restorePanelWidth();
  initPanelResize();
});

// ── Card layout persistence (order + size) ────────────────────────────────────
const STORAGE_KEY      = "spyTraderCardOrder";
const CARD_SIZES_KEY   = "spyTraderCardSizes";
let draggedCard        = null;
let _resizeSaveTimer   = null;

function saveCardSizes() {
  const sizes = {};
  document.querySelectorAll(".left-panel .card[data-card-id]").forEach(card => {
    const w = card.style.width;
    const h = card.style.height;
    if (w || h) sizes[card.dataset.cardId] = { w, h };
  });
  localStorage.setItem(CARD_SIZES_KEY, JSON.stringify(sizes));
}

function restoreCardSizes() {
  try {
    const saved = JSON.parse(localStorage.getItem(CARD_SIZES_KEY) || "{}");
    Object.entries(saved).forEach(([id, sz]) => {
      const card = document.querySelector(`[data-card-id="${id}"]`);
      if (!card) return;
      if (sz.w) card.style.width  = sz.w;
      if (sz.h) card.style.height = sz.h;
    });
  } catch (_) {}
}

// Attach a single ResizeObserver on all settings cards so any resize is saved
function initCardResize() {
  const ro = new ResizeObserver(() => {
    clearTimeout(_resizeSaveTimer);
    _resizeSaveTimer = setTimeout(saveCardSizes, 350);
  });
  document.querySelectorAll(".left-panel .card[data-card-id]").forEach(c => ro.observe(c));
}

function initDragDrop() {
  document.querySelectorAll(".card[data-card-id]").forEach(card => {
    // Default NOT draggable — only the grip enables dragging so text stays selectable
    card.draggable = false;

    const grip = card.querySelector(".drag-grip");
    if (grip) {
      grip.addEventListener("mousedown", () => { card.draggable = true; });
    }

    card.addEventListener("dragstart", (e) => {
      draggedCard = card;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", card.dataset.cardId);
      setTimeout(() => card.classList.add("dragging"), 0);
    });

    card.addEventListener("dragend", () => {
      card.draggable = false;        // re-lock after drag completes
      card.classList.remove("dragging");
      clearDragMarkers();
      saveCardOrder();
      updateGridLayout();
      draggedCard = null;
    });

    card.addEventListener("dragover", (e) => {
      if (!draggedCard || card === draggedCard) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const rect    = card.getBoundingClientRect();
      const isAbove = e.clientY < rect.top + rect.height / 2;
      card.classList.toggle("drag-above",  isAbove);
      card.classList.toggle("drag-below", !isAbove);
    });

    card.addEventListener("dragleave", () => {
      card.classList.remove("drag-above");
      card.classList.remove("drag-below");
    });

    card.addEventListener("drop", (e) => {
      e.preventDefault();
      if (!draggedCard || card === draggedCard) return;
      const rect    = card.getBoundingClientRect();
      const isAbove = e.clientY < rect.top + rect.height / 2;
      const parent  = card.parentNode;
      parent.insertBefore(draggedCard, isAbove ? card : card.nextSibling);
      clearDragMarkers();
    });
  });

  document.querySelectorAll(".left-panel, .right-panel").forEach(panel => {
    panel.addEventListener("dragover", (e) => {
      if (!draggedCard) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    });
    panel.addEventListener("drop", (e) => {
      if (!draggedCard) return;
      e.preventDefault();
      if (e.target === panel) panel.appendChild(draggedCard);
    });
  });
}

function clearDragMarkers() {
  document.querySelectorAll(".card.drag-above, .card.drag-below").forEach(c => {
    c.classList.remove("drag-above");
    c.classList.remove("drag-below");
  });
}

function saveCardOrder() {
  const left  = Array.from(document.querySelectorAll(".left-panel  > [data-card-id]")).map(c => c.dataset.cardId);
  const right = Array.from(document.querySelectorAll(".right-panel > [data-card-id]")).map(c => c.dataset.cardId);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ left, right }));
}

function restoreCardOrder() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return;
  try {
    const { left = [], right = [] } = JSON.parse(saved);
    const leftPanel  = document.querySelector(".left-panel");
    const rightPanel = document.querySelector(".right-panel");
    left.forEach(id => {
      const card = document.querySelector(`[data-card-id="${id}"]`);
      if (card) leftPanel.appendChild(card);
    });
    right.forEach(id => {
      const card = document.querySelector(`[data-card-id="${id}"]`);
      if (card) rightPanel.appendChild(card);
    });
  } catch (e) {
    console.warn("Could not restore card order:", e);
  }
}

function resetLayout() {
  if (!confirm("Reset all card positions and sizes to defaults?")) return;
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(CARD_SIZES_KEY);
  localStorage.removeItem("spyTraderLayout_v2");
  localStorage.removeItem("spyTraderLayoutLocked");
  localStorage.removeItem(PANEL_WIDTH_KEY);
  location.reload();
}

// ── Panel resize (drag the vertical divider) ──────────────────────────────────
const PANEL_WIDTH_KEY = "spyTraderPanelWidth";

function initPanelResize() {
  const divider   = document.getElementById("panel-divider");
  const dashboard = document.querySelector(".dashboard");
  if (!divider || !dashboard) return;

  let startX = 0;
  let startWidth = 0;

  divider.addEventListener("mousedown", (e) => {
    e.preventDefault();
    startX     = e.clientX;
    startWidth = document.getElementById("left-panel").getBoundingClientRect().width;
    divider.classList.add("resizing");

    const onMove = (ev) => {
      const delta    = ev.clientX - startX;
      const totalW   = dashboard.getBoundingClientRect().width - 5; // minus divider
      const newLeft  = Math.max(160, Math.min(startWidth + delta, totalW - 200));
      dashboard.style.gridTemplateColumns = `${newLeft}px 5px 1fr`;
    };

    const onUp = () => {
      divider.classList.remove("resizing");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
      // Persist the left-panel pixel width
      const leftW = document.getElementById("left-panel").getBoundingClientRect().width;
      localStorage.setItem(PANEL_WIDTH_KEY, Math.round(leftW));
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
  });
}

function restorePanelWidth() {
  const saved     = localStorage.getItem(PANEL_WIDTH_KEY);
  const dashboard = document.querySelector(".dashboard");
  if (saved && dashboard) {
    dashboard.style.gridTemplateColumns = `${saved}px 5px 1fr`;
  }
}

// ── Clipboard copy helpers ────────────────────────────────────────────────────
function copyLog() {
  const lines = Array.from(document.querySelectorAll("#log-output .log-line"))
    .map(el => el.textContent.trimEnd())
    .join("\n");
  navigator.clipboard.writeText(lines).then(() => {
    showCopied("btn-copy-log");
  }).catch(() => {
    // Fallback: select all text in the element
    const range = document.createRange();
    range.selectNodeContents(document.getElementById("log-output"));
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
  });
}

function showCopied(btnId) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 1500);
}

function updateGridLayout() {
  const dashboard = document.querySelector(".dashboard");
  const left      = document.querySelector(".left-panel");
  const right     = document.querySelector(".right-panel");
  if (!dashboard) return;
  const leftCount  = left  ? left.querySelectorAll("[data-card-id]").length  : 0;
  const rightCount = right ? right.querySelectorAll("[data-card-id]").length : 0;
  dashboard.classList.toggle("no-left",  leftCount  === 0);
  dashboard.classList.toggle("no-right", rightCount === 0);
}

// ── Multi-Pane Chart Grid ─────────────────────────────────────────────────────

// Full tradable universe (mirrors scripts/universe.py ALL, sorted). Keep in sync
// if universe.py changes — these populate every chart pane's symbol dropdown.
const SYMBOLS = [
  "AAPL","ADBE","AMD","AMZN","ARKK","ARM","AVGO","BAC","C","CBRE",
  "CRM","CRWD","CRWV","DIA","EEM","EFA","EWZ","FXI","GDX","GLD",
  "GLW","GOOG","HOOD","HYG","IBM","IEF","INTC","IWM","IYR","JPM",
  "KRE","LRCX","MA","META","MSFT","MU","NET","NFLX","NKE","NOW",
  "NVDA","ORCL","PLTR","QQQ","RSP","SLV","SMH","SOFI","SOXX","SPY",
  "TEAM","TLT","TSM","UBER","UNH","USO","V","VOO","VTI","WFC",
  "XBI","XHB","XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE",
  "XLU","XLV","XLY","XOP",
];

const LIVE_RANGES        = new Set(["1D", "5D"]);
const CHART_AUTO_REFRESH = 15_000;

const _DEFAULT_SYMS = {
  1: ["SPY"],
  2: ["SPY","QQQ"],
  4: ["SPY","QQQ","NVDA","AAPL"],
  6: ["SPY","QQQ","NVDA","AAPL","META","AMZN"],
  8: ["SPY","QQQ","NVDA","AAPL","META","AMZN","MSFT","GOOG"],
};

// Legacy compat — pane 0's symbol tracks currentSymbol
let currentSymbol = localStorage.getItem("chart_pane_0_sym") || "SPY";

// ── Timeframe presets (interval + look-back range) ────────────────────────────
const TIMEFRAMES = {
  "1m":  { interval: "1m",  range: "1D"  },
  "5m":  { interval: "5m",  range: "5D"  },
  "15m": { interval: "15m", range: "1D"  },
  "30m": { interval: "30m", range: "5D"  },
  "1h":  { interval: "1h",  range: "1M"  },
  "1D":  { interval: "1d",  range: "1Y"  },
};

// ── ChartPane: one independent LightweightCharts instance ────────────────────
class ChartPane {
  constructor(id, gridEl) {
    this.id  = id;
    this.sym = localStorage.getItem(`chart_pane_${id}_sym`) || "SPY";
    // Timeframe: new key preferred, fall back to old iv key
    this.tf  = localStorage.getItem(`chart_pane_${id}_tf`) ||
               this._tfFromIv(localStorage.getItem(`chart_pane_${id}_iv`) || "15m");
    const tfMap   = TIMEFRAMES[this.tf] || TIMEFRAMES["15m"];
    this.interval = tfMap.interval;
    this.range    = tfMap.range;
    this._seq          = 0;
    this._refreshTimer = null;
    this._lastClose    = null;
    this._prevClose    = null;
    this._lastBars     = null;
    this._lastOverlays = {};
    this._indPanelOpen = false;

    // Indicator toggle state
    this._ind = this._loadIndicators();

    // Main chart LWC handles
    this.chart        = null;
    this.candleSeries = null;
    this.volumeSeries = null;
    // Moving averages
    this.sma20Series  = null; this.sma50Series  = null; this.sma200Series = null;
    this.ema20Series  = null; this.ema50Series  = null; this.ema200Series = null;
    this.vwapSeries   = null;
    // Bands & channels
    this.bbUpperSeries    = null; this.bbMidSeries     = null; this.bbLowerSeries    = null;
    this.donchUpperSeries = null; this.donchLowerSeries = null;
    this.keltUpperSeries  = null; this.keltLowerSeries  = null;
    // Trend
    this.psarBullSeries = null; this.psarBearSeries = null;
    this.stBullSeries   = null; this.stBearSeries   = null;
    this.ichiTenSeries  = null; this.ichiKijSeries  = null;
    this.ichiSenASeries = null; this.ichiSenBSeries = null;

    // Sub-chart LWC handles (RSI / MACD / Stochastic)
    this.rsiChart         = null; this.rsiSeries        = null;
    this.macdChart        = null; this.macdFastSeries   = null;
    this.macdSignalSeries = null; this.macdHistSeries   = null;
    this.stochChart       = null; this.stochKSeries     = null; this.stochDSeries = null;
    this._stochBodyEl     = null;

    this._priceLines = [];
    this._posLines   = [];
    this._pivotLines = [];
    this._fvgLines   = [];
    this._signalTips = {};
    this._shadeEls   = [];

    this._buildDOM(gridEl);
    this._initChart();
    this._initSubCharts();
    this._applyIndicatorButtons();
    this.fetch(false);
    this._startAutoRefresh();
  }

  // ── localStorage helpers ───────────────────────────────────────────────────
  _tfFromIv(iv) {
    return { "1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","1d":"1D" }[iv] || "15m";
  }

  _loadIndicators() {
    // Always start with a clean chart — no indicators restored from localStorage.
    // Indicators stay on only for the current page session; each fresh load is clean.
    return {
      sma20: false, sma50: false, sma200: false,
      ema20: false, ema50: false, ema200: false, vwap: false,
      bb: false, donchian: false, keltner: false,
      psar: false, supertrend: false, ichimoku: false,
      pivots: false, fvg: false, vpoc: false,
      rsi: false, macd: false, stoch: false,
    };
  }

  _saveIndicators() {
    localStorage.setItem(`chart_pane_${this.id}_ind`, JSON.stringify(this._ind));
  }

  // ── DOM construction ───────────────────────────────────────────────────────
  _buildDOM(gridEl) {
    const pid = this.id;

    const pane = document.createElement("div");
    pane.className = "chart-pane";
    pane.id        = `pane-${pid}`;

    // ── Header ──────────────────────────────────────────────────────────────
    const hdr = document.createElement("div");
    hdr.className = "pane-header";
    hdr.innerHTML = `
      <span class="pane-source">Alpaca</span>
      <select class="pane-sym-select" id="pane-sym-${pid}">
        ${SYMBOLS.map(s => `<option value="${s}"${s===this.sym?" selected":""}>${s}</option>`).join("")}
      </select>
      <select class="pane-tf-select" id="pane-tf-${pid}">
        ${Object.keys(TIMEFRAMES).map(tf =>
          `<option value="${tf}"${tf===this.tf?" selected":""}>${tf}</option>`
        ).join("")}
      </select>
      <button class="pane-ind-btn" id="pane-ind-btn-${pid}">INDICATORS</button>
      <div class="pane-price-badge">
        <span class="pane-badge-sym">${this.sym}</span>
        <span class="pane-badge-price" id="pane-badge-price-${pid}">—</span>
        <span class="pane-badge-chg"  id="pane-badge-chg-${pid}">—</span>
      </div>
    `;
    hdr.querySelector(".pane-sym-select").addEventListener("change", e => this.setSymbol(e.target.value));
    hdr.querySelector(".pane-tf-select").addEventListener("change", e => this.setTimeframe(e.target.value));
    hdr.querySelector(".pane-ind-btn").addEventListener("click", () => this.toggleIndicatorsPanel());

    // ── Indicators panel (slides in from left) ──────────────────────────────
    const IND_DEFS = [
      { section: "MOVING AVERAGES" },
      { key: "sma20",  color: "#fb923c", label: "SMA (20)" },
      { key: "sma50",  color: "#fbbf24", label: "SMA (50)" },
      { key: "sma200", color: "#ef4444", label: "SMA (200)" },
      { key: "ema20",  color: "#22d3ee", label: "EMA (20)" },
      { key: "ema50",  color: "#a78bfa", label: "EMA (50)" },
      { key: "ema200", color: "#f43f5e", label: "EMA (200)" },
      { key: "vwap",   color: "#f59e0b", label: "VWAP" },
      { section: "BANDS & CHANNELS" },
      { key: "bb",       color: "#60a5fa", label: "Bollinger (20, 2)" },
      { key: "donchian", color: "#34d399", label: "Donchian (20)" },
      { key: "keltner",  color: "#818cf8", label: "Keltner (20, 2)" },
      { section: "TREND" },
      { key: "psar",       color: "#e2e8f0", label: "Parabolic SAR" },
      { key: "supertrend", color: "#00e5a0", label: "SuperTrend (10, 3)" },
      { key: "ichimoku",   color: "#38bdf8", label: "Ichimoku Cloud" },
      { section: "SUPPORT & RESISTANCE" },
      { key: "pivots", color: "#94a3b8", label: "Pivot Points" },
      { key: "fvg",    color: "#fde68a", label: "Fair Value Gaps" },
      { key: "vpoc",   color: "#c084fc", label: "Volume Profile (POC)" },
      { section: "OSCILLATORS" },
      { key: "rsi",  color: "#a78bfa", label: "RSI (14)" },
      { key: "macd", color: "#22d3ee", label: "MACD (12, 26, 9)" },
      { key: "stoch",color: "#4ade80", label: "Stochastic (14, 3, 3)" },
    ];
    const indPanel = document.createElement("div");
    indPanel.className = "indicators-panel";
    indPanel.id        = `ind-panel-${pid}`;
    indPanel.innerHTML = IND_DEFS.map(d =>
      d.section
        ? `<div class="ind-section">${d.section}</div>`
        : `<div class="ind-row" data-ind="${d.key}">
             <input type="checkbox" data-ind="${d.key}"${this._ind[d.key]?" checked":""}>
             <span class="ind-dot" style="background:${d.color}"></span>
             <span class="ind-label">${d.label}</span>
           </div>`
    ).join("");
    // Wire checkbox events.
    // Rule: only ONE handler fires per user action to avoid double-toggle.
    //   • Click on label / row area  → row click handler: manually flips cb, calls toggleIndicator
    //   • Click directly on checkbox → browser toggles cb, fires "change" → change handler calls toggleIndicator
    //                                   row click also fires (bubble), but we early-return if target is INPUT
    indPanel.querySelectorAll(".ind-row").forEach(row => {
      row.addEventListener("click", e => {
        if (e.target.tagName === "INPUT") return; // checkbox click handled by "change" below
        const key = row.dataset.ind;
        const cb = row.querySelector("input");
        cb.checked = !cb.checked;   // visual sync (doesn't fire "change")
        this.toggleIndicator(key);
      });
    });
    indPanel.querySelectorAll("input[type=checkbox]").forEach(cb =>
      cb.addEventListener("change", () => this.toggleIndicator(cb.dataset.ind))
    );

    // ── Content area ────────────────────────────────────────────────────────
    const content   = document.createElement("div");
    content.className = "pane-content";

    const chartArea = document.createElement("div");
    chartArea.className = "pane-chart-area";

    const mainBody  = document.createElement("div");
    mainBody.className = "pane-main-body";
    mainBody.id        = `pane-main-${pid}`;

    const rsiBody   = document.createElement("div");
    rsiBody.className = "pane-sub-body";
    rsiBody.id        = `pane-rsi-${pid}`;
    rsiBody.style.display = this._ind.rsi ? "" : "none";

    const macdBody  = document.createElement("div");
    macdBody.className = "pane-sub-body";
    macdBody.id        = `pane-macd-${pid}`;
    macdBody.style.display = this._ind.macd ? "" : "none";

    const stochBody = document.createElement("div");
    stochBody.className = "pane-sub-body";
    stochBody.id        = `pane-stoch-${pid}`;
    stochBody.style.display = this._ind.stoch ? "" : "none";

    chartArea.appendChild(mainBody);
    chartArea.appendChild(rsiBody);
    chartArea.appendChild(macdBody);
    chartArea.appendChild(stochBody);

    content.appendChild(indPanel);
    content.appendChild(chartArea);

    pane.appendChild(hdr);
    pane.appendChild(content);
    gridEl.appendChild(pane);

    this.paneEl       = pane;
    this._bodyEl      = mainBody;
    this._rsiBodyEl   = rsiBody;
    this._macdBodyEl  = macdBody;
    this._stochBodyEl = stochBody;
  }

  // ── Chart initialization ───────────────────────────────────────────────────
  _initChart() {
    const container = this._bodyEl;
    if (!container || typeof LightweightCharts === "undefined") return;

    const baseOpts = {
      width:  container.clientWidth  || 300,
      height: container.clientHeight || 200,
      layout: { background: { type: "solid", color: "#04070e" }, textColor: "#7a96b8", fontSize: 10, fontFamily: "JetBrains Mono, monospace" },
      grid:   { vertLines: { color: "rgba(21,32,53,0.6)" }, horzLines: { color: "rgba(21,32,53,0.6)" } },
      rightPriceScale: { borderColor: "#152035", textColor: "#4a6280", scaleMargins: { top: 0.05, bottom: 0.14 } },
      timeScale: { borderColor: "#152035", textColor: "#4a6280", timeVisible: true, secondsVisible: false, rightOffset: 5, barSpacing: 8, minBarSpacing: 3, fixLeftEdge: false, fixRightEdge: false },
      crosshair: { mode: 1, vertLine: { color: "#22d3ee", width: 1, style: 3, labelBackgroundColor: "#0f3040" }, horzLine: { color: "#22d3ee", width: 1, style: 3, labelBackgroundColor: "#0f3040" } },
      handleScroll: true, handleScale: true,
    };

    this.chart = LightweightCharts.createChart(container, baseOpts);

    this.candleSeries = this.chart.addCandlestickSeries({
      upColor: "#00e5a0", downColor: "#ff3d68", borderUpColor: "#00e5a0", borderDownColor: "#ff3d68",
      wickUpColor: "#00e5a055", wickDownColor: "#ff3d6855", priceLineVisible: false,
    });
    const L = (color, w=1, style=0, title="", last=false) =>
      this.chart.addLineSeries({ color, lineWidth: w, lineStyle: style, priceLineVisible: false, lastValueVisible: last, title });

    // Moving averages
    this.sma20Series  = L("#fb923c", 1, 0, "SMA20");
    this.sma50Series  = L("#fbbf24", 1, 0, "SMA50");
    this.sma200Series = L("#ef4444", 1, 2, "SMA200");
    this.ema20Series  = L("#22d3ee", 1, 0, "EMA20");
    this.ema50Series  = L("#a78bfa", 1, 0, "EMA50");
    this.ema200Series = L("#f43f5e", 1, 2, "EMA200");
    this.vwapSeries   = this.chart.addLineSeries({ color: "#f59e0b", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "VWAP" });

    // Bands & channels
    this.bbUpperSeries    = L("#60a5fa55", 1, 0); this.bbMidSeries    = L("#60a5fa88", 1, 0); this.bbLowerSeries    = L("#60a5fa55", 1, 0);
    this.donchUpperSeries = L("#34d39955", 1, 0); this.donchLowerSeries = L("#34d39955", 1, 0);
    this.keltUpperSeries  = L("#818cf855", 1, 0); this.keltLowerSeries  = L("#818cf855", 1, 0);

    // Trend
    this.psarBullSeries = L("#e2e8f0", 1, 3, "PSAR↑");
    this.psarBearSeries = L("#94a3b8", 1, 3, "PSAR↓");
    this.stBullSeries   = L("#00e5a0", 2, 0, "ST↑");
    this.stBearSeries   = L("#ff3d68", 2, 0, "ST↓");
    this.ichiTenSeries  = L("#22d3ee", 1, 0, "Tenkan");
    this.ichiKijSeries  = L("#f43f5e", 1, 0, "Kijun");
    this.ichiSenASeries = L("#00e5a066", 1, 0, "SenkouA");
    this.ichiSenBSeries = L("#ff3d6866", 1, 0, "SenkouB");

    this.volumeSeries = this.chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", color: "#3b82f660" });
    this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.88, bottom: 0 }, borderVisible: false });

    new ResizeObserver(() => {
      if (this.chart && container.clientWidth && container.clientHeight)
        this.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    }).observe(container);
  }

  _initSubCharts() {
    if (typeof LightweightCharts === "undefined") return;

    const subBase = {
      layout: { background: { type: "solid", color: "#04070e" }, textColor: "#7a96b8", fontSize: 9, fontFamily: "JetBrains Mono, monospace" },
      grid:   { vertLines: { color: "rgba(21,32,53,0.25)" }, horzLines: { color: "rgba(21,32,53,0.35)" } },
      rightPriceScale: { borderColor: "#152035", textColor: "#4a6280", scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { visible: false },
      handleScroll: false, handleScale: false,
      crosshair: { mode: 1 },
    };

    // RSI sub-chart
    if (this._rsiBodyEl) {
      this.rsiChart = LightweightCharts.createChart(this._rsiBodyEl, {
        ...subBase, width: this._rsiBodyEl.clientWidth || 300, height: this._rsiBodyEl.clientHeight || 80,
      });
      this.rsiSeries = this.rsiChart.addLineSeries({ color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
      // OB / OS reference lines
      this.rsiSeries.createPriceLine({ price: 70, color: "#ff3d6855", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OB" });
      this.rsiSeries.createPriceLine({ price: 30, color: "#00e5a055", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OS" });
      new ResizeObserver(() => {
        if (this.rsiChart && this._rsiBodyEl.clientWidth)
          this.rsiChart.applyOptions({ width: this._rsiBodyEl.clientWidth, height: this._rsiBodyEl.clientHeight });
      }).observe(this._rsiBodyEl);
    }

    // MACD sub-chart (shows time axis since it's the bottom-most)
    if (this._macdBodyEl) {
      this.macdChart = LightweightCharts.createChart(this._macdBodyEl, {
        ...subBase,
        width: this._macdBodyEl.clientWidth || 300, height: this._macdBodyEl.clientHeight || 80,
        timeScale: { visible: true, borderColor: "#152035", textColor: "#4a6280" },
      });
      this.macdHistSeries   = this.macdChart.addHistogramSeries({ priceLineVisible: false });
      this.macdFastSeries   = this.macdChart.addLineSeries({ color: "#22d3ee", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "MACD"   });
      this.macdSignalSeries = this.macdChart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "Signal" });
      new ResizeObserver(() => {
        if (this.macdChart && this._macdBodyEl.clientWidth)
          this.macdChart.applyOptions({ width: this._macdBodyEl.clientWidth, height: this._macdBodyEl.clientHeight });
      }).observe(this._macdBodyEl);
    }

    // Stochastic sub-chart
    if (this._stochBodyEl) {
      this.stochChart = LightweightCharts.createChart(this._stochBodyEl, {
        ...subBase, width: this._stochBodyEl.clientWidth || 300, height: this._stochBodyEl.clientHeight || 80,
        timeScale: { visible: false },
      });
      this.stochKSeries = this.stochChart.addLineSeries({ color: "#4ade80", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "%K" });
      this.stochDSeries = this.stochChart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "%D" });
      this.stochKSeries.createPriceLine({ price: 80, color: "#ff3d6855", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OB" });
      this.stochKSeries.createPriceLine({ price: 20, color: "#00e5a055", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OS" });
      new ResizeObserver(() => {
        if (this.stochChart && this._stochBodyEl.clientWidth)
          this.stochChart.applyOptions({ width: this._stochBodyEl.clientWidth, height: this._stochBodyEl.clientHeight });
      }).observe(this._stochBodyEl);
    }
  }

  // ── Indicator panel controls ───────────────────────────────────────────────
  toggleIndicatorsPanel() {
    this._indPanelOpen = !this._indPanelOpen;
    const panel = document.getElementById(`ind-panel-${this.id}`);
    if (panel) panel.classList.toggle("open", this._indPanelOpen);
    const btn = document.getElementById(`pane-ind-btn-${this.id}`);
    if (btn) btn.classList.toggle("panel-open", this._indPanelOpen);
  }

  toggleIndicator(key) {
    this._ind[key] = !this._ind[key];
    this._saveIndicators();
    this._applyIndicatorButtons();
    // Show/hide sub-chart containers
    if (this._rsiBodyEl)   this._rsiBodyEl.style.display   = this._ind.rsi   ? "" : "none";
    if (this._macdBodyEl)  this._macdBodyEl.style.display  = this._ind.macd  ? "" : "none";
    if (this._stochBodyEl) this._stochBodyEl.style.display = this._ind.stoch ? "" : "none";
    // Re-render with cached bars
    if (this._lastBars) this._renderData(this._lastBars, this._lastOverlays);
    // Sub-charts were just revealed from display:none — their LightweightCharts
    // instance was sized at 0×0. Force a resize on the next frame after the
    // browser has laid out the flex container so clientWidth/Height are correct.
    requestAnimationFrame(() => {
      if (this._ind.rsi   && this.rsiChart   && this._rsiBodyEl?.clientWidth)
        this.rsiChart.applyOptions({ width: this._rsiBodyEl.clientWidth, height: this._rsiBodyEl.clientHeight || 80 });
      if (this._ind.macd  && this.macdChart  && this._macdBodyEl?.clientWidth)
        this.macdChart.applyOptions({ width: this._macdBodyEl.clientWidth, height: this._macdBodyEl.clientHeight || 80 });
      if (this._ind.stoch && this.stochChart && this._stochBodyEl?.clientWidth)
        this.stochChart.applyOptions({ width: this._stochBodyEl.clientWidth, height: this._stochBodyEl.clientHeight || 80 });
    });
  }

  _applyIndicatorButtons() {
    const anyOn = Object.values(this._ind).some(Boolean);
    const btn = document.getElementById(`pane-ind-btn-${this.id}`);
    if (btn) btn.classList.toggle("active", anyOn);
  }

  // ── Data fetch ─────────────────────────────────────────────────────────────
  fetch(force = false) {
    this._seq++;
    socket.emit("get_chart_data", {
      interval:      this.interval,
      range:         this.range,
      symbol:        this.sym,
      force_refresh: !!force,
      _seq:          this._seq,
      pane_id:       this.id,
    });
  }

  // ── Symbol / timeframe setters ─────────────────────────────────────────────
  setSymbol(sym) {
    this.sym = sym;
    localStorage.setItem(`chart_pane_${this.id}_sym`, sym);
    // Update badge label
    const badgeSym = this.paneEl.querySelector(".pane-badge-sym");
    if (badgeSym) badgeSym.textContent = sym;
    if (this.id === 0) {
      currentSymbol = sym;
      setEl("ticker-symbol", sym);
      socket.emit("set_active_symbol", { symbol: sym });
    }
    this._lastClose = null; this._prevClose = null; this._lastBars = null;
    this.fetch(true);
  }

  setTimeframe(tf) {
    this.tf = tf;
    localStorage.setItem(`chart_pane_${this.id}_tf`, tf);
    const map = TIMEFRAMES[tf] || TIMEFRAMES["15m"];
    this.interval = map.interval;
    this.range    = map.range;
    this._lastBars = null;
    this.fetch(true);
    if (LIVE_RANGES.has(this.range)) this._startAutoRefresh(); else this._stopAutoRefresh();
  }

  // ── Auto-refresh ───────────────────────────────────────────────────────────
  _startAutoRefresh() {
    this._stopAutoRefresh();
    this._refreshTimer = setInterval(() => {
      if (LIVE_RANGES.has(this.range)) this.fetch(false);
    }, CHART_AUTO_REFRESH);
  }
  _stopAutoRefresh() {
    if (this._refreshTimer) { clearInterval(this._refreshTimer); this._refreshTimer = null; }
  }

  // ── Price line helpers ─────────────────────────────────────────────────────
  _clearPriceLines() {
    if (!this.candleSeries) return;
    this._priceLines.forEach(pl => { try { this.candleSeries.removePriceLine(pl); } catch (_) {} });
    this._priceLines = [];
  }
  _clearPosLines() {
    if (!this.candleSeries) return;
    this._posLines.forEach(pl => { try { this.candleSeries.removePriceLine(pl); } catch (_) {} });
    this._posLines = [];
  }
  _clearPivotLines() {
    if (!this.candleSeries) return;
    this._pivotLines.forEach(pl => { try { this.candleSeries.removePriceLine(pl); } catch (_) {} });
    this._pivotLines = [];
  }
  _clearFVGLines() {
    if (!this.candleSeries) return;
    this._fvgLines.forEach(pl => { try { this.candleSeries.removePriceLine(pl); } catch (_) {} });
    this._fvgLines = [];
  }
  _clearShades() {
    this._shadeEls.forEach(el => el.remove());
    this._shadeEls = [];
  }

  _flash(dir) {
    if (!this.paneEl) return;
    this.paneEl.classList.remove("flash-green", "flash-red");
    void this.paneEl.offsetWidth;
    if (dir === "green") this.paneEl.classList.add("flash-green");
    else if (dir === "red")  this.paneEl.classList.add("flash-red");
  }

  // ── Price badge ────────────────────────────────────────────────────────────
  _updateBadge(price, prevClose) {
    const priceEl = document.getElementById(`pane-badge-price-${this.id}`);
    const chgEl   = document.getElementById(`pane-badge-chg-${this.id}`);
    if (!priceEl || price == null) return;
    priceEl.textContent = price.toFixed(2);
    if (chgEl && prevClose && prevClose > 0) {
      const chg = price - prevClose;
      const pct = (chg / prevClose) * 100;
      const up  = chg >= 0;
      chgEl.textContent  = `${up?"+":""}${chg.toFixed(2)} (${up?"+":""}${pct.toFixed(2)}%)`;
      chgEl.className    = `pane-badge-chg${up ? "" : " down"}`;
    }
  }

  // ── Core render ────────────────────────────────────────────────────────────
  _renderData(bars, ov) {
    if (!this.candleSeries) return;
    const n  = bars.length;
    const clean = arr => (arr || []).filter(p => p && p.value != null);
    const SET  = (s, d) => { if (s) s.setData(d); };
    const OFF  = (...ss) => ss.forEach(s => { if (s) s.setData([]); });

    this.candleSeries.setData(bars);
    if (this.volumeSeries)
      this.volumeSeries.setData(bars.map(b => ({
        time: b.time, value: b.volume,
        color: (b.close >= b.open) ? "#00e5a055" : "#ff3d6855",
      })));

    // ── Moving averages ───────────────────────────────────────────────────────
    const closes = bars.map(b => b.close);
    const mkLine = (values, period) => {
      const out = [];
      for (let i = period-1; i < values.length; i++)
        out.push({ time: bars[i].time, value: values[i] });
      return out;
    };

    // SMA helper
    const sma = (period) => {
      const out = [];
      let sum = 0;
      for (let i = 0; i < n; i++) {
        sum += closes[i];
        if (i >= period) sum -= closes[i - period];
        if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
      }
      return out;
    };

    // For 50/200 MAs, prefer the server's warmup-computed series (ov.sma50/…) when
    // present — they form even on short ranges (e.g. 15m/1D) where the visible
    // bars alone are too few. Fall back to client compute when the window is long
    // enough, then to the flat daily-EMA200 level.
    const hasSrv = k => Array.isArray(ov[k]) && ov[k].length > 0;
    const flat200 = ov.ema200d != null ? bars.map(b => ({ time: b.time, value: ov.ema200d })) : [];

    SET(this.sma20Series, this._ind.sma20 ? sma(20) : []);
    SET(this.sma50Series, this._ind.sma50
      ? (hasSrv("sma50") ? ov.sma50 : sma(50)) : []);
    if (this._ind.sma200) {
      SET(this.sma200Series, hasSrv("sma200") ? ov.sma200
        : n >= 200 ? sma(200) : flat200);
    } else SET(this.sma200Series, []);

    const ema20v  = ChartPane._ema(closes, 20);
    const ema50v  = ChartPane._ema(closes, 50);
    SET(this.ema20Series, this._ind.ema20 ? mkLine(ema20v, 20) : []);
    SET(this.ema50Series, this._ind.ema50
      ? (hasSrv("ema50") ? ov.ema50 : mkLine(ema50v, 50)) : []);
    if (this._ind.ema200) {
      SET(this.ema200Series, hasSrv("ema200") ? ov.ema200
        : n >= 200 ? mkLine(ChartPane._ema(closes, 200), 200) : flat200);
    } else SET(this.ema200Series, []);

    SET(this.vwapSeries, this._ind.vwap ? clean(ov.vwap) : []);

    // ── Bands & channels ──────────────────────────────────────────────────────
    if (this._ind.bb && n >= 20) {
      const { upper, mid, lower } = ChartPane._computeBB(bars);
      SET(this.bbUpperSeries, upper); SET(this.bbMidSeries, mid); SET(this.bbLowerSeries, lower);
    } else OFF(this.bbUpperSeries, this.bbMidSeries, this.bbLowerSeries);

    if (this._ind.donchian && n >= 20) {
      const { upper, lower } = ChartPane._computeDonchian(bars);
      SET(this.donchUpperSeries, upper); SET(this.donchLowerSeries, lower);
    } else OFF(this.donchUpperSeries, this.donchLowerSeries);

    if (this._ind.keltner && n >= 20) {
      const { upper, lower } = ChartPane._computeKeltner(bars);
      SET(this.keltUpperSeries, upper); SET(this.keltLowerSeries, lower);
    } else OFF(this.keltUpperSeries, this.keltLowerSeries);

    // ── Trend ─────────────────────────────────────────────────────────────────
    if (this._ind.psar && n >= 3) {
      const { bull, bear } = ChartPane._computePSAR(bars);
      SET(this.psarBullSeries, bull); SET(this.psarBearSeries, bear);
    } else OFF(this.psarBullSeries, this.psarBearSeries);

    if (this._ind.supertrend && n >= 12) {
      const { bull, bear } = ChartPane._computeSuperTrend(bars);
      SET(this.stBullSeries, bull); SET(this.stBearSeries, bear);
    } else OFF(this.stBullSeries, this.stBearSeries);

    if (this._ind.ichimoku && n >= 52) {
      const { tenkan, kijun, senkouA, senkouB } = ChartPane._computeIchimoku(bars);
      SET(this.ichiTenSeries, tenkan); SET(this.ichiKijSeries, kijun);
      SET(this.ichiSenASeries, senkouA); SET(this.ichiSenBSeries, senkouB);
    } else OFF(this.ichiTenSeries, this.ichiKijSeries, this.ichiSenASeries, this.ichiSenBSeries);

    // ── Support & resistance ──────────────────────────────────────────────────
    this._clearPivotLines();
    if (this._ind.pivots && this.candleSeries) {
      // Prefer server prior_levels (needs Alpaca); fall back to client-side
      // _computePivots(bars) so pivots also work without login (guest charts).
      const pl_data = ov.prior_levels || {};
      let pp, r1, r2, r3, s1, s2, s3;
      if (pl_data.prev_high && pl_data.prev_low && pl_data.prev_close) {
        const pdH = pl_data.prev_high, pdL = pl_data.prev_low, pdC = pl_data.prev_close;
        pp = (pdH + pdL + pdC) / 3; const rng = pdH - pdL;
        r1 = 2*pp - pdL; r2 = pp + rng; r3 = pdH + 2*(pp-pdL);
        s1 = 2*pp - pdH; s2 = pp - rng; s3 = pdL - 2*(pdH-pp);
      } else {
        const cp = ChartPane._computePivots(bars, (this.interval || "1d"));
        if (cp) ({ pp, r1, r2, r3, s1, s2, s3 } = cp);
      }
      if (pp != null) {
        const addPL = (price, color, title) =>
          this._pivotLines.push(this.candleSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
        addPL(pp, "#94a3b8", "PP");
        addPL(r1, "#f43f5e99", "R1"); addPL(r2, "#f43f5e66", "R2"); addPL(r3, "#f43f5e44", "R3");
        addPL(s1, "#00e5a099", "S1"); addPL(s2, "#00e5a066", "S2"); addPL(s3, "#00e5a044", "S3");
      }
    }

    this._clearFVGLines();
    if (this._ind.fvg && n >= 3) {
      ChartPane._computeFVG(bars).forEach(g => {
        const col = g.bull ? "#00e5a077" : "#ff3d6877";
        this._fvgLines.push(this.candleSeries.createPriceLine({ price: g.top,    color: col, lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: "" }));
        this._fvgLines.push(this.candleSeries.createPriceLine({ price: g.bottom, color: col, lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: "" }));
      });
    }

    if (this._ind.vpoc && n >= 10) {
      const vp = ChartPane._computeVPOC(bars);
      if (vp && this.candleSeries) {
        this._pivotLines.push(this.candleSeries.createPriceLine({ price: vp.poc,    color: "#c084fc",   lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "POC" }));
        this._pivotLines.push(this.candleSeries.createPriceLine({ price: vp.vaHigh, color: "#c084fc66", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "VAH" }));
        this._pivotLines.push(this.candleSeries.createPriceLine({ price: vp.vaLow,  color: "#c084fc66", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "VAL" }));
      }
    }

    // ── Oscillator sub-charts ─────────────────────────────────────────────────
    if (this._ind.rsi && this.rsiSeries && n > 15) {
      this.rsiSeries.setData(ChartPane._computeRSI(bars));
      if (this.rsiChart) this.rsiChart.timeScale().fitContent();
    } else if (this.rsiSeries) this.rsiSeries.setData([]);

    if (this._ind.macd && this.macdFastSeries && n > 27) {
      const { macdData, signalData, histData } = ChartPane._computeMACD(bars);
      this.macdFastSeries.setData(macdData); this.macdSignalSeries.setData(signalData); this.macdHistSeries.setData(histData);
      if (this.macdChart) this.macdChart.timeScale().fitContent();
    } else if (this.macdFastSeries) OFF(this.macdFastSeries, this.macdSignalSeries, this.macdHistSeries);

    if (this._ind.stoch && this.stochKSeries && n >= 20) {
      const { kData, dData } = ChartPane._computeStochastic(bars);
      this.stochKSeries.setData(kData); this.stochDSeries.setData(dData);
      if (this.stochChart) this.stochChart.timeScale().fitContent();
    } else if (this.stochKSeries) OFF(this.stochKSeries, this.stochDSeries);

    if (n > 0) this.chart.timeScale().fitContent();
  }

  // ── Socket data handler ────────────────────────────────────────────────────
  onData(d) {
    if (!this.candleSeries || !d.bars) return;
    if (d._seq     && d._seq     < this._seq)        return;  // stale response
    if (d.symbol   && d.symbol   !== this.sym)       return;
    if (d.interval && d.interval !== this.interval)  return;
    if (d.range    && d.range    !== this.range)     return;

    const ov       = d.overlays || {};
    const newClose = d.bars.length ? d.bars[d.bars.length-1].close : null;

    // Price flash on tick
    if (newClose != null && this._lastClose != null) {
      if      (newClose > this._lastClose) this._flash("green");
      else if (newClose < this._lastClose) this._flash("red");
    }
    this._lastClose = newClose;

    // Price badge: use prev_close from server overlays for change %
    const pc = (ov.prior_levels || {}).prev_close;
    if (pc) this._prevClose = pc;
    this._updateBadge(newClose, this._prevClose);

    // Cache for re-render on indicator toggle
    this._lastBars    = d.bars;
    this._lastOverlays = ov;

    // Render candles + indicators
    this._renderData(d.bars, ov);

    // ORB / prior-level price lines
    this._clearPriceLines();
    this._clearPosLines();
    const orb    = ov.orb          || {};
    const pl     = ov.prior_levels || {};
    const within = (lvl, pct=0.05) => newClose && lvl ? Math.abs((lvl-newClose)/newClose) <= pct : false;

    if (orb.high)          this._priceLines.push(this.candleSeries.createPriceLine({ price: orb.high,  color: "#22d3ee", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "ORB H" }));
    if (orb.low)           this._priceLines.push(this.candleSeries.createPriceLine({ price: orb.low,   color: "#22d3ee", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "ORB L" }));
    if (within(pl.prev_high))  this._priceLines.push(this.candleSeries.createPriceLine({ price: pl.prev_high,  color: "#7a96b8", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "PDH" }));
    if (within(pl.prev_low))   this._priceLines.push(this.candleSeries.createPriceLine({ price: pl.prev_low,   color: "#7a96b8", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "PDL" }));
    if (within(pl.prev_close)) this._priceLines.push(this.candleSeries.createPriceLine({ price: pl.prev_close, color: "#4a6280", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "PDC" }));

    // Position lines
    (d.position_overlay || []).forEach(p => {
      if (!newClose || Math.abs((p.entry_price-newClose)/newClose) > 0.10) return;
      const dry = p.is_dry_run ? " [DRY]" : "";
      this._posLines.push(this.candleSeries.createPriceLine({ price: p.entry_price, color: "#fbbf24", lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: `Entry ${p.remaining}x${dry}` }));
      this._posLines.push(this.candleSeries.createPriceLine({ price: p.stop_price,  color: "#ff3d68", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: `Stop${p.partial_done?" (trail)":""}` }));
      if (!p.partial_done) this._posLines.push(this.candleSeries.createPriceLine({ price: p.target_50, color: "#fbbf24", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "T1" }));
      this._posLines.push(this.candleSeries.createPriceLine({ price: p.target_75, color: "#00e5a0", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "T2" }));
    });

    // Signal markers
    this._signalTips = {};
    const sigMarks = (d.signals || []).map(s => {
      if (s.tip) this._signalTips[s.time] = { tip: s.tip };
      const side = s.direction === "bull" ? "▲ CALL" : "▼ PUT";
      return { time: s.time, position: s.direction==="bull"?"belowBar":"aboveBar", color: s.direction==="bull"?"#00e5a0":"#ff3d68", shape: s.direction==="bull"?"arrowUp":"arrowDown", text: s.badge?`${side} ${s.badge}`:side };
    });
    const closeMarks = (d.closes || []).map(c => ({
      time: c.time, position: "inBar", color: (c.pnl_pct||0)>=0?"#00e5a0":"#ff3d68", shape: "circle",
      text: `${(c.pnl_pct||0).toFixed(0)}% ${c.reason||""}`.slice(0,40),
    }));
    this.candleSeries.setMarkers([...sigMarks,...closeMarks].sort((a,b)=>a.time-b.time));

    // Blocked-window shading
    this._clearShades();
    if (d.blocked_windows && d.blocked_windows.length && this.chart) {
      const ts = this.chart.timeScale();
      d.blocked_windows.forEach(w => {
        const x1 = ts.timeToCoordinate(w.start);
        const x2 = ts.timeToCoordinate(w.end);
        if (x1 == null || x2 == null) return;
        const div = document.createElement("div");
        div.style.cssText = `position:absolute;left:${Math.min(x1,x2)}px;top:0;width:${Math.abs(x2-x1)}px;bottom:20px;background:rgba(122,150,184,0.06);border-left:1px dashed rgba(122,150,184,0.25);border-right:1px dashed rgba(122,150,184,0.25);pointer-events:none;z-index:1`;
        div.title = w.label;
        this._bodyEl.appendChild(div);
        this._shadeEls.push(div);
      });
    }
  }

  addSignalMarker(s) {
    if (!this.candleSeries || !s) return;
    if (s.symbol && s.symbol !== this.sym) return;
    if (s.tip) this._signalTips[s.time] = { tip: s.tip };
    const side = s.direction === "bull" ? "CALL" : "PUT";
    const ex   = this.candleSeries.markers ? this.candleSeries.markers() : [];
    this.candleSeries.setMarkers([...ex, { time: s.time, position: s.direction==="bull"?"belowBar":"aboveBar", color: s.direction==="bull"?"#00d88a":"#ff4560", shape: s.direction==="bull"?"arrowUp":"arrowDown", text: s.badge?`${side} ${s.badge}`:side }]);
  }

  destroy() {
    this._stopAutoRefresh();
    this._clearShades();
    this._clearPivotLines();
    this._clearFVGLines();
    if (this.rsiChart)   { try { this.rsiChart.remove();   } catch (_) {} this.rsiChart   = null; }
    if (this.macdChart)  { try { this.macdChart.remove();  } catch (_) {} this.macdChart  = null; }
    if (this.stochChart) { try { this.stochChart.remove(); } catch (_) {} this.stochChart = null; }
    if (this.chart)      { try { this.chart.remove();      } catch (_) {} this.chart      = null; }
    if (this.paneEl)     { this.paneEl.remove(); this.paneEl = null; }
  }

  // ── Client-side indicator computation ──────────────────────────────────────

  // ATR (Wilder's smoothing)
  static _atr(bars, period=14) {
    const tr = bars.map((b,i) => !i ? b.high-b.low :
      Math.max(b.high-b.low, Math.abs(b.high-bars[i-1].close), Math.abs(b.low-bars[i-1].close)));
    const atr = new Array(bars.length).fill(0);
    atr[period-1] = tr.slice(0,period).reduce((a,b)=>a+b,0)/period;
    for (let i=period; i<bars.length; i++) atr[i]=(atr[i-1]*(period-1)+tr[i])/period;
    return atr;
  }

  // Donchian Channel
  static _computeDonchian(bars, period=20) {
    const upper=[], lower=[];
    for (let i=period-1; i<bars.length; i++) {
      const sl = bars.slice(i-period+1, i+1);
      upper.push({ time: bars[i].time, value: Math.max(...sl.map(b=>b.high)) });
      lower.push({ time: bars[i].time, value: Math.min(...sl.map(b=>b.low)) });
    }
    return { upper, lower };
  }

  // Keltner Channel (EMA20 ± 2×ATR10)
  static _computeKeltner(bars, period=20, mult=2) {
    const closes = bars.map(b=>b.close);
    const emaV   = ChartPane._ema(closes, period);
    const atrV   = ChartPane._atr(bars, 10);
    const upper=[], lower=[];
    for (let i=period-1; i<bars.length; i++) {
      if (emaV[i]==null || !atrV[i]) continue;
      upper.push({ time: bars[i].time, value: emaV[i]+mult*atrV[i] });
      lower.push({ time: bars[i].time, value: emaV[i]-mult*atrV[i] });
    }
    return { upper, lower };
  }

  // Parabolic SAR
  static _computePSAR(bars, iAF=0.02, step=0.02, maxAF=0.2) {
    const n=bars.length; if (n<3) return { bull:[], bear:[] };
    const bull=[], bear=[];
    let rising = bars[1].close > bars[0].close;
    let af=iAF, ep=rising?bars[0].high:bars[0].low, sar=rising?bars[0].low:bars[0].high;
    for (let i=1; i<n; i++) {
      sar = sar + af*(ep-sar);
      if (rising) {
        sar = Math.min(sar, bars[i-1].low, i>1?bars[i-2].low:bars[i-1].low);
        if (bars[i].low < sar) {
          rising=false; sar=ep; ep=bars[i].low; af=iAF;
          bear.push({ time:bars[i].time, value:sar });
        } else {
          if (bars[i].high>ep){ ep=bars[i].high; af=Math.min(af+step,maxAF); }
          bull.push({ time:bars[i].time, value:sar });
        }
      } else {
        sar = Math.max(sar, bars[i-1].high, i>1?bars[i-2].high:bars[i-1].high);
        if (bars[i].high > sar) {
          rising=true; sar=ep; ep=bars[i].high; af=iAF;
          bull.push({ time:bars[i].time, value:sar });
        } else {
          if (bars[i].low<ep){ ep=bars[i].low; af=Math.min(af+step,maxAF); }
          bear.push({ time:bars[i].time, value:sar });
        }
      }
    }
    return { bull, bear };
  }

  // SuperTrend (period=10, multiplier=3)
  static _computeSuperTrend(bars, period=10, mult=3) {
    const n=bars.length; if (n<period) return { bull:[], bear:[] };
    const atrV = ChartPane._atr(bars, period);
    const bull=[], bear=[];
    let stDown=0, stUp=Infinity, trend=1;
    for (let i=period; i<n; i++) {
      const hl2=(bars[i].high+bars[i].low)/2;
      const dn = hl2-mult*atrV[i];
      const up = hl2+mult*atrV[i];
      stDown = (dn>stDown || bars[i-1].close<stDown) ? dn : stDown;
      stUp   = (up<stUp   || bars[i-1].close>stUp)   ? up : stUp;
      if (bars[i].close>stUp)  trend=1;
      else if (bars[i].close<stDown) trend=-1;
      if (trend===1) bull.push({ time:bars[i].time, value:stDown });
      else           bear.push({ time:bars[i].time, value:stUp });
    }
    return { bull, bear };
  }

  // Ichimoku Cloud
  static _computeIchimoku(bars) {
    const n=bars.length;
    const midN=(b,start,len)=>{ let hi=-Infinity,lo=Infinity; for(let i=start;i<start+len&&i<n;i++){hi=Math.max(hi,b[i].high);lo=Math.min(lo,b[i].low);} return(hi+lo)/2; };
    const tenkan=[], kijun=[], senkouA=[], senkouB=[];
    for (let i=8;  i<n; i++) tenkan.push({ time:bars[i].time, value:midN(bars,i-8,9) });
    for (let i=25; i<n; i++) {
      const k=midN(bars,i-25,26); kijun.push({ time:bars[i].time, value:k });
      const ti=i-8; // tenkan[] index 0 = bar 8, so tenkan at bar i is tenkan[i-8]
      const tVal=ti>=0&&ti<tenkan.length?tenkan[ti].value:null;
      if (tVal!=null) senkouA.push({ time:bars[i].time, value:(tVal+k)/2 });
    }
    for (let i=51; i<n; i++) senkouB.push({ time:bars[i].time, value:midN(bars,i-51,52) });
    return { tenkan, kijun, senkouA, senkouB };
  }

  // Pivot Points (classic, from previous day or previous bar)
  static _computePivots(bars, interval) {
    const n=bars.length; if (n<2) return null;
    let pdH, pdL, pdC;
    if (interval==='1d') {
      pdH=bars[n-2].high; pdL=bars[n-2].low; pdC=bars[n-2].close;
    } else {
      // Intraday: group by day
      const dayMap={};
      bars.forEach(b=>{
        const d=typeof b.time==='number'?new Date(b.time*1000).toISOString().slice(0,10):String(b.time).slice(0,10);
        if(!dayMap[d])dayMap[d]=[];dayMap[d].push(b);
      });
      const days=Object.keys(dayMap).sort();
      if (days.length<2) return null;
      const prev=dayMap[days[days.length-2]];
      pdH=Math.max(...prev.map(b=>b.high)); pdL=Math.min(...prev.map(b=>b.low)); pdC=prev[prev.length-1].close;
    }
    const pp=(pdH+pdL+pdC)/3, rng=pdH-pdL;
    return { pp, r1:2*pp-pdL, r2:pp+rng, r3:pdH+2*(pp-pdL), s1:2*pp-pdH, s2:pp-rng, s3:pdL-2*(pdH-pp) };
  }

  // Fair Value Gaps (last 6, unfilled)
  static _computeFVG(bars) {
    const gaps=[];
    for (let i=2; i<bars.length; i++) {
      if (bars[i].low > bars[i-2].high) // bullish gap
        gaps.push({ bull:true,  top:bars[i].low,    bottom:bars[i-2].high, time:bars[i].time });
      else if (bars[i].high < bars[i-2].low) // bearish gap
        gaps.push({ bull:false, top:bars[i-2].low,  bottom:bars[i].high,   time:bars[i].time });
    }
    return gaps.slice(-6);
  }

  // Volume Profile — POC + Value Area
  static _computeVPOC(bars, bins=50) {
    if (!bars.length) return null;
    const lo=Math.min(...bars.map(b=>b.low)), hi=Math.max(...bars.map(b=>b.high));
    if (hi===lo) return null;
    const bsz=(hi-lo)/bins, vol=new Array(bins).fill(0);
    bars.forEach(b=>{ const idx=Math.min(Math.floor((b.close-lo)/bsz),bins-1); vol[idx]+=(b.volume||1); });
    const maxI=vol.indexOf(Math.max(...vol)), poc=lo+(maxI+0.5)*bsz;
    const total=vol.reduce((a,b)=>a+b,0);
    let acc=vol[maxI], up=maxI, dn=maxI;
    while(acc<total*0.70&&(up<bins-1||dn>0)){
      const vU=up<bins-1?vol[up+1]:0, vD=dn>0?vol[dn-1]:0;
      vU>=vD ? acc+=vol[++up] : acc+=vol[--dn];
    }
    return { poc, vaHigh:lo+(up+1)*bsz, vaLow:lo+dn*bsz };
  }

  // Stochastic (14, 3, 3) — slow
  static _computeStochastic(bars, kPeriod=14, smooth=3, dPeriod=3) {
    const n=bars.length; if (n<kPeriod) return { kData:[], dData:[] };
    const raw=[];
    for (let i=kPeriod-1; i<n; i++) {
      const sl=bars.slice(i-kPeriod+1,i+1);
      const hi=Math.max(...sl.map(b=>b.high)), lo=Math.min(...sl.map(b=>b.low));
      raw.push({ time:bars[i].time, value:hi===lo?50:((bars[i].close-lo)/(hi-lo))*100 });
    }
    const smK=[];
    for (let i=smooth-1; i<raw.length; i++) {
      smK.push({ time:raw[i].time, value:raw.slice(i-smooth+1,i+1).reduce((a,b)=>a+b.value,0)/smooth });
    }
    const dData=[];
    for (let i=dPeriod-1; i<smK.length; i++)
      dData.push({ time:smK[i].time, value:smK.slice(i-dPeriod+1,i+1).reduce((a,b)=>a+b.value,0)/dPeriod });
    return { kData:smK, dData };
  }

  static _ema(values, period) {
    const k = 2 / (period + 1);
    const result = new Array(values.length).fill(null);
    if (values.length < period) return result;
    result[period - 1] = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < values.length; i++)
      result[i] = values[i] * k + result[i-1] * (1 - k);
    return result;
  }

  static _computeRSI(bars, period = 14) {
    if (bars.length < period + 1) return [];
    const c = bars.map(b => b.close);
    let avgG = 0, avgL = 0;
    for (let i = 1; i <= period; i++) {
      const d = c[i] - c[i-1];
      if (d > 0) avgG += d; else avgL -= d;
    }
    avgG /= period; avgL /= period;
    const out = [];
    for (let i = period + 1; i <= bars.length; i++) {
      const d = c[i-1] - c[i-2];
      avgG = (avgG * (period-1) + Math.max(d, 0)) / period;
      avgL = (avgL * (period-1) + Math.max(-d,0)) / period;
      const rs = avgL === 0 ? 100 : avgG / avgL;
      out.push({ time: bars[i-1].time, value: 100 - 100/(1+rs) });
    }
    return out;
  }

  static _computeMACD(bars, fast=12, slow=26, signal=9) {
    const c    = bars.map(b => b.close);
    const emaF = ChartPane._ema(c, fast);
    const emaS = ChartPane._ema(c, slow);
    const line = [];
    for (let i = 0; i < bars.length; i++)
      if (emaF[i] != null && emaS[i] != null)
        line.push({ time: bars[i].time, value: emaF[i]-emaS[i] });
    const sigEMA = ChartPane._ema(line.map(m => m.value), signal);
    const macdData   = line.map(m => ({ time: m.time, value: m.value }));
    const signalData = line.map((m,j) => sigEMA[j] != null ? { time: m.time, value: sigEMA[j] } : null).filter(Boolean);
    const histData   = line.map((m,j) => sigEMA[j] != null ? {
      time: m.time, value: m.value - sigEMA[j],
      color: (m.value - sigEMA[j]) >= 0 ? "#00e5a055" : "#ff3d6855",
    } : null).filter(Boolean);
    return { macdData, signalData, histData };
  }

  static _computeBB(bars, period=20, mult=2) {
    const c = bars.map(b => b.close);
    const upper=[], mid=[], lower=[];
    for (let i = period-1; i < bars.length; i++) {
      const sl = c.slice(i-period+1, i+1);
      const mn = sl.reduce((a,b)=>a+b,0)/period;
      const sd = Math.sqrt(sl.reduce((a,b)=>a+(b-mn)**2,0)/period);
      upper.push({ time: bars[i].time, value: mn+mult*sd });
      mid.push(  { time: bars[i].time, value: mn });
      lower.push({ time: bars[i].time, value: mn-mult*sd });
    }
    return { upper, mid, lower };
  }
}

// ── Grid Manager ──────────────────────────────────────────────────────────────
const gridManager = {
  panes: [],
  count: 0,

  init() {
    const saved = parseInt(localStorage.getItem("chart_grid_count")) || 1;
    this.setGridCount(saved);
  },

  setGridCount(n) {
    // Destroy existing panes
    this.panes.forEach(p => p.destroy());
    this.panes = [];
    this.count = n;
    localStorage.setItem("chart_grid_count", n);

    const grid = document.getElementById("chart-grid");
    if (!grid) return;
    grid.className = `chart-grid grid-${n}`;

    const defaults = _DEFAULT_SYMS[n] || ["SPY"];
    for (let i = 0; i < n; i++) {
      if (!localStorage.getItem(`chart_pane_${i}_sym`)) {
        localStorage.setItem(`chart_pane_${i}_sym`, defaults[i] || "SPY");
      }
      this.panes.push(new ChartPane(i, grid));
    }

    // Sync grid dropdown
    const dd = document.getElementById("grid-dropdown");
    if (dd) dd.value = n;

    // Keep currentSymbol in sync with pane 0
    if (this.panes[0]) currentSymbol = this.panes[0].sym;
  },
};

function setGridCount(n) {
  gridManager.setGridCount(n);
  _setViewMode("chart");
}

// ── View mode ─────────────────────────────────────────────────────────────────
function _setViewMode(mode) {
  document.body.classList.remove("view-chart", "view-settings", "view-log", "view-screener", "view-positions");
  document.body.classList.add("view-" + mode);
  document.querySelectorAll("#tab-chart, #tab-settings, #tab-log, #tab-screener, #tab-positions, .bt-tab").forEach(t => t.classList.remove("active"));
  if (mode === "chart") {
    const tc = document.getElementById("tab-chart");
    if (tc) tc.classList.add("active");
    setTimeout(() => {
      gridManager.panes.forEach(p => { if (p.chart) p.chart.timeScale().fitContent(); });
    }, 50);
  }
}

function showCharts() {
  _setViewMode("chart");
  try { if (window.location.pathname !== "/charts") history.pushState({}, "", "/charts"); } catch (e) {}
  // Ensure pane 0 shows SPY if nothing has been set yet
  if (gridManager.panes[0] && !localStorage.getItem("chart_pane_0_sym")) {
    gridManager.panes[0].setSymbol("SPY");
  }
  const bp = document.getElementById("backtest-panel");
  const gw = document.getElementById("chart-grid-wrapper");
  if (bp) bp.style.display = "none";
  if (gw) gw.style.display = "";
}

function setActiveSymbol(symbol) {
  _setViewMode("chart");
  const bp = document.getElementById("backtest-panel");
  const gw = document.getElementById("chart-grid-wrapper");
  if (bp) bp.style.display = "none";
  if (gw) gw.style.display = "";
  currentSymbol = symbol;
  setEl("ticker-symbol", symbol);
  if (gridManager.panes[0]) gridManager.panes[0].setSymbol(symbol);
  socket.emit("set_active_symbol", { symbol });
}

function showSettings() {
  _setViewMode("settings");
  document.getElementById("tab-settings").classList.add("active");
}

function showLog() {
  _setViewMode("log");
  document.getElementById("tab-log").classList.add("active");
}

// ── Positions tab (#24) ───────────────────────────────────────────────────────
let _lastPositions = { open: [], auto: [], account: [], options: [] };
let _lastExitCfg = { stock_tp_pct: 6, stock_sl_pct: 3, stock_stall_days: 3,
                     opt_tp_pct: 80, opt_sl_pct: 50, opt_stall_min: 90, time_cap_days: 21 };

function showPositions() {
  _setViewMode("positions");
  const t = document.getElementById("tab-positions");
  if (t) t.classList.add("active");
  _renderPositionsTable();
  // NOTE: do NOT emit the auth-gated "refresh" here — if the socket isn't
  // authenticated it would disconnect the client and blank the whole UI. The
  // server pushes state (incl. account_positions) every few seconds anyway.
}

function refreshPositions() {
  socket.emit("refresh_positions");   // server invalidates cache + re-pushes state
  _renderPositionsTable();            // immediate re-render from current cache
}

function saveExitConfig() {
  const v = id => parseFloat(document.getElementById(id).value);
  socket.emit("set_exit_config", {
    stock_tp_pct: v("ex-stock-tp"), stock_sl_pct: v("ex-stock-sl"), stock_stall_days: v("ex-stock-stall"),
    opt_tp_pct:   v("ex-opt-tp"),   opt_sl_pct:   v("ex-opt-sl"),   opt_stall_min:   v("ex-opt-stall"),
    time_cap_days: v("ex-cap"),
  });
  _exitSaved();
}

function _exitChanged() {   // enable Save on any edit
  const b = document.getElementById("btn-save-exit");
  if (b) { b.disabled = false; b.textContent = "Save Exit Settings"; b.style.opacity = "1"; b.style.cursor = "pointer"; }
}
function _exitSaved() {      // back to disabled "✓ Saved"
  const b = document.getElementById("btn-save-exit");
  if (b) { b.disabled = true; b.textContent = "✓ Saved"; b.style.opacity = ".45"; b.style.cursor = "not-allowed"; }
}

// renderJournal removed 2026-06-04 — the Notes panel was retired; closed trades
// are surfaced in the Log (auto-engine "CLOSED" / "OPTION EXIT" lines).

function _posPnl(usd, pct) {
  if (usd == null) return "—";
  const cls = usd >= 0 ? "postab-pnl-up" : "postab-pnl-down";
  return `<span class="${cls}">${usd >= 0 ? "+" : ""}$${usd.toFixed(0)}${pct != null ? ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)` : ""}</span>`;
}

// Money with sign, for the hero numbers.
function _money(n) {
  const v = n || 0;
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toLocaleString(undefined, {maximumFractionDigits: 0})}`;
}

// A compact "exit plan" pill: take-profit (green) and stop (red) target prices,
// with the live exit-config % and any trailing/floor/time-cap context. This is
// the redesigned Exit column — it shows the ACTUAL targets, not a stale label.
function _exitPlanStock(p, e) {
  const cfg = _lastExitCfg || {};
  const tp = +cfg.stock_tp_pct || 6, sl = +cfg.stock_sl_pct || 3;
  const entry = p.entry || 0, last = p.last || entry;
  const tpPx = entry * (1 + tp / 100);
  // Stop is the tighter of the configured % and the engine's trailing/floor stop.
  const cfgStop = entry * (1 - sl / 100);
  const engStop = e && e.stop ? e.stop : 0;
  const stopPx = engStop ? Math.max(engStop, cfgStop) : cfgStop;
  const isFloor = e && e.profit_floor;
  // progress toward TP (how far price has travelled from stop→TP)
  const span = Math.max(tpPx - stopPx, 0.0001);
  const prog = Math.min(100, Math.max(0, (last - stopPx) / span * 100));
  const days = e && e.days_to_cap != null ? `${e.days_to_cap}d` : `${cfg.time_cap_days || 21}d`;
  const tierTxt = e && e.tier >= 1 ? ` ·T${e.tier}` : "";
  const stopLbl = isFloor ? "Floor" : "Stop";
  return `<div class="pos-exit">
    <div class="pos-exit-bar"><span style="width:${prog}%"></span></div>
    <div class="pos-exit-row">
      <span class="pe-sl">${stopLbl} $${stopPx.toFixed(2)}${tierTxt}</span>
      <span class="pe-tp">TP $${tpPx.toFixed(2)}</span>
    </div>
    <div class="pos-exit-meta">+${tp}% / −${sl}% · trail · ${days}</div>
  </div>`;
}

function _exitPlanOption(netCost, mktVal) {
  const cfg = _lastExitCfg || {};
  const tp = +cfg.opt_tp_pct || 80, sl = +cfg.opt_sl_pct || 50;
  const tpVal = netCost * (1 + tp / 100);
  const slVal = netCost * (1 - sl / 100);
  const span = Math.max(tpVal - slVal, 0.0001);
  const prog = Math.min(100, Math.max(0, (mktVal - slVal) / span * 100));
  return `<div class="pos-exit">
    <div class="pos-exit-bar"><span style="width:${prog}%"></span></div>
    <div class="pos-exit-row">
      <span class="pe-sl">SL $${slVal.toFixed(0)}</span>
      <span class="pe-tp">TP $${tpVal.toFixed(0)}</span>
    </div>
    <div class="pos-exit-meta">+${tp}% / −${sl}% · stall ${cfg.opt_stall_min || 90}m</div>
  </div>`;
}

function _heroCard(label, valHtml, sub, accent) {
  return `<div class="pos-hero-card" style="--accent:${accent || "var(--accent)"}">
    <div class="pos-hero-label">${label}</div>
    <div class="pos-hero-val">${valHtml}</div>
    <div class="pos-hero-sub">${sub || ""}</div>
  </div>`;
}

function _renderPositionsTable() {
  const el = document.getElementById("positions-tab-body");
  if (!el) return;
  try {
  const acct     = (_lastPositions.account || []).filter(p => (p.qty || 0) !== 0)
                     .sort((a,b) => (b.pnl_usd||0) - (a.pnl_usd||0));
  const acctOpts = (_lastPositions.options || []).filter(p => (p.qty || 0) !== 0);
  const autoBy = {};
  (_lastPositions.auto || []).forEach(p => { autoBy[p.sym] = p; });
  if (!acct.length && !acctOpts.length) {
    el.innerHTML = `<div class="pos-empty">
      <div class="pos-empty-ico">📭</div>
      <div class="pos-empty-title">No open positions</div>
      <div class="pos-empty-sub">Positions you hold will appear here with live P&L and their exit plan.</div>
    </div>`;
    return;
  }

  // ── Aggregates for the hero row ──
  const gTot = acct.reduce((s,p)=>s+(p.pnl_usd||0),0) + acctOpts.reduce((s,p)=>s+(p.pnl_usd||0),0);
  const gDay = acct.reduce((s,p)=>s+(p.day_pnl_usd||0),0) + acctOpts.reduce((s,p)=>s+(p.day_pnl_usd||0),0);
  const mktTotal = acct.reduce((s,p)=>s+((p.last||p.entry||0)*(p.qty||0)),0)
                 + acctOpts.reduce((s,p)=>s+(p.mkt_value||0),0);
  const nPos = acct.length + acctOpts.length;
  const winners = [...acct, ...acctOpts].filter(p => (p.pnl_usd||0) > 0).length;
  const totCls = gTot >= 0 ? "up" : "down";
  const dayCls = gDay >= 0 ? "up" : "down";

  let html = `<div class="pos-wrap">`;

  // Hero strip
  html += `<div class="pos-hero">
    ${_heroCard("Total P&amp;L", `<span class="ph-${totCls}">${_money(gTot)}</span>`,
                `across ${nPos} position${nPos!==1?"s":""}`, gTot>=0?"#22c55e":"#f43f5e")}
    ${_heroCard("Today", `<span class="ph-${dayCls}">${_money(gDay)}</span>`,
                "session change", gDay>=0?"#22c55e":"#f43f5e")}
    ${_heroCard("Market Value", `$${mktTotal.toLocaleString(undefined,{maximumFractionDigits:0})}`,
                "open exposure", "#3b82f6")}
    ${_heroCard("Winners", `${winners}<span class="ph-frac">/${nPos}</span>`,
                `${nPos?Math.round(winners/nPos*100):0}% in profit`, "#8b5cf6")}
  </div>`;

  html += `<div class="pos-toolbar">
    <span class="pos-toolbar-title">Open Positions</span>
    <button class="pos-refresh" onclick="refreshPositions()">↻ Refresh</button>
  </div>`;

  // ── Stocks & ETFs ──
  if (acct.length) {
    const totPnl = acct.reduce((s, p) => s + (p.pnl_usd || 0), 0);
    const totDay = acct.reduce((s, p) => s + (p.day_pnl_usd || 0), 0);
    html += `<div class="pos-sec">
      <div class="pos-sec-head"><span class="pos-sec-name">📈 Stocks &amp; ETFs <em>${acct.length}</em></span>
        <span class="pos-sec-tot">Today ${_posPnl(totDay)} · Total ${_posPnl(totPnl)}</span></div>`;
    html += `<div class="pos-tbl-wrap"><table class="pos-tbl"><thead><tr>
      <th>Symbol</th><th>Qty</th><th class="num">Entry</th><th class="num">Now</th>
      <th>Exit plan</th><th class="num">Day</th><th class="num">Total P&amp;L</th></tr></thead><tbody>`;
    html += acct.map(p => {
      const e = autoBy[p.sym];
      const src = e ? `🤖 ${e.strategy || "engine"}` : "manual";
      const last = p.last || p.entry || 0;
      const up = (p.pnl_usd || 0) >= 0;
      return `<tr class="pos-row ${up ? "row-up" : "row-down"}">
        <td><div class="pos-sym"><b>${p.sym}</b><span class="pos-src">${src}</span></div></td>
        <td>${p.qty}</td>
        <td class="num">$${(p.entry || 0).toFixed(2)}</td>
        <td class="num"><b>$${last.toFixed(2)}</b></td>
        <td class="exit-td">${_exitPlanStock(p, e)}</td>
        <td class="num">${_posPnl(p.day_pnl_usd, p.day_pnl_pct)}</td>
        <td class="num">${_posPnl(p.pnl_usd, p.pnl_pct)}</td></tr>`;
    }).join("");
    html += `</tbody></table></div></div>`;
  }

  // ── Options (grouped by underlying) ──
  if (acctOpts.length) {
    const byU = {};
    acctOpts.forEach(p => { (byU[p.sym] = byU[p.sym] || []).push(p); });
    // Sort option groups by total P&L desc (operator) — matches the stocks table.
    const _grpPnl = legs => legs.reduce((s, l) => s + (l.pnl_usd || 0), 0);
    const groups = Object.entries(byU).sort((a, b) => _grpPnl(b[1]) - _grpPnl(a[1]));
    const oTot = acctOpts.reduce((s,p)=>s+(p.pnl_usd||0),0);
    const oDay = acctOpts.reduce((s,p)=>s+(p.day_pnl_usd||0),0);
    html += `<div class="pos-sec">
      <div class="pos-sec-head"><span class="pos-sec-name">🎯 Options <em>${groups.length}</em></span>
        <span class="pos-sec-tot">Today ${_posPnl(oDay)} · Total ${_posPnl(oTot)}</span></div>`;
    html += `<div class="pos-tbl-wrap"><table class="pos-tbl"><thead><tr>
      <th>Underlying</th><th>Legs</th><th class="num">Net cost</th><th class="num">Mkt value</th>
      <th>Exit plan</th><th class="num">Day</th><th class="num">Total P&amp;L</th></tr></thead><tbody>`;
    html += groups.map(([u, legs]) => {
      const netCost = Math.abs(legs.reduce((s,l)=>s+((l.entry||0)*100*(l.qty||0)),0));
      const mktVal  = legs.reduce((s,l)=>s+(l.mkt_value||0),0);
      const netPnl  = legs.reduce((s,l)=>s+(l.pnl_usd||0),0);
      const netDay  = legs.reduce((s,l)=>s+(l.day_pnl_usd||0),0);
      const pct     = netCost > 0 ? (netPnl/netCost*100) : null;
      const legList = legs.map(l=>`<span class="pos-leg">${l.qty>0?"+":""}${l.qty} ${l.occ}</span>`).join("");
      const up = netPnl >= 0;
      return `<tr class="pos-row ${up ? "row-up" : "row-down"}">
        <td><b>${u}</b></td>
        <td class="pos-legs">${legList}</td>
        <td class="num">$${netCost.toFixed(0)}</td>
        <td class="num"><b>$${mktVal.toFixed(0)}</b></td>
        <td class="exit-td">${_exitPlanOption(netCost, mktVal)}</td>
        <td class="num">${_posPnl(netDay)}</td>
        <td class="num">${_posPnl(netPnl, pct)}</td></tr>`;
    }).join("");
    html += `</tbody></table></div></div>`;
  }

  html += `</div>`;
  el.innerHTML = html;
  } catch (err) {
    el.innerHTML = `<div class="pos-empty"><div class="pos-empty-title">Positions render error</div>
      <div class="pos-empty-sub">${err.message}</div></div>`;
    console.error("renderPositionsTable", err);
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// SCREENER TAB — Two validated tables with live auto-update
// Backtest results (2yr, 25 symbols, next-day open→close · run 2026-05-24):
//   Breakout  PF 1.88  Win 51.5%  Dir 51.5%  AvgRet +0.78%  ✅
//   Bull Flag PF 1.44  Win 61.5%  Dir 61.5%  AvgRet +0.45%  ✅ (Volatile Markets p.57)
//   RSI Dip   PF 1.41  Win 53.7%  Dir 53.7%  AvgRet +0.42%  ✅
//   Gap+Vol   PF 1.37  Win 50.6%  Dir 50.6%  AvgRet +0.41%  ✅
//   Momentum  PF 1.00  → REMOVED (no edge)
//   VWAP Bounce PF 0.85 → REMOVED (negative edge)
// Elder Impulse insight: RSI Dip + Red PF=1.82 > Green PF=1.76 (mean-reversion)
//   Impulse Red = OK for RSI Dip · NOT OK for momentum setups
// ═════════════════════════════════════════════════════════════════════════════
const SCR_SETUP_CFG = {
  "Breakout":    { color: "#3b82f6", label: "Breakout",   pf: 1.88, valid: true  },
  "Bull Flag":   { color: "#22c55e", label: "Bull Flag",  pf: 1.44, valid: true  },
  "RSI Dip":     { color: "#f97316", label: "RSI Dip",    pf: 1.41, valid: true  },
  "Gap+Vol":     { color: "#eab308", label: "Gap+Vol",    pf: 1.37, valid: true  },
  "Momentum":    { color: "#475569", label: "Momentum",   pf: 1.00, valid: false },
  "VWAP Bounce": { color: "#475569", label: "VWAP Bounce",pf: 0.85, valid: false },
  "Neutral":     { color: "#334155", label: "Neutral",    pf: 0,    valid: false },
};

let _scrLastTs  = 0;   // timestamp of last received update
let _autoTrade  = false;  // mirrors server state["auto_trade"] — skip confirm when true
let _scrAutoId = null; // setInterval handle for clock tick

function showScreener() {
  _setViewMode("screener");
  document.getElementById("tab-screener").classList.add("active");
  socket.emit("get_screener", {});       // serve cache + refresh if stale
  _scrStartClock();
}

function scrRefresh() {
  const spin = document.getElementById("scr-spin");
  if (spin) spin.style.display = "";
  socket.emit("get_screener", { force: true });
}

// ── Auto-execute options toggle ───────────────────────────────────────────────
function scrToggleAutoExec() {
  socket.emit("toggle_auto_execute_options");
}

function _updateAutoExecBtn(armed, execToday) {
  execToday = execToday || [];
  // Primary control now lives in Settings → Automation
  const btn = document.getElementById("btn-auto-exec");
  if (btn) {
    btn.classList.toggle("armed", !!armed);
    btn.classList.toggle("off",  !armed);
    btn.textContent = armed ? "🟢 ON" : "⬛ OFF";
  }
  // (screener-topbar mirror removed per operator request 2026-06-01 — the
  //  armed control + counter live in Settings → Automation)
}

// ── Inner screener tab switch ─────────────────────────────────────────────────
function scrSwitchTab(tab) {
  ["picks", "stocks", "options"].forEach(t => {
    const btn  = document.getElementById("scr-tab-" + t);
    const pane = document.getElementById("scr-pane-" + t);
    if (btn)  btn.classList.toggle("active",  t === tab);
    if (pane) pane.classList.toggle("active", t === tab);
  });
}

function _scrStartClock() {
  if (_scrAutoId) return;
  _scrAutoId = setInterval(() => {
    const el = document.getElementById("scr-updated");
    if (!el || !_scrLastTs) return;
    const age = Math.round((Date.now() / 1000) - _scrLastTs);
    const mins = Math.floor(age / 60), secs = age % 60;
    const ageStr = mins > 0 ? `${mins}m ${secs}s ago` : `${secs}s ago`;
    el.textContent = `Updated ${ageStr}`;
  }, 5000);
}

function _scrBadge(text, color, bg) {
  bg  = bg  || color + "20";
  return `<span class="scr-badge" style="background:${bg};color:${color};border:1px solid ${color}40">${text}</span>`;
}

function _clsDir(v) { return v > 0 ? "scr-up" : v < 0 ? "scr-down" : "scr-flat"; }

// ── KB-principles confidence cell (shared by both tables) ────────────────────
// pct = % of codified KB rules the candidate matches. principles = {matched,failed}.
function _scrConfCell(pct, principles) {
  if (pct == null) return `<td><span style="color:#475569">—</span></td>`;
  const color = pct >= 75 ? "#22c55e" : pct >= 60 ? "#f59e0b" : "#f43f5e";
  const p = principles || {};
  const matched = (p.matched || []).map(s => "✓ " + s).join("\n");
  const failed  = (p.failed  || []).map(s => "✗ " + s).join("\n");
  const tip = `KB match ${pct}% — share of codified KB rules this setup satisfies (NOT a win probability). Gate floor 60%.\n\n${matched}${failed ? "\n\n" + failed : ""}`
    .replace(/"/g, "'");
  const gate = pct < 60 ? " 🔒" : "";
  return `<td title="${tip}"><b style="color:${color}">${pct}%</b>${gate}</td>`;
}

// ── Held-position exit plan cell (operator: show OUR exits for what we bought)
function _scrExitInline(ep) {
  if (!ep) return "";
  const f = v => (v == null ? "—" : (typeof v === "number" ? v.toFixed(2) : v));
  const stop = ep.stop != null ? `stop ${f(ep.stop)}` : "";
  const tgt  = ep.target != null ? ` · tgt ${f(ep.target)}` : "";
  // Honest badge per daily-position status: only an OPEN (filled) position is "HELD".
  // A pending/unfilled order or a fresh signal is NOT held — it just suppresses a
  // duplicate buy. (Bug: a never-filled pending order showed 🔵 HELD.)
  const st = ep.status || "open";
  const [badge, color] = st === "pending" ? ["⏳ PENDING", "#f59e0b"]
                       : st === "signal"  ? ["📍 SIGNAL",  "#a78bfa"]
                       : ["🔵 HELD", "var(--cyan)"];
  const tip = `${st === "open" ? "HELD" : st.toUpperCase()} ${ep.instrument} · entry ${f(ep.entry)} (${ep.unit||""})\n` +
              `stop ${f(ep.stop)}${ep.target!=null?` · target ${f(ep.target)}`:""}\n` +
              `exit: ${ep.trigger||""}`;
  return `<span title="${tip.replace(/"/g,"'")}" style="color:${color};font-weight:700">${badge}</span>` +
         `<br><span style="font-size:9px;color:var(--muted)">${stop}${tgt}</span>`;
}

// ── Table 1 renderer — Day Trading Stocks ────────────────────────────────────
function _renderDtTable(rows) {
  const tbody = document.getElementById("scr-dt-tbody");
  if (!tbody) return;

  // Sort by KB match desc (operator 2026-06-04). Previously [...valid, ...neutral],
  // which overrode the server's KB-match ordering — that's why stocks weren't sorted.
  const sorted = [...rows].sort((a, b) => (b.kb_match || 0) - (a.kb_match || 0));
  const all = sorted.slice(0, 15);
  // CR-3: keep the FULL sorted list (not the 15-slice) so _execPick can map a Picks-tab
  // row ranked >15 back to its execution row; the 15 rendered buttons index the same prefix.
  window._scrDtRows = sorted;

  // Update tab count badge
  const countEl = document.getElementById("scr-stocks-count");
  if (countEl) countEl.textContent = all.length || "—";

  if (!all.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:32px;font-size:11px">
      Loading live data… (takes ~60 s for 25 symbols)</td></tr>`;
    return;
  }

  let rank = 0;
  tbody.innerHTML = all.map(r => {
    const cfg      = SCR_SETUP_CFG[r.setup] || SCR_SETUP_CFG["Neutral"];
    const isValid  = cfg.valid;
    const chgSign  = r.chg_pct >= 0 ? "+" : "";
    const rvCls    = r.rel_vol >= 1.5 ? "scr-up" : r.rel_vol < 0.8 ? "scr-down" : "";
    const rsiCls   = r.rsi14 <= 35 ? "scr-down" : r.rsi14 >= 60 ? "scr-up" : "";
    const rsi2Cls  = r.rsi2_d < 10 ? "scr-down" : r.rsi2_d > 70 ? "scr-up" : "";
    const vwapArrow= r.vwap_diff >= 0 ? "▲" : "▼";
    const vwapCls  = r.vwap_diff >= 0 ? "scr-up" : "scr-down";
    const setupBadge = _scrBadge(cfg.label, cfg.color);
    const pfDisp   = isValid ? `<b style="color:${cfg.color}">${r.bt_pf.toFixed(2)}</b>` : `<span style="color:#475569">—</span>`;
    const retDisp  = isValid ? `<span class="scr-up">+${r.bt_ret.toFixed(3)}%</span>` : `<span style="color:#475569">—</span>`;

    // ── Elder Impulse System (Step-by-Step p.47) ─────────────────────────────
    // Backtest insight: For RSI Dip (mean-reversion), Red PF=1.82 > Green PF=1.76
    // Red Impulse = sustained selling = BETTER entry for dip buys (NOT a veto for RSI Dip)
    // Red IS a veto for momentum setups (Breakout, Bull Flag, Gap+Vol)
    const imp = r.impulse || "Blue";
    const impEmoji = imp === "Green" ? "🟢" : imp === "Red" ? "🔴" : "🔵";
    const isRsiDip = r.setup === "RSI Dip";
    const impTitle = imp === "Green"
      ? "Elder Impulse Green — EMA13 rising + MACD-H rising → BUY ZONE"
      : imp === "Red"
        ? (isRsiDip
            ? "Elder Impulse Red — sustained selling = BETTER dip-buy entry for RSI Dip (PF 1.82 > All 1.41) — mean-reversion backtest insight"
            : "Elder Impulse Red — EMA13 falling + MACD-H falling → NO LONGS for momentum setups (Elder p.47)")
        : "Elder Impulse Blue — mixed signals → neutral, watch";
    // Row highlight: only flag Red for momentum setups, not RSI Dip
    const impStyle = imp === "Red" && isValid && !isRsiDip
      ? 'style="background:rgba(255,61,104,0.08)"' : "";
    const impDisp  = `<span title="${impTitle}">${impEmoji}</span>`;

    // ── O'Neill Pocket Pivot (Morales p.132) ─────────────────────────────────
    const ppStar  = r.pkt_pivot
      ? `<span title="📌 O'Neill Pocket Pivot — today's volume > highest down-day vol in prior 10 sessions (Morales p.132)">📌</span>` : "";
    const topStar = r.is_top
      ? `<span class="scr-top-star" title="Top-5 backtested performer for this setup">⭐</span>` : "";
    const pickDisp = `${topStar}${ppStar}`;

    const rowCls   = isValid ? "scr-row" : "scr-row scr-neutral";
    rank += isValid ? 1 : 0;
    const rankDisp = isValid ? `<b>${rank}</b>` : `<span style="color:#334155">—</span>`;

    const reason   = (r.reason   || "").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    const strategy = (r.strategy || "").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    const hasDetail = !!(r.reason || r.strategy);
    const detailHint = hasDetail ? ` <span class="scr-expand-hint">▸ click for strategy</span>` : "";

    // Tooltip shows the columns we removed from the table (Range%, HV20, RSI2-D, raw values)
    const rowTip = `Range ${r.day_range.toFixed(1)}%  HV20 ${r.hv20.toFixed(0)}%  RSI2-D ${r.rsi2_d.toFixed(1)}  EMA20 $${r.ema20_d}  EMA13 $${(r.ema13_d||0).toFixed(2)}  FI2d ${(r.fi2d||0).toFixed(0)}  ADV ${r.adv30m}M`;
    // Setup cell folds in the profit factor (removed the standalone PF/Ret% cols)
    const setupCell = isValid
      ? `<div class="scr-setup-cell">${setupBadge}<span class="scr-setup-pf" style="color:${cfg.color}">PF ${r.bt_pf.toFixed(2)} · +${r.bt_ret.toFixed(2)}%</span></div>`
      : `<span style="color:#475569">—</span>`;
    return `<tr class="${rowCls} scr-expandable" ${impStyle}
        title="${rowTip}"
        onclick="_toggleScrDetail(this)">
      <td class="scr-rank">${rankDisp}</td>
      <td><span class="scr-sym">${r.sym} <span title="${impTitle}" style="font-size:10px">${impEmoji}</span></span><br><span class="scr-sector">${r.sector}${detailHint}</span></td>
      <td class="scr-price num">$${r.price.toFixed(2)}</td>
      <td class="num ${_clsDir(r.chg_pct)}">${chgSign}${r.chg_pct.toFixed(1)}%</td>
      <td class="num ${rvCls}">${r.rel_vol.toFixed(2)}×</td>
      <td>${setupCell}</td>
      ${_scrConfCell(r.kb_match, r.kb_principles)}
      <td>${r.held ? _scrExitInline(r.exit_plan) : pickDisp}</td>
      <td>${(isValid && !r.held)
        ? `<button class="scr-exec-btn" onclick='event.stopPropagation(); _execScreenerStock(${all.indexOf(r)})' title="Buy 10 shares of ${r.sym} (paper)">⚡ Buy</button>`
        : `<span style="color:var(--muted);font-size:10px">—</span>`}</td>
    </tr>
    <tr class="scr-detail-row" style="display:none">
      <td colspan="9">
        <div class="scr-detail-panel">
          ${reason   ? `<div class="scr-detail-reason"><span class="scr-detail-label">📊 Why rated:</span> ${reason}</div>` : ""}
          ${strategy ? `<div class="scr-detail-strategy"><span class="scr-detail-label">🎯 Strategy:</span> ${strategy}</div>` : ""}
          <div class="scr-detail-meta">RSI14 ${r.rsi14.toFixed(0)} · vs VWAP ${vwapArrow}${Math.abs(r.vwap_diff).toFixed(1)}% · Impulse ${imp} · Range ${r.day_range.toFixed(1)}% · HV20 ${r.hv20.toFixed(0)}%</div>
        </div>
      </td>
    </tr>`;
  }).join("");
}

// ── Table 2 renderer — Options Opportunities ──────────────────────────────────
function _renderOptTable(rows) {
  const tbody = document.getElementById("scr-opt-tbody");
  if (!tbody) return;

  const display = rows.slice(0, 15);

  // Update tab count badge
  const optCountEl = document.getElementById("scr-options-count");
  if (optCountEl) optCountEl.textContent = display.length || "—";

  if (!display.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:24px">
      No active signals today — Connors RSI(2) &lt; 10 triggers after market close ·
      intraday setups populate once market opens</td></tr>`;
    return;
  }

  tbody.innerHTML = display.map((o, idx) => {
    // Badge color by source quality
    const badgeColor =
      o.badge.includes("Proven")   ? "#a78bfa" :
      o.badge.includes("Top Pick") ? "#f59e0b" : "#22c55e";
    const badge = _scrBadge(o.badge, badgeColor);

    // Direction chip
    const dirColor = o.direction.includes("▲") ? "#22c55e" : "#f43f5e";
    const dirBadge = `<span style="color:${dirColor};font-weight:700">${o.direction}</span>`;

    // Dir hit color — Bull Flag 61.5% > RSI Dip 53.7% > Breakout 51.5% > Gap+Vol 50.6%
    const dirHit  = o.dir_pct || 0;
    const dirCls  = dirHit >= 60 ? "scr-up" : dirHit >= 53 ? "" : "scr-down";
    const dirDisp = `<span class="${dirCls}" title="Backtested directional accuracy: ≥60% green, 53-60% neutral, &lt;53% yellow">${dirHit.toFixed(1)}%</span>`;

    // PF color
    const pfColor = o.pf >= 1.3 ? "#22c55e" : o.pf >= 1.1 ? "#f59e0b" : "#f43f5e";
    const pfDisp  = `<b style="color:${pfColor}">${(o.pf||0).toFixed(2)}</b>`;

    // Structure badge
    const structColor = o.structure.includes("Spread") ? "#f59e0b" : "#22d3ee";
    const structBadge = _scrBadge(o.structure, structColor);

    // Action — mark rows promoted to BUY purely on a 100% KB-match
    const actCls  = o.action === "✅ BUY" ? "scr-action-buy" : "scr-action-watch";
    const kb100   = o.kb100_upgrade ? ` <span title="promoted to BUY on 100% KB-match" style="font-size:9px;color:#22c55e">⭐100</span>` : "";
    const action  = `<span class="${actCls}">${o.action}</span>${kb100}`;

    // IVR
    const ivrDisp = o.ivr && o.ivr !== "—"
      ? `<span style="color:${parseFloat(o.ivr)<30?'#22c55e':'#f59e0b'}">IVR ${o.ivr}</span>`
      : `<span style="color:#475569">—</span>`;

    // Execute button — enabled only for BUY-recommended rows
    // stopPropagation prevents the row click (detail toggle) from firing
    const canExec  = o.action === "✅ BUY";
    const execPayload = JSON.stringify({
      sym: o.sym, structure: o.structure, expiry: o.expiry,
      opt_type: o.opt_type || "Call", max_risk: o.max_risk || 400,
      // include scoring fields so the server-side KB/debate gate can evaluate the row
      dir_pct: o.dir_pct, pf: o.pf, ivr: o.ivr,
      direction: o.direction, signal: o.signal
    }).replace(/"/g, "&quot;");
    // If we HOLD this symbol, show OUR exit plan instead of the Execute button
    const execBtn = o.held
      ? _scrExitInline(o.exit_plan)
      : (canExec
        ? `<button class="scr-exec-btn" onclick='event.stopPropagation(); _execScreenerOption(${idx})'
             title="Place MARKET order via Alpaca (paper · relaxed-fill, §9 advisory)\n${o.sym} ${o.structure} ${o.expiry}\nHard ceiling: $600 · +80%/−50% exit"
             data-payload="${execPayload}">⚡ Buy @ Mkt</button>`
        : `<span style="color:var(--muted);font-size:10px">—</span>`);

    const oReason   = (o.reason   || "").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    const oStrategy = (o.strategy || "").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    const oHasDetail = !!(o.reason || o.strategy);
    const oHint = oHasDetail
      ? ` <span class="scr-expand-hint">▸ click row for strategy</span>` : "";

    // Edge cell merges directional hit-rate + profit factor (dropped 2 columns)
    const edgeCell = `<div class="scr-edge-cell">${dirDisp}<span class="scr-edge-pf">PF ${pfDisp}</span></div>`;
    // Expiry cell folds in DTE + IVR detail (dropped those columns)
    const ivrInline = (o.ivr && o.ivr !== "—") ? ` · IVR ${o.ivr}` : "";
    const expiryCell = `<div class="scr-exp-cell"><span>${o.expiry}</span><span class="scr-exp-dte">${o.dte}d${ivrInline}</span></div>`;
    return `<tr class="scr-row scr-expandable" title="${(o.confidence||'').replace(/"/g,"'")}"
        onclick="_toggleScrDetail(this)">
      <td><div class="scr-sym"><b>${o.sym}</b><span class="scr-src-tag">${badge}</span></div><span style="font-size:9px;color:var(--muted)">${oHint}</span></td>
      <td>${dirBadge}<br><span class="scr-sector" style="font-size:10px">${o.signal}</span></td>
      <td class="num">${edgeCell}</td>
      <td>${structBadge}</td>
      <td>${expiryCell}</td>
      ${_scrConfCell(o.kb_match, o.kb_principles)}
      <td class="num" style="color:#f59e0b" title="Hard ceiling $600/trade — fills at market, +80%/−50% exit"><b>≤$600</b></td>
      <td>${action}</td>
      <td>${execBtn}</td>
    </tr>
    <tr class="scr-detail-row" style="display:none">
      <td colspan="9">
        <div class="scr-detail-panel">
          ${oReason   ? `<div class="scr-detail-reason"><span class="scr-detail-label">📊 Why rated:</span> ${oReason}</div>` : ""}
          ${oStrategy ? `<div class="scr-detail-strategy"><span class="scr-detail-label">🎯 Strategy:</span> ${oStrategy}</div>` : ""}
        </div>
      </td>
    </tr>`;
  }).join("");

  // Store rows for execute function to reference
  // CR-3: store the FULL rows (not the 15-slice) so _execPick maps picks ranked >15.
  // The 15 rendered Execute buttons index the same prefix, so their indices stay valid.
  window._scrOptRows = rows;
}

// ── Merged Picks renderer (MERGED_PICKS_ENABLED) — one KB-ranked list ─────────
// shown==traded. Each pick is routed to stock or option; ⚡ Buy dispatches to the
// existing per-instrument executor by matching the underlying row by symbol.
function _renderPicksTable(rows) {
  const tbody = document.getElementById("scr-picks-tbody");
  if (!tbody) return;
  const all = (rows || []).slice(0, 20);
  window._scrPickRows = all;
  const countEl = document.getElementById("scr-picks-count");
  if (countEl) countEl.textContent = all.length || "—";
  if (!all.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:32px;font-size:11px">No picks yet…</td></tr>`;
    return;
  }
  tbody.innerHTML = all.map((p, i) => {
    const routeChip = p.route === "options" ? _scrBadge("Ⓞ Option", "#a78bfa")
                    : p.route === "stocks"  ? _scrBadge("🅢 Stock", "#38bdf8")
                    : _scrBadge("skip", "#64748b");
    const detail = p.structure || (p.route === "stocks" ? "shares" : "");
    const edge = (p.dir_pct != null)
      ? `${(+p.dir_pct).toFixed(0)}% · PF ${p.pf != null ? (+p.pf).toFixed(2) : "—"}` : "";
    const canBuy = p.action === "✅ BUY" && p.route !== "skip" && !p.held;
    const act = p.held ? _scrExitInline(p.exit_plan)
      : (canBuy
         ? `<button class="scr-exec-btn" onclick='event.stopPropagation(); _execPick(${i})' title="Route ${p.route} (paper)">⚡ Buy</button>`
         : `<span style="color:var(--muted)">${(p.action || "").replace("✅ ", "")}</span>`);
    return `<tr>
      <td><b>${p.sym}</b><br><span style="font-size:9px;color:var(--muted)">${p.source || p.strategy || ""}</span></td>
      <td>${routeChip}</td>
      <td>${detail}</td>
      ${_scrConfCell(p.kb_match, p.kb_principles)}
      <td class="num">${edge}</td>
      <td>${act}</td>
    </tr>`;
  }).join("");
}

// ⚡ Buy on a pick → dispatch to the existing executor by route, matching by symbol.
function _execPick(idx) {
  const p = (window._scrPickRows || [])[idx];
  if (!p) return;
  if (p.route === "options") {
    const oi = (window._scrOptRows || []).findIndex(o => (o.sym || "").toUpperCase() === p.sym);
    if (oi >= 0) return _execScreenerOption(oi);
  } else if (p.route === "stocks") {
    const si = (window._scrDtRows || []).findIndex(r => (r.sym || "").toUpperCase() === p.sym);
    if (si >= 0) return _execScreenerStock(si);
  }
  _scrToast(`${p.sym} not executable`, p.route_reason || "no route", "warn");
}

// ── SocketIO handlers ─────────────────────────────────────────────────────────
socket.on("screener_data", function(data) {
  _scrLastTs = data.ts || (Date.now() / 1000);

  // Status bar
  const mktEl  = document.getElementById("scr-mkt-status");
  const dotEl  = document.getElementById("scr-dot");
  const spinEl = document.getElementById("scr-spin");
  if (mktEl)  mktEl.textContent = data.market_open ? "Market Open" : "Market Closed";
  if (dotEl)  { dotEl.className = "scr-dot " + (data.market_open ? "live" : "closed"); }
  if (spinEl) spinEl.style.display = "none";

  _renderDtTable(data.dt || []);
  _renderOptTable(data.options || []);
  // Merged picks (MERGED_PICKS_ENABLED): show the unified tab and default to it.
  const picksTab = document.getElementById("scr-tab-picks");
  if (data.picks) {
    _renderPicksTable(data.picks);
    if (picksTab) picksTab.style.display = "";
    if (!window._scrPicksShown) { scrSwitchTab("picks"); window._scrPicksShown = true; }
  } else if (picksTab) {
    picksTab.style.display = "none";   // flag off → hide, keep legacy tabs
  }
  _scrStartClock();
});

// Result handler for options execution
window._kbBlocked = {};
socket.on("screener_order_result", function(r) {
  const ok   = r.success;
  const sym  = r.sym || "";
  const msg  = r.message || (ok ? "Order submitted" : "Order failed");
  const paper = r.paper !== false;  // default true = paper

  // Gate-blocked manual click → arm an override so a second click forces it
  if (r.gate_blocked) { window._kbBlocked[sym] = true; }
  else if (ok) { delete window._kbBlocked[sym]; }

  _scrToast(
    ok ? `✅ ${sym} Order Submitted${paper ? " (paper)" : " ⚠ LIVE!"}`
       : (r.gate_blocked ? `⚠️ ${sym} below KB floor` : `❌ ${sym} Order Failed`),
    msg,
    ok ? (paper ? "info" : "warn") : (r.gate_blocked ? "warn" : "error")
  );

  // Re-enable execute buttons (restore the right label per table)
  document.querySelectorAll("#scr-opt-tbody .scr-exec-btn").forEach(b => { b.disabled = false; b.textContent = "⚡ Execute"; });
  document.querySelectorAll("#scr-dt-tbody  .scr-exec-btn").forEach(b => { b.disabled = false; b.textContent = "⚡ Buy"; });
});

// ── Options execute function ───────────────────────────────────────────────────
function _execScreenerOption(idx) {
  const rows = window._scrOptRows || [];
  const o    = rows[idx];
  if (!o) return;

  // Skip confirmation modal when Auto-Trade is ON (mirrors the existing
  // trade_signal behaviour where backend auto-approves without user click)
  if (!_autoTrade) {
    const msg = `Execute ${o.structure} on ${o.sym}?\n\nExpiry: ${o.expiry}\nMax risk: $${o.max_risk||400}\nAccount: Paper (dry_run mirrors server setting)`;
    if (!confirm(msg)) return;
  }

  // Disable button during submission
  const btn = document.querySelectorAll(".scr-exec-btn")[idx];
  if (btn) { btn.disabled = true; btn.textContent = "⏳ Submitting…"; }

  socket.emit("execute_screener_option", {
    sym:       o.sym,
    structure: o.structure,
    expiry:    o.expiry,
    opt_type:  o.opt_type || "Call",
    max_risk:  o.max_risk || 400,
    // scoring fields so the server KB gate can evaluate the row (was missing →
    // gate saw 0% dir / 0 PF and blocked valid picks like HOOD)
    dir_pct:   o.dir_pct,
    pf:        o.pf,
    ivr:       o.ivr,
    direction: o.direction,
    signal:    o.signal,
    kb_override: !!window._kbBlocked[o.sym],
  });
}

// ── Stock execute function (buy 10 shares, paper) ─────────────────────────────
function _execScreenerStock(idx) {
  const rows = window._scrDtRows || [];
  const r = rows[idx];
  if (!r) return;
  if (!_autoTrade) {
    if (!confirm(`Buy 10 shares of ${r.sym} (${r.setup})?\n\nPrice ~$${(r.price||0).toFixed(2)}  ·  Paper (dry_run mirrors server)`)) return;
  }
  const btns = document.querySelectorAll("#scr-dt-tbody .scr-exec-btn");
  const btn = btns[idx];
  if (btn) { btn.disabled = true; btn.textContent = "⏳…"; }
  socket.emit("execute_screener_stock", {
    sym: r.sym, price: r.price, setup: r.setup, valid: r.valid,
    bt_pf: r.bt_pf, rel_vol: r.rel_vol, rsi14: r.rsi14, impulse: r.impulse,
    kb_override: !!window._kbBlocked[r.sym],
  });
}

// ── Expandable detail row toggle ──────────────────────────────────────────────
function _toggleScrDetail(tr) {
  // Each data row is immediately followed by its hidden detail sibling
  const detail = tr.nextElementSibling;
  if (!detail || !detail.classList.contains("scr-detail-row")) return;
  const opening = detail.style.display === "none" || detail.style.display === "";
  detail.style.display = opening ? "table-row" : "none";
  tr.classList.toggle("scr-expanded", opening);
}

// ── Toast notification helper ─────────────────────────────────────────────────
function _scrToast(title, body, type) {
  // type: "info" | "warn" | "error"
  const colors = { info: "#22c55e", warn: "#f59e0b", error: "#f43f5e" };
  const color  = colors[type] || colors.info;

  const toast = document.createElement("div");
  toast.style.cssText = `
    position:fixed; bottom:24px; right:24px; z-index:9999;
    background:#1e293b; border:1px solid ${color}; border-radius:8px;
    padding:12px 18px; max-width:480px; box-shadow:0 4px 24px rgba(0,0,0,.6);
    font-size:13px; color:#e2e8f0; animation:fadeInUp 0.3s ease;
  `;
  toast.innerHTML = `
    <div style="font-weight:700;color:${color};margin-bottom:4px">${title}</div>
    <div style="color:#94a3b8;font-size:11px;word-break:break-all">${body}</div>
  `;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 8000);
}

// ── Zoom / refresh (all panes) ────────────────────────────────────────────────
function zoomIn() {
  gridManager.panes.forEach(p => {
    if (!p.chart) return;
    const lr = p.chart.timeScale().getVisibleLogicalRange();
    if (lr) { const d = (lr.to-lr.from)*0.2; p.chart.timeScale().setVisibleLogicalRange({from:lr.from+d,to:lr.to-d}); }
  });
}
function zoomOut() {
  gridManager.panes.forEach(p => {
    if (!p.chart) return;
    const lr = p.chart.timeScale().getVisibleLogicalRange();
    if (lr) { const d = (lr.to-lr.from)*0.3; p.chart.timeScale().setVisibleLogicalRange({from:lr.from-d,to:lr.to+d}); }
  });
}
function resetZoom() { gridManager.panes.forEach(p => p.chart && p.chart.timeScale().fitContent()); }
function refreshChart() { gridManager.panes.forEach(p => p.fetch(true)); }

// ── Backtest UI ───────────────────────────────────────────────────────────────

// S&P 500 top-100 by avg daily volume (random sample pool)
const BT_SP500_TOP100 = [
  "AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","GOOG","AVGO","JPM",
  "V","UNH","XOM","LLY","JNJ","WMT","MA","PG","HD","COST","ORCL","ABBV",
  "BAC","KO","MRK","CVX","NFLX","AMD","CRM","ACN","PEP","TMO","ADBE",
  "CSCO","ABT","LIN","IBM","GS","MS","TXN","ISRG","AMGN","INTU","AXP",
  "SPGI","CAT","RTX","GE","HON","NEE","ETN","LOW","BKNG","VRTX","DHR",
  "MDT","BLK","PLD","SYK","GILD","REGN","C","CVS","ELV","BSX","CI",
  "MDLZ","KLAC","LRCX","CME","MU","SNPS","CDNS","ZTS","PANW","CTAS",
  "APH","PGR","AON","ICE","EQIX","CL","MCO","F","GM","T","VZ","WFC",
  "USB","ADP","TGT","SO","D","DUK","EXC","AEP","SRE","SPY","QQQ","IWM"
];

// State
let _btSymbols  = new Set(["SPY"]);
let _btYears    = 1;
let _btSource   = "yfinance";
let _btBarSize  = "daily";
let _btStopPct  = 0.30;
let _btTargetPct= 1.00;
let _btVolMin   = 1.2;

// ── Init chip display on load ─────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => btRenderChips());

// ── Show / hide ───────────────────────────────────────────────────────────────
function showBacktest() {
  _setViewMode("chart");
  document.getElementById("backtest-panel").style.display = "";
  const gw = document.getElementById("chart-grid-wrapper");
  if (gw) gw.style.display = "none";
  document.querySelectorAll("#tab-chart, #tab-settings, #tab-log").forEach(t => t.classList.remove("active"));
  document.getElementById("tab-backtest").classList.add("active");
  btRenderChips();
}

function hideBacktest() {
  const bp = document.getElementById("backtest-panel");
  if (bp) bp.style.display = "none";
  const gw = document.getElementById("chart-grid-wrapper");
  if (gw) gw.style.display = "";
  document.getElementById("tab-backtest").classList.remove("active");
}

// ── Symbol helpers ────────────────────────────────────────────────────────────
function btRandom(n) {
  const pool = [...BT_SP500_TOP100];
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  _btSymbols = new Set(pool.slice(0, n));
  btRenderChips();
}

function btAddSymbol() {
  const inp = document.getElementById("bt-sym-input");
  const raw = inp.value.toUpperCase().trim();
  if (!raw) return;
  raw.split(/[\s,;]+/).forEach(s => { if (s.length >= 1 && s.length <= 5) _btSymbols.add(s); });
  inp.value = "";
  btRenderChips();
}

function btRemove(sym) {
  _btSymbols.delete(sym);
  btRenderChips();
}

function btClear() {
  _btSymbols.clear();
  btRenderChips();
}

function btRenderChips() {
  const cont  = document.getElementById("bt-chips");
  const count = document.getElementById("bt-sym-count");
  if (!cont) return;
  const syms  = [..._btSymbols];
  cont.innerHTML = syms.length
    ? syms.map(s => `<span class="bt-chip">${s}<span class="bt-chip-x" onclick="btRemove('${s}')">×</span></span>`).join("")
    : `<span style="color:var(--muted);font-size:11px">No symbols — use 🎲 random or type to add</span>`;
  if (count) count.textContent = syms.length === 1 ? "1 symbol" : `${syms.length} symbols`;
}

// ── Period / bar / param setters ──────────────────────────────────────────────
function setBtPeriod(y)  { _btYears    = y; }
function setBtBarSize(v) { _btBarSize  = v; }
function setBtStop(v)    { _btStopPct  = v; }
function setBtTarget(v)  { _btTargetPct = v; }
function setBtVol(v)     { _btVolMin   = v; }

// ── Strategy preset selector ───────────────────────────────────────────────────
function btSetStratPreset(preset) {
  const all = [...document.querySelectorAll("[name='bt-strat']")];
  const core      = ["breakout","bull_flag","rsi_dip","gap_vol"];
  const extended  = ["rsi_dip_red","nr7","bb_squeeze","pocket_pivot","pbs","turtle_soup"];
  const intraday  = ["orb","vwap","ema","rsi_gate"];
  all.forEach(cb => {
    if (preset === "core")      cb.checked = core.includes(cb.value);
    else if (preset === "extended") cb.checked = core.includes(cb.value) || extended.includes(cb.value);
    else if (preset === "intraday") cb.checked = intraday.includes(cb.value);
    else if (preset === "all")  cb.checked = true;
    else if (preset === "none") cb.checked = false;
  });
}

// ── Run ───────────────────────────────────────────────────────────────────────
function runBacktest() {
  const symbols = [..._btSymbols];
  if (!symbols.length) { alert("Add at least one symbol (or use 🎲 random)."); return; }

  const strategies = [...document.querySelectorAll("[name='bt-strat']:checked")]
    .map(el => el.value);
  if (!strategies.length) { alert("Select at least one strategy."); return; }

  const logEl  = document.getElementById("bt-log");
  const resEl  = document.getElementById("bt-results");
  const logTtl = document.getElementById("bt-log-title");
  const runBtn = document.getElementById("bt-run-btn");

  logEl.innerHTML  = "";
  resEl.style.display = "none";
  logTtl.style.display = "";
  runBtn.disabled  = true;
  runBtn.textContent = "⏳ Running…";

  // Scroll the run button into view so the log appears right below it.
  runBtn.scrollIntoView({ behavior: "smooth", block: "center" });

  socket.emit("run_backtest", {
    symbols,
    years:      _btYears,
    source:     _btSource,
    bar_size:   _btBarSize,
    strategies,
    stop_pct:   _btStopPct,
    target_pct: _btTargetPct,
    vol_min:    _btVolMin,
  });
}

// ── Log stream ────────────────────────────────────────────────────────────────
socket.on("backtest_log", (d) => {
  const logEl = document.getElementById("bt-log");
  if (!logEl) return;
  const div = document.createElement("div");
  div.className = "bt-log-line " +
    (d.level === "ERROR" ? "err" : (d.message.startsWith("✓") || d.message.startsWith("✅")) ? "ok" : "inf");
  div.textContent = d.message;
  logEl.appendChild(div);
  // Scroll the bt-body (not the log element itself) to keep the log in view.
  const body = document.querySelector(".bt-body");
  if (body) body.scrollTop = body.scrollHeight;
  if (d.message.includes("complete")) {
    const runBtn = document.getElementById("bt-run-btn");
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = "▶ Run Backtest"; }
  }
});

// ── Results renderer ──────────────────────────────────────────────────────────
socket.on("backtest_results", (d) => {
  const tbody = document.getElementById("bt-tbody");
  const resEl = document.getElementById("bt-results");
  const meta  = document.getElementById("bt-results-meta");
  if (!tbody || !d.results || !d.results.length) return;

  // Setup badge class — covers all KB-validated strategies
  const setupBadge = (setup) => {
    const cls = {
      // Core validated (§DT1–DT5)
      "Breakout":     "bt-setup-brk",
      "Bull Flag":    "bt-setup-bfl",
      "RSI Dip":      "bt-setup-rsi",
      "Gap+Vol":      "bt-setup-gap",
      // Extended KB strategies
      "RSI Dip+Red":  "bt-setup-rdr",   // §T6 best sub-condition PF 1.82
      "NR7":          "bt-setup-nr7",   // §DT14 Cooper narrowest range
      "BB Squeeze":   "bt-setup-bbsq", // §T13 Bollinger bandwidth squeeze
      "Pocket Pivot": "bt-setup-pp",   // §T8 Morales/Kacher accumulation
      "PBS":          "bt-setup-pbs",  // §T22 Velez Pristine Buy Setup
      "Turtle Soup":  "bt-setup-ts",   // §DT8 Raschke 20d low reversal
      // Intraday
      "ORB":          "bt-setup-orb",
      "VWAP":         "bt-setup-vwap",
      "Intraday":     "bt-setup-intr",
    }[setup] || "bt-setup-intr";
    return `<span class="bt-setup-badge ${cls}">${setup}</span>`;
  };

  // Sort: best PF first
  const sorted = [...d.results].sort((a, b) => {
    const pfa = parseFloat(a.metrics?.profit_factor) || 0;
    const pfb = parseFloat(b.metrics?.profit_factor) || 0;
    return pfb - pfa;
  });

  tbody.innerHTML = sorted.map(r => {
    const m   = r.metrics || {};
    const pf  = m.profit_factor ?? "n/a";
    const pfl = parseFloat(pf) || 0;
    const wr  = m.win_rate ?? 0;
    const sig = m.total_pnl ?? 0;
    const bh  = r.baseline ?? 0;
    const sh  = m.sharpe ?? 0;
    const dd  = m.max_dd ?? 0;
    const exp = m.expectancy ?? 0;

    let edge = "—", edgeCls = "bt-muted";
    if (r.trades > 0) {
      if (pfl >= 1.5 && sh >= 0.5)      { edge = "✅ Yes";        edgeCls = "bt-edge-yes";  }
      else if (pfl >= 1.0 && pfl < 1.5) { edge = "⚠️ Marginal";  edgeCls = "bt-edge-marg"; }
      else                               { edge = "❌ No";         edgeCls = "bt-edge-no";   }
    }

    const pfCls  = pfl >= 1.5 ? "bt-green" : pfl >= 1.0 ? "bt-cyan" : "bt-red";
    const bhDiff = sig - bh;

    return `<tr>
      <td class="bt-cyan" style="font-weight:700">${r.symbol}</td>
      <td>${setupBadge(r.setup || "—")}</td>
      <td>${r.trades}</td>
      <td class="${wr >= 50 ? 'bt-green' : 'bt-red'}">${wr.toFixed(1)}%</td>
      <td class="${pfCls}">${typeof pf === 'number' ? pf.toFixed(2) : pf}</td>
      <td class="${exp >= 0 ? 'bt-green' : 'bt-red'}">${exp >= 0 ? '+' : ''}${exp.toFixed(2)}%</td>
      <td class="${sh >= 0.5 ? 'bt-green' : sh >= 0 ? '' : 'bt-red'}">${sh.toFixed(2)}</td>
      <td class="${dd <= -10 ? 'bt-red' : 'bt-muted'}">${dd.toFixed(2)}%</td>
      <td class="${sig >= 0 ? 'bt-green' : 'bt-red'}">${sig >= 0 ? '+' : ''}${sig.toFixed(2)}%</td>
      <td class="${bhDiff >= 0 ? 'bt-green' : 'bt-red'}">${bhDiff >= 0 ? '+' : ''}${bhDiff.toFixed(2)}%</td>
      <td class="${edgeCls}">${edge}</td>
    </tr>`;
  }).join("");

  if (meta) {
    const src   = d.source || "yfinance";
    const yrs   = d.years  || "?";
    const nsym  = new Set(d.results.map(r => r.symbol)).size;
    const total = d.results.reduce((s, r) => s + (r.trades || 0), 0);
    meta.textContent = `${nsym} symbol${nsym>1?'s':''} · ${yrs}yr · ${src} · ${total} total trades`;
  }

  resEl.style.display = "";
  // Scroll results into view inside the bt-body container.
  requestAnimationFrame(() => {
    resEl.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

// ── Route chart_data to the correct pane ─────────────────────────────────────
socket.on("chart_data", (d) => {
  if (d.pane_id != null) {
    const pane = gridManager.panes[d.pane_id];
    if (pane) pane.onData(d);
  } else {
    // Legacy fallback (no pane_id): route to pane 0
    if (gridManager.panes[0]) gridManager.panes[0].onData(d);
  }
});

// ── Real-time signal markers (broadcast to all matching panes) ────────────────
socket.on("chart_signal", (s) => {
  if (!s) return;
  gridManager.panes.forEach(p => p.addSignalMarker(s));
  // Surface in Last-Signal banner
  const sb = document.getElementById("signal-banner");
  const st = document.getElementById("signal-text");
  if (sb && st && s.tip) { st.textContent = s.tip; sb.classList.add("show"); }
});

// ── Open Positions card ───────────────────────────────────────────────────────
function _renderAutoPositions(autoPos) {
  // Autonomous-engine stock positions (separate store from intraday options)
  const a = (autoPos || []).filter(p => (p.qty || 0) > 0);
  if (!a.length) return "";
  const rows = a.map(p => {
    const pnl = p.pnl_usd != null
      ? `<span class="pos-pnl ${p.pnl_usd >= 0 ? 'up' : 'down'}">${p.pnl_usd >= 0 ? '+' : ''}$${p.pnl_usd.toFixed(0)} (${(p.pnl_pct||0).toFixed(1)}%)</span>`
      : '';
    const tier = p.tier >= 1 ? ` · T${p.tier}` : '';
    const dry = p.dry_run ? ' <span style="color:var(--muted);font-size:9px">[DRY]</span>' : '';
    // Once the stop ratchets to/above entry it's a profit-locking floor, not a stop.
    const stopLbl = p.profit_floor ? 'Floor' : 'Stop';
    const stopCls = p.profit_floor ? ' style="color:var(--up)"' : '';
    // Exit plan: trailing stop ratchets up (no fixed target — winners ride it) +
    // a time-cap backstop that forces an exit after the hold limit.
    const capTxt = (p.days_to_cap != null) ? `cap ${p.days_to_cap}d` : 'cap 21d';
    return `<div class="pos-row">
      <div class="pos-top">
        <span class="pos-sym">${p.sym}${dry}</span>
        <span class="pos-dir bull">${p.qty}sh</span>
        ${pnl}
      </div>
      <div class="pos-levels">
        <span>${p.strategy}</span>
        <span>Entry $${(p.entry||0).toFixed(2)}</span>
        <span>Now $${(p.last||p.entry||0).toFixed(2)}</span>
        <span${stopCls}>${stopLbl} $${(p.stop||0).toFixed(2)}${tier}</span>
        <span title="trailing stop ratchets up (no fixed target); ${capTxt} = forced time-cap exit">Exit: trail · ${capTxt}</span>
      </div>
    </div>`;
  }).join('');
  return `<div style="font-size:10px;color:var(--muted);margin:6px 0 2px">🤖 Autonomous engine (${a.length})</div>${rows}`;
}

function renderPositions(positions, autoPos) {
  const el = document.getElementById("positions-list");
  if (!el) return;
  const active = (positions || []).filter(p => (p.remaining ?? p.contracts ?? 0) > 0);
  const autoHtml = _renderAutoPositions(autoPos);
  if (!active.length && !autoHtml) {
    el.innerHTML = '<div class="pos-empty">No open positions</div>';
    return;
  }
  el.innerHTML = active.map(p => {
    const dir    = (p.direction || "bull").toLowerCase();
    const dirLbl = dir === "bull" ? "CALL" : "PUT";
    const entry  = p.entry_price ?? 0;
    const stop   = p.stop_price  ?? 0;
    const t1     = p.target_50   ?? 0;
    const t2     = p.target_75   ?? 0;
    const qty    = p.remaining   ?? p.contracts ?? 0;
    const unreal = p.unrealized_pct ?? null;
    const pnlHtml = unreal != null
      ? `<span class="pos-pnl ${unreal >= 0 ? 'up' : 'down'}">${unreal >= 0 ? '+' : ''}${unreal.toFixed(1)}%</span>`
      : '';
    const sym = p.occ_symbol ?? p.symbol ?? '?';
    const dryTag = p.is_dry_run ? ' <span style="color:var(--muted);font-size:9px">[DRY]</span>' : '';
    const narr = p.narrative ? `<div class="pos-narrative">${p.narrative}</div>` : '';
    return `<div class="pos-row">
      <div class="pos-top">
        <span class="pos-sym">${sym}${dryTag}</span>
        <span class="pos-dir ${dir}">${dirLbl} ×${qty}</span>
        ${pnlHtml}
      </div>
      <div class="pos-levels">
        <span>Entry $${entry.toFixed(2)}</span>
        <span>Stop $${stop.toFixed(2)}</span>
        <span>T1 $${t1.toFixed(2)}</span>
        <span>T2 $${t2.toFixed(2)}</span>
      </div>
      ${narr}
    </div>`;
  }).join('') + autoHtml;
}
