const frequencyState = {
  schemes: [],
  currentScheme: "",
  resultFiles: [],
  selectedResultFile: "",
  status: null,
  pollTimer: null,
  activeResultTab: "metrics",
};

const FREQUENCY_SELECTION_STORAGE_KEY = "powerPlanFrequencySelection";

document.addEventListener("DOMContentLoaded", () => {
  bindFrequencyActions();
  bindFrequencyTabs();
  loadFrequencyPage().catch(showFrequencyError);
});

async function loadFrequencyPage() {
  const remembered = readStoredJson(FREQUENCY_SELECTION_STORAGE_KEY, {});
  frequencyState.schemes = (await frequencyApi("/api/planning/schemes")).schemes || [];
  if (remembered.scheme && frequencyState.schemes.some((scheme) => scheme.name === remembered.scheme)) {
    frequencyState.currentScheme = remembered.scheme;
  } else if (frequencyState.schemes.length) {
    frequencyState.currentScheme = frequencyState.schemes[0].name;
  }
  renderFrequencySchemes();
  await loadFrequencyResults(remembered.result || "");
  await refreshFrequencyStatus();
}

async function frequencyApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.error || "请求失败");
    error.payload = data;
    throw error;
  }
  return data;
}

function bindFrequencyActions() {
  document.getElementById("frequencyResultSelect")?.addEventListener("change", async (event) => {
    frequencyState.selectedResultFile = event.target.value || "";
    rememberFrequencySelection();
    renderFrequencyCurrentLabel();
    await refreshFrequencyStatus();
  });
  document.getElementById("startFrequency")?.addEventListener("click", () => controlFrequency("start"));
  document.getElementById("queueFrequency")?.addEventListener("click", () => controlFrequency("queue"));
  document.getElementById("stopFrequency")?.addEventListener("click", () => controlFrequency(terminalFrequencyAction()));
}

function bindFrequencyTabs() {
  const buttons = Array.from(document.querySelectorAll("[data-result-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-result-panel]"));
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.resultTab || "metrics";
      frequencyState.activeResultTab = target;
      buttons.forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-selected", String(active));
      });
      panels.forEach((panel) => {
        const active = panel.dataset.resultPanel === target;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
    });
  });
}

function renderFrequencySchemes() {
  const list = document.getElementById("schemeList");
  if (!list) return;
  if (!frequencyState.schemes.length) {
    list.innerHTML = '<div class="validation-item">暂无方案，请先在参数维护中新建方案。</div>';
    return;
  }
  list.innerHTML = `<ul class="scheme-list-items" role="listbox">${frequencyState.schemes
    .map((scheme) => `<li class="scheme-item ${scheme.name === frequencyState.currentScheme ? "active" : ""}" data-name="${escapeHtml(scheme.name)}" role="option" aria-selected="${scheme.name === frequencyState.currentScheme ? "true" : "false"}" tabindex="0">${escapeHtml(scheme.name)}</li>`)
    .join("")}</ul>`;
  list.querySelectorAll(".scheme-item").forEach((item) => {
    const selectScheme = async () => {
      frequencyState.currentScheme = item.dataset.name || "";
      frequencyState.selectedResultFile = "";
      renderFrequencySchemes();
      await loadFrequencyResults();
      await refreshFrequencyStatus();
    };
    item.addEventListener("click", () => selectScheme().catch(showFrequencyError));
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectScheme().catch(showFrequencyError);
      }
    });
  });
}

async function loadFrequencyResults(preferred = frequencyState.selectedResultFile) {
  const select = document.getElementById("frequencyResultSelect");
  if (!frequencyState.currentScheme) {
    frequencyState.resultFiles = [];
    frequencyState.selectedResultFile = "";
    renderFrequencyResults();
    return;
  }
  const selectedParam = preferred ? `&filename=${encodeURIComponent(preferred)}` : "";
  const data = await frequencyApi(`/api/evaluation/results?scheme=${encodeURIComponent(frequencyState.currentScheme)}${selectedParam}`);
  frequencyState.resultFiles = data.results || [];
  const readableNames = frequencyState.resultFiles.filter((item) => item.readable !== false).map((item) => item.name);
  frequencyState.selectedResultFile = data.selected || (readableNames.includes(preferred) ? preferred : readableNames[0] || "");
  if (select) select.value = frequencyState.selectedResultFile;
  rememberFrequencySelection();
  renderFrequencyResults();
  renderFrequencyCurrentLabel();
}

function renderFrequencyResults() {
  const select = document.getElementById("frequencyResultSelect");
  if (!select) return;
  if (!frequencyState.resultFiles.length) {
    select.innerHTML = '<option value="">暂无结果文件</option>';
  } else {
    const placeholder = frequencyState.selectedResultFile ? "" : '<option value="">暂无可读取结果文件</option>';
    select.innerHTML = placeholder + frequencyState.resultFiles.map(renderFrequencyResultOption).join("");
  }
  select.value = frequencyState.selectedResultFile;
  renderFrequencyResultWarnings();
}

function renderFrequencyResultOption(item) {
  const unreadable = item.readable === false;
  const label = `${resultDisplayName(item.name)}${unreadable ? "（无法读取）" : ""}`;
  return `<option value="${escapeHtml(item.name)}">${escapeHtml(label)}</option>`;
}

function renderFrequencyResultWarnings() {
  const host = document.getElementById("frequencyResultWarnings");
  if (!host) return;
  const unreadable = frequencyState.resultFiles.filter((item) => item.readable === false);
  host.innerHTML = unreadable
    .map((item) => `<div class="validation-item error">结果文件 ${escapeHtml(item.name)} ${escapeHtml(item.message || "无法读取，请重新生成或删除该文件。")}</div>`)
    .join("");
  host.hidden = unreadable.length === 0;
}

async function refreshFrequencyStatus() {
  const data = await frequencyApi(frequencyStatusPath());
  frequencyState.status = data;
  renderFrequencyStatus(data);
  scheduleFrequencyPolling();
}

function frequencyStatusPath() {
  if (!frequencyState.currentScheme) return "/api/frequency/status?light=1";
  const filenameParam = frequencyState.selectedResultFile ? `&filename=${encodeURIComponent(frequencyState.selectedResultFile)}` : "";
  return `/api/frequency/status?scheme=${encodeURIComponent(frequencyState.currentScheme)}${filenameParam}&light=1`;
}

async function controlFrequency(action) {
  if (!frequencyState.currentScheme) {
    alert("请先选择方案");
    return;
  }
  if (!frequencyState.selectedResultFile) {
    alert("请先选择结果文件");
    return;
  }
  try {
    await frequencyApi("/api/tasks/control", {
      method: "POST",
      body: JSON.stringify({
        action,
        task_type: "frequency",
        scheme: frequencyState.currentScheme,
        result: frequencyState.selectedResultFile,
      }),
    });
    await refreshFrequencyStatus();
  } catch (error) {
    const data = error.payload || {};
    if (data.message) alert(data.message);
    else showFrequencyError(error);
    await refreshFrequencyStatus().catch(() => null);
  }
}

function renderFrequencyStatus(data) {
  renderFrequencyCurrentLabel();
  updateFrequencyActions(data);
  const metrics = Array.isArray(data.metrics) ? data.metrics : [];
  setText("frequencyStatus", metricValue(metrics, "状态", data.task_status || data.status || "-"));
  setText("frequencyStartTime", metricValue(metrics, "开始", data.start_time || "-"));
  setText("frequencyEndTime", metricValue(metrics, "完成", data.end_time || "-"));
  setText("frequencyMin", formatFrequency(metricValue(metrics, "最低频率", "-")));
  setText("frequencyMax", formatFrequency(metricValue(metrics, "最高频率", "-")));
  renderFrequencySummaryTable(data.summary || []);
  renderFrequencyMetricsTable(data.frequency_table || []);
  renderFrequencyCurve(data.curves?.safety_daily || []);
  renderFrequencyLogs(data.logs || []);
  translateNode(document.body);
}

function renderFrequencySummaryTable(rows) {
  const target = document.getElementById("frequencySummaryTable");
  if (!target) return;
  const normalized = Array.isArray(rows) ? rows : [];
  if (!normalized.length) {
    target.innerHTML = '<div class="empty-summary">暂无频率摘要</div>';
    return;
  }
  target.innerHTML = renderSimpleTable(normalized);
}

function renderFrequencyMetricsTable(rows) {
  const target = document.getElementById("frequencyMetricsTable");
  if (!target) return;
  const normalized = Array.isArray(rows) ? rows : [];
  if (!normalized.length) {
    target.innerHTML = '<div class="empty-summary">暂无频率计算指标</div>';
    return;
  }
  target.innerHTML = renderSimpleTable(normalized);
}

function renderSimpleTable(rows) {
  const columns = Array.from(rows.reduce((set, row) => {
    Object.keys(row || {}).forEach((key) => set.add(key));
    return set;
  }, new Set()));
  return `
    <table>
      <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row?.[column] ?? "")}</td>`).join("")}</tr>`).join("")}
      </tbody>
    </table>`;
}

function renderFrequencyCurve(points) {
  const target = document.getElementById("frequencyCurveChart");
  if (!target) return;
  const rows = Array.isArray(points) ? points.filter((point) => Number.isFinite(Number(point.frequency_max)) && Number.isFinite(Number(point.frequency_min))) : [];
  if (!rows.length) {
    target.innerHTML = '<div class="empty-summary">暂无频率日曲线</div>';
    return;
  }
  const width = 1000;
  const height = 330;
  const margin = { top: 28, right: 26, bottom: 34, left: 64 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const minValue = Math.min(49.5, ...rows.map((point) => Number(point.frequency_min)));
  const maxValue = Math.max(50.5, ...rows.map((point) => Number(point.frequency_max)));
  const yMin = Math.floor((minValue - 0.05) * 10) / 10;
  const yMax = Math.ceil((maxValue + 0.05) * 10) / 10;
  const xAt = (index) => margin.left + (rows.length <= 1 ? 0 : (index / (rows.length - 1)) * plotWidth);
  const yAt = (value) => margin.top + ((yMax - value) / Math.max(0.001, yMax - yMin)) * plotHeight;
  const maxPath = linePath(rows, (point) => Number(point.frequency_max), xAt, yAt);
  const minPath = linePath(rows, (point) => Number(point.frequency_min), xAt, yAt);
  const ticks = [yMax, 50.5, 50.0, 49.5, yMin].filter((value, index, list) => list.indexOf(value) === index);
  target.innerHTML = `
    <svg class="safety-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="频率计算日曲线">
      ${ticks.map((tick) => `<line class="safety-grid-line" x1="${margin.left}" y1="${yAt(tick).toFixed(2)}" x2="${width - margin.right}" y2="${yAt(tick).toFixed(2)}"></line><text class="safety-tick-label" x="${margin.left - 8}" y="${(yAt(tick) + 4).toFixed(2)}">${escapeHtml(tick.toFixed(1))}</text>`).join("")}
      <line class="safety-axis-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
      <line class="safety-center-line" x1="${margin.left}" y1="${yAt(50).toFixed(2)}" x2="${width - margin.right}" y2="${yAt(50).toFixed(2)}"></line>
      <path class="safety-frequency-line up" d="${maxPath}"></path>
      <path class="safety-frequency-line down" d="${minPath}"></path>
      ${renderDayTicks(rows, xAt, height - margin.bottom)}
    </svg>
    <div class="safety-chart-legend">
      <button type="button"><i style="background:#c7504a"></i>最高频率</button>
      <button type="button"><i style="background:#4d7fd1"></i>最低频率</button>
    </div>`;
}

function renderDayTicks(rows, xAt, bottomY) {
  const step = Math.max(1, Math.floor(rows.length / 6));
  return rows
    .map((point, index) => ({ point, index }))
    .filter(({ index }) => index === 0 || index === rows.length - 1 || index % step === 0)
    .map(({ point, index }) => {
      const x = xAt(index);
      return `<line class="safety-x-tick" x1="${x.toFixed(2)}" y1="${bottomY - 4}" x2="${x.toFixed(2)}" y2="${bottomY}"></line><text class="safety-x-label" x="${x.toFixed(2)}" y="${bottomY + 16}">${escapeHtml(point.day ?? index + 1)}</text>`;
    })
    .join("");
}

function linePath(points, accessor, xAt, yAt) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index).toFixed(2)} ${yAt(accessor(point)).toFixed(2)}`).join(" ");
}

function renderFrequencyLogs(logs) {
  const target = document.getElementById("frequencyLogs");
  if (!target) return;
  const rows = Array.isArray(logs) ? logs : [];
  target.innerHTML = rows.length
    ? rows.map((log) => `<div class="log-line ${escapeHtml(log.level || "info")}"><span>${escapeHtml(log.time || "")}</span><strong>${escapeHtml(log.message || "")}</strong></div>`).join("")
    : '<div class="log-line info"><strong>暂无评估日志</strong></div>';
  target.scrollTop = target.scrollHeight;
}

function updateFrequencyActions(data = {}) {
  const hasSelection = Boolean(frequencyState.currentScheme && frequencyState.selectedResultFile);
  const startButton = document.getElementById("startFrequency");
  const queueButton = document.getElementById("queueFrequency");
  const stopButton = document.getElementById("stopFrequency");
  if (!startButton || !queueButton || !stopButton) return;
  startButton.disabled = !hasSelection || data.can_start_task === false;
  queueButton.disabled = !hasSelection || data.can_queue_task === false;
  stopButton.disabled = !hasSelection || !data.can_stop_task;
  stopButton.textContent = data.can_cancel_queue_task ? "离队" : "停止";
}

function terminalFrequencyAction() {
  return frequencyState.status?.can_cancel_queue_task ? "cancel_queue" : "stop";
}

function scheduleFrequencyPolling() {
  if (frequencyState.pollTimer) window.clearInterval(frequencyState.pollTimer);
  const data = frequencyState.status || {};
  const delay = data.status === "运行中" || data.task_status === "排队中" ? 1000 : 4000;
  frequencyState.pollTimer = window.setInterval(() => {
    refreshFrequencyStatus().catch(showFrequencyError);
  }, delay);
}

function renderFrequencyCurrentLabel() {
  const schemeName = frequencyState.currentScheme || "未选择方案";
  const resultName = resultDisplayName(frequencyState.selectedResultFile) || "未选择结果";
  setText("frequencyCurrentScheme", `当前: ${schemeName}/${resultName}`);
}

function metricValue(metrics, label, fallback = "-") {
  const item = metrics.find((metric) => metric && metric.label === label);
  return item?.value ?? fallback;
}

function setText(id, value) {
  const target = document.getElementById(id);
  if (target) target.textContent = value ?? "-";
}

function formatFrequency(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(3)} Hz` : String(value || "-");
}

function resultDisplayName(filename) {
  return String(filename || "").replace(/_results\.xlsx$/i, "");
}

function rememberFrequencySelection() {
  writeStoredJson(FREQUENCY_SELECTION_STORAGE_KEY, {
    scheme: frequencyState.currentScheme || "",
    result: frequencyState.selectedResultFile || "",
  });
}

function readStoredJson(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (error) {
    return fallback;
  }
}

function writeStoredJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    // 本地记忆失败不影响评估流程。
  }
}

function showFrequencyError(error) {
  const message = error?.payload?.message || error?.message || "请求失败";
  renderFrequencyLogs([{ time: "", level: "error", message }]);
}

function translateNode(target) {
  if (window.PowerPlanI18n) window.PowerPlanI18n.translate(target, window.PowerPlanI18n.currentLanguage());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
