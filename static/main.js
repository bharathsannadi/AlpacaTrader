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
  } else {
    document.getElementById("login-error").textContent = r.error || "Login failed.";
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
  // Show login if not authenticated
  if (!s.logged_in) {
    document.getElementById("login-overlay").classList.remove("hidden");
  }

  // SPY price
  if (s.spy_price) {
    const chg   = s.spy_change_pct ?? 0;
    const cls   = chg > 0 ? "up" : chg < 0 ? "down" : "neutral";
    const sign  = chg > 0 ? "+" : "";
    setEl("spy-price", `$${s.spy_price.toFixed(2)}`,  `ticker-price ${cls}`);
    setEl("spy-chg",   `${sign}${chg.toFixed(2)}%`,   `ticker-chg ${cls}`);
  }

  // VIX
  if (s.vix != null) {
    const cls = s.vix > 28 ? "down" : s.vix > 20 ? "neutral" : "up";
    setEl("hdr-vix", s.vix.toFixed(1), `value ${cls}`);
  }

  // Account
  if (s.account_value) {
    const fmt = v => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2 });
    setEl("hdr-account", fmt(s.account_value));
    setEl("hdr-bp",      fmt(s.buying_power ?? 0));

    const riskPct = parseFloat(document.getElementById("risk-pct").value) / 100;
    const maxRisk = s.account_value * riskPct;
    setEl("hdr-risk", fmt(maxRisk));
  }

  // Active symbol — keep tab + ticker label + chart title in sync
  if (s.active_symbol) {
    currentSymbol = s.active_symbol;
    setEl("ticker-symbol", s.active_symbol);
    setEl("chart-title",   s.active_symbol);
    document.querySelectorAll(".symbol-tab").forEach(tab => {
      tab.classList.toggle("active", tab.dataset.symbol === s.active_symbol);
    });
  }

  // Unified mode pill — accounts for paper/live AND dry/live trading
  const pill = document.getElementById("mode-pill");
  if (pill) {
    const accountLabel = s.paper_mode ? "PAPER" : "LIVE";
    const tradeLabel   = s.dry_run    ? "DRY RUN" : "LIVE TRADING";
    pill.textContent = `${accountLabel} · ${tradeLabel}`;
    // Class precedence: live trading > paper > dry-run
    pill.className = "mode-pill" +
      (!s.dry_run     ? " live" :
       s.paper_mode   ? " paper-on" : "");
  }

  // Toggle sync
  document.getElementById("dry-run-toggle").checked = !!s.dry_run;

  // Sessions
  setSession("morning", s.morning_running);
  setSession("evening", s.evening_running);
  setStreamButtons(s.streaming);

  // Sync time inputs (only if user is not actively editing)
  if (s.morning_end) {
    const el = document.getElementById("morning-end");
    if (el && document.activeElement !== el) el.value = s.morning_end;
    const win = document.getElementById("morning-window");
    if (win) win.textContent = `9:30 – ${formatTime12h(s.morning_end)} ET`;
  }
  if (s.evening_end) {
    const el = document.getElementById("evening-end");
    if (el && document.activeElement !== el) el.value = s.evening_end;
    const win = document.getElementById("evening-window");
    if (win) win.textContent = `3:00 – ${formatTime12h(s.evening_end)} ET`;
  }

  // Stepper values
  if (s.vix_max != null)       setEl("val-vix-max",       s.vix_max);
  if (s.stop_loss != null)     setEl("val-stop-loss",     `-${s.stop_loss}%`);
  if (s.profit_target != null) setEl("val-profit-target", `+${s.profit_target}%`);
  if (s.dte_min != null)       setEl("val-dte-min",       s.dte_min);
  if (s.dte_max != null)       setEl("val-dte-max",       s.dte_max);

  // Timestamp
  if (s.timestamp) setEl("hdr-time", s.timestamp);
}

function setEl(id, text, className) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  if (className !== undefined) el.className = className;
}

function setSession(name, running) {
  const dot   = document.getElementById(`dot-${name}`);
  const start = document.getElementById(`btn-start-${name}`);
  const stop  = document.getElementById(`btn-stop-${name}`);
  if (!dot) return;
  dot.className  = `session-dot ${running ? "running" : "stopped"}`;
  start.disabled = !!running;
  stop.disabled  = !running;
}

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

function doLogout()    { socket.emit("logout");        }
function startMorning(){ socket.emit("start_morning"); }
function stopMorning() { socket.emit("stop_morning");  }
function startEvening(){ socket.emit("start_evening"); }
function stopEvening() { socket.emit("stop_evening");  }
function startStream() { socket.emit("start_stream"); }
function stopStream()  { socket.emit("stop_stream");  }

function setSessionTimes() {
  socket.emit("set_session_times", {
    morning_end: document.getElementById("morning-end").value,
    evening_end: document.getElementById("evening-end").value,
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
  ["login-api-key", "login-api-secret"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
  });

  // Drag-drop layout (reorder within / between panels)
  restoreCardOrder();
  initDragDrop();
  updateGridLayout();
});

// ── Drag-and-drop card reordering ─────────────────────────────────────────────
const STORAGE_KEY = "spyTraderCardOrder";
let draggedCard   = null;

function initDragDrop() {
  document.querySelectorAll(".card[data-card-id]").forEach(card => {
    card.draggable = true;

    card.addEventListener("dragstart", (e) => {
      draggedCard = card;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", card.dataset.cardId);
      setTimeout(() => card.classList.add("dragging"), 0);
    });

    card.addEventListener("dragend", () => {
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
  location.reload();
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
let chart            = null;
let candleSeries     = null;
let currentTimeframe = "1D";
let currentSymbol    = "SPY";
let chartInitialized = false;

function initChart() {
  if (chartInitialized) {
    socket.emit("get_chart_data", { timeframe: currentTimeframe });
    return;
  }
  const container = document.getElementById("chart-container");
  if (!container || typeof LightweightCharts === "undefined") return;

  chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: container.clientHeight || 240,
    layout: {
      background: { type: "solid", color: "#050810" },
      textColor:  "#94a3b8",
      fontSize:   10,
      fontFamily: "JetBrains Mono, monospace",
    },
    grid: {
      vertLines: { color: "rgba(30,42,58,0.5)" },
      horzLines: { color: "rgba(30,42,58,0.5)" },
    },
    rightPriceScale: { borderColor: "#1e2a3a", textColor: "#64748b" },
    timeScale:       { borderColor: "#1e2a3a", textColor: "#64748b", timeVisible: true, secondsVisible: false },
    crosshair: {
      mode: 1,
      vertLine: { color: "#3b82f6", width: 1, style: 3, labelBackgroundColor: "#3b82f6" },
      horzLine: { color: "#3b82f6", width: 1, style: 3, labelBackgroundColor: "#3b82f6" },
    },
    handleScroll: true,
    handleScale:  true,
  });

  candleSeries = chart.addCandlestickSeries({
    upColor:        "#00d88a",
    downColor:      "#ff4560",
    borderUpColor:  "#00d88a",
    borderDownColor:"#ff4560",
    wickUpColor:    "#00d88a",
    wickDownColor:  "#ff4560",
  });

  // Auto-resize on window resize
  new ResizeObserver(() => {
    if (chart && container.clientWidth && container.clientHeight) {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    }
  }).observe(container);

  chartInitialized = true;
  socket.emit("get_chart_data", { timeframe: currentTimeframe });
}

function setTimeframe(tf) {
  currentTimeframe = tf;
  document.querySelectorAll(".tf-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.tf === tf);
  });
  if (chartInitialized) socket.emit("get_chart_data", { timeframe: tf });
}

function refreshChart() {
  if (chartInitialized) socket.emit("get_chart_data", { timeframe: currentTimeframe });
}

function setActiveSymbol(symbol) {
  currentSymbol = symbol;
  document.querySelectorAll(".symbol-tab").forEach(tab => {
    tab.classList.toggle("active", tab.dataset.symbol === symbol);
  });
  setEl("ticker-symbol", symbol);
  setEl("chart-title",   symbol);
  socket.emit("set_active_symbol", { symbol });
  if (chartInitialized) socket.emit("get_chart_data", { timeframe: currentTimeframe, symbol });
}

socket.on("chart_data", (d) => {
  if (!candleSeries || !d.bars) return;
  candleSeries.setData(d.bars);

  // Apply markers from signal history
  const markers = (d.signals || []).map(s => ({
    time: s.time,
    position: s.direction === "bull" ? "belowBar" : "aboveBar",
    color:    s.direction === "bull" ? "#00d88a" : "#ff4560",
    shape:    s.direction === "bull" ? "arrowUp" : "arrowDown",
    text:     s.direction === "bull" ? "CALL"    : "PUT",
  }));
  candleSeries.setMarkers(markers);

  // Empty-state toggle: surface "no data" instead of a silently blank chart.
  // 1D mode auto-rolls back to the last trading day, so an empty result here
  // means there's truly no IEX activity for this symbol in the last ~10 days.
  const empty   = document.getElementById("chart-empty");
  const detail  = document.getElementById("chart-empty-detail");
  if (empty) {
    if (d.bars.length === 0) {
      const sym = d.symbol || currentSymbol;
      const tf  = d.timeframe || currentTimeframe;
      if (detail) {
        detail.textContent =
          `No bars returned for ${sym} (${tf}) — Alpaca's free IEX feed ` +
          `has no recent data. Try a longer timeframe or a different symbol.`;
      }
      empty.classList.remove("hidden");
    } else {
      empty.classList.add("hidden");
      chart.timeScale().fitContent();
    }
  } else if (d.bars.length > 0) {
    chart.timeScale().fitContent();
  }
});

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
