const EVALUATION_SELECTION_STORAGE_KEY = "powerPlanLastEvaluationSelection";
const EVALUATION_PAGE_STATE_KEY = "evaluation";
const COLLAPSED_PANEL_SIZE = 0;
const HOURLY_CURVE_PRELOAD_BATCH_SIZE = 8;
const HOURLY_CURVE_PRELOAD_DELAY_MS = 300;
const HOURLY_CURVE_PRELOAD_BATCH_DELAY_MS = 120;

const state = {
  schemes: [],
  currentScheme: "",
  optimization: null,
  pollTimer: null,
  pollDelay: 4000,
  greenResultTableWidth: null,
  safetyResultTableWidth: null,
  overviewLeftColumnWidth: null,
  greenDailyPoints: [],
  safetyDailyPoints: [],
  resultFiles: [],
  resultsByScheme: {},
  collapsedSchemes: new Set(),
  selectedResultFile: "",
  planningResultRows: [],
  greenChartSize: null,
  safetyChartSize: null,
  resultChartResizeObserver: null,
  evaluationCurveViewer: null,
  evaluationResultRailWidth: null,
  evaluationSchemeRailHeight: null,
  curveDataKey: "",
  curvePayload: null,
  loadedCurveKeys: new Set(),
  hourlyCurvePreloadToken: 0,
  activeResultTab: "overview",
  isSwitchingResult: false,
  greenSeriesVisibility: null,
  safetySeriesVisibility: null,
  axisRanges: {},
  seriesToggleBound: false,
  lastOptimizationRenderSignature: "",
};

let restoredEvaluationPageState = {};

function restoreEvaluationPageState() {
  restoredEvaluationPageState = window.PowerPlanPageState?.read?.(EVALUATION_PAGE_STATE_KEY, {}) || {};
  const saved = restoredEvaluationPageState;
  if (typeof saved.currentScheme === "string") state.currentScheme = saved.currentScheme;
  if (typeof saved.selectedResultFile === "string") state.selectedResultFile = saved.selectedResultFile;
  if (["overview", "green", "safety", "logs", "curves"].includes(saved.activeResultTab)) state.activeResultTab = saved.activeResultTab;
  if (Array.isArray(saved.collapsedSchemes)) state.collapsedSchemes = new Set(saved.collapsedSchemes.map((item) => String(item || "")).filter(Boolean));
  ["greenResultTableWidth", "safetyResultTableWidth", "overviewLeftColumnWidth", "evaluationResultRailWidth", "evaluationSchemeRailHeight"].forEach((key) => {
    const savedNumber = window.PowerPlanPageState?.number?.(saved[key]);
    if (Number.isFinite(savedNumber)) state[key] = savedNumber;
  });
  if (state.greenResultTableWidth) document.documentElement.style.setProperty("--green-result-table-width", `${Math.round(state.greenResultTableWidth)}px`);
  if (state.safetyResultTableWidth) document.documentElement.style.setProperty("--safety-result-table-width", `${Math.round(state.safetyResultTableWidth)}px`);
  if (state.overviewLeftColumnWidth) document.documentElement.style.setProperty("--overview-left-column-width", `${Math.round(state.overviewLeftColumnWidth)}px`);
  if (state.evaluationResultRailWidth) document.documentElement.style.setProperty("--evaluation-result-rail-width", `${Math.round(state.evaluationResultRailWidth)}px`);
  if (state.evaluationSchemeRailHeight) document.documentElement.style.setProperty("--evaluation-scheme-rail-height", `${Math.round(state.evaluationSchemeRailHeight)}px`);
  if (saved.greenSeriesVisibility && typeof saved.greenSeriesVisibility === "object") state.greenSeriesVisibility = { ...saved.greenSeriesVisibility };
  if (saved.safetySeriesVisibility && typeof saved.safetySeriesVisibility === "object") state.safetySeriesVisibility = { ...saved.safetySeriesVisibility };
  if (saved.axisRanges && typeof saved.axisRanges === "object") state.axisRanges = normalizeAxisRanges(saved.axisRanges);
}

function evaluationPageStateSnapshot() {
  return {
    currentScheme: state.currentScheme || "",
    selectedResultFile: state.selectedResultFile || "",
    activeResultTab: state.activeResultTab || "overview",
    collapsedSchemes: Array.from(state.collapsedSchemes || []),
    greenResultTableWidth: state.greenResultTableWidth,
    safetyResultTableWidth: state.safetyResultTableWidth,
    overviewLeftColumnWidth: state.overviewLeftColumnWidth,
    evaluationResultRailWidth: state.evaluationResultRailWidth,
    evaluationSchemeRailHeight: state.evaluationSchemeRailHeight,
    greenSeriesVisibility: state.greenSeriesVisibility,
    safetySeriesVisibility: state.safetySeriesVisibility,
    axisRanges: state.axisRanges || {},
  };
}

function rememberEvaluationPageState(partial = {}) {
  const next = { ...evaluationPageStateSnapshot(), ...(partial || {}) };
  restoredEvaluationPageState = next;
  window.PowerPlanPageState?.write?.(EVALUATION_PAGE_STATE_KEY, next);
}

const resultTabLabels = {
  overview: "结果概览",
  green: "经济性指标",
  safety: "安全性指标",
};

const greenDailySeries = [
  { key: "diesel_energy", label: "柴发日电量", direction: "up", color: "#7a6650" },
  { key: "wind_energy", label: "风电日电量", direction: "up", color: "#2a9d8f" },
  { key: "pv_energy", label: "光伏日电量", direction: "up", color: "#d8a31a" },
  { key: "hydrogen_energy", label: "氢能日电量", direction: "up", color: "#4d7fd1" },
  { key: "storage_discharge_energy", label: "储能放电量", direction: "up", color: "#5aa66f" },
  { key: "load_energy", label: "负荷电量", direction: "down", color: "#c7504a" },
  { key: "hydrogen_production_energy", label: "制氢电量", direction: "down", color: "#6b5fb5" },
  { key: "storage_charge_energy", label: "储能充电量", direction: "down", color: "#3c9fb2" },
];

const safetyDailySeries = [
  { key: "frequency_max", label: "向上频率最大值", color: "#c7504a" },
  { key: "frequency_min", label: "向下频率最小值", color: "#4d7fd1" },
];

const resultColumnResizeConfig = {
  green: {
    stateKey: "greenResultTableWidth",
    cssVariable: "--green-result-table-width",
    layoutSelector: ".green-result-layout",
    tableSelector: ".green-result-table",
  },
  safety: {
    stateKey: "safetyResultTableWidth",
    cssVariable: "--safety-result-table-width",
    layoutSelector: ".safety-result-layout",
    tableSelector: ".safety-result-table",
  },
};

function ensureSeriesVisibility(kind) {
  const stateKey = `${kind}SeriesVisibility`;
  const seriesList = kind === "green" ? greenDailySeries : safetyDailySeries;
  const visibility = state[stateKey] && typeof state[stateKey] === "object" ? state[stateKey] : {};
  seriesList.forEach((series) => {
    if (typeof visibility[series.key] !== "boolean") visibility[series.key] = true;
  });
  state[stateKey] = visibility;
  return visibility;
}

function isSeriesVisible(kind, seriesKey) {
  return ensureSeriesVisibility(kind)[seriesKey] !== false;
}

function setSeriesVisibility(kind, seriesKey, visible) {
  const visibility = ensureSeriesVisibility(kind);
  visibility[seriesKey] = Boolean(visible);
  return visibility[seriesKey];
}

function bindSeriesToggleButtons() {
  if (state.seriesToggleBound) return;
  state.seriesToggleBound = true;
  document.addEventListener("click", (event) => {
    const button = event.target?.closest?.("[data-series-toggle]");
    if (!button) return;
    const [kind, seriesKey] = String(button.dataset.seriesToggle || "").split(":");
    if (!kind || !seriesKey) return;
    if (kind === "green") toggleGreenSeriesVisibility(seriesKey, button.closest("[data-result-chart-viewport]"));
    else if (kind === "safety") toggleSafetySeriesVisibility(seriesKey, button.closest("[data-result-chart-viewport]"));
  });
}

function toggleSeriesVisibility(kind, seriesKey, viewport) {
  if (!seriesKey) return;
  setSeriesVisibility(kind, seriesKey, !isSeriesVisible(kind, seriesKey));
  renderAdaptiveResultChart(kind, viewport || document.querySelector(`[data-result-chart-viewport="${kind}"]`));
  rememberEvaluationPageState({ [`${kind}SeriesVisibility`]: state[`${kind}SeriesVisibility`] });
}

function toggleGreenSeriesVisibility(seriesKey, viewport) {
  toggleSeriesVisibility("green", seriesKey, viewport);
}

function toggleSafetySeriesVisibility(seriesKey, viewport) {
  toggleSeriesVisibility("safety", seriesKey, viewport);
}

function renderSeriesLegendButtons(kind, seriesList) {
  return seriesList
    .map((series) => {
      const visible = isSeriesVisible(kind, series.key);
      return `<button type="button" class="${visible ? "is-visible" : "is-hidden"}" data-series-toggle="${kind}:${series.key}" aria-pressed="${visible ? "true" : "false"}"><i style="background:${series.color}"></i><span>${escapeHtml(series.label)}</span></button>`;
    })
    .join("");
}

function bindResultAxisRangeControls() {
  document.addEventListener("change", (event) => {
    if (!event.target.matches("[data-result-axis-min], [data-result-axis-max]")) return;
    const kind = event.target.dataset.resultAxisMin || event.target.dataset.resultAxisMax || "";
    const previous = state.axisRanges[kind] || {};
    const value = storedAxisNumber(event.target.value);
    const next = { ...previous };
    if (event.target.matches("[data-result-axis-min]")) {
      if (Number.isFinite(value)) next.min = value;
      else delete next.min;
    }
    if (event.target.matches("[data-result-axis-max]")) {
      if (Number.isFinite(value)) next.max = value;
      else delete next.max;
    }
    if (Object.keys(next).length) state.axisRanges[kind] = next;
    else delete state.axisRanges[kind];
    renderAdaptiveResultChart(kind);
    rememberEvaluationPageState({ axisRanges: state.axisRanges });
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-result-axis-reset]");
    if (!button) return;
    const kind = button.dataset.resultAxisReset || "";
    delete state.axisRanges[kind];
    renderAdaptiveResultChart(kind);
    rememberEvaluationPageState({ axisRanges: state.axisRanges });
  });
}

function renderResultAxisRangeControls(kind) {
  const range = state.axisRanges[kind] || {};
  return `
    <div class="axis-range-controls" aria-label="纵坐标显示范围">
      <button type="button" class="axis-range-toggle">纵坐标配置</button>
      <div class="axis-range-panel">
        <label>最小值<input type="number" step="any" data-result-axis-min="${escapeHtml(kind)}" value="${escapeHtml(range.min ?? "")}" placeholder="自动"></label>
        <label>最大值<input type="number" step="any" data-result-axis-max="${escapeHtml(kind)}" value="${escapeHtml(range.max ?? "")}" placeholder="自动"></label>
        <button type="button" data-result-axis-reset="${escapeHtml(kind)}">自动</button>
      </div>
    </div>`;
}

function applyAxisRange(autoMin, autoMax, range = {}) {
  const min = storedAxisNumber(range.min);
  const max = storedAxisNumber(range.max);
  const hasMin = Number.isFinite(min);
  const hasMax = Number.isFinite(max);
  if (hasMin && hasMax && max > min) return { min, max };
  if (hasMin && !hasMax) return { min, max: Math.max(autoMax, min + 1) };
  if (!hasMin && hasMax) return { min: Math.min(autoMin, max - 1), max };
  return { min: autoMin, max: autoMax };
}

function storedAxisNumber(value, fallback = null) {
  const helper = window.PowerPlanPageState?.number;
  if (typeof helper === "function") return helper(value, fallback);
  return value !== null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function normalizeAxisRanges(value) {
  if (!value || typeof value !== "object") return {};
  return Object.entries(value).reduce((next, [key, range]) => {
    if (!key || !range || typeof range !== "object") return next;
    const min = storedAxisNumber(range.min);
    const max = storedAxisNumber(range.max);
    const normalized = {};
    if (Number.isFinite(min)) normalized.min = min;
    if (Number.isFinite(max)) normalized.max = max;
    if (Object.keys(normalized).length) next[String(key)] = normalized;
    return next;
  }, {});
}

document.addEventListener("DOMContentLoaded", () => {
  restoreEvaluationPageState();
  state.evaluationCurveViewer = window.ResultCurveViewer
    ? window.ResultCurveViewer.create({
        listId: "evaluationCurveNameList",
        chartId: "evaluationCurveChart",
        emptyText: "暂无小时级曲线",
        promptText: "请选择小时级曲线",
        stateKey: "evaluation-result-curves",
        onSelectionChange: () => syncEvaluationCurveViewerIfHourlyActive(),
      })
    : null;
  bindResultTabs();
  bindOptimizationActions();
  bindEvaluationResultActions();
  bindLogContextMenu({
    boxId: "evaluationLogs",
    emptyText: "暂无评估日志",
    clearLogs: clearEvaluationLogs,
    saveLogs: saveEvaluationLogs,
  });
  bindSeriesToggleButtons();
  bindResultAxisRangeControls();
  bindEvaluationMainResizeHandle();
  bindEvaluationSchemeListResizeHandle();
  window.addEventListener("resize", () => {
    clampEvaluationMainWidth();
    if (state.evaluationSchemeRailHeight) setEvaluationSchemeRailHeight(state.evaluationSchemeRailHeight);
    else setEvaluationSchemeRailHeight(evaluationSchemeRailHeightBounds().max);
  });
  loadSchemes()
    .then(() => loadEvaluationResults())
    .then(() => refreshOptimizationStatus(state.currentScheme, state.selectedResultFile))
    .catch(showError);
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
    // 选择记忆只是体验增强，存储不可用时不影响主流程。
  }
}

function storedEvaluationSelection() {
  const previous = readStoredJson(EVALUATION_SELECTION_STORAGE_KEY, {}) || {};
  const stored = {
    ...previous,
    scheme: state.currentScheme || restoredEvaluationPageState.currentScheme || previous.scheme || "",
    result: state.selectedResultFile || restoredEvaluationPageState.selectedResultFile || previous.result || "",
  };
  if (!stored || typeof stored !== "object") return { scheme: "", result: "" };
  return {
    scheme: String(stored.scheme || ""),
    result: String(stored.result || ""),
  };
}

function rememberEvaluationSelection() {
  writeStoredJson(EVALUATION_SELECTION_STORAGE_KEY, {
    scheme: state.currentScheme || "",
    result: state.selectedResultFile || "",
  });
  rememberEvaluationPageState({
    currentScheme: state.currentScheme || "",
    selectedResultFile: state.selectedResultFile || "",
  });
}

async function loadSchemes() {
  state.schemes = (await api("/api/planning/schemes")).schemes || [];
  const remembered = storedEvaluationSelection();
  if (state.currentScheme && !state.schemes.some((scheme) => scheme.name === state.currentScheme)) {
    state.currentScheme = "";
    state.selectedResultFile = "";
  }
  if (!state.currentScheme && state.schemes.some((scheme) => scheme.name === remembered.scheme)) {
    state.currentScheme = remembered.scheme;
  }
  if (!state.currentScheme && state.schemes.length) state.currentScheme = state.schemes[0].name;
  renderSchemes();
  loadEvaluationResultTree().catch(showError);
  renderCurrentScheme();
}

function renderSchemes() {
  const list = document.getElementById("schemeList");
  if (!state.schemes.length) {
    list.innerHTML = '<div class="validation-item">暂无方案，请先在参数维护中新建方案。</div>';
    return;
  }
  list.innerHTML = `<ul class="scheme-list-items evaluation-scheme-tree" role="tree">${state.schemes
    .map((scheme) => renderEvaluationSchemeTreeNode(scheme))
    .join("")}</ul>`;
  list.querySelectorAll("[data-scheme-tree-toggle]").forEach((toggle) => {
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleEvaluationSchemeCollapsed(toggle.dataset.schemeTreeToggle || "");
    });
  });
  list.querySelectorAll(".scheme-item[data-name]").forEach((item) => {
    bindSchemeListItem(item, () => {
      state.currentScheme = item.dataset.name || "";
      renderSchemes();
      clearEvaluationDisplayForSchemeSwitch(state.currentScheme);
      loadEvaluationResults()
        .then(() => refreshOptimizationStatus(state.currentScheme, state.selectedResultFile))
        .catch((error) => {
          state.isSwitchingResult = false;
          showError(error);
        });
    });
  });
  list.querySelectorAll(".scheme-result-item").forEach((item) => {
    bindSchemeListItem(item, () => {
      state.currentScheme = item.dataset.scheme || "";
      state.selectedResultFile = item.dataset.result || "";
      renderSchemes();
      clearEvaluationResultDisplayForSwitch(state.selectedResultFile);
      loadEvaluationResults(state.selectedResultFile)
        .then(() => refreshOptimizationStatus(state.currentScheme, state.selectedResultFile))
        .catch((error) => {
          state.isSwitchingResult = false;
          showError(error);
        });
    });
  });
  updateEvaluationSchemeListResizeHandle();
}

function bindSchemeListItem(item, onSelect) {
  item.addEventListener("click", onSelect);
  item.addEventListener("keydown", (event) => {
    if (item.dataset.name && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      event.preventDefault();
      setEvaluationSchemeCollapsed(item.dataset.name, event.key === "ArrowLeft");
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  });
}

function renderEvaluationSchemeTreeNode(scheme) {
  const schemeName = scheme.name || "";
  const activeScheme = schemeName === state.currentScheme;
  const results = state.resultsByScheme[schemeName];
  const collapsed = state.collapsedSchemes.has(schemeName);
  const hasResults = Array.isArray(results) && results.length > 0;
  const resultItems = Array.isArray(results)
    ? results.map((item) => renderEvaluationResultTreeItem(schemeName, item)).join("")
    : '<li class="scheme-result-empty">正在读取结果...</li>';
  return `<li class="scheme-tree-node${activeScheme ? " active" : ""}" role="none">
    <div class="scheme-item scheme-tree-parent ${activeScheme ? "active" : ""}" data-name="${escapeHtml(schemeName)}" role="treeitem" aria-selected="${activeScheme ? "true" : "false"}" aria-expanded="${collapsed ? "false" : "true"}" tabindex="0">
      <span class="scheme-tree-caret ${collapsed ? "collapsed" : ""}" data-scheme-tree-toggle="${escapeHtml(schemeName)}" aria-hidden="true">${collapsed ? "▸" : "▾"}</span>
      <span class="scheme-tree-label">${escapeHtml(schemeName)}</span>
    </div>
    <ul class="scheme-result-list" role="group" ${collapsed ? "hidden" : ""}>
      ${hasResults ? resultItems : Array.isArray(results) ? '<li class="scheme-result-empty">暂无结果</li>' : resultItems}
    </ul>
  </li>`;
}

function renderEvaluationResultTreeItem(schemeName, item) {
  const name = item?.name || "";
  const active = schemeName === state.currentScheme && name === state.selectedResultFile;
  const readable = item?.readable !== false;
  const label = resultDisplayName(name) || name;
  const title = readable ? label : `${label}（无法读取）`;
  return `<li class="scheme-result-item ${active ? "active" : ""} ${readable ? "" : "unreadable"}" data-scheme="${escapeHtml(schemeName)}" data-result="${escapeHtml(name)}" role="treeitem" aria-selected="${active ? "true" : "false"}" tabindex="0" title="${escapeHtml(title)}">
    <span>${escapeHtml(label)}</span>
  </li>`;
}

async function loadEvaluationResultTree() {
  const schemes = state.schemes.map((scheme) => scheme.name).filter(Boolean);
  await Promise.all(schemes.map(async (schemeName) => {
    if (Array.isArray(state.resultsByScheme[schemeName])) return;
    const data = await api(`/api/evaluation/results?scheme=${encodeURIComponent(schemeName)}&light=1`);
    state.resultsByScheme[schemeName] = data.results || [];
  }));
  renderSchemes();
}

function toggleEvaluationSchemeCollapsed(schemeName) {
  if (!schemeName) return;
  setEvaluationSchemeCollapsed(schemeName, !state.collapsedSchemes.has(schemeName));
}

function setEvaluationSchemeCollapsed(schemeName, collapsed) {
  if (!schemeName) return;
  if (collapsed) state.collapsedSchemes.add(schemeName);
  else state.collapsedSchemes.delete(schemeName);
  renderSchemes();
  rememberEvaluationPageState({ collapsedSchemes: Array.from(state.collapsedSchemes) });
}

function renderCurrentScheme() {
  const current = document.getElementById("optimizationCurrentScheme");
  if (!current) return;
  current.textContent = currentEvaluationResultLabel();
  renderCurrentEvaluationResultTitle();
}

function bindOptimizationActions() {
  document.getElementById("startEvaluation").addEventListener("click", () => controlOptimization("start"));
  document.getElementById("queueEvaluation")?.addEventListener("click", () => controlOptimization("queue"));
  document.getElementById("stopEvaluation").addEventListener("click", () => controlOptimization(terminalEvaluationAction()));
}

function bindEvaluationResultActions() {
  document.getElementById("deleteEvaluationResult").addEventListener("click", () => manageEvaluationResult("delete"));
  document.getElementById("copyEvaluationResult").addEventListener("click", copyEvaluationResult);
  document.getElementById("saveEvaluationResult").addEventListener("click", saveEvaluationResult);
  document.getElementById("renameEvaluationResult").addEventListener("click", renameEvaluationResult);
}

function clearEvaluationDisplayForSchemeSwitch(scheme = state.currentScheme) {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.isSwitchingResult = true;
  state.resultFiles = [];
  state.selectedResultFile = "";
  renderCurrentScheme();
  state.planningResultRows = [];
  state.curveDataKey = "";
  state.curvePayload = null;
  state.loadedCurveKeys = new Set();
  state.hourlyCurvePreloadToken += 1;
  state.lastOptimizationRenderSignature = "";
  state.greenDailyPoints = [];
  state.safetyDailyPoints = [];
  state.optimization = defaultOptimizationState(scheme);
  state.optimization = renderEvaluationSchemeSwitchingState(scheme, state.optimization);
  renderEvaluationResults();
  renderEvaluationPlanningResultTable();
  renderOptimization(state.optimization);
  state.evaluationCurveViewer?.clear("正在加载小时级曲线");
}

function renderEvaluationSchemeSwitchingState(scheme, base = defaultOptimizationState(scheme)) {
  return {
    ...base,
    status: "切换中",
    metrics: [
      { label: "状态", value: "切换中", unit: "" },
      { label: "开始", value: "-", unit: "" },
      { label: "完成", value: "-", unit: "" },
      { label: "度电成本", value: "-", unit: "元" },
      { label: "绿电占比", value: "-", unit: "%" },
    ],
    results: {
      overview_tables: [
        { title: "规划结果", rows: [] },
      ],
      overview_disks: defaultOverviewDisks(),
      green: [],
      green_table: [],
      safety: [],
      safety_table: [],
      curves: { green: [], green_daily: [], safety: [], safety_daily: [] },
    },
    logs: [{ time: "", level: "info", message: `正在切换方案：${scheme || "未选择方案"}` }],
  };
}

function clearEvaluationResultDisplayForSwitch(filename = state.selectedResultFile) {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.isSwitchingResult = true;
  state.curveDataKey = "";
  state.curvePayload = null;
  state.loadedCurveKeys = new Set();
  state.hourlyCurvePreloadToken += 1;
  state.lastOptimizationRenderSignature = "";
  renderCurrentScheme();
  state.planningResultRows = [];
  state.greenDailyPoints = [];
  state.safetyDailyPoints = [];
  state.optimization = defaultOptimizationState(state.currentScheme);
  state.optimization = renderEvaluationSwitchingState(filename, state.optimization);
  renderEvaluationPlanningResultTable();
  renderOptimization(state.optimization);
  state.evaluationCurveViewer?.clear("正在加载小时级曲线");
  updateEvaluationResultActions();
}

function renderEvaluationSwitchingState(filename, base = defaultOptimizationState(state.currentScheme)) {
  const displayName = resultDisplayName(filename) || "当前结果";
  return {
    ...base,
    status: "切换中",
    metrics: [
      { label: "状态", value: "切换中", unit: "" },
      { label: "开始", value: "-", unit: "" },
      { label: "完成", value: "-", unit: "" },
      { label: "度电成本", value: "-", unit: "元" },
      { label: "绿电占比", value: "-", unit: "%" },
    ],
    results: {
      overview_tables: [
        { title: "规划结果", rows: [] },
      ],
      overview_disks: defaultOverviewDisks(),
      green: [],
      green_table: [],
      safety: [],
      safety_table: [],
      curves: { green: [], green_daily: [], safety: [], safety_daily: [] },
    },
    logs: [{ time: "", level: "info", message: `正在切换结果：${displayName}` }],
  };
}

async function loadEvaluationResults(selected = state.selectedResultFile) {
  if (!state.currentScheme) {
    state.resultFiles = [];
    state.selectedResultFile = "";
    state.planningResultRows = [];
    renderEvaluationResults();
    renderEvaluationPlanningResultTable();
    state.curveDataKey = "";
    state.evaluationCurveViewer?.clear("请先选择方案");
    return;
  }
  const remembered = storedEvaluationSelection();
  const requestedSelected = selected || (remembered.scheme === state.currentScheme ? remembered.result : "");
  const selectedParam = requestedSelected ? `&filename=${encodeURIComponent(requestedSelected)}` : "";
  const data = await api(`/api/evaluation/results?scheme=${encodeURIComponent(state.currentScheme)}${selectedParam}`);
  state.resultFiles = data.results || [];
  state.resultsByScheme[state.currentScheme] = state.resultFiles;
  const readableNames = state.resultFiles.filter((item) => item.readable !== false).map((item) => item.name);
  state.selectedResultFile = data.selected || (readableNames.includes(requestedSelected) ? requestedSelected : readableNames[0] || "");
  rememberEvaluationSelection();
  renderCurrentScheme();
  renderSchemes();
  state.planningResultRows = data.planning_result_rows || [];
  renderEvaluationResults();
  renderEvaluationPlanningResultTable();
  if (state.activeResultTab === "curves" && !state.isSwitchingResult) loadEvaluationCurveData().catch(showError);
}

function renderEvaluationResults() {
  renderCurrentEvaluationResultTitle();
  renderEvaluationResultWarnings();
  updateEvaluationResultActions();
}

function renderEvaluationResultWarnings() {
  const host = document.getElementById("evaluationResultWarnings");
  if (!host) return;
  const unreadable = state.resultFiles.filter((item) => item.readable === false);
  host.innerHTML = unreadable
    .map((item) => `<div class="validation-item error">结果文件 ${escapeHtml(item.name)} ${escapeHtml(item.message || "无法读取，请重新生成或删除该文件。")}</div>`)
    .join("");
  host.hidden = unreadable.length === 0;
}

function resultDisplayName(filename) {
  return String(filename || "").replace(/_results\.xlsx$/, "");
}

function currentEvaluationResultLabel() {
  const schemeName = state.currentScheme || "未选择方案";
  const resultName = resultDisplayName(state.selectedResultFile) || "未选择结果";
  return `当前: ${schemeName}/${resultName}`;
}

function renderCurrentEvaluationResultTitle() {
  const title = document.getElementById("evaluationPlanningResultTitle");
  if (!title) return;
  title.textContent = `当前结果:${resultDisplayName(state.selectedResultFile) || "未选择结果"}`;
}

function renderEvaluationPlanningResultTable() {
  const container = document.getElementById("evaluationPlanningResultTable");
  if (!container) return;
  const rows = Array.isArray(state.planningResultRows) ? state.planningResultRows : [];
  if (!rows.length) {
    container.innerHTML = '<div class="empty-summary">暂无规划结果</div>';
    return;
  }
  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>设备类型</th>
          <th>设计台数</th>
          <th>单台容量</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(renderEvaluationPlanningResultRow).join("")}
      </tbody>
    </table>`;
}

function renderEvaluationPlanningResultRow(row, index) {
  const disabled = selectedResultIsDefault() ? " disabled" : "";
  return `
    <tr>
      <td>${escapeHtml(row["设备类型"] ?? "")}</td>
      <td><input type="number" step="1" min="0" inputmode="numeric" pattern="[0-9]*" data-planning-count-index="${index}" value="${escapeHtml(row["设计台数"] ?? "")}"${disabled}></td>
      <td>${escapeHtml(row["单台容量"] ?? "")}</td>
    </tr>`;
}

async function saveEvaluationResult() {
  if (!validatePlanningCountInput()) return;
  await manageEvaluationResult("save", { planning_result_rows: collectPlanningResultRows() });
}

function validatePlanningCountInput() {
  for (const input of document.querySelectorAll("[data-planning-count-index]")) {
    if (!/^\d+$/.test(input.value)) {
      alert("设计台数必须为非负整数");
      input.focus();
      return false;
    }
  }
  return true;
}

function collectPlanningResultRows() {
  const rows = (Array.isArray(state.planningResultRows) ? state.planningResultRows : []).map((row) => ({ ...row }));
  document.querySelectorAll("[data-planning-count-index]").forEach((input) => {
    const index = Number(input.dataset.planningCountIndex);
    if (!Number.isInteger(index) || !rows[index]) return;
    rows[index]["设计台数"] = Number.parseInt(input.value, 10);
  });
  return rows;
}

function selectedResultIsDefault() {
  return state.selectedResultFile === "opt_results.xlsx";
}

function selectedResultIsReadable() {
  const selected = state.resultFiles.find((item) => item.name === state.selectedResultFile);
  return !selected || selected.readable !== false;
}

function updateEvaluationResultActions() {
  const hasScheme = Boolean(state.currentScheme);
  const hasSelection = Boolean(state.selectedResultFile);
  const canEditWorkbook = selectedResultIsReadable() && !selectedResultIsDefault();
  const deleteButton = document.getElementById("deleteEvaluationResult");
  const copyButton = document.getElementById("copyEvaluationResult");
  const saveButton = document.getElementById("saveEvaluationResult");
  const renameButton = document.getElementById("renameEvaluationResult");
  deleteButton.disabled = selectedResultIsDefault() || !hasScheme || !hasSelection;
  saveButton.disabled = !canEditWorkbook || !hasScheme || !hasSelection;
  copyButton.disabled = !selectedResultIsReadable() || !hasScheme || !hasSelection;
  renameButton.disabled = !canEditWorkbook || !hasScheme || !hasSelection;
  [deleteButton, copyButton, saveButton, renameButton].forEach((button) => {
    button.classList.toggle("is-disabled", button.disabled);
    button.setAttribute("aria-disabled", String(button.disabled));
  });
  document.querySelectorAll("[data-planning-count-index]").forEach((input) => {
    input.disabled = !canEditWorkbook || !hasScheme || !hasSelection;
  });
}

async function copyEvaluationResult() {
  if (!state.selectedResultFile) {
    alert("请先选择结果文件");
    return;
  }
  const targetName = prompt("请输入新结果名称", `${resultDisplayName(state.selectedResultFile) || "当前结果"}_副本`);
  if (targetName === null) return;
  await manageEvaluationResult("copy", { target_name: targetName.trim() });
}

async function renameEvaluationResult() {
  if (!state.selectedResultFile) {
    alert("请先选择结果文件");
    return;
  }
  if (selectedResultIsDefault()) {
    alert("默认结果文件不允许重命名");
    return;
  }
  const targetName = prompt("请输入新的结果名称", resultDisplayName(state.selectedResultFile) || "");
  if (targetName === null) return;
  await manageEvaluationResult("rename", { target_name: targetName.trim() });
}

async function manageEvaluationResult(action, extra = {}) {
  if (!state.currentScheme) {
    alert("请先选择方案");
    return;
  }
  if (!state.selectedResultFile) {
    alert("请先选择结果文件");
    return;
  }
  try {
    const data = await api("/api/evaluation/results", {
      method: "POST",
      body: JSON.stringify({
        scheme: state.currentScheme,
        action,
        filename: state.selectedResultFile,
        ...extra,
      }),
    });
    state.resultFiles = data.results || [];
    state.selectedResultFile = data.selected || state.selectedResultFile;
    rememberEvaluationSelection();
    renderCurrentScheme();
    state.planningResultRows = data.planning_result_rows || state.planningResultRows || [];
    state.curveDataKey = "";
    state.curvePayload = null;
    state.loadedCurveKeys = new Set();
    state.hourlyCurvePreloadToken += 1;
    renderEvaluationResults();
    renderEvaluationPlanningResultTable();
    if (state.activeResultTab === "curves") loadEvaluationCurveData().catch(showError);
    renderEvaluationMessage(action, data.selected);
  } catch (error) {
    const data = error.payload || {};
    if (data.message) alert(data.message);
    else if (action === "copy") alert("复制失败");
    else if (action === "rename") alert("重命名失败");
    else showError(error);
    await loadEvaluationResults().catch(showError);
  }
}

function renderEvaluationMessage(action, filename) {
  const messages = {
    delete: "结果文件已删除",
    copy: `结果文件已复制：${filename || ""}`,
    save: `结果文件已保存：${filename || state.selectedResultFile}`,
    rename: `结果文件已重命名：${filename || ""}`,
  };
  const message = messages[action];
  if (!message) return;
  const box = document.getElementById("evaluationLogs");
  if (box) {
    box.insertAdjacentHTML(
      "beforeend",
      `<div class="log-line ok"><span>${escapeHtml(new Date().toLocaleString("zh-CN"))}</span><strong>${escapeHtml(message)}</strong></div>`,
    );
    box.scrollTop = box.scrollHeight;
  }
  alert(message);
}

async function controlOptimization(action) {
  if (!state.currentScheme) {
    alert("请先选择方案");
    return;
  }
  try {
    const data = await api("/api/tasks/control", {
      method: "POST",
      body: JSON.stringify({
        action,
        task_type: "evaluation",
        scheme: state.currentScheme,
        result: state.selectedResultFile,
      }),
    });
    await refreshOptimizationStatus(state.currentScheme, state.selectedResultFile);
    scheduleOptimizationPolling();
  } catch (error) {
    const data = error.payload || {};
    if (data.error === "running") alert(data.message || "正在运行，无法再次启动");
    else if (data.error === "not_running") alert(data.message || "没有运行");
    else if (data.message) alert(data.message);
    else showError(error);
    await refreshOptimizationStatus().catch(showError);
  }
}

async function clearEvaluationLogs() {
  if (!state.currentScheme) return;
  const data = await api("/api/evaluation/control", {
    method: "POST",
    body: JSON.stringify({
      action: "clear_logs",
      scheme: state.currentScheme,
      filename: state.selectedResultFile,
    }),
  });
  state.optimization = data.state;
  renderOptimization(data.state);
}

function saveEvaluationLogs() {
  const logs = state.optimization?.logs || [];
  const resultName = state.selectedResultFile ? `_${state.selectedResultFile.replace(/_results\.xlsx$/i, "")}` : "";
  saveLogsToFile(logs, `方案评估_${state.currentScheme || "未选择方案"}${resultName}_运行日志`);
}

async function refreshOptimizationStatus(scheme = state.currentScheme, filename = state.selectedResultFile) {
  const data = await api(optimizationStatusPath(scheme, filename));
  if (scheme !== state.currentScheme || filename !== state.selectedResultFile) return;
  state.isSwitchingResult = false;
  state.optimization = data;
  renderOptimization(data);
  scheduleOptimizationPolling();
}

function optimizationStatusPath(scheme, filename = state.selectedResultFile) {
  if (!scheme) return "/api/evaluation/status?light=1";
  const filenameParam = filename ? `&filename=${encodeURIComponent(filename)}` : "";
  return `/api/evaluation/status?scheme=${encodeURIComponent(scheme)}${filenameParam}&light=1`;
}

function scheduleOptimizationPolling() {
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  const data = state.optimization || {};
  state.pollDelay = data.status === "运行中" || data.task_status === "排队中" ? 1000 : 4000;
  state.pollTimer = window.setInterval(() => {
    refreshOptimizationStatus(state.currentScheme, state.selectedResultFile).catch(showError);
  }, state.pollDelay);
}

function bindResultTabs() {
  document.querySelectorAll("[data-result-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activateEvaluationResultTab(button.dataset.resultTab || "overview");
    });
  });
  activateEvaluationResultTab(state.activeResultTab, { remember: false, load: false });
}

function activateEvaluationResultTab(target, options = {}) {
  const buttons = Array.from(document.querySelectorAll("[data-result-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-result-panel]"));
  const activeTarget = buttons.some((button) => button.dataset.resultTab === target) ? target : "overview";
  state.activeResultTab = activeTarget;
  buttons.forEach((item) => {
    const active = item.dataset.resultTab === activeTarget;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  panels.forEach((panel) => {
    const active = panel.dataset.resultPanel === activeTarget;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  if (options.remember !== false) rememberEvaluationPageState({ activeResultTab: activeTarget });
  if (activeTarget === "curves" && options.load !== false) loadEvaluationCurveData().catch(showError);
  window.requestAnimationFrame(refreshAdaptiveResultCharts);
}

function renderOptimization(data) {
  const renderSignature = JSON.stringify(data || {});
  if (renderSignature && renderSignature === state.lastOptimizationRenderSignature) return;
  state.lastOptimizationRenderSignature = renderSignature;
  updateOptimizationActions(data);
  renderMetrics(data.metrics || []);
  const allowEmptyResult = data.status === "切换中";
  renderOverviewTables(data.results?.overview_tables || defaultOverviewTables(), data.results?.overview_disks || defaultOverviewDisks());
  renderGreenResult(data.results?.green_table || [], data.results?.curves?.green_daily || [], { allowEmpty: allowEmptyResult });
  renderSafetyResult(data.results?.safety_table || [], data.results?.curves?.safety_daily || [], { allowEmpty: allowEmptyResult });
  bindOverviewColumnResizeHandles();
  bindResultColumnResizeHandles();
  bindAdaptiveResultCharts();
  bindChartHoverCursors();
  renderOptimizationLogs(data.logs || []);
  if (state.activeResultTab === "curves" && !state.isSwitchingResult) loadEvaluationCurveData().catch(showError);
}

async function loadEvaluationCurveData() {
  if (!state.currentScheme || !state.selectedResultFile || !state.evaluationCurveViewer) {
    state.evaluationCurveViewer?.clear("请先选择方案和结果");
    return;
  }
  const runKey = state.optimization?.end_time || state.optimization?.status || "";
  const key = `${state.currentScheme}/${state.selectedResultFile}/${runKey}`;
  if (state.curveDataKey === key) return;
  state.curveDataKey = key;
  state.curvePayload = null;
  state.loadedCurveKeys = new Set();
  state.hourlyCurvePreloadToken += 1;
  state.evaluationCurveViewer.clear("正在加载小时级曲线");
  const items = [{ scheme: state.currentScheme, filename: state.selectedResultFile }];
  try {
    const data = await api(`/api/comparison/data?mode=summary&items=${encodeURIComponent(JSON.stringify(items))}`);
    if (key !== state.curveDataKey) return;
    state.curvePayload = data;
    state.evaluationCurveViewer.setData(data);
    scheduleEvaluationHourlyCurvePreload(items, key, data.curves || [], state.hourlyCurvePreloadToken);
  } catch (error) {
    state.curveDataKey = "";
    state.curvePayload = null;
    state.loadedCurveKeys = new Set();
    state.hourlyCurvePreloadToken += 1;
    state.evaluationCurveViewer.clear(error.payload?.message || error.message || "暂无小时级曲线");
  }
}

function scheduleEvaluationHourlyCurvePreload(items, key, curveNames, token) {
  const names = uniqueCurveNames(curveNames);
  if (!items.length || !names.length) return;
  window.setTimeout(() => {
    preloadEvaluationHourlyCurves(items, key, names, token).catch(showError);
  }, HOURLY_CURVE_PRELOAD_DELAY_MS);
}

async function preloadEvaluationHourlyCurves(items, key, curveNames, token) {
  for (let index = 0; index < curveNames.length; index += HOURLY_CURVE_PRELOAD_BATCH_SIZE) {
    if (state.curveDataKey !== key || state.hourlyCurvePreloadToken !== token) return;
    const batch = curveNames
      .slice(index, index + HOURLY_CURVE_PRELOAD_BATCH_SIZE)
      .filter((name) => !state.loadedCurveKeys.has(curveLoadKey(key, "hourly", name)));
    if (!batch.length) continue;
    const data = await api(
      `/api/comparison/data?mode=curves&group=hourly&curves=${encodeURIComponent(JSON.stringify(batch))}&items=${encodeURIComponent(JSON.stringify(items))}`,
    );
    if (state.curveDataKey !== key || state.hourlyCurvePreloadToken !== token) return;
    state.curvePayload = mergeCurvePayload(state.curvePayload || {}, data);
    batch.forEach((name) => state.loadedCurveKeys.add(curveLoadKey(key, "hourly", name)));
    syncEvaluationCurveViewerIfHourlyActive();
    if (index + HOURLY_CURVE_PRELOAD_BATCH_SIZE < curveNames.length) {
      await delay(HOURLY_CURVE_PRELOAD_BATCH_DELAY_MS);
    }
  }
}

function syncEvaluationCurveViewerIfHourlyActive() {
  const selection = state.evaluationCurveViewer?.getSelection?.();
  if (selection?.group !== "hourly" || !state.curvePayload) return;
  state.evaluationCurveViewer.setData(state.curvePayload);
}

function uniqueCurveNames(curveNames) {
  return Array.from(new Set((curveNames || []).map((name) => String(name || "").trim()).filter(Boolean)));
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function curveLoadKey(itemsKey, group, name) {
  return `${itemsKey}|${group}|${name}`;
}

function mergeCurvePayload(base, data) {
  const nextGroups = { ...(base.curve_groups || {}) };
  Object.entries(data.curve_groups || {}).forEach(([groupKey, groupData]) => {
    const current = nextGroups[groupKey] || { title: groupData?.title || "", curves: [], series: {} };
    const curves = [...(current.curves || [])];
    (groupData?.curves || []).forEach((name) => {
      if (!curves.includes(name)) curves.push(name);
    });
    const series = { ...(current.series || {}) };
    Object.entries(groupData?.series || {}).forEach(([curveName, curveSeries]) => {
      series[curveName] = Array.isArray(curveSeries) ? curveSeries : [];
    });
    nextGroups[groupKey] = { title: groupData?.title || current.title || "", curves, series };
  });
  const hourly = nextGroups.hourly || { curves: [], series: {} };
  return {
    ...base,
    items: data.items?.length ? data.items : base.items || [],
    curve_groups: nextGroups,
    annual_table: data.annual_table?.length ? data.annual_table : base.annual_table || [],
    curves: hourly.curves || [],
    series: hourly.series || {},
  };
}

function updateOptimizationActions(data = state.optimization || {}) {
  const startButton = document.getElementById("startEvaluation");
  const queueButton = document.getElementById("queueEvaluation");
  const stopButton = document.getElementById("stopEvaluation");
  if (!startButton || !stopButton) return;
  const hasScheme = Boolean(state.currentScheme);
  const hasResult = Boolean(state.selectedResultFile);
  const isRunning = data.status === "运行中";
  startButton.disabled = !hasScheme || !hasResult || (typeof data.can_start_task === "boolean" ? !data.can_start_task : isRunning);
  if (queueButton) queueButton.disabled = !hasScheme || !hasResult || (typeof data.can_queue_task === "boolean" ? !data.can_queue_task : isRunning);
  const canExitOrStop = Boolean(data.can_cancel_queue_task || data.can_stop_task);
  stopButton.disabled = !hasScheme || !hasResult || !canExitOrStop;
  stopButton.textContent = data.can_cancel_queue_task ? "离队" : "停止";
  [startButton, queueButton, stopButton].filter(Boolean).forEach((button) => {
    button.classList.toggle("is-disabled", button.disabled);
    button.classList.toggle("is-active", !button.disabled);
    button.setAttribute("aria-disabled", String(button.disabled));
  });
  startButton.title = !hasScheme ? "请先选择方案" : !hasResult ? "请先选择结果文件" : isRunning ? "当前方案正在评估" : "启动当前方案评估";
  if (queueButton) queueButton.title = !hasScheme ? "请先选择方案" : !hasResult ? "请先选择结果文件" : data.queued ? "当前评估任务已加入队列" : "将当前评估任务排队";
  stopButton.title = !hasScheme ? "请先选择方案" : !hasResult ? "请先选择结果文件" : data.can_cancel_queue_task ? "从队列中移出当前评估任务" : isRunning ? "停止当前方案评估" : "当前方案没有运行";
}

function terminalEvaluationAction() {
  return state.optimization?.can_cancel_queue_task ? "cancel_queue" : "stop";
}

function defaultOptimizationState(scheme = "") {
  return {
    status: "待启动",
    scheme,
    start_time: "",
    end_time: "",
    progress: 0,
    metrics: [
      { label: "状态", value: "待启动", unit: "" },
      { label: "开始", value: "-", unit: "" },
      { label: "完成", value: "-", unit: "" },
      { label: "度电成本", value: "-", unit: "元" },
      { label: "绿电占比", value: "-", unit: "%" },
    ],
    results: {
      overview_tables: defaultOverviewTables(),
      overview_disks: defaultOverviewDisks(),
      green: [],
      green_table: defaultGreenTable(),
      safety: [],
      safety_table: defaultSafetyTable(),
      curves: { green: [], green_daily: [], safety: [], safety_daily: [] },
    },
    logs: [{ time: "", level: "", message: "正在加载当前方案评估状态" }],
    running_schemes: [],
  };
}

function renderMetrics(metrics) {
  const byLabel = new Map(metrics.map((item) => [item.label, item]));
  setMetric("optimizationStatus", byLabel.get("状态"));
  setMetric("optimizationStartTime", byLabel.get("开始"));
  setMetric("optimizationEndTime", byLabel.get("完成"));
  setMetric("evaluationScore", byLabel.get("度电成本"));
  setMetric("evaluationRisk", byLabel.get("绿电占比"));
}

function setMetric(id, item) {
  const element = document.getElementById(id);
  if (!element) return;
  if (!item) {
    element.textContent = "-";
    return;
  }
  const unit = item.unit ? ` ${item.unit}` : "";
  element.textContent = `${formatMetricValue(item)}${unit}`;
}

function defaultOverviewTables() {
  return [
    { title: "规划结果", rows: [{ "名称": "-", "设计台数": "-", "单台容量": "-", "总容量": "-", "单位": "" }] },
  ];
}

function defaultOverviewDisks() {
  return [
    { title: "成本构成", left_label: "运行成本", left_value: 0, right_label: "建设成本", right_value: 0, unit: "万元" },
    {
      title: "容量构成",
      unit: "kW/kWh",
      segments: [
        { label: "柴发容量", value: 0, unit: "kW" },
        { label: "风电容量", value: 0, unit: "kW" },
        { label: "光伏容量", value: 0, unit: "kW" },
        { label: "电储能容量", value: 0, unit: "kWh" },
        { label: "燃料电池容量", value: 0, unit: "kW" },
      ],
    },
    { title: "电量构成", left_label: "柴发电量", left_value: 0, right_label: "新能源电量", right_value: 0, unit: "MWh" },
  ];
}

function defaultGreenTable() {
  return [
    { "指标": "负荷总电量", "数值": "-", "单位": "kWh" },
    { "指标": "柴发总电量", "数值": "-", "单位": "kWh" },
    { "指标": "风机总发电量", "数值": "-", "单位": "kWh" },
    { "指标": "光伏总发电量", "数值": "-", "单位": "kWh" },
    { "指标": "电储总发电量", "数值": "-", "单位": "kWh" },
    { "指标": "氢储总发电量", "数值": "-", "单位": "kWh" },
    { "指标": "新能源总弃电量", "数值": "-", "单位": "kWh" },
    { "指标": "新能源占比", "数值": "-", "单位": "%" },
    { "指标": "新能源弃电率", "数值": "-", "单位": "%" },
    { "指标": "柴油消耗", "数值": "-", "单位": "吨" },
    { "指标": "制氢总量", "数值": "-", "单位": "Nm3" },
  ];
}

function defaultSafetyTable() {
  return [
    { "指标": "向上扰动最大量", "数值": "-", "单位": "kW" },
    { "指标": "向下扰动最大量", "数值": "-", "单位": "kW" },
    { "指标": "最高频率", "数值": "-", "单位": "Hz" },
    { "指标": "最低频率", "数值": "-", "单位": "Hz" },
    { "指标": "频率安全风险小时数", "数值": "-", "单位": "h" },
  ];
}

function renderOverviewTables(tables, disks) {
  const panel = document.getElementById("overviewResult");
  if (!panel) return;
  const safeTables = tables.length ? tables : defaultOverviewTables();
  const planningTable = safeTables.find((table) => table?.title === "规划结果") || safeTables[0] || defaultOverviewTables()[0];
  panel.innerHTML = `
    <div class="optimization-overview-grid">
      ${renderOverviewTableCard(planningTable)}
      <div class="overview-column-resize-handle" data-overview-column-resize="left-middle" role="separator" tabindex="0" aria-label="调整左侧规划结果和中间构成图宽度" aria-orientation="vertical"></div>
      ${renderOverviewCompositionBars(disks?.length ? disks : defaultOverviewDisks())}
    </div>`;
}

function renderOverviewTableCard(table) {
  const displayTable = formatOverviewTableForDisplay(table);
  return `
    <section class="overview-table-card">
      <h2>${escapeHtml(displayTable.title || "")}</h2>
      <div class="data-table optimization-overview-table">${renderResultTable(displayTable.rows || [])}</div>
    </section>`;
}

function formatOverviewTableForDisplay(table = {}) {
  if (table.title !== "规划结果") return table;
  return { ...table, rows: formatOverviewPlanningRows(table.rows || []) };
}

function formatOverviewPlanningRows(rows) {
  return rows.map((row) => ({
    "名称": row["名称"] ?? row["设备类型"] ?? "",
    "设计台数": row["设计台数"] ?? "",
    "单台容量": row["单台容量"] ?? "",
    "总容量": row["总容量"] ?? "",
    "单位": row["单位"] ?? "",
  }));
}

function renderOverviewCompositionBars(disks) {
  return `<section class="overview-composition-stack">${disks.map(renderOverviewCompositionBar).join("")}</section>`;
}

const overviewCompositionColors = ["#0d5c59", "#d8b35d", "#3d7fc2", "#7b61a8", "#c76f45", "#2e9f78"];

function renderOverviewCompositionBar(disk) {
  const displayDisk = normalizeOverviewCompositionDisplay(disk);
  const segments = displayDisk.segments;
  const positiveTotal = segments.reduce((sum, segment) => sum + Math.max(0, segment.value), 0);
  const summarySegments = buildOverviewCompositionSummary(segments, positiveTotal);
  const multiClass = segments.length > 2 ? " multi-segment" : "";
  return `
    <div class="composition-bar-card${multiClass}">
      <h2>${escapeHtml(displayDisk.title)}</h2>
      <div class="composition-bar-summary">
        ${summarySegments
          .map((segment) => `<span class="${segment.isTotal ? "total" : ""}">
            <em class="composition-bar-summary-label">${segment.isTotal ? "" : `<i class="composition-bar-summary-dot" style="background:${escapeHtml(segment.color)}"></i>`}${escapeHtml(segment.label)}</em>
            <strong>${escapeHtml(formatOverviewCompositionNumber(segment.value, displayDisk.type))}${escapeHtml(segment.unit)}</strong>
            ${Number.isFinite(segment.percent) ? `<small class="composition-bar-percent">${Math.round(segment.percent)}%</small>` : ""}
          </span>`)
          .join("")}
      </div>
      <div class="composition-bar-track" aria-label="${escapeHtml(displayDisk.title)}">
        ${segments
          .map((segment) => {
            const percent = positiveTotal > 0 ? Math.max(0, (segment.value / positiveTotal) * 100) : 100 / segments.length;
            return `<div class="composition-bar-segment ${escapeHtml(segment.className)}" style="width:${percent.toFixed(2)}%;--composition-segment-color:${escapeHtml(segment.color)}"></div>`;
          })
          .join("")}
      </div>
    </div>`;
}

function normalizeOverviewCompositionDisplay(disk = {}) {
  const rawTitle = String(disk.title || "");
  const baseTitle = rawTitle.replace(/[（(]\s*单位[:：][^）)]*[）)]/g, "").trim() || rawTitle;
  const type = overviewCompositionType(baseTitle);
  const titleUnit = overviewCompositionTitleUnit(type, disk.unit);
  const segments = normalizeOverviewCompositionSegments(disk).map((segment) => {
    const unit = segment.unit || disk.unit || "";
    return {
      ...segment,
      label: simplifyOverviewCompositionLabel(segment.label, type),
      value: normalizeOverviewCompositionValue(segment.value, type, unit),
      unit: "",
    };
  });
  return {
    title: titleUnit ? `${baseTitle}(单位: ${titleUnit})` : baseTitle,
    type,
    segments,
  };
}

function overviewCompositionType(title) {
  if (title.includes("成本")) return "cost";
  if (title.includes("容量")) return "capacity";
  if (title.includes("电量")) return "energy";
  return "default";
}

function overviewCompositionTitleUnit(type, fallbackUnit = "") {
  if (type === "cost") return "万元";
  if (type === "capacity") return "kW";
  if (type === "energy") return "万kWh";
  return fallbackUnit || "";
}

function simplifyOverviewCompositionLabel(label, type) {
  let text = String(label || "").trim();
  if (type === "cost") text = text.replace(/成本/g, "");
  if (type === "capacity") text = text.replace(/容量/g, "");
  if (type === "energy") text = text.replace(/总发电量|总用电量|总电量|发电量|用电量|电量/g, "");
  if (type === "capacity" && text === "电储能") text = "电储";
  if (type === "capacity" && text === "燃料电池") text = "燃电";
  if (type === "energy" && text === "柴") text = "柴发";
  return text.trim() || label || "-";
}

function normalizeOverviewCompositionValue(value, type, unit = "") {
  const number = Number(value) || 0;
  if (type !== "energy") return number;
  const normalizedUnit = String(unit || "").trim().toLowerCase();
  if (normalizedUnit.includes("万")) return number;
  if (normalizedUnit.includes("mwh")) return number / 10;
  return number / 10000;
}

function formatOverviewCompositionNumber(value, type) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (type === "capacity") return Math.round(number).toLocaleString("zh-CN");
  return formatNumber(number);
}

function normalizeOverviewCompositionSegments(disk = {}) {
  if (Array.isArray(disk.segments) && disk.segments.length) {
    return disk.segments.map((segment, index) => ({
      label: segment.label ?? segment.name ?? "",
      value: Number(segment.value) || 0,
      unit: segment.unit ?? disk.unit ?? "",
      color: overviewCompositionColors[index % overviewCompositionColors.length],
      className: `segment-${index + 1}`,
      dotClass: `segment-dot-${index + 1}`,
    }));
  }
  return [
    {
      label: disk.left_label || "",
      value: Number(disk.left_value) || 0,
      unit: disk.unit || "",
      color: overviewCompositionColors[0],
      className: "primary",
      dotClass: "primary-dot",
    },
    {
      label: disk.right_label || "",
      value: Number(disk.right_value) || 0,
      unit: disk.unit || "",
      color: overviewCompositionColors[1],
      className: "secondary",
      dotClass: "secondary-dot",
    },
  ];
}

function buildOverviewCompositionSummary(segments, positiveTotal) {
  const usedUnits = [...new Set(segments.map((segment) => segment.unit).filter(Boolean))];
  const summary = segments.map((segment) => ({
    ...segment,
    percent: positiveTotal > 0 ? Math.max(0, (segment.value / positiveTotal) * 100) : 100 / Math.max(segments.length, 1),
    isTotal: false,
  }));
  if (usedUnits.length <= 1 && segments.length <= 2) {
    summary.push({
      label: "合计",
      value: segments.reduce((sum, segment) => sum + segment.value, 0),
      unit: usedUnits[0] || "",
      percent: null,
      isTotal: true,
    });
  }
  return summary;
}

function renderResultPanel(key, title, rows, points) {
  const panel = document.getElementById(`${key}Result`);
  if (!panel) return;
  panel.innerHTML = `
    <div class="optimization-result-layout">
      <div class="optimization-result-chart" aria-label="${escapeHtml(title)}曲线">${renderMiniBars(points)}</div>
      <div class="data-table optimization-result-table">${renderResultTable(rows)}</div>
    </div>`;
}

function renderGreenResult(rows, dailyPoints, options = {}) {
  const panel = document.getElementById("greenResult");
  if (!panel) return;
  state.greenDailyPoints = Array.isArray(dailyPoints) ? dailyPoints : [];
  const safeRows = rows.length ? rows : options.allowEmpty ? [] : defaultGreenTable();
  const formattedRows = safeRows.map((row) => ({
    "指标": row["指标"],
    "数值": formatDisplayValue(row["数值"], row, "数值"),
    "单位": row["单位"] || "",
  }));
  panel.innerHTML = `
    <div class="green-result-layout">
      <div class="data-table green-result-table">${renderResultTable(formattedRows)}</div>
      <div class="result-column-resize-handle" data-result-column-resize="green" role="separator" tabindex="0" aria-label="调整经济性指标表格和曲线宽度" aria-orientation="vertical"></div>
      <section class="green-chart-card green-daily-chart" aria-label="${escapeHtml(resultTabLabels.green)}日曲线">
        <div class="green-chart-viewport" data-result-chart-viewport="green">${renderGreenDailyChart(state.greenDailyPoints)}</div>
      </section>
    </div>`;
}

function renderGreenDailyChart(points) {
  if (!points.length) return '<div class="empty-summary">暂无日曲线</div>';
  const { width, height } = resultChartSize("green", 1000, 330);
  const margin = resultChartMargins(width, height);
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const upSeries = greenDailySeries.filter((series) => series.direction === "up" && isSeriesVisible("green", series.key));
  const downSeries = greenDailySeries.filter((series) => series.direction === "down" && isSeriesVisible("green", series.key));
  if (!upSeries.length && !downSeries.length) return `${renderGreenChartLegend()}<div class="empty-summary">暂无可显示曲线</div>`;
  const autoUpMax = Math.max(
    ...points.map((point) => upSeries.reduce((total, series) => total + numericValue(point[series.key]), 0)),
    1,
  );
  const autoDownMax = Math.max(
    ...points.map((point) => downSeries.reduce((total, series) => total + numericValue(point[series.key]), 0)),
    1,
  );
  const axisRange = applyAxisRange(-autoDownMax, autoUpMax, state.axisRanges.green);
  const upMax = Math.max(axisRange.max, 0.001);
  const downMax = Math.max(-axisRange.min, 0.001);
  const zeroY = margin.top + plotHeight * (upMax / (upMax + downMax));
  const topSpan = Math.max(1, zeroY - margin.top);
  const bottomSpan = Math.max(1, margin.top + plotHeight - zeroY);
  const xAt = (index) => margin.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
  const yUp = (value) => zeroY - (value / upMax) * topSpan;
  const yDown = (value) => zeroY + (value / downMax) * bottomSpan;
  const tickRatios = height >= 200 ? [0.5, 1] : [1];
  const positiveTicks = tickRatios.map((ratio) => ({
    y: yUp(upMax * ratio),
    label: `+${formatAxisNumber(upMax * ratio)}`,
  }));
  const negativeTicks = tickRatios.map((ratio) => ({
    y: yDown(downMax * ratio),
    label: `-${formatAxisNumber(downMax * ratio)}`,
  }));
  return `
    ${renderGreenChartLegend()}
    ${renderResultAxisRangeControls("green")}
    <svg class="green-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="绿电日曲线" data-chart-kind="green" data-chart-width="${width}" data-chart-height="${height}" data-plot-left="${margin.left}" data-plot-right="${width - margin.right}" data-plot-top="${margin.top}" data-plot-bottom="${height - margin.bottom}">
      <line class="green-axis-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
      <line class="green-zero-line" x1="${margin.left}" y1="${zeroY.toFixed(2)}" x2="${width - margin.right}" y2="${zeroY.toFixed(2)}"></line>
      ${positiveTicks.concat(negativeTicks).map((tick) => renderGreenTick(tick, margin.left, width - margin.right)).join("")}
      <text class="green-tick-label green-zero-label" x="${margin.left - 8}" y="${zeroY.toFixed(2)}">0</text>
      ${renderGreenStackedAreas(points, upSeries, xAt, yUp)}
      ${renderGreenStackedAreas(points, downSeries, xAt, yDown)}
      ${renderGreenXAxis(points, xAt, zeroY, height - margin.bottom, width)}
      <line class="chart-hover-line" data-chart-hover-line="green" x1="${margin.left}" x2="${margin.left}" y1="${margin.top}" y2="${height - margin.bottom}" hidden></line>
      <rect class="chart-hover-capture" data-chart-hover="green" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"></rect>
    </svg>
    <div class="chart-hover-tooltip" data-chart-hover-tooltip="green" hidden></div>`;
}

function renderSafetyResult(rows, dailyPoints, options = {}) {
  const panel = document.getElementById("safetyResult");
  if (!panel) return;
  state.safetyDailyPoints = Array.isArray(dailyPoints) ? dailyPoints : [];
  const safeRows = rows.length ? rows : options.allowEmpty ? [] : defaultSafetyTable();
  const formattedRows = safeRows.map((row) => ({
    "指标": row["指标"],
    "数值": formatDisplayValue(row["数值"], row, "数值"),
    "单位": row["单位"] || "",
  }));
  panel.innerHTML = `
    <div class="safety-result-layout">
      <div class="data-table safety-result-table">${renderResultTable(formattedRows)}</div>
      <div class="result-column-resize-handle" data-result-column-resize="safety" role="separator" tabindex="0" aria-label="调整安全性指标表格和曲线宽度" aria-orientation="vertical"></div>
      <section class="safety-chart-card safety-frequency-chart" aria-label="${escapeHtml(resultTabLabels.safety)}日曲线">
        <div class="safety-chart-viewport" data-result-chart-viewport="safety">${renderSafetyDailyChart(state.safetyDailyPoints)}</div>
      </section>
    </div>`;
}

function renderSafetyDailyChart(points) {
  if (!points.length) return '<div class="empty-summary">暂无日曲线</div>';
  const { width, height } = resultChartSize("safety", 1000, 330);
  const margin = resultChartMargins(width, height);
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const visibleSeries = safetyDailySeries.filter((series) => isSeriesVisible("safety", series.key));
  if (!visibleSeries.length) return `${renderSafetyChartLegend()}<div class="empty-summary">暂无可显示曲线</div>`;
  const nominalFrequency = safetyNominalFrequency(points);
  const maxDeviation = Math.max(
    ...points.map((point) => Math.max(...visibleSeries.map((series) => Math.abs(numericFrequency(point[series.key]) - nominalFrequency)))),
    0.001,
  );
  const axisRange = applyAxisRange(nominalFrequency - maxDeviation, nominalFrequency + maxDeviation, state.axisRanges.safety);
  const yMin = axisRange.min;
  const yMax = axisRange.max;
  const centerY = margin.top + ((yMax - nominalFrequency) / Math.max(0.001, yMax - yMin)) * plotHeight;
  const xAt = (index) => margin.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
  const yAt = (value) => margin.top + ((yMax - numericFrequency(value)) / Math.max(0.001, yMax - yMin)) * plotHeight;
  const maxPath = linePath(points, (point) => point.frequency_max, xAt, yAt);
  const minPath = linePath(points, (point) => point.frequency_min, xAt, yAt);
  return `
    ${renderSafetyChartLegend()}
    ${renderResultAxisRangeControls("safety")}
    <svg class="safety-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="安全频率日曲线" data-chart-kind="safety" data-chart-width="${width}" data-chart-height="${height}" data-plot-left="${margin.left}" data-plot-right="${width - margin.right}" data-plot-top="${margin.top}" data-plot-bottom="${height - margin.bottom}">
      <line class="safety-axis-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
      <line class="safety-center-line" x1="${margin.left}" y1="${centerY.toFixed(2)}" x2="${width - margin.right}" y2="${centerY.toFixed(2)}"></line>
      <line class="safety-grid-line" x1="${margin.left}" y1="${margin.top}" x2="${width - margin.right}" y2="${margin.top}"></line>
      <line class="safety-grid-line" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
      <text class="safety-tick-label" x="${margin.left - 8}" y="${margin.top + 2}">${escapeHtml(formatAxisNumber(yMax))}</text>
      <text class="safety-tick-label safety-zero-label" x="${margin.left - 8}" y="${centerY.toFixed(2)}">${escapeHtml(formatAxisNumber(nominalFrequency))}</text>
      <text class="safety-tick-label" x="${margin.left - 8}" y="${height - margin.bottom - 2}">${escapeHtml(formatAxisNumber(yMin))}</text>
      ${isSeriesVisible("safety", "frequency_max") ? `<path class="safety-frequency-area up" d="${frequencyAreaPath(points, (point) => point.frequency_max, xAt, yAt, centerY)}"></path><path class="safety-frequency-line up" d="${maxPath}"></path>` : ""}
      ${isSeriesVisible("safety", "frequency_min") ? `<path class="safety-frequency-area down" d="${frequencyAreaPath(points, (point) => point.frequency_min, xAt, yAt, centerY)}"></path><path class="safety-frequency-line down" d="${minPath}"></path>` : ""}
      ${renderSafetyXAxis(points, xAt, centerY, height - margin.bottom, width)}
      <line class="chart-hover-line" data-chart-hover-line="safety" x1="${margin.left}" x2="${margin.left}" y1="${margin.top}" y2="${height - margin.bottom}" hidden></line>
      <rect class="chart-hover-capture" data-chart-hover="safety" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"></rect>
    </svg>
    <div class="chart-hover-tooltip" data-chart-hover-tooltip="safety" hidden></div>`;
}

function linePath(points, valueAccessor, xAt, yAt) {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index).toFixed(2)} ${yAt(valueAccessor(point)).toFixed(2)}`)
    .join(" ");
}

function frequencyAreaPath(points, valueAccessor, xAt, yAt, centerY) {
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index).toFixed(2)} ${yAt(valueAccessor(point)).toFixed(2)}`).join(" ");
  const lastX = xAt(points.length - 1).toFixed(2);
  const firstX = xAt(0).toFixed(2);
  return `${line} L ${lastX} ${centerY.toFixed(2)} L ${firstX} ${centerY.toFixed(2)} Z`;
}

function renderSafetyXAxis(points, xAt, centerY, bottomY, width) {
  const tickIndexes = chartTickIndexes(points, width);
  return tickIndexes
    .map((index) => {
      const x = xAt(index);
      const day = points[index]?.day ?? index + 1;
      return `
        <line class="safety-x-tick" x1="${x.toFixed(2)}" y1="${centerY.toFixed(2)}" x2="${x.toFixed(2)}" y2="${bottomY}"></line>
        <text class="safety-x-label" x="${x.toFixed(2)}" y="${bottomY + 14}">${escapeHtml(day)}</text>`;
    })
    .join("");
}

function renderGreenStackedAreas(points, seriesList, xAt, yAt) {
  const base = points.map(() => 0);
  return seriesList
    .map((series) => {
      const top = points.map((point, index) => base[index] + numericValue(point[series.key]));
      const upperLine = top.map((value, index) => `${xAt(index).toFixed(2)},${yAt(value).toFixed(2)}`).join(" ");
      const lowerLine = base
        .map((value, index) => `${xAt(index).toFixed(2)},${yAt(value).toFixed(2)}`)
        .reverse()
        .join(" ");
      top.forEach((value, index) => {
        base[index] = value;
      });
      return `<polygon class="green-stack-area" points="${upperLine} ${lowerLine}" fill="${series.color}"><title>${escapeHtml(series.label)}</title></polygon>`;
    })
    .join("");
}

function renderGreenChartLegend() {
  return `<div class="green-chart-legend">${renderSeriesLegendButtons("green", greenDailySeries)}</div>`;
}

function renderSafetyChartLegend() {
  return `<div class="safety-chart-legend">${renderSeriesLegendButtons("safety", safetyDailySeries)}</div>`;
}

function renderGreenTick(tick, left, right) {
  return `
    <line class="green-grid-line" x1="${left}" y1="${tick.y.toFixed(2)}" x2="${right}" y2="${tick.y.toFixed(2)}"></line>
    <text class="green-tick-label" x="${left - 8}" y="${tick.y.toFixed(2)}">${escapeHtml(tick.label)}</text>`;
}

function renderGreenXAxis(points, xAt, zeroY, bottomY, width) {
  const tickIndexes = chartTickIndexes(points, width);
  return tickIndexes
    .map((index) => {
      const x = xAt(index);
      const day = points[index]?.day ?? index + 1;
      return `
        <line class="green-x-tick" x1="${x.toFixed(2)}" y1="${zeroY.toFixed(2)}" x2="${x.toFixed(2)}" y2="${bottomY}"></line>
        <text class="green-x-label" x="${x.toFixed(2)}" y="${bottomY + 14}">${escapeHtml(day)}</text>`;
    })
    .join("");
}

function renderResultTable(rows) {
  if (!rows.length) return '<div class="empty-summary">暂无结果</div>';
  const headers = Object.keys(rows[0]);
  return `<table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows
    .map((row) => `<tr>${headers.map((header) => `<td>${escapeHtml(formatDisplayValue(row[header], row, header))}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function numericValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
}

function numericFrequency(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 50;
}

function safetyNominalFrequency(points) {
  for (const point of points || []) {
    const number = Number(point?.nominal_frequency_hz);
    if (Number.isFinite(number) && number > 0) return number;
  }
  return 50;
}

function renderMiniBars(points) {
  if (!points.length) return '<div class="empty-summary">暂无曲线</div>';
  const maxValue = Math.max(...points.map((point) => Number(point.value) || 0), 1);
  return `<div class="mini-bar-chart">${points
    .map((point) => {
      const value = Number(point.value) || 0;
      const height = Math.max(6, (value / maxValue) * 100);
      return `<div class="mini-bar-item"><div class="mini-bar-value">${escapeHtml(formatDisplayValue(value))}</div><div class="mini-bar-track"><span style="height:${height}%"></span></div><div class="mini-bar-label">${escapeHtml(point.label)}</div></div>`;
    })
    .join("")}</div>`;
}

function formatMetricValue(item) {
  if (!item) return "-";
  if (["开始", "完成"].includes(item.label)) return formatMetricTime(item.value);
  if (item.label === "度电成本") return formatLevelizedCostValue(item.value);
  return formatDisplayValue(item.value);
}

function formatMetricTime(value) {
  const text = String(value ?? "").trim();
  if (!text || text === "-") return "-";
  const match = text.match(/(\d{2}:\d{2}:\d{2})$/);
  return match ? match[1] : text;
}

function formatDisplayValue(value) {
  const row = arguments[1] || null;
  const header = arguments[2] || "";
  if (row?.["指标"] === "度电成本" && header !== "指标") return formatLevelizedCostValue(value);
  if (typeof value !== "number" || !Number.isFinite(value)) return value ?? "";
  if (Number.isInteger(value)) return value.toLocaleString("zh-CN");
  return formatNumber(value);
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatLevelizedCostValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "";
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function formatAxisNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return formatNumber(number);
}

function formatFrequency(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (Math.abs(number - Number(number.toFixed(2))) >= 0.0005) return `${number.toFixed(4)} Hz`;
  return `${number.toFixed(2)} Hz`;
}

function formatFrequencyDeviation(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (Math.abs(number) < 0.01) return number.toFixed(4);
  if (Math.abs(number) < 0.1) return number.toFixed(3);
  return number.toFixed(2);
}

function formatSignedDeviation(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  const sign = number >= 0 ? "+" : "";
  return `${sign}${formatFrequencyDeviation(number)}`;
}

function renderOptimizationLogs(logs) {
  const box = document.getElementById("evaluationLogs");
  if (!box) return;
  const shouldStickToBottom = isLogScrolledNearBottom(box);
  const previousScrollTop = box.scrollTop;
  if (!logs.length) {
    box.innerHTML = '<div class="log-line">暂无评估日志</div>';
    return;
  }
  box.innerHTML = logs
    .map((item) => `<div class="log-line ${escapeHtml(item.level || "")}"><span>${escapeHtml(item.time || "")}</span><strong>${escapeHtml(item.message || "")}</strong></div>`)
    .join("");
  box.scrollTop = shouldStickToBottom ? box.scrollHeight : previousScrollTop;
}

function isLogScrolledNearBottom(box) {
  const distance = box.scrollHeight - box.scrollTop - box.clientHeight;
  return distance <= 12;
}

function bindLogContextMenu({ boxId, emptyText, clearLogs, saveLogs }) {
  const box = document.getElementById(boxId);
  if (!box) return;
  const menu = createLogContextMenu();
  box.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    showLogContextMenu(menu, event.clientX, event.clientY);
  });
  menu.addEventListener("click", async (event) => {
    const action = event.target?.dataset?.logMenuAction;
    if (!action) return;
    hideLogContextMenu(menu);
    try {
      if (action === "clear") {
        await clearLogs();
      } else if (action === "save") {
        saveLogs();
      }
    } catch (error) {
      showError(error);
    }
  });
  window.addEventListener("click", () => hideLogContextMenu(menu));
  window.addEventListener("resize", () => hideLogContextMenu(menu));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideLogContextMenu(menu);
  });
  if (!box.textContent.trim()) box.innerHTML = `<div class="log-line">${escapeHtml(emptyText)}</div>`;
}

function createLogContextMenu() {
  const menu = document.createElement("div");
  menu.className = "log-context-menu";
  menu.setAttribute("role", "menu");
  menu.hidden = true;
  menu.innerHTML = `
    <button type="button" role="menuitem" data-log-menu-action="clear">清空日志</button>
    <button type="button" role="menuitem" data-log-menu-action="save">保存日志到文件</button>`;
  document.body.appendChild(menu);
  return menu;
}

function showLogContextMenu(menu, x, y) {
  menu.hidden = false;
  const width = menu.offsetWidth || 180;
  const height = menu.offsetHeight || 88;
  const left = Math.min(x, window.innerWidth - width - 8);
  const top = Math.min(y, window.innerHeight - height - 8);
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
}

function hideLogContextMenu(menu) {
  menu.hidden = true;
}

function saveLogsToFile(logs, baseName) {
  const content = formatLogsForFile(logs);
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${safeFileName(baseName)}_${timestampForFile()}.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatLogsForFile(logs) {
  if (!logs.length) return "暂无评估日志\n";
  return `${logs.map((item) => `[${item.time || ""}] [${item.level || "info"}] ${item.message || ""}`).join("\n")}\n`;
}

function timestampForFile() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function safeFileName(value) {
  return String(value || "运行日志").replace(/[\\/:*?"<>|]/g, "_").replace(/\s+/g, "_").slice(0, 80) || "运行日志";
}

function bindAdaptiveResultCharts() {
  if (!("ResizeObserver" in window)) {
    window.requestAnimationFrame(refreshAdaptiveResultCharts);
    return;
  }
  if (!state.resultChartResizeObserver) {
    state.resultChartResizeObserver = new ResizeObserver((entries) => {
      entries.forEach((entry) => updateResultChartSize(entry.target, entry.contentRect));
    });
  }
  state.resultChartResizeObserver.disconnect();
  document.querySelectorAll("[data-result-chart-viewport]").forEach((viewport) => {
    state.resultChartResizeObserver.observe(viewport);
  });
  window.requestAnimationFrame(refreshAdaptiveResultCharts);
}

function refreshAdaptiveResultCharts() {
  document.querySelectorAll("[data-result-chart-viewport]").forEach((viewport) => updateResultChartSize(viewport));
}

function updateResultChartSize(viewport, rect = viewport.getBoundingClientRect()) {
  const kind = viewport.dataset.resultChartViewport;
  if (kind !== "green" && kind !== "safety") return;
  const width = Math.round(rect.width || 0);
  const height = Math.round(rect.height || 0);
  if (width < 80 || height < 80) return;

  const sizeKey = `${kind}ChartSize`;
  const previous = state[sizeKey] || {};
  if (Math.abs((previous.width || 0) - width) <= 2 && Math.abs((previous.height || 0) - height) <= 2) return;

  state[sizeKey] = { width, height };
  renderAdaptiveResultChart(kind, viewport);
}

function renderAdaptiveResultChart(kind, viewport = document.querySelector(`[data-result-chart-viewport="${kind}"]`)) {
  if (!viewport) return;
  if (kind === "green") {
    viewport.innerHTML = renderGreenDailyChart(state.greenDailyPoints || []);
  } else if (kind === "safety") {
    viewport.innerHTML = renderSafetyDailyChart(state.safetyDailyPoints || []);
  }
  bindChartHoverCursors();
}

function bindChartHoverCursors() {
  document.querySelectorAll("[data-chart-hover]").forEach((capture) => {
    if (capture.dataset.hoverBound === "true") return;
    capture.dataset.hoverBound = "true";
    capture.addEventListener("pointerenter", (event) => updateChartHoverCursor(event, capture));
    capture.addEventListener("pointermove", (event) => updateChartHoverCursor(event, capture));
    capture.addEventListener("pointerleave", () => hideChartHoverCursor(capture));
    capture.addEventListener("pointercancel", () => hideChartHoverCursor(capture));
  });
}

function updateChartHoverCursor(event, capture = event.currentTarget) {
  const kind = capture?.dataset?.chartHover;
  const points = kind === "green" ? state.greenDailyPoints : kind === "safety" ? state.safetyDailyPoints : [];
  if (!kind || !points.length) return;

  const svg = capture.ownerSVGElement;
  const viewport = capture.closest("[data-result-chart-viewport]");
  const line = svg?.querySelector(`[data-chart-hover-line="${kind}"]`);
  const tooltip = viewport?.querySelector(`[data-chart-hover-tooltip="${kind}"]`);
  if (!svg || !viewport || !line || !tooltip) return;

  const chartWidth = numericSvgAttribute(svg, "chartWidth", "width");
  const plotLeft = numericSvgAttribute(svg, "plotLeft", "left");
  const plotRight = numericSvgAttribute(svg, "plotRight", "right");
  const svgRect = svg.getBoundingClientRect();
  if (!chartWidth || !svgRect.width || plotRight <= plotLeft) return;

  const pointerX = ((event.clientX - svgRect.left) / svgRect.width) * chartWidth;
  const clampedX = Math.min(Math.max(pointerX, plotLeft), plotRight);
  const ratio = (clampedX - plotLeft) / (plotRight - plotLeft);
  const index = Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))));
  const snappedX = plotLeft + (points.length === 1 ? (plotRight - plotLeft) / 2 : (index / (points.length - 1)) * (plotRight - plotLeft));

  line.setAttribute("x1", snappedX.toFixed(2));
  line.setAttribute("x2", snappedX.toFixed(2));
  line.removeAttribute("hidden");

  tooltip.innerHTML = kind === "green" ? renderGreenHoverTooltip(points[index], index) : renderSafetyHoverTooltip(points[index], index);
  tooltip.removeAttribute("hidden");
  positionChartHoverTooltip(tooltip, viewport, event);
}

function hideChartHoverCursor(capture) {
  const kind = capture?.dataset?.chartHover;
  const svg = capture?.ownerSVGElement;
  const viewport = capture?.closest("[data-result-chart-viewport]");
  svg?.querySelector(`[data-chart-hover-line="${kind}"]`)?.setAttribute("hidden", "");
  viewport?.querySelector(`[data-chart-hover-tooltip="${kind}"]`)?.setAttribute("hidden", "");
}

function positionChartHoverTooltip(tooltip, viewport, event) {
  const viewportRect = viewport.getBoundingClientRect();
  const offset = 14;
  const padding = 8;
  const localX = event.clientX - viewportRect.left;
  const localY = event.clientY - viewportRect.top;
  const width = tooltip.offsetWidth || 180;
  const height = tooltip.offsetHeight || 120;
  let left = localX + offset;
  let top = localY + offset;

  if (left + width + padding > viewport.clientWidth) left = localX - width - offset;
  if (top + height + padding > viewport.clientHeight) top = localY - height - offset;

  tooltip.style.left = `${Math.max(padding, Math.min(left, viewport.clientWidth - width - padding))}px`;
  tooltip.style.top = `${Math.max(padding, Math.min(top, viewport.clientHeight - height - padding))}px`;
}

function renderGreenHoverTooltip(point, index) {
  const day = point?.day ?? index + 1;
  const rows = greenDailySeries
    .filter((series) => isSeriesVisible("green", series.key))
    .map((series) => {
      const value = formatNumber(numericValue(point?.[series.key]));
      return `<div><span>${escapeHtml(series.label)}</span><strong>${escapeHtml(value)} kWh</strong></div>`;
    })
    .join("");
  return `<h3>第 ${escapeHtml(day)} 天</h3>${rows}`;
}

function renderSafetyHoverTooltip(point, index) {
  const day = point?.day ?? index + 1;
  const nominalFrequency = safetyNominalFrequency([point]);
  const rows = [];
  if (isSeriesVisible("safety", "frequency_max")) {
    const maxFrequency = numericFrequency(point?.frequency_max);
    rows.push(`<div><span>向上频率最大值</span><strong>${escapeHtml(formatFrequency(maxFrequency))} (${escapeHtml(formatSignedDeviation(maxFrequency - nominalFrequency))})</strong></div>`);
  }
  if (isSeriesVisible("safety", "frequency_min")) {
    const minFrequency = numericFrequency(point?.frequency_min);
    rows.push(`<div><span>向下频率最小值</span><strong>${escapeHtml(formatFrequency(minFrequency))} (${escapeHtml(formatSignedDeviation(minFrequency - nominalFrequency))})</strong></div>`);
  }
  return `<h3>第 ${escapeHtml(day)} 天</h3>${rows.join("")}`;
}

function numericSvgAttribute(svg, dataKey, fallbackName) {
  const dataValue = Number(svg.dataset[dataKey]);
  if (Number.isFinite(dataValue)) return dataValue;
  const attrValue = Number(svg.getAttribute(fallbackName));
  return Number.isFinite(attrValue) ? attrValue : 0;
}

function resultChartSize(kind, fallbackWidth, fallbackHeight) {
  const size = state[`${kind}ChartSize`] || {};
  return {
    width: Math.max(260, Math.round(size.width || fallbackWidth)),
    height: Math.max(160, Math.round(size.height || fallbackHeight)),
  };
}

function resultChartMargins(width, height) {
  const compactWidth = width < 620;
  return {
    top: 18,
    right: compactWidth ? 36 : 48,
    bottom: height >= 200 ? 34 : 42,
    left: compactWidth ? 62 : 72,
  };
}

function chartTickIndexes(points, width) {
  const lastIndex = points.length - 1;
  const indexes = width < 620 ? [0, Math.round(lastIndex / 2), lastIndex] : [0, 90, 181, 272, lastIndex];
  return indexes.filter((index, position, values) => index >= 0 && index < points.length && values.indexOf(index) === position);
}

function bindResultColumnResizeHandles() {
  document.querySelectorAll("[data-result-column-resize]").forEach((handle) => {
    if (handle.dataset.resizeBound === "true") return;
    const kind = handle.dataset.resultColumnResize;
    const config = resultColumnResizeConfig[kind];
    if (!config) return;
    handle.dataset.resizeBound = "true";

    const applyWidth = (width) => setResultColumnTableWidth(kind, width, handle);
    const currentWidth = () => currentResultColumnTableWidth(kind, handle);

    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = currentWidth();
      handle.classList.add("dragging");
      handle.setPointerCapture?.(event.pointerId);

      const onMove = (moveEvent) => {
        applyWidth(startWidth + moveEvent.clientX - startX);
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
      const keySteps = {
        ArrowLeft: -24,
        ArrowRight: 24,
        PageDown: -96,
        PageUp: 96,
      };
      if (event.key in keySteps) {
        event.preventDefault();
        applyWidth(currentWidth() + keySteps[event.key]);
      } else if (event.key === "Home") {
        event.preventDefault();
        applyWidth(resultColumnWidthBounds(kind, handle).min);
      } else if (event.key === "End") {
        event.preventDefault();
        applyWidth(resultColumnWidthBounds(kind, handle).max);
      }
    });

    handle.setAttribute("aria-valuenow", String(Math.round(currentWidth())));
    const bounds = resultColumnWidthBounds(kind, handle);
    handle.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    handle.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
  });
}

function bindEvaluationMainResizeHandle() {
  const handle = document.getElementById("evaluationMainResizeHandle");
  if (!handle) return;

  const applyWidth = (width) => setEvaluationResultRailWidth(width, handle);
  const currentWidth = () => currentEvaluationResultRailWidth();

  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = currentWidth();
    handle.classList.add("dragging");
    handle.setPointerCapture?.(event.pointerId);

    const onMove = (moveEvent) => {
      applyWidth(startWidth + moveEvent.clientX - startX);
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
    const keySteps = {
      ArrowLeft: -24,
      ArrowRight: 24,
      PageDown: -96,
      PageUp: 96,
    };
    if (event.key in keySteps) {
      event.preventDefault();
      applyWidth(currentWidth() + keySteps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyWidth(evaluationMainWidthBounds().min);
    } else if (event.key === "End") {
      event.preventDefault();
      applyWidth(evaluationMainWidthBounds().max);
    }
  });

  applyWidth(currentWidth());
}

function bindEvaluationSchemeListResizeHandle() {
  const handle = document.getElementById("evaluationSchemeListResizeHandle");
  if (!handle) return;
  const applyHeight = (height) => setEvaluationSchemeRailHeight(height, handle);
  const currentHeight = () => currentEvaluationSchemeRailHeight();

  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = currentHeight();
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
    const steps = {
      ArrowUp: -24,
      ArrowDown: 24,
      PageUp: -96,
      PageDown: 96,
    };
    if (event.key in steps) {
      event.preventDefault();
      applyHeight(currentHeight() + steps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyHeight(evaluationSchemeRailHeightBounds().min);
    } else if (event.key === "End") {
      event.preventDefault();
      applyHeight(evaluationSchemeRailHeightBounds().max);
    }
  });
  if (state.evaluationSchemeRailHeight) updateEvaluationSchemeListResizeHandle();
  else setEvaluationSchemeRailHeight(evaluationSchemeRailHeightBounds().max, handle);
}

function setEvaluationSchemeRailHeight(height, handle = document.getElementById("evaluationSchemeListResizeHandle")) {
  const bounds = evaluationSchemeRailHeightBounds();
  const numericHeight = Number(height);
  const safeHeight = Math.min(Math.max(Number.isFinite(numericHeight) ? numericHeight : bounds.min, bounds.min), bounds.max);
  const roundedHeight = Math.round(safeHeight);
  state.evaluationSchemeRailHeight = roundedHeight;
  document.documentElement.style.setProperty("--evaluation-scheme-rail-height", `${roundedHeight}px`);
  handle?.setAttribute("aria-valuenow", String(roundedHeight));
  handle?.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
  handle?.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
  rememberEvaluationPageState({ evaluationSchemeRailHeight: state.evaluationSchemeRailHeight });
}

function currentEvaluationSchemeRailHeight() {
  const rail = document.querySelector(".evaluation-workspace > .scheme-rail");
  return state.evaluationSchemeRailHeight || rail?.getBoundingClientRect().height || 240;
}

function evaluationSchemeRailHeightBounds() {
  const workspace = document.querySelector(".evaluation-workspace");
  const handle = document.getElementById("evaluationSchemeListResizeHandle");
  if (!workspace) return { min: 150, max: 600 };
  const style = getComputedStyle(workspace);
  const rowGap = Number.parseFloat(style.rowGap || style.gap) || 0;
  const handleHeight = handle?.getBoundingClientRect().height || 8;
  const contentHeight =
    (workspace.clientHeight || window.innerHeight - 120) -
    (Number.parseFloat(style.paddingTop) || 0) -
    (Number.parseFloat(style.paddingBottom) || 0);
  const bottomRailMinHeight = 260;
  return {
    min: 150,
    max: Math.max(180, Math.min(960, contentHeight - rowGap * 2 - handleHeight - bottomRailMinHeight)),
  };
}

function updateEvaluationSchemeListResizeHandle() {
  const handle = document.getElementById("evaluationSchemeListResizeHandle");
  if (!handle) return;
  const bounds = evaluationSchemeRailHeightBounds();
  handle.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
  handle.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
  handle.setAttribute("aria-valuenow", String(Math.round(currentEvaluationSchemeRailHeight())));
}

function setEvaluationResultRailWidth(width, handle = document.getElementById("evaluationMainResizeHandle")) {
  const bounds = evaluationMainWidthBounds();
  const numericWidth = Number(width);
  const safeWidth = Math.min(Math.max(Number.isFinite(numericWidth) ? numericWidth : bounds.min, bounds.min), bounds.max);
  const roundedWidth = Math.round(safeWidth);
  state.evaluationResultRailWidth = roundedWidth;
  document.documentElement.style.setProperty("--evaluation-result-rail-width", `${roundedWidth}px`);
  handle?.setAttribute("aria-valuenow", String(roundedWidth));
  handle?.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
  handle?.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
  rememberEvaluationPageState({ evaluationResultRailWidth: state.evaluationResultRailWidth });
}

function currentEvaluationResultRailWidth() {
  const rail = document.querySelector(".evaluation-result-rail");
  return state.evaluationResultRailWidth || rail?.getBoundingClientRect().width || 360;
}

function clampEvaluationMainWidth() {
  if (!state.evaluationResultRailWidth) return;
  setEvaluationResultRailWidth(state.evaluationResultRailWidth);
}

function evaluationMainWidthBounds() {
  const workspace = document.querySelector(".evaluation-workspace");
  if (!workspace) return { min: COLLAPSED_PANEL_SIZE, max: 620 };
  const handle = document.getElementById("evaluationMainResizeHandle");
  const style = window.getComputedStyle(workspace);
  const gap = cssNumber(style.columnGap || style.gap);
  const handleWidth = handle?.getBoundingClientRect().width || 10;
  const max = workspace.clientWidth - handleWidth - gap * 2;
  return {
    min: COLLAPSED_PANEL_SIZE,
    max: Math.max(COLLAPSED_PANEL_SIZE, Math.min(1200, max)),
  };
}

function setResultColumnTableWidth(kind, width, handle) {
  const config = resultColumnResizeConfig[kind];
  if (!config) return;
  const bounds = resultColumnWidthBounds(kind, handle);
  const numericWidth = Number(width);
  const safeWidth = Math.min(Math.max(Number.isFinite(numericWidth) ? numericWidth : bounds.min, bounds.min), bounds.max);
  const roundedWidth = Math.round(safeWidth);
  state[config.stateKey] = roundedWidth;
  document.documentElement.style.setProperty(config.cssVariable, `${roundedWidth}px`);
  handle?.setAttribute("aria-valuenow", String(roundedWidth));
  handle?.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
  handle?.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
  rememberEvaluationPageState({ [config.stateKey]: roundedWidth });
}

function currentResultColumnTableWidth(kind, handle) {
  const config = resultColumnResizeConfig[kind];
  if (!config) return 360;
  const layout = resultColumnLayout(kind, handle);
  const table = layout?.querySelector(config.tableSelector);
  return state[config.stateKey] || table?.getBoundingClientRect().width || 360;
}

function resultColumnWidthBounds(kind, handle) {
  const layout = resultColumnLayout(kind, handle);
  if (!layout) return { min: COLLAPSED_PANEL_SIZE, max: 620 };
  const style = window.getComputedStyle(layout);
  const gap = cssNumber(style.columnGap || style.gap);
  const handleWidth = handle?.getBoundingClientRect().width || 10;
  const maxTableWidth = layout.clientWidth - gap * 2 - handleWidth;
  return {
    min: COLLAPSED_PANEL_SIZE,
    max: Math.max(COLLAPSED_PANEL_SIZE, maxTableWidth),
  };
}

function resultColumnLayout(kind, handle) {
  const config = resultColumnResizeConfig[kind];
  return config ? handle?.closest(config.layoutSelector) : null;
}

function bindOverviewColumnResizeHandles() {
  document.querySelectorAll("[data-overview-column-resize]").forEach((handle) => {
    if (handle.dataset.bound === "true") return;
    handle.dataset.bound = "true";
    const applyWidth = (width) => applyOverviewColumnWidth(handle.dataset.overviewColumnResize, width, handle);
    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const mode = handle.dataset.overviewColumnResize || "left-middle";
      const startX = event.clientX;
      const startWidth = currentOverviewColumnWidth(mode, handle);
      handle.classList.add("dragging");
      handle.setPointerCapture?.(event.pointerId);

      const onMove = (moveEvent) => {
        applyWidth(startWidth + moveEvent.clientX - startX);
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
    bindHorizontalResizeHandleKeys(handle, () => currentOverviewColumnWidth(handle.dataset.overviewColumnResize || "left-middle", handle), applyWidth, () => overviewColumnWidthBounds(handle));
  });
}

function applyOverviewColumnWidth(mode, width, handle) {
  const bounds = overviewColumnWidthBounds(handle);
  const safeWidth = Math.min(Math.max(Number(width) || bounds.min, bounds.min), bounds.max);
  state.overviewLeftColumnWidth = Math.round(safeWidth);
  document.documentElement.style.setProperty("--overview-left-column-width", `${Math.round(safeWidth)}px`);
  rememberEvaluationPageState({ overviewLeftColumnWidth: state.overviewLeftColumnWidth });
}

function currentOverviewColumnWidth(mode, handle) {
  const card = handle?.previousElementSibling;
  return state.overviewLeftColumnWidth || card?.getBoundingClientRect().width || 320;
}

function overviewColumnWidthBounds(handle) {
  const grid = handle?.closest(".optimization-overview-grid");
  if (!grid) return { min: COLLAPSED_PANEL_SIZE, max: 720 };
  const handleWidth = handle?.getBoundingClientRect().width || 10;
  const gap = cssNumber(window.getComputedStyle(grid).columnGap || window.getComputedStyle(grid).gap);
  const max = grid.clientWidth - handleWidth - gap * 2;
  return { min: COLLAPSED_PANEL_SIZE, max: Math.max(COLLAPSED_PANEL_SIZE, max) };
}

function bindHorizontalResizeHandleKeys(handle, currentWidth, applyWidth, boundsFactory) {
  handle.addEventListener("keydown", (event) => {
    const keySteps = {
      ArrowLeft: -16,
      ArrowRight: 16,
      PageUp: 64,
      PageDown: -64,
    };
    if (event.key in keySteps) {
      event.preventDefault();
      applyWidth(currentWidth() + keySteps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyWidth(boundsFactory().min);
    } else if (event.key === "End") {
      event.preventDefault();
      applyWidth(boundsFactory().max);
    }
  });
}

function cssNumber(value) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : 0;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
}

function showError(error) {
  alert(error.message || String(error));
}
