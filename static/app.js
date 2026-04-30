"use strict";

// ── DOM references ──────────────────────────────────────────────────────────
const logSelect        = document.getElementById("logSelect");
const cameraSelect     = document.getElementById("cameraSelect");
const renderBtn        = document.getElementById("renderBtn");
const videoPlayer      = document.getElementById("videoPlayer");
const videoPlaceholder = document.getElementById("videoPlaceholder");
const renderProgress   = document.getElementById("renderProgress");
const graphBtn         = document.getElementById("graphBtn");
const graphCanvas      = document.getElementById("graphCanvas");
const graphPlaceholder = document.getElementById("graphPlaceholder");
const dataSourceBadge  = document.getElementById("dataSourceBadge");

const statCity          = document.getElementById("statCity");
const statAvgComplexity = document.getElementById("statAvgComplexity");
const statMaxComplexity = document.getElementById("statMaxComplexity");
const statMinComplexity = document.getElementById("statMinComplexity");
const statFrames        = document.getElementById("statFrames");
const statVehicles      = document.getElementById("statVehicles");
const statPedestrians   = document.getElementById("statPedestrians");
const statCamera        = document.getElementById("statCamera");

let activeSSE = null;

// ── Check pre-generated data ─────────────────────────────────────────────────
async function checkScenarioData() {
  try {
    const res = await fetch("/api/scenario-data");
    const data = await res.json();
    if (data.length > 0) {
      dataSourceBadge.textContent = `${data.length} scenarios loaded`;
      dataSourceBadge.classList.add("ready");
      graphPlaceholder.innerHTML = `
        <div class="placeholder-icon small">📊</div>
        ${data.length} scenarios ready — select axes and click Generate.
      `;
    }
  } catch (_) {}
}

// ── Log list ──────────────────────────────────────────────────────────────────
async function loadLogs() {
  try {
    const res = await fetch("/api/logs");
    const logs = await res.json();
    logSelect.innerHTML = logs.length
      ? logs.map(l =>
          `<option value="${l.id}">${l.city} — ${l.id.substring(0, 8)}…</option>`
        ).join("")
      : `<option disabled>No logs found in train directory</option>`;
    if (logs.length) await loadCameras(logs[0].id);
  } catch (_) {
    logSelect.innerHTML = `<option disabled>Error loading logs</option>`;
  }
}

async function loadCameras(logId) {
  try {
    const res = await fetch(`/api/cameras/${encodeURIComponent(logId)}`);
    const cameras = await res.json();
    cameraSelect.innerHTML = cameras.map(c =>
      `<option value="${c}"${c === "ring_front_center" ? " selected" : ""}>${c}</option>`
    ).join("");
  } catch (_) {
    cameraSelect.innerHTML = `<option value="ring_front_center">ring_front_center</option>`;
  }
}

logSelect.addEventListener("change", () => loadCameras(logSelect.value));

// ── Render ────────────────────────────────────────────────────────────────────
function appendLog(text) {
  renderProgress.removeAttribute("hidden");
  renderProgress.textContent += text + "\n";
  renderProgress.scrollTop = renderProgress.scrollHeight;
}

renderBtn.addEventListener("click", () => {
  if (activeSSE) { activeSSE.close(); activeSSE = null; }

  const logId  = logSelect.value;
  const camera = cameraSelect.value;

  renderBtn.disabled = true;
  renderProgress.textContent = "";
  renderProgress.removeAttribute("hidden");
  videoPlayer.style.display = "none";
  videoPlaceholder.style.display = "flex";

  const url = `/api/render/${encodeURIComponent(logId)}?camera=${encodeURIComponent(camera)}`;
  activeSSE = new EventSource(url);

  activeSSE.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.line !== undefined) appendLog(data.line);

    if (data.done) {
      activeSSE.close(); activeSSE = null;
      renderBtn.disabled = false;
      appendLog("✓ Render complete.");
      const videoSrc = `/static/output/${encodeURIComponent(logId)}/video.mp4?t=${Date.now()}`;
      videoPlayer.src = videoSrc;
      videoPlayer.load();
      videoPlayer.style.display = "block";
      videoPlaceholder.style.display = "none";
      loadStats(logId, data.camera);
    }

    if (data.error) {
      activeSSE.close(); activeSSE = null;
      renderBtn.disabled = false;
      appendLog("✗ " + data.error);
    }
  };

  activeSSE.onerror = () => {
    if (activeSSE) { activeSSE.close(); activeSSE = null; }
    renderBtn.disabled = false;
    appendLog("✗ Connection lost.");
  };
});

// ── Stats ──────────────────────────────────────────────────────────────────
function fmt(val, decimals = 2) {
  return val != null ? Number(val).toFixed(decimals) : "—";
}

async function loadStats(logId, camera) {
  try {
    const res = await fetch(`/api/stats/${encodeURIComponent(logId)}`);
    if (!res.ok) return;
    const d = await res.json();
    statCity.textContent          = d.city || "—";
    statCamera.textContent        = d.camera_name || camera || "—";
    statAvgComplexity.textContent = fmt(d.average_complexity_score);
    statMaxComplexity.textContent = fmt(d.max_frame_complexity);
    statMinComplexity.textContent = fmt(d.min_frame_complexity);
    statFrames.textContent        = d.processed_frames ?? "—";
    statVehicles.textContent      = fmt(d.vehicle_count, 1);
    statPedestrians.textContent   = fmt(d.pedestrian_count, 1);
  } catch (_) {}
}

// ── Graph ──────────────────────────────────────────────────────────────────
const PALETTE = [
  "#a5b4fc", "#4ade80", "#fb923c", "#f0abfc",
  "#2dd4bf", "#fde68a", "#f87171", "#60a5fa",
];

function paletteFor(n) {
  const colors = [];
  for (let i = 0; i < n; i++) colors.push(PALETTE[i % PALETTE.length]);
  return colors;
}

function hexToRgba(hex, alpha) {
  const v = hex.replace("#", "");
  const r = parseInt(v.slice(0, 2), 16);
  const g = parseInt(v.slice(2, 4), 16);
  const b = parseInt(v.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

let chartInstance = null;

function showGraphError(msg) {
  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
  graphCanvas.setAttribute("hidden", "");
  graphCanvas.classList.remove("loaded");
  graphPlaceholder.style.display = "flex";
  graphPlaceholder.innerHTML = `
    <div class="placeholder-icon small">⚠</div>
    ${msg}
  `;
}

function renderChart(payload) {
  const { labels, values, counts, x_label, y_label, title } = payload;

  if (!labels || labels.length === 0) {
    showGraphError("No data yet — run <code>extract_data.py</code> or render a scenario first.");
    return;
  }

  const colors = paletteFor(labels.length);
  const bgColors = colors.map(c => hexToRgba(c, 0.55));
  const borderColors = colors;

  graphPlaceholder.style.display = "none";
  graphCanvas.removeAttribute("hidden");

  if (chartInstance) chartInstance.destroy();

  chartInstance = new Chart(graphCanvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: y_label,
        data: values,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1.5,
        borderRadius: 6,
        hoverBackgroundColor: colors,
        hoverBorderColor: "#ffffff",
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 500, easing: "easeOutQuart" },
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: title,
          color: "#a5b4fc",
          font: { size: 13, weight: "600", family: "ui-sans-serif, Inter, sans-serif" },
          padding: { top: 4, bottom: 12 },
        },
        tooltip: {
          backgroundColor: "rgba(28, 28, 33, 0.96)",
          borderColor: "rgba(165, 180, 252, 0.4)",
          borderWidth: 1,
          titleColor: "#f4f4f5",
          bodyColor: "#c4c4cc",
          padding: 10,
          cornerRadius: 6,
          displayColors: true,
          boxPadding: 4,
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed.y;
              const n = counts ? counts[ctx.dataIndex] : null;
              const formatted = Number.isInteger(v) ? v : v.toFixed(2);
              const suffix = n != null ? `   (n=${n})` : "";
              return `${y_label}: ${formatted}${suffix}`;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: x_label, color: "#8a8a96", font: { size: 11 } },
          ticks: { color: "#c4c4cc", font: { size: 11 } },
          grid: { display: false },
          border: { color: "rgba(255, 255, 255, 0.10)" },
        },
        y: {
          title: { display: true, text: y_label, color: "#8a8a96", font: { size: 11 } },
          ticks: { color: "#c4c4cc", font: { size: 11 } },
          grid: { color: "rgba(255, 255, 255, 0.06)" },
          border: { color: "rgba(255, 255, 255, 0.10)" },
          beginAtZero: true,
        },
      },
    },
  });

  requestAnimationFrame(() => graphCanvas.classList.add("loaded"));
}

graphBtn.addEventListener("click", async () => {
  const x = document.getElementById("xAxisSelect").value;
  const y = document.getElementById("yAxisSelect").value;
  const url = `/api/graph?x=${x}&y=${y}&t=${Date.now()}`;

  graphCanvas.classList.remove("loaded");

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderChart(data);
  } catch (_) {
    showGraphError("No data yet — run <code>extract_data.py</code> or render a scenario first.");
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadLogs();
checkScenarioData();
