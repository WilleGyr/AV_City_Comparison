"use strict";

// ── DOM references ──────────────────────────────────────────────────────────
const logSelect        = document.getElementById("logSelect");
const cameraSelect     = document.getElementById("cameraSelect");
const renderBtn        = document.getElementById("renderBtn");
const playBtn          = document.getElementById("playBtn");
const stopBtn          = document.getElementById("stopBtn");
const videoPlayer      = document.getElementById("videoPlayer");
const videoPlaceholder = document.getElementById("videoPlaceholder");
const renderProgress   = document.getElementById("renderProgress");
const graphBtn         = document.getElementById("graphBtn");
const graphImg         = document.getElementById("graphImg");
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

// ── Video controls ─────────────────────────────────────────────────────────
playBtn.addEventListener("click", () => { if (videoPlayer.src) videoPlayer.play(); });
stopBtn.addEventListener("click", () => { videoPlayer.pause(); videoPlayer.currentTime = 0; });

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
graphBtn.addEventListener("click", () => {
  const x = document.getElementById("xAxisSelect").value;
  const y = document.getElementById("yAxisSelect").value;
  const url = `/api/graph?x=${x}&y=${y}&t=${Date.now()}`;

  graphImg.classList.remove("loaded");
  graphImg.removeAttribute("hidden");
  graphPlaceholder.style.display = "none";

  const img = new Image();
  img.onload = () => {
    graphImg.src = img.src;
    graphImg.classList.add("loaded");
  };
  img.onerror = () => {
    graphImg.setAttribute("hidden", "");
    graphPlaceholder.style.display = "flex";
    graphPlaceholder.innerHTML = `
      <div class="placeholder-icon small">⚠</div>
      No data yet — run <code>extract_data.py</code> or render a scenario first.
    `;
  };
  img.src = url;
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadLogs();
checkScenarioData();
