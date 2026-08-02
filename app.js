const state = { samples: [], current: -1 };
const $ = (id) => document.getElementById(id);
const ui = {
  pathInput: $("pathInput"),
  fileInput: $("fileInput"),
  runPath: $("runPath"),
  runUpload: $("runUpload"),
  sampleList: $("sampleList"),
  status: $("status"),
  title: $("title"),
  rate: $("rate"),
  r2: $("r2"),
  points: $("points"),
  plot: $("plot"),
  pickStart: $("pickStart"),
  pickEnd: $("pickEnd"),
  startIndex: $("startIndex"),
  endIndex: $("endIndex"),
  xMin: $("xMin"),
  xMax: $("xMax"),
  yMin: $("yMin"),
  yMax: $("yMax"),
  applyAxis: $("applyAxis"),
  resetAxis: $("resetAxis"),
  saveManual: $("saveManual"),
  exportPng: $("exportPng"),
  message: $("message"),
};

function msg(text) { ui.message.textContent = text; }
function sample() { return state.samples[state.current] || null; }

function requireServer() {
  if (window.location.protocol === "file:") {
    throw new Error("Start the server with start_oxygen_rate_web.bat, then open http://127.0.0.1:8765. Opening index.html directly cannot upload or fit files.");
  }
}

async function postJson(url, payload) {
  requireServer();
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function processPath() {
  try {
    msg("Processing...");
    const data = await postJson("/api/process-path", { path: ui.pathInput.value.trim() });
    loadSamples(data.samples || []);
    msg(`Done ${data.ok_count}/${data.total_count}`);
  } catch (err) {
    msg(err.message);
  }
}

async function uploadFiles() {
  try {
    requireServer();
    const files = Array.from(ui.fileInput.files || []);
    if (!files.length) return;
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    msg("Uploading and fitting...");
    const res = await fetch("/api/upload", { method: "POST", body });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Upload failed");
    loadSamples(data.samples || []);
    msg(`Done ${data.ok_count}/${data.total_count}`);
  } catch (err) {
    msg(err.message);
  }
}

function loadSamples(samples) {
  state.samples = samples;
  state.current = samples.length ? 0 : -1;
  renderList();
  selectSample(state.current);
}

function renderList() {
  ui.sampleList.innerHTML = "";
  state.samples.forEach((s, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `sample${i === state.current ? " active" : ""}`;
    b.innerHTML = `<div><div class="sample-name">${esc(s.sample || s.name)}</div><div class="sample-rate">${esc(s.oxygen_rate_umol_L_s || s.error || "")}</div></div><span class="pill ${s.status}">${s.status}</span>`;
    b.onclick = () => selectSample(i);
    ui.sampleList.appendChild(b);
  });
}

function selectSample(i) {
  state.current = i;
  renderList();
  const s = sample();
  if (!s) {
    ui.title.textContent = "No sample selected";
    ui.status.textContent = "Waiting for input";
    ui.rate.textContent = "--";
    ui.r2.textContent = "--";
    ui.points.textContent = "--";
    draw();
    return;
  }
  initializeSelection(s);
  syncInputsFromSelection();
  syncAxisInputs();
  updateMetrics(s);
  draw();
}

function updateMetrics(s, fit = null) {
  const f = fit || s;
  ui.title.textContent = s.sample || s.name || "TXT";
  ui.status.textContent = s.status === "ok" ? "Fitted" : "Manual selection available";
  ui.rate.textContent = f.oxygen_rate_umol_L_s || "--";
  ui.r2.textContent = f.r2 || "--";
  ui.points.textContent = f.fit_points || "--";
}

function cleanIndices(indices, max) {
  return [...new Set((indices || [])
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value) && value >= 0 && value <= max))]
    .sort((a, b) => a - b);
}

function sameIndices(a, b) {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

function rangeIndices(start, end) {
  const [a, b] = start <= end ? [start, end] : [end, start];
  return Array.from({ length: b - a + 1 }, (_, offset) => a + offset);
}

function continuousIndices(indices, max) {
  const cleaned = cleanIndices(indices, max);
  if (cleaned.length <= 1) return cleaned;
  return rangeIndices(cleaned[0], cleaned[cleaned.length - 1]);
}

function initialSelectedIndices(s) {
  const max = Math.max(0, (s.rows || []).length - 1);
  if (Array.isArray(s.fit_selected_indices) && s.fit_selected_indices.length) {
    return continuousIndices(s.fit_selected_indices, max);
  }
  if (Number.isInteger(s.fit_start_index) && Number.isInteger(s.fit_end_index)) {
    return continuousIndices(rangeIndices(s.fit_start_index, s.fit_end_index), max);
  }
  return [];
}

function initializeSelection(s) {
  if (!Array.isArray(s.selected_indices)) {
    s.selected_indices = initialSelectedIndices(s);
  }
}

function selectedIndices() {
  const s = sample();
  if (!s) return [];
  initializeSelection(s);
  const max = Math.max(0, s.rows.length - 1);
  const normalized = continuousIndices(s.selected_indices, max);
  if (!sameIndices(normalized, s.selected_indices)) {
    s.selected_indices = normalized;
  }
  return s.selected_indices;
}

function selectedPoints() {
  const s = sample();
  if (!s || !s.rows?.length) return [];
  return selectedIndices().map((index) => s.rows[index]).filter(Boolean);
}

function inputRange() {
  const s = sample();
  const max = s ? Math.max(0, s.rows.length - 1) : 0;
  let a = parseInt(ui.startIndex.value, 10);
  let b = parseInt(ui.endIndex.value, 10);
  if (!Number.isFinite(a)) a = 0;
  if (!Number.isFinite(b)) b = a;
  a = Math.max(0, Math.min(max, a));
  b = Math.max(0, Math.min(max, b));
  return a <= b ? [a, b] : [b, a];
}

function syncInputsFromSelection() {
  const s = sample();
  const max = s ? Math.max(0, s.rows.length - 1) : 0;
  ui.startIndex.max = String(max);
  ui.endIndex.max = String(max);
  const indices = selectedIndices();
  if (indices.length) {
    ui.startIndex.value = indices[0];
    ui.endIndex.value = indices[indices.length - 1];
  } else {
    ui.startIndex.value = 0;
    ui.endIndex.value = Math.min(4, max);
  }
}

function setSelection(indices, quiet = false) {
  const s = sample();
  if (!s) return;
  const max = Math.max(0, s.rows.length - 1);
  s.selected_indices = continuousIndices(indices, max);
  syncInputsFromSelection();
  draw();
  if (!quiet) msg(`${s.selected_indices.length} point(s) selected`);
}

function selectRangeFromInputs() {
  const [a, b] = inputRange();
  setSelection(rangeIndices(a, b), true);
  msg(`Selected ${b - a + 1} point(s) by range`);
}

function clearManualSelection() {
  setSelection([], true);
  msg("Selection cleared");
}

function togglePoint(index) {
  const indices = selectedIndices();
  const exists = indices.includes(index);
  let next;
  if (!exists) {
    next = indices.length
      ? rangeIndices(Math.min(indices[0], index), Math.max(indices[indices.length - 1], index))
      : [index];
  } else if (indices.length === 1) {
    next = [];
  } else if (index === indices[0]) {
    next = rangeIndices(index + 1, indices[indices.length - 1]);
  } else if (index === indices[indices.length - 1]) {
    next = rangeIndices(indices[0], index - 1);
  } else {
    const leftCount = index - indices[0];
    const rightCount = indices[indices.length - 1] - index;
    next = leftCount <= rightCount
      ? rangeIndices(index + 1, indices[indices.length - 1])
      : rangeIndices(indices[0], index - 1);
  }
  setSelection(next, true);
  msg(`${exists ? "Deselected" : "Selected"} point ${index}. ${selectedIndices().length} point(s) selected`);
}

function fitManual() {
  const pts = selectedPoints();
  if (pts.length < 2) return null;
  const n = pts.length;
  const xm = pts.reduce((sum, p) => sum + p[0], 0) / n;
  const ym = pts.reduce((sum, p) => sum + p[1], 0) / n;
  const ssxx = pts.reduce((sum, p) => sum + (p[0] - xm) ** 2, 0);
  if (!ssxx) return null;
  const slope = pts.reduce((sum, p) => sum + (p[0] - xm) * (p[1] - ym), 0) / ssxx;
  const intercept = ym - slope * xm;
  const ssr = pts.reduce((sum, p) => sum + (p[1] - (slope * p[0] + intercept)) ** 2, 0);
  const sst = pts.reduce((sum, p) => sum + (p[1] - ym) ** 2, 0);
  const r2 = sst === 0 ? 1 : 1 - ssr / sst;
  return {
    slope,
    intercept,
    oxygen_rate_umol_L_s: (-slope).toFixed(4),
    r2: r2.toFixed(4),
    fit_points: String(n),
  };
}

function numericInputValue(input) {
  const value = Number(input.value);
  return Number.isFinite(value) ? value : null;
}

function cleanAxisLimits(limits = {}) {
  const cleaned = {};
  ["xmin", "xmax", "ymin", "ymax"].forEach((key) => {
    const value = Number(limits[key]);
    if (Number.isFinite(value)) cleaned[key] = value;
  });
  return cleaned;
}

function readAxisInputs() {
  return cleanAxisLimits({
    xmin: numericInputValue(ui.xMin),
    xmax: numericInputValue(ui.xMax),
    ymin: numericInputValue(ui.yMin),
    ymax: numericInputValue(ui.yMax),
  });
}

function syncAxisInputs() {
  const limits = sample()?.axis_limits || {};
  ui.xMin.value = Number.isFinite(limits.xmin) ? limits.xmin : "";
  ui.xMax.value = Number.isFinite(limits.xmax) ? limits.xmax : "";
  ui.yMin.value = Number.isFinite(limits.ymin) ? limits.ymin : "";
  ui.yMax.value = Number.isFinite(limits.ymax) ? limits.ymax : "";
}

function applyAxisLimits(quiet = false) {
  const s = sample();
  if (!s) return;
  s.axis_limits = readAxisInputs();
  draw();
  if (!quiet) msg("Axis range updated");
}

function resetAxisLimits() {
  const s = sample();
  if (!s) return;
  s.axis_limits = {};
  syncAxisInputs();
  draw();
  msg("Automatic axis range restored");
}

function axisLimitsForSave() {
  const limits = cleanAxisLimits(sample()?.axis_limits || {});
  return Object.keys(limits).length ? limits : null;
}

function plotGeometry(rows, rect, limits = {}) {
  const xs = rows.map((p) => p[0]);
  const ys = rows.map((p) => p[1]);
  const autoXmin = Math.min(...xs), autoXmax = Math.max(...xs);
  const ymin0 = Math.min(...ys), ymax0 = Math.max(...ys);
  const ypad = Math.max(3, (ymax0 - ymin0) * 0.08);
  const autoYmin = ymin0 - ypad, autoYmax = ymax0 + ypad;
  let xmin = Number.isFinite(limits.xmin) ? limits.xmin : autoXmin;
  let xmax = Number.isFinite(limits.xmax) ? limits.xmax : autoXmax;
  let ymin = Number.isFinite(limits.ymin) ? limits.ymin : autoYmin;
  let ymax = Number.isFinite(limits.ymax) ? limits.ymax : autoYmax;
  if (!(xmax > xmin)) {
    xmin = autoXmin;
    xmax = autoXmax;
  }
  if (!(ymax > ymin)) {
    ymin = autoYmin;
    ymax = autoYmax;
  }
  const pad = { l: 64, r: 24, t: 26, b: 52 };
  const w = Math.max(1, rect.width - pad.l - pad.r);
  const h = Math.max(1, rect.height - pad.t - pad.b);
  return {
    xmin,
    xmax,
    ymin,
    ymax,
    pad,
    w,
    h,
    sx: (x) => pad.l + ((x - xmin) / Math.max(1e-9, xmax - xmin)) * w,
    sy: (y) => pad.t + (1 - (y - ymin) / Math.max(1e-9, ymax - ymin)) * h,
  };
}

function draw() {
  const canvas = ui.plot;
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(760, Math.round(rect.width * dpr));
  canvas.height = Math.max(430, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const s = sample();
  if (!s || !s.rows?.length) return;

  const rows = s.rows;
  const g = plotGeometry(rows, rect, s.axis_limits || {});
  const { xmin, xmax, ymin, ymax, pad, w, h, sx, sy } = g;

  ctx.strokeStyle = "#d8e1e6";
  ctx.lineWidth = 1;
  ctx.font = "12px Segoe UI, Arial";
  ctx.fillStyle = "#65747d";
  for (let i = 0; i <= 5; i++) {
    const x = pad.l + (w * i) / 5;
    const y = pad.t + (h * i) / 5;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + w, y); ctx.stroke();
    ctx.fillText((xmin + (xmax - xmin) * i / 5).toFixed(0), x - 8, pad.t + h + 22);
    ctx.fillText((ymax - (ymax - ymin) * i / 5).toFixed(0), 18, y + 4);
  }

  ctx.strokeStyle = "#172126";
  ctx.strokeRect(pad.l, pad.t, w, h);

  ctx.save();
  ctx.beginPath();
  ctx.rect(pad.l, pad.t, w, h);
  ctx.clip();

  ctx.beginPath();
  rows.forEach((p, i) => i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1])));
  ctx.strokeStyle = "#286f96";
  ctx.lineWidth = 1.6;
  ctx.stroke();

  ctx.fillStyle = "#286f96";
  rows.forEach((p) => {
    ctx.beginPath();
    ctx.arc(sx(p[0]), sy(p[1]), 2.2, 0, Math.PI * 2);
    ctx.fill();
  });

  const indices = selectedIndices();
  const fit = fitManual();
  ctx.fillStyle = "#d98528";
  indices.forEach((index) => {
    const p = rows[index];
    if (!p) return;
    ctx.beginPath();
    ctx.arc(sx(p[0]), sy(p[1]), 4.8, 0, Math.PI * 2);
    ctx.fill();
  });

  if (fit && indices.length >= 2) {
    const first = rows[indices[0]];
    const last = rows[indices[indices.length - 1]];
    ctx.beginPath();
    ctx.moveTo(sx(first[0]), sy(fit.slope * first[0] + fit.intercept));
    ctx.lineTo(sx(last[0]), sy(fit.slope * last[0] + fit.intercept));
    ctx.strokeStyle = "#ba2b22";
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.restore();
    updateMetrics(s, fit);
  } else {
    ctx.restore();
    updateMetrics(s, {
      oxygen_rate_umol_L_s: "",
      r2: "",
      fit_points: indices.length ? String(indices.length) : "",
    });
  }
}

function nearestIndex(ev) {
  const s = sample();
  if (!s?.rows?.length) return null;
  const rect = ui.plot.getBoundingClientRect();
  const g = plotGeometry(s.rows, rect, s.axis_limits || {});
  const x = ev.clientX - rect.left;
  const y = ev.clientY - rect.top;
  let best = null;
  let dist = Infinity;
  s.rows.forEach((p, i) => {
    const px = g.sx(p[0]);
    const py = g.sy(p[1]);
    if (px < g.pad.l - 6 || px > g.pad.l + g.w + 6 || py < g.pad.t - 6 || py > g.pad.t + g.h + 6) {
      return;
    }
    const dx = px - x;
    const dy = py - y;
    const d = Math.hypot(dx, dy);
    if (d < dist) { dist = d; best = i; }
  });
  return dist <= 18 ? best : null;
}

async function saveManual() {
  const s = sample();
  if (!s) return;
  try {
    requireServer();
  } catch (err) {
    msg(err.message);
    return;
  }

  const indices = selectedIndices();
  const n = indices.length;
  if (n < 3) { msg("Save manual fit needs at least 3 selected fit points"); return; }
  try {
    msg("Saving...");
    const axisLimits = axisLimitsForSave();
    const data = await postJson("/api/refit", {
      file_path: s.input_file,
      selected_indices: indices,
      start_index: indices[0],
      end_index: indices[indices.length - 1],
      axis_limits: axisLimits,
    });
    data.sample.axis_limits = axisLimits || {};
    state.samples[state.current] = data.sample;
    selectSample(state.current);
    msg("Manual fit saved");
  } catch (err) {
    msg(err.message);
  }
}

function manualPayload(s, indices, axisLimits, downloadPng = false) {
  return {
    file_path: s.input_file,
    selected_indices: indices,
    start_index: indices[0],
    end_index: indices[indices.length - 1],
    axis_limits: axisLimits,
    download_png: downloadPng,
  };
}

function plotPathFromSample(s) {
  if (s?.plot_path) return s.plot_path;
  return "system Downloads folder";
}

async function exportPng() {
  const s = sample();
  if (!s) return;
  try {
    requireServer();
  } catch (err) {
    msg(err.message);
    return;
  }

  const indices = selectedIndices();
  const n = indices.length;
  if (n < 3) { msg("PNG export needs at least 3 selected fit points"); return; }
  try {
    msg("Exporting PNG...");
    const axisLimits = axisLimitsForSave();
    const data = await postJson("/api/export-png", {
      file_path: s.input_file,
      selected_indices: indices,
      axis_limits: axisLimits,
    });
    msg(`PNG exported: ${data.plot_path || plotPathFromSample(s)}`);
  } catch (err) {
    if (/Unknown endpoint/i.test(err.message)) {
      msg("PNG export endpoint is not active. Close the old server and restart start_oxygen_rate_web.bat.");
    } else {
      msg(err.message);
    }
  }
}

function esc(v) {
  return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

ui.runPath.onclick = processPath;
ui.runUpload.onclick = uploadFiles;
ui.pickStart.onclick = selectRangeFromInputs;
ui.pickEnd.onclick = clearManualSelection;
ui.plot.onclick = (ev) => {
  const i = nearestIndex(ev);
  if (i === null) {
    msg("Click near a data point");
    return;
  }
  togglePoint(i);
};
ui.startIndex.onchange = selectRangeFromInputs;
ui.endIndex.onchange = selectRangeFromInputs;
ui.applyAxis.onclick = () => applyAxisLimits(false);
ui.resetAxis.onclick = resetAxisLimits;
[ui.xMin, ui.xMax, ui.yMin, ui.yMax].forEach((input) => {
  input.onchange = () => applyAxisLimits(true);
});
ui.saveManual.onclick = saveManual;
ui.exportPng.onclick = exportPng;
window.onresize = draw;
if (window.location.protocol === "file:") {
  msg("Start the server with start_oxygen_rate_web.bat, then open http://127.0.0.1:8765. Opening index.html directly can show the page, but cannot upload or fit files.");
}
