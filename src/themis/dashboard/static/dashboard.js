// Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
// Themis Dashboard — Real-time test visualization frontend.
// Pure JavaScript, no dependencies, no build step.

(function () {
  "use strict";

  // =========================================================================
  // State
  // =========================================================================

  const state = {
    ws: null,
    connected: false,
    results: [],          // most recent first
    maxResults: 1000,
    filter: "ALL",
    search: "",
    soundEnabled: false,
    reconnectDelay: 1000,
    reconnectTimer: null,
    latencyHistory: [],   // last 50
    maxLatencyHistory: 50,
  };

  const stats = { total: 0, pass: 0, fail: 0, warn: 0, pass_rate: 0, avg_latency_ms: 0, avg_score: 0 };

  // =========================================================================
  // DOM refs (populated on init)
  // =========================================================================

  let dom = {};

  function cacheDom() {
    dom = {
      statusDot:     document.getElementById("status-dot"),
      statusText:    document.getElementById("status-text"),
      soundBtn:      document.getElementById("sound-toggle"),
      statTotal:     document.getElementById("stat-total"),
      statPass:      document.getElementById("stat-pass"),
      statFail:      document.getElementById("stat-fail"),
      statWarn:      document.getElementById("stat-warn"),
      statRate:      document.getElementById("stat-rate"),
      statLatency:   document.getElementById("stat-latency"),
      resultsPanel:  document.getElementById("results-panel"),
      filterBtns:    document.querySelectorAll(".filter-btn"),
      searchInput:   document.getElementById("search-input"),
      latencyCanvas: document.getElementById("latency-chart"),
      donutCanvas:   document.getElementById("donut-chart"),
      tokenCanvas:   document.getElementById("token-chart"),
    };
  }

  // =========================================================================
  // WebSocket
  // =========================================================================

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws`;

    state.ws = new WebSocket(url);

    state.ws.onopen = function () {
      state.connected = true;
      state.reconnectDelay = 1000;
      updateConnectionUI();
    };

    state.ws.onclose = function () {
      state.connected = false;
      updateConnectionUI();
      scheduleReconnect();
    };

    state.ws.onerror = function () {
      state.connected = false;
      updateConnectionUI();
    };

    state.ws.onmessage = function (evt) {
      let msg;
      try { msg = JSON.parse(evt.data); } catch (_) { return; }

      if (msg.type === "result") {
        handleResult(msg.data);
      } else if (msg.type === "stats") {
        Object.assign(stats, msg.data);
        renderStats();
      } else if (msg.type === "pong") {
        // keepalive ack
      }
    };
  }

  function scheduleReconnect() {
    if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(function () {
      connectWs();
      state.reconnectDelay = Math.min(state.reconnectDelay * 1.5, 15000);
    }, state.reconnectDelay);
  }

  function updateConnectionUI() {
    if (!dom.statusDot) return;
    dom.statusDot.classList.toggle("connected", state.connected);
    dom.statusText.textContent = state.connected ? "LIVE" : "DISCONNECTED";
  }

  // =========================================================================
  // Handle incoming result
  // =========================================================================

  function handleResult(data) {
    state.results.unshift(data);
    if (state.results.length > state.maxResults) state.results.pop();

    // Latency history
    state.latencyHistory.push(data.latency_ms);
    if (state.latencyHistory.length > state.maxLatencyHistory) {
      state.latencyHistory.shift();
    }

    // Sound on failure
    if (state.soundEnabled && data.verdict === "FAIL") beepFail();

    renderResults();
    drawLatencyChart();
    drawDonutChart();
    drawTokenChart();
  }

  // =========================================================================
  // Render functions
  // =========================================================================

  function renderStats() {
    if (!dom.statTotal) return;
    dom.statTotal.textContent   = stats.total;
    dom.statPass.textContent    = stats.pass;
    dom.statFail.textContent    = stats.fail;
    dom.statWarn.textContent    = stats.warn;
    dom.statRate.textContent    = stats.pass_rate + "%";
    dom.statLatency.textContent = stats.avg_latency_ms + "ms";
  }

  function renderResults() {
    if (!dom.resultsPanel) return;

    const filtered = state.results.filter(function (r) {
      if (state.filter !== "ALL" && r.verdict !== state.filter) return false;
      if (state.search && !r.name.toLowerCase().includes(state.search.toLowerCase())) return false;
      return true;
    });

    if (filtered.length === 0) {
      dom.resultsPanel.innerHTML =
        '<div class="empty-state">' +
        '<div class="empty-state-icon">&#x2696;</div>' +
        '<div class="empty-state-text">Awaiting test results...</div>' +
        '</div>';
      return;
    }

    // Build HTML. For perf, rebuild entirely (fine for <1000 items with no complex DOM).
    let html = "";
    for (let i = 0; i < Math.min(filtered.length, 200); i++) {
      html += buildResultCard(filtered[i]);
    }
    dom.resultsPanel.innerHTML = html;

    // Attach click handlers for diff expand
    dom.resultsPanel.querySelectorAll(".result-card").forEach(function (card) {
      card.addEventListener("click", function () {
        const panel = card.querySelector(".diff-panel");
        if (panel) panel.classList.toggle("open");
      });
    });
  }

  function buildResultCard(r) {
    const scorePercent = Math.round(r.score * 100);
    const scoreClass = scorePercent >= 80 ? "high" : scorePercent >= 50 ? "medium" : "low";
    const ts = new Date(r.timestamp * 1000);
    const timeStr = ts.toLocaleTimeString();

    const expectedHtml = highlightDiff(r.expected || "(none)", r.actual || "(none)", true);
    const actualHtml   = highlightDiff(r.actual || "(none)", r.expected || "(none)", false);

    return (
      '<div class="result-card verdict-' + r.verdict + '">' +
        '<div class="result-header">' +
          '<div class="result-left">' +
            '<span class="verdict-badge ' + r.verdict + '">' + r.verdict + '</span>' +
            '<span class="result-name">' + escHtml(r.name) + '</span>' +
            '<span class="result-id">#' + escHtml(r.id) + '</span>' +
          '</div>' +
          '<div class="result-metrics">' +
            '<div class="metric">' +
              '<span class="metric-value">' + r.latency_ms + 'ms</span>' +
              '<span class="metric-label">Latency</span>' +
            '</div>' +
            '<div class="metric">' +
              '<span class="metric-value">' + r.tokens_used + '</span>' +
              '<span class="metric-label">Tokens</span>' +
            '</div>' +
            '<div class="score-bar-container">' +
              '<div class="score-bar"><div class="score-bar-fill ' + scoreClass + '" style="width:' + scorePercent + '%"></div></div>' +
              '<span class="score-value">' + scorePercent + '%</span>' +
            '</div>' +
            '<span class="result-time">' + timeStr + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="diff-panel">' +
          '<div class="diff-columns">' +
            '<div class="diff-col">' +
              '<div class="diff-label">Expected</div>' +
              '<div class="diff-content">' + expectedHtml + '</div>' +
            '</div>' +
            '<div class="diff-col">' +
              '<div class="diff-label">Actual</div>' +
              '<div class="diff-content">' + actualHtml + '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  // =========================================================================
  // Diff highlighting (word-level)
  // =========================================================================

  function highlightDiff(text, other, isExpected) {
    if (!text || !other || text === "(none)" || other === "(none)") {
      return escHtml(text);
    }

    const wordsA = text.split(/(\s+)/);
    const wordsB = other.split(/(\s+)/);
    let html = "";

    for (let i = 0; i < wordsA.length; i++) {
      const w = wordsA[i];
      if (/^\s+$/.test(w)) {
        html += escHtml(w);
        continue;
      }
      if (i < wordsB.length && wordsA[i] === wordsB[i]) {
        html += '<span class="match">' + escHtml(w) + '</span>';
      } else if (i < wordsB.length && wordsA[i].toLowerCase() === wordsB[i].toLowerCase()) {
        html += '<span class="partial">' + escHtml(w) + '</span>';
      } else {
        html += '<span class="deviate">' + escHtml(w) + '</span>';
      }
    }
    return html;
  }

  // =========================================================================
  // Charts — Pure Canvas API
  // =========================================================================

  // --- Latency Sparkline ---

  function drawLatencyChart() {
    const canvas = dom.latencyCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    const data = state.latencyHistory;
    if (data.length < 2) {
      ctx.fillStyle = "#555570";
      ctx.font = "12px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Waiting for data...", W / 2, H / 2);
      return;
    }

    const max = Math.max(...data) * 1.1 || 1;
    const min = 0;
    const pad = { top: 10, bottom: 20, left: 10, right: 10 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    // Grid lines
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (plotH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
    }

    // Gradient fill
    const grad = ctx.createLinearGradient(0, pad.top, 0, H - pad.bottom);
    grad.addColorStop(0, "rgba(0, 170, 255, 0.25)");
    grad.addColorStop(1, "rgba(0, 170, 255, 0.0)");

    // Line
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = pad.left + (i / (data.length - 1)) * plotW;
      const y = pad.top + plotH - ((data[i] - min) / (max - min)) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = "#00aaff";
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();

    // Fill below
    const lastX = pad.left + plotW;
    ctx.lineTo(lastX, pad.top + plotH);
    ctx.lineTo(pad.left, pad.top + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Dots at last point
    const lastVal = data[data.length - 1];
    const lx = pad.left + plotW;
    const ly = pad.top + plotH - ((lastVal - min) / (max - min)) * plotH;
    ctx.beginPath();
    ctx.arc(lx, ly, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#00aaff";
    ctx.fill();
    ctx.strokeStyle = "#0a0a0f";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Label
    ctx.fillStyle = "#8888aa";
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = "right";
    ctx.fillText(Math.round(lastVal) + "ms", lx - 8, ly - 6);

    // Axis label
    ctx.fillStyle = "#555570";
    ctx.font = "9px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText("last " + data.length + " tests", W / 2, H - 4);
  }

  // --- Donut / Ring Chart (pass/fail/warn) ---

  function drawDonutChart() {
    const canvas = dom.donutCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    const total = stats.pass + stats.fail + stats.warn;
    if (total === 0) {
      ctx.fillStyle = "#555570";
      ctx.font = "12px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("No data", W / 2, H / 2);
      return;
    }

    const cx = W / 2;
    const cy = H / 2 - 4;
    const outerR = Math.min(W, H) / 2 - 14;
    const innerR = outerR * 0.62;

    const slices = [
      { value: stats.pass, color: "#00ff88", label: "Pass" },
      { value: stats.fail, color: "#ff3366", label: "Fail" },
      { value: stats.warn, color: "#ffaa00", label: "Warn" },
    ];

    let angle = -Math.PI / 2;
    slices.forEach(function (s) {
      if (s.value === 0) return;
      const sliceAngle = (s.value / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, angle, angle + sliceAngle);
      ctx.arc(cx, cy, innerR, angle + sliceAngle, angle, true);
      ctx.closePath();
      ctx.fillStyle = s.color;
      ctx.globalAlpha = 0.85;
      ctx.fill();
      ctx.globalAlpha = 1;
      angle += sliceAngle;
    });

    // Center text
    ctx.fillStyle = "#e8e8f0";
    ctx.font = "bold 18px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(stats.pass_rate + "%", cx, cy - 2);
    ctx.fillStyle = "#555570";
    ctx.font = "9px 'JetBrains Mono', monospace";
    ctx.fillText("PASS RATE", cx, cy + 14);
  }

  // --- Token Usage Bar Chart ---

  function drawTokenChart() {
    const canvas = dom.tokenCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    // Last 20 results
    const data = state.results.slice(0, 20).reverse();
    if (data.length === 0) {
      ctx.fillStyle = "#555570";
      ctx.font = "12px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("No data", W / 2, H / 2);
      return;
    }

    const pad = { top: 10, bottom: 20, left: 10, right: 10 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    const maxTokens = Math.max(...data.map(function (d) { return d.tokens_used; })) * 1.1 || 1;
    const barW = plotW / data.length;
    const gap = Math.max(2, barW * 0.2);

    // Grid
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = pad.top + (plotH / 3) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
    }

    const verdictColors = { PASS: "#00ff88", FAIL: "#ff3366", WARN: "#ffaa00" };

    data.forEach(function (d, i) {
      const barH = (d.tokens_used / maxTokens) * plotH;
      const x = pad.left + i * barW + gap / 2;
      const y = pad.top + plotH - barH;
      const w = barW - gap;

      ctx.fillStyle = verdictColors[d.verdict] || "#00aaff";
      ctx.globalAlpha = 0.7;
      ctx.beginPath();
      // Rounded top
      const r = Math.min(3, w / 2);
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, pad.top + plotH);
      ctx.lineTo(x, pad.top + plotH);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.fill();
      ctx.globalAlpha = 1;
    });

    // Label
    ctx.fillStyle = "#555570";
    ctx.font = "9px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText("last " + data.length + " tests", W / 2, H - 4);
  }

  // =========================================================================
  // Sound
  // =========================================================================

  function beepFail() {
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.type = "square";
      osc.frequency.value = 440;
      gain.gain.value = 0.08;
      osc.start();
      gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.2);
      osc.stop(ac.currentTime + 0.2);
    } catch (_) {
      // Audio not supported
    }
  }

  // =========================================================================
  // Filters
  // =========================================================================

  function setupFilters() {
    dom.filterBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const v = btn.dataset.verdict;
        state.filter = v;
        // Update active classes
        dom.filterBtns.forEach(function (b) {
          b.className = "filter-btn";
          if (b.dataset.verdict === v) {
            if (v === "PASS") b.classList.add("active-pass");
            else if (v === "FAIL") b.classList.add("active-fail");
            else if (v === "WARN") b.classList.add("active-warn");
            else b.classList.add("active");
          }
        });
        renderResults();
      });
    });

    dom.searchInput.addEventListener("input", function () {
      state.search = dom.searchInput.value;
      renderResults();
    });
  }

  function setupSound() {
    dom.soundBtn.addEventListener("click", function () {
      state.soundEnabled = !state.soundEnabled;
      dom.soundBtn.classList.toggle("active", state.soundEnabled);
      dom.soundBtn.textContent = state.soundEnabled ? "SND ON" : "SND OFF";
    });
  }

  // =========================================================================
  // Helpers
  // =========================================================================

  function escHtml(s) {
    if (!s) return "";
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // =========================================================================
  // Resize handling
  // =========================================================================

  let resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      drawLatencyChart();
      drawDonutChart();
      drawTokenChart();
    }, 150);
  });

  // =========================================================================
  // Keepalive
  // =========================================================================

  setInterval(function () {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send("ping");
    }
  }, 30000);

  // =========================================================================
  // Init
  // =========================================================================

  document.addEventListener("DOMContentLoaded", function () {
    cacheDom();
    setupFilters();
    setupSound();
    renderStats();
    renderResults();
    drawLatencyChart();
    drawDonutChart();
    drawTokenChart();
    connectWs();
  });

})();
