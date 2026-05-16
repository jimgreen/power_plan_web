const MAX_TABS = 4;

const state = {
  schemes: [],
  tabs: [{ id: "tab-1", scheme: "", result: "", results: [] }],
  activeTabId: "tab-1",
  draggingTabId: "",
  comparison: { items: [], tables: { capacity: [], energy: [], safety: [] }, curve_groups: {}, annual_table: [], curves: [], series: {} },
  comparisonCurveViewer: null,
  selectedCurves: [],
  tableHeight: null,
  tableColumnWidths: [1, 1, 1],
  hoverIndex: null,
  curveDataKey: "",
};

document.addEventListener("DOMContentLoaded", () => {
  state.comparisonCurveViewer = window.ResultCurveViewer
    ? window.ResultCurveViewer.create({
        listId: "curveNameList",
        chartId: "comparisonCurveChart",
        emptyText: "暂无小时级曲线",
        promptText: "请选择小时级曲线",
      })
    : null;
  bindAddTab();
  bindComparisonTableColumnResizeHandles();
  bindComparisonTableCurveResizeHandle();
  loadSchemes().catch(showError);
});

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch (error) {
    throw new Error("请求后台失败，请检查 WEB 服务是否正常运行，或查看服务器错误日志。");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.error || "请求失败");
    error.payload = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

async function loadSchemes() {
  state.schemes = (await api("/api/planning/schemes")).schemes || [];
  state.tabs.forEach((tab) => {
    if (!tab.scheme && state.schemes.length) tab.scheme = state.schemes[0].name;
  });
  await Promise.all(state.tabs.map(loadResultFilesForTab));
  renderComparisonTabs();
  await refreshComparisonData();
}

async function loadResultFilesForTab(tab) {
  if (!tab.scheme) {
    tab.results = [];
    tab.result = "";
    return;
  }
  const data = await api(`/api/evaluation/results?scheme=${encodeURIComponent(tab.scheme)}${tab.result ? `&filename=${encodeURIComponent(tab.result)}` : ""}`);
  tab.results = data.results || [];
  const readableNames = tab.results.filter((item) => item.readable !== false).map((item) => item.name);
  tab.result = data.selected || (readableNames.includes(tab.result) ? tab.result : readableNames[0] || "");
}

function bindAddTab() {
  document.getElementById("comparisonTabs").addEventListener("click", async (event) => {
    if (!event.target.closest("#addComparisonTab")) return;
    if (state.tabs.length >= MAX_TABS) return;
    const tab = {
      id: `tab-${Date.now()}`,
      scheme: state.schemes[0]?.name || "",
      result: "",
      results: [],
    };
    state.tabs.push(tab);
    state.activeTabId = tab.id;
    await loadResultFilesForTab(tab);
    renderComparisonTabs();
    refreshComparisonData().catch(showError);
  });
}

function renderComparisonTabs() {
  const container = document.getElementById("comparisonTabs");
  container.innerHTML = state.tabs.map((tab, index) => renderComparisonTab(tab, index)).join("") + renderAddComparisonTab();
  document.getElementById("addComparisonTab").disabled = state.tabs.length >= MAX_TABS;
  renderComparisonResultWarnings();

  container.querySelectorAll("[data-comparison-tab]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (event.target.closest("select")) return;
      state.activeTabId = element.dataset.comparisonTab || state.activeTabId;
      renderComparisonTabs();
    });
    element.addEventListener("dragstart", (event) => {
      state.draggingTabId = element.dataset.comparisonTab || "";
      event.dataTransfer.effectAllowed = "move";
    });
    element.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });
    element.addEventListener("drop", (event) => {
      event.preventDefault();
      moveComparisonTab(state.draggingTabId, element.dataset.comparisonTab || "");
    });
  });

  container.querySelectorAll(".comparison-tab-selectors select").forEach((select) => {
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("mousedown", (event) => event.stopPropagation());
  });

  container.querySelectorAll("[data-close-comparison-tab]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const tabId = button.dataset.closeComparisonTab || "";
      state.tabs = state.tabs.filter((tab, index) => index === 0 || tab.id !== tabId);
      if (!state.tabs.some((tab) => tab.id === state.activeTabId)) state.activeTabId = state.tabs[0]?.id || "";
      renderComparisonTabs();
      clearComparisonDisplayForSwitch();
      refreshComparisonData().catch(showError);
    });
  });

  container.querySelectorAll("[data-scheme-select]").forEach((schemeSelect) => {
    schemeSelect.addEventListener("change", async () => {
      const tab = tabById(schemeSelect.dataset.schemeSelect);
      if (!tab) return;
      tab.scheme = schemeSelect.value;
      tab.result = "";
      clearComparisonDisplayForSwitch();
      await loadResultFilesForTab(tab);
      renderComparisonTabs();
      refreshComparisonData().catch(showError);
    });
  });

  container.querySelectorAll("[data-result-select]").forEach((resultSelect) => {
    resultSelect.addEventListener("change", () => {
      const tab = tabById(resultSelect.dataset.resultSelect);
      if (!tab) return;
      tab.result = resultSelect.value;
      clearComparisonDisplayForSwitch();
      refreshComparisonData().catch(showError);
    });
  });
}

function renderAddComparisonTab() {
  return `<button id="addComparisonTab" class="comparison-add-tab" type="button">添加对比</button>`;
}

function renderComparisonTab(tab, index) {
  const active = tab.id === state.activeTabId ? " active" : "";
  return `
    <section class="comparison-tab${active}" data-comparison-tab="${escapeHtml(tab.id)}" draggable="true">
      <div class="comparison-tab-head">
        <strong>对比${index + 1}</strong>
        ${index === 0 ? "" : `<button type="button" data-close-comparison-tab="${escapeHtml(tab.id)}" aria-label="关闭对比${index + 1}">×</button>`}
      </div>
      <div class="comparison-tab-selectors">
        <select data-scheme-select="${escapeHtml(tab.id)}" aria-label="方案列表">${renderSchemeOptions(tab.scheme)}</select>
        <select data-result-select="${escapeHtml(tab.id)}" aria-label="结果列表">${renderResultOptions(tab)}</select>
      </div>
    </section>`;
}

function renderSchemeOptions(selected) {
  if (!state.schemes.length) return '<option value="">暂无方案</option>';
  return state.schemes
    .map((scheme) => `<option value="${escapeHtml(scheme.name)}"${scheme.name === selected ? " selected" : ""}>${escapeHtml(scheme.name)}</option>`)
    .join("");
}

function renderResultOptions(tab) {
  if (!tab.results.length) return '<option value="">暂无结果</option>';
  return tab.results
    .map((item) => {
      const unreadable = item.readable === false;
      const selected = item.name === tab.result ? " selected" : "";
      const disabled = unreadable ? " disabled" : "";
      const label = `${resultDisplayName(item.name)}${unreadable ? "（无法读取）" : ""}`;
      return `<option value="${escapeHtml(item.name)}"${selected}${disabled}>${escapeHtml(label)}</option>`;
    })
    .join("");
}

function renderComparisonResultWarnings() {
  const host = document.getElementById("comparisonResultWarnings");
  if (!host) return;
  const warnings = state.tabs.flatMap((tab) =>
    (tab.results || [])
      .filter((item) => item.readable === false)
      .map((item) => ({ scheme: tab.scheme, item }))
  );
  host.innerHTML = warnings
    .map(({ scheme, item }) => `<div class="validation-item error">${escapeHtml(scheme || "未选择方案")} 的结果文件 ${escapeHtml(item.name)} ${escapeHtml(item.message || "无法读取，请重新生成或删除该文件。")}</div>`)
    .join("");
  host.hidden = warnings.length === 0;
}

function moveComparisonTab(sourceId, targetId) {
  if (!sourceId || !targetId || sourceId === targetId) return;
  const sourceIndex = state.tabs.findIndex((tab) => tab.id === sourceId);
  const targetIndex = state.tabs.findIndex((tab) => tab.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0) return;
  const [tab] = state.tabs.splice(sourceIndex, 1);
  state.tabs.splice(targetIndex, 0, tab);
  renderComparisonTabs();
  clearComparisonDisplayForSwitch();
  refreshComparisonData().catch(showError);
}

async function refreshComparisonData() {
  const items = state.tabs.filter((tab) => tab.scheme && tab.result).map((tab) => ({ scheme: tab.scheme, filename: tab.result }));
  const requestKey = JSON.stringify(items);
  state.curveDataKey = requestKey;
  if (!items.length) {
    state.comparison = { items: [], tables: { capacity: [], energy: [], safety: [] }, curve_groups: {}, annual_table: [], curves: [], series: {} };
  } else {
    const summary = await api(`/api/comparison/data?mode=summary&items=${encodeURIComponent(requestKey)}`);
    if (state.curveDataKey !== requestKey) return;
    state.comparison = summary;
  }
  state.selectedCurves = state.selectedCurves.filter((name) => state.comparison.curves.includes(name));
  if (!state.selectedCurves.length && state.comparison.curves.length) {
    state.selectedCurves = [state.comparison.curves[0]];
  }
  state.hoverIndex = null;
  renderComparisonTables();
  state.comparisonCurveViewer?.clear("正在加载小时级曲线");
  if (!state.comparisonCurveViewer) {
    renderCurveNameList();
    renderComparisonCurveChart();
  }
  loadComparisonCurveData(items).catch(showError);
}

function clearComparisonDisplayForSwitch() {
  state.comparison = { items: [], tables: { capacity: [], energy: [], safety: [] }, curve_groups: {}, annual_table: [], curves: [], series: {} };
  state.selectedCurves = [];
  state.hoverIndex = null;
  state.curveDataKey = "";
  renderComparisonTables();
  state.comparisonCurveViewer?.clear("正在加载小时级曲线");
  if (!state.comparisonCurveViewer) {
    renderCurveNameList();
    renderComparisonCurveChart();
  }
}

async function loadComparisonCurveData(items = state.tabs.filter((tab) => tab.scheme && tab.result).map((tab) => ({ scheme: tab.scheme, filename: tab.result }))) {
  if (!items.length) {
    state.comparisonCurveViewer?.clear("暂无小时级曲线");
    return;
  }
  const key = JSON.stringify(items);
  if (state.curveDataKey !== key) return;
  state.curveDataKey = key;
  try {
    const data = await api(`/api/comparison/data?items=${encodeURIComponent(key)}`);
    if (state.curveDataKey !== key) return;
    state.comparison = { ...state.comparison, curve_groups: data.curve_groups || {}, curves: data.curves || [], series: data.series || {}, annual_table: data.annual_table || state.comparison.annual_table || [] };
    state.selectedCurves = state.selectedCurves.filter((name) => state.comparison.curves.includes(name));
    if (!state.selectedCurves.length && state.comparison.curves.length) {
      state.selectedCurves = [state.comparison.curves[0]];
    }
    state.comparisonCurveViewer?.setData(state.comparison);
    if (!state.comparisonCurveViewer) {
      renderCurveNameList();
      renderComparisonCurveChart();
    }
  } catch (error) {
    if (state.curveDataKey === key) state.curveDataKey = "";
    throw error;
  }
}

function renderComparisonTables() {
  renderTable("capacityComparisonTable", state.comparison.tables?.capacity || [], "暂无规划容量对比");
  renderTable("energyComparisonTable", state.comparison.tables?.energy || [], "暂无供能指标对比");
  renderTable("safetyComparisonTable", state.comparison.tables?.safety || [], "暂无安全指标对比");
}

function renderTable(id, rows, emptyText) {
  const target = document.getElementById(id);
  if (!rows.length) {
    target.innerHTML = `<div class="empty-summary">${escapeHtml(emptyText)}</div>`;
    return;
  }
  const headers = Object.keys(rows[0]);
  target.innerHTML = `<table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows
    .map((row) => `<tr>${headers.map((header) => `<td>${escapeHtml(row[header] ?? "")}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function renderCurveNameList() {
  if (state.comparisonCurveViewer) {
    state.comparisonCurveViewer.render();
    return;
  }
  const target = document.getElementById("curveNameList");
  if (!state.comparison.curves.length) {
    target.innerHTML = '<div class="empty-summary">暂无小时级曲线</div>';
    return;
  }
  target.innerHTML = state.comparison.curves
    .map(
      (name) =>
        `<li class="comparison-curve-name-item${state.selectedCurves.includes(name) ? " active" : ""}" data-curve-name="${escapeHtml(name)}" role="option" aria-selected="${state.selectedCurves.includes(name) ? "true" : "false"}" tabindex="0">${escapeHtml(name)}</li>`
    )
    .join("");
  target.innerHTML = `<ul aria-multiselectable="true">${target.innerHTML}</ul>`;
  target.querySelectorAll("[data-curve-name]").forEach((button) => {
    button.addEventListener("click", () => {
      toggleSelectedCurve(button.dataset.curveName || "");
    });
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleSelectedCurve(button.dataset.curveName || "");
      }
    });
  });
}

function toggleSelectedCurve(name) {
  if (!name) return;
  if (state.selectedCurves.includes(name)) {
    state.selectedCurves = state.selectedCurves.filter((item) => item !== name);
  } else {
    state.selectedCurves = [...state.selectedCurves, name];
  }
  renderCurveNameList();
  renderComparisonCurveChart();
}

function selectedCurveNames() {
  return state.selectedCurves.filter((name) => state.comparison.curves.includes(name));
}

function selectedCurveSeries() {
  return selectedCurveNames().flatMap((curveName) =>
    (state.comparison.series?.[curveName] || []).map((item) => ({
      ...item,
      curveName,
      displayLabel: `${curveName} / ${item.label}`,
    }))
  );
}

function renderComparisonCurveChart() {
  if (state.comparisonCurveViewer) {
    state.comparisonCurveViewer.render();
    return;
  }
  const target = document.getElementById("comparisonCurveChart");
  const curveNames = selectedCurveNames();
  const series = selectedCurveSeries();
  if (!curveNames.length || !series.length) {
    target.innerHTML = '<div class="empty-summary">请选择小时级曲线</div>';
    return;
  }
  const width = 1080;
  const height = 360;
  const margin = { top: 18, right: 24, bottom: 28, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const allY = series.flatMap((item) => item.points.map((point) => Number(point.y)).filter(Number.isFinite));
  const minY = Math.min(...allY, 0);
  const maxY = Math.max(...allY, 1);
  const ySpan = Math.max(maxY - minY, 1);
  const maxPoints = Math.max(...series.map((item) => item.points.length), 1);
  const xAt = (index, total) => margin.left + (total <= 1 ? plotWidth / 2 : (index / (total - 1)) * plotWidth);
  const yAt = (value) => margin.top + plotHeight - ((value - minY) / ySpan) * plotHeight;
  const colors = ["#21d5ff", "#82e7b5", "#ffc857", "#ff7a90", "#b38cff", "#5ee7df", "#ff9f43", "#ff6bcb"];
  const yTicks = [0, 0.5, 1].map((ratio) => ({
    ratio,
    value: minY + ySpan * ratio,
    y: yAt(minY + ySpan * ratio),
  }));
  target.innerHTML = `
    <div class="comparison-curve-legend">${series
      .map((item, index) => `<span><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(item.displayLabel)}</span>`)
      .join("")}</div>
    <div class="comparison-chart-frame" style="--comparison-chart-left:${((margin.left / width) * 100).toFixed(3)}%; --comparison-chart-right:${((margin.right / width) * 100).toFixed(3)}%; --comparison-chart-top:${((margin.top / height) * 100).toFixed(3)}%; --comparison-chart-bottom:${((margin.bottom / height) * 100).toFixed(3)}%;">
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(curveNames.join('、'))}曲线对比">
        <line class="comparison-chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
        <line class="comparison-chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
        ${yTicks.map((tick) => renderYAxisGrid(tick.y, margin.left, width - margin.right)).join("")}
        ${series.map((item, index) => renderSeriesPath(item.points, xAt, yAt, colors[index % colors.length])).join("")}
        <g id="comparisonChartHover" hidden>
          <line class="comparison-chart-hover-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
        </g>
        <rect class="comparison-chart-hover-capture" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"></rect>
      </svg>
      ${renderComparisonAxisLabels({ yTicks, series, maxPoints })}
      ${renderComparisonCurveStats(series)}
      <div id="comparisonChartTooltip" class="comparison-chart-tooltip" hidden></div>
    </div>`;
  bindComparisonChartHover({ width, height, margin, plotWidth, plotHeight, series });
}

function renderYAxisGrid(y, left, right) {
  return `<line class="comparison-chart-grid" x1="${left}" y1="${y.toFixed(2)}" x2="${right}" y2="${y.toFixed(2)}"></line>`;
}

function renderComparisonAxisLabels({ yTicks, series, maxPoints }) {
  const firstPoints = series[0]?.points || [];
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const index = Math.min(Math.round(ratio * Math.max(maxPoints - 1, 0)), firstPoints.length - 1);
    return {
      ratio,
      label: firstPoints[index]?.x ?? Math.round(ratio * Math.max(maxPoints - 1, 0)) + 1,
    };
  });
  return `
    <div class="comparison-chart-y-axis" aria-hidden="true">${yTicks
      .map((tick) => `<span style="bottom:${(tick.ratio * 100).toFixed(2)}%">${escapeHtml(formatAxis(tick.value))}</span>`)
      .join("")}</div>
    <div class="comparison-chart-x-axis" aria-hidden="true">${xTicks
      .map((tick) => `<span style="left:${(tick.ratio * 100).toFixed(2)}%">${escapeHtml(tick.label)}</span>`)
      .join("")}</div>`;
}

function renderComparisonCurveStats(series) {
  return `<div class="comparison-curve-stats" aria-label="当前曲线统计信息">${series.map((item) => {
    const values = item.points.map((point) => Number(point.y)).filter(Number.isFinite);
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 0;
    const sum = values.reduce((total, value) => total + value, 0);
    const average = values.length ? sum / values.length : 0;
    return `<section><strong>${escapeHtml(item.displayLabel)}</strong><span>最小 ${escapeHtml(formatAxis(min))}</span><span>最大 ${escapeHtml(formatAxis(max))}</span><span>平均 ${escapeHtml(formatAxis(average))}</span><span>合计 ${escapeHtml(formatAxis(sum))}</span></section>`;
  }).join("")}</div>`;
}

function renderSeriesPath(points, xAt, yAt, color) {
  const sampled = downsample(points, 720);
  const path = sampled
    .map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index, sampled.length).toFixed(2)} ${yAt(Number(point.y)).toFixed(2)}`)
    .join(" ");
  return `<path class="comparison-series-line" d="${path}" stroke="${color}"></path>`;
}

function downsample(points, limit) {
  if (points.length <= limit) return points;
  const step = Math.ceil(points.length / limit);
  return points.filter((_, index) => index % step === 0);
}

function bindComparisonChartHover(chart) {
  const target = document.getElementById("comparisonCurveChart");
  const capture = target.querySelector(".comparison-chart-hover-capture");
  const tooltip = document.getElementById("comparisonChartTooltip");
  if (!capture || !tooltip) return;
  capture.addEventListener("mousemove", (event) => {
    const rect = capture.getBoundingClientRect();
    const ratio = Math.min(Math.max((event.clientX - rect.left) / Math.max(rect.width, 1), 0), 1);
    const maxPoints = Math.max(...chart.series.map((item) => item.points.length), 1);
    const index = Math.round(ratio * (maxPoints - 1));
    state.hoverIndex = index;
    renderComparisonChartHover(chart, event, index);
  });
  capture.addEventListener("mouseleave", () => {
    state.hoverIndex = null;
    const hover = document.getElementById("comparisonChartHover");
    if (hover) hover.setAttribute("hidden", "");
    tooltip.hidden = true;
  });
}

function renderComparisonChartHover(chart, event, pointIndex) {
  const hover = document.getElementById("comparisonChartHover");
  const tooltip = document.getElementById("comparisonChartTooltip");
  const chartTarget = document.getElementById("comparisonCurveChart");
  if (!hover || !tooltip || !chartTarget) return;
  const maxPoints = Math.max(...chart.series.map((item) => item.points.length), 1);
  const ratio = maxPoints <= 1 ? 0 : Math.min(Math.max(pointIndex / (maxPoints - 1), 0), 1);
  const x = chart.margin.left + ratio * chart.plotWidth;
  hover.removeAttribute("hidden");
  hover.querySelector("line")?.setAttribute("x1", x.toFixed(2));
  hover.querySelector("line")?.setAttribute("x2", x.toFixed(2));
  const rows = chart.series.map((item) => {
    const index = Math.min(Math.max(pointIndex, 0), item.points.length - 1);
    const point = item.points[index] || {};
    return { label: item.displayLabel || item.label, x: point.x ?? index + 1, y: point.y };
  });
  tooltip.innerHTML = `
    <h3>${escapeHtml(rows[0]?.x ?? "")}</h3>
    ${rows.map((row) => `<div><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(formatAxis(row.y))}</strong></div>`).join("")}`;
  tooltip.hidden = false;
  const bounds = chartTarget.getBoundingClientRect();
  const tooltipX = Math.min(Math.max(event.clientX - bounds.left + 14, 8), Math.max(bounds.width - tooltip.offsetWidth - 8, 8));
  const tooltipY = Math.min(Math.max(event.clientY - bounds.top + 14, 8), Math.max(bounds.height - tooltip.offsetHeight - 8, 8));
  tooltip.style.left = `${Math.round(tooltipX)}px`;
  tooltip.style.top = `${Math.round(tooltipY)}px`;
}

function bindComparisonTableColumnResizeHandles() {
  document.querySelectorAll("[data-comparison-table-column-resize]").forEach((handle) => {
    const resizeType = handle.dataset.comparisonTableColumnResize;
    const leftIndex = resizeType === "capacity-energy" ? 0 : 1;
    const rightIndex = resizeType === "capacity-energy" ? 1 : 2;
    const applyWidths = (nextWidths) => {
      const widths = normalizeTableColumnWidths(nextWidths);
      state.tableColumnWidths = widths;
      document.documentElement.style.setProperty("--comparison-capacity-table-width", `${widths[0].toFixed(3)}fr`);
      document.documentElement.style.setProperty("--comparison-energy-table-width", `${widths[1].toFixed(3)}fr`);
      document.documentElement.style.setProperty("--comparison-safety-table-width", `${widths[2].toFixed(3)}fr`);
      handle.setAttribute("aria-valuenow", String(Math.round(widths[leftIndex] * 100)));
    };
    applyWidths(state.tableColumnWidths);
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const grid = document.querySelector(".comparison-table-grid");
      if (!grid) return;
      const startX = event.clientX;
      const startWidths = [...state.tableColumnWidths];
      const totalPixelWidth = grid.getBoundingClientRect().width - 20;
      const totalFr = startWidths.reduce((sum, value) => sum + value, 0);
      const pixelsPerFr = Math.max(totalPixelWidth / totalFr, 1);
      handle.classList.add("dragging");
      handle.setPointerCapture?.(event.pointerId);
      const onMove = (moveEvent) => {
        const deltaFr = (moveEvent.clientX - startX) / pixelsPerFr;
        const next = [...startWidths];
        next[leftIndex] = startWidths[leftIndex] + deltaFr;
        next[rightIndex] = startWidths[rightIndex] - deltaFr;
        applyWidths(next);
      };
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
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const delta = event.key === "ArrowLeft" ? -0.08 : 0.08;
        const next = [...state.tableColumnWidths];
        next[leftIndex] += delta;
        next[rightIndex] -= delta;
        applyWidths(next);
      }
    });
  });
}

function normalizeTableColumnWidths(widths) {
  const minWidth = 0.45;
  return widths.map((value) => Math.max(Number(value) || 1, minWidth));
}

function bindComparisonTableCurveResizeHandle() {
  const handle = document.getElementById("comparisonTableCurveResizeHandle");
  const panel = document.querySelector(".comparison-panel");
  if (!handle || !panel) return;
  const applyHeight = (height) => {
    const safeHeight = Math.min(Math.max(Number(height) || 320, 220), Math.max(220, panel.clientHeight - 260));
    state.tableHeight = safeHeight;
    document.documentElement.style.setProperty("--comparison-table-height", `${Math.round(safeHeight)}px`);
    handle.setAttribute("aria-valuenow", String(Math.round(safeHeight)));
  };
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = document.querySelector(".comparison-table-grid")?.getBoundingClientRect().height || 320;
    handle.classList.add("dragging");
    handle.setPointerCapture?.(event.pointerId);
    const onMove = (moveEvent) => applyHeight(startHeight + moveEvent.clientY - startY);
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
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      const current = state.tableHeight || document.querySelector(".comparison-table-grid")?.getBoundingClientRect().height || 320;
      applyHeight(current + (event.key === "ArrowUp" ? -24 : 24));
    }
  });
}

function tabById(id) {
  return state.tabs.find((tab) => tab.id === id);
}

function resultDisplayName(filename) {
  return String(filename || "").replace(/_results\.xlsx$/, "");
}

function formatAxis(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
}

function showError(error) {
  alert(error.message || String(error));
}
