const frequencyState = {
  schemes: [],
  currentScheme: "",
  resultFiles: [],
  selectedResultFile: "",
  status: null,
  pollTimer: null,
  activeResultTab: "metrics",
  frequencyTimeCurve: null,
  frequency8760Rows: [],
  axisRanges: {},
};

const FREQUENCY_SELECTION_STORAGE_KEY = "powerPlanFrequencySelection";
const FREQUENCY_8760_SERIES = [
  { key: "柴发开机容量", color: "#0d5c59" },
  { key: "向上最大扰动", color: "#c7504a" },
  { key: "向下最大扰动", color: "#7d5fb2" },
  { key: "优化频率最大值", color: "#d8902c" },
  { key: "优化频率最小值", color: "#4d7fd1" },
  { key: "仿真频率最大值", color: "#b55a7a" },
  { key: "仿真频率最小值", color: "#2d8a55" },
];

document.addEventListener("DOMContentLoaded", () => {
  bindFrequencyActions();
  bindFrequencyTabs();
  bindFrequencyMetricsResize();
  bindFrequencyTimeResultResize();
  bindFrequencyAxisRangeControls();
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
  document.getElementById("frequencyCurveQuery")?.addEventListener("click", () => refreshFrequencyTimeCurve().catch(showFrequencyError));
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
      if (target === "curve") {
        refreshFrequencyTimeCurve().catch(showFrequencyError);
      }
    });
  });
}

function bindFrequencyMetricsResize() {
  bindFrequencyHorizontalResize({
    handleId: "frequencyMetricsResizeHandle",
    layoutSelector: ".frequency-metrics-layout",
    cssVariable: "--frequency-metrics-table-width",
    defaultWidth: 360,
    minWidth: 240,
    rightMinWidth: 360,
  });
}

function bindFrequencyTimeResultResize() {
  bindFrequencyHorizontalResize({
    handleId: "frequencyTimeResultResizeHandle",
    layoutSelector: ".frequency-time-result-layout",
    cssVariable: "--frequency-time-info-width",
    defaultWidth: 360,
    minWidth: 220,
    rightMinWidth: 320,
  });
}

function bindFrequencyHorizontalResize({ handleId, layoutSelector, cssVariable, defaultWidth, minWidth, rightMinWidth }) {
  const handle = document.getElementById(handleId);
  const layout = document.querySelector(layoutSelector);
  if (!handle || !layout || handle.dataset.resizeBound === "true") return;
  handle.dataset.resizeBound = "true";
  const bounds = () => {
    const width = layout.getBoundingClientRect().width || 900;
    return { min: minWidth, max: Math.max(minWidth + 40, width - rightMinWidth) };
  };
  const currentWidth = () => {
    const value = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue(cssVariable));
    return Number.isFinite(value) ? value : defaultWidth;
  };
  const applyWidth = (width) => {
    const limits = bounds();
    const next = Math.min(limits.max, Math.max(limits.min, width));
    document.documentElement.style.setProperty(cssVariable, `${Math.round(next)}px`);
    handle.setAttribute("aria-valuenow", String(Math.round(next)));
    handle.setAttribute("aria-valuemin", String(Math.round(limits.min)));
    handle.setAttribute("aria-valuemax", String(Math.round(limits.max)));
  };
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = currentWidth();
    handle.classList.add("dragging");
    handle.setPointerCapture?.(event.pointerId);
    const onMove = (moveEvent) => applyWidth(startWidth + moveEvent.clientX - startX);
    const onDone = () => {
      handle.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onDone);
      window.removeEventListener("pointercancel", onDone);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onDone);
    window.addEventListener("pointercancel", onDone);
  });
  handle.addEventListener("keydown", (event) => {
    const steps = { ArrowLeft: -24, ArrowRight: 24, PageDown: -96, PageUp: 96 };
    if (event.key in steps) {
      event.preventDefault();
      applyWidth(currentWidth() + steps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyWidth(bounds().min);
    } else if (event.key === "End") {
      event.preventDefault();
      applyWidth(bounds().max);
    }
  });
  applyWidth(currentWidth());
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
  initializeFrequencyTimeControls(data.frequency_8760_table || []);
  if (frequencyState.activeResultTab === "curve") {
    await refreshFrequencyTimeCurve().catch(showFrequencyError);
  }
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
    const request = frequencyApi("/api/tasks/control", {
      method: "POST",
      body: JSON.stringify({
        action,
        task_type: "frequency",
        scheme: frequencyState.currentScheme,
        result: frequencyState.selectedResultFile,
      }),
    });
    if (action === "start" || action === "queue") {
      frequencyState.status = { ...(frequencyState.status || {}), status: action === "queue" ? "排队中" : "运行中" };
      scheduleFrequencyPolling();
      window.setTimeout(() => refreshFrequencyStatus().catch(showFrequencyError), 250);
    }
    await request;
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
  frequencyState.frequency8760Rows = data.frequency_8760_table || [];
  renderFrequency8760CurveBoard(frequencyState.frequency8760Rows);
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

function renderFrequency8760CurveBoard(rows) {
  const target = document.getElementById("frequency8760CurveBoard");
  if (!target) return;
  const normalized = Array.isArray(rows) ? rows : [];
  if (!normalized.length) {
    target.innerHTML = '<div class="empty-summary">暂无8760点频率指标曲线</div>';
    return;
  }
  const drawableSeries = FREQUENCY_8760_SERIES
    .map((series) => ({
      ...series,
      values: normalized.map((row, index) => ({
        hour: Number(row?.["小时"] ?? index + 1),
        value: Number(row?.[series.key]),
      })).filter((point) => Number.isFinite(point.value)),
    }))
    .filter((series) => series.values.length);
  if (!drawableSeries.length) {
    target.innerHTML = '<div class="empty-summary">暂无8760点频率指标曲线</div>';
    return;
  }
  const width = 1180;
  const laneHeight = 78;
  const margin = { top: 22, right: 40, bottom: 34, left: 118 };
  const plotWidth = width - margin.left - margin.right;
  const height = margin.top + margin.bottom + laneHeight * drawableSeries.length;
  const xAt = (hour) => margin.left + ((Math.max(1, Math.min(8760, hour)) - 1) / 8759) * plotWidth;
  const laneModels = drawableSeries.map((series, laneIndex) => {
    const laneTop = margin.top + laneIndex * laneHeight;
    const values = series.values.map((point) => point.value);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const span = Math.max(0.00001, rawMax - rawMin);
    const autoMin = rawMin - span * 0.08;
    const autoMax = rawMax + span * 0.08;
    const { min: yMin, max: yMax } = applyAxisRange(autoMin, autoMax, frequencyState.axisRanges.frequency8760);
    const yAt = (value) => laneTop + 10 + ((yMax - value) / Math.max(0.00001, yMax - yMin)) * (laneHeight - 24);
    const sampled = frequencyDownsample(series.values, 720);
    const path = sampled
      .map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(point.hour).toFixed(2)} ${yAt(point.value).toFixed(2)}`)
      .join(" ");
    const average = values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1);
    return { ...series, laneTop, rawMin, rawMax, yMin, yMax, average, yAt, path, count: values.length };
  });
  const lanes = laneModels.map((series) => {
    return `
      <g class="frequency-8760-lane">
        <text class="frequency-8760-series-label" x="${margin.left - 12}" y="${(series.laneTop + laneHeight / 2).toFixed(2)}">${escapeHtml(series.key)}</text>
        <line class="frequency-8760-grid" x1="${margin.left}" y1="${(series.laneTop + laneHeight - 12).toFixed(2)}" x2="${width - margin.right}" y2="${(series.laneTop + laneHeight - 12).toFixed(2)}"></line>
        <text class="frequency-8760-value-label" x="${width - margin.right + 4}" y="${(series.laneTop + 15).toFixed(2)}">${escapeHtml(formatCompactNumber(series.yMax))}</text>
        <text class="frequency-8760-value-label" x="${width - margin.right + 4}" y="${(series.laneTop + laneHeight - 12).toFixed(2)}">${escapeHtml(formatCompactNumber(series.yMin))}</text>
        <path class="frequency-8760-line" d="${series.path}" style="stroke:${series.color}"></path>
      </g>`;
  }).join("");
  target.innerHTML = `
    ${renderFrequencyAxisRangeControls("frequency8760")}
    <div class="comparison-chart-frame frequency-8760-chart-frame" style="--comparison-chart-left:${((margin.left / width) * 100).toFixed(3)}%; --comparison-chart-right:${((margin.right / width) * 100).toFixed(3)}%; --comparison-chart-top:${((margin.top / height) * 100).toFixed(3)}%; --comparison-chart-bottom:${((margin.bottom / height) * 100).toFixed(3)}%;">
      <svg class="frequency-8760-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="8760点频率指标曲线">
        ${[1, 2190, 4380, 6570, 8760].map((hour) => `<line class="frequency-8760-x-grid" x1="${xAt(hour).toFixed(2)}" y1="${margin.top}" x2="${xAt(hour).toFixed(2)}" y2="${height - margin.bottom}"></line>`).join("")}
        ${lanes}
        <g id="frequency8760Hover" hidden>
          <line class="comparison-chart-hover-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
        </g>
        <rect class="comparison-chart-hover-capture frequency-8760-hover-capture" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${height - margin.top - margin.bottom}"></rect>
      </svg>
      ${renderFrequency8760AxisLabels({ margin, width, height })}
      ${renderFrequency8760Stats(laneModels)}
      <div id="frequency8760Tooltip" class="comparison-chart-tooltip" hidden></div>
    </div>`;
  bindFrequency8760Hover({ width, height, margin, plotWidth, series: laneModels });
}

function renderFrequency8760AxisLabels({ margin, width }) {
  const xTicks = [1, 2190, 4380, 6570, 8760].map((hour) => ({ ratio: (hour - 1) / 8759, label: hour }));
  return `<div class="comparison-chart-x-axis" aria-hidden="true">${xTicks
    .map((tick) => `<span style="left:${(tick.ratio * 100).toFixed(2)}%">${escapeHtml(tick.label)}</span>`)
    .join("")}</div>`;
}

function renderFrequency8760Stats(series) {
  return `<div class="comparison-curve-stats frequency-8760-stats" aria-label="8760点频率指标统计">${series.map((item) => `
    <section>
      <strong style="border-left:4px solid ${item.color}; padding-left:7px">${escapeHtml(item.key)}</strong>
      <span>最小 ${escapeHtml(formatCompactNumber(item.rawMin))}</span>
      <span>最大 ${escapeHtml(formatCompactNumber(item.rawMax))}</span>
      <span>平均 ${escapeHtml(formatCompactNumber(item.average))}</span>
      <span>点数 ${escapeHtml(item.count)}</span>
    </section>`).join("")}</div>`;
}

function bindFrequency8760Hover(chart) {
  const target = document.getElementById("frequency8760CurveBoard");
  const capture = target?.querySelector(".frequency-8760-hover-capture");
  const tooltip = document.getElementById("frequency8760Tooltip");
  if (!target || !capture || !tooltip) return;
  capture.addEventListener("mousemove", (event) => {
    const rect = capture.getBoundingClientRect();
    const ratio = Math.min(Math.max((event.clientX - rect.left) / Math.max(rect.width, 1), 0), 1);
    const hour = Math.round(ratio * 8759) + 1;
    renderFrequency8760Hover(chart, event, hour);
  });
  capture.addEventListener("mouseleave", () => {
    document.getElementById("frequency8760Hover")?.setAttribute("hidden", "");
    tooltip.hidden = true;
  });
}

function renderFrequency8760Hover(chart, event, hour) {
  const hover = document.getElementById("frequency8760Hover");
  const tooltip = document.getElementById("frequency8760Tooltip");
  const board = document.getElementById("frequency8760CurveBoard");
  if (!hover || !tooltip || !board) return;
  const ratio = (Math.max(1, Math.min(8760, hour)) - 1) / 8759;
  const x = chart.margin.left + ratio * chart.plotWidth;
  hover.removeAttribute("hidden");
  hover.querySelector("line")?.setAttribute("x1", x.toFixed(2));
  hover.querySelector("line")?.setAttribute("x2", x.toFixed(2));
  const rows = chart.series.map((series) => {
    const point = nearestFrequencyPoint(series.values, hour);
    return { label: series.key, value: point?.value, color: series.color };
  });
  tooltip.innerHTML = `
    <h3>第${escapeHtml(hour)}小时</h3>
    ${rows.map((row) => `<div><span style="border-left:4px solid ${row.color}; padding-left:7px">${escapeHtml(row.label)}</span><strong>${escapeHtml(formatCompactNumber(row.value))}</strong></div>`).join("")}`;
  tooltip.hidden = false;
  const bounds = board.getBoundingClientRect();
  const tooltipX = Math.min(Math.max(event.clientX - bounds.left + 14, 8), Math.max(bounds.width - tooltip.offsetWidth - 8, 8));
  const tooltipY = Math.min(Math.max(event.clientY - bounds.top + 14, 8), Math.max(bounds.height - tooltip.offsetHeight - 8, 8));
  tooltip.style.left = `${Math.round(tooltipX)}px`;
  tooltip.style.top = `${Math.round(tooltipY)}px`;
}

function nearestFrequencyPoint(points, hour) {
  return points.reduce((best, point) => {
    if (!best) return point;
    return Math.abs(point.hour - hour) < Math.abs(best.hour - hour) ? point : best;
  }, null);
}

function frequencyDownsample(points, limit) {
  if (points.length <= limit) return points;
  const step = Math.ceil(points.length / limit);
  return points.filter((_, index) => index % step === 0 || index === points.length - 1);
}

function renderSimpleTable(rows, preferredColumns = null) {
  const discoveredColumns = Array.from(rows.reduce((set, row) => {
    Object.keys(row || {}).forEach((key) => set.add(key));
    return set;
  }, new Set()));
  const columns = Array.isArray(preferredColumns) && preferredColumns.length
    ? [...preferredColumns, ...discoveredColumns.filter((column) => !preferredColumns.includes(column))]
    : discoveredColumns;
  return `
    <table>
      <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row?.[column] ?? "")}</td>`).join("")}</tr>`).join("")}
      </tbody>
    </table>`;
}

function formatCompactNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  const absolute = Math.abs(numeric);
  const digits = absolute >= 100 ? 1 : absolute >= 10 ? 2 : 4;
  return String(Number(numeric.toFixed(digits)));
}

async function refreshFrequencyTimeCurve() {
  const target = document.getElementById("frequencyCurveChart");
  if (!target) return;
  if (!frequencyState.currentScheme || !frequencyState.selectedResultFile) {
    renderFrequencyTimeCurve(null, "请先选择方案和结果文件");
    return;
  }
  const params = new URLSearchParams({
    scheme: frequencyState.currentScheme,
    filename: frequencyState.selectedResultFile,
    month: selectedFrequencyCurveDatePart("month"),
    day: selectedFrequencyCurveDatePart("day"),
    hour: document.getElementById("frequencyCurveHour")?.value || "",
  });
  renderFrequencyTimeCurve(null, "正在读取分时曲线...");
  const data = await frequencyApi(`/api/frequency/time-curve?${params.toString()}`);
  frequencyState.frequencyTimeCurve = data;
  applyFrequencyTimeSelection(data.selection || {});
  renderFrequencyTimeInfoTable(data.summary_table || []);
  renderFrequencyTimeCurve(data);
}

function initializeFrequencyTimeControls(rows) {
  const dateInput = document.getElementById("frequencyCurveDate");
  const hourInput = document.getElementById("frequencyCurveHour");
  if (!dateInput || dateInput.value || !Array.isArray(rows) || !rows.length) return;
  const first = rows[0] || {};
  const parts = parseFrequencyTimeText(first["时间"]);
  if (!parts) return;
  dateInput.value = frequencyDateInputValue(parts);
  if (hourInput) hourInput.value = parts.hour;
}

function applyFrequencyTimeSelection(selection) {
  if (!selection) return;
  const dateInput = document.getElementById("frequencyCurveDate");
  const hourInput = document.getElementById("frequencyCurveHour");
  if (dateInput && selection.month !== "" && selection.day !== "") {
    dateInput.value = frequencyDateInputValue(selection);
  }
  if (hourInput && selection.hour !== "" && selection.hour != null) {
    hourInput.value = selection.hour;
  }
}

function parseFrequencyTimeText(value) {
  const match = String(value || "").match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})/);
  return match ? { year: match[1], month: match[2], day: match[3], hour: match[4] } : null;
}

function selectedFrequencyCurveDatePart(part) {
  const value = document.getElementById("frequencyCurveDate")?.value || "";
  const match = value.match(/\d{4}-(\d{2})-(\d{2})/);
  if (!match) return "";
  return part === "month" ? String(Number(match[1])) : String(Number(match[2]));
}

function frequencyDateInputValue(parts) {
  const year = String(parts.year || "2026").padStart(4, "0");
  const month = String(parts.month || "1").padStart(2, "0");
  const day = String(parts.day || "1").padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function renderFrequencyTimeInfoTable(rows) {
  const target = document.getElementById("frequencyTimeInfoTable");
  if (!target) return;
  const normalized = Array.isArray(rows) ? rows : [];
  target.innerHTML = normalized.length ? renderSimpleTable(normalized, ["指标", "数值", "单位"]) : '<div class="empty-summary">暂无该时刻频率信息</div>';
}

function renderFrequencyTimeCurve(data, message = "暂无分时曲线") {
  const target = document.getElementById("frequencyCurveChart");
  if (!target) return;
  const high = Array.isArray(data?.curves?.high) ? data.curves.high.filter((point) => Number.isFinite(Number(point.frequency))) : [];
  const low = Array.isArray(data?.curves?.low) ? data.curves.low.filter((point) => Number.isFinite(Number(point.frequency))) : [];
  if (!high.length || !low.length) {
    target.innerHTML = `<div class="empty-summary">${escapeHtml(message)}</div>`;
    return;
  }
  const width = 1000;
  const height = 330;
  const margin = { top: 28, right: 26, bottom: 34, left: 64 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const allValues = [...high, ...low].map((point) => Number(point.frequency));
  const minValue = Math.min(49.5, ...allValues);
  const maxValue = Math.max(50.5, ...allValues);
  const autoMin = Math.floor((minValue - 0.05) * 10) / 10;
  const autoMax = Math.ceil((maxValue + 0.05) * 10) / 10;
  const { min: yMin, max: yMax } = applyAxisRange(autoMin, autoMax, frequencyState.axisRanges.frequencyTime);
  const maxTime = Math.max(...high.map((point) => Number(point.time)), ...low.map((point) => Number(point.time)), 3);
  const xAt = (time) => margin.left + (Number(time) / Math.max(0.01, maxTime)) * plotWidth;
  const yAt = (value) => margin.top + ((yMax - value) / Math.max(0.001, yMax - yMin)) * plotHeight;
  const highPath = timeLinePath(high, xAt, yAt);
  const lowPath = timeLinePath(low, xAt, yAt);
  const ticks = [yMax, 50.5, 50.0, 49.5, yMin].filter((value, index, list) => list.indexOf(value) === index);
  target.innerHTML = `
    ${renderFrequencyAxisRangeControls("frequencyTime")}
    <svg class="safety-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="分时曲线">
      ${ticks.map((tick) => `<line class="safety-grid-line" x1="${margin.left}" y1="${yAt(tick).toFixed(2)}" x2="${width - margin.right}" y2="${yAt(tick).toFixed(2)}"></line><text class="safety-tick-label" x="${margin.left - 8}" y="${(yAt(tick) + 4).toFixed(2)}">${escapeHtml(tick.toFixed(1))}</text>`).join("")}
      <line class="safety-axis-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
      <line class="safety-center-line" x1="${margin.left}" y1="${yAt(50).toFixed(2)}" x2="${width - margin.right}" y2="${yAt(50).toFixed(2)}"></line>
      <path class="safety-frequency-line up" d="${highPath}"></path>
      <path class="safety-frequency-line down" d="${lowPath}"></path>
      ${renderTimeTicks(maxTime, xAt, height - margin.bottom)}
    </svg>
    <div class="safety-chart-legend">
      <button type="button"><i style="background:#c7504a"></i>高频曲线</button>
      <button type="button"><i style="background:#4d7fd1"></i>低频曲线</button>
    </div>`;
}

function renderTimeTicks(maxTime, xAt, bottomY) {
  return [0, 0.5, 1, 1.5, 2, 2.5, maxTime]
    .filter((value, index, list) => list.indexOf(value) === index)
    .map((time) => {
      const x = xAt(time);
      return `<line class="safety-x-tick" x1="${x.toFixed(2)}" y1="${bottomY - 4}" x2="${x.toFixed(2)}" y2="${bottomY}"></line><text class="safety-x-label" x="${x.toFixed(2)}" y="${bottomY + 16}">${escapeHtml(Number(time).toFixed(1))}s</text>`;
    })
    .join("");
}

function timeLinePath(points, xAt, yAt) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(point.time).toFixed(2)} ${yAt(Number(point.frequency)).toFixed(2)}`).join(" ");
}

function bindFrequencyAxisRangeControls() {
  document.addEventListener("change", (event) => {
    if (!event.target.matches("[data-frequency-axis-min], [data-frequency-axis-max]")) return;
    const key = event.target.dataset.frequencyAxisMin || event.target.dataset.frequencyAxisMax || "";
    const previous = frequencyState.axisRanges[key] || {};
    const value = event.target.value === "" ? "" : Number(event.target.value);
    const next = { ...previous };
    if (event.target.matches("[data-frequency-axis-min]")) next.min = Number.isFinite(value) ? value : "";
    if (event.target.matches("[data-frequency-axis-max]")) next.max = Number.isFinite(value) ? value : "";
    frequencyState.axisRanges[key] = next;
    rerenderFrequencyAxisBoard(key);
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-frequency-axis-reset]");
    if (!button) return;
    const key = button.dataset.frequencyAxisReset || "";
    delete frequencyState.axisRanges[key];
    rerenderFrequencyAxisBoard(key);
  });
}

function rerenderFrequencyAxisBoard(key) {
  if (key === "frequency8760") renderFrequency8760CurveBoard(frequencyState.frequency8760Rows || []);
  if (key === "frequencyTime") renderFrequencyTimeCurve(frequencyState.frequencyTimeCurve);
}

function renderFrequencyAxisRangeControls(key) {
  const range = frequencyState.axisRanges[key] || {};
  return `
    <div class="axis-range-controls" aria-label="纵坐标显示范围">
      <span>纵坐标</span>
      <label>最小值<input type="number" step="any" data-frequency-axis-min="${escapeHtml(key)}" value="${escapeHtml(range.min ?? "")}" placeholder="自动"></label>
      <label>最大值<input type="number" step="any" data-frequency-axis-max="${escapeHtml(key)}" value="${escapeHtml(range.max ?? "")}" placeholder="自动"></label>
      <button type="button" data-frequency-axis-reset="${escapeHtml(key)}">自动</button>
    </div>`;
}

function applyAxisRange(autoMin, autoMax, range = {}) {
  let min = Number(range.min);
  let max = Number(range.max);
  const hasMin = Number.isFinite(min);
  const hasMax = Number.isFinite(max);
  if (hasMin && hasMax && max > min) return { min, max };
  if (hasMin && !hasMax) return { min, max: Math.max(autoMax, min + 1) };
  if (!hasMin && hasMax) return { min: Math.min(autoMin, max - 1), max };
  return { min: autoMin, max: autoMax };
}

function linePath(points, accessor, xAt, yAt) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index).toFixed(2)} ${yAt(accessor(point)).toFixed(2)}`).join(" ");
}

function renderFrequencyLogs(logs) {
  const target = document.getElementById("frequencyLogs");
  if (!target) return;
  const shouldStickToBottom = isLogScrolledNearBottom(target);
  const previousScrollTop = target.scrollTop;
  const rows = Array.isArray(logs) ? logs : [];
  target.innerHTML = rows.length
    ? rows.map((log) => `<div class="log-line ${escapeHtml(log.level || "info")}"><span>${escapeHtml(log.time || "")}</span><strong>${escapeHtml(log.message || "")}</strong></div>`).join("")
    : '<div class="log-line info"><strong>暂无评估日志</strong></div>';
  target.scrollTop = shouldStickToBottom ? target.scrollHeight : previousScrollTop;
}

function isLogScrolledNearBottom(box) {
  const distance = box.scrollHeight - box.scrollTop - box.clientHeight;
  return distance <= 12;
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
