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
    initChart();                  // Build chart and load default 1D bars
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

  // Account
  if (s.account_value) {
    const fmt = v => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2 });
    setEl("hdr-account", fmt(s.account_value));
    setEl("hdr-bp",      fmt(s.buying_power ?? 0));
    const riskPct = parseFloat(document.getElementById("risk-pct").value) / 100;
    setEl("hdr-risk", fmt(s.account_value * riskPct));
  }

  // Active symbol — sync tab highlight + header ticker + chart title
  if (s.active_symbol && s.active_symbol !== currentSymbol) {
    currentSymbol = s.active_symbol;
    setEl("ticker-symbol", s.active_symbol);
    setEl("chart-title",   s.active_symbol);
    document.querySelectorAll(".symbol-tab").forEach(tab =>
      tab.classList.toggle("active", tab.dataset.symbol === s.active_symbol));
    _fetchChart(false);  // chart must match the new symbol
  } else if (s.active_symbol) {
    setEl("ticker-symbol", s.active_symbol);
    setEl("chart-title",   s.active_symbol);
    document.querySelectorAll(".symbol-tab").forEach(tab =>
      tab.classList.toggle("active", tab.dataset.symbol === s.active_symbol));
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

// ── Chart (lightweight-charts) ────────────────────────────────────────────────
let chart             = null;
let candleSeries      = null;
let chartInitialized  = false;
let chartRefreshTimer = null;
let _chartSeq         = 0;
let currentSymbol     = "SPY";

// ── Persistent interval + range (survive page reload via localStorage) ────────
const _IV_DEFAULT  = "15m";
const _RNG_DEFAULT = "1D";
// Live ranges: auto-refresh every N ms. Historical ranges don't change intraday.
const LIVE_RANGES        = new Set(["1D", "5D"]);
const CHART_AUTO_REFRESH = 15_000;

let currentInterval = localStorage.getItem("chart_iv")  || _IV_DEFAULT;
let currentRange    = localStorage.getItem("chart_rng") || _RNG_DEFAULT;

// ── Single fetch entry-point ──────────────────────────────────────────────────
function _fetchChart(force) {
  if (!chartInitialized) return;
  const seq = ++_chartSeq;
  socket.emit("get_chart_data", {
    interval:      currentInterval,
    range:         currentRange,
    symbol:        currentSymbol,
    force_refresh: !!force,
    _seq:          seq,
  });
}

function startChartAutoRefresh() {
  stopChartAutoRefresh();
  chartRefreshTimer = setInterval(() => {
    if (LIVE_RANGES.has(currentRange)) _fetchChart(false);
  }, CHART_AUTO_REFRESH);
}
function stopChartAutoRefresh() {
  if (chartRefreshTimer) { clearInterval(chartRefreshTimer); chartRefreshTimer = null; }
}

// ── Sync button highlights ────────────────────────────────────────────────────
function _syncIvBtns(iv) {
  document.querySelectorAll("[data-iv]").forEach(b =>
    b.classList.toggle("iv-active", b.dataset.iv === iv));
}
function _syncRngBtns(rng) {
  document.querySelectorAll("[data-rng]").forEach(b =>
    b.classList.toggle("rng-active", b.dataset.rng === rng));
}

// ── Public setters (called by button onclick) ─────────────────────────────────
function setInterval_(iv) {
  if (!iv) return;
  currentInterval = iv;
  localStorage.setItem("chart_iv", iv);
  _syncIvBtns(iv);
  _fetchChart(true);
  if (LIVE_RANGES.has(currentRange)) startChartAutoRefresh(); else stopChartAutoRefresh();
}
function setRange(rng) {
  if (!rng) return;
  currentRange = rng;
  localStorage.setItem("chart_rng", rng);
  _syncRngBtns(rng);
  _fetchChart(true);
  if (LIVE_RANGES.has(rng)) startChartAutoRefresh(); else stopChartAutoRefresh();
}

// ── Chart init ────────────────────────────────────────────────────────────────
// Overlay handles (so we can update without re-creating)
let vwapSeries     = null;
let ema9Series     = null;
let ema21Series    = null;
let ema200Series   = null;
let volumeSeries   = null;
// Price lines created on candleSeries — store the priceLine handles for cleanup
let _priceLines    = [];
// Position lines (stop/T1/T2) — same idea but tracked separately so position
// updates don't clobber prior-day / ORB lines
let _positionLines = [];

function _clearPriceLines() {
  if (!candleSeries) return;
  _priceLines.forEach(pl => { try { candleSeries.removePriceLine(pl); } catch (e) {} });
  _priceLines = [];
}
function _clearPositionLines() {
  if (!candleSeries) return;
  _positionLines.forEach(pl => { try { candleSeries.removePriceLine(pl); } catch (e) {} });
  _positionLines = [];
}

function initChart() {
  if (chartInitialized) {
    _syncIvBtns(currentInterval);
    _syncRngBtns(currentRange);
    _fetchChart(false);
    startChartAutoRefresh();
    return;
  }
  const container = document.getElementById("chart-container");
  if (!container || typeof LightweightCharts === "undefined") return;

  chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: container.clientHeight || 280,
    layout: {
      background: { type: "solid", color: "#04070e" },
      textColor:  "#7a96b8",
      fontSize:   10,
      fontFamily: "JetBrains Mono, monospace",
    },
    grid: {
      vertLines: { color: "rgba(21,32,53,0.6)" },
      horzLines: { color: "rgba(21,32,53,0.6)" },
    },
    rightPriceScale: {
      borderColor:  "#152035",
      textColor:    "#4a6280",
      scaleMargins: { top: 0.05, bottom: 0.14 },  // tighter top + volume room (~14%)
    },
    timeScale: {
      borderColor:     "#152035",
      textColor:       "#4a6280",
      timeVisible:     true,
      secondsVisible:  false,
      rightOffset:     5,
      barSpacing:      8,
      minBarSpacing:   3,
      // Don't lock the left edge — lets the time scale collapse the gaps where
      // there are no bars (lunch lull, after-hours, weekends).
      fixLeftEdge:     false,
      fixRightEdge:    false,
      lockVisibleTimeRangeOnResize: false,
    },
    crosshair: {
      mode: 1,
      vertLine: { color: "#22d3ee", width: 1, style: 3, labelBackgroundColor: "#0f3040" },
      horzLine: { color: "#22d3ee", width: 1, style: 3, labelBackgroundColor: "#0f3040" },
    },
    handleScroll: true,
    handleScale:  true,
  });

  candleSeries = chart.addCandlestickSeries({
    upColor:          "#00e5a0",
    downColor:        "#ff3d68",
    borderUpColor:    "#00e5a0",
    borderDownColor:  "#ff3d68",
    wickUpColor:      "#00e5a055",
    wickDownColor:    "#ff3d6855",
    priceLineVisible: false,   // we'll show our own — engine's last is noisy here
  });

  // VWAP — orange, the most-watched intraday line
  vwapSeries = chart.addLineSeries({
    color: "#f59e0b", lineWidth: 2, priceLineVisible: false,
    lastValueVisible: true, title: "VWAP",
  });

  // EMAs
  ema9Series  = chart.addLineSeries({
    color: "#22d3ee", lineWidth: 1, priceLineVisible: false,
    lastValueVisible: false, title: "EMA9",
  });
  ema21Series = chart.addLineSeries({
    color: "#a78bfa", lineWidth: 1, priceLineVisible: false,
    lastValueVisible: false, title: "EMA21",
  });
  ema200Series = chart.addLineSeries({
    color: "#f43f5e", lineWidth: 1, lineStyle: 2, priceLineVisible: false,
    lastValueVisible: false, title: "EMA200d",
  });

  // Volume histogram — separate price scale anchored at the bottom
  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
    color: "#3b82f660",
  });
  chart.priceScale("vol").applyOptions({
    scaleMargins: { top: 0.88, bottom: 0 },   // volume occupies bottom ~12%
    borderVisible: false,
  });

  new ResizeObserver(() => {
    if (chart && container.clientWidth && container.clientHeight)
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
  }).observe(container);

  // Crosshair hover → tooltip with all indicator values
  chart.subscribeCrosshairMove((param) => _onCrosshairMove(param));

  chartInitialized = true;
  _syncIvBtns(currentInterval);
  _syncRngBtns(currentRange);
  _fetchChart(false);
  startChartAutoRefresh();
}

function _onCrosshairMove(param) {
  const tip = document.getElementById("chart-tooltip");
  if (!tip) return;
  if (!param.time || !param.seriesPrices) { tip.style.display = "none"; return; }
  const candle = param.seriesPrices.get(candleSeries);
  if (!candle) { tip.style.display = "none"; return; }
  const vwap  = param.seriesPrices.get(vwapSeries);
  const ema9  = param.seriesPrices.get(ema9Series);
  const ema21 = param.seriesPrices.get(ema21Series);
  const fmt = v => (v == null ? "–" : v.toFixed(2));
  tip.innerHTML =
    `O ${fmt(candle.open)} · H ${fmt(candle.high)} · L ${fmt(candle.low)} · C ${fmt(candle.close)}` +
    `<br>VWAP ${fmt(vwap)} · EMA9 ${fmt(ema9)} · EMA21 ${fmt(ema21)}`;
  tip.style.display = "block";
  const x = Math.min(param.point.x + 12, document.getElementById("chart-container").clientWidth - 240);
  const y = Math.max(12, param.point.y - 60);
  tip.style.left = x + "px";
  tip.style.top  = y + "px";
}

function zoomIn() {
  if (!chart) return;
  const lr = chart.timeScale().getVisibleLogicalRange();
  if (!lr) return;
  const delta = (lr.to - lr.from) * 0.2;
  chart.timeScale().setVisibleLogicalRange({ from: lr.from + delta, to: lr.to - delta });
}

function zoomOut() {
  if (!chart) return;
  const lr = chart.timeScale().getVisibleLogicalRange();
  if (!lr) return;
  const delta = (lr.to - lr.from) * 0.3;
  chart.timeScale().setVisibleLogicalRange({ from: lr.from - delta, to: lr.to + delta });
}

function resetZoom() {
  if (!chart) return;
  chart.timeScale().fitContent();
}

function refreshChart() { _fetchChart(true); }

function _setViewMode(mode) {
  // mode: "chart" | "settings" | "log"
  document.body.classList.remove("view-chart", "view-settings", "view-log");
  document.body.classList.add("view-" + mode);
  // clear all special tab highlights
  document.querySelectorAll("#tab-settings, #tab-log, .bt-tab").forEach(t => t.classList.remove("active"));
  // Trigger chart resize when switching to chart view
  if (mode === "chart") {
    setTimeout(() => { if (window._chart) window._chart.timeScale().fitContent(); }, 50);
  }
}

function setActiveSymbol(symbol) {
  _setViewMode("chart");
  // hide backtest, show chart
  const bp = document.getElementById("backtest-panel");
  const cc = document.querySelector(".chart-card");
  if (bp) bp.style.display = "none";
  if (cc) cc.style.display = "";
  currentSymbol = symbol;
  // deactivate all tabs, activate the clicked one
  document.querySelectorAll(".symbol-tab, .settings-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".symbol-tab").forEach(tab =>
    tab.classList.toggle("active", tab.dataset.symbol === symbol));
  setEl("ticker-symbol", symbol);
  setEl("chart-title",   symbol);
  socket.emit("set_active_symbol", { symbol });
  _fetchChart(false);
}

function showSettings() {
  _setViewMode("settings");
  document.querySelectorAll(".symbol-tab[data-symbol]").forEach(t => t.classList.remove("active"));
  document.getElementById("tab-settings").classList.add("active");
}

function showLog() {
  _setViewMode("log");
  document.querySelectorAll(".symbol-tab[data-symbol]").forEach(t => t.classList.remove("active"));
  document.getElementById("tab-log").classList.add("active");
}

// ── Backtest UI ───────────────────────────────────────────────────────────────
let _btDays = 7;

function showBacktest() {
  _setViewMode("chart");
  document.getElementById("backtest-panel").style.display = "";
  document.querySelector(".chart-card").style.display = "none";
  document.querySelectorAll(".symbol-tab, .settings-tab").forEach(t => t.classList.remove("active"));
  document.getElementById("tab-backtest").classList.add("active");
}

function hideBacktest() {
  const bp = document.getElementById("backtest-panel");
  const cc = document.querySelector(".chart-card");
  if (bp) bp.style.display = "none";
  if (cc) cc.style.display = "";
  document.getElementById("tab-backtest").classList.remove("active");
  // restore active symbol tab
  document.querySelectorAll(".symbol-tab[data-symbol]").forEach(t =>
    t.classList.toggle("active", t.dataset.symbol === currentSymbol));
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

socket.on("chart_data", (d) => {
  if (!candleSeries || !d.bars) return;
  // Drop stale out-of-order responses
  if (d._seq && d._seq < _chartSeq) return;
  // Drop if symbol, interval, or range no longer matches what the user has selected
  if (d.symbol   && d.symbol   !== currentSymbol)   return;
  if (d.interval && d.interval !== currentInterval) return;
  if (d.range    && d.range    !== currentRange)    return;

  candleSeries.setData(d.bars);

  // ── Volume histogram (color-coded by candle direction) ─────────────────────
  const volData = d.bars.map(b => ({
    time:  b.time,
    value: b.volume,
    color: (b.close >= b.open) ? "#00e5a055" : "#ff3d6855",
  }));
  if (volumeSeries) volumeSeries.setData(volData);

  // ── Indicator overlays (VWAP / EMAs) ───────────────────────────────────────
  const overlays = d.overlays || {};
  const cleanLine = arr => (arr || []).filter(p => p && p.value != null);
  if (vwapSeries)  vwapSeries.setData(cleanLine(overlays.vwap));
  if (ema9Series)  ema9Series.setData(cleanLine(overlays.ema9));
  if (ema21Series) ema21Series.setData(cleanLine(overlays.ema21));
  if (ema200Series) {
    // EMA200d is a single daily value — render as a flat line across the chart
    // BUT only if it's within range of current price. Otherwise it crushes the
    // y-axis (e.g. SPY $737 with EMA200d $667 = -9.5% → candles become invisible).
    // When too far, hide the line but surface the value+distance in a badge so
    // the trader still knows the macro level.
    const FAR_PCT = 0.03;   // 3% — beyond this, hide
    const lastClose = (d.bars && d.bars.length) ? d.bars[d.bars.length - 1].close : null;
    const ema200 = overlays.ema200d;
    if (ema200 && lastClose) {
      const distFrac = (ema200 - lastClose) / lastClose;
      if (Math.abs(distFrac) <= FAR_PCT) {
        const flat = d.bars.map(b => ({ time: b.time, value: ema200 }));
        ema200Series.setData(flat);
      } else {
        ema200Series.setData([]);
      }
      _renderEma200Badge(ema200, distFrac);
    } else {
      ema200Series.setData([]);
      _renderEma200Badge(null, null);
    }
  }

  // ── ORB high/low + prior day H/L/C + position lines ────────────────────────
  _clearPriceLines();
  _clearPositionLines();

  const orb = overlays.orb || {};
  if (orb.high) _priceLines.push(candleSeries.createPriceLine({
    price: orb.high, color: "#22d3ee", lineWidth: 1, lineStyle: 0,
    axisLabelVisible: true, title: "ORB H",
  }));
  if (orb.low) _priceLines.push(candleSeries.createPriceLine({
    price: orb.low, color: "#22d3ee", lineWidth: 1, lineStyle: 0,
    axisLabelVisible: true, title: "ORB L",
  }));
  const pl = overlays.prior_levels || {};
  // Clip prior-day levels that are too far from current price — same reason
  // as EMA200d: they compress the y-axis and bury the candles.
  const _lastClose = (d.bars && d.bars.length) ? d.bars[d.bars.length - 1].close : null;
  const _within = (lvl) => {
    if (!_lastClose || !lvl) return false;
    return Math.abs((lvl - _lastClose) / _lastClose) <= 0.05;  // 5% band
  };
  if (_within(pl.prev_high))  _priceLines.push(candleSeries.createPriceLine({
    price: pl.prev_high, color: "#7a96b8", lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: "PDH",
  }));
  if (_within(pl.prev_low))   _priceLines.push(candleSeries.createPriceLine({
    price: pl.prev_low, color: "#7a96b8", lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: "PDL",
  }));
  if (_within(pl.prev_close)) _priceLines.push(candleSeries.createPriceLine({
    price: pl.prev_close, color: "#4a6280", lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: "PDC",
  }));

  // ── Open positions: entry / stop / T1 / T2 ────────────────────────────────
  // CRITICAL: entry/stop/T1/T2 are OPTION premium prices (e.g. $5.75 stop on a
  // SPY 737P), NOT underlying prices. Drawing them as priceLines on the
  // underlying-symbol chart crushes the y-axis (e.g. SPY $737 + option $3 →
  // scale spans $3-$740, candles become invisible).
  //
  // Solution: only render position lines if they fall within ±10% of the
  // current underlying price (which would be the unusual case of plotting an
  // option chart directly). Otherwise summarize positions in a side badge.
  const positions = d.position_overlay || [];
  const _within10 = (price) => {
    if (!_lastClose || !price) return false;
    return Math.abs((price - _lastClose) / _lastClose) <= 0.10;
  };
  positions.forEach(p => {
    if (!_within10(p.entry_price)) return;  // it's an option-priced position
    const dryTag = p.is_dry_run ? " [DRY]" : "";
    _positionLines.push(candleSeries.createPriceLine({
      price: p.entry_price, color: "#fbbf24", lineWidth: 2, lineStyle: 0,
      axisLabelVisible: true, title: `Entry ${p.remaining}x${dryTag}`,
    }));
    _positionLines.push(candleSeries.createPriceLine({
      price: p.stop_price, color: "#ff3d68", lineWidth: 1, lineStyle: 1,
      axisLabelVisible: true, title: `Stop${p.partial_done ? " (trail)" : ""}`,
    }));
    if (!p.partial_done) {
      _positionLines.push(candleSeries.createPriceLine({
        price: p.target_50, color: "#fbbf24", lineWidth: 1, lineStyle: 1,
        axisLabelVisible: true, title: "T1",
      }));
    }
    _positionLines.push(candleSeries.createPriceLine({
      price: p.target_75, color: "#00e5a0", lineWidth: 1, lineStyle: 1,
      axisLabelVisible: true, title: "T2",
    }));
  });

  // ── Live P&L badge for the active symbol's position ────────────────────────
  _renderPnlBadge(positions, d.bars);

  // ── Signal markers + close markers (with reason in tooltip text) ───────────
  const sigMarks = (d.signals || []).map(s => ({
    time:     s.time,
    position: s.direction === "bull" ? "belowBar"  : "aboveBar",
    color:    s.direction === "bull" ? "#00e5a0"   : "#ff3d68",
    shape:    s.direction === "bull" ? "arrowUp"   : "arrowDown",
    text:     s.direction === "bull" ? "▲ CALL"    : "▼ PUT",
  }));
  const closeMarks = (d.closes || []).map(c => ({
    time:     c.time,
    position: "inBar",
    color:    (c.pnl_pct || 0) >= 0 ? "#00e5a0" : "#ff3d68",
    shape:    "circle",
    text:     `${(c.pnl_pct || 0).toFixed(0)}% ${c.reason || ""}`.slice(0, 40),
  }));
  candleSeries.setMarkers([...sigMarks, ...closeMarks].sort((a,b) => a.time - b.time));

  // ── Blocked windows: render via background line series with shaded regions ─
  _renderBlockedWindows(d.blocked_windows || [], d.bars);

  const empty  = document.getElementById("chart-empty");
  const detail = document.getElementById("chart-empty-detail");
  if (empty) {
    if (d.bars.length === 0) {
      if (detail) detail.textContent =
        `No data · ${d.symbol || currentSymbol} ${d.interval || currentInterval} / ${d.range || currentRange}. ` +
        `Try ↻ or a different interval.`;
      empty.classList.remove("hidden");
    } else {
      empty.classList.add("hidden");
      chart.timeScale().fitContent();
    }
  } else if (d.bars.length > 0) {
    chart.timeScale().fitContent();
  }
});

function _renderEma200Badge(value, distFrac) {
  const badge = document.getElementById("chart-ema200-badge");
  if (!badge) return;
  if (value == null) { badge.style.display = "none"; return; }
  const pctStr = ((distFrac >= 0) ? "+" : "") + (distFrac * 100).toFixed(1) + "%";
  const near = Math.abs(distFrac) <= 0.03;
  badge.style.display = "inline-block";
  badge.style.color = near ? "#f43f5e" : "#7a96b8";
  badge.style.borderColor = (near ? "#f43f5e" : "#7a96b8") + "66";
  badge.textContent = `EMA200d $${value.toFixed(2)} (${pctStr})` + (near ? "" : " · off-chart");
}

function _renderPnlBadge(positions, bars) {
  const badge = document.getElementById("chart-pnl-badge");
  if (!badge) return;
  if (!positions.length || !bars.length) { badge.style.display = "none"; return; }

  // Summary across all open positions on this symbol. We can't compute true
  // option-premium P&L from underlying bars alone — the engine knows that and
  // updates the positions table separately. Here we show direction + an
  // "underlying is moving X% in/against your favor since open" hint.
  let bulls = 0, bears = 0, totalContracts = 0, anyDry = false;
  positions.forEach(p => {
    if (p.direction === "bull") bulls += p.remaining; else bears += p.remaining;
    totalContracts += p.remaining;
    if (p.is_dry_run) anyDry = true;
  });
  // Use the active session's opening bar as the reference for "favor" gauge
  const opened = bars[0].close;
  const lastClose = bars[bars.length - 1].close;
  const undMovePct = ((lastClose - opened) / opened) * 100;
  // Net directional exposure: positive = bullish bias, negative = bearish bias
  const net = bulls - bears;
  const movedWith = (net > 0 && undMovePct > 0) || (net < 0 && undMovePct < 0);
  const movedSize = Math.abs(undMovePct);
  const color = (net === 0) ? "#7a96b8" : (movedWith ? "#00e5a0" : "#ff3d68");
  const dirLabel = net > 0 ? "▲" : (net < 0 ? "▼" : "•");
  badge.style.color = color;
  badge.style.borderColor = color + "66";
  badge.style.display = "inline-block";
  badge.title = "Underlying move since open (option P&L is in the positions table)";
  badge.textContent =
    `${totalContracts}x ${dirLabel}` +
    `  und ${undMovePct >= 0 ? "+" : ""}${undMovePct.toFixed(2)}%` +
    (anyDry ? "  [DRY]" : "");
}

// Track shading overlay divs so we can remove them on each update
let _shadeEls = [];

function _renderBlockedWindows(windows, bars) {
  const container = document.getElementById("chart-container");
  if (!container || !chart) return;
  _shadeEls.forEach(el => el.remove());
  _shadeEls = [];
  if (!windows.length || !bars.length) return;

  const timeScale = chart.timeScale();
  windows.forEach(w => {
    const x1 = timeScale.timeToCoordinate(w.start);
    const x2 = timeScale.timeToCoordinate(w.end);
    if (x1 == null || x2 == null) return;
    const div = document.createElement("div");
    div.style.position = "absolute";
    div.style.left = Math.min(x1, x2) + "px";
    div.style.top = "0";
    div.style.width = Math.abs(x2 - x1) + "px";
    div.style.bottom = "20px";  // leave time axis visible
    div.style.background = "rgba(122, 150, 184, 0.06)";
    div.style.borderLeft = "1px dashed rgba(122,150,184,0.25)";
    div.style.borderRight = "1px dashed rgba(122,150,184,0.25)";
    div.style.pointerEvents = "none";
    div.style.zIndex = "1";
    div.title = w.label;
    container.appendChild(div);
    _shadeEls.push(div);
  });
}

// Real-time signal marker — push directly when one fires.
// Skip if the marker is for a different symbol than the user is viewing.
socket.on("chart_signal", (s) => {
  if (!candleSeries || !s) return;
  if (s.symbol && s.symbol !== currentSymbol) return;
  const existing = candleSeries.markers ? candleSeries.markers() : [];
  const newMark  = {
    time: s.time,
    position: s.direction === "bull" ? "belowBar" : "aboveBar",
    color:    s.direction === "bull" ? "#00d88a" : "#ff4560",
    shape:    s.direction === "bull" ? "arrowUp" : "arrowDown",
    text:     s.direction === "bull" ? "CALL"    : "PUT",
  };
  candleSeries.setMarkers([...existing, newMark]);
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
