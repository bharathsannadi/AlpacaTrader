/* SPY Auto Trader — Dashboard JS */

const socket = io({ secure: true, rejectUnauthorized: false });
let logEl     = document.getElementById("log-output");
let lineCount = 0;

// ── Socket events ─────────────────────────────────────────────────────────────
// Server emits state automatically on connect — no need to call refresh.
// Refresh is auth-required, so calling it before login causes a disconnect.
socket.on("state", updateUI);

// Server tells us we need to re-authenticate (e.g. after a reconnect)
socket.on("login_required", () => {
  document.getElementById("login-overlay").classList.remove("hidden");
  appendLog("Session expired — please log in again.", "WARNING");
});

socket.on("login_result", (r) => {
  const btn = document.getElementById("login-btn");
  btn.disabled    = false;
  btn.textContent = "Connect to Alpaca";
  if (r.success) {
    document.getElementById("login-overlay").classList.add("hidden");
    appendLog("Connected successfully.", "INFO");
    socket.emit("refresh");
    gridManager.init();           // Build multi-pane chart grid
    requestExecBrief();           // Load exec narrative on login
  } else {
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

// ── UI update ─────────────────────────────────────────────────────────────────
function updateUI(s) {
  if (!s.logged_in) {
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
    const riskPct = parseFloat(document.getElementById("risk-pct").value) / 100;
    setEl("hdr-risk", fmt(s.account_value * riskPct));
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

  // Mode pill
  const pill = document.getElementById("mode-pill");
  if (pill) {
    const accountLabel = s.paper_mode ? "PAPER" : "LIVE";
    const tradeLabel   = s.dry_run    ? "DRY RUN" : "LIVE TRADING";
    pill.textContent = `${accountLabel} · ${tradeLabel}`;
    pill.className = "mode-pill" +
      (!s.dry_run   ? " live" :
       s.paper_mode ? " paper-on" : "");
  }

  document.getElementById("dry-run-toggle").checked = !!s.dry_run;

  setStreamButtons(s.streaming);

  // Automation toggles
  syncToggleBtn("btn-auto-schedule", s.auto_schedule !== false);
  syncToggleBtn("btn-news-filter",   s.news_filter_enabled !== false);
  syncToggleBtn("btn-trade-memory",  s.trade_memory_enabled !== false);
  syncToggleBtn("btn-debate",        s.debate_enabled === true);
  syncToggleBtn("btn-auto-trade",    s.auto_trade === true);

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
  if (s.open_positions !== undefined) renderPositions(s.open_positions);

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
  if (!dot) return;
  dot.className  = `stream-dot ${streaming ? "live" : ""}`;
  start.disabled = !!streaming;
  stop.disabled  = !streaming;
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

  btn.disabled    = true;
  btn.textContent = "Connecting...";
  socket.emit("login", { api_key: apiKey, api_secret: apiSecret, paper });
}

function doLogout()          { socket.emit("logout");              }
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
  // Default to Settings view on load
  _setViewMode("settings");


  ["login-api-key", "login-api-secret"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
  });

  // Drag-drop layout (reorder within / between panels)
  restoreCardOrder();
  initDragDrop();
  updateGridLayout();

  // Panel resize divider
  restorePanelWidth();
  initPanelResize();
});

// ── Drag-and-drop card reordering ─────────────────────────────────────────────
const STORAGE_KEY = "spyTraderCardOrder";
let draggedCard   = null;

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
  if (!confirm("Reset all card positions to defaults? Your custom layout will be lost.")) return;
  localStorage.removeItem(STORAGE_KEY);
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

const SYMBOLS = [
  "SPY","AMZN","GOOG","MSFT","NVDA","META","IWM",
  "CBRE","GLW","QQQ","NFLX","CRWV","NET","AAPL","NOW","SOFI",
  "HOOD","UNH","MU","AMD","ARM","TSM","LRCX","AVGO","IBM",
  "PLTR","CRM","ORCL","NKE","TEAM","UBER","CRWD","ADBE","INTC",
  "MA","V","WFC","C","BAC","JPM",
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
    this.chart          = null;
    this.candleSeries   = null;
    this.vwapSeries     = null;
    this.ema9Series     = null;
    this.ema21Series    = null;
    this.ema200Series   = null;
    this.volumeSeries   = null;
    this.bbUpperSeries  = null;
    this.bbMidSeries    = null;
    this.bbLowerSeries  = null;

    // Sub-chart LWC handles (RSI / MACD)
    this.rsiChart         = null;
    this.rsiSeries        = null;
    this.macdChart        = null;
    this.macdFastSeries   = null;
    this.macdSignalSeries = null;
    this.macdHistSeries   = null;

    this._priceLines = [];
    this._posLines   = [];
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
    try {
      const s = localStorage.getItem(`chart_pane_${this.id}_ind`);
      if (s) return JSON.parse(s);
    } catch (_) {}
    return { ema9: false, ema21: false, ema200: true, vwap: true, bb: false, rsi: false, macd: false };
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
      { key: "ema9",   color: "#22d3ee", label: "EMA (9)" },
      { key: "ema21",  color: "#a78bfa", label: "EMA (21)" },
      { key: "ema200", color: "#f43f5e", label: "EMA (200)" },
      { key: "vwap",   color: "#f59e0b", label: "VWAP" },
      { section: "BANDS & CHANNELS" },
      { key: "bb",     color: "#60a5fa", label: "Bollinger (20, 2)" },
      { section: "OSCILLATORS" },
      { key: "rsi",    color: "#a78bfa", label: "RSI (14)" },
      { key: "macd",   color: "#22d3ee", label: "MACD (12, 26, 9)" },
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
    // Wire checkbox events (clicking row also toggles)
    indPanel.querySelectorAll(".ind-row").forEach(row => {
      row.addEventListener("click", e => {
        const key = row.dataset.ind;
        if (e.target.tagName !== "INPUT") {
          const cb = row.querySelector("input");
          cb.checked = !cb.checked;
        }
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

    chartArea.appendChild(mainBody);
    chartArea.appendChild(rsiBody);
    chartArea.appendChild(macdBody);

    content.appendChild(indPanel);
    content.appendChild(chartArea);

    pane.appendChild(hdr);
    pane.appendChild(content);
    gridEl.appendChild(pane);

    this.paneEl      = pane;
    this._bodyEl     = mainBody;
    this._rsiBodyEl  = rsiBody;
    this._macdBodyEl = macdBody;
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
    this.vwapSeries   = this.chart.addLineSeries({ color: "#f59e0b", lineWidth: 2, priceLineVisible: false, lastValueVisible: true,  title: "VWAP"    });
    this.ema9Series   = this.chart.addLineSeries({ color: "#22d3ee", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "EMA9"    });
    this.ema21Series  = this.chart.addLineSeries({ color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "EMA21"   });
    this.ema200Series = this.chart.addLineSeries({ color: "#f43f5e", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, title: "EMA200d" });
    // Bollinger Bands (hidden until enabled)
    this.bbUpperSeries = this.chart.addLineSeries({ color: "#60a5fa66", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    this.bbMidSeries   = this.chart.addLineSeries({ color: "#60a5fa99", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    this.bbLowerSeries = this.chart.addLineSeries({ color: "#60a5fa66", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

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
    if (this._rsiBodyEl)  this._rsiBodyEl.style.display  = this._ind.rsi  ? "" : "none";
    if (this._macdBodyEl) this._macdBodyEl.style.display = this._ind.macd ? "" : "none";
    // Re-render with cached bars
    if (this._lastBars) this._renderData(this._lastBars, this._lastOverlays);
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
    const newClose = bars.length ? bars[bars.length-1].close : null;
    const clean    = arr => (arr || []).filter(p => p && p.value != null);

    this.candleSeries.setData(bars);
    if (this.volumeSeries)
      this.volumeSeries.setData(bars.map(b => ({
        time: b.time, value: b.volume,
        color: (b.close >= b.open) ? "#00e5a055" : "#ff3d6855",
      })));

    // Overlays from server — gated by indicator toggles
    if (this.vwapSeries)   this.vwapSeries.setData(  this._ind.vwap  ? clean(ov.vwap)  : []);
    if (this.ema9Series)   this.ema9Series.setData(   this._ind.ema9  ? clean(ov.ema9)  : []);
    if (this.ema21Series)  this.ema21Series.setData(  this._ind.ema21 ? clean(ov.ema21) : []);
    if (this.ema200Series) {
      const e200 = ov.ema200d;
      if (this._ind.ema200 && e200 && newClose && Math.abs((e200-newClose)/newClose) <= 0.03)
        this.ema200Series.setData(bars.map(b => ({ time: b.time, value: e200 })));
      else
        this.ema200Series.setData([]);
    }

    // Bollinger Bands (computed client-side)
    if (this._ind.bb && bars.length >= 20) {
      const { upper, mid, lower } = ChartPane._computeBB(bars);
      if (this.bbUpperSeries) this.bbUpperSeries.setData(upper);
      if (this.bbMidSeries)   this.bbMidSeries.setData(mid);
      if (this.bbLowerSeries) this.bbLowerSeries.setData(lower);
    } else {
      if (this.bbUpperSeries) this.bbUpperSeries.setData([]);
      if (this.bbMidSeries)   this.bbMidSeries.setData([]);
      if (this.bbLowerSeries) this.bbLowerSeries.setData([]);
    }

    // RSI sub-chart
    if (this._ind.rsi && this.rsiSeries && bars.length > 15) {
      this.rsiSeries.setData(ChartPane._computeRSI(bars));
      if (this.rsiChart) this.rsiChart.timeScale().fitContent();
    } else if (this.rsiSeries) {
      this.rsiSeries.setData([]);
    }

    // MACD sub-chart
    if (this._ind.macd && this.macdFastSeries && bars.length > 27) {
      const { macdData, signalData, histData } = ChartPane._computeMACD(bars);
      this.macdFastSeries.setData(macdData);
      this.macdSignalSeries.setData(signalData);
      this.macdHistSeries.setData(histData);
      if (this.macdChart) this.macdChart.timeScale().fitContent();
    } else if (this.macdFastSeries) {
      this.macdFastSeries.setData([]); this.macdSignalSeries.setData([]); this.macdHistSeries.setData([]);
    }

    if (bars.length > 0) this.chart.timeScale().fitContent();
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
    if (this.rsiChart)  { try { this.rsiChart.remove();  } catch (_) {} this.rsiChart  = null; }
    if (this.macdChart) { try { this.macdChart.remove(); } catch (_) {} this.macdChart = null; }
    if (this.chart)     { try { this.chart.remove();     } catch (_) {} this.chart     = null; }
    if (this.paneEl)    { this.paneEl.remove(); this.paneEl = null; }
  }

  // ── Client-side indicator computation ──────────────────────────────────────
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

    // Sync grid count buttons
    document.querySelectorAll(".grid-btn").forEach(b => {
      b.classList.toggle("active", parseInt(b.dataset.count) === n);
    });

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
  document.body.classList.remove("view-chart", "view-settings", "view-log");
  document.body.classList.add("view-" + mode);
  document.querySelectorAll("#tab-chart, #tab-settings, #tab-log, .bt-tab").forEach(t => t.classList.remove("active"));
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
let _btDays = 7;

function showBacktest() {
  _setViewMode("chart");
  document.getElementById("backtest-panel").style.display = "";
  const gw = document.getElementById("chart-grid-wrapper");
  if (gw) gw.style.display = "none";
  document.querySelectorAll(".grid-btn, #tab-settings, #tab-log").forEach(t => t.classList.remove("active"));
  document.getElementById("tab-backtest").classList.add("active");
}

function hideBacktest() {
  const bp = document.getElementById("backtest-panel");
  if (bp) bp.style.display = "none";
  const gw = document.getElementById("chart-grid-wrapper");
  if (gw) gw.style.display = "";
  document.getElementById("tab-backtest").classList.remove("active");
}

function setBtDays(d) {
  _btDays = d;
  document.querySelectorAll(".bt-day-btn").forEach(b =>
    b.classList.toggle("active", parseInt(b.dataset.days) === d));
}

function runBacktest() {
  const symbols = [...document.querySelectorAll("#bt-symbol-grid input:checked")]
    .map(el => el.value);
  if (!symbols.length) { alert("Select at least one symbol."); return; }

  const logEl  = document.getElementById("bt-log");
  const resEl  = document.getElementById("bt-results");
  const logTtl = document.getElementById("bt-log-title");
  const runBtn = document.getElementById("bt-run-btn");

  logEl.innerHTML  = "";
  resEl.style.display = "none";
  logTtl.style.display = "";
  runBtn.disabled  = true;
  runBtn.textContent = "⏳ Running…";

  socket.emit("run_backtest", { symbols, days: _btDays });
}

socket.on("backtest_log", (d) => {
  const logEl = document.getElementById("bt-log");
  if (!logEl) return;
  const div = document.createElement("div");
  div.className = "bt-log-line " +
    (d.level === "ERROR" ? "err" : d.message.startsWith("✓") ? "ok" : "inf");
  div.textContent = d.message;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
  if (d.message.includes("complete")) {
    const runBtn = document.getElementById("bt-run-btn");
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = "▶ Run Backtest"; }
  }
});

socket.on("backtest_results", (d) => {
  const tbody = document.getElementById("bt-tbody");
  const resEl = document.getElementById("bt-results");
  if (!tbody || !d.results || !d.results.length) return;

  tbody.innerHTML = d.results.map(r => {
    const m   = r.metrics || {};
    const pf  = m.profit_factor ?? "n/a";
    const pfl = parseFloat(pf);
    const wr  = m.win_rate ?? 0;
    const sig = m.total_pnl ?? 0;
    const bh  = r.baseline ?? 0;
    const sh  = m.sharpe ?? 0;
    const dd  = m.max_dd ?? 0;
    const exp = m.expectancy ?? 0;

    // Edge verdict
    let edge = "—", edgeCls = "bt-muted";
    if (r.trades > 0) {
      if (pfl >= 1.5 && sh >= 0.5)     { edge = "✅ Yes";   edgeCls = "bt-edge-yes"; }
      else if (pfl >= 1.0 && pfl < 1.5){ edge = "⚠️ Marginal"; edgeCls = "bt-edge-marg"; }
      else                              { edge = "❌ No";    edgeCls = "bt-edge-no";  }
    }

    const pnlCls  = sig >= 0  ? "bt-green" : "bt-red";
    const bhDiff  = sig - bh;
    const bhCls   = bhDiff >= 0 ? "bt-green" : "bt-red";
    const pfCls   = pfl >= 1.5 ? "bt-green" : pfl >= 1.0 ? "bt-cyan" : "bt-red";

    return `<tr>
      <td class="bt-cyan">${r.symbol}</td>
      <td>${r.trades}</td>
      <td class="${wr >= 50 ? 'bt-green' : 'bt-red'}">${wr.toFixed(1)}%</td>
      <td class="${pfCls}">${typeof pf === 'number' ? pf.toFixed(2) : pf}</td>
      <td class="${exp >= 0 ? 'bt-green' : 'bt-red'}">${exp >= 0 ? '+' : ''}${exp.toFixed(2)}%</td>
      <td class="${sh >= 0.5 ? 'bt-green' : sh >= 0 ? '' : 'bt-red'}">${sh.toFixed(2)}</td>
      <td class="${dd <= -10 ? 'bt-red' : 'bt-muted'}">${dd.toFixed(2)}%</td>
      <td class="${pnlCls}">${sig >= 0 ? '+' : ''}${sig.toFixed(2)}%</td>
      <td class="${bhCls}">${bhDiff >= 0 ? '+' : ''}${bhDiff.toFixed(2)}% vs B&H</td>
      <td class="${edgeCls}">${edge}</td>
    </tr>`;
  }).join("");

  resEl.style.display = "";
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
function renderPositions(positions) {
  const el = document.getElementById("positions-list");
  if (!el) return;
  const active = (positions || []).filter(p => (p.remaining ?? p.contracts ?? 0) > 0);
  if (!active.length) {
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
  }).join('');
}
