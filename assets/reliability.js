(() => {
  "use strict";

  const PAGE_STATE_KEY = "reliability";
  const DEMO_SOURCE = "demo_scenario_assumption";
  const RESULT_REFRESH_DELAY_MS = 1200;

  const DEVICE_LABELS = {
    wind: "风机",
    pv: "光伏",
    solar: "光伏",
    storage: "储能 PCS",
    battery: "储能 PCS",
    diesel: "柴油发电机",
    generator: "柴油发电机",
  };

  const DEMO_PARAMETERS = Object.freeze({
    mode: "both",
    simulation_years: 1000,
    random_seed: 20260712,
    critical_load_ratio: 0.6,
    reserve_duration_hours: 24,
    dispatch_policy: "reliability_first",
    assumption_source: DEMO_SOURCE,
    devices: [
      {
        device_type: "wind",
        label: "风机",
        unit_count: 2,
        unit_capacity_kw: 100,
        forced_outage_rate: 0.08,
        mttr_hours: 72,
        extreme_cold_capacity_factor: 0.85,
        capex_wan_per_unit: 120,
        fixed_om_rate: 0.025,
        design_life_years: 20,
      },
      {
        device_type: "pv",
        label: "光伏",
        unit_count: 4,
        unit_capacity_kw: 50,
        forced_outage_rate: 0.02,
        mttr_hours: 24,
        extreme_cold_capacity_factor: 0.8,
        capex_wan_per_unit: 22.5,
        fixed_om_rate: 0.015,
        design_life_years: 25,
      },
      {
        device_type: "storage",
        label: "储能 PCS",
        unit_count: 3,
        unit_capacity_kw: 100,
        forced_outage_rate: 0.03,
        mttr_hours: 48,
        battery_forced_outage_rate: 0.02,
        battery_mttr_hours: 96,
        extreme_cold_capacity_factor: 0.75,
        capex_wan_per_unit: 220,
        fixed_om_rate: 0.015,
        design_life_years: 10,
      },
      {
        device_type: "diesel",
        label: "柴油发电机",
        unit_count: 2,
        unit_capacity_kw: 100,
        forced_outage_rate: 0.05,
        mttr_hours: 36,
        extreme_cold_capacity_factor: 0.9,
        capex_wan_per_unit: 30,
        fixed_om_rate: 0.04,
        design_life_years: 15,
        startup_failure_rate: 0.03,
        variable_om_yuan_per_kwh: 0.15,
      },
    ],
  });

  const state = {
    schemes: [],
    currentScheme: "",
    selectedResult: "",
    resultFiles: [],
    parameters: clone(DEMO_PARAMETERS),
    parameterWarnings: [],
    result: null,
    status: null,
    activeTab: "overview",
    pollTimer: null,
    contextToken: 0,
    lastCompletedKey: "",
  };

  document.addEventListener("DOMContentLoaded", () => {
    restorePageState();
    bindSelections();
    bindParameterActions();
    bindControlActions();
    bindTabs();
    renderDeviceRows(state.parameters.devices);
    renderAssumptionWarning();
    renderStatus(null);
    renderResult(null);
    loadSchemes().catch((error) => showMessage(error.message, "error"));
  });

  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        credentials: "same-origin",
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      });
    } catch (error) {
      throw new Error("请求后台失败，请检查 WEB 服务或 SSH 隧道是否正常运行。");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.message || data.error || `请求失败（HTTP ${response.status}）`);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }

  function restorePageState() {
    const saved = window.PowerPlanPageState?.read(PAGE_STATE_KEY, {}) || {};
    state.currentScheme = typeof saved.currentScheme === "string" ? saved.currentScheme : "";
    state.selectedResult = typeof saved.selectedResult === "string" ? saved.selectedResult : "";
    state.activeTab = ["overview", "scenarios", "distribution", "worst", "contribution", "logs"].includes(saved.activeTab)
      ? saved.activeTab
      : "overview";
  }

  function rememberPageState(partial = {}) {
    window.PowerPlanPageState?.patch(PAGE_STATE_KEY, {
      currentScheme: state.currentScheme,
      selectedResult: state.selectedResult,
      activeTab: state.activeTab,
      ...partial,
    });
  }

  function bindSelections() {
    document.getElementById("reliabilitySchemeSelect")?.addEventListener("change", async (event) => {
      state.currentScheme = event.target.value || "";
      state.selectedResult = "";
      rememberPageState();
      await switchContext().catch((error) => showMessage(error.message, "error"));
    });

    document.getElementById("reliabilityResultSelect")?.addEventListener("change", async (event) => {
      state.selectedResult = event.target.value || "";
      rememberPageState();
      await loadCurrentContext().catch((error) => showMessage(error.message, "error"));
    });

    document.getElementById("reliabilityMode")?.addEventListener("change", updateModeDependentControls);
  }

  function bindParameterActions() {
    document.getElementById("saveReliabilityParameters")?.addEventListener("click", () => {
      saveParameters().catch((error) => showMessage(error.message, "error"));
    });
    document.getElementById("resetReliabilityParameters")?.addEventListener("click", () => {
      state.parameters = clone(DEMO_PARAMETERS);
      state.parameterWarnings = [];
      applyParametersToForm(state.parameters);
      renderAssumptionWarning();
      showMessage("已恢复演示场景假设；点击“保存参数”后才会写入当前方案。", "ok");
    });
  }

  function bindControlActions() {
    document.getElementById("startReliability")?.addEventListener("click", () => {
      controlReliability("start").catch((error) => showMessage(error.message, "error"));
    });
    document.getElementById("queueReliability")?.addEventListener("click", () => {
      controlReliability("queue").catch((error) => showMessage(error.message, "error"));
    });
    document.getElementById("stopReliability")?.addEventListener("click", () => {
      controlReliability("stop").catch((error) => showMessage(error.message, "error"));
    });
  }

  function bindTabs() {
    document.querySelectorAll("[data-reliability-tab]").forEach((button) => {
      button.addEventListener("click", () => activateTab(button.dataset.reliabilityTab || "overview"));
    });
    activateTab(state.activeTab, false);
  }

  function activateTab(tabName, remember = true) {
    const available = Array.from(document.querySelectorAll("[data-reliability-tab]")).map(
      (button) => button.dataset.reliabilityTab,
    );
    const target = available.includes(tabName) ? tabName : "overview";
    state.activeTab = target;
    document.querySelectorAll("[data-reliability-tab]").forEach((button) => {
      const active = button.dataset.reliabilityTab === target;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-reliability-panel]").forEach((panel) => {
      const active = panel.dataset.reliabilityPanel === target;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    if (remember) rememberPageState({ activeTab: target });
  }

  async function loadSchemes() {
    const data = await api("/api/planning/schemes");
    state.schemes = normalizeSchemes(data.schemes);
    if (!state.schemes.length) {
      state.currentScheme = "";
      renderSchemeOptions();
      renderCurrentSelection();
      showMessage("暂无规划方案，请先在“参数维护”中新建方案。", "error");
      return;
    }

    if (!state.schemes.some((scheme) => scheme.name === state.currentScheme)) {
      state.currentScheme = state.schemes[0].name;
      state.selectedResult = "";
    }
    renderSchemeOptions();
    rememberPageState();
    await switchContext();
  }

  function normalizeSchemes(value) {
    if (!Array.isArray(value)) return [];
    return value
      .map((item) => (typeof item === "string" ? { name: item } : item && typeof item === "object" ? item : null))
      .filter((item) => item?.name)
      .map((item) => ({ ...item, name: String(item.name) }));
  }

  function renderSchemeOptions() {
    const select = document.getElementById("reliabilitySchemeSelect");
    if (!select) return;
    if (!state.schemes.length) {
      select.innerHTML = '<option value="">暂无方案</option>';
      select.disabled = true;
      return;
    }
    select.disabled = false;
    select.innerHTML = state.schemes
      .map(
        (scheme) =>
          `<option value="${escapeHtml(scheme.name)}"${scheme.name === state.currentScheme ? " selected" : ""}>${escapeHtml(
            scheme.name,
          )}</option>`,
      )
      .join("");
  }

  async function switchContext() {
    const token = ++state.contextToken;
    clearPolling();
    state.result = null;
    state.status = null;
    state.resultFiles = [];
    state.parameters = clone(DEMO_PARAMETERS);
    state.parameterWarnings = [];
    applyParametersToForm(state.parameters);
    renderAssumptionWarning();
    renderCurrentSelection();
    renderResult(null);
    renderStatus(null);
    renderResultOptions();
    if (!state.currentScheme) return;

    await loadResultIndex(token);
    if (token !== state.contextToken) return;
    await loadCurrentContext(token);
  }

  async function loadResultIndex(token = state.contextToken) {
    try {
      const data = await api(`/api/reliability/results?scheme=${encodeURIComponent(state.currentScheme)}`);
      if (token !== state.contextToken) return;
      state.resultFiles = normalizeResultFiles(
        data.results || data.result_files || data.files || data.planning_results || data.source_results,
      );
      const availableNames = state.resultFiles.map((item) => item.name);
      const apiSelected = String(data.selected || data.filename || "");
      if (apiSelected && availableNames.includes(apiSelected) && !state.selectedResult) state.selectedResult = apiSelected;
      if (state.selectedResult && !availableNames.includes(state.selectedResult)) state.selectedResult = "";
      if (extractResultPayload(data)) state.result = extractResultPayload(data);
    } catch (error) {
      if (token !== state.contextToken) return;
      state.resultFiles = [];
      if (error.status !== 404) showMessage(`结果列表读取失败：${error.message}`, "error");
    }
    renderResultOptions();
    rememberPageState();
  }

  function normalizeResultFiles(value) {
    if (!Array.isArray(value)) return [];
    const seen = new Set();
    return value
      .map((item) => {
        if (typeof item === "string") return { name: item, label: resultDisplayName(item), readable: true };
        if (!item || typeof item !== "object") return null;
        const name = String(item.name || item.filename || item.file || item.id || "");
        if (!name) return null;
        return {
          ...item,
          name,
          label: String(item.label || item.display_name || resultDisplayName(name)),
          readable: item.readable !== false,
        };
      })
      .filter((item) => {
        if (!item || seen.has(item.name)) return false;
        seen.add(item.name);
        return true;
      });
  }

  function renderResultOptions() {
    const select = document.getElementById("reliabilityResultSelect");
    if (!select) return;
    const defaultSelected = !state.selectedResult;
    const options = [
      `<option value=""${defaultSelected ? " selected" : ""}>默认/当前配置</option>`,
      ...state.resultFiles.map(
        (item) =>
          `<option value="${escapeHtml(item.name)}"${item.name === state.selectedResult ? " selected" : ""}${
            item.readable === false ? " disabled" : ""
          }>${escapeHtml(item.label)}${item.readable === false ? "（无法读取）" : ""}</option>`,
      ),
    ];
    select.innerHTML = options.join("");
    select.disabled = !state.currentScheme;
  }

  async function loadCurrentContext(token = state.contextToken) {
    if (!state.currentScheme) return;
    const requestToken = token || state.contextToken;
    state.result = null;
    state.status = null;
    renderCurrentSelection();
    renderResult(null);
    renderStatus(null);

    const settled = await Promise.allSettled([
      loadParameters(requestToken),
      loadSelectedResult(requestToken),
      refreshStatus(requestToken, false),
    ]);
    if (requestToken !== state.contextToken) return;
    const rejected = settled.filter((item) => item.status === "rejected");
    if (rejected.length === settled.length) {
      showMessage(rejected[0].reason?.message || "可靠性数据读取失败。", "error");
    }
    schedulePolling();
    rememberPageState();
  }

  async function loadParameters(token = state.contextToken) {
    const data = await api(reliabilityPath("/api/reliability/parameters"));
    if (token !== state.contextToken) return;
    const raw = data.parameters || data.data?.parameters || data.data || data;
    state.parameters = normalizeParameters(raw);
    state.parameterWarnings = normalizeWarnings(data.assumption_warnings || data.warnings || raw.assumption_warnings);
    applyParametersToForm(state.parameters);
    renderAssumptionWarning();
  }

  function normalizeParameters(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const defaults = clone(DEMO_PARAMETERS);
    const mode = normalizeMode(firstDefined(source.mode, source.assessment_mode, source.simulation_mode));
    const criticalRatio = normalizeRatio(
      firstDefined(source.critical_load_ratio, source.critical_ratio, source.critical_load_share),
      defaults.critical_load_ratio,
    );
    const devices = normalizeDevices(
      firstDefined(source.devices, source.device_reliability, source.reliability_devices, source.equipment),
      defaults.devices,
    );
    return {
      mode,
      simulation_years: clampInteger(
        firstDefined(source.simulation_years, source.monte_carlo_years, source.years),
        1,
        10000,
        defaults.simulation_years,
      ),
      random_seed: clampInteger(firstDefined(source.random_seed, source.seed), 0, 2147483647, defaults.random_seed),
      critical_load_ratio: criticalRatio,
      reserve_duration_hours: clampNumber(
        firstDefined(source.reserve_duration_hours, source.reserve_hours, source.backup_duration_hours),
        0,
        720,
        defaults.reserve_duration_hours,
      ),
      dispatch_policy: normalizeDispatchPolicy(
        firstDefined(source.dispatch_policy, source.failure_dispatch_policy, source.strategy),
      ),
      assumption_source: String(firstDefined(source.assumption_source, source.source, defaults.assumption_source)),
      devices,
    };
  }

  function normalizeMode(value) {
    const text = String(value || "").toLowerCase();
    if (["deterministic", "n-1", "n1", "stress_test"].includes(text)) return "deterministic";
    if (["monte_carlo", "monte-carlo", "mc", "probabilistic"].includes(text)) return "monte_carlo";
    return "both";
  }

  function normalizeDispatchPolicy(value) {
    const text = String(value || "").toLowerCase();
    if (["renewable_first", "economic", "proportional", "reliability_first"].includes(text)) return text;
    return "reliability_first";
  }

  function normalizeDevices(value, fallback) {
    const sourceRows = Array.isArray(value)
      ? value
      : value && typeof value === "object"
        ? Object.entries(value).map(([device_type, fields]) => ({ device_type, ...(fields || {}) }))
        : [];
    const aliases = {
      wind_turbine: "wind",
      wind_power: "wind",
      photovoltaic: "pv",
      solar: "pv",
      battery: "storage",
      ess: "storage",
      diesel_generator: "diesel",
      generator: "diesel",
    };
    const fallbackByType = new Map(fallback.map((row) => [row.device_type, row]));
    const normalizedByType = new Map();
    sourceRows.forEach((row) => {
      if (!row || typeof row !== "object") return;
      const rawType = String(firstDefined(row.device_type, row.type, row.device, row.name, "")).toLowerCase();
      const type = aliases[rawType] || rawType;
      if (!type) return;
      const base = fallbackByType.get(type) || {};
      normalizedByType.set(type, {
        device_type: type,
        label: String(firstDefined(row.label, row.display_name, DEVICE_LABELS[type], type)),
        unit_count: clampInteger(firstDefined(row.unit_count, row.count, row.units), 0, 100000, base.unit_count ?? 1),
        unit_capacity_kw: clampNumber(
          firstDefined(row.unit_capacity_kw, row.capacity_kw, row.rated_power_kw, row.power_kw),
          0,
          100000000,
          base.unit_capacity_kw ?? 0,
        ),
        forced_outage_rate: normalizeRatio(
          firstDefined(row.forced_outage_rate, row.for_rate, row.for, row.outage_rate),
          base.forced_outage_rate ?? 0,
        ),
        mttr_hours: clampNumber(
          firstDefined(row.mttr_hours, row.mttr, row.repair_hours),
          0,
          8760,
          base.mttr_hours ?? 0,
        ),
        ...(type === "storage"
          ? {
              battery_forced_outage_rate: normalizeRatio(
                firstDefined(row.battery_forced_outage_rate, row.battery_for_rate, row.battery_for),
                base.battery_forced_outage_rate ?? base.forced_outage_rate ?? 0,
              ),
              battery_mttr_hours: clampNumber(
                firstDefined(row.battery_mttr_hours, row.battery_repair_hours),
                0,
                8760,
                base.battery_mttr_hours ?? base.mttr_hours ?? 0,
              ),
            }
          : {}),
        extreme_cold_capacity_factor: normalizeRatio(
          firstDefined(
            row.extreme_cold_capacity_factor,
            row.cold_capacity_factor,
            row.polar_capacity_factor,
            row.cold_derating_factor,
          ),
          base.extreme_cold_capacity_factor ?? 1,
        ),
        capex_wan_per_unit: clampNumber(
          firstDefined(row.capex_wan_per_unit, row.capex_wan, row.cost_wan_per_unit, row.cost),
          0,
          100000000,
          base.capex_wan_per_unit ?? 0,
        ),
        fixed_om_rate: normalizeRatio(
          firstDefined(row.fixed_om_rate, row.fixed_om_ratio, row.fixed_om_rate_percent),
          base.fixed_om_rate ?? 0,
        ),
        design_life_years: clampNumber(
          firstDefined(row.design_life_years, row.design_life, row.lifetime_years),
          0,
          100,
          base.design_life_years ?? 0,
        ),
        ...(type === "diesel"
          ? {
              startup_failure_rate: normalizeRatio(
                firstDefined(row.startup_failure_rate, row.start_failure_rate, row.start_fail_rate),
                base.startup_failure_rate ?? 0,
              ),
              variable_om_yuan_per_kwh: clampNumber(
                firstDefined(row.variable_om_yuan_per_kwh, row.variable_om, row.variable_om_cost),
                0,
                1000000,
                base.variable_om_yuan_per_kwh ?? 0,
              ),
            }
          : {}),
      });
    });
    return fallback.map((row) => ({ ...row, ...(normalizedByType.get(row.device_type) || {}) }));
  }

  function applyParametersToForm(parameters) {
    setValue("reliabilityMode", parameters.mode);
    setValue("reliabilitySimulationYears", parameters.simulation_years);
    setValue("reliabilityRandomSeed", parameters.random_seed);
    setValue("reliabilityCriticalLoadRatio", round(parameters.critical_load_ratio * 100, 4));
    setValue("reliabilityReserveDuration", parameters.reserve_duration_hours);
    setValue("reliabilityDispatchPolicy", parameters.dispatch_policy);
    renderDeviceRows(parameters.devices);
    updateModeDependentControls();
  }

  function renderDeviceRows(devices) {
    const body = document.getElementById("reliabilityDeviceRows");
    if (!body) return;
    body.innerHTML = devices
      .map(
        (device) => `<tr data-device-type="${escapeHtml(device.device_type)}" data-device-label="${escapeHtml(
          device.label || DEVICE_LABELS[device.device_type] || device.device_type,
        )}">
          <td class="reliability-device-name">${escapeHtml(
            device.label || DEVICE_LABELS[device.device_type] || device.device_type,
          )}</td>
          <td><input data-device-field="unit_count" type="number" min="0" max="100000" step="1" value="${escapeHtml(
            numberInputValue(device.unit_count),
          )}" aria-label="${escapeHtml(device.label)}台数"></td>
          <td><input data-device-field="unit_capacity_kw" type="number" min="0" max="100000000" step="0.1" value="${escapeHtml(
            numberInputValue(device.unit_capacity_kw),
          )}" aria-label="${escapeHtml(device.label)}单机功率"></td>
          <td>${device.device_type === "storage" ? `<div class="reliability-dual-input">
            <label>PCS<input data-device-field="forced_outage_rate_percent" type="number" min="0" max="100" step="0.01" value="${escapeHtml(
              numberInputValue(round(device.forced_outage_rate * 100, 6)),
            )}" aria-label="储能PCS强迫停运率"></label>
            <label>电池<input data-device-field="battery_forced_outage_rate_percent" type="number" min="0" max="100" step="0.01" value="${escapeHtml(
              numberInputValue(round((device.battery_forced_outage_rate || 0) * 100, 6)),
            )}" aria-label="储能电池组强迫停运率"></label>
          </div>` : `<input data-device-field="forced_outage_rate_percent" type="number" min="0" max="100" step="0.01" value="${escapeHtml(
            numberInputValue(round(device.forced_outage_rate * 100, 6)),
          )}" aria-label="${escapeHtml(device.label)}强迫停运率">`}</td>
          <td>${device.device_type === "storage" ? `<div class="reliability-dual-input">
            <label>PCS<input data-device-field="mttr_hours" type="number" min="0" max="8760" step="0.1" value="${escapeHtml(
              numberInputValue(device.mttr_hours),
            )}" aria-label="储能PCS平均修复时间"></label>
            <label>电池<input data-device-field="battery_mttr_hours" type="number" min="0" max="8760" step="0.1" value="${escapeHtml(
              numberInputValue(device.battery_mttr_hours),
            )}" aria-label="储能电池组平均修复时间"></label>
          </div>` : `<input data-device-field="mttr_hours" type="number" min="0" max="8760" step="0.1" value="${escapeHtml(
            numberInputValue(device.mttr_hours),
          )}" aria-label="${escapeHtml(device.label)}平均修复时间">`}</td>
          <td><input data-device-field="extreme_cold_capacity_factor_percent" type="number" min="0" max="100" step="0.1" value="${escapeHtml(
            numberInputValue(round(device.extreme_cold_capacity_factor * 100, 6)),
          )}" aria-label="${escapeHtml(device.label)}极寒可用容量系数"></td>
          <td><input data-device-field="capex_wan_per_unit" type="number" min="0" max="100000000" step="0.01" value="${escapeHtml(
            numberInputValue(device.capex_wan_per_unit),
          )}" aria-label="${escapeHtml(device.label)}单位资本成本"></td>
          <td><input data-device-field="fixed_om_rate_percent" type="number" min="0" max="100" step="0.01" value="${escapeHtml(
            numberInputValue(round(device.fixed_om_rate * 100, 6)),
          )}" aria-label="${escapeHtml(device.label)}固定运维率"></td>
          <td><input data-device-field="design_life_years" type="number" min="0" max="100" step="0.1" value="${escapeHtml(
            numberInputValue(device.design_life_years),
          )}" aria-label="${escapeHtml(device.label)}设计寿命"></td>
          <td><input data-device-field="startup_failure_rate_percent" type="number" min="0" max="100" step="0.01" value="${escapeHtml(
            device.device_type === "diesel" ? numberInputValue(round((device.startup_failure_rate || 0) * 100, 6)) : "",
          )}" placeholder="仅柴发" aria-label="${escapeHtml(device.label)}启动失败率"${
            device.device_type === "diesel" ? "" : " disabled"
          }></td>
          <td><input data-device-field="variable_om_yuan_per_kwh" type="number" min="0" max="1000000" step="0.01" value="${escapeHtml(
            device.device_type === "diesel" ? numberInputValue(device.variable_om_yuan_per_kwh) : "",
          )}" placeholder="仅柴发" aria-label="${escapeHtml(device.label)}变动运维成本"${
            device.device_type === "diesel" ? "" : " disabled"
          }></td>
        </tr>`,
      )
      .join("");
  }

  function collectParameters() {
    const mode = document.getElementById("reliabilityMode")?.value || "both";
    const simulationYears = requiredInteger("reliabilitySimulationYears", "模拟年数", 1, 10000);
    const randomSeed = requiredInteger("reliabilityRandomSeed", "随机种子", 0, 2147483647);
    const criticalPercent = requiredNumber("reliabilityCriticalLoadRatio", "关键负荷比例", 0, 100);
    const reserveHours = requiredNumber("reliabilityReserveDuration", "备用持续时间", 0, 720);
    const dispatchPolicy = document.getElementById("reliabilityDispatchPolicy")?.value || "reliability_first";
    const devices = Array.from(document.querySelectorAll("#reliabilityDeviceRows tr[data-device-type]")).map((row) => {
      const value = (field) => row.querySelector(`[data-device-field="${field}"]`)?.value;
      const label = row.dataset.deviceLabel || DEVICE_LABELS[row.dataset.deviceType] || row.dataset.deviceType;
      const unitCount = validatedNumber(value("unit_count"), `${label}台数`, 0, 100000, true);
      const unitCapacity = validatedNumber(value("unit_capacity_kw"), `${label}单机功率`, 0, 100000000, false);
      const forPercent = validatedNumber(value("forced_outage_rate_percent"), `${label} FOR`, 0, 100, false);
      const mttr = validatedNumber(value("mttr_hours"), `${label} MTTR`, 0, 8760, false);
      const coldCapacityPercent = validatedNumber(
        value("extreme_cold_capacity_factor_percent"),
        `${label}极寒可用容量系数`,
        0,
        100,
        false,
      );
      const capex = validatedNumber(value("capex_wan_per_unit"), `${label} CAPEX`, 0, 100000000, false);
      const fixedOmPercent = validatedNumber(value("fixed_om_rate_percent"), `${label}固定运维率`, 0, 100, false);
      const designLife = validatedNumber(value("design_life_years"), `${label}设计寿命`, 0, 100, false);
      const device = {
        device_type: row.dataset.deviceType,
        label,
        unit_count: unitCount,
        unit_capacity_kw: unitCapacity,
        forced_outage_rate: forPercent / 100,
        mttr_hours: mttr,
        extreme_cold_capacity_factor: coldCapacityPercent / 100,
        capex_wan_per_unit: capex,
        fixed_om_rate: fixedOmPercent / 100,
        design_life_years: designLife,
      };
      if (row.dataset.deviceType === "diesel") {
        const startupFailurePercent = validatedNumber(
          value("startup_failure_rate_percent"),
          `${label}启动失败率`,
          0,
          100,
          false,
        );
        device.startup_failure_rate = startupFailurePercent / 100;
        device.variable_om_yuan_per_kwh = validatedNumber(
          value("variable_om_yuan_per_kwh"),
          `${label}变动运维`,
          0,
          1000000,
          false,
        );
      } else if (row.dataset.deviceType === "storage") {
        const batteryForPercent = validatedNumber(
          value("battery_forced_outage_rate_percent"),
          "储能电池组 FOR",
          0,
          100,
          false,
        );
        device.battery_forced_outage_rate = batteryForPercent / 100;
        device.battery_mttr_hours = validatedNumber(
          value("battery_mttr_hours"),
          "储能电池组 MTTR",
          0,
          8760,
          false,
        );
      }
      return device;
    });
    if (mode !== "deterministic" && simulationYears < 30) {
      throw new Error("蒙特卡洛模拟年数建议至少为 30 年；当前设置不足以形成稳定概率指标。");
    }
    return {
      mode,
      simulation_years: simulationYears,
      random_seed: randomSeed,
      critical_load_ratio: criticalPercent / 100,
      reserve_duration_hours: reserveHours,
      dispatch_policy: dispatchPolicy,
      assumption_source: state.parameters.assumption_source || DEMO_SOURCE,
      devices,
    };
  }

  function updateModeDependentControls() {
    const deterministicOnly = document.getElementById("reliabilityMode")?.value === "deterministic";
    const years = document.getElementById("reliabilitySimulationYears");
    const seed = document.getElementById("reliabilityRandomSeed");
    if (years) years.disabled = deterministicOnly;
    if (seed) seed.disabled = deterministicOnly;
  }

  async function saveParameters(options = {}) {
    if (!state.currentScheme) throw new Error("请先选择方案。");
    const parameters = collectParameters();
    const data = await api("/api/reliability/parameters", {
      method: "PUT",
      body: JSON.stringify({
        scheme: state.currentScheme,
        filename: state.selectedResult || "",
        parameters,
      }),
    });
    state.parameters = normalizeParameters(data.parameters || parameters);
    state.parameterWarnings = normalizeWarnings(data.assumption_warnings || data.warnings || state.parameterWarnings);
    applyParametersToForm(state.parameters);
    renderAssumptionWarning();
    if (!options.quiet) showMessage("可靠性参数已保存。", "ok");
    return state.parameters;
  }

  async function controlReliability(action) {
    if (!state.currentScheme) throw new Error("请先选择方案。");
    let parameters = state.parameters;
    if (action === "start" || action === "queue") parameters = await saveParameters({ quiet: true });

    const data = await api("/api/reliability/control", {
      method: "POST",
      body: JSON.stringify({
        action,
        scheme: state.currentScheme,
        filename: state.selectedResult || "",
        parameters,
      }),
    });
    const status = extractStatusPayload(data);
    if (status) {
      state.status = status;
      renderStatus(status);
    }
    const actionMessages = {
      start: "可靠性评估已启动。",
      queue: "可靠性评估已加入任务队列。",
      stop: "已发送停止请求。",
    };
    showMessage(data.message || actionMessages[action] || "操作已提交。", "ok");
    schedulePolling(250);
  }

  async function refreshStatus(token = state.contextToken, schedule = true) {
    if (!state.currentScheme) return;
    const requestContext = selectionKey();
    const data = await api(reliabilityPath("/api/reliability/status", { light: "1" }));
    if (token !== state.contextToken || requestContext !== selectionKey()) return;
    const status = extractStatusPayload(data) || data;
    state.status = status;
    renderStatus(status);

    const inlineResult = extractResultPayload(data);
    if (inlineResult) {
      state.result = inlineResult;
      renderResult(inlineResult);
    }

    const currentStatus = statusText(status);
    if (isCompletedStatus(currentStatus)) {
      const completeKey = `${selectionKey()}|${firstDefined(status.end_time, status.completed_at, status.updated_at, "complete")}`;
      if (completeKey !== state.lastCompletedKey) {
        state.lastCompletedKey = completeKey;
        window.setTimeout(() => {
          if (requestContext === selectionKey()) loadSelectedResult(state.contextToken).catch(() => null);
        }, RESULT_REFRESH_DELAY_MS);
      }
    }
    if (schedule) schedulePolling();
  }

  function schedulePolling(delay) {
    clearPolling();
    if (!state.currentScheme) return;
    const status = statusText(state.status);
    const active = isActiveStatus(status);
    const nextDelay = Number.isFinite(delay) ? delay : active ? 1000 : 5000;
    state.pollTimer = window.setTimeout(() => {
      state.pollTimer = null;
      refreshStatus(state.contextToken, true).catch((error) => {
        showMessage(`状态刷新失败：${error.message}`, "error");
        schedulePolling(5000);
      });
    }, nextDelay);
  }

  function clearPolling() {
    if (state.pollTimer) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  async function loadSelectedResult(token = state.contextToken) {
    if (!state.currentScheme) return;
    const requestContext = selectionKey();
    const data = await api(reliabilityPath("/api/reliability/results"));
    if (token !== state.contextToken || requestContext !== selectionKey()) return;

    const files = normalizeResultFiles(data.results || data.result_files || data.files);
    if (files.length) {
      state.resultFiles = files;
      renderResultOptions();
    }
    const result = extractResultPayload(data);
    state.result = result;
    renderResult(result);
  }

  function extractStatusPayload(data) {
    if (!data || typeof data !== "object") return null;
    const candidate = data.state || data.task || data.status_payload;
    if (candidate && typeof candidate === "object") return candidate;
    if (
      typeof data.status === "string" ||
      typeof data.task_status === "string" ||
      data.progress !== undefined ||
      Array.isArray(data.logs)
    ) {
      return data;
    }
    return null;
  }

  function extractResultPayload(data) {
    if (!data || typeof data !== "object") return null;
    const candidates = [data.result, data.selected_result, data.reliability_result, data.payload, data.data?.result];
    const direct = candidates.find((item) => item && typeof item === "object" && !Array.isArray(item));
    if (direct) return direct;
    const resultLikeKeys = [
      "metrics",
      "reliability_metrics",
      "n1_scenarios",
      "annual_distribution",
      "worst_year_series",
      "device_contributions",
    ];
    return resultLikeKeys.some((key) => data[key] !== undefined) ? data : null;
  }

  function renderCurrentSelection() {
    const target = document.getElementById("reliabilityCurrentSelection");
    if (!target) return;
    if (!state.currentScheme) {
      target.textContent = "当前：未选择方案";
      return;
    }
    const resultLabel = state.selectedResult ? resultDisplayName(state.selectedResult) : "默认/当前配置";
    target.textContent = `当前：${state.currentScheme} / ${resultLabel}`;
    target.title = target.textContent;
  }

  function renderAssumptionWarning() {
    const target = document.getElementById("reliabilityAssumptionWarning");
    if (!target) return;
    const source = String(state.parameters.assumption_source || DEMO_SOURCE).toLowerCase();
    const demo = !source || source.includes("demo") || source.includes("assumption") || source.includes("default");
    const warningText = state.parameterWarnings.length ? ` ${state.parameterWarnings.join("；")}` : "";
    target.dataset.authoritative = String(!demo);
    target.innerHTML = demo
      ? `<strong>演示场景假设：</strong>当前 FOR、MTTR、极寒系数、寿命与成本参数为系统演示默认值，均不是厂商承诺值、采购报价或现场统计。正式决策前应替换为极地运行实测与供应商数据。${escapeHtml(
          warningText,
        )}`
      : `<strong>已加载方案可靠性参数：</strong>来源标记为“${escapeHtml(
          state.parameters.assumption_source,
        )}”。仍应核对设备批次、极寒降额、维修可达性与统计期。${escapeHtml(warningText)}`;
  }

  function renderStatus(status) {
    const text = statusText(status) || "待启动";
    setText("reliabilityStatus", text);
    const progress = normalizeProgress(firstDefined(status?.progress, status?.progress_percent, status?.percent));
    const bar = document.getElementById("reliabilityProgressBar");
    if (bar) bar.style.width = `${progress}%`;

    const active = isActiveStatus(text);
    const queued = isQueuedStatus(text);
    const hasScheme = Boolean(state.currentScheme);
    setDisabled("startReliability", !hasScheme || active || queued);
    setDisabled("queueReliability", !hasScheme || active || queued);
    setDisabled("stopReliability", !hasScheme || (!active && !queued));
    document.getElementById("startReliability")?.classList.toggle("is-active", active);
    document.getElementById("queueReliability")?.classList.toggle("is-active", queued);
    renderLogs(status?.logs || state.result?.logs || []);
  }

  function statusText(status) {
    if (!status) return "";
    const raw = firstDefined(status.status, status.task_status, status.state, status.phase, "");
    if (raw && typeof raw === "object") return statusText(raw);
    const text = String(raw || "");
    const normalized = text.toLowerCase();
    const translations = {
      idle: "待启动",
      pending: "排队中",
      queued: "排队中",
      running: "运行中",
      stopping: "停止中",
      stopped: "已停止",
      complete: "已完成",
      completed: "已完成",
      success: "已完成",
      failed: "失败",
      error: "失败",
    };
    return translations[normalized] || text || "待启动";
  }

  function renderResult(result) {
    const metrics = extractMetrics(result);
    renderHeadlineMetrics(metrics, result);
    renderOverview(metrics, result);
    renderScenarioTable(result);
    renderDistribution(result);
    renderConvergence(result);
    renderWorstYear(result);
    renderContributions(result);
    renderAssumptionLog(result);
    renderLogs(state.status?.logs || result?.logs || []);
  }

  function extractMetrics(result) {
    if (!result || typeof result !== "object") return {};
    const sources = [
      result.metrics,
      result.reliability_metrics,
      result.summary,
      result.monte_carlo?.metrics,
      result.probabilistic?.metrics,
      result,
    ].filter((item) => item && typeof item === "object");
    const metric = (...keys) => firstFromSources(sources, keys);
    const lpsp = asNumber(metric("lpsp", "loss_of_power_supply_probability"));
    let reliability = asNumber(metric("supply_reliability", "supply_reliability_rate", "asai", "availability"));
    if (reliability === null && lpsp !== null) reliability = 1 - normalizeRatio(lpsp, 0);
    return {
      eens: asNumber(metric("eens_kwh_per_year", "eens_kwh", "EENS", "eens")),
      lole: asNumber(metric("lole_hours_per_year", "lole_h_per_year", "lole_hours", "LOLE", "lole")),
      lolp: asNumber(metric("lolp", "LOLP", "loss_of_load_probability")),
      supplyReliability: reliability,
      n1PassRate: asNumber(metric("n1_pass_rate", "n_1_pass_rate", "n1_rate")),
      p95Eens: asNumber(metric("p95_eens_kwh", "eens_p95_kwh", "p95_eens", "eens_p95")),
      maxUnmetPower: asNumber(metric("max_unmet_load_kw", "maximum_unserved_power_kw", "max_loss_kw")),
      maxOutageDuration: asNumber(metric("max_outage_duration_hours", "maximum_outage_duration_h", "max_loss_duration_h")),
      lpsp,
      simulationYears: asNumber(metric("simulation_years", "monte_carlo_years", "sample_years")),
      confidenceLevel: asNumber(metric("confidence_level", "ci_level")),
      eensCiLower: asNumber(metric("eens_ci_lower_kwh", "eens_ci_low", "eens_lower_ci")),
      eensCiUpper: asNumber(metric("eens_ci_upper_kwh", "eens_ci_high", "eens_upper_ci")),
      criticalLoadSupplyRate: asNumber(metric("critical_load_supply_rate", "critical_supply_reliability")),
    };
  }

  function renderHeadlineMetrics(metrics, result) {
    const scenarios = extractScenarios(result);
    const n1Rate = metrics.n1PassRate !== null && metrics.n1PassRate !== undefined
      ? metrics.n1PassRate
      : calculateScenarioPassRate(scenarios);
    setText("reliabilityEens", metricValue(metrics.eens, "kWh/a", 2));
    setText("reliabilityLole", metricValue(metrics.lole, "h/a", 2));
    setText("reliabilityLolp", percentValue(metrics.lolp, 3));
    setText("reliabilitySupplyRate", percentValue(metrics.supplyReliability, 4));
    setText("reliabilityN1Rate", percentValue(n1Rate, 1));
  }

  function renderOverview(metrics, result) {
    const target = document.getElementById("reliabilityOverview");
    if (!target) return;
    if (!result) {
      target.innerHTML = '<div class="reliability-empty" style="grid-column:1/-1">尚无可靠性评估结果。请选择方案与结果，核对场景假设后点击“启动”。</div>';
      return;
    }
    const scenarios = extractScenarios(result);
    const n1Rate = metrics.n1PassRate ?? calculateScenarioPassRate(scenarios);
    const confidence = formatConfidence(metrics);
    const cards = [
      ["年期望未供电量（EENS）", metricValue(metrics.eens, "kWh/a", 3), "衡量失供电规模；用于方案间风险比较，也可与 VOLL 结合计入经济损失。"],
      ["年期望失负荷时长（LOLE）", metricValue(metrics.lole, "h/a", 3), "衡量一年中供需无法平衡的期望小时数，不等于单次最长停电。"],
      ["失负荷概率（LOLP）", percentValue(metrics.lolp, 4), "任一时刻发生失负荷的概率，需结合模拟步长与样本年数解释。"],
      ["供电可靠率", percentValue(metrics.supplyReliability, 5), "按已供电量占总需求电量统计；与 ASAI 等用户侧指标并不等价。"],
      ["N-1 通过率", percentValue(n1Rate, 1), `${scenarios.length || 0} 个已返回场景中满足预设判据的比例。`],
      ["P95 年 EENS", metricValue(metrics.p95Eens, "kWh", 3), "95% 模拟年不超过该未供电量，用于观察均值掩盖的长尾风险。"],
      ["最大单次失供电功率", metricValue(metrics.maxUnmetPower, "kW", 2), "最不利时刻的功率缺口，反映备用与瞬时支撑边界。"],
      ["最大失供电持续时间", metricValue(metrics.maxOutageDuration, "h", 2), "最长连续失负荷时段，决定储能续航与维修响应要求。"],
      ["EENS 置信区间", confidence, "区间过宽说明样本不足或年度风险分布长尾明显，应增加模拟年数。"],
    ];
    target.innerHTML = cards
      .map(
        ([label, value, note]) => `<article class="reliability-summary-card">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
          <small>${escapeHtml(note)}</small>
        </article>`,
      )
      .join("");
  }

  function extractScenarios(result) {
    return firstArray(
      result?.n1_scenarios,
      result?.n_1_scenarios,
      result?.scenarios,
      result?.deterministic_scenarios,
      result?.deterministic?.scenarios,
      result?.n1?.scenarios,
    );
  }

  function renderScenarioTable(result) {
    const target = document.getElementById("reliabilityScenarioTable");
    if (!target) return;
    const rows = extractScenarios(result);
    if (!rows.length) {
      target.innerHTML = '<div class="reliability-empty">暂无 N-1 场景结果。仅蒙特卡洛模式不会生成该表；若已选择联合模式，请检查任务日志。</div>';
      return;
    }
    target.innerHTML = `<table>
      <thead><tr>
        <th>场景</th><th>停运设备</th><th>故障时长</th><th>最大缺供</th><th>未供电量</th><th>关键负荷</th><th>判定</th><th>说明</th>
      </tr></thead>
      <tbody>${rows
        .map((row, index) => {
          const pass = scenarioPass(row);
          const passText = pass === null ? "-" : pass ? "通过" : "未通过";
          const passColor = pass === null ? "" : pass ? "color:#baf7d2" : "color:#ffd6d6";
          return `<tr>
            <td>${escapeHtml(firstDefined(row.name, row.scenario, row.id, `N-1-${index + 1}`))}</td>
            <td>${escapeHtml(firstDefined(row.outage_device, row.failed_device, row.device, row.component, "-"))}</td>
            <td>${escapeHtml(metricValue(asNumber(firstDefined(row.duration_hours, row.outage_duration_h, row.duration)), "h", 2))}</td>
            <td>${escapeHtml(metricValue(asNumber(firstDefined(row.max_unmet_load_kw, row.max_shortage_kw, row.max_loss_kw)), "kW", 2))}</td>
            <td>${escapeHtml(metricValue(asNumber(firstDefined(row.eens_kwh, row.unserved_energy_kwh, row.energy_not_served_kwh)), "kWh", 2))}</td>
            <td>${escapeHtml(percentValue(asNumber(firstDefined(row.critical_load_supply_rate, row.critical_supply_rate)), 2))}</td>
            <td style="${passColor}"><strong>${passText}</strong></td>
            <td>${escapeHtml(firstDefined(row.note, row.message, row.reason, "-"))}</td>
          </tr>`;
        })
        .join("")}</tbody>
    </table>`;
  }

  function scenarioPass(row) {
    const value = firstDefined(row.pass, row.passed, row.is_pass, row.compliant, row.feasible);
    if (value === undefined || value === null || value === "") {
      const unmet = asNumber(firstDefined(row.unserved_energy_kwh, row.eens_kwh, row.max_unmet_load_kw));
      return unmet === null ? null : unmet <= 1e-9;
    }
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    const text = String(value).toLowerCase();
    if (["pass", "passed", "true", "yes", "ok", "通过", "满足"].includes(text)) return true;
    if (["fail", "failed", "false", "no", "未通过", "不满足"].includes(text)) return false;
    return null;
  }

  function calculateScenarioPassRate(rows) {
    if (!rows.length) return null;
    const values = rows.map(scenarioPass).filter((value) => value !== null);
    if (!values.length) return null;
    return values.filter(Boolean).length / values.length;
  }

  function annualDistributionValues(result) {
    const raw = firstArray(
      result?.annual_distribution,
      result?.annual_results,
      result?.monte_carlo?.annual_distribution,
      result?.monte_carlo?.annual_results,
      result?.probabilistic?.annual_distribution,
      result?.annual_eens,
    );
    return raw
      .map((item, index) => {
        if (typeof item === "number") return { year: index + 1, value: item };
        if (!item || typeof item !== "object") return null;
        const value = asNumber(firstDefined(item.eens_kwh, item.eens, item.unserved_energy_kwh, item.value));
        if (value === null) return null;
        return { year: asNumber(firstDefined(item.year, item.simulation_year, item.index)) ?? index + 1, value };
      })
      .filter(Boolean);
  }

  function renderDistribution(result) {
    const target = document.getElementById("reliabilityAnnualChart");
    if (!target) return;
    const values = annualDistributionValues(result).map((item) => item.value);
    if (!values.length) {
      target.innerHTML = '<div class="reliability-empty">暂无年度分布数据。确定性 N-1 模式不生成蒙特卡洛年度样本。</div>';
      return;
    }
    target.innerHTML = renderHistogramSvg(values, "EENS（kWh/模拟年）", "模拟年数量");
  }

  function convergencePoints(result) {
    const raw = firstArray(
      result?.convergence,
      result?.monte_carlo_convergence,
      result?.monte_carlo?.convergence,
      result?.probabilistic?.convergence,
    );
    const points = raw
      .map((item, index) => {
        if (typeof item === "number") return { x: index + 1, mean: item, low: null, high: null };
        if (!item || typeof item !== "object") return null;
        const mean = asNumber(firstDefined(item.mean_eens_kwh, item.eens_mean_kwh, item.cumulative_eens, item.mean, item.value));
        if (mean === null) return null;
        return {
          x: asNumber(firstDefined(item.simulation_years, item.sample_count, item.years, item.n, item.year)) ?? index + 1,
          mean,
          low: asNumber(firstDefined(item.ci_lower_kwh, item.lower, item.low)),
          high: asNumber(firstDefined(item.ci_upper_kwh, item.upper, item.high)),
        };
      })
      .filter(Boolean);
    if (points.length) return points;

    const annual = annualDistributionValues(result);
    if (annual.length < 2) return [];
    let sum = 0;
    const stride = Math.max(1, Math.floor(annual.length / 80));
    return annual
      .map((item, index) => {
        sum += item.value;
        return { x: index + 1, mean: sum / (index + 1), low: null, high: null };
      })
      .filter((item, index) => index === annual.length - 1 || index % stride === 0);
  }

  function renderConvergence(result) {
    const target = document.getElementById("reliabilityConvergenceChart");
    if (!target) return;
    const points = convergencePoints(result);
    if (!points.length) {
      target.innerHTML = '<div class="reliability-empty">暂无收敛序列。后端可返回 simulation_years、mean_eens_kwh 与置信区间上下界。</div>';
      return;
    }
    target.innerHTML = renderConvergenceSvg(points);
  }

  function worstYearPoints(result) {
    const raw = firstArray(
      result?.worst_year_series,
      result?.worst_year?.series,
      result?.monte_carlo?.worst_year_series,
      result?.probabilistic?.worst_year_series,
      result?.worst_case_series,
    );
    return raw
      .map((item, index) => {
        if (!item || typeof item !== "object") return null;
        return {
          x: asNumber(firstDefined(item.hour, item.time_index, item.index, item.t)) ?? index,
          load: asNumber(firstDefined(item.load_kw, item.demand_kw, item.load)),
          supply: asNumber(firstDefined(item.supplied_load_kw, item.available_generation_kw, item.supply_kw, item.generation_kw)),
          unmet: asNumber(firstDefined(item.unmet_load_kw, item.shortage_kw, item.loss_kw, item.unserved_power_kw)),
        };
      })
      .filter((item) => item.load !== null || item.supply !== null || item.unmet !== null);
  }

  function renderWorstYear(result) {
    const target = document.getElementById("reliabilityWorstYearChart");
    if (!target) return;
    const points = worstYearPoints(result);
    if (!points.length) {
      target.innerHTML = '<div class="reliability-empty">暂无最差年时序。联合或蒙特卡洛评估完成后，可在此查看负荷、可供功率与未供电功率的时间对应关系。</div>';
      return;
    }
    const stride = Math.max(1, Math.ceil(points.length / 1200));
    const sampled = points.filter((item, index) => index % stride === 0 || index === points.length - 1);
    target.innerHTML = renderMultiLineSvg(
      sampled,
      [
        { key: "load", label: "负荷", color: "#f7c75d" },
        { key: "supply", label: "可供/已供功率", color: "#21d5ff" },
        { key: "unmet", label: "未供电功率", color: "#ff6b7a" },
      ],
      "小时",
      "功率（kW）",
    );
  }

  function contributionRows(result) {
    return firstArray(
      result?.device_contributions,
      result?.failure_contributions,
      result?.contributions,
      result?.monte_carlo?.device_contributions,
    );
  }

  function renderContributions(result) {
    const target = document.getElementById("reliabilityContributionTable");
    if (!target) return;
    const rows = contributionRows(result);
    if (!rows.length) {
      target.innerHTML = '<div class="reliability-empty">暂无设备故障贡献分解。该区域用于识别 EENS 的主要来源，不应把相关故障简单归因于单台设备。</div>';
      return;
    }
    target.innerHTML = `<table>
      <thead><tr><th>设备/故障组</th><th>EENS 贡献</th><th>占比</th><th>事件数</th></tr></thead>
      <tbody>${rows
        .map((row) => `<tr>
          <td>${escapeHtml(firstDefined(row.label, row.device_name, row.device_type, row.component, "-"))}</td>
          <td>${escapeHtml(metricValue(asNumber(firstDefined(row.eens_kwh, row.unserved_energy_kwh, row.value)), "kWh", 2))}</td>
          <td>${escapeHtml(percentValue(asNumber(firstDefined(row.share, row.ratio, row.contribution_rate)), 2))}</td>
          <td>${escapeHtml(integerValue(asNumber(firstDefined(row.event_count, row.events, row.count))))}</td>
        </tr>`)
        .join("")}</tbody>
    </table>`;
  }

  function assumptionItems(result) {
    const raw = firstArray(
      result?.assumption_log,
      result?.assumptions,
      result?.method_assumptions,
      result?.metadata?.assumptions,
    );
    if (raw.length) return raw;
    return [
      { name: "参数来源", value: state.parameters.assumption_source || DEMO_SOURCE, note: "场景假设必须与实测或厂商数据区分。" },
      { name: "评估模式", value: modeLabel(state.parameters.mode), note: "确定性可行不等于概率可靠。" },
      { name: "蒙特卡洛年数", value: state.parameters.simulation_years, unit: "年", note: "样本不足时置信区间会较宽。" },
      { name: "关键负荷比例", value: round(state.parameters.critical_load_ratio * 100, 3), unit: "%", note: "负荷分级依据需由站区运行单位确认。" },
      { name: "成本参数", value: "场景假设、非采购报价", note: "CAPEX、固定运维和柴发变动运维只用于方案比较口径。" },
      { name: "独立故障假设", value: "默认启用", note: "共同原因故障、极端天气相关故障需另行建模。" },
    ];
  }

  function renderAssumptionLog(result) {
    const target = document.getElementById("reliabilityAssumptionLog");
    if (!target) return;
    const items = assumptionItems(result);
    target.innerHTML = items
      .map((item) => {
        if (typeof item === "string") return `<li>${escapeHtml(item)}</li>`;
        const name = firstDefined(item.name, item.key, item.parameter, item.title, "假设");
        const value = firstDefined(item.value, item.setting, item.description, "-");
        const unit = item.unit ? ` ${item.unit}` : "";
        const source = item.source ? `；来源：${item.source}` : "";
        const note = firstDefined(item.note, item.boundary, item.message, "");
        return `<li><strong>${escapeHtml(name)}：</strong>${escapeHtml(value)}${escapeHtml(unit)}${escapeHtml(source)}${
          note ? `<br>${escapeHtml(note)}` : ""
        }</li>`;
      })
      .join("");
  }

  function renderLogs(logs) {
    const target = document.getElementById("reliabilityLogs");
    if (!target) return;
    const rows = Array.isArray(logs) ? logs : [];
    if (!rows.length) {
      target.innerHTML = '<div class="reliability-empty">暂无运行日志。</div>';
      return;
    }
    target.innerHTML = rows
      .map((item) => {
        if (typeof item === "string") return `<div class="log-line"><strong>${escapeHtml(item)}</strong></div>`;
        const level = String(item.level || item.status || "info").toLowerCase();
        const css = level.includes("error") ? "error" : level.includes("warn") ? "warn" : level.includes("ok") || level.includes("success") ? "ok" : "";
        return `<div class="log-line ${css}"><span>${escapeHtml(
          firstDefined(item.time, item.timestamp, item.created_at, ""),
        )}</span><strong>${escapeHtml(firstDefined(item.message, item.text, item.detail, ""))}</strong></div>`;
      })
      .join("");
    target.scrollTop = target.scrollHeight;
  }

  function renderHistogramSvg(values, xLabel, yLabel) {
    const finite = values.filter(Number.isFinite);
    if (!finite.length) return '<div class="reliability-empty">暂无可绘制数据。</div>';
    const width = 760;
    const height = 280;
    const margin = { left: 62, right: 20, top: 24, bottom: 48 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const minValue = Math.min(...finite);
    const maxValue = Math.max(...finite);
    const binCount = Math.max(5, Math.min(18, Math.round(Math.sqrt(finite.length))));
    const span = maxValue - minValue || Math.max(1, Math.abs(maxValue) * 0.1);
    const binWidth = span / binCount;
    const bins = Array.from({ length: binCount }, (_, index) => ({
      start: minValue + index * binWidth,
      end: minValue + (index + 1) * binWidth,
      count: 0,
    }));
    finite.forEach((value) => {
      const index = Math.min(binCount - 1, Math.max(0, Math.floor((value - minValue) / binWidth)));
      bins[index].count += 1;
    });
    const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
    const barGap = 3;
    const barWidth = plotWidth / binCount - barGap;
    const bars = bins
      .map((bin, index) => {
        const x = margin.left + (index * plotWidth) / binCount + barGap / 2;
        const h = (bin.count / maxCount) * plotHeight;
        return `<rect x="${round(x, 2)}" y="${round(margin.top + plotHeight - h, 2)}" width="${round(
          Math.max(1, barWidth),
          2,
        )}" height="${round(h, 2)}" rx="2" fill="rgba(33,213,255,0.58)" stroke="rgba(108,238,255,0.86)"><title>${formatNumber(
          bin.start,
          2,
        )}–${formatNumber(bin.end, 2)} kWh：${bin.count} 年</title></rect>`;
      })
      .join("");
    const grid = axisGrid(width, height, margin, 5, maxCount, (value) => formatNumber(value, 0));
    const p50 = quantile(finite, 0.5);
    const p95 = quantile(finite, 0.95);
    const xScale = (value) => margin.left + ((value - minValue) / span) * plotWidth;
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="年度 EENS 分布直方图">
      ${grid}
      ${bars}
      ${referenceLine(xScale(p50), margin.top, plotHeight, "#f7c75d", `P50 ${formatNumber(p50, 2)}`)}
      ${referenceLine(xScale(p95), margin.top, plotHeight, "#ff6b7a", `P95 ${formatNumber(p95, 2)}`)}
      <text x="${margin.left + plotWidth / 2}" y="${height - 8}" text-anchor="middle">${escapeHtml(xLabel)}</text>
      <text x="14" y="${margin.top + plotHeight / 2}" text-anchor="middle" transform="rotate(-90 14 ${
        margin.top + plotHeight / 2
      })">${escapeHtml(yLabel)}</text>
      <text x="${margin.left}" y="${height - 27}" text-anchor="start">${formatNumber(minValue, 2)}</text>
      <text x="${margin.left + plotWidth}" y="${height - 27}" text-anchor="end">${formatNumber(maxValue, 2)}</text>
    </svg>`;
  }

  function renderConvergenceSvg(points) {
    const series = [
      { key: "mean", label: "累计平均 EENS", color: "#21d5ff" },
      { key: "low", label: "置信区间下界", color: "#7dd3a8", dash: "6 4" },
      { key: "high", label: "置信区间上界", color: "#ff9f67", dash: "6 4" },
    ].filter((item) => points.some((point) => Number.isFinite(point[item.key])));
    return renderMultiLineSvg(points, series, "模拟年数", "EENS（kWh/a）");
  }

  function renderMultiLineSvg(points, series, xLabel, yLabel) {
    const width = 900;
    const height = 300;
    const margin = { left: 70, right: 24, top: 38, bottom: 48 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const xValues = points.map((point) => asNumber(point.x)).filter(Number.isFinite);
    const yValues = series.flatMap((item) => points.map((point) => asNumber(point[item.key])).filter(Number.isFinite));
    if (!xValues.length || !yValues.length) return '<div class="reliability-empty">暂无可绘制数据。</div>';
    let minX = Math.min(...xValues);
    let maxX = Math.max(...xValues);
    let minY = Math.min(0, Math.min(...yValues));
    let maxY = Math.max(...yValues);
    if (maxX === minX) maxX = minX + 1;
    if (maxY === minY) maxY = minY + 1;
    const xScale = (value) => margin.left + ((value - minX) / (maxX - minX)) * plotWidth;
    const yScale = (value) => margin.top + plotHeight - ((value - minY) / (maxY - minY)) * plotHeight;
    const grid = axisGrid(width, height, margin, 5, maxY, (value) => formatNumber(value, 2), minY);
    const paths = series
      .map((item) => {
        const segments = [];
        let current = [];
        points.forEach((point) => {
          const x = asNumber(point.x);
          const y = asNumber(point[item.key]);
          if (!Number.isFinite(x) || !Number.isFinite(y)) {
            if (current.length) segments.push(current);
            current = [];
            return;
          }
          current.push(`${current.length ? "L" : "M"}${round(xScale(x), 2)},${round(yScale(y), 2)}`);
        });
        if (current.length) segments.push(current);
        return segments
          .map(
            (segment) => `<path d="${segment.join(" ")}" fill="none" stroke="${item.color}" stroke-width="2"${
              item.dash ? ` stroke-dasharray="${item.dash}"` : ""
            } vector-effect="non-scaling-stroke"/>`,
          )
          .join("");
      })
      .join("");
    const legend = series
      .map(
        (item, index) => `<g transform="translate(${margin.left + index * 190},16)">
          <line x1="0" y1="0" x2="26" y2="0" stroke="${item.color}" stroke-width="3"${
            item.dash ? ` stroke-dasharray="${item.dash}"` : ""
          }/>
          <text x="34" y="4">${escapeHtml(item.label)}</text>
        </g>`,
      )
      .join("");
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(yLabel)}时序曲线">
      ${grid}${paths}${legend}
      <text x="${margin.left + plotWidth / 2}" y="${height - 8}" text-anchor="middle">${escapeHtml(xLabel)}</text>
      <text x="15" y="${margin.top + plotHeight / 2}" text-anchor="middle" transform="rotate(-90 15 ${
        margin.top + plotHeight / 2
      })">${escapeHtml(yLabel)}</text>
      ${xAxisLabels(minX, maxX, margin, plotWidth, height)}
    </svg>`;
  }

  function axisGrid(width, height, margin, tickCount, maxValue, formatter, minValue = 0) {
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    return Array.from({ length: tickCount + 1 }, (_, index) => {
      const ratio = index / tickCount;
      const y = margin.top + plotHeight - ratio * plotHeight;
      const value = minValue + ratio * (maxValue - minValue);
      return `<line x1="${margin.left}" y1="${round(y, 2)}" x2="${margin.left + plotWidth}" y2="${round(
        y,
        2,
      )}" stroke="rgba(108,147,160,0.22)"/><text x="${margin.left - 9}" y="${round(y + 4, 2)}" text-anchor="end">${escapeHtml(
        formatter(value),
      )}</text>`;
    }).join("");
  }

  function xAxisLabels(minX, maxX, margin, plotWidth, height) {
    return Array.from({ length: 6 }, (_, index) => {
      const ratio = index / 5;
      const x = margin.left + ratio * plotWidth;
      const value = minX + ratio * (maxX - minX);
      return `<text x="${round(x, 2)}" y="${height - 27}" text-anchor="middle">${escapeHtml(formatNumber(value, 0))}</text>`;
    }).join("");
  }

  function referenceLine(x, top, plotHeight, color, label) {
    if (!Number.isFinite(x)) return "";
    return `<line x1="${round(x, 2)}" y1="${top}" x2="${round(x, 2)}" y2="${top + plotHeight}" stroke="${color}" stroke-width="2" stroke-dasharray="5 4"/>
      <text x="${round(x + 4, 2)}" y="${top + 13}" fill="${color}">${escapeHtml(label)}</text>`;
  }

  function formatConfidence(metrics) {
    if (metrics.eensCiLower !== null && metrics.eensCiUpper !== null) {
      const level = metrics.confidenceLevel === null ? "" : `${percentValue(metrics.confidenceLevel, 0)} `;
      return `${level}[${formatNumber(metrics.eensCiLower, 2)}, ${formatNumber(metrics.eensCiUpper, 2)}] kWh/a`;
    }
    return "-";
  }

  function modeLabel(mode) {
    return {
      both: "确定性 N-1 + 序贯蒙特卡洛",
      deterministic: "仅确定性 N-1",
      monte_carlo: "仅序贯蒙特卡洛",
    }[mode] || mode || "-";
  }

  function reliabilityPath(base, extra = {}) {
    const query = new URLSearchParams({ scheme: state.currentScheme, ...extra });
    if (state.selectedResult) query.set("filename", state.selectedResult);
    return `${base}?${query.toString()}`;
  }

  function selectionKey() {
    return `${state.currentScheme}|${state.selectedResult}`;
  }

  function resultDisplayName(filename) {
    return String(filename || "")
      .replace(/_reliability_results?\.json$/i, "")
      .replace(/_results?\.(xlsx|json|csv)$/i, "")
      .replace(/\.(xlsx|json|csv)$/i, "");
  }

  function isActiveStatus(text) {
    const value = String(text || "").toLowerCase();
    return value.includes("运行") || value.includes("running") || value.includes("stopping") || value.includes("停止中");
  }

  function isQueuedStatus(text) {
    const value = String(text || "").toLowerCase();
    return value.includes("排队") || value.includes("queue") || value.includes("pending");
  }

  function isCompletedStatus(text) {
    const value = String(text || "").toLowerCase();
    return value.includes("完成") || value.includes("complete") || value.includes("success");
  }

  function normalizeProgress(value) {
    const number = asNumber(value);
    if (number === null) return isCompletedStatus(statusText(state.status)) ? 100 : 0;
    return Math.max(0, Math.min(100, number <= 1 ? number * 100 : number));
  }

  function normalizeWarnings(value) {
    if (!value) return [];
    if (Array.isArray(value)) return value.map((item) => String(item?.message || item || "")).filter(Boolean);
    return [String(value.message || value)].filter(Boolean);
  }

  function normalizeRatio(value, fallback = null) {
    const number = asNumber(value);
    if (number === null) return fallback;
    return Math.max(0, Math.min(1, Math.abs(number) <= 1.0000001 ? number : number / 100));
  }

  function metricValue(value, unit, digits = 2) {
    const number = asNumber(value);
    if (number === null) return "-";
    return `${formatNumber(number, digits)}${unit ? ` ${unit}` : ""}`;
  }

  function percentValue(value, digits = 2) {
    const number = asNumber(value);
    if (number === null) return "-";
    const percent = Math.abs(number) <= 1.0000001 ? number * 100 : number;
    return `${formatNumber(percent, digits)}%`;
  }

  function integerValue(value) {
    const number = asNumber(value);
    return number === null ? "-" : formatNumber(number, 0);
  }

  function formatNumber(value, maximumFractionDigits = 2) {
    const number = asNumber(value);
    if (number === null) return "-";
    return new Intl.NumberFormat("zh-CN", {
      maximumFractionDigits,
      minimumFractionDigits: 0,
    }).format(number);
  }

  function quantile(values, probability) {
    const sorted = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
    if (!sorted.length) return null;
    const position = (sorted.length - 1) * probability;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
  }

  function requiredInteger(id, label, min, max) {
    const input = document.getElementById(id);
    return validatedNumber(input?.value, label, min, max, true);
  }

  function requiredNumber(id, label, min, max) {
    const input = document.getElementById(id);
    return validatedNumber(input?.value, label, min, max, false);
  }

  function validatedNumber(value, label, min, max, integer) {
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`${label}必须是有效数字。`);
    if (number < min || number > max) throw new Error(`${label}必须在 ${min}–${max} 之间。`);
    if (integer && !Number.isInteger(number)) throw new Error(`${label}必须是整数。`);
    return number;
  }

  function clampInteger(value, min, max, fallback) {
    const number = asNumber(value);
    if (number === null) return fallback;
    return Math.round(Math.max(min, Math.min(max, number)));
  }

  function clampNumber(value, min, max, fallback) {
    const number = asNumber(value);
    if (number === null) return fallback;
    return Math.max(min, Math.min(max, number));
  }

  function asNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function firstDefined(...values) {
    return values.find((value) => value !== undefined && value !== null && value !== "");
  }

  function firstFromSources(sources, keys) {
    for (const source of sources) {
      for (const key of keys) {
        if (source[key] !== undefined && source[key] !== null && source[key] !== "") return source[key];
      }
    }
    return null;
  }

  function firstArray(...values) {
    return values.find((value) => Array.isArray(value)) || [];
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function round(value, digits = 2) {
    const factor = 10 ** digits;
    return Math.round((Number(value) + Number.EPSILON) * factor) / factor;
  }

  function numberInputValue(value) {
    const number = asNumber(value);
    return number === null ? "" : String(number);
  }

  function setValue(id, value) {
    const target = document.getElementById(id);
    if (target && value !== undefined && value !== null) target.value = String(value);
  }

  function setText(id, value) {
    const target = document.getElementById(id);
    if (target) target.textContent = value === undefined || value === null || value === "" ? "-" : String(value);
  }

  function setDisabled(id, disabled) {
    const target = document.getElementById(id);
    if (!target) return;
    target.disabled = Boolean(disabled);
    target.classList.toggle("is-disabled", Boolean(disabled));
  }

  function showMessage(message, type = "") {
    const target = document.getElementById("reliabilityMessage");
    if (!target) return;
    target.hidden = !message;
    target.className = `reliability-message${type ? ` ${type}` : ""}`;
    target.textContent = message || "";
    if (message && type === "ok") {
      window.setTimeout(() => {
        if (target.textContent === message) target.hidden = true;
      }, 4500);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
})();
