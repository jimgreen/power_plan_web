const state = {
  schemes: [],
  currentScheme: "",
  payload: null,
  month: 0,
  timeChartRange: { scope: "year", month: 0, day: 1 },
  timeSeriesLoading: null,
  timeSeriesDirty: false,
  loadCurveTemplates: [],
  mapConfig: null,
  mapPoint: null,
  mapInstance: null,
  mapMarker: null,
  mapCleanup: null,
  mapProvider: "amap",
  mapReverseGeocodeToken: 0,
  chartMeta: null,
  chartDrag: null,
  pendingWeatherRows: null,
  pendingWeatherMeta: null,
  weatherPreviewVisibleCurves: new Set(["wind_speed", "solar_irradiance", "temperature"]),
  weatherPreviewManualHeight: null,
  loadPreviewMeta: null,
  loadPreviewDrag: null,
  timeSeriesImportManualChartHeight: null,
  timeSeriesImportVisibleCurves: new Set(["wind_speed", "solar_irradiance", "temperature", "load"]),
  timeSeriesImportChartMeta: null,
  timeSeriesImportChartFrame: 0,
  timeSeriesImportDrag: null,
  timeChartManualHeight: null,
  layoutObserver: null,
  layoutFrame: 0,
  timeChartRenderFrame: 0,
  schemeRailLayoutFrame: 0,
  schemeRailManualHeight: null,
  pendingTimeSeriesImport: null,
  pendingLoadCurve: null,
  originalLoadCurve: null,
  loadGeneratorSourceCurve: null,
  loadGeneratorSourceName: "",
  curveGeneratorTarget: "wind_speed",
  isSwitchingScheme: false,
};

let activePlanningParameterGroup = "normal";
let activeDeviceContextTarget = null;
let activeDeviceEditingCell = null;
let activeTimeEditingCell = null;

const PLANNING_PAGE_STATE_KEY = "planning";
const WEATHER_COORDINATE_STORAGE_KEY = "powerPlanWeatherCoordinate";
const COLLAPSED_PANEL_SIZE = 0;
const AMAP_TILE_SIZE = 256;
const AMAP_MIN_ZOOM = 2;
const AMAP_MAX_ZOOM = 18;
const AMAP_DEFAULT_ZOOM = 4;
const WEB_MERCATOR_MAX_LAT = 85.05112878;
const GLOBAL_TILE_SOURCE_LABEL = "OpenStreetMap 全球底图";
const OSM_TILE_PROVIDERS = [
  {
    name: "OpenStreetMap DE",
    url: (x, y, z) => `https://tile.openstreetmap.de/${z}/${x}/${y}.png`,
  },
  {
    name: "OpenStreetMap France HOT",
    url: (x, y, z) => `https://a.tile.openstreetmap.fr/hot/${z}/${x}/${y}.png`,
  },
  {
    name: "CartoDB Light",
    url: (x, y, z) => `https://b.basemaps.cartocdn.com/light_all/${z}/${x}/${y}.png`,
  },
  {
    name: "OpenStreetMap",
    url: (x, y, z) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`,
  },
];

const deviceSpecs = [
  ["diesel_generators", "柴发", ["name", "cost", "capacity", "power_upper", "power_lower", "fuel_rate", "inertia_constant_h", "primary_frequency_coefficient_k", "damping_coefficient_d", "governor_time_constant_t", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["wind_turbines", "风机", ["name", "cost", "capacity", "cut_in_wind_speed", "rated_wind_speed", "cut_out_wind_speed", "is_grid_forming", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["photovoltaics", "光伏", ["name", "cost", "capacity", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["storage_pcs", "储能PCS", ["name", "cost", "power_capacity", "storage_charge_efficiency", "storage_discharge_efficiency", "is_grid_forming", "storage_equivalent_inertia_constant_h", "storage_equivalent_primary_frequency_coefficient_k", "storage_equivalent_damping_coefficient_d", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["storage_battery_packs", "储能电池组", ["name", "cost", "battery_capacity", "soc_upper", "soc_lower", "self_discharge_rate", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["hydrogen_electrolyzers", "电制氢", ["name", "cost", "power_capacity", "power_lower", "electric_to_hydrogen_efficiency", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["hydrogen_tanks", "储氢罐", ["name", "cost", "hydrogen_tank_capacity", "soc_upper", "soc_lower", "self_discharge_rate", "quantity_lower", "quantity_upper", "design_life_years"]],
  ["fuel_cells", "燃料电池", ["name", "cost", "power_capacity", "hydrogen_to_electric_efficiency", "quantity_lower", "quantity_upper", "design_life_years"]],
];

const summarySeries = [
  ["wind_speed", "风速", "#1f9bb4", "m/s"],
  ["solar_irradiance", "太阳辐照", "#d79018", "W/m2"],
  ["temperature", "环境温度", "#7a5aa6", "℃"],
  ["load", "负荷", "#2d6b45", "kW"],
];

const timeSeriesImportSeries = [
  ["wind_speed", "风速", "#21d5ff", "m/s"],
  ["solar_irradiance", "太阳辐射", "#ffd166", "W/m2"],
  ["temperature", "环境温度", "#b292ff", "℃"],
  ["load", "负荷", "#64e6a3", "kW"],
];

const timeSeriesValueKeys = new Set(["wind_speed", "solar_irradiance", "temperature", "load"]);
const weatherPreviewSeries = timeSeriesImportSeries.filter(([key]) => key !== "load");

const curveGeneratorSpecs = {
  wind_speed: {
    key: "wind_speed",
    label: "风速",
    title: "风速生成",
    unit: "m/s",
    maxLabel: "风速最大值",
    minLabel: "风速最小值",
    averageLabel: "风速平均值",
    generateLabel: "生成风速曲线",
    saveTemplateVisible: false,
    emptyPreview: "生成后显示风速曲线预览",
    adjustedMessage: "风速曲线已调整，请检查预览后点击确定。",
    generatedMessage: "风速曲线已生成，请检查预览后点击确定。",
    confirmMessage: "风速曲线已确认，请保存方案",
    cancelMessage: "风速生成已取消",
    sourceLoadedMessage: "原始风速曲线已载入，请点击生成风速曲线。",
    importedMessage: "风速文件已导入为原始曲线，请点击生成风速曲线。",
    importFailedPrefix: "风速文件导入失败：",
    generationFailedPrefix: "风速生成失败：",
    selectedFileMessage: "请先选择风速文件",
    invalidLengthMessage: "风速曲线应为8760点",
    tableInvalidMessage: "当前时序表不是8760行，未更新风速",
  },
  solar_irradiance: {
    key: "solar_irradiance",
    label: "光照辐射",
    title: "光照辐射生成",
    unit: "W/m2",
    maxLabel: "光照辐射最大值",
    minLabel: "光照辐射最小值",
    averageLabel: "光照辐射平均值",
    generateLabel: "生成光照辐射曲线",
    saveTemplateVisible: false,
    emptyPreview: "生成后显示光照辐射曲线预览",
    adjustedMessage: "光照辐射曲线已调整，请检查预览后点击确定。",
    generatedMessage: "光照辐射曲线已生成，请检查预览后点击确定。",
    confirmMessage: "光照辐射曲线已确认，请保存方案",
    cancelMessage: "光照辐射生成已取消",
    sourceLoadedMessage: "原始光照辐射曲线已载入，请点击生成光照辐射曲线。",
    importedMessage: "光照辐射文件已导入为原始曲线，请点击生成光照辐射曲线。",
    importFailedPrefix: "光照辐射文件导入失败：",
    generationFailedPrefix: "光照辐射生成失败：",
    selectedFileMessage: "请先选择光照辐射文件",
    invalidLengthMessage: "光照辐射曲线应为8760点",
    tableInvalidMessage: "当前时序表不是8760行，未更新光照辐射",
  },
  load: {
    key: "load",
    label: "负荷",
    title: "负荷生成",
    unit: "kW",
    maxLabel: "负荷最大值",
    minLabel: "负荷最小值",
    averageLabel: "负荷平均值",
    generateLabel: "生成负荷曲线",
    saveTemplateVisible: true,
    emptyPreview: "生成后显示负荷曲线预览",
    adjustedMessage: "负荷曲线已调整，请检查预览后点击确定。",
    generatedMessage: "负荷曲线已生成，请检查预览后点击确定。",
    confirmMessage: "负荷曲线已确认，请保存方案",
    cancelMessage: "负荷生成已取消",
    sourceLoadedMessage: "原始负荷曲线已载入，请点击生成负荷曲线。",
    importedMessage: "负荷文件已导入为原始曲线，请点击生成负荷曲线。",
    importFailedPrefix: "负荷文件导入失败：",
    generationFailedPrefix: "负荷生成失败：",
    selectedFileMessage: "请先选择负荷文件",
    invalidLengthMessage: "负荷曲线应为8760点",
    tableInvalidMessage: "当前时序表不是8760行，未更新负荷",
  },
};

const planningParameterSpecs = [
  ["diesel_price", "柴油价格(万元/吨)", "number", { min: 0, defaultValue: 0 }],
  ["diesel_minimum_on_hours", "柴发开机持续工作小时数下限", "number", { min: 0, max: 24, integer: true, defaultValue: 12 }],
  ["diesel_minimum_off_hours", "柴发关机持续工作小时数下限", "number", { min: 0, max: 24, integer: true, defaultValue: 12 }],
  ["operation_mode", "工作模式", "select", { defaultValue: "annual", options: [["annual", "全年运行"], ["summer", "度夏运行"]] }],
  ["winter_start_month", "冬季开始月份", "number", { min: 1, max: 12, integer: true, positive: true, defaultValue: 10 }],
  ["winter_start_day", "冬季开始日期", "number", { min: 1, max: 31, integer: true, positive: true, defaultValue: 1 }],
  ["winter_end_month", "冬季结束月份", "number", { min: 1, max: 12, integer: true, positive: true, defaultValue: 4 }],
  ["winter_end_day", "冬季结束日期", "number", { min: 1, max: 31, integer: true, positive: true, defaultValue: 30 }],
  ["green_power_ratio_lower", "绿色电量占比下限(0.0-1.0)", "number", { min: 0, max: 1, defaultValue: 0 }],
  ["optimization_time_limit_minutes", "规划求解时间上限(分钟)", "number", { min: 10, max: 1440, integer: true, positive: true, defaultValue: 60 }],
  ["preferred_solver", "优先求解器", "select", { defaultValue: "auto", options: [["auto", "自动选择"], ["gurobi", "Gurobi"], ["cplex", "CPLEX"], ["mosek", "原生MOSEK"], ["scipy", "SciPy HiGHS"]] }],
  ["initial_storage_soc_ratio", "初始电储SOC(0.0-1.0)", "number", { min: 0, max: 1, defaultValue: 0.5 }],
  ["storage_balance_mode", "电储能平衡模式", "select", { defaultValue: "daily", options: [["daily", "日内平衡"], ["weekly", "周内平衡"], ["monthly", "月度平衡"], ["annual", "年度平衡"], ["none", "不闭环"]] }],
  ["initial_hydrogen_storage_ratio", "初始氢储SOC(0.0-1.0)", "number", { min: 0, max: 1, defaultValue: 0.5 }],
  ["post_disturbance_power_balance_enabled", "是否考虑扰动后平衡约束", "boolean", { defaultValue: 1 }],
  ["renewable_n_1_enabled", "是否考虑新能源N-1", "boolean", { defaultValue: 0 }],
  ["renewable_disturbance_enabled", "是否考虑新能源扰动", "boolean", { defaultValue: 0 }],
  ["load_disturbance_enabled", "是否考虑负荷扰动", "boolean", { defaultValue: 0 }],
  ["load_up_disturbance_factor", "负荷向上扰动系数(0.0-0.5)", "number", { min: 0, max: 0.5, defaultValue: 0 }],
  ["load_down_disturbance_factor", "负荷向下扰动系数(0.0-0.5)", "number", { min: 0, max: 0.5, defaultValue: 0 }],
  ["renewable_down_disturbance_factor", "新能源向下扰动系数(0.0-0.5)", "number", { min: 0, max: 0.5, defaultValue: 0 }],
  ["frequency_security_constraint_enabled", "是否考虑频率安全约束", "boolean", { defaultValue: 0 }],
  ["nominal_frequency_hz", "额定频率(Hz)", "number", { min: 45, max: 65, defaultValue: 50.0 }],
  ["frequency_nadir_lower_hz", "频率最低点下限(Hz)", "number", { min: 45, max: 65, defaultValue: 49.5 }],
  ["frequency_peak_upper_hz", "频率最高点上限(Hz)", "number", { min: 45, max: 65, defaultValue: 50.5 }],
  ["frequency_lower_security_margin_hz", "频率下限安全裕度(Hz)", "number", { min: 0, max: 2, defaultValue: 0.0 }],
  ["frequency_upper_security_margin_hz", "频率上限安全裕度(Hz)", "number", { min: 0, max: 2, defaultValue: 0.0 }],
  ["load_frequency_coefficient_d", "负荷频率系数D", "number", { min: 0, max: 20, defaultValue: 0.0 }],
  ["rocof_upper_hz_per_s", "RoCoF上限(Hz/s)", "number", { min: 0.0001, max: 20, defaultValue: 1.0 }],
  ["steady_state_frequency_lower_hz", "稳态频率下限(Hz)", "number", { min: 0, max: 65, defaultValue: 49.5 }],
  ["steady_state_frequency_upper_hz", "稳态频率上限(Hz)", "number", { min: 0, max: 65, defaultValue: 50.5 }],
  ["frequency_governor_time_constant_s", "频率等效调速时间常数T(s)", "number", { min: 0, max: 20, defaultValue: 0.6 }],
  ["frequency_nadir_evaluation_duration_s", "频率Nadir评估时长(s)", "number", { min: 1, max: 200, defaultValue: 20.0 }],
  ["nadir_linearization_samples_per_axis", "Nadir线性化每轴采样点数", "number", { min: 2, max: 7, integer: true, positive: true, integerMessage: "Nadir线性化每轴采样点数必须为正整数", defaultValue: 4 }],
  ["nadir_linearization_interval_ratio", "Nadir线性化区间比例", "number", { min: 0.05, max: 1, defaultValue: 0.5 }],
  ["network_synchronization_coefficient_base", "网络同步系数基值", "number", { min: -100, max: 100, defaultValue: 1.0 }],
  ["network_synchronization_coefficient_slope", "网络同步系数斜率", "number", { min: -100, max: 100, defaultValue: 0.0 }],
  ["network_synchronization_reference_load_kw", "网络同步系数基准负荷(kW)", "number", { min: 0, defaultValue: 0.0 }],
  ["storage_frequency_regulation_enabled", "储能是否参与调频", "boolean", { defaultValue: 0 }],
];

const planningParameterSpecsByKey = new Map(planningParameterSpecs.map((spec) => [spec[0], spec]));

const planningParameterGroups = [
  {
    key: "normal",
    title: "常规参数",
    keys: [
      "diesel_price",
      "diesel_minimum_on_hours",
      "diesel_minimum_off_hours",
      "operation_mode",
      "winter_start_month",
      "winter_start_day",
      "winter_end_month",
      "winter_end_day",
      "green_power_ratio_lower",
      "optimization_time_limit_minutes",
      "preferred_solver",
      "initial_storage_soc_ratio",
      "storage_balance_mode",
      "initial_hydrogen_storage_ratio",
    ],
  },
  {
    key: "disturbance",
    title: "扰动后安全参数",
    toggleKey: "post_disturbance_power_balance_enabled",
    keys: [
      "post_disturbance_power_balance_enabled",
      "renewable_n_1_enabled",
      "renewable_disturbance_enabled",
      "load_disturbance_enabled",
      "load_up_disturbance_factor",
      "load_down_disturbance_factor",
      "renewable_down_disturbance_factor",
    ],
  },
  {
    key: "frequency",
    title: "频率安全参数",
    toggleKey: "frequency_security_constraint_enabled",
    keys: [
      "frequency_security_constraint_enabled",
      "nominal_frequency_hz",
      "frequency_nadir_lower_hz",
      "frequency_peak_upper_hz",
      "frequency_lower_security_margin_hz",
      "frequency_upper_security_margin_hz",
      "load_frequency_coefficient_d",
      "rocof_upper_hz_per_s",
      "steady_state_frequency_lower_hz",
      "steady_state_frequency_upper_hz",
      "frequency_governor_time_constant_s",
      "frequency_nadir_evaluation_duration_s",
      "nadir_linearization_samples_per_axis",
      "nadir_linearization_interval_ratio",
      "network_synchronization_coefficient_base",
      "network_synchronization_coefficient_slope",
      "network_synchronization_reference_load_kw",
      "storage_frequency_regulation_enabled",
    ],
  },
];

const visibleDevices = new Set(deviceSpecs.map(([key]) => key));

const monthRanges = [
  ["1月", 0, 744],
  ["2月", 744, 1416],
  ["3月", 1416, 2160],
  ["4月", 2160, 2880],
  ["5月", 2880, 3624],
  ["6月", 3624, 4344],
  ["7月", 4344, 5088],
  ["8月", 5088, 5832],
  ["9月", 5832, 6552],
  ["10月", 6552, 7296],
  ["11月", 7296, 8016],
  ["12月", 8016, 8760],
];

const deviceGroups = [
  ["windSolarDiesel", "风光柴", ["diesel_generators", "wind_turbines", "photovoltaics"]],
  ["electricStorage", "电储能", ["storage_pcs", "storage_battery_packs"]],
  ["hydrogenStorage", "氢储能", ["hydrogen_electrolyzers", "hydrogen_tanks", "fuel_cells"]],
];

let restoredPlanningPageState = {};

function restorePlanningPageState() {
  restoredPlanningPageState = window.PowerPlanPageState?.read?.(PLANNING_PAGE_STATE_KEY, {}) || {};
  const saved = restoredPlanningPageState;
  if (typeof saved.currentScheme === "string") state.currentScheme = saved.currentScheme;
  const savedMonth = window.PowerPlanPageState?.number?.(saved.month);
  if (Number.isFinite(savedMonth)) state.month = Math.min(Math.max(savedMonth, 0), monthRanges.length - 1);
  if (saved.timeChartRange && typeof saved.timeChartRange === "object") {
    state.timeChartRange = normalizeTimeChartRange(saved.timeChartRange);
  }
  const schemeRailManualHeight = window.PowerPlanPageState?.number?.(saved.schemeRailManualHeight);
  const timeChartManualHeight = window.PowerPlanPageState?.number?.(saved.timeChartManualHeight);
  const weatherPreviewManualHeight = window.PowerPlanPageState?.number?.(saved.weatherPreviewManualHeight);
  const timeSeriesImportManualChartHeight = window.PowerPlanPageState?.number?.(saved.timeSeriesImportManualChartHeight);
  if (Number.isFinite(schemeRailManualHeight)) state.schemeRailManualHeight = schemeRailManualHeight;
  if (Number.isFinite(timeChartManualHeight)) state.timeChartManualHeight = timeChartManualHeight;
  if (Number.isFinite(weatherPreviewManualHeight)) state.weatherPreviewManualHeight = weatherPreviewManualHeight;
  if (Number.isFinite(timeSeriesImportManualChartHeight)) state.timeSeriesImportManualChartHeight = timeSeriesImportManualChartHeight;
  if (typeof saved.curveGeneratorTarget === "string" && curveGeneratorSpecs[saved.curveGeneratorTarget]) {
    state.curveGeneratorTarget = saved.curveGeneratorTarget;
  }
  if (typeof saved.mapProvider === "string") state.mapProvider = saved.mapProvider;
  if (Array.isArray(saved.visibleDevices)) {
    const allowed = new Set(deviceSpecs.map(([key]) => key));
    visibleDevices.clear();
    saved.visibleDevices.forEach((key) => {
      if (allowed.has(key)) visibleDevices.add(key);
    });
    if (!visibleDevices.size) deviceSpecs.forEach(([key]) => visibleDevices.add(key));
  }
  if (Array.isArray(saved.weatherPreviewVisibleCurves)) {
    const allowed = new Set(weatherPreviewSeries.map(([key]) => key));
    state.weatherPreviewVisibleCurves = new Set(saved.weatherPreviewVisibleCurves.filter((key) => allowed.has(key)));
    if (!state.weatherPreviewVisibleCurves.size) state.weatherPreviewVisibleCurves = new Set(["wind_speed", "solar_irradiance", "temperature"]);
  }
  if (Array.isArray(saved.timeSeriesImportVisibleCurves)) {
    const allowed = new Set(timeSeriesImportSeries.map(([key]) => key));
    state.timeSeriesImportVisibleCurves = new Set(saved.timeSeriesImportVisibleCurves.filter((key) => allowed.has(key)));
    if (!state.timeSeriesImportVisibleCurves.size) state.timeSeriesImportVisibleCurves = new Set(["wind_speed", "solar_irradiance", "temperature", "load"]);
  }
  if (planningParameterGroups.some((group) => group.key === saved.activePlanningParameterGroup)) {
    activePlanningParameterGroup = saved.activePlanningParameterGroup;
  }
}

function planningPageStateSnapshot() {
  return {
    activeTab: document.querySelector(".tab.active")?.dataset.tab || restoredPlanningPageState.activeTab || "",
    summaryTab: document.querySelector("[data-summary-tab].active")?.dataset.summaryTab || restoredPlanningPageState.summaryTab || "",
    currentScheme: state.currentScheme || "",
    month: state.month,
    timeChartRange: normalizeTimeChartRange(state.timeChartRange),
    activePlanningParameterGroup,
    visibleDevices: Array.from(visibleDevices),
    loadGeneratorMode: document.getElementById("loadGeneratorMode")?.value || restoredPlanningPageState.loadGeneratorMode || "random",
    selectedCurve: document.querySelector('[data-curve][aria-pressed="true"]')?.dataset.curve || restoredPlanningPageState.selectedCurve || "",
    schemeRailManualHeight: state.schemeRailManualHeight,
    timeChartManualHeight: state.timeChartManualHeight,
    weatherPreviewManualHeight: state.weatherPreviewManualHeight,
    timeSeriesImportManualChartHeight: state.timeSeriesImportManualChartHeight,
    curveGeneratorTarget: state.curveGeneratorTarget,
    mapProvider: state.mapProvider,
    weatherPreviewVisibleCurves: Array.from(state.weatherPreviewVisibleCurves),
    timeSeriesImportVisibleCurves: Array.from(state.timeSeriesImportVisibleCurves),
  };
}

function rememberPlanningPageState(partial = {}) {
  const next = { ...planningPageStateSnapshot(), ...(partial || {}) };
  restoredPlanningPageState = next;
  window.PowerPlanPageState?.write?.(PLANNING_PAGE_STATE_KEY, next);
}

const labels = {
  name: "名称",
  solar_irradiance: "太阳辐照",
  temperature: "环境温度",
  capacity: "容量(kW)",
  power_capacity: "容量(kW)",
  storage_charge_efficiency: "充电效率(0.0-1.0)",
  storage_discharge_efficiency: "放电效率(0.0-1.0)",
  storage_equivalent_inertia_constant_h: "等效惯量常数H(s)",
  storage_equivalent_primary_frequency_coefficient_k: "等效一次调频系数K",
  storage_equivalent_damping_coefficient_d: "等效阻尼系数D",
  battery_capacity: "容量(kWh)",
  soc_upper: "SOC上限",
  soc_lower: "SOC下限",
  self_discharge_rate: "自损耗率(0-1%/天)",
  hydrogen_tank_capacity: "容量(Nm3)",
  quantity_lower: "数量下限(台)",
  quantity_upper: "数量上限(台)",
  design_life_years: "设计年限(年）",
  cost: "成本(万元/台)",
  power_upper: "功率上限(kW)",
  power_lower: "功率下限(kW)",
  fuel_rate: "油耗率(kg/kWh)",
  inertia_constant_h: "惯量常数H(s)",
  primary_frequency_coefficient_k: "一次调频系数K",
  damping_coefficient_d: "阻尼系数D",
  governor_time_constant_t: "调速时间常数T(s)",
  is_grid_forming: "是否构网",
  cut_in_wind_speed: "切入风速(m/s)",
  rated_wind_speed: "额定风速(m/s)",
  cut_out_wind_speed: "切出风速(m/s)",
  electric_to_hydrogen_efficiency: "电-氢效率(Nm3/kWh)",
  hydrogen_to_electric_efficiency: "氢-电效率(kWh/Nm3)",
};

const deviceFieldDefaults = {
  design_life_years: 20,
  inertia_constant_h: 3.5,
  primary_frequency_coefficient_k: 0.4,
  damping_coefficient_d: 0.01,
  governor_time_constant_t: 0.6,
  rated_wind_speed: 12,
  is_grid_forming: 0,
  storage_equivalent_inertia_constant_h: 2.5,
  storage_equivalent_primary_frequency_coefficient_k: 0.5,
  storage_equivalent_damping_coefficient_d: 0.05,
  storage_charge_efficiency: 0.95,
  storage_discharge_efficiency: 0.95,
  soc_upper: 0.9,
  soc_lower: 0.1,
  self_discharge_rate: 0.01,
};

const dieselGeneratorDefaultValues = {
  cost: 200,
  capacity: 300,
  power_upper: 250,
  power_lower: 80,
  fuel_rate: 0.28,
  inertia_constant_h: 3.5,
  primary_frequency_coefficient_k: 0.4,
  damping_coefficient_d: 0.01,
  governor_time_constant_t: 0.6,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const windTurbineDefaultValues = {
  cost: 400,
  capacity: 100,
  cut_in_wind_speed: 3,
  rated_wind_speed: 10,
  cut_out_wind_speed: 25,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const photovoltaicDefaultValues = {
  cost: 200,
  capacity: 100,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const storagePcsDefaultValues = {
  cost: 30,
  power_capacity: 100,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const storageBatteryPackDefaultValues = {
  cost: 100,
  battery_capacity: 200,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const hydrogenElectrolyzerDefaultValues = {
  cost: 400,
  power_capacity: 70,
  power_lower: 30,
  electric_to_hydrogen_efficiency: 0.2,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const hydrogenTankDefaultValues = {
  cost: 100,
  hydrogen_tank_capacity: 4000,
  quantity_lower: 1,
  quantity_upper: 5,
  design_life_years: 20,
};

const fuelCellDefaultValues = {
  cost: 200,
  power_capacity: 500,
  hydrogen_to_electric_efficiency: 1.5,
  quantity_upper: 5,
  design_life_years: 20,
};

const deviceFieldRules = {
  quantity_lower: { integer: true, nonNegative: true, attrs: ['min="0"', 'step="1"', 'inputmode="numeric"', 'pattern="[0-9]*"'], message: "数量上下限必须为非负整数" },
  quantity_upper: { integer: true, nonNegative: true, attrs: ['min="0"', 'step="1"', 'inputmode="numeric"', 'pattern="[0-9]*"'], message: "数量上下限必须为非负整数" },
  design_life_years: { integer: true, positive: true, attrs: ['min="1"', 'step="1"', 'inputmode="numeric"', 'pattern="[0-9]*"'], message: "设计年限(年）必须为正整数" },
  cost: { nonNegative: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "成本(万元/台)必须为非负浮点数" },
  capacity: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "容量(kW)必须为正实数" },
  power_capacity: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "容量(kW)必须为正实数" },
  storage_charge_efficiency: { min: 0, max: 1, positive: true, attrs: ['min="0"', 'max="1"', 'step="any"', 'inputmode="decimal"'], message: "充电效率(0.0-1.0)必须在0到1之间，且必须大于0" },
  storage_discharge_efficiency: { min: 0, max: 1, positive: true, attrs: ['min="0"', 'max="1"', 'step="any"', 'inputmode="decimal"'], message: "放电效率(0.0-1.0)必须在0到1之间，且必须大于0" },
  battery_capacity: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "容量(kWh)必须为正实数" },
  soc_upper: { min: 0, max: 1, attrs: ['min="0"', 'max="1"', 'step="any"', 'inputmode="decimal"'], message: "SOC上限(0.0-1.0)必须在0到1之间" },
  soc_lower: { min: 0, max: 1, attrs: ['min="0"', 'max="1"', 'step="any"', 'inputmode="decimal"'], message: "SOC下限(0.0-1.0)必须在0到1之间" },
  self_discharge_rate: { min: 0, max: 0.01, attrs: ['min="0"', 'max="0.01"', 'step="any"', 'inputmode="decimal"'], message: "自损耗率(0-1%/天)必须在0到0.01之间" },
  is_grid_forming: { integer: true, min: 0, max: 1, attrs: ['min="0"', 'max="1"', 'step="1"', 'inputmode="numeric"', 'pattern="[01]"'], message: "是否构网必须为0或1" },
  storage_equivalent_inertia_constant_h: { min: 0, max: 20, attrs: ['min="0"', 'max="20"', 'step="any"', 'inputmode="decimal"'], message: "等效惯量常数H(s)必须在0到20.0之间" },
  storage_equivalent_primary_frequency_coefficient_k: { min: 0, max: 10, attrs: ['min="0"', 'max="10"', 'step="any"', 'inputmode="decimal"'], message: "等效一次调频系数K必须在0到10.0之间" },
  storage_equivalent_damping_coefficient_d: { min: 0, max: 20, attrs: ['min="0"', 'max="20"', 'step="any"', 'inputmode="decimal"'], message: "等效阻尼系数D必须在0到20.0之间" },
  hydrogen_tank_capacity: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "容量(Nm3)必须为正实数" },
  electric_to_hydrogen_efficiency: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "电-氢效率(Nm3/kWh)必须为正实数" },
  hydrogen_to_electric_efficiency: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "氢-电效率(kWh/Nm3)必须为正实数" },
  fuel_rate: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "油耗率(kg/kWh)必须为正实数" },
  inertia_constant_h: { min: 0, max: 20, attrs: ['min="0"', 'max="20"', 'step="any"', 'inputmode="decimal"'], message: "惯量常数H(s)必须在0到20.0之间" },
  primary_frequency_coefficient_k: { min: 0, max: 10, attrs: ['min="0"', 'max="10"', 'step="any"', 'inputmode="decimal"'], message: "一次调频系数K必须在0到10.0之间" },
  damping_coefficient_d: { min: 0, max: 20, attrs: ['min="0"', 'max="20"', 'step="any"', 'inputmode="decimal"'], message: "阻尼系数D必须在0到20.0之间" },
  governor_time_constant_t: { min: 0.0001, max: 20, attrs: ['min="0.0001"', 'max="20"', 'step="any"', 'inputmode="decimal"'], message: "调速时间常数T(s)必须在0.0001到20.0之间" },
  power_lower: { nonNegative: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "功率下限(kW)必须为非负实数" },
  cut_in_wind_speed: { nonNegative: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "切入风速(m/s)必须为非负实数" },
  rated_wind_speed: { positive: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "额定风速(m/s)必须为正实数" },
  cut_out_wind_speed: { nonNegative: true, attrs: ['min="0"', 'step="any"', 'inputmode="decimal"'], message: "切出风速(m/s)必须为非负实数" },
};

document.addEventListener("DOMContentLoaded", () => {
  restorePlanningPageState();
  bindTabs();
  bindSummaryTabs();
  bindPlanningParameterInputs();
  bindTimeResizeHandle();
  bindTimeSeriesImportResizeHandle();
  bindWeatherPreviewResizeHandle();
  bindSchemeListResizeHandle();
  bindActions();
  bindDeviceContextMenu();
  bindAdaptiveLayout();
  syncAdaptiveLayout();
  loadLoadCurveTemplates().catch(showError);
  loadSchemes().catch(showError);
});

function bindTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      activatePlanningTab(button.dataset.tab || "time");
    });
  });
  activatePlanningTab(restoredPlanningPageState.activeTab || document.querySelector(".tab.active")?.dataset.tab || "time", { remember: false });
}

function activatePlanningTab(tabKey, options = {}) {
  const button = Array.from(document.querySelectorAll(".tab")).find((item) => item.dataset.tab === tabKey) || document.querySelector(".tab");
  if (!button) return;
  const target = button.dataset.tab || "";
  const panel = document.getElementById(`${target}Tab`);
  if (!panel) return;
  document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  panel.classList.add("active");
  syncAdaptiveLayout();
  ensureTimeSeriesForActiveTab();
  if (options.remember !== false) rememberPlanningPageState({ activeTab: target });
}

function bindSummaryTabs() {
  document.querySelectorAll("[data-summary-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activateSummaryTab(button.dataset.summaryTab || "devices");
    });
  });
  activateSummaryTab(restoredPlanningPageState.summaryTab || document.querySelector("[data-summary-tab].active")?.dataset.summaryTab || "devices", { remember: false });
}

function activateSummaryTab(target, options = {}) {
  const buttons = Array.from(document.querySelectorAll("[data-summary-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-summary-panel]"));
  const activeTarget = buttons.some((button) => button.dataset.summaryTab === target) ? target : buttons[0]?.dataset.summaryTab || "";
  buttons.forEach((item) => {
    const active = item.dataset.summaryTab === activeTarget;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  panels.forEach((panel) => {
    const active = panel.dataset.summaryPanel === activeTarget;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  syncAdaptiveLayout();
  if (options.remember !== false) rememberPlanningPageState({ summaryTab: activeTarget });
}

function bindActions() {
  document.getElementById("createScheme").addEventListener("click", createScheme);
  document.getElementById("copyScheme").addEventListener("click", copyScheme);
  document.getElementById("renameScheme").addEventListener("click", renameScheme);
  document.getElementById("shareScheme").addEventListener("click", shareScheme);
  document.getElementById("importScheme").addEventListener("click", importScheme);
  document.getElementById("exportScheme").addEventListener("click", exportScheme);
  document.getElementById("schemeImportFile").addEventListener("change", onSchemeImportFileChange);
  document.getElementById("saveScheme").addEventListener("click", saveScheme);
  document.getElementById("deleteScheme").addEventListener("click", deleteScheme);
  document.getElementById("importTimeSeriesFile").addEventListener("click", importTimeSeriesFile);
  document.getElementById("openTimeSeriesImportFile").addEventListener("click", openTimeSeriesImportFile);
  document.getElementById("timeSeriesImportFile").addEventListener("change", onTimeSeriesImportFileChange);
  document.getElementById("closeTimeSeriesImport").addEventListener("click", cancelTimeSeriesImport);
  document.getElementById("confirmTimeSeriesImport").addEventListener("click", confirmImportedTimeSeries);
  document.querySelectorAll("[data-import-curve]").forEach((button) => {
    button.addEventListener("click", () => toggleTimeSeriesImportCurve(button.dataset.importCurve));
  });
  const timeSeriesImportChart = document.getElementById("timeSeriesImportChart");
  timeSeriesImportChart.addEventListener("pointerdown", startTimeSeriesImportValueDrag);
  document.getElementById("loadGeneratorMode").addEventListener("change", onLoadGeneratorModeChange);
  document.getElementById("openCurveGenerator").addEventListener("click", () => openCurveGenerator());
  document.querySelectorAll("[data-curve-generator-target]").forEach((button) => {
    button.addEventListener("click", () => selectCurveGeneratorTarget(button.dataset.curveGeneratorTarget));
  });
  document.getElementById("closeLoadGenerator").addEventListener("click", cancelLoadGenerator);
  document.getElementById("generateLoadCurve").addEventListener("click", generateLoadCurve);
  document.getElementById("loadCurveImportFile").addEventListener("change", onLoadCurveImportFileChange);
  document.getElementById("saveLoadTemplate").addEventListener("click", saveLoadTemplate);
  const loadGeneratorPreview = document.getElementById("loadGeneratorPreview");
  loadGeneratorPreview.addEventListener("pointerdown", startLoadPreviewValueDrag);
  document.getElementById("confirmLoadGenerator").addEventListener("click", confirmGeneratedLoadCurve);
  document.getElementById("geocodePlace").addEventListener("click", geocodePlace);
  document.getElementById("fetchWeatherHistory").addEventListener("click", fetchWeatherHistory);
  document.getElementById("openCoordinatePicker").addEventListener("click", openCoordinatePicker);
  document.getElementById("closeMapPicker").addEventListener("click", closeMapPicker);
  document.getElementById("confirmMapPoint").addEventListener("click", confirmMapPoint);
  document.getElementById("weatherPlace").addEventListener("input", rememberWeatherInputsFromFields);
  document.getElementById("weatherYear").addEventListener("input", rememberWeatherInputsFromFields);
  document.getElementById("weatherLatitude").addEventListener("input", rememberWeatherInputsFromFields);
  document.getElementById("weatherLongitude").addEventListener("input", rememberWeatherInputsFromFields);
  document.getElementById("weatherLatitude").addEventListener("change", syncMapPointFromInputs);
  document.getElementById("weatherLongitude").addEventListener("change", syncMapPointFromInputs);
  document.querySelectorAll("[data-weather-preview-curve]").forEach((button) => {
    button.addEventListener("click", () => toggleWeatherPreviewCurve(button.dataset.weatherPreviewCurve));
  });
  document.querySelectorAll("[data-map-provider]").forEach((button) => {
    button.addEventListener("click", () => selectMapProvider(button.dataset.mapProvider));
  });
  document.querySelectorAll("[data-curve]").forEach((button) => {
    button.addEventListener("click", () => selectCurve(button.dataset.curve));
  });
  if (restoredPlanningPageState.selectedCurve) selectCurve(restoredPlanningPageState.selectedCurve, { remember: false });
  bindTimeChartRangeControls();
  const timeChart = document.getElementById("timeChart");
  timeChart.addEventListener("mousemove", onChartMouseMove);
  timeChart.addEventListener("mouseleave", hideChartCursor);
  timeChart.addEventListener("pointerdown", startChartValueDrag);
  const timeTable = document.getElementById("timeTable");
  timeTable?.addEventListener("input", (event) => {
    if (event.target?.matches?.("[data-time-index][data-key]")) onTimeInput(event);
  });
  timeTable?.addEventListener("pointerdown", onTimeCellPointerDown);
  timeTable?.addEventListener("focusout", onTimeInputFocusOut);
  timeTable?.addEventListener("keydown", onTimeInputKeydown);
  document.getElementById("timeSeriesImportPreview")?.addEventListener("input", (event) => {
    if (event.target?.matches?.("[data-time-series-import-index][data-time-series-import-key]")) onTimeSeriesImportInput(event);
  });
  document.addEventListener("mousemove", onHistogramMouseMove);
  document.addEventListener("mouseleave", hideHistogramTip);
  window.addEventListener("resize", scheduleAdaptiveLayout);
}

function bindDeviceContextMenu() {
  ensureDeviceContextMenu();
  document.addEventListener("click", (event) => {
    if (!event.target?.closest?.("#deviceRowContextMenu")) hideDeviceContextMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideDeviceContextMenu();
      exitDeviceCellEdit();
    }
  });
  window.addEventListener("scroll", hideDeviceContextMenu, true);
  window.addEventListener("resize", hideDeviceContextMenu);
}

function ensureDeviceContextMenu() {
  let menu = document.getElementById("deviceRowContextMenu");
  if (menu) return menu;
  menu = document.createElement("div");
  menu.id = "deviceRowContextMenu";
  menu.className = "device-context-menu";
  menu.hidden = true;
  menu.innerHTML = '<button type="button" data-device-context-action="delete">删除该行</button>';
  menu.addEventListener("click", onDeviceContextMenuClick);
  document.body.appendChild(menu);
  return menu;
}

function onDeviceRowContextMenu(event) {
  const row = event.currentTarget;
  if (!row?.dataset) return;
  event.preventDefault();
  selectDeviceRow(row);
  exitDeviceCellEdit();
  activeDeviceContextTarget = {
    device: row.dataset.device || "",
    row: Number(row.dataset.row),
  };
  showDeviceContextMenu(event.clientX, event.clientY);
}

function onDeviceCellPointerDown(event) {
  if (event.button !== 0) return;
  enterDeviceCellEdit(event.currentTarget);
}

function enterDeviceCellEdit(cell) {
  if (!cell || activeDeviceEditingCell === cell) return;
  exitDeviceCellEdit();
  const input = cell.querySelector(".device-input");
  if (!input) return;
  cell.classList.add("editing");
  input.readOnly = false;
  input.removeAttribute("readonly");
  input.tabIndex = 0;
  activeDeviceEditingCell = cell;
  window.requestAnimationFrame(() => {
    input.focus({ preventScroll: true });
    input.select?.();
  });
}

function exitDeviceCellEdit(cell = activeDeviceEditingCell) {
  if (!cell) return;
  const input = cell.querySelector(".device-input");
  cell.classList.remove("editing");
  if (input) {
    input.readOnly = true;
    input.setAttribute("readonly", "readonly");
    input.tabIndex = -1;
  }
  if (activeDeviceEditingCell === cell) activeDeviceEditingCell = null;
}

function onDeviceInputBlur(event) {
  exitDeviceCellEdit(event.target.closest(".device-cell"));
}

function onDeviceInputKeydown(event) {
  if (event.key !== "Enter" && event.key !== "Escape") return;
  event.preventDefault();
  event.target.blur();
}

function onTimeCellPointerDown(event) {
  if (event.button !== 0) return;
  const cell = event.target?.closest?.(".time-cell");
  if (!cell || !event.currentTarget.contains(cell)) return;
  enterTimeCellEdit(cell);
}

function enterTimeCellEdit(cell) {
  if (!cell || activeTimeEditingCell === cell) return;
  exitTimeCellEdit();
  const input = cell.querySelector(".time-cell-input");
  if (!input) return;
  cell.classList.add("editing");
  input.readOnly = false;
  input.removeAttribute("readonly");
  input.tabIndex = 0;
  activeTimeEditingCell = cell;
  window.requestAnimationFrame(() => {
    input.focus({ preventScroll: true });
    input.select?.();
  });
}

function exitTimeCellEdit(cell = activeTimeEditingCell) {
  if (!cell) return;
  const input = cell.querySelector(".time-cell-input");
  cell.classList.remove("editing");
  if (input) {
    input.readOnly = true;
    input.setAttribute("readonly", "readonly");
    input.tabIndex = -1;
  }
  if (activeTimeEditingCell === cell) activeTimeEditingCell = null;
}

function onTimeInputFocusOut(event) {
  if (!event.target?.matches?.(".time-cell-input")) return;
  finalizeTimeInput(event.target);
  exitTimeCellEdit(event.target.closest(".time-cell"));
}

function onTimeInputKeydown(event) {
  if (!event.target?.matches?.(".time-cell-input")) return;
  if (event.key !== "Enter" && event.key !== "Escape") return;
  event.preventDefault();
  event.target.blur();
}

function finalizeTimeInput(input) {
  if (!input || !state.payload) return;
  const row = state.payload.time_series?.[Number(input.dataset.timeIndex)];
  const key = input.dataset.key;
  if (!row || !key) return;
  const value = normalizeTimeSeriesCellValue(key, input.value);
  row[key] = value;
  const formatted = formatTimeSeriesCellValue(key, value);
  input.value = formatted;
  const display = input.closest(".time-cell")?.querySelector(".time-cell-display");
  if (display) display.textContent = formatted;
}

function selectDeviceRow(row) {
  document.querySelectorAll(".device-row.selected").forEach((item) => {
    item.classList.remove("selected");
    item.removeAttribute("aria-selected");
  });
  if (!row) return;
  row.classList.add("selected");
  row.setAttribute("aria-selected", "true");
}

function clearDeviceRowSelection() {
  selectDeviceRow(null);
}

function showDeviceContextMenu(clientX, clientY) {
  const menu = ensureDeviceContextMenu();
  menu.hidden = false;
  const rect = menu.getBoundingClientRect();
  const left = Math.min(clientX, Math.max(0, window.innerWidth - rect.width - 8));
  const top = Math.min(clientY, Math.max(0, window.innerHeight - rect.height - 8));
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
}

function hideDeviceContextMenu() {
  const menu = document.getElementById("deviceRowContextMenu");
  if (menu) menu.hidden = true;
  activeDeviceContextTarget = null;
  clearDeviceRowSelection();
}

function onDeviceContextMenuClick(event) {
  const action = event.target?.dataset?.deviceContextAction;
  if (action !== "delete" || !activeDeviceContextTarget) return;
  deleteDeviceRowByPosition(activeDeviceContextTarget.device, activeDeviceContextTarget.row);
}

function bindAdaptiveLayout() {
  if (!("ResizeObserver" in window)) return;
  const targets = [
    document.querySelector(".editor-panel"),
    document.getElementById("timeTab"),
    document.getElementById("devicesTab"),
    document.getElementById("planningTab"),
    document.getElementById("limitsTab"),
  ].filter(Boolean);
  state.layoutObserver = new ResizeObserver(() => scheduleAdaptiveLayout());
  targets.forEach((target) => state.layoutObserver.observe(target));
}

function scheduleAdaptiveLayout() {
  if (state.layoutFrame) return;
  state.layoutFrame = window.requestAnimationFrame(() => {
    state.layoutFrame = 0;
    syncAdaptiveLayout();
  });
}

function syncAdaptiveLayout() {
  applyPanelTableMaxHeight();
  applyAdaptiveSchemeRailLayout();
  applyAdaptiveTimeSeriesLayout();
  applyAdaptiveSummaryLayout();
  scheduleRenderChart();
  if (!document.getElementById("mapPickerModal")?.hidden) {
    renderWeatherPreviewChart(state.pendingWeatherRows || []);
  }
}

function scheduleRenderChart() {
  if (state.timeChartRenderFrame) return;
  state.timeChartRenderFrame = window.requestAnimationFrame(() => {
    state.timeChartRenderFrame = 0;
    renderChart();
  });
}

function applyPanelTableMaxHeight() {
  const editor = document.querySelector(".editor-panel");
  const header = document.querySelector(".editor-header");
  const available = editor ? editor.clientHeight - (header?.offsetHeight || 0) - 72 : window.innerHeight * 0.55;
  const tableMaxHeight = Math.min(680, Math.max(220, available));
  document.documentElement.style.setProperty("--panel-table-max-height", `${Math.round(tableMaxHeight)}px`);
}

function scheduleSchemeRailLayout() {
  if (state.schemeRailLayoutFrame) {
    window.cancelAnimationFrame(state.schemeRailLayoutFrame);
  }
  state.schemeRailLayoutFrame = window.requestAnimationFrame(() => {
    state.schemeRailLayoutFrame = 0;
    applyAdaptiveSchemeRailLayout();
  });
}

function applyAdaptiveSchemeRailLayout() {
  const layout = document.querySelector(".planning-scheme-rail-layout");
  const rail = layout?.closest(".scheme-rail");
  const workspace = rail?.closest(".workspace");
  const summaryRail = workspace?.querySelector(".summary-rail");
  const schemeList = layout?.querySelector(".scheme-list");
  const handle = document.getElementById("schemeListResizeHandle");
  if (!layout || !rail || !workspace || !schemeList) return;

  const workspaceStyle = getComputedStyle(workspace);
  const railStyle = getComputedStyle(rail);
  const layoutStyle = getComputedStyle(layout);
  const rowGap = parseFloat(workspaceStyle.rowGap || workspaceStyle.gap || 0) || 0;
  const workspaceContentHeight =
    workspace.clientHeight -
    (parseFloat(workspaceStyle.paddingTop) || 0) -
    (parseFloat(workspaceStyle.paddingBottom) || 0);
  const layoutGap = parseFloat(layoutStyle.rowGap || layoutStyle.gap || 0) || 0;
  const verticalChrome =
    (parseFloat(railStyle.paddingTop) || 0) +
    (parseFloat(railStyle.paddingBottom) || 0) +
    (parseFloat(railStyle.borderTopWidth) || 0) +
    (parseFloat(railStyle.borderBottomWidth) || 0);
  const children = Array.from(layout.children);
  const nonListHeight = children
    .filter((child) => child !== schemeList)
    .reduce((sum, child) => sum + child.getBoundingClientRect().height, 0);
  const gapHeight = Math.max(0, children.length - 1) * layoutGap;
  const requiredRailHeight = Math.ceil(verticalChrome + nonListHeight + schemeList.scrollHeight + gapHeight);
  const summaryMinimumHeight = Math.max(280, Math.min(340, summaryRail?.scrollHeight || 280));
  const handleHeight = handle?.getBoundingClientRect().height || 8;
  const maxRailHeight = Math.max(150, workspaceContentHeight - rowGap * 2 - handleHeight - summaryMinimumHeight);
  const preferredHeight = Number.isFinite(state.schemeRailManualHeight) ? state.schemeRailManualHeight : maxRailHeight;
  const targetHeight = Math.max(150, Math.min(preferredHeight, maxRailHeight));
  const capped = requiredRailHeight > targetHeight + 2;
  workspace.style.setProperty("--planning-scheme-rail-height", `${Math.round(targetHeight)}px`);
  rail.classList.toggle("scheme-list-capped", capped);
  updateSchemeListResizeHandle(targetHeight, maxRailHeight);
}

function bindSchemeListResizeHandle() {
  const handle = document.getElementById("schemeListResizeHandle");
  if (!handle) return;
  const applyHeight = (height) => {
    const bounds = schemeRailHeightBounds();
    state.schemeRailManualHeight = Math.min(Math.max(Number(height) || bounds.min, bounds.min), bounds.max);
    applyAdaptiveSchemeRailLayout();
    rememberPlanningPageState({ schemeRailManualHeight: state.schemeRailManualHeight });
  };
  const currentHeight = () => currentSchemeRailHeight();

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
      applyHeight(schemeRailHeightBounds().min);
    } else if (event.key === "End") {
      event.preventDefault();
      applyHeight(schemeRailHeightBounds().max);
    }
  });
}

function currentSchemeRailHeight() {
  const rail = document.querySelector(".planning-scheme-rail-layout")?.closest(".scheme-rail");
  return state.schemeRailManualHeight || rail?.getBoundingClientRect().height || 240;
}

function schemeRailHeightBounds() {
  const workspace = document.querySelector(".workspace");
  const summaryRail = workspace?.querySelector(".summary-rail");
  const handle = document.getElementById("schemeListResizeHandle");
  if (!workspace) return { min: 150, max: 600 };
  const workspaceStyle = getComputedStyle(workspace);
  const rowGap = parseFloat(workspaceStyle.rowGap || workspaceStyle.gap || 0) || 0;
  const workspaceContentHeight =
    workspace.clientHeight -
    (parseFloat(workspaceStyle.paddingTop) || 0) -
    (parseFloat(workspaceStyle.paddingBottom) || 0);
  const summaryMinimumHeight = Math.max(280, Math.min(340, summaryRail?.scrollHeight || 280));
  const handleHeight = handle?.getBoundingClientRect().height || 8;
  return {
    min: 150,
    max: Math.max(150, workspaceContentHeight - rowGap * 2 - handleHeight - summaryMinimumHeight),
  };
}

function updateSchemeListResizeHandle(height, maxHeight) {
  const handle = document.getElementById("schemeListResizeHandle");
  if (!handle) return;
  handle.setAttribute("aria-valuemin", "150");
  handle.setAttribute("aria-valuemax", String(Math.round(maxHeight || schemeRailHeightBounds().max)));
  handle.setAttribute("aria-valuenow", String(Math.round(height || currentSchemeRailHeight())));
}

function applyAdaptiveTimeSeriesLayout() {
  const tab = document.getElementById("timeTab");
  const chart = document.getElementById("timeChart");
  const chartCard = tab?.querySelector(".chart-card");
  const tableCard = tab?.querySelector(".table-card");
  const table = document.getElementById("timeTable");
  const toolbar = tab?.querySelector(".time-table-toolbar");
  const handle = document.getElementById("timeResizeHandle");
  if (!tab || !chart || !chartCard || !tableCard || !table || !tab.classList.contains("active")) return;

  const tabHeight = tab.clientHeight || Math.max(520, window.innerHeight - 180);
  const chartChrome = Math.max(0, chartCard.offsetHeight - chart.clientHeight);
  const tableChrome = Math.max(0, tableCard.offsetHeight - table.clientHeight) || (toolbar?.offsetHeight || 0) + 44;
  const handleHeight = (handle?.offsetHeight || 14) + 10;
  const available = Math.max(COLLAPSED_PANEL_SIZE, tabHeight - chartChrome - tableChrome - handleHeight - 32);
  const autoChartHeight = Math.min(340, Math.max(COLLAPSED_PANEL_SIZE, available * 0.4));
  const chartHeight = clampTimeChartHeight(state.timeChartManualHeight ?? autoChartHeight);
  const tableHeight = Math.max(COLLAPSED_PANEL_SIZE, available - chartHeight);

  document.documentElement.style.setProperty("--time-chart-height", `${Math.round(chartHeight)}px`);
  document.documentElement.style.setProperty("--time-table-height", `${Math.round(tableHeight)}px`);
  handle?.setAttribute("aria-valuenow", String(Math.round(chartHeight)));
}

function applyAdaptiveSummaryLayout() {
  const tab = document.getElementById("limitsTab");
  const summarySwitcher = tab?.querySelector(".summary-switcher");
  const summaryTabs = tab?.querySelector(".summary-tabs");
  const activePanel = tab?.querySelector(".summary-tab-panel.active");
  const heading = activePanel?.querySelector(".panel-heading");
  if (!tab || !summarySwitcher || !activePanel || !tab.classList.contains("active")) return;

  const switcherStyle = getComputedStyle(summarySwitcher);
  const tabsStyle = summaryTabs ? getComputedStyle(summaryTabs) : null;
  const headingStyle = heading ? getComputedStyle(heading) : null;
  const switcherPadding = parseFloat(switcherStyle.paddingTop || 0) + parseFloat(switcherStyle.paddingBottom || 0);
  const tabsHeight = (summaryTabs?.offsetHeight || 0) + parseFloat(tabsStyle?.marginBottom || 0);
  const headingHeight = (heading?.offsetHeight || 0) + parseFloat(headingStyle?.marginBottom || 0);
  const availablePanelHeight = (summarySwitcher.clientHeight || Math.max(260, tab.clientHeight - 32)) - switcherPadding - tabsHeight;
  const panelHeight = Math.max(180, availablePanelHeight);
  const contentHeight = Math.max(140, panelHeight - headingHeight);
  const tableHeight = Math.max(160, contentHeight);
  const histogramGridHeight = Math.max(240, contentHeight);
  const histogramSvgHeight = Math.max(120, (histogramGridHeight - 14) / 2 - 76);

  document.documentElement.style.setProperty("--summary-panel-height", `${Math.round(panelHeight)}px`);
  document.documentElement.style.setProperty("--summary-table-height", `${Math.round(tableHeight)}px`);
  document.documentElement.style.setProperty("--summary-histogram-grid-height", `${Math.round(histogramGridHeight)}px`);
  document.documentElement.style.setProperty("--summary-histogram-svg-height", `${Math.round(histogramSvgHeight)}px`);
}

function bindTimeResizeHandle() {
  const handle = document.getElementById("timeResizeHandle");
  const chart = document.getElementById("timeChart");
  if (!handle || !chart) return;

  const applyHeight = (height) => {
    const safeHeight = clampTimeChartHeight(height);
    state.timeChartManualHeight = safeHeight;
    document.documentElement.style.setProperty("--time-chart-height", `${Math.round(safeHeight)}px`);
    handle.setAttribute("aria-valuenow", String(Math.round(safeHeight)));
    syncAdaptiveLayout();
    rememberPlanningPageState({ timeChartManualHeight: state.timeChartManualHeight });
  };

  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = chart.getBoundingClientRect().height || 240;
    handle.classList.add("dragging");
    handle.setPointerCapture?.(event.pointerId);

    const onMove = (moveEvent) => {
      applyHeight(startHeight + moveEvent.clientY - startY);
    };
    const onDone = () => {
      handle.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onDone);
      window.removeEventListener("pointercancel", onDone);
      syncAdaptiveLayout();
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onDone);
    window.addEventListener("pointercancel", onDone);
  });

  handle.addEventListener("keydown", (event) => {
    const currentHeight = chart.getBoundingClientRect().height || 240;
    const keySteps = {
      ArrowUp: -12,
      ArrowDown: 12,
      PageUp: -48,
      PageDown: 48,
    };
    if (event.key in keySteps) {
      event.preventDefault();
      applyHeight(currentHeight + keySteps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyHeight(COLLAPSED_PANEL_SIZE);
    } else if (event.key === "End") {
      event.preventDefault();
      applyHeight(maxTimeChartHeight());
    }
  });

  handle.setAttribute("aria-valuenow", String(Math.round(chart.getBoundingClientRect().height || 240)));
}

function bindTimeSeriesImportResizeHandle() {
  const handle = document.getElementById("timeSeriesImportResizeHandle");
  const chart = document.getElementById("timeSeriesImportChart");
  if (!handle || !chart) return;

  const applyHeight = (height) => {
    const safeHeight = clampTimeSeriesImportChartHeight(height);
    state.timeSeriesImportManualChartHeight = safeHeight;
    document.documentElement.style.setProperty("--time-series-import-chart-height", `${Math.round(safeHeight)}px`);
    handle.setAttribute("aria-valuenow", String(Math.round(safeHeight)));
    renderTimeSeriesImportChart(state.pendingTimeSeriesImport || []);
    rememberPlanningPageState({ timeSeriesImportManualChartHeight: state.timeSeriesImportManualChartHeight });
  };

  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = chart.getBoundingClientRect().height || 240;
    handle.classList.add("dragging");
    handle.setPointerCapture?.(event.pointerId);

    const onMove = (moveEvent) => {
      applyHeight(startHeight + moveEvent.clientY - startY);
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
    const currentHeight = chart.getBoundingClientRect().height || 240;
    const keySteps = {
      ArrowUp: -12,
      ArrowDown: 12,
      PageUp: -48,
      PageDown: 48,
    };
    if (event.key in keySteps) {
      event.preventDefault();
      applyHeight(currentHeight + keySteps[event.key]);
    }
  });

  handle.setAttribute("aria-valuenow", String(Math.round(chart.getBoundingClientRect().height || 240)));
}

function bindWeatherPreviewResizeHandle() {
  const handle = document.getElementById("weatherPreviewResizeHandle");
  const panel = document.querySelector(".weather-preview-panel");
  if (!handle || !panel) return;

  const applyHeight = (height) => {
    const safeHeight = clampWeatherPreviewHeight(height);
    state.weatherPreviewManualHeight = safeHeight;
    document.documentElement.style.setProperty("--weather-preview-panel-height", `${Math.round(safeHeight)}px`);
    handle.setAttribute("aria-valuenow", String(Math.round(safeHeight)));
    renderWeatherPreviewChart(state.pendingWeatherRows || []);
    setTimeout(() => state.mapInstance?.resize?.(), 0);
    rememberPlanningPageState({ weatherPreviewManualHeight: state.weatherPreviewManualHeight });
  };

  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = panel.getBoundingClientRect().height || 220;
    handle.classList.add("dragging");
    handle.setPointerCapture?.(event.pointerId);

    const onMove = (moveEvent) => {
      applyHeight(startHeight - (moveEvent.clientY - startY));
    };
    const onDone = () => {
      handle.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onDone);
      window.removeEventListener("pointercancel", onDone);
      state.mapInstance?.resize?.();
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onDone);
    window.addEventListener("pointercancel", onDone);
  });

  handle.addEventListener("keydown", (event) => {
    const currentHeight = panel.getBoundingClientRect().height || 220;
    const keySteps = {
      ArrowUp: 12,
      ArrowDown: -12,
      PageUp: 48,
      PageDown: -48,
    };
    if (event.key in keySteps) {
      event.preventDefault();
      applyHeight(currentHeight + keySteps[event.key]);
    }
  });

  handle.setAttribute("aria-valuenow", String(Math.round(panel.getBoundingClientRect().height || 220)));
}

function clampTimeChartHeight(height) {
  return Math.min(Math.max(Number(height) || 240, COLLAPSED_PANEL_SIZE), maxTimeChartHeight());
}

function clampTimeSeriesImportChartHeight(height) {
  return Math.min(Math.max(Number(height) || 240, COLLAPSED_PANEL_SIZE), 430);
}

function clampWeatherPreviewHeight(height) {
  return Math.min(Math.max(Number(height) || 220, COLLAPSED_PANEL_SIZE), 460);
}

function maxTimeChartHeight() {
  const tab = document.getElementById("timeTab");
  const available = tab ? tab.clientHeight - 110 : 420;
  return Math.max(COLLAPSED_PANEL_SIZE, Math.min(900, available));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.message || data.error || "请求失败");
    error.code = data.error;
    error.status = response.status;
    throw error;
  }
  return data;
}

async function loadSchemes() {
  state.schemes = (await api("/api/planning/schemes")).schemes;
  if (state.currentScheme && !state.schemes.some((scheme) => scheme.name === state.currentScheme)) {
    state.currentScheme = "";
  }
  renderSchemes();
  if (state.currentScheme) {
    await selectScheme(state.currentScheme, { preserveMonth: true });
  } else if (state.schemes.length) {
    await selectScheme(state.schemes[0].name);
  } else {
    renderSummary();
    syncSchemeActionState();
  }
}

async function loadLoadCurveTemplates() {
  const result = await api("/api/planning/load-curve/templates");
  state.loadCurveTemplates = Array.isArray(result.templates) ? result.templates : [];
  renderLoadGeneratorModeOptions();
}

function renderLoadGeneratorModeOptions() {
  const select = document.getElementById("loadGeneratorMode");
  if (!select) return;
  const currentValue = (select.value && select.value !== "random" ? select.value : restoredPlanningPageState.loadGeneratorMode) || select.value || "random";
  const spec = curveGeneratorSpec();
  const fixedOptions = [
    ["random", "随机曲线"],
    ["file", "文件导入"],
  ];
  const templateOptions = spec.key === "load"
    ? state.loadCurveTemplates
      .map((template) => `<option value="template:${escapeHtml(template.name)}">${escapeHtml(template.name)}</option>`)
      .join("")
    : "";
  select.innerHTML = `${fixedOptions.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}${templateOptions}`;
  if (Array.from(select.options).some((option) => option.value === currentValue)) {
    select.value = currentValue;
  }
  rememberPlanningPageState({ loadGeneratorMode: select.value || "random" });
}

function renderSchemes() {
  const list = document.getElementById("schemeList");
  if (!state.schemes.length) {
    list.innerHTML = "<div class=\"validation-item\">暂无方案，请新建方案。</div>";
    syncSchemeActionState();
    scheduleSchemeRailLayout();
    return;
  }
  list.innerHTML = `<ul class="scheme-list-items" role="listbox">${state.schemes
    .map((scheme) => {
      const accessLabel = scheme.access_level === "shared" ? '<span class="scheme-access-label">共享</span>' : "";
      return `<li class="scheme-item ${scheme.name === state.currentScheme ? "active" : ""}" data-name="${escapeHtml(scheme.name)}" role="option" aria-selected="${scheme.name === state.currentScheme ? "true" : "false"}" tabindex="0"><span class="scheme-item-content"><span class="scheme-item-name">${escapeHtml(scheme.name)}</span>${accessLabel}</span></li>`;
    })
    .join("")}</ul>`;
  document.querySelectorAll(".scheme-item").forEach((item) => {
    bindSchemeListItem(item, () => selectSchemeWithSwitchFeedback(item.dataset.name).catch(showError));
  });
  syncSchemeActionState();
  scheduleSchemeRailLayout();
}

function bindSchemeListItem(item, onSelect) {
  item.addEventListener("click", onSelect);
  item.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  });
}

async function selectScheme(name, options = {}) {
  const previousScheme = state.currentScheme;
  state.currentScheme = name;
  state.timeSeriesLoading = null;
  state.timeSeriesDirty = false;
  state.payload = normalizePayload(await api(`/api/planning/schemes/${encodeURIComponent(name)}/overview`));
  state.isSwitchingScheme = false;
  if (options.preserveMonth !== true && previousScheme !== name) state.month = 0;
  renderAll();
  ensureTimeSeriesForActiveTab();
  if (options.remember !== false) rememberPlanningPageState({ currentScheme: state.currentScheme, month: state.month });
}

async function selectSchemeWithSwitchFeedback(name) {
  clearPlanningDisplayForSchemeSwitch(name);
  await selectScheme(name);
}

function clearPlanningDisplayForSchemeSwitch(name) {
  state.currentScheme = name || "";
  state.timeSeriesLoading = null;
  state.timeSeriesDirty = false;
  state.isSwitchingScheme = true;
  state.payload = renderPlanningSwitchingState(name);
  state.month = 0;
  state.chartMeta = null;
  hideChartCursor();
  renderAll();
}

function renderPlanningSwitchingState(name) {
  return {
    scheme: name || "",
    time_series: [],
    time_series_count: 0,
    timeSeriesLoaded: false,
    time_series_loaded: false,
    validation: [{ level: "info", message: `正在切换方案：${name || "未选择方案"}` }],
    planning_parameters: [defaultPlanningParameterRow()],
  };
}

async function createScheme() {
  const name = normalizeSchemeName(prompt("请输入新方案名称"));
  if (!name) return;
  if (schemeNameExists(name)) {
    alert("方案名称已存在，请使用其他名称");
    return;
  }
  const created = await api("/api/planning/schemes", { method: "POST", body: JSON.stringify({ name }) }).catch(showError);
  if (!created) return;
  state.currentScheme = created.scheme;
  await loadSchemes();
  await selectScheme(state.currentScheme);
}

async function copyScheme() {
  if (!state.currentScheme) return alert("请先选择方案");
  const target = normalizeSchemeName(prompt("请输入复制后的方案名称", `${state.currentScheme}_副本`));
  if (!target) return;
  const payload = { source: state.currentScheme, target };
  const existingTarget = schemeItemByName(target);
  if (existingTarget?.can_manage === false) {
    alert("同名方案来自他人分享，不能覆盖，请换一个名称");
    return;
  }
  if (existingTarget || schemeNameExists(target)) {
    const confirmed = confirm(`方案名称已存在：${target}\n是否覆盖？`);
    if (!confirmed) return;
    payload.overwrite = true;
  }
  const copied = await api("/api/planning/schemes/copy", {
    method: "POST",
    body: JSON.stringify(payload),
  }).catch(showError);
  if (!copied) return;
  state.currentScheme = copied.scheme;
  await loadSchemes();
  await selectScheme(state.currentScheme);
}

function importScheme() {
  const input = document.getElementById("schemeImportFile");
  input.value = "";
  input.click();
}

async function onSchemeImportFileChange(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const defaultName = normalizeSchemeName(file.name.replace(/\.zip$/i, "")) || "导入方案";
    const target = normalizeSchemeName(prompt("请输入导入后的方案名称", defaultName));
    if (!target) return;
    const existingTarget = schemeItemByName(target);
    if (existingTarget?.can_manage === false) {
      alert("同名方案来自他人分享，不能覆盖，请换一个名称");
      return;
    }
    const payload = { filename: file.name, name: target };
    if (existingTarget || schemeNameExists(target)) {
      const confirmed = confirm(`方案名称已存在：${target}\n是否覆盖？`);
      if (!confirmed) return;
      payload.overwrite = true;
    }
    payload.content_base64 = await arrayBufferToBase64(await file.arrayBuffer());
    const imported = await api("/api/planning/schemes/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.currentScheme = imported.scheme;
    await loadSchemes();
    await selectScheme(state.currentScheme);
    alert("方案导入成功");
  } catch (error) {
    alert(`方案导入失败：${error.message || String(error)}`);
  } finally {
    event.target.value = "";
  }
}

async function exportScheme() {
  if (!state.currentScheme) return alert("请先选择方案");
  try {
    const response = await fetch(`/api/planning/schemes/${encodeURIComponent(state.currentScheme)}/export`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.message || data.error || "导出失败");
    }
    const blob = await response.blob();
    downloadBlob(blob, filenameFromContentDisposition(response.headers.get("Content-Disposition")) || `${state.currentScheme}.zip`);
  } catch (error) {
    alert(`方案导出失败：${error.message || String(error)}`);
  }
}

async function renameScheme() {
  if (!state.currentScheme) return alert("请先选择方案");
  if (!currentSchemeCanManage()) return alert("共享方案只能查看或复制，不能修改名称");
  const target = normalizeSchemeName(prompt("请输入新的方案名称", state.currentScheme));
  if (!target || target === state.currentScheme) return;
  if (schemeNameExists(target, state.currentScheme)) {
    alert("方案名称已存在，请使用其他名称");
    return;
  }
  const renamed = await api("/api/planning/schemes/rename", {
    method: "POST",
    body: JSON.stringify({ source: state.currentScheme, target }),
  }).catch(showError);
  if (!renamed) return;
  state.currentScheme = renamed.scheme;
  await loadSchemes();
  await selectScheme(state.currentScheme);
}

async function shareScheme() {
  if (!state.currentScheme) return alert("请先选择方案");
  if (!currentSchemeCanManage()) return alert("共享方案只能查看或复制，不能继续分享");
  const detail = await api(`/api/planning/schemes/${encodeURIComponent(state.currentScheme)}/shares`).catch(showError);
  if (!detail) return;
  const sharedUsers = Array.isArray(detail.shared_with_usernames) ? detail.shared_with_usernames : [];
  const currentText = sharedUsers.length ? `当前已分享给：${sharedUsers.join("、")}` : "当前还没有分享给其他用户";
  const input = prompt(`${currentText}\n请输入要分享的用户名；如果要取消分享，请输入 -用户名。`, "");
  if (input === null) return;
  const text = String(input || "").trim();
  if (!text) return;
  const unshare = text.startsWith("-");
  const username = (unshare ? text.slice(1) : text).trim();
  if (!username) {
    alert("用户名不能为空");
    return;
  }
  const result = await api(unshare ? "/api/planning/schemes/unshare" : "/api/planning/schemes/share", {
    method: "POST",
    body: JSON.stringify({ scheme: state.currentScheme, username }),
  }).catch(showError);
  if (!result) return;
  await loadSchemes();
  alert(unshare ? `已取消分享给 ${username}` : `已分享给 ${username}`);
}

async function saveScheme() {
  if (!state.currentScheme || !state.payload) return alert("请先选择方案");
  if (!currentSchemeCanManage()) return alert("共享方案只能查看或复制，不能保存修改");
  try {
    syncPlanningParameterInputs();
    if (!isTimeSeriesLoaded()) {
      await ensureTimeSeriesLoaded();
      if (!isTimeSeriesLoaded()) {
        alert("保存参数失败：时序数据未加载，无法保存");
        return;
      }
    }
    syncPlanningParameterInputs();
    const warnings = collectSaveWarnings();
    const blockingWarnings = warnings.filter((item) => item.level === "error");
    const advisoryWarnings = warnings.filter((item) => item.level !== "error");
    if (blockingWarnings.length) {
      renderSummary();
      alert(`参数校验未通过：\n${blockingWarnings.map((item) => `- ${item.message}`).join("\n")}`);
      return;
    }
    if (advisoryWarnings.length && !confirm(`参数存在警告：\n${advisoryWarnings.map((item) => `- ${item.message}`).join("\n")}\n是否继续保存？`)) {
      renderSummary();
      return;
    }
    const savePayload = buildSchemeSavePayload();
    const previousTimeSeries = state.payload.time_series;
    const previousTimeSeriesCount = state.payload.time_series_count;
    const previousTimeSeriesLoaded = isTimeSeriesLoaded();
    const savedPayload = await api(`/api/planning/schemes/${encodeURIComponent(state.currentScheme)}`, {
      method: "PUT",
      body: JSON.stringify(savePayload),
    });
    state.payload = normalizePayload(savedPayload);
    if (!savePayload.time_series && previousTimeSeriesLoaded) {
      state.payload.time_series = previousTimeSeries;
      state.payload.time_series_count = previousTimeSeriesCount;
      setTimeSeriesLoaded(true);
    }
    state.timeSeriesDirty = false;
    if (!state.payload) {
      alert("保存参数失败：后台返回数据为空");
      return;
    }
    renderAll();
    alert("参数保存成功");
  } catch (error) {
    alert(`保存参数失败：${error.message || String(error)}`);
  }
}

function buildSchemeSavePayload() {
  const payload = { ...(state.payload || {}) };
  if (!state.timeSeriesDirty) {
    delete payload.time_series;
    payload.time_series_loaded = false;
    payload.timeSeriesLoaded = false;
    return payload;
  }
  if (!isTimeSeriesLoaded() || !Array.isArray(payload.time_series) || payload.time_series.length !== 8760) {
    throw new Error("时序数据未正确加载，无法保存曲线");
  }
  return payload;
}

async function deleteScheme() {
  if (!state.currentScheme) return alert("请先选择方案");
  if (!currentSchemeCanManage()) return alert("共享方案只能查看或复制，不能删除");
  const deletedIndex = state.schemes.findIndex((scheme) => scheme.name === state.currentScheme);
  if (!confirm(`确认删除方案“${state.currentScheme}”？删除后无法恢复。`)) return;
  const result = await api(`/api/planning/schemes/${encodeURIComponent(state.currentScheme)}`, { method: "DELETE" }).catch(showError);
  if (!result) return;
  await selectNextSchemeAfterDelete(Math.max(0, deletedIndex));
  alert("删除成功");
}

async function geocodePlace() {
  const placeInput = document.getElementById("weatherPlace");
  const place = placeInput.value.trim();
  if (!place) {
    setMapPickerHint("请输入地名");
    return;
  }
  setMapPickerHint("正在定位...");
  const result = await api("/api/planning/geocode", {
    method: "POST",
    body: JSON.stringify({ place }),
  }).catch((error) => {
    setMapPickerHint(error.message || String(error));
    return null;
  });
  if (!result) return;
  rememberWeatherCoordinate(result.latitude, result.longitude, coordinateInputNumber("weatherYear"), place);
  setMapPoint(result.latitude, result.longitude, "geocode", result);
}

async function reverseGeocodePoint(latitude, longitude) {
  const token = ++state.mapReverseGeocodeToken;
  setMapPickerHint(`地图坐标：${formatCoordinate(latitude)}, ${formatCoordinate(longitude)}；正在解析地点...`);
  const result = await api("/api/planning/reverse-geocode", {
    method: "POST",
    body: JSON.stringify({ latitude, longitude }),
  }).catch((error) => {
    if (token === state.mapReverseGeocodeToken) {
      setMapPickerHint(`地图坐标：${formatCoordinate(latitude)}, ${formatCoordinate(longitude)}；地点解析失败`);
      console.warn("地图选点地点解析失败", error);
    }
    return null;
  });
  if (!result || token !== state.mapReverseGeocodeToken) return;
  setWeatherPlaceFromReverseGeocode(result, latitude, longitude);
}

function setWeatherPlaceFromReverseGeocode(result, latitude, longitude) {
  const place = String(result?.place || result?.display_name || "").trim();
  if (!place) return false;
  const input = document.getElementById("weatherPlace");
  if (input) input.value = place;
  rememberWeatherCoordinate(latitude, longitude, coordinateInputNumber("weatherYear"), place);
  setMapPickerHint(`地图坐标：${formatCoordinate(latitude)}, ${formatCoordinate(longitude)}；地点已更新：${place}`);
  setWeatherImportStatus("地点已更新", "ok");
  return true;
}

async function fetchWeatherHistory() {
  if (!state.currentScheme || !state.payload) {
    setWeatherImportStatus("请先选择方案", "error");
    return;
  }
  const latitude = Number(document.getElementById("weatherLatitude").value);
  const longitude = Number(document.getElementById("weatherLongitude").value);
  const year = Number(document.getElementById("weatherYear").value);
  const localError = validateWeatherInputs(latitude, longitude, year);
  if (localError) {
    setWeatherImportStatus(localError, "error");
    return;
  }
  setWeatherImportStatus("正在获取历史气象...");
  const result = await api("/api/planning/weather-history", {
    method: "POST",
    body: JSON.stringify({ latitude, longitude, year }),
  }).catch((error) => {
    setWeatherImportStatus(error.message || String(error), "error");
    return null;
  });
  if (!result) return;
  const rows = Array.isArray(result.rows) ? result.rows : [];
  if (rows.length !== 8760) {
    setWeatherImportStatus(`历史气象数据小时数应为8760，当前为${rows.length}`, "error");
    return;
  }
  state.pendingWeatherRows = normalizeTimeSeriesRows(rows);
  state.pendingWeatherMeta = { year, latitude, longitude };
  rememberWeatherCoordinate(latitude, longitude, year, document.getElementById("weatherPlace")?.value || "");
  renderWeatherPreviewChart(rows);
  setWeatherImportStatus("气象数据已预览，请确认后更新主页面", "ok");
}

async function applyPendingWeatherHistory() {
  const rows = Array.isArray(state.pendingWeatherRows) ? state.pendingWeatherRows : [];
  const meta = state.pendingWeatherMeta || {};
  if (rows.length !== 8760) {
    const message = "请先获取气象数据并确认预览曲线";
    setWeatherImportStatus(message, "error");
    alert(message);
    return false;
  }
  if (!state.currentScheme || !state.payload) {
    setWeatherImportStatus("请先选择方案", "error");
    return false;
  }
  await ensureTimeSeriesLoaded().catch((error) => {
    setWeatherImportStatus(error.message || String(error), "error");
    return false;
  });
  if (!isTimeSeriesLoaded()) return false;
  const nextRows = (state.payload.time_series || []).map((row, index) => {
    const weather = rows[index];
    if (!weather) return row;
    return {
      ...row,
      datetime: weather.datetime || row.datetime,
      wind_speed: normalizeTimeSeriesCellValue("wind_speed", weather.wind_speed),
      solar_irradiance: normalizeTimeSeriesCellValue("solar_irradiance", weather.solar_irradiance),
      temperature: normalizeTimeSeriesCellValue("temperature", weather.temperature),
    };
  });
  if (nextRows.length !== 8760) {
    setWeatherImportStatus("当前时序表不是8760行，未更新数据", "error");
    return false;
  }
  state.payload.time_series = nextRows;
  state.payload.time_series_count = nextRows.length;
  markTimeSeriesDirty();
  renderChart();
  renderTimeTable();
  renderLimitSummary();
  renderSummary();
  clearPendingWeatherPreview(false);
  const year = Number(meta.year);
  const latitude = Number(meta.latitude);
  const longitude = Number(meta.longitude);
  setWeatherImportStatus(`${year}年气象已更新（纬度：${latitude.toFixed(3)}，经度：${longitude.toFixed(3)}）`, "ok");
  return true;
}

function clearPendingWeatherPreview(render = true) {
  state.pendingWeatherRows = null;
  state.pendingWeatherMeta = null;
  if (render) renderWeatherPreviewChart([]);
}

function importTimeSeriesFile() {
  openTimeSeriesImportModal();
}

function openTimeSeriesImportFile() {
  if (!state.currentScheme || !state.payload) {
    setTimeSeriesImportHint("请先选择方案", "error");
    return;
  }
  const input = document.getElementById("timeSeriesImportFile");
  input.value = "";
  input.click();
}

async function onTimeSeriesImportFileChange(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  setTimeSeriesImportHint(`正在解析导入文件：${file.name}`);
  setTimeSeriesImportSummary("正在解析...");
  try {
    const content_base64 = await arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/planning/time-series/import", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, content_base64 }),
    });
    const rows = normalizeTimeSeriesRows(result.time_series || []);
    state.pendingTimeSeriesImport = rows;
    renderTimeSeriesImportPreview(rows);
    const level = isTimeSeriesImportWarning(result) ? "warning" : "ok";
    setTimeSeriesImportHint(result.message || "导入文件解析成功，请确认后保存。", level);
    setTimeSeriesImportSummary(`已解析：${file.name}，共${rows.length}行`);
  } catch (error) {
    state.pendingTimeSeriesImport = null;
    renderTimeSeriesImportPreview([]);
    setTimeSeriesImportHint(`导入失败：${error.message || String(error)}`, "error");
    setTimeSeriesImportSummary("导入失败");
  } finally {
    event.target.value = "";
  }
}

async function confirmImportedTimeSeries() {
  const rows = state.pendingTimeSeriesImport;
  if (!Array.isArray(rows) || rows.length !== 8760) {
    setTimeSeriesImportHint("请先打开并成功解析8760行曲线文件", "error");
    return;
  }
  const previousRows = state.payload.time_series;
  const previousCount = state.payload.time_series_count;
  const previousLoaded = isTimeSeriesLoaded();
  const previousDirty = state.timeSeriesDirty;
  applyImportedTimeSeries(rows, "导入曲线已写入当前方案", false);
  setTimeSeriesImportHint("正在保存到后台...");
  try {
    state.payload = normalizePayload(await api(`/api/planning/schemes/${encodeURIComponent(state.currentScheme)}`, {
      method: "PUT",
      body: JSON.stringify(state.payload),
    }));
    state.timeSeriesDirty = false;
    state.pendingTimeSeriesImport = null;
    renderAll();
    closeTimeSeriesImport();
    setWeatherImportStatus("导入曲线已保存到后台", "ok");
  } catch (error) {
    if (previousRows === undefined) {
      delete state.payload.time_series;
    } else {
      state.payload.time_series = previousRows;
    }
    state.payload.time_series_count = previousCount;
    setTimeSeriesLoaded(previousLoaded);
    state.timeSeriesDirty = previousDirty;
    renderChart();
    renderMonthTabs();
    renderTimeTable();
    renderLimitSummary();
    renderSummary();
    setTimeSeriesImportHint(`保存失败：${error.message || String(error)}`, "error");
  }
}

function cancelTimeSeriesImport() {
  state.pendingTimeSeriesImport = null;
  renderTimeSeriesImportPreview([]);
  closeTimeSeriesImport();
  setWeatherImportStatus("导入曲线已取消");
}

function closeTimeSeriesImport() {
  hideModal(document.getElementById("timeSeriesImportModal"));
}

function applyImportedTimeSeries(rows, message, updateStatus = true) {
  if (!Array.isArray(rows) || rows.length !== 8760) {
    setWeatherImportStatus(`导入失败：时序数据行数应为8760，当前为${Array.isArray(rows) ? rows.length : 0}`, "error");
    return;
  }
  const nextRows = normalizeTimeSeriesRows(rows);
  state.payload.time_series = nextRows;
  state.payload.time_series_count = nextRows.length;
  state.month = 0;
  markTimeSeriesDirty();
  renderChart();
  renderMonthTabs();
  renderTimeTable();
  renderLimitSummary();
  renderSummary();
  if (updateStatus) setWeatherImportStatus(`${message}，请保存方案`, "ok");
}

function renderTimeSeriesImportPreview(rows) {
  const host = document.getElementById("timeSeriesImportPreview");
  if (!host) return;
  renderTimeSeriesImportChart(rows);
  if (!Array.isArray(rows) || rows.length === 0) {
    host.innerHTML = "<div class=\"empty-summary\">打开文件后，在这里预览8760点曲线。</div>";
    return;
  }
  const fields = [
    ["wind_speed", "风速"],
    ["solar_irradiance", "太阳辐射"],
    ["temperature", "环境温度"],
    ["load", "负荷"],
  ];
  const tableRows = rows
    .map((row, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(row.datetime || "")}</td>${fields
      .map(([key]) => `<td><input type="number" step="any" inputmode="decimal" data-time-series-import-index="${index}" data-time-series-import-key="${escapeHtml(key)}" value="${escapeHtml(formatTimeSeriesCellValue(key, row[key]))}"></td>`)
      .join("")}</tr>`)
    .join("");
  host.innerHTML = `<table><thead><tr><th>小时序号</th><th>时间</th>${fields.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${tableRows}</tbody></table>`;
}

function renderTimeSeriesImportChart(rows) {
  const svg = document.getElementById("timeSeriesImportChart");
  if (!svg) return;
  const width = svg.clientWidth || 900;
  const height = svg.clientHeight || state.timeSeriesImportManualChartHeight || 240;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  if (!Array.isArray(rows) || rows.length === 0) {
    svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" rx="12" fill="transparent"/><text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5a716e" font-size="15">打开文件后显示曲线预览</text>`;
    state.timeSeriesImportChartMeta = null;
    return;
  }
  const visibleSpecs = timeSeriesImportSeries.filter(([key]) => state.timeSeriesImportVisibleCurves.has(key));
  if (!visibleSpecs.length) {
    svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" rx="12" fill="transparent"/><text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5a716e" font-size="15">请选择至少一条曲线</text>`;
    state.timeSeriesImportChartMeta = null;
    return;
  }

  const padding = { left: 54, right: 24, top: 28, bottom: 34 };
  const plotWidth = Math.max(1, width - padding.left - padding.right);
  const plotHeight = Math.max(1, height - padding.top - padding.bottom);
  const x = (index) => padding.left + (index / Math.max(1, rows.length - 1)) * plotWidth;
  const scalesByKey = new Map();
  const yForSeries = (key) => {
    const values = rows.map((row) => Number(row[key])).filter(Number.isFinite);
    const rawMin = values.length ? Math.min(...values) : 0;
    const rawMax = values.length ? Math.max(...values) : 1;
    const min = rawMin === rawMax ? rawMin - 1 : rawMin;
    const max = rawMin === rawMax ? rawMax + 1 : rawMax;
    const span = max - min || 1;
    const scale = {
      min,
      max,
      rawMin,
      rawMax,
      span,
      y(value) {
        const number = Number(value);
        const safeValue = Number.isFinite(number) ? number : rawMin;
        return padding.top + plotHeight - ((safeValue - min) / span) * plotHeight;
      },
      valueFromY(localY) {
        const ratio = (padding.top + plotHeight - localY) / plotHeight;
        return min + ratio * span;
      },
    };
    scalesByKey.set(key, scale);
    return scale;
  };
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = padding.top + plotHeight * ratio;
      return `<line x1="${padding.left}" x2="${width - padding.right}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(137, 180, 186, 0.36)"/>`;
    })
    .join("");
  const xTicks = monthRanges
    .map(([label, start]) => {
      const tickX = x(start);
      return `<line x1="${tickX.toFixed(1)}" x2="${tickX.toFixed(1)}" y1="${padding.top + plotHeight}" y2="${padding.top + plotHeight + 5}" stroke="rgba(137, 180, 186, 0.5)"/><text x="${tickX.toFixed(1)}" y="${height - 10}" text-anchor="middle" fill="#dffbff" font-size="10">${label}</text>`;
    })
    .join("");
  const paths = visibleSpecs
    .map(([key, title, color, unit]) => {
      const scale = yForSeries(key);
      const d = rows.map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${scale.y(row[key]).toFixed(1)}`).join(" ");
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.7" vector-effect="non-scaling-stroke"><title>${escapeHtml(title)} ${escapeHtml(formatNumber(scale.rawMin))}-${escapeHtml(formatNumber(scale.rawMax))}${escapeHtml(unit)}</title></path>`;
    })
    .join("");
  const legend = visibleSpecs
    .map(([, title, color], index) => {
      const legendX = padding.left + index * 132;
      return `<g transform="translate(${legendX}, 16)"><line x1="0" x2="22" y1="0" y2="0" stroke="${color}" stroke-width="2"/><text x="28" y="4" fill="#dffbff" font-size="12">${escapeHtml(title)}</text></g>`;
    })
    .join("");
  svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" rx="12" fill="transparent"/><g>${grid}</g><line x1="${padding.left}" x2="${width - padding.right}" y1="${padding.top + plotHeight}" y2="${padding.top + plotHeight}" stroke="rgba(180, 226, 230, 0.7)"/><line x1="${padding.left}" x2="${padding.left}" y1="${padding.top}" y2="${padding.top + plotHeight}" stroke="rgba(180, 226, 230, 0.7)"/><g>${xTicks}</g>${paths}<g>${legend}</g>`;
  state.timeSeriesImportChartMeta = { rows, visibleSpecs, width, height, padding, plotWidth, plotHeight, scalesByKey };
}

function startTimeSeriesImportValueDrag(event) {
  if (!state.timeSeriesImportChartMeta || !Array.isArray(state.pendingTimeSeriesImport) || !state.pendingTimeSeriesImport.length) return;
  if (event.button !== undefined && event.button !== 0) return;
  if (event.isPrimary === false) return;
  const point = timeSeriesImportValueFromPointer(event);
  if (!point) return;
  const timeSeriesImportChart = document.getElementById("timeSeriesImportChart");
  if (!timeSeriesImportChart) return;

  event.preventDefault();
  state.timeSeriesImportDrag = { pointerId: event.pointerId, curveKey: point.curveKey, edited: false, lastPoint: null };
  timeSeriesImportChart.classList.add("editing");
  timeSeriesImportChart.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", onTimeSeriesImportValueDragMove);
  window.addEventListener("pointerup", endTimeSeriesImportValueDrag);
  window.addEventListener("pointercancel", endTimeSeriesImportValueDrag);
  applyTimeSeriesImportValueEdit(event);
}

function onTimeSeriesImportValueDragMove(event) {
  if (!state.timeSeriesImportDrag) return;
  if (event.pointerId !== undefined && state.timeSeriesImportDrag.pointerId !== undefined && event.pointerId !== state.timeSeriesImportDrag.pointerId) return;
  event.preventDefault();
  applyTimeSeriesImportValueEdit(event);
}

function endTimeSeriesImportValueDrag(event) {
  if (!state.timeSeriesImportDrag) return;
  if (event?.pointerId !== undefined && state.timeSeriesImportDrag.pointerId !== undefined && event.pointerId !== state.timeSeriesImportDrag.pointerId) return;
  const timeSeriesImportChart = document.getElementById("timeSeriesImportChart");
  if (timeSeriesImportChart) {
    timeSeriesImportChart.classList.remove("editing");
    timeSeriesImportChart.releasePointerCapture?.(state.timeSeriesImportDrag.pointerId);
  }
  state.timeSeriesImportDrag = null;
  window.removeEventListener("pointermove", onTimeSeriesImportValueDragMove);
  window.removeEventListener("pointerup", endTimeSeriesImportValueDrag);
  window.removeEventListener("pointercancel", endTimeSeriesImportValueDrag);
}

function applyTimeSeriesImportValueEdit(event) {
  if (!state.timeSeriesImportChartMeta || !Array.isArray(state.pendingTimeSeriesImport)) return false;
  const point = timeSeriesImportValueFromPointer(event, state.timeSeriesImportDrag?.curveKey);
  if (!point) return false;
  const { curveKey } = point;
  const points = interpolatedCurveEditPoints(state.timeSeriesImportDrag?.lastPoint, point);
  let edited = false;
  points.forEach(({ index: pointIndex, value }) => {
    if (!state.pendingTimeSeriesImport[pointIndex]) return;
    const editedValue = roundEditedCurveValue(clampEditedCurveValue(value, curveKey));
    state.pendingTimeSeriesImport[pointIndex][curveKey] = editedValue;
    updateTimeSeriesImportCell(pointIndex, curveKey, editedValue);
    edited = true;
  });
  if (!edited) return false;
  if (state.timeSeriesImportDrag) {
    state.timeSeriesImportDrag.edited = true;
    state.timeSeriesImportDrag.lastPoint = point;
  }
  scheduleTimeSeriesImportChartRender();
  setTimeSeriesImportHint("导入曲线已调整，请确认后保存。", "ok");
  return true;
}

function timeSeriesImportValueFromPointer(event, preferredCurveKey = "") {
  const meta = state.timeSeriesImportChartMeta;
  const svg = document.getElementById("timeSeriesImportChart");
  const rows = Array.isArray(state.pendingTimeSeriesImport) ? state.pendingTimeSeriesImport : meta?.rows;
  if (!meta || !svg || !Array.isArray(rows) || !rows.length) return null;
  const rect = svg.getBoundingClientRect();
  const localX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * meta.width;
  const localY = ((event.clientY - rect.top) / Math.max(1, rect.height)) * meta.height;
  const xRatio = Math.min(1, Math.max(0, (localX - meta.padding.left) / meta.plotWidth));
  const index = Math.round(xRatio * Math.max(1, rows.length - 1));
  const row = rows[index];
  if (!row) return null;

  let curveKey = preferredCurveKey;
  if (!curveKey || !meta.scalesByKey.has(curveKey)) {
    let nearest = null;
    meta.visibleSpecs.forEach(([key]) => {
      const scale = meta.scalesByKey.get(key);
      if (!scale) return;
      const distance = Math.abs(scale.y(row[key]) - localY);
      if (!nearest || distance < nearest.distance) {
        nearest = { key, distance };
      }
    });
    curveKey = nearest?.key || "";
  }
  const scale = curveKey ? meta.scalesByKey.get(curveKey) : null;
  if (!scale) return null;
  return { index, curveKey, value: scale.valueFromY(localY) };
}

function onTimeSeriesImportInput(event) {
  const input = event.target;
  const index = Number(input.dataset.timeSeriesImportIndex);
  const key = input.dataset.timeSeriesImportKey;
  if (!Array.isArray(state.pendingTimeSeriesImport) || !state.pendingTimeSeriesImport[index] || !key) return;
  const value = normalizeTimeSeriesCellValue(key, input.value);
  const nextValue = typeof value === "number" ? clampEditedCurveValue(value, key) : value;
  state.pendingTimeSeriesImport[index][key] = nextValue;
  const formatted = formatTimeSeriesCellValue(key, nextValue);
  if (input.value !== formatted) input.value = formatted;
  scheduleTimeSeriesImportChartRender();
  setTimeSeriesImportHint("导入曲线已调整，请确认后保存。", "ok");
}

function scheduleTimeSeriesImportChartRender() {
  if (state.timeSeriesImportChartFrame) return;
  state.timeSeriesImportChartFrame = window.requestAnimationFrame(() => {
    state.timeSeriesImportChartFrame = 0;
    renderTimeSeriesImportChart(state.pendingTimeSeriesImport || []);
  });
}

function updateTimeSeriesImportCell(index, key, value) {
  const input = document.querySelector(`[data-time-series-import-index="${index}"][data-time-series-import-key="${key}"]`);
  if (input) input.value = formatTimeSeriesCellValue(key, value);
}

function toggleTimeSeriesImportCurve(curveKey) {
  if (!curveKey) return;
  if (state.timeSeriesImportVisibleCurves.has(curveKey)) {
    state.timeSeriesImportVisibleCurves.delete(curveKey);
  } else {
    state.timeSeriesImportVisibleCurves.add(curveKey);
  }
  syncTimeSeriesImportCurveToggles();
  renderTimeSeriesImportChart(state.pendingTimeSeriesImport || []);
  rememberPlanningPageState({ timeSeriesImportVisibleCurves: Array.from(state.timeSeriesImportVisibleCurves) });
}

function syncTimeSeriesImportCurveToggles() {
  document.querySelectorAll("[data-import-curve]").forEach((button) => {
    const active = state.timeSeriesImportVisibleCurves.has(button.dataset.importCurve);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function filenameFromContentDisposition(header) {
  const text = String(header || "");
  const utf8Match = text.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (error) {
      return utf8Match[1];
    }
  }
  const asciiMatch = text.match(/filename="([^"]+)"/i);
  return asciiMatch ? asciiMatch[1] : "";
}

function downloadBlob(blob, filename) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename || "scheme.zip";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function showModalInBody(modal) {
  if (!modal) return;
  if (modal.parentElement !== document.body) {
    document.body.appendChild(modal);
  }
  modal.hidden = false;
  document.body.classList.add("modal-open");
}

function hideModal(modal) {
  if (!modal) return;
  modal.hidden = true;
  if (!document.querySelector(".map-picker-modal:not([hidden])")) {
    document.body.classList.remove("modal-open");
  }
}

function setTimeSeriesImportHint(message, level = "") {
  const hint = document.getElementById("timeSeriesImportHint");
  if (!hint) return;
  hint.textContent = message;
  hint.classList.toggle("error", level === "error");
  hint.classList.toggle("ok", level === "ok");
  hint.classList.toggle("warning", level === "warning");
}

function isTimeSeriesImportWarning(result) {
  const message = String(result?.message || "");
  return message.includes("自动补齐")
    || message.includes("已使用前8760行")
    || message.includes("缺失时点")
    || message.includes("无效数值")
    || message.includes("已修复");
}

function setTimeSeriesImportSummary(message) {
  const summary = document.getElementById("timeSeriesImportSummary");
  if (summary) summary.textContent = message;
}

function openTimeSeriesImportModal() {
  if (!state.currentScheme || !state.payload) {
    setWeatherImportStatus("请先选择方案", "error");
    return;
  }
  state.pendingTimeSeriesImport = null;
  state.timeSeriesImportChartMeta = null;
  state.timeSeriesImportDrag = null;
  syncTimeSeriesImportCurveToggles();
  const input = document.getElementById("timeSeriesImportFile");
  if (input) input.value = "";
  renderTimeSeriesImportPreview([]);
  setTimeSeriesImportHint("请选择包含风速、太阳辐射、环境温度、负荷的 Excel 或 CSV 文件。");
  setTimeSeriesImportSummary("未选择文件");
  showModalInBody(document.getElementById("timeSeriesImportModal"));
}

function openLoadGenerator() {
  openCurveGenerator("load");
}

function openWindGenerator() {
  openCurveGenerator("wind_speed");
}

function openSolarGenerator() {
  openCurveGenerator("solar_irradiance");
}

function openCurveGenerator(target = state.curveGeneratorTarget) {
  if (!state.currentScheme || !state.payload) {
    setWeatherImportStatus("请先选择方案", "error");
    return;
  }
  setCurveGeneratorTarget(target);
  configureCurveGeneratorModal();
  prefillLoadGeneratorValues();
  resetCurveGeneratorWorkingState();
  showModalInBody(document.getElementById("loadGeneratorModal"));
  refreshCurveGeneratorForTarget();
}

function selectCurveGeneratorTarget(target) {
  if (!curveGeneratorSpecs[target] || target === state.curveGeneratorTarget) {
    syncCurveGeneratorTabs();
    return;
  }
  setCurveGeneratorTarget(target);
  configureCurveGeneratorModal();
  prefillLoadGeneratorValues();
  resetCurveGeneratorWorkingState();
  refreshCurveGeneratorForTarget();
}

function setCurveGeneratorTarget(target) {
  state.curveGeneratorTarget = curveGeneratorSpecs[target] ? target : "wind_speed";
  rememberPlanningPageState({ curveGeneratorTarget: state.curveGeneratorTarget });
}

function resetCurveGeneratorWorkingState() {
  state.originalLoadCurve = currentCurveGeneratorRows();
  state.loadGeneratorSourceCurve = null;
  state.loadGeneratorSourceName = "";
  state.pendingLoadCurve = null;
}

function refreshCurveGeneratorForTarget() {
  const mode = document.getElementById("loadGeneratorMode").value;
  const spec = curveGeneratorSpec();
  setLoadGeneratorHint(`输入${spec.label}最大值、最小值、平均值，并选择生成模式。`);
  renderLoadGeneratorPreview(state.originalLoadCurve, []);
  loadLoadGeneratorModeSource(mode).catch((error) => {
    setLoadGeneratorHint(error.message || String(error), "error");
  });
}

function syncCurveGeneratorTabs() {
  document.querySelectorAll("[data-curve-generator-target]").forEach((button) => {
    const active = button.dataset.curveGeneratorTarget === state.curveGeneratorTarget;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function configureCurveGeneratorModal() {
  const spec = curveGeneratorSpec();
  const title = document.getElementById("loadGeneratorTitle");
  const confirm = document.getElementById("confirmLoadGenerator");
  const close = document.getElementById("closeLoadGenerator");
  const generate = document.getElementById("generateLoadCurve");
  const save = document.getElementById("saveLoadTemplate");
  const preview = document.getElementById("loadGeneratorPreview");
  if (title) title.textContent = "曲线生成";
  if (confirm) confirm.textContent = "确认";
  if (close) close.setAttribute("aria-label", "取消曲线生成");
  if (generate) generate.textContent = spec.generateLabel;
  if (save) save.hidden = !spec.saveTemplateVisible;
  if (preview) preview.setAttribute("aria-label", `生成${spec.label}曲线预览`);
  setLabelText("loadGeneratorMaxLabel", spec.maxLabel);
  setLabelText("loadGeneratorMinLabel", spec.minLabel);
  setLabelText("loadGeneratorAverageLabel", spec.averageLabel);
  syncCurveGeneratorTabs();
  renderLoadGeneratorModeOptions();
}

function setLabelText(id, text) {
  const element = document.getElementById(id);
  if (element) element.textContent = text;
}

function curveGeneratorSpec() {
  return curveGeneratorSpecs[state.curveGeneratorTarget] || curveGeneratorSpecs.load;
}

function closeLoadGenerator() {
  state.loadPreviewMeta = null;
  state.loadPreviewDrag = null;
  hideModal(document.getElementById("loadGeneratorModal"));
}

function cancelLoadGenerator() {
  const spec = curveGeneratorSpec();
  state.pendingLoadCurve = null;
  state.originalLoadCurve = null;
  state.loadGeneratorSourceCurve = null;
  state.loadGeneratorSourceName = "";
  closeLoadGenerator();
  setWeatherImportStatus(spec.cancelMessage);
}

function prefillLoadGeneratorValues() {
  const spec = curveGeneratorSpec();
  const rows = isTimeSeriesLoaded() ? state.payload.time_series || [] : [];
  const values = rows.map((row) => Number(row[spec.key])).filter(Number.isFinite);
  const max = values.length ? Math.max(...values) : 100;
  const min = values.length ? Math.min(...values) : 0;
  const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : Math.max(min, max / 2);
  document.getElementById("loadGeneratorMax").value = roundUiNumber(max);
  document.getElementById("loadGeneratorMin").value = roundUiNumber(min);
  document.getElementById("loadGeneratorAverage").value = roundUiNumber(average);
}

async function generateLoadCurve() {
  if (!state.currentScheme || !state.payload) {
    setLoadGeneratorHint("请先选择方案", "error");
    return;
  }
  const mode = document.getElementById("loadGeneratorMode").value;
  const { max, min, average } = currentLoadGeneratorTargets();
  const sourceRows = loadGeneratorPreviewSourceRows();
  const spec = curveGeneratorSpec();
  if (mode === "file" && (!Array.isArray(state.loadGeneratorSourceCurve) || state.loadGeneratorSourceCurve.length !== 8760)) {
    setLoadGeneratorHint(spec.selectedFileMessage, "error");
    importLoadCurveFile();
    return;
  }
  setLoadGeneratorHint(`正在${spec.generateLabel}...`);
  const requestBody = curveGeneratorRequestBody(mode, min, max, average);
  const result = await api(curveGeneratorGenerateEndpoint(), {
    method: "POST",
    body: JSON.stringify(requestBody),
  }).catch((error) => {
    setLoadGeneratorHint(error.message || String(error), "error");
    setWeatherImportStatus(`${spec.generationFailedPrefix}${error.message || String(error)}`, "error");
    return null;
  });
  if (!result) return;
  state.pendingLoadCurve = normalizeCurveRows(curveRowsFromResponse(result), spec.key);
  renderLoadGeneratorPreview(sourceRows, state.pendingLoadCurve);
  setLoadGeneratorHint(spec.generatedMessage, "ok");
}

function curveGeneratorGenerateEndpoint() {
  return curveGeneratorSpec().key === "load" ? "/api/planning/load-curve/generate" : "/api/planning/time-series-curve/generate";
}

function curveGeneratorImportEndpoint() {
  return curveGeneratorSpec().key === "load" ? "/api/planning/load-curve/import" : "/api/planning/time-series-curve/import";
}

function curveGeneratorRequestBody(mode, min, max, average) {
  const spec = curveGeneratorSpec();
  if (spec.key === "load") {
    return mode === "file"
      ? { mode, max, min, average, source_load_curve: state.loadGeneratorSourceCurve }
      : { mode, max, min, average };
  }
  return mode === "file"
    ? { curve: spec.key, mode, max, min, average, source_curve: state.loadGeneratorSourceCurve }
    : { curve: spec.key, mode, max, min, average };
}

function curveRowsFromResponse(result) {
  const spec = curveGeneratorSpec();
  if (spec.key === "load") return result.load_curve || result.curve_data || [];
  return result[`${spec.key}_curve`] || result.curve_data || [];
}

async function saveLoadTemplate() {
  if (curveGeneratorSpec().key !== "load") {
    setLoadGeneratorHint("当前曲线暂不支持保存模板", "error");
    return;
  }
  const rows = loadCurveRowsForTemplate();
  if (!Array.isArray(rows) || rows.length !== 8760) {
    setLoadGeneratorHint("请先生成或导入负荷曲线", "error");
    return;
  }
  const defaultName = currentLoadTemplateName();
  const name = prompt("请输入负荷模板名称", defaultName);
  if (name === null) return;
  const cleanName = normalizeSchemeName(name);
  if (!cleanName) {
    setLoadGeneratorHint("模板名称不能为空", "error");
    return;
  }
  await saveLoadTemplateRequest(cleanName, rows, false);
}

async function saveLoadTemplateRequest(name, rows, overwrite) {
  setLoadGeneratorHint("正在保存负荷模板...");
  try {
    const result = await api("/api/planning/load-curve/templates", {
      method: "POST",
      body: JSON.stringify({ name, load_curve: rows, overwrite }),
    });
    state.loadCurveTemplates = Array.isArray(result.templates) ? result.templates : state.loadCurveTemplates;
    renderLoadGeneratorModeOptions();
    document.getElementById("loadGeneratorMode").value = `template:${result.template.name}`;
    setLoadGeneratorHint(result.message || `负荷模板已保存：${result.template.name}`, "ok");
  } catch (error) {
    const message = error.message || String(error);
    if (!overwrite && (error.code === "exists" || message.includes("模板名称已存在"))) {
      if (confirm(`模板名称已存在：${name}。是否覆盖保存？`)) {
        await saveLoadTemplateRequest(name, rows, true);
      } else {
        setLoadGeneratorHint("负荷模板保存已取消");
      }
      return;
    }
    setLoadGeneratorHint(`负荷模板保存失败：${message}`, "error");
  }
}

function loadCurveRowsForTemplate() {
  if (Array.isArray(state.pendingLoadCurve) && state.pendingLoadCurve.length === 8760) {
    return state.pendingLoadCurve;
  }
  if (Array.isArray(state.loadGeneratorSourceCurve) && state.loadGeneratorSourceCurve.length === 8760) {
    return state.loadGeneratorSourceCurve;
  }
  return currentLoadCurveRows();
}

function currentLoadTemplateName() {
  const select = document.getElementById("loadGeneratorMode");
  const selected = select?.selectedOptions?.[0];
  const value = select?.value || "";
  if (value === "file" && state.loadGeneratorSourceName) return state.loadGeneratorSourceName.replace(/\.[^.]+$/, "");
  if (value.startsWith("template:")) return value.slice("template:".length);
  return selected?.textContent?.trim() || "负荷模板";
}

function onLoadGeneratorModeChange(event) {
  const mode = event.target.value;
  state.pendingLoadCurve = null;
  rememberPlanningPageState({ loadGeneratorMode: mode });
  loadLoadGeneratorModeSource(mode).catch((error) => {
    setLoadGeneratorHint(error.message || String(error), "error");
  });
}

async function loadLoadGeneratorModeSource(mode) {
  const spec = curveGeneratorSpec();
  if (mode === "file") {
    setLoadGeneratorHint(spec.selectedFileMessage);
    importLoadCurveFile();
    return;
  }
  const modeAtStart = mode;
  setLoadGeneratorHint(`正在载入原始${spec.label}曲线...`);
  let rows = [];
  let sourceName = "";
  if (spec.key === "load" && mode.startsWith("template:")) {
    const templateName = mode.slice("template:".length);
    const template = state.loadCurveTemplates.find((item) => item.name === templateName);
    rows = normalizeCurveRows(template?.load_curve || [], spec.key);
    sourceName = templateName;
  }
  if (!rows.length) {
    const result = await api(curveGeneratorGenerateEndpoint(), {
      method: "POST",
      body: JSON.stringify(curveGeneratorRequestBody(mode, 0, 1, spec.key === "solar_irradiance" ? 0.25 : 0.5)),
    });
    if (document.getElementById("loadGeneratorMode").value !== modeAtStart) return;
    rows = normalizeCurveRows(curveRowsFromResponse(result), spec.key);
    sourceName = result.mode || mode;
  }
  state.loadGeneratorSourceCurve = rows;
  state.loadGeneratorSourceName = sourceName;
  state.pendingLoadCurve = null;
  renderLoadGeneratorPreview(loadGeneratorPreviewSourceRows(), []);
  setLoadGeneratorHint(spec.sourceLoadedMessage, "ok");
}

function importLoadCurveFile() {
  if (!state.currentScheme || !state.payload) {
    setLoadGeneratorHint("请先选择方案", "error");
    return;
  }
  const loadCurveImportFile = document.getElementById("loadCurveImportFile");
  loadCurveImportFile.value = "";
  loadCurveImportFile.click();
}

async function onLoadCurveImportFileChange(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const spec = curveGeneratorSpec();
  setLoadGeneratorHint(`正在导入${spec.label}文件：${file.name}`);
  try {
    const content_base64 = await arrayBufferToBase64(await file.arrayBuffer());
    const body = spec.key === "load"
      ? { filename: file.name, content_base64, raw: true }
      : { curve: spec.key, filename: file.name, content_base64, raw: true };
    const result = await api(curveGeneratorImportEndpoint(), {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.loadGeneratorSourceCurve = normalizeCurveRows(curveRowsFromResponse(result), spec.key);
    state.loadGeneratorSourceName = file.name;
    state.pendingLoadCurve = null;
    renderLoadGeneratorPreview(loadGeneratorPreviewSourceRows(), []);
    const level = isTimeSeriesImportWarning(result) ? "warning" : "ok";
    setLoadGeneratorHint(result.message || spec.importedMessage, level);
  } catch (error) {
    state.loadGeneratorSourceCurve = null;
    state.loadGeneratorSourceName = "";
    state.pendingLoadCurve = null;
    renderLoadGeneratorPreview(state.originalLoadCurve, []);
    setLoadGeneratorHint(`${spec.importFailedPrefix}${error.message || String(error)}`, "error");
  } finally {
    event.target.value = "";
  }
}

function normalizeLoadCurveRows(rows) {
  return normalizeCurveRows(rows, "load");
}

function normalizeCurveRows(rows, key = curveGeneratorSpec().key) {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((row, index) => {
      const value = Number(typeof row === "object" && row !== null ? row[key] : row);
      return Number.isFinite(value) ? { hour_index: index + 1, [key]: normalizeTimeSeriesCellValue(key, value) } : null;
    })
    .filter(Boolean);
}

function loadGeneratorPreviewSourceRows() {
  if (Array.isArray(state.loadGeneratorSourceCurve) && state.loadGeneratorSourceCurve.length) {
    return state.loadGeneratorSourceCurve;
  }
  return state.originalLoadCurve || [];
}

function currentLoadGeneratorTargets() {
  return {
    max: Number(document.getElementById("loadGeneratorMax").value),
    min: Number(document.getElementById("loadGeneratorMin").value),
    average: Number(document.getElementById("loadGeneratorAverage").value),
  };
}

async function confirmGeneratedLoadCurve() {
  const spec = curveGeneratorSpec();
  if (!Array.isArray(state.pendingLoadCurve) || state.pendingLoadCurve.length !== 8760) {
    setLoadGeneratorHint(`请先${spec.generateLabel}`, "error");
    return;
  }
  await ensureTimeSeriesLoaded().catch((error) => {
    setLoadGeneratorHint(error.message || String(error), "error");
    return false;
  });
  if (!isTimeSeriesLoaded()) return;
  applyGeneratedLoadCurve(state.pendingLoadCurve);
  state.pendingLoadCurve = null;
  state.originalLoadCurve = null;
  state.loadGeneratorSourceCurve = null;
  state.loadGeneratorSourceName = "";
  closeLoadGenerator();
  setWeatherImportStatus(spec.confirmMessage, "ok");
}

function applyGeneratedLoadCurve(rows) {
  const spec = curveGeneratorSpec();
  if (!Array.isArray(rows) || rows.length !== 8760) {
    setLoadGeneratorHint(`${spec.invalidLengthMessage}，当前为${Array.isArray(rows) ? rows.length : 0}`, "error");
    return;
  }
  if (!Array.isArray(state.payload.time_series) || state.payload.time_series.length !== 8760) {
    setLoadGeneratorHint(spec.tableInvalidMessage, "error");
    return;
  }
  state.payload.time_series = state.payload.time_series.map((row, index) => {
    const curve = rows[index];
    return { ...row, [spec.key]: normalizeTimeSeriesCellValue(spec.key, curve[spec.key]) };
  });
  markTimeSeriesDirty();
  selectCurve(spec.key);
  renderChart();
  renderTimeTable();
  renderLimitSummary();
  renderSummary();
}

function setLoadGeneratorHint(message, level = "") {
  const hint = document.getElementById("loadGeneratorHint");
  if (!hint) return;
  hint.textContent = message;
  hint.classList.toggle("error", level === "error");
  hint.classList.toggle("ok", level === "ok");
  hint.classList.toggle("warning", level === "warning");
}

function currentLoadCurveRows() {
  return currentCurveGeneratorRows("load");
}

function currentCurveGeneratorRows(key = curveGeneratorSpec().key) {
  if (!isTimeSeriesLoaded()) return [];
  return (state.payload.time_series || []).map((row, index) => ({
    hour_index: index + 1,
    [key]: Number(row[key]),
  })).filter((row) => Number.isFinite(row[key]));
}

function renderLoadGeneratorPreview(originalRows, generatedRows) {
  const svg = document.getElementById("loadGeneratorPreview");
  if (!svg) return;
  const spec = curveGeneratorSpec();
  const width = svg.clientWidth || 720;
  const height = svg.clientHeight || 220;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";
  const original = Array.isArray(originalRows) ? originalRows.map((row) => Number(row[spec.key])).filter(Number.isFinite) : [];
  const generated = Array.isArray(generatedRows) ? generatedRows.map((row) => Number(row[spec.key])).filter(Number.isFinite) : [];
  const allValues = [...original, ...generated];
  if (!allValues.length) {
    svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" rx="10" fill="transparent"/><text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5a716e" font-size="15">${spec.emptyPreview}</text>`;
    state.loadPreviewMeta = null;
    return;
  }
  const padding = { left: 46, right: 18, top: 18, bottom: 30 };
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const span = max - min || 1;
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const editable = generated.length > 0;
  const linePoints = (values) => values.map((value, index) => {
    const x = padding.left + (index / Math.max(1, values.length - 1)) * plotWidth;
    const y = padding.top + (1 - (value - min) / span) * plotHeight;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const preview = generated.length ? generated : original;
  const avg = preview.reduce((sum, value) => sum + value, 0) / preview.length;
  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" rx="10" fill="rgba(255,255,255,0.03)"/>
    <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="rgba(160,190,190,0.5)"/>
    <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="rgba(160,190,190,0.5)"/>
    ${original.length ? `<polyline points="${linePoints(original)}" fill="none" stroke="#8aa2ad" stroke-width="1.4" stroke-dasharray="5 4"/>` : ""}
    ${generated.length ? `<polyline points="${linePoints(generated)}" fill="none" stroke="#21d5ff" stroke-width="1.8"/>` : ""}
    <g transform="translate(${width - 178}, ${padding.top + 2})">
      <line x1="0" y1="0" x2="28" y2="0" stroke="#8aa2ad" stroke-width="1.4" stroke-dasharray="5 4"/>
      <text x="36" y="4" fill="#dffbff" font-size="12">修改前</text>
      <line x1="92" y1="0" x2="120" y2="0" stroke="#21d5ff" stroke-width="1.8"/>
      <text x="128" y="4" fill="#dffbff" font-size="12">修改后</text>
    </g>
    <text x="${padding.left}" y="${padding.top - 5}" fill="#dffbff" font-size="12">最大 ${roundUiNumber(max)} ${spec.unit}</text>
    <text x="${padding.left}" y="${height - 8}" fill="#dffbff" font-size="12">最小 ${roundUiNumber(min)} / 平均 ${roundUiNumber(avg)} ${spec.unit}</text>
  `;
  state.loadPreviewMeta = { editable, width, height, padding, plotWidth, plotHeight, minValue: min, valueSpan: span, rows: generatedRows };
}

function startLoadPreviewValueDrag(event) {
  if (!state.loadPreviewMeta?.editable || !Array.isArray(state.pendingLoadCurve) || !state.pendingLoadCurve.length) return;
  if (event.button !== undefined && event.button !== 0) return;
  if (event.isPrimary === false) return;
  const loadGeneratorPreview = document.getElementById("loadGeneratorPreview");
  if (!loadGeneratorPreview) return;

  event.preventDefault();
  state.loadPreviewDrag = { pointerId: event.pointerId, edited: false, lastPoint: null };
  loadGeneratorPreview.classList.add("editing");
  loadGeneratorPreview.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", onLoadPreviewValueDragMove);
  window.addEventListener("pointerup", endLoadPreviewValueDrag);
  window.addEventListener("pointercancel", endLoadPreviewValueDrag);
  applyLoadPreviewValueEdit(event);
}

function onLoadPreviewValueDragMove(event) {
  if (!state.loadPreviewDrag) return;
  if (event.pointerId !== undefined && state.loadPreviewDrag.pointerId !== undefined && event.pointerId !== state.loadPreviewDrag.pointerId) return;
  event.preventDefault();
  applyLoadPreviewValueEdit(event);
}

function endLoadPreviewValueDrag(event) {
  if (!state.loadPreviewDrag) return;
  if (event?.pointerId !== undefined && state.loadPreviewDrag.pointerId !== undefined && event.pointerId !== state.loadPreviewDrag.pointerId) return;
  const loadGeneratorPreview = document.getElementById("loadGeneratorPreview");
  if (loadGeneratorPreview) {
    loadGeneratorPreview.classList.remove("editing");
    loadGeneratorPreview.releasePointerCapture?.(state.loadPreviewDrag.pointerId);
  }
  state.loadPreviewDrag = null;
  window.removeEventListener("pointermove", onLoadPreviewValueDragMove);
  window.removeEventListener("pointerup", endLoadPreviewValueDrag);
  window.removeEventListener("pointercancel", endLoadPreviewValueDrag);
}

function applyLoadPreviewValueEdit(event) {
  if (!state.loadPreviewMeta?.editable || !Array.isArray(state.pendingLoadCurve)) return false;
  const point = loadPreviewValueFromPointer(event);
  if (!point) return false;
  const points = interpolatedCurveEditPoints(state.loadPreviewDrag?.lastPoint, point);
  const spec = curveGeneratorSpec();
  let edited = false;
  points.forEach(({ index: pointIndex, value }) => {
    if (!state.pendingLoadCurve[pointIndex]) return;
    state.pendingLoadCurve[pointIndex][spec.key] = roundEditedCurveValue(Math.max(0, value));
    edited = true;
  });
  if (!edited) return false;
  if (state.loadPreviewDrag) {
    state.loadPreviewDrag.edited = true;
    state.loadPreviewDrag.lastPoint = point;
  }
  renderLoadGeneratorPreview(state.originalLoadCurve, state.pendingLoadCurve);
  setLoadGeneratorHint(spec.adjustedMessage, "ok");
  return true;
}

function loadPreviewValueFromPointer(event) {
  const meta = state.loadPreviewMeta;
  const svg = document.getElementById("loadGeneratorPreview");
  if (!meta || !svg) return null;
  const rect = svg.getBoundingClientRect();
  const localX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * meta.width;
  const localY = ((event.clientY - rect.top) / Math.max(1, rect.height)) * meta.height;
  const xRatio = Math.min(1, Math.max(0, (localX - meta.padding.left) / meta.plotWidth));
  const index = Math.round(xRatio * Math.max(1, state.pendingLoadCurve.length - 1));
  const yRatio = (meta.padding.top + meta.plotHeight - localY) / meta.plotHeight;
  const value = meta.minValue + yRatio * meta.valueSpan;
  return { index, value };
}

function roundUiNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.round(number * 1000) / 1000) : "";
}

async function openCoordinatePicker() {
  const modal = document.getElementById("mapPickerModal");
  restoreWeatherCoordinate();
  showModalInBody(modal);
  setMapPickerHint("根据地名查找坐标，或点击地图选点。");
  renderWeatherPreviewLegend();
  renderWeatherPreviewChart(state.pendingWeatherRows || []);
  const config = await loadMapConfig();
  if (!config) return;
  state.mapProvider = chooseAvailableMapProvider(config, state.mapProvider);
  renderMapProviderTabs(config);
  if (!mapProviderKey(config, state.mapProvider)) {
    setMapPickerHint(`可按地名查找；未配置${mapProviderLabel(state.mapProvider)} Key。`);
    return;
  }
  await loadSelectedMapProvider();
}

async function selectMapProvider(provider) {
  if (!provider || provider === state.mapProvider) return;
  state.mapProvider = provider;
  rememberPlanningPageState({ mapProvider: state.mapProvider });
  const config = await loadMapConfig();
  renderMapProviderTabs(config);
  await loadSelectedMapProvider();
}

async function loadSelectedMapProvider() {
  const config = await loadMapConfig();
  if (!config) return;
  const providers = [state.mapProvider, "amap", "osm"].filter((provider, index, array) => provider && array.indexOf(provider) === index);
  const errors = [];
  for (const provider of providers) {
    const key = mapProviderKey(config, provider);
    resetMapCanvas();
    if (provider !== "osm" && !key) {
      errors.push(`${mapProviderLabel(provider)}未配置 Key`);
      continue;
    }
    try {
      if (provider === "osm") {
        initOsmTilePicker();
      } else {
        initAmapTilePicker();
      }
      state.mapProvider = provider;
      rememberPlanningPageState({ mapProvider: state.mapProvider });
      renderMapProviderTabs(config);
      setMapPickerHint(`当前接口：${mapProviderLabel(provider)}。根据地名查找坐标，或点击地图选点。`);
      return;
    } catch (error) {
      errors.push(`${mapProviderLabel(provider)}：${error.message || error}`);
    }
  }
  setMapPickerHint(`地图加载失败：${errors.join("；") || "未能加载任何地图服务"}`);
}

function closeMapPicker({ clearPreview = true } = {}) {
  if (clearPreview) clearPendingWeatherPreview();
  hideModal(document.getElementById("mapPickerModal"));
}

async function loadMapConfig() {
  if (state.mapConfig) return state.mapConfig;
  state.mapConfig = await api("/api/planning/map-config").catch((error) => {
    document.getElementById("mapPickerHint").textContent = error.message || String(error);
    return null;
  });
  return state.mapConfig;
}

function chooseAvailableMapProvider(config, preferred) {
  if (mapProviderKey(config, preferred)) return preferred;
  const provider = (config?.providers || []).find((item) => item.enabled);
  return provider?.key || preferred || "amap";
}

function mapProviderKey(config, provider) {
  if (!config) return "";
  if (provider === "osm") return "openstreetmap";
  return config.amap_key || "";
}

function mapProviderLabel(provider) {
  if (provider === "osm") return "OpenStreetMap";
  return "高德地图";
}

function renderMapProviderTabs(config) {
  document.querySelectorAll("[data-map-provider]").forEach((button) => {
    const provider = button.dataset.mapProvider;
    const active = provider === state.mapProvider;
    const enabled = provider === "osm" || Boolean(mapProviderKey(config, provider));
    button.classList.toggle("active", active);
    button.classList.toggle("disabled", !enabled);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.title = enabled ? `${mapProviderLabel(provider)}接口` : `${mapProviderLabel(provider)}未配置 Key`;
  });
}

function resetMapCanvas() {
  if (typeof state.mapCleanup === "function") {
    state.mapCleanup();
  }
  state.mapInstance = null;
  state.mapMarker = null;
  state.mapCleanup = null;
  const canvas = document.getElementById("mapPickerCanvas");
  if (canvas) {
    canvas.classList.remove("amap-tile-map", "dragging");
    canvas.innerHTML = "";
  }
}

function loadAmapScript(key) {
  if (window.AMap) return Promise.resolve();
  if (window.__powerPlanAmapLoading) return window.__powerPlanAmapLoading;
  window.__powerPlanAmapLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("高德地图脚本加载失败"));
    document.head.appendChild(script);
  });
  return window.__powerPlanAmapLoading;
}

function initAmapPicker() {
  initAmapTilePicker();
}

function initAmapTilePicker() {
  const canvas = document.getElementById("mapPickerCanvas");
  if (!canvas) return;
  const center = currentMapCenterArray();
  state.mapInstance = createTileMap(canvas, center, AMAP_DEFAULT_ZOOM, "amap");
  state.mapMarker = state.mapInstance.marker;
  state.mapCleanup = state.mapInstance.destroy;
  setTimeout(() => state.mapInstance.resize(), 80);
}

function initOsmTilePicker() {
  const canvas = document.getElementById("mapPickerCanvas");
  if (!canvas) return;
  const center = currentMapCenterArray();
  state.mapInstance = createTileMap(canvas, center, AMAP_DEFAULT_ZOOM, "osm");
  state.mapMarker = state.mapInstance.marker;
  state.mapCleanup = state.mapInstance.destroy;
  setTimeout(() => state.mapInstance.resize(), 80);
}

function currentMapCenterArray() {
  const latitude = coordinateInputNumber("weatherLatitude");
  const longitude = coordinateInputNumber("weatherLongitude");
  if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
    return [clampLongitude(longitude), clampLatitude(latitude)];
  }
  return [116.39723, 39.9075];
}

function coordinateInputNumber(id) {
  const value = document.getElementById(id)?.value;
  if (value === undefined || String(value).trim() === "") return NaN;
  const number = Number(value);
  return Number.isFinite(number) ? number : NaN;
}

function createAmapTileMap(canvas, center, initialZoom) {
  return createTileMap(canvas, center, initialZoom, "amap");
}

function createTileMap(canvas, center, initialZoom, provider = "amap") {
  canvas.classList.add("amap-tile-map");
  const attribution = provider === "osm" ? `${GLOBAL_TILE_SOURCE_LABEL} / ${OSM_TILE_PROVIDERS[0].name}` : `高德地图 / ${GLOBAL_TILE_SOURCE_LABEL}`;
  canvas.innerHTML = `
    <div class="amap-tile-layer" aria-hidden="true"></div>
    <div class="amap-coordinate-marker" aria-hidden="true"><span></span></div>
    <div class="amap-map-controls" aria-label="${mapProviderLabel(provider)}缩放控件">
      <button type="button" data-amap-zoom="in" aria-label="放大地图">+</button>
      <button type="button" data-amap-zoom="out" aria-label="缩小地图">-</button>
    </div>
    <div class="amap-map-attribution">${attribution}</div>
  `;
  const tileLayer = canvas.querySelector(".amap-tile-layer");
  const markerElement = canvas.querySelector(".amap-coordinate-marker");
  let zoom = clampZoom(initialZoom);
  let centerPoint = normalizeLngLatArray(center);
  let markerPoint = [...centerPoint];
  let dragState = null;

  const render = () => {
    renderAmapTileLayer(canvas, tileLayer, centerPoint, zoom, provider);
    renderAmapMarker(canvas, markerElement, centerPoint, markerPoint, zoom);
  };

  const setCenter = (position) => {
    centerPoint = normalizeLngLatArray(position);
    render();
  };

  const marker = {
    setPosition(position) {
      markerPoint = normalizeLngLatArray(position);
      render();
    },
  };

  const setZoom = (nextZoom) => {
    zoom = clampZoom(nextZoom);
    render();
  };

  const pointFromEvent = (event) => {
    const rect = canvas.getBoundingClientRect();
    const centerPixel = lngLatToWebMercatorPixel(centerPoint[0], centerPoint[1], zoom);
    const pixel = {
      x: centerPixel.x + event.clientX - rect.left - rect.width / 2,
      y: centerPixel.y + event.clientY - rect.top - rect.height / 2,
    };
    return webMercatorPixelToLngLat(pixel.x, pixel.y, zoom);
  };

  const onWheel = (event) => {
    event.preventDefault();
    setZoom(zoom + (event.deltaY < 0 ? 1 : -1));
  };

  const onPointerDown = (event) => {
    if (event.target.closest?.(".amap-map-controls")) return;
    const centerPixel = lngLatToWebMercatorPixel(centerPoint[0], centerPoint[1], zoom);
    dragState = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      centerPixel,
      moved: false,
    };
    canvas.setPointerCapture?.(event.pointerId);
    canvas.classList.add("dragging");
  };

  const onPointerMove = (event) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - dragState.startX;
    const deltaY = event.clientY - dragState.startY;
    if (Math.abs(deltaX) + Math.abs(deltaY) > 4) {
      dragState.moved = true;
    }
    const nextCenter = webMercatorPixelToLngLat(
      dragState.centerPixel.x - deltaX,
      dragState.centerPixel.y - deltaY,
      zoom,
    );
    centerPoint = nextCenter;
    render();
  };

  const onPointerEnd = (event) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    const shouldSelect = !dragState.moved;
    dragState = null;
    canvas.releasePointerCapture?.(event.pointerId);
    canvas.classList.remove("dragging");
    if (shouldSelect) {
      const point = pointFromEvent(event);
      markerPoint = point;
      setMapPoint(point[1], point[0]);
      reverseGeocodePoint(point[1], point[0]);
    }
  };

  const onControlClick = (event) => {
    const button = event.target.closest?.("[data-amap-zoom]");
    if (!button) return;
    setZoom(zoom + (button.dataset.amapZoom === "in" ? 1 : -1));
  };

  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerEnd);
  canvas.addEventListener("pointercancel", onPointerEnd);
  canvas.addEventListener("click", onControlClick);
  render();

  return {
    marker,
    setCenter,
    setZoom,
    getZoom: () => zoom,
    resize: render,
    destroy() {
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerEnd);
      canvas.removeEventListener("pointercancel", onPointerEnd);
      canvas.removeEventListener("click", onControlClick);
    },
  };
}

function renderAmapTileLayer(canvas, tileLayer, center, zoom, provider = "amap") {
  if (!canvas || !tileLayer) return;
  const width = canvas.clientWidth || 800;
  const height = canvas.clientHeight || 420;
  const centerPixel = lngLatToWebMercatorPixel(center[0], center[1], zoom);
  const startX = centerPixel.x - width / 2;
  const startY = centerPixel.y - height / 2;
  const endX = startX + width;
  const endY = startY + height;
  const minTileX = Math.floor(startX / AMAP_TILE_SIZE) - 1;
  const maxTileX = Math.floor(endX / AMAP_TILE_SIZE) + 1;
  const minTileY = Math.floor(startY / AMAP_TILE_SIZE) - 1;
  const maxTileY = Math.floor(endY / AMAP_TILE_SIZE) + 1;
  const tileCount = 2 ** zoom;
  const tiles = [];
  for (let tileY = minTileY; tileY <= maxTileY; tileY += 1) {
    if (tileY < 0 || tileY >= tileCount) continue;
    for (let tileX = minTileX; tileX <= maxTileX; tileX += 1) {
      const wrappedTileX = modulo(tileX, tileCount);
      const left = tileX * AMAP_TILE_SIZE - startX;
      const top = tileY * AMAP_TILE_SIZE - startY;
      const server = (Math.abs(wrappedTileX + tileY) % 4) + 1;
      const tileSource = provider === "osm"
        ? osmTileUrl(wrappedTileX, tileY, zoom, 0)
        : amapTileUrl(server, wrappedTileX, tileY, zoom);
      const osmFallbacks = osmTileFallbackUrls(wrappedTileX, tileY, zoom);
      const fallbackAttribute = osmFallbacks.length
        ? ` data-fallback-index="${provider === "osm" ? 1 : 0}" data-fallback-srcs="${encodeURIComponent(JSON.stringify(osmFallbacks))}"`
        : "";
      tiles.push(
        `<img class="amap-map-tile" alt="" draggable="false" src="${tileSource}"${fallbackAttribute} style="left:${left.toFixed(2)}px;top:${top.toFixed(2)}px;">`,
      );
    }
  }
  tileLayer.innerHTML = tiles.join("");
  tileLayer.querySelectorAll(".amap-map-tile[data-fallback-srcs]").forEach((tile) => {
    tile.addEventListener("error", () => switchAmapTileToGlobalFallback(tile), { once: true });
  });
}

function renderAmapMarker(canvas, markerElement, center, markerPoint, zoom) {
  if (!canvas || !markerElement) return;
  const centerPixel = lngLatToWebMercatorPixel(center[0], center[1], zoom);
  const markerPixel = lngLatToWebMercatorPixel(markerPoint[0], markerPoint[1], zoom);
  const left = canvas.clientWidth / 2 + markerPixel.x - centerPixel.x;
  const top = canvas.clientHeight / 2 + markerPixel.y - centerPixel.y;
  markerElement.style.transform = `translate(${left.toFixed(2)}px, ${top.toFixed(2)}px) translate(-50%, -100%)`;
}

function amapTileUrl(server, x, y, z) {
  return `https://webrd0${server}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x=${x}&y=${y}&z=${z}`;
}

function osmTileUrl(x, y, z, providerIndex = 0) {
  const provider = OSM_TILE_PROVIDERS[providerIndex] || OSM_TILE_PROVIDERS[0];
  return provider.url(x, y, z);
}

function osmTileFallbackUrls(x, y, z) {
  return OSM_TILE_PROVIDERS.map((provider) => provider.url(x, y, z));
}

function switchAmapTileToGlobalFallback(tile) {
  if (!tile) return;
  let fallbackSources = [];
  try {
    fallbackSources = JSON.parse(decodeURIComponent(tile.dataset.fallbackSrcs || "[]"));
  } catch (error) {
    fallbackSources = [];
  }
  const fallbackIndex = Number(tile.dataset.fallbackIndex || 0);
  const fallbackSource = fallbackSources[fallbackIndex];
  if (!fallbackSource) return;
  tile.dataset.fallbackIndex = String(fallbackIndex + 1);
  tile.classList.add("global-fallback");
  tile.addEventListener("error", () => switchAmapTileToGlobalFallback(tile), { once: true });
  tile.src = fallbackSource;
}

function lngLatToWebMercatorPixel(longitude, latitude, zoom) {
  const lat = clampLatitude(latitude);
  const lng = clampLongitude(longitude);
  const sinLat = Math.sin((lat * Math.PI) / 180);
  const scale = AMAP_TILE_SIZE * 2 ** zoom;
  return {
    x: ((lng + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

function webMercatorPixelToLngLat(x, y, zoom) {
  const scale = AMAP_TILE_SIZE * 2 ** zoom;
  const longitude = (x / scale) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  const latitude = (Math.atan(Math.sinh(n)) * 180) / Math.PI;
  return [clampLongitude(longitude), clampLatitude(latitude)];
}

function normalizeLngLatArray(position) {
  const longitude = Array.isArray(position) ? Number(position[0]) : Number(position?.lng);
  const latitude = Array.isArray(position) ? Number(position[1]) : Number(position?.lat);
  return [
    clampLongitude(Number.isFinite(longitude) ? longitude : 116.39723),
    clampLatitude(Number.isFinite(latitude) ? latitude : 39.9075),
  ];
}

function clampLatitude(latitude) {
  return Math.max(-WEB_MERCATOR_MAX_LAT, Math.min(WEB_MERCATOR_MAX_LAT, Number(latitude)));
}

function clampLongitude(longitude) {
  const value = Number(longitude);
  if (!Number.isFinite(value)) return 0;
  return ((value + 180) % 360 + 360) % 360 - 180;
}

function clampZoom(zoom) {
  return Math.max(AMAP_MIN_ZOOM, Math.min(AMAP_MAX_ZOOM, Math.round(Number(zoom) || AMAP_DEFAULT_ZOOM)));
}

function modulo(value, divisor) {
  return ((value % divisor) + divisor) % divisor;
}

function setMapPoint(latitude, longitude, source = "map", geocodeResult = null) {
  if (source !== "map") state.mapReverseGeocodeToken += 1;
  state.mapPoint = { latitude, longitude };
  document.getElementById("weatherLatitude").value = formatCoordinate(latitude);
  document.getElementById("weatherLongitude").value = formatCoordinate(longitude);
  rememberWeatherCoordinate(latitude, longitude, coordinateInputNumber("weatherYear"), document.getElementById("weatherPlace")?.value || "");
  if (state.mapInstance) {
    state.mapInstance.setCenter([longitude, latitude]);
    if (source === "geocode" && state.mapInstance.setZoom) state.mapInstance.setZoom(11);
    if (state.mapMarker) state.mapMarker.setPosition([longitude, latitude]);
  }
  const sourceText = source === "geocode" ? geocodeHintLabel(geocodeResult) : (source === "manual" ? "输入坐标" : "地图坐标");
  setMapPickerHint(`${sourceText}：${formatCoordinate(latitude)}, ${formatCoordinate(longitude)}`);
  setWeatherImportStatus("坐标已填入", "ok");
}

function syncMapPointFromInputs() {
  const latitude = coordinateInputNumber("weatherLatitude");
  const longitude = coordinateInputNumber("weatherLongitude");
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  if (latitude < -90 || latitude > 90) {
    setMapPickerHint("纬度范围应为 -90 到 90");
    return;
  }
  if (longitude < -180 || longitude > 180) {
    setMapPickerHint("经度范围应为 -180 到 180");
    return;
  }
  setMapPoint(latitude, longitude, "manual");
}

function rememberWeatherCoordinate(latitude, longitude, year, place = "") {
  const lat = Number(latitude);
  const lng = Number(longitude);
  const dataYear = Number(year);
  const cleanPlace = String(place || document.getElementById("weatherPlace")?.value || "").trim();
  const payload = {
    place: cleanPlace,
  };
  if (Number.isFinite(lat)) {
    payload.latitude = lat;
    payload.latitudeText = formatCoordinate(lat);
  }
  if (Number.isFinite(lng)) {
    payload.longitude = lng;
    payload.longitudeText = formatCoordinate(lng);
  }
  if (Number.isInteger(dataYear)) {
    payload.year = dataYear;
    payload.yearText = String(dataYear);
  } else {
    const yearText = String(document.getElementById("weatherYear")?.value || "");
    if (yearText) payload.yearText = yearText;
  }
  writeWeatherCoordinatePayload(payload);
}

function rememberWeatherInputsFromFields() {
  const place = String(document.getElementById("weatherPlace")?.value || "").trim();
  const latitudeText = String(document.getElementById("weatherLatitude")?.value || "");
  const longitudeText = String(document.getElementById("weatherLongitude")?.value || "");
  const yearText = String(document.getElementById("weatherYear")?.value || "");
  const latitude = storedOptionalNumber(latitudeText);
  const longitude = storedOptionalNumber(longitudeText);
  const year = storedOptionalNumber(yearText);
  const payload = { place, latitudeText, longitudeText, yearText };
  if (Number.isFinite(latitude)) payload.latitude = latitude;
  if (Number.isFinite(longitude)) payload.longitude = longitude;
  if (Number.isInteger(year)) payload.year = year;
  writeWeatherCoordinatePayload(payload);
}

function writeWeatherCoordinatePayload(payload) {
  const hasValue = Object.values(payload || {}).some((value) => String(value ?? "").trim() !== "");
  try {
    if (hasValue) localStorage.setItem(WEATHER_COORDINATE_STORAGE_KEY, JSON.stringify(payload));
    else localStorage.removeItem(WEATHER_COORDINATE_STORAGE_KEY);
  } catch (error) {
    console.warn("保存气象坐标失败", error);
  }
}

function restoreWeatherCoordinate() {
  let stored = null;
  try {
    stored = JSON.parse(localStorage.getItem(WEATHER_COORDINATE_STORAGE_KEY) || "null");
  } catch (error) {
    stored = null;
  }
  if (!stored) return;
  const latitude = storedOptionalNumber(stored.latitude);
  const longitude = storedOptionalNumber(stored.longitude);
  const year = storedOptionalNumber(stored.year);
  const latitudeText = typeof stored.latitudeText === "string" ? stored.latitudeText : "";
  const longitudeText = typeof stored.longitudeText === "string" ? stored.longitudeText : "";
  const yearText = typeof stored.yearText === "string" ? stored.yearText : "";
  const place = String(stored.place || "").trim();
  const latitudeInput = document.getElementById("weatherLatitude");
  const longitudeInput = document.getElementById("weatherLongitude");
  const yearInput = document.getElementById("weatherYear");
  if (latitudeInput) latitudeInput.value = latitudeText || (Number.isFinite(latitude) ? formatCoordinate(latitude) : "");
  if (longitudeInput) longitudeInput.value = longitudeText || (Number.isFinite(longitude) ? formatCoordinate(longitude) : "");
  if (yearInput) yearInput.value = yearText || (Number.isInteger(year) ? String(year) : "");
  if (place) document.getElementById("weatherPlace").value = place;
  if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
    state.mapPoint = { latitude, longitude };
  }
}

function storedOptionalNumber(value) {
  if (value === null || value === undefined || value === "") return NaN;
  const number = Number(value);
  return Number.isFinite(number) ? number : NaN;
}

function formatCoordinate(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(3) : "";
}

function renderWeatherPreviewLegend() {
  document.querySelectorAll("[data-weather-preview-curve]").forEach((button) => {
    const active = state.weatherPreviewVisibleCurves.has(button.dataset.weatherPreviewCurve);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function toggleWeatherPreviewCurve(curveKey) {
  if (!curveKey) return;
  if (state.weatherPreviewVisibleCurves.has(curveKey)) {
    state.weatherPreviewVisibleCurves.delete(curveKey);
  } else {
    state.weatherPreviewVisibleCurves.add(curveKey);
  }
  renderWeatherPreviewLegend();
  renderWeatherPreviewChart(state.pendingWeatherRows || []);
  rememberPlanningPageState({ weatherPreviewVisibleCurves: Array.from(state.weatherPreviewVisibleCurves) });
}

function renderWeatherPreviewChart(rows) {
  const svg = document.getElementById("weatherPreviewChart");
  if (!svg) return;
  renderWeatherPreviewStats(rows);
  const width = svg.clientWidth || 900;
  const height = svg.clientHeight || 210;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const baseRect = `<rect x="0" y="0" width="${width}" height="${height}" rx="12" fill="transparent"/>`;
  if (!Array.isArray(rows) || rows.length === 0) {
    svg.innerHTML = `${baseRect}<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5a716e" font-size="15">获取气象后显示风、光、温曲线预览</text>`;
    return;
  }
  const visibleSpecs = weatherPreviewSeries.filter(([key]) => state.weatherPreviewVisibleCurves.has(key));
  if (!visibleSpecs.length) {
    svg.innerHTML = `${baseRect}<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5a716e" font-size="15">请选择至少一条曲线</text>`;
    return;
  }

  const padding = { left: 54, right: 24, top: 22, bottom: 32 };
  const plotWidth = Math.max(1, width - padding.left - padding.right);
  const plotHeight = Math.max(1, height - padding.top - padding.bottom);
  const x = (index) => padding.left + (index / Math.max(1, rows.length - 1)) * plotWidth;
  const yScale = (key) => {
    const values = rows.map((row) => Number(row[key])).filter(Number.isFinite);
    const rawMin = values.length ? Math.min(...values) : 0;
    const rawMax = values.length ? Math.max(...values) : 1;
    const min = rawMin === rawMax ? rawMin - 1 : rawMin;
    const max = rawMin === rawMax ? rawMax + 1 : rawMax;
    const span = max - min || 1;
    return {
      rawMin,
      rawMax,
      y(value) {
        const number = Number(value);
        const safeValue = Number.isFinite(number) ? number : rawMin;
        return padding.top + plotHeight - ((safeValue - min) / span) * plotHeight;
      },
    };
  };
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = padding.top + plotHeight * ratio;
      return `<line x1="${padding.left}" x2="${width - padding.right}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(137, 180, 186, 0.36)"/>`;
    })
    .join("");
  const xTicks = monthRanges
    .map(([label, start]) => {
      const tickX = x(start);
      return `<line x1="${tickX.toFixed(1)}" x2="${tickX.toFixed(1)}" y1="${padding.top + plotHeight}" y2="${padding.top + plotHeight + 5}" stroke="rgba(137, 180, 186, 0.5)"/><text x="${tickX.toFixed(1)}" y="${height - 9}" text-anchor="middle" fill="#dffbff" font-size="10">${label}</text>`;
    })
    .join("");
  const paths = visibleSpecs
    .map(([key, title, color, unit]) => {
      const scale = yScale(key);
      const d = rows.map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${scale.y(row[key]).toFixed(1)}`).join(" ");
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" vector-effect="non-scaling-stroke"><title>${escapeHtml(title)} ${escapeHtml(formatNumber(scale.rawMin))}-${escapeHtml(formatNumber(scale.rawMax))}${escapeHtml(unit)}</title></path>`;
    })
    .join("");
  svg.innerHTML = `${baseRect}<g>${grid}</g><line x1="${padding.left}" x2="${width - padding.right}" y1="${padding.top + plotHeight}" y2="${padding.top + plotHeight}" stroke="rgba(180, 226, 230, 0.7)"/><line x1="${padding.left}" x2="${padding.left}" y1="${padding.top}" y2="${padding.top + plotHeight}" stroke="rgba(180, 226, 230, 0.7)"/><g>${xTicks}</g>${paths}`;
}

function renderWeatherPreviewStats(rows) {
  const host = document.getElementById("weatherPreviewStats");
  if (!host) return;
  if (!Array.isArray(rows) || rows.length === 0) {
    host.innerHTML = '<span class="weather-preview-stat-empty">暂无气象数据</span>';
    return;
  }
  host.innerHTML = weatherPreviewSeries
    .map(([key, title, color, unit]) => {
      const stats = calculateSeriesStats(rows, key);
      if (!stats.count) {
        return `<div class="weather-preview-stat-item" style="--curve-color:${color}"><strong>${escapeHtml(title)}</strong><span>暂无</span></div>`;
      }
      return `<div class="weather-preview-stat-item" style="--curve-color:${color}"><strong>${escapeHtml(title)}</strong><span>最大值 ${escapeHtml(formatNumber(stats.max))}${escapeHtml(unit)}</span><span>最小值 ${escapeHtml(formatNumber(stats.min))}${escapeHtml(unit)}</span><span>平均值 ${escapeHtml(formatNumber(stats.avg))}${escapeHtml(unit)}</span></div>`;
    })
    .join("");
}

function geocodeHintLabel(result) {
  const displayName = String(result?.display_name || result?.place || "").trim();
  const provider = String(result?.source || "").includes("高德") ? "高德定位" : "地名定位";
  return displayName ? `${provider}（${displayName}）` : provider;
}

async function confirmMapPoint() {
  if (await applyPendingWeatherHistory()) {
    closeMapPicker();
  }
}

function validateWeatherInputs(latitude, longitude, year) {
  const currentYear = new Date().getFullYear();
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) return "纬度范围应为 -90 到 90";
  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) return "经度范围应为 -180 到 180";
  if (!Number.isInteger(year) || year < 2001 || year >= currentYear) return `历史数据年必须为2001到${currentYear - 1}之间的整数`;
  return "";
}

function setWeatherImportStatus(message, level = "") {
  const host = document.getElementById("weatherImportStatus");
  if (!host) return;
  host.textContent = message;
  host.classList.toggle("error", level === "error");
  host.classList.toggle("ok", level === "ok");
}

function setMapPickerHint(message) {
  const hint = document.getElementById("mapPickerHint");
  if (hint) hint.textContent = message;
}

async function selectNextSchemeAfterDelete(deletedIndex) {
  state.schemes = (await api("/api/planning/schemes")).schemes;
  const nextScheme = state.schemes[Math.min(deletedIndex, state.schemes.length - 1)];
  state.currentScheme = "";
  state.payload = null;
  if (nextScheme) {
    await selectScheme(nextScheme.name);
  } else {
    renderAll();
  }
}

async function ensureTimeSeriesLoaded() {
  if (!state.currentScheme || !state.payload || isTimeSeriesLoaded()) return true;
  if (state.timeSeriesLoading) return state.timeSeriesLoading;
  state.timeSeriesLoading = api(`/api/planning/schemes/${encodeURIComponent(state.currentScheme)}/time-series`)
    .then((data) => {
      if (!state.payload || data.scheme !== state.currentScheme) return false;
      state.payload.time_series = data.time_series || [];
      state.payload.time_series_count = data.time_series_count ?? state.payload.time_series.length;
      state.payload.validation = data.validation || state.payload.validation || [];
      setTimeSeriesLoaded(true);
      state.timeSeriesDirty = false;
      state.month = 0;
      renderChart();
      renderTimeTable();
      renderLimitSummary();
      renderSummary();
      return true;
    })
    .finally(() => {
      state.timeSeriesLoading = null;
    });
  renderChart();
  renderMonthTabs();
  renderTimeTable();
  renderLimitSummary();
  renderSummary();
  return state.timeSeriesLoading;
}

function ensureTimeSeriesForActiveTab() {
  if (shouldAutoLoadTimeSeries()) {
    ensureTimeSeriesLoaded().catch(showError);
  }
}

function shouldAutoLoadTimeSeries() {
  const tab = activeTabKey();
  return tab === "time" || tab === "limits";
}

function activeTabKey() {
  const tab = document.querySelector(".tab.active");
  return tab ? tab.dataset.tab : "time";
}

function renderAll() {
  renderSchemes();
  renderTimeChartRangeControls();
  renderChart();
  renderMonthTabs();
  renderTimeTable();
  renderDeviceFilters();
  renderDeviceTables();
  renderPlanningParameters();
  renderLimitSummary();
  renderSummary();
}

function renderChart() {
  const svg = document.getElementById("timeChart");
  if (!state.payload) {
    svg.innerHTML = "";
    state.chartMeta = null;
    return;
  }
  if (!isTimeSeriesLoaded()) {
    const width = svg.clientWidth || 900;
    const height = svg.clientHeight || 320;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" rx="18" fill="transparent"/><text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#5a716e" font-size="16">${state.timeSeriesLoading ? "时序数据加载中..." : "时序数据尚未加载"}</text>`;
    state.chartMeta = null;
    return;
  }
  const rows = filteredTimeChartRows(state.payload.time_series || []);
  const width = svg.clientWidth || 900;
  const height = svg.clientHeight || 320;
  const padLeft = 62;
  const padRight = 28;
  const padTop = 28;
  const padBottom = 48;
  const plotWidth = Math.max(1, width - padLeft - padRight);
  const plotHeight = Math.max(1, height - padTop - padBottom);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const [curveKey, curveTitle, color, unit] = selectedCurveSpec();
  const values = numericValues(rows, curveKey);
  const rawMin = values.length ? Math.min(...values) : 0;
  const rawMax = values.length ? Math.max(...values) : 1;
  const minValue = rawMin === rawMax ? rawMin - 1 : rawMin;
  const maxValue = rawMin === rawMax ? rawMax + 1 : rawMax;
  const valueSpan = maxValue - minValue || 1;
  const x = (index) => padLeft + (index / Math.max(1, rows.length - 1)) * plotWidth;
  const y = (value) => {
    const number = Number(value);
    const safeValue = Number.isFinite(number) ? number : 0;
    return padTop + plotHeight - ((safeValue - minValue) / valueSpan) * plotHeight;
  };
  const yTicks = [0, 1, 2, 3, 4].map((index) => minValue + (valueSpan * index) / 4);
  const yGrid = yTicks
    .map((value) => {
      const tickY = y(value);
      return `<line x1="${padLeft}" x2="${width - padRight}" y1="${tickY.toFixed(1)}" y2="${tickY.toFixed(1)}" stroke="#d4e1dd"/><text x="${padLeft - 8}" y="${(tickY + 4).toFixed(1)}" text-anchor="end" fill="#5a716e" font-size="11">${escapeHtml(formatNumber(value))}</text>`;
    })
    .join("");
  const xTicks = timeChartXTicks(rows, x, height, padTop, plotHeight);
  const d = rows.map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(row[curveKey]).toFixed(1)}`).join(" ");
  const axisTitle = `${curveTitle}${unit ? `(${unit})` : ""}`;
  svg.innerHTML = `<rect x="0" y="0" width="${width}" height="${height}" rx="18" fill="transparent"/><g>${yGrid}</g><line x1="${padLeft}" x2="${width - padRight}" y1="${padTop + plotHeight}" y2="${padTop + plotHeight}" stroke="#5a716e"/><line x1="${padLeft}" x2="${padLeft}" y1="${padTop}" y2="${padTop + plotHeight}" stroke="#5a716e"/><g>${xTicks}</g><path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/><g id="chartCursor" class="chart-cursor" hidden><line id="chartCursorLine" x1="0" x2="0" y1="${padTop}" y2="${padTop + plotHeight}"/><circle id="chartCursorPoint" cx="0" cy="0" r="4"/></g><text x="${padLeft}" y="18" fill="#294944" font-size="13" font-weight="700">${escapeHtml(axisTitle)}</text>`;
  state.chartMeta = { rows, curveKey, curveTitle, color, unit, padLeft, padRight, padTop, plotWidth, plotHeight, minValue, valueSpan, width, height };
}

function bindTimeChartRangeControls() {
  document.querySelectorAll("[data-time-chart-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      state.timeChartRange.scope = button.dataset.timeChartScope || "year";
      state.timeChartRange = normalizeTimeChartRange(state.timeChartRange);
      hideChartCursor();
      renderTimeChartRangeControls();
      renderChart();
      rememberPlanningPageState({ timeChartRange: state.timeChartRange });
    });
  });
  const monthSelect = document.getElementById("timeChartMonth");
  if (monthSelect) {
    monthSelect.addEventListener("change", () => {
      state.timeChartRange.month = Number(monthSelect.value);
      state.timeChartRange.day = 1;
      state.timeChartRange = normalizeTimeChartRange(state.timeChartRange);
      hideChartCursor();
      renderTimeChartRangeControls();
      renderChart();
      rememberPlanningPageState({ timeChartRange: state.timeChartRange });
    });
  }
  const daySelect = document.getElementById("timeChartDay");
  if (daySelect) {
    daySelect.addEventListener("change", () => {
      state.timeChartRange.day = Number(daySelect.value);
      state.timeChartRange = normalizeTimeChartRange(state.timeChartRange);
      hideChartCursor();
      renderTimeChartRangeControls();
      renderChart();
      rememberPlanningPageState({ timeChartRange: state.timeChartRange });
    });
  }
  renderTimeChartRangeControls();
}

function renderTimeChartRangeControls() {
  state.timeChartRange = normalizeTimeChartRange(state.timeChartRange);
  document.querySelectorAll("[data-time-chart-scope]").forEach((button) => {
    const active = button.dataset.timeChartScope === state.timeChartRange.scope;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const monthSelect = document.getElementById("timeChartMonth");
  if (monthSelect) {
    monthSelect.innerHTML = monthRanges.map(([label], index) => `<option value="${index}" ${index === state.timeChartRange.month ? "selected" : ""}>${label}</option>`).join("");
    monthSelect.disabled = state.timeChartRange.scope === "year";
  }
  const daySelect = document.getElementById("timeChartDay");
  if (daySelect) {
    daySelect.innerHTML = availableDaysInMonth(state.timeChartRange.month).map((day) => `<option value="${day}" ${day === state.timeChartRange.day ? "selected" : ""}>${day}日</option>`).join("");
    daySelect.disabled = state.timeChartRange.scope !== "day";
  }
}

function normalizeTimeChartRange(range) {
  const next = { scope: "year", month: 0, day: 1, ...(range || {}) };
  if (!["year", "month", "day"].includes(next.scope)) next.scope = "year";
  next.month = Math.min(Math.max(Number.isFinite(Number(next.month)) ? Number(next.month) : 0, 0), 11);
  const days = availableDaysInMonth(next.month);
  next.day = Math.min(Math.max(Number.isFinite(Number(next.day)) ? Number(next.day) : 1, 1), days.length);
  return next;
}

function availableDaysInMonth(monthIndex) {
  const [, start, end] = monthRanges[Math.min(Math.max(Number(monthIndex) || 0, 0), 11)] || monthRanges[0];
  return Array.from({ length: Math.ceil((end - start) / 24) }, (_, index) => index + 1);
}

function filteredTimeChartRows(rows) {
  const range = normalizeTimeChartRange(state.timeChartRange);
  if (range.scope === "year") {
    return rows.map((row, index) => ({ ...row, absoluteIndex: index }));
  }
  const [, monthStart, monthEnd] = monthRanges[range.month] || monthRanges[0];
  const start = range.scope === "day" ? monthStart + (range.day - 1) * 24 : monthStart;
  const end = range.scope === "day" ? Math.min(start + 24, monthEnd) : monthEnd;
  return rows.slice(start, end).map((row, offset) => ({ ...row, absoluteIndex: start + offset }));
}

function timeChartXTicks(rows, x, height, padTop, plotHeight) {
  if (!rows.length) return "";
  if (state.timeChartRange.scope === "year") {
    return monthRanges
      .map(([label, start]) => {
        const tickX = x(start);
        return `<line x1="${tickX.toFixed(1)}" x2="${tickX.toFixed(1)}" y1="${padTop + plotHeight}" y2="${padTop + plotHeight + 5}" stroke="#8ba49f"/><text x="${tickX.toFixed(1)}" y="${height - 12}" text-anchor="middle" fill="#5a716e" font-size="11">${label}</text>`;
      })
      .join("");
  }
  const tickCount = state.timeChartRange.scope === "day" ? 6 : 5;
  return Array.from({ length: tickCount }, (_, index) => {
    const pointIndex = Math.min(Math.round((index / Math.max(tickCount - 1, 1)) * Math.max(rows.length - 1, 0)), rows.length - 1);
    const row = rows[pointIndex] || {};
    const label = state.timeChartRange.scope === "day" ? `${((row.absoluteIndex || 0) % 24) + 1}时` : `第${Math.floor(pointIndex / 24) + 1}日`;
    const tickX = x(pointIndex);
    return `<line x1="${tickX.toFixed(1)}" x2="${tickX.toFixed(1)}" y1="${padTop + plotHeight}" y2="${padTop + plotHeight + 5}" stroke="#8ba49f"/><text x="${tickX.toFixed(1)}" y="${height - 12}" text-anchor="middle" fill="#5a716e" font-size="11">${escapeHtml(label)}</text>`;
  }).join("");
}

function selectedCurveSpec() {
  const selected = document.querySelector('[data-curve][aria-pressed="true"]');
  return summarySeries.find(([key]) => key === selected?.dataset.curve) || summarySeries[0];
}

function selectCurve(curveKey, options = {}) {
  const target = summarySeries.find(([key]) => key === curveKey) || summarySeries[0];
  document.querySelectorAll("[data-curve]").forEach((button) => {
    const active = button.dataset.curve === target[0];
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  hideChartCursor();
  renderChart();
  if (options.remember !== false) rememberPlanningPageState({ selectedCurve: target[0] });
}

function onChartMouseMove(event) {
  if (!state.chartMeta) return;
  const svg = document.getElementById("timeChart");
  const cursor = document.getElementById("chartCursor");
  const cursorLine = document.getElementById("chartCursorLine");
  const cursorPoint = document.getElementById("chartCursorPoint");
  const tip = document.getElementById("chartTip");
  if (!svg || !cursor || !cursorLine || !cursorPoint || !tip) return;
  const meta = state.chartMeta;
  const rect = svg.getBoundingClientRect();
  const localX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * meta.width;
  const ratio = Math.min(1, Math.max(0, (localX - meta.padLeft) / meta.plotWidth));
  const index = Math.round(ratio * Math.max(1, meta.rows.length - 1));
  const row = meta.rows[index];
  if (!row) return;
  const pointX = meta.padLeft + (index / Math.max(1, meta.rows.length - 1)) * meta.plotWidth;
  const value = Number(row[meta.curveKey]);
  const safeValue = Number.isFinite(value) ? value : 0;
  const pointY = meta.padTop + meta.plotHeight - ((safeValue - meta.minValue) / meta.valueSpan) * meta.plotHeight;
  cursor.hidden = false;
  cursorLine.setAttribute("x1", pointX.toFixed(1));
  cursorLine.setAttribute("x2", pointX.toFixed(1));
  cursorPoint.setAttribute("cx", pointX.toFixed(1));
  cursorPoint.setAttribute("cy", pointY.toFixed(1));
  cursorPoint.setAttribute("fill", meta.color);
  tip.hidden = false;
  tip.innerHTML = `${escapeHtml(meta.curveTitle)}：${escapeHtml(formatNumber(safeValue))}${escapeHtml(meta.unit)}<br>小时：${escapeHtml(row.hour_index ?? index + 1)}<br>时间：${escapeHtml(row.datetime || "")}`;
  positionFloatingTipInRect(tip, rect, event);
}

function startChartValueDrag(event) {
  if (!state.chartMeta || !state.payload || !isTimeSeriesLoaded()) return;
  if (event.button !== undefined && event.button !== 0) return;
  if (event.isPrimary === false) return;
  const timeChart = document.getElementById("timeChart");
  if (!timeChart) return;

  event.preventDefault();
  state.chartDrag = { pointerId: event.pointerId, edited: false, lastPoint: null };
  timeChart.classList.add("editing");
  timeChart.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", onChartValueDragMove);
  window.addEventListener("pointerup", endChartValueDrag);
  window.addEventListener("pointercancel", endChartValueDrag);
  applyChartValueEdit(event);
}

function onChartValueDragMove(event) {
  if (!state.chartDrag) return;
  if (event.pointerId !== undefined && state.chartDrag.pointerId !== undefined && event.pointerId !== state.chartDrag.pointerId) return;
  event.preventDefault();
  applyChartValueEdit(event);
}

function endChartValueDrag(event) {
  if (!state.chartDrag) return;
  if (event?.pointerId !== undefined && state.chartDrag.pointerId !== undefined && event.pointerId !== state.chartDrag.pointerId) return;
  const timeChart = document.getElementById("timeChart");
  const edited = state.chartDrag.edited;
  if (timeChart) {
    timeChart.classList.remove("editing");
    timeChart.releasePointerCapture?.(state.chartDrag.pointerId);
  }
  state.chartDrag = null;
  window.removeEventListener("pointermove", onChartValueDragMove);
  window.removeEventListener("pointerup", endChartValueDrag);
  window.removeEventListener("pointercancel", endChartValueDrag);
  if (edited) {
    renderTimeTable();
    renderLimitSummary();
    renderSummary();
  }
}

function applyChartValueEdit(event) {
  if (!state.chartMeta || !state.payload || !isTimeSeriesLoaded()) return false;
  const meta = state.chartMeta;
  const point = chartValueFromPointer(event);
  if (!point) return false;
  const points = interpolatedCurveEditPoints(state.chartDrag?.lastPoint, point);
  let edited = false;
  points.forEach(({ index: pointIndex, value }) => {
    const absoluteIndex = meta.rows[pointIndex]?.absoluteIndex ?? pointIndex;
    const row = state.payload.time_series[absoluteIndex];
    if (!row) return;
    const editedValue = roundEditedCurveValue(clampEditedCurveValue(value, meta.curveKey));
    state.payload.time_series[absoluteIndex][meta.curveKey] = editedValue;
    updateVisibleTimeCell(absoluteIndex, meta.curveKey, editedValue);
    edited = true;
  });
  if (!edited) return false;
  markTimeSeriesDirty();
  if (state.chartDrag) {
    state.chartDrag.edited = true;
    state.chartDrag.lastPoint = point;
  }
  renderChart();
  onChartMouseMove(event);
  setWeatherImportStatus("曲线已修改，请保存方案", "ok");
  return true;
}

function chartValueFromPointer(event) {
  const meta = state.chartMeta;
  const svg = document.getElementById("timeChart");
  if (!meta || !svg) return null;
  const rect = svg.getBoundingClientRect();
  const localX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * meta.width;
  const localY = ((event.clientY - rect.top) / Math.max(1, rect.height)) * meta.height;
  const xRatio = Math.min(1, Math.max(0, (localX - meta.padLeft) / meta.plotWidth));
  const index = Math.round(xRatio * Math.max(1, meta.rows.length - 1));
  const yRatio = (meta.padTop + meta.plotHeight - localY) / meta.plotHeight;
  const value = meta.minValue + yRatio * meta.valueSpan;
  return { index, value };
}

function clampEditedCurveValue(value, curveKey) {
  if (!Number.isFinite(value)) return 0;
  return curveKey === "temperature" ? value : Math.max(0, value);
}

function roundEditedCurveValue(value) {
  return roundTimeSeriesValue(value);
}

function interpolatedCurveEditPoints(previousPoint, currentPoint) {
  const currentIndex = Math.round(Number(currentPoint?.index));
  const currentValue = Number(currentPoint?.value);
  if (!Number.isFinite(currentIndex) || !Number.isFinite(currentValue)) return [];
  const previousIndex = Math.round(Number(previousPoint?.index));
  const previousValue = Number(previousPoint?.value);
  if (!Number.isFinite(previousIndex) || !Number.isFinite(previousValue) || previousIndex === currentIndex) {
    return [{ index: currentIndex, value: currentValue }];
  }
  const startIndex = Math.min(previousIndex, currentIndex);
  const endIndex = Math.max(previousIndex, currentIndex);
  const indexSpan = currentIndex - previousIndex;
  const valueSpan = currentValue - previousValue;
  return Array.from({ length: endIndex - startIndex + 1 }, (_, offset) => {
    const index = startIndex + offset;
    const ratio = (index - previousIndex) / indexSpan;
    return { index, value: previousValue + valueSpan * ratio };
  });
}

function updateVisibleTimeCell(index, key, value) {
  const input = document.querySelector(`[data-time-index="${index}"][data-key="${key}"]`);
  const formatted = formatTimeSeriesCellValue(key, value);
  if (input) input.value = formatted;
  const display = document.querySelector(`[data-time-display-index="${index}"][data-time-display-key="${key}"]`);
  if (display) display.textContent = formatted;
}

function positionFloatingTipInRect(tip, bounds, event) {
  const margin = 8;
  const tipWidth = tip.offsetWidth || 180;
  const tipHeight = tip.offsetHeight || 64;
  const minLeft = bounds.left + margin;
  const maxLeft = Math.max(minLeft, bounds.right - tipWidth - margin);
  const minTop = bounds.top + margin;
  const maxTop = Math.max(minTop, bounds.bottom - tipHeight - margin);
  const preferredLeft = event.clientX + 14;
  const preferredTop = event.clientY - tipHeight - 10;
  const viewportLeft = Math.min(maxLeft, Math.max(minLeft, preferredLeft));
  const viewportTop = Math.min(maxTop, Math.max(minTop, preferredTop));
  const parent = tip.offsetParent || document.body;
  const parentRect = parent.getBoundingClientRect();
  tip.style.left = `${viewportLeft - parentRect.left + (parent.scrollLeft || 0)}px`;
  tip.style.top = `${viewportTop - parentRect.top + (parent.scrollTop || 0)}px`;
}

function hideChartCursor() {
  const cursor = document.getElementById("chartCursor");
  const tip = document.getElementById("chartTip");
  if (cursor) cursor.hidden = true;
  if (tip) tip.hidden = true;
}

function renderMonthTabs() {
  const host = document.getElementById("monthTabs");
  if (!host) return;
  host.innerHTML = monthRanges
    .map(([label], index) => `<button class="month-tab ${index === state.month ? "active" : ""}" type="button" data-month="${index}">${label}</button>`)
    .join("");
  host.querySelectorAll("[data-month]").forEach((button) => {
    button.addEventListener("click", () => {
      state.month = Number(button.dataset.month);
      renderMonthTabs();
      renderTimeTable();
      rememberPlanningPageState({ month: state.month });
    });
  });
}

function renderTimeTable() {
  const container = document.getElementById("timeTable");
  exitTimeCellEdit();
  if (!state.payload) {
    container.innerHTML = "";
    return;
  }
  if (!isTimeSeriesLoaded()) {
    document.getElementById("pageInfo").textContent = state.timeSeriesLoading ? "加载中" : "未加载";
    container.innerHTML = `<div class="empty-summary">${state.timeSeriesLoading ? "时序数据加载中..." : "时序数据尚未加载，进入时序数据或方案概览时会自动加载。"}</div>`;
    return;
  }
  const rows = state.payload.time_series || [];
  const [label, start, end] = monthRanges[state.month] || monthRanges[0];
  const pageRows = rows.slice(start, end);
  document.getElementById("pageInfo").textContent = `${label} 第 ${start + 1}-${Math.min(end, rows.length)} 小时`;
  const fields = ["datetime", "wind_speed", "solar_irradiance", "temperature", "load"];
  container.innerHTML = `<table><thead><tr><th>小时序号</th><th>时间</th><th>风速</th><th>太阳辐照</th><th>环境温度</th><th>负荷</th></tr></thead><tbody>${pageRows
    .map((row, offset) => {
      const index = start + offset;
      return `<tr><td>${row.hour_index}</td>${fields
        .map((key) => timeCellHtml(index, key, row[key]))
        .join("")}</tr>`;
    })
    .join("")}</tbody></table>`;
}

function timeCellHtml(index, key, value) {
  const safeValue = escapeHtml(formatTimeSeriesCellValue(key, value));
  return `<td class="time-cell" data-time-cell="true"><span class="time-cell-display" data-time-display-index="${index}" data-time-display-key="${escapeHtml(key)}">${safeValue}</span><input class="time-cell-input" data-time-index="${index}" data-key="${escapeHtml(key)}" value="${safeValue}" readonly="readonly" tabindex="-1"></td>`;
}

function onTimeInput(event) {
  const input = event.target;
  const row = state.payload.time_series[Number(input.dataset.timeIndex)];
  const key = input.dataset.key;
  const value = normalizeTimeSeriesCellValue(key, input.value);
  row[key] = value;
  const display = input.closest(".time-cell")?.querySelector(".time-cell-display");
  if (display) display.textContent = formatTimeSeriesCellValue(key, value);
  markTimeSeriesDirty();
  scheduleRenderChart();
  renderLimitSummary();
}

function renderDeviceTables() {
  const jump = document.getElementById("deviceJump");
  const host = document.getElementById("deviceTables");
  if (!state.payload) {
    jump.innerHTML = "";
    host.innerHTML = "";
    return;
  }
  const shownSpecs = deviceSpecs.filter(([key]) => visibleDevices.has(key));
  jump.innerHTML = shownSpecs.map(([key, title]) => `<a href="#${key}">${title}</a>`).join("");
  if (!shownSpecs.length) {
    host.innerHTML = "<div class=\"validation-item\">当前未选择任何设备类型。</div>";
    return;
  }
  const sharedColumnCount = deviceTableColumnCount(shownSpecs);
  host.innerHTML = shownSpecs
    .map(([key, title, fields]) => `<section id="${key}" class="device-card"><div class="panel-heading"><h2>${title}</h2><button class="add-row" type="button" data-device="${key}">新增行</button></div>${deviceTable(key, fields, sharedColumnCount)}</section>`)
    .join("");
  host.querySelectorAll(".device-input").forEach((input) => {
    input.addEventListener("input", onDeviceInput);
    input.addEventListener("blur", onDeviceInputBlur);
    input.addEventListener("keydown", onDeviceInputKeydown);
  });
  host.querySelectorAll(".device-cell").forEach((cell) => cell.addEventListener("pointerdown", onDeviceCellPointerDown));
  host.querySelectorAll(".device-row").forEach((row) => row.addEventListener("contextmenu", onDeviceRowContextMenu));
  host.querySelectorAll(".add-row").forEach((button) => button.addEventListener("click", addDeviceRow));
  activeDeviceEditingCell = null;
  hideDeviceContextMenu();
}

function renderDeviceFilters() {
  const host = document.getElementById("deviceFilters");
  if (!host) return;
  host.innerHTML = deviceGroups
    .map(([key, title, devices]) => `<label class="device-filter"><input type="checkbox" data-device-group="${key}" ${devices.every((device) => visibleDevices.has(device)) ? "checked" : ""}> ${title}</label>`)
    .join("");
  host.querySelectorAll("[data-device-group]").forEach((input) => {
    const group = deviceGroups.find(([key]) => key === input.dataset.deviceGroup);
    const devices = group ? group[2] : [];
    input.indeterminate = devices.some((device) => visibleDevices.has(device)) && !devices.every((device) => visibleDevices.has(device));
    input.addEventListener("change", () => {
      devices.forEach((device) => {
        if (input.checked) {
          visibleDevices.add(device);
        } else {
          visibleDevices.delete(device);
        }
      });
      renderDeviceFilters();
      renderDeviceTables();
      rememberPlanningPageState({ visibleDevices: Array.from(visibleDevices) });
    });
  });
}

function deviceTableColumnCount(specs) {
  return Math.max(0, ...specs.map(([, , fields]) => fields.length));
}

function deviceTable(key, fields, columnCount = fields.length) {
  const rows = state.payload[key] || [];
  const fillerCount = Math.max(0, columnCount - fields.length);
  const fillerHeadings = deviceEmptyColumnsHtml(fillerCount, "th", "device-empty-heading");
  return `<div class="data-table device-data-table"><table class="device-parameter-table"><thead><tr>${fields.map((field, columnIndex) => `<th class="${deviceColumnClass(columnIndex)}"><span class="device-heading-label">${deviceHeadingLabelHtml(field)}</span></th>`).join("")}${fillerHeadings}</tr></thead><tbody>${rows
    .map((row, index) => `<tr class="device-row" data-device="${escapeHtml(key)}" data-row="${index}">${fields.map((field, columnIndex) => `<td class="device-cell ${deviceColumnClass(columnIndex)}" data-device-cell-edit="true"><span class="device-cell-display">${escapeHtml(row[field])}</span><input ${deviceInputAttributes(key, index, field, row[field])}></td>`).join("")}${deviceEmptyColumnsHtml(fillerCount, "td", "device-empty-cell")}</tr>`)
    .join("")}</tbody></table></div>`;
}

function deviceEmptyColumnsHtml(count, tagName, className) {
  return Array.from({ length: count }, () => `<${tagName} class="${className}" aria-hidden="true"></${tagName}>`).join("");
}

function deviceHeadingLabelHtml(field) {
  const label = String(labels[field] || field);
  const symbolMatch = label.match(/^(.+?)([A-Za-z][A-Za-z0-9/_-]*[(（][^)）]+[)）])$/);
  if (symbolMatch) {
    if (symbolMatch[1].includes("效率")) {
      return `${escapeHtml(symbolMatch[1])}<br>${escapeHtml(symbolMatch[2].replace(/[()（）]/g, ""))}`;
    }
    return deviceTwoLineHeadingHtml(symbolMatch[1], symbolMatch[2]);
  }
  const match = label.match(/^(.+?)([(（][^)）]+[)）])$/);
  if (match) {
    if (match[1].includes("效率")) {
      return `${escapeHtml(match[1])}<br>${escapeHtml(match[2].replace(/[()（）]/g, ""))}`;
    }
    return deviceTwoLineHeadingHtml(match[1], match[2]);
  }
  const chars = Array.from(label);
  if (chars.length > 5) {
    return `${escapeHtml(chars.slice(0, 4).join(""))}<br>${escapeHtml(chars.slice(4).join(""))}`;
  }
  return escapeHtml(label);
}

function deviceTwoLineHeadingHtml(main, suffix) {
  const chars = Array.from(String(main || ""));
  if (chars.length > 4) {
    return `${escapeHtml(chars.slice(0, 4).join(""))}<br>${escapeHtml(`${chars.slice(4).join("")}${suffix}`)}`;
  }
  return `${escapeHtml(main)}<br>${escapeHtml(suffix)}`;
}

function deviceColumnClass(columnIndex) {
  return columnIndex < 3 ? `device-sticky-col device-sticky-${columnIndex + 1}` : "";
}

function deviceInputAttributes(device, rowIndex, field, value) {
  const rule = deviceFieldRules[field];
  const attrs = [
    'class="device-input"',
    `data-device="${escapeHtml(device)}"`,
    `data-row="${rowIndex}"`,
    `data-key="${escapeHtml(field)}"`,
    'readonly="readonly"',
    'tabindex="-1"',
  ];
  if (rule) {
    attrs.push('type="number"');
    attrs.push(...rule.attrs);
  }
  attrs.push(`value="${escapeHtml(value)}"`);
  return attrs.join(" ");
}

function onDeviceInput(event) {
  const input = event.target;
  state.payload[input.dataset.device][Number(input.dataset.row)][input.dataset.key] = coerceInput(input.value);
  const display = input.closest(".device-cell")?.querySelector(".device-cell-display");
  if (display) display.textContent = input.value;
  renderLimitSummary();
  renderSummary();
}

function addDeviceRow(event) {
  const key = event.target.dataset.device;
  const spec = deviceSpecs.find((item) => item[0] === key);
  const row = Object.fromEntries(spec[2].map((field) => [field, defaultDeviceFieldValue(field, spec)]));
  state.payload[key] = state.payload[key] || [];
  state.payload[key].push(row);
  renderDeviceTables();
  renderLimitSummary();
  renderSummary();
}

function defaultDeviceFieldValue(field, spec) {
  if (field === "name") {
    return `${spec[1]}${(state.payload[spec[0]] || []).length + 1}`;
  }
  if (spec[0] === "diesel_generators" && Object.prototype.hasOwnProperty.call(dieselGeneratorDefaultValues, field)) {
    return dieselGeneratorDefaultValues[field];
  }
  if (spec[0] === "wind_turbines" && Object.prototype.hasOwnProperty.call(windTurbineDefaultValues, field)) {
    return windTurbineDefaultValues[field];
  }
  if (spec[0] === "photovoltaics" && Object.prototype.hasOwnProperty.call(photovoltaicDefaultValues, field)) {
    return photovoltaicDefaultValues[field];
  }
  if (spec[0] === "storage_pcs" && Object.prototype.hasOwnProperty.call(storagePcsDefaultValues, field)) {
    return storagePcsDefaultValues[field];
  }
  if (spec[0] === "storage_battery_packs" && Object.prototype.hasOwnProperty.call(storageBatteryPackDefaultValues, field)) {
    return storageBatteryPackDefaultValues[field];
  }
  if (spec[0] === "hydrogen_electrolyzers" && Object.prototype.hasOwnProperty.call(hydrogenElectrolyzerDefaultValues, field)) {
    return hydrogenElectrolyzerDefaultValues[field];
  }
  if (spec[0] === "hydrogen_tanks" && Object.prototype.hasOwnProperty.call(hydrogenTankDefaultValues, field)) {
    return hydrogenTankDefaultValues[field];
  }
  if (spec[0] === "fuel_cells" && Object.prototype.hasOwnProperty.call(fuelCellDefaultValues, field)) {
    return fuelCellDefaultValues[field];
  }
  if (field === "self_discharge_rate") {
    return spec[0] === "hydrogen_tanks" ? 0.001 : 0.01;
  }
  if (spec[0] === "hydrogen_tanks" && field === "soc_upper") {
    return 0.85;
  }
  if (spec[0] === "hydrogen_tanks" && field === "soc_lower") {
    return 0.15;
  }
  return Object.prototype.hasOwnProperty.call(deviceFieldDefaults, field) ? deviceFieldDefaults[field] : 0;
}

function deleteDeviceRow(event) {
  deleteDeviceRowByPosition(event.target.dataset.device, Number(event.target.dataset.row));
}

function deleteDeviceRowByPosition(device, rowIndex) {
  if (!device || !Array.isArray(state.payload?.[device])) return;
  if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.payload[device].length) return;
  state.payload[device].splice(rowIndex, 1);
  hideDeviceContextMenu();
  renderDeviceTables();
  renderLimitSummary();
  renderSummary();
}

function renderPlanningParameters() {
  const host = document.getElementById("planningParametersTable");
  if (!host) return;
  if (!state.payload) {
    host.innerHTML = "";
    return;
  }
  const row = planningParameterRow();
  const activeGroup = planningParameterGroups.find((group) => group.key === activePlanningParameterGroup) || planningParameterGroups[0];
  activePlanningParameterGroup = activeGroup.key;
  host.innerHTML = `<div class="planning-parameter-grid">${renderPlanningParameterTabs(activeGroup.key)}<div class="planning-parameter-panel">${renderPlanningParameterGroupTable(activeGroup, row, true)}</div></div>`;
  host.querySelectorAll("[data-planning-parameter-tab]").forEach((button) => {
    button.addEventListener("click", () => selectPlanningParameterGroup(button.dataset.planningParameterTab));
  });
}

function renderPlanningParameterTabs(activeKey) {
  return `<div class="planning-parameter-tabs" role="tablist" aria-label="规划参数分页">${planningParameterGroups
    .map((group) => {
      const active = group.key === activeKey;
      return `<button class="planning-parameter-tab ${active ? "active" : ""}" type="button" role="tab" aria-selected="${active ? "true" : "false"}" data-planning-parameter-tab="${escapeHtml(group.key)}">${escapeHtml(group.title)}</button>`;
    })
    .join("")}</div>`;
}

function selectPlanningParameterGroup(groupKey) {
  if (!planningParameterGroups.some((group) => group.key === groupKey)) return;
  activePlanningParameterGroup = groupKey;
  renderPlanningParameters();
  rememberPlanningPageState({ activePlanningParameterGroup });
}

function renderPlanningParameterGroupTable(group, row, editable = false) {
  const groupEnabled = isPlanningGroupEnabled(group, row);
  const rows = group.keys
    .filter((key) => !group.toggleKey || key !== group.toggleKey)
    .map((key) => planningParameterSpecsByKey.get(key))
    .filter(Boolean)
    .map(([key, label, type, options]) => {
      const value = editable ? planningParameterControl(key, type, options, row[key], group, groupEnabled) : escapeHtml(formatPlanningParameterValue(row[key], type, options));
      return `<tr><td>${label}</td><td>${value}</td><td>${planningParameterRangeText(type, options)}</td></tr>`;
    })
    .join("");
  const toggle = editable && group.toggleKey ? planningGroupToggle(group, row) : "";
  const status = group.toggleKey ? `<em class="planning-parameter-group-status">${groupEnabled ? "已启用" : "未启用"}</em>` : "";
  return `<section class="planning-parameter-group ${groupEnabled ? "" : "disabled"}" data-planning-group="${escapeHtml(group.key)}"><h3>${toggle}<span>${escapeHtml(group.title)}</span>${status}</h3><table><colgroup><col class="planning-parameter-name-col"><col class="planning-parameter-value-col"><col class="planning-parameter-range-col"></colgroup><thead><tr><th>参数名称</th><th>参数值</th><th>取值范围</th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

function planningGroupToggle(group, row) {
  const checked = truthyPlanningValue(row[group.toggleKey]);
  return `<label class="planning-parameter-switch"><input type="checkbox" data-planning-group-toggle="${escapeHtml(group.key)}" data-planning-key="${escapeHtml(group.toggleKey)}" ${checked ? "checked" : ""}><span></span></label>`;
}

function isPlanningGroupEnabled(group, row) {
  return !group.toggleKey || truthyPlanningValue(row[group.toggleKey]);
}

function planningParameterControl(key, type, options, value, group = null, groupEnabled = true) {
  const isGroupToggle = group && group.toggleKey === key;
  const disabled = group && group.toggleKey && !groupEnabled && !isGroupToggle;
  if (type === "boolean") {
    const checked = truthyPlanningValue(value);
    return `<select class="planning-bool-select" data-planning-key="${key}" data-planning-type="boolean" ${disabled ? "disabled" : ""}><option value="1" ${checked ? "selected" : ""}>是</option><option value="0" ${checked ? "" : "selected"}>否</option></select>`;
  }
  if (type === "select") {
    const selectedValue = String(value || options.defaultValue || "");
    const optionMarkup = (options.options || [])
      .map(([optionValue, optionLabel]) => `<option value="${escapeHtml(optionValue)}" ${String(optionValue) === selectedValue ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`)
      .join("");
    return `<select class="planning-select" data-planning-key="${key}" data-planning-type="select" ${disabled ? "disabled" : ""}>${optionMarkup}</select>`;
  }
  const attrs = [
    `data-planning-key="${key}"`,
    'type="number"',
    options.min !== undefined ? `min="${options.min}"` : "",
    options.max !== undefined ? `max="${options.max}"` : "",
    `step="${options.integer ? 1 : 0.01}"`,
    disabled ? "disabled" : "",
  ].filter(Boolean).join(" ");
  return `<input ${attrs} value="${escapeHtml(value)}">`;
}

function onPlanningGroupToggle(event) {
  const input = event.target;
  const row = planningParameterRow();
  row[input.dataset.planningKey] = input.checked ? 1 : 0;
  renderPlanningParameters();
  renderLimitSummary();
  renderSummary();
}

function onPlanningParameterInput(event) {
  const input = event.target;
  syncPlanningParameterInput(input);
  renderLimitSummary();
  renderSummary();
}

function bindPlanningParameterInputs() {
  document.addEventListener("input", onPlanningParameterInputEvent);
  document.addEventListener("change", onPlanningParameterInputEvent);
}

function onPlanningParameterInputEvent(event) {
  const input = event.target;
  if (!input?.matches?.("[data-planning-key]")) return;
  if (input.dataset.planningGroupToggle) {
    if (event.type === "change") onPlanningGroupToggle(event);
    return;
  }
  onPlanningParameterInput(event);
}

function syncPlanningParameterInputs() {
  if (!state.payload) return;
  document.querySelectorAll("[data-planning-key]").forEach((input) => syncPlanningParameterInput(input));
}

function syncPlanningParameterInput(input) {
  if (!input || !input.dataset || !input.dataset.planningKey || !state.payload) return;
  const row = planningParameterRow();
  row[input.dataset.planningKey] =
    input.dataset.planningType === "boolean"
      ? numericBooleanPlanningValue(input.value)
      : input.dataset.planningType === "select"
        ? input.value
        : input.type === "checkbox"
          ? (input.checked ? 1 : 0)
          : coerceInput(input.value);
}

function planningParameterRow() {
  if (!state.payload) return defaultPlanningParameterRow();
  if (!Array.isArray(state.payload.planning_parameters)) {
    state.payload.planning_parameters = state.payload.planning_parameters ? [state.payload.planning_parameters] : [defaultPlanningParameterRow()];
  }
  if (!state.payload.planning_parameters.length) {
    state.payload.planning_parameters.push(defaultPlanningParameterRow());
  }
  state.payload.planning_parameters[0] = normalizePlanningParameterRow(state.payload.planning_parameters[0]);
  return state.payload.planning_parameters[0];
}

function defaultPlanningParameterRow() {
  return Object.fromEntries(planningParameterSpecs.map(([key, , , options]) => [key, options.defaultValue]));
}

function normalizePlanningParameterRow(row) {
  const normalized = { ...defaultPlanningParameterRow(), ...(row || {}) };
  planningParameterSpecs.forEach(([key, , type]) => {
    if (type === "boolean") {
      normalized[key] = numericBooleanPlanningValue(normalized[key]);
    }
    if (type === "select") {
      const spec = planningParameterSpecsByKey.get(key);
      const validValues = new Set((spec?.[3]?.options || []).map(([value]) => String(value)));
      normalized[key] = validValues.has(String(normalized[key])) ? String(normalized[key]) : spec?.[3]?.defaultValue || "";
    }
  });
  return normalized;
}

function renderPlanningParameterSummaryTable() {
  if (!state.payload) return "";
  const row = planningParameterRow();
  return `<div class="planning-parameter-grid summary">${planningParameterGroups
    .map((group) => renderPlanningParameterGroupTable(group, row, false))
    .join("")}</div>`;
}

function formatPlanningParameterValue(value, type, options = {}) {
  if (type === "boolean") return truthyPlanningValue(value) ? "是" : "否";
  if (type === "select") return formatPlanningParameterSelectValue(value, options);
  return value;
}

function formatPlanningParameterSelectValue(value, options) {
  const selected = (options.options || []).find(([optionValue]) => String(optionValue) === String(value));
  return selected ? selected[1] : value;
}

function planningParameterRangeText(type, options) {
  if (type === "boolean") return "是/否";
  if (type === "select") return (options.options || []).map(([, label]) => label).join(" / ");
  if (options.min !== undefined && options.max !== undefined) return `${options.min} - ${options.max}`;
  if (options.min !== undefined) return `不小于 ${options.min}`;
  if (options.max !== undefined) return `不大于 ${options.max}`;
  return "-";
}

function truthyPlanningValue(value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  return ["true", "1", "yes", "y", "是"].includes(String(value).trim().toLowerCase());
}

function numericBooleanPlanningValue(value) {
  return truthyPlanningValue(value) ? 1 : 0;
}

function renderLimitSummary() {
  renderSchemeSummary();
}

function renderSchemeSummary() {
  const hosts = [
    document.getElementById("summaryCharts"),
    document.getElementById("quantitySummary"),
    document.getElementById("planningSummary"),
  ].filter(Boolean);
  if (!state.payload) {
    hosts.forEach((host) => {
      host.innerHTML = "";
    });
    return;
  }

  const rows = isTimeSeriesLoaded() ? state.payload.time_series || [] : [];
  const chartsHost = document.getElementById("summaryCharts");
  const quantityHost = document.getElementById("quantitySummary");
  const planningHost = document.getElementById("planningSummary");

  if (chartsHost) {
    chartsHost.innerHTML = isTimeSeriesLoaded()
      ? summarySeries.map(([key, title, color, unit]) => renderHistogramPanel(rows, key, title, color, unit)).join("")
      : renderTimeSeriesPlaceholder("加载后显示风速、太阳辐照、环境温度、负荷直方图。");
  }

  if (quantityHost) {
    quantityHost.innerHTML = renderCandidateDeviceTable();
  }

  if (planningHost) {
    planningHost.innerHTML = renderPlanningParameterSummaryTable();
  }
  requestAnimationFrame(syncAdaptiveLayout);
}

function renderHistogramPanel(rows, key, title, color, unit) {
  const values = numericValues(rows, key);
  const stats = calculateSeriesStats(rows, key);
  return `<div class="histogram-panel"><div class="histogram-head"><strong>${title}分布</strong><span>${stats.count}点</span></div>${histogramSvg(values, color, title)}<div class="histogram-meta">最小值 ${formatNumber(stats.min)} ${unit} / 最大值 ${formatNumber(stats.max)} ${unit} / 平均值 ${formatNumber(stats.avg)} ${unit}</div></div>`;
}

function renderTimeSeriesPlaceholder(message) {
  return `<div class="empty-summary">时序数据尚未加载，${state.timeSeriesLoading ? "正在自动加载。" : message}</div>`;
}

function renderCandidateDeviceTable() {
  const rows = deviceSpecs.flatMap(([key, title]) =>
    (state.payload[key] || []).map((row) => ({
      device: title,
      name: row.name,
      capacity: capacityValue(key, row),
      lower: row.quantity_lower,
      upper: row.quantity_upper,
    })),
  );
  if (!rows.length) {
    return "<div class=\"empty-summary\">暂无设备条目</div>";
  }
  return `<table><thead><tr><th>设备类型</th><th>名称</th><th>容量</th><th>数量下限(台)</th><th>数量上限(台)</th><th>状态</th></tr></thead><tbody>${rows
    .map((row) => {
      const status = limitStatus(row.lower, row.upper);
      return `<tr><td>${row.device}</td><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.capacity)}</td><td>${escapeHtml(row.lower)}</td><td>${escapeHtml(row.upper)}</td><td class="${status === "正常" ? "status-ok" : "status-error"}">${status}</td></tr>`;
    })
    .join("")}</tbody></table>`;
}

function capacityValue(key, row) {
  const fieldByDevice = {
    diesel_generators: "capacity",
    wind_turbines: "capacity",
    photovoltaics: "capacity",
    storage_pcs: "power_capacity",
    storage_battery_packs: "battery_capacity",
    hydrogen_electrolyzers: "power_capacity",
    hydrogen_tanks: "hydrogen_tank_capacity",
    fuel_cells: "power_capacity",
  };
  return row[fieldByDevice[key]] ?? "";
}

function limitStatus(lower, upper) {
  if (lower === "" || upper === "") return "未填写";
  const lowerNumber = Number(lower);
  const upperNumber = Number(upper);
  if (!Number.isFinite(lowerNumber) || !Number.isFinite(upperNumber)) return "错误";
  return upperNumber < lowerNumber ? "错误" : "正常";
}

function numericValues(rows, key) {
  return rows
    .map((row) => row[key])
    .filter((value) => value !== "" && value !== null && value !== undefined)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function calculateSeriesStats(rows, key) {
  const values = numericValues(rows, key);
  if (!values.length) {
    return { count: 0, min: null, max: null, avg: null };
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  return { count: values.length, min, max, avg };
}

function buildHistogram(values, binCount = 12) {
  const cleanValues = values.filter((value) => Number.isFinite(value));
  if (!cleanValues.length) return [];
  const min = Math.min(...cleanValues);
  const max = Math.max(...cleanValues);
  if (min === max) return [{ lower: min, upper: max, count: cleanValues.length }];
  const step = (max - min) / binCount;
  const bins = Array.from({ length: binCount }, (_, index) => ({
    lower: min + step * index,
    upper: index === binCount - 1 ? max : min + step * (index + 1),
    count: 0,
  }));
  cleanValues.forEach((value) => {
    const index = Math.min(binCount - 1, Math.floor((value - min) / step));
    bins[index].count += 1;
  });
  return bins;
}

function histogramSvg(values, color, title = "") {
  const bins = buildHistogram(values);
  if (!bins.length) {
    return "<div class=\"empty-summary\">暂无时序数据</div>";
  }
  const width = 460;
  const height = 220;
  const padLeft = 48;
  const padRight = 20;
  const padTop = 34;
  const padBottom = 34;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const step = plotWidth / bins.length;
  const barWidth = Math.max(2, step - 4);
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const y = (count) => padTop + plotHeight - (count / maxCount) * plotHeight;
  const yTicks = [0, 0.5, 1].map((ratio) => maxCount * ratio);
  const yAxis = yTicks
    .map((count) => {
      const tickY = y(count);
      return `<line x1="${padLeft}" x2="${width - padRight}" y1="${tickY.toFixed(1)}" y2="${tickY.toFixed(1)}" stroke="#d4e1dd"/><text x="${padLeft - 8}" y="${(tickY + 4).toFixed(1)}" fill="#5a716e" font-size="11" text-anchor="end">${formatInteger(count)}</text>`;
    })
    .join("");
  const bars = bins
    .map((bin, index) => {
      const barHeight = (bin.count / maxCount) * plotHeight;
      const x = padLeft + step * index + (step - barWidth) / 2;
      const barY = padTop + plotHeight - barHeight;
      const title = `${formatNumber(bin.lower)} - ${formatNumber(bin.upper)}: ${bin.count}`;
      const labelY = Math.max(12, barY - 5);
      return `<rect class="histogram-bar" data-bin-range="${escapeHtml(formatHistogramRange(bin))}" data-bin-count="${escapeHtml(formatInteger(bin.count))}" x="${x.toFixed(1)}" y="${barY.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="3" fill="${color}"><title>${escapeHtml(title)}</title></rect><text x="${(x + barWidth / 2).toFixed(1)}" y="${labelY.toFixed(1)}" fill="#294944" font-size="10" text-anchor="middle">${formatInteger(bin.count)}</text>`;
    })
    .join("");
  const minLabel = formatNumber(bins[0].lower);
  const maxLabel = formatNumber(bins[bins.length - 1].upper);
  return `<svg class="histogram-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}统计直方图"><g>${yAxis}</g><line x1="${padLeft}" x2="${width - padRight}" y1="${padTop + plotHeight}" y2="${padTop + plotHeight}" stroke="#8ba49f"/><line x1="${padLeft}" x2="${padLeft}" y1="${padTop}" y2="${padTop + plotHeight}" stroke="#8ba49f"/>${bars}<text x="${padLeft}" y="${height - 8}" fill="#5a716e" font-size="12">${escapeHtml(minLabel)}</text><text x="${width - padRight}" y="${height - 8}" fill="#5a716e" font-size="12" text-anchor="end">${escapeHtml(maxLabel)}</text></svg>`;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatInteger(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.round(number)) : "-";
}

function formatHistogramRange(bin) {
  return `${formatNumber(bin.lower)} - ${formatNumber(bin.upper)}`;
}

function onHistogramMouseMove(event) {
  const bar = event.target.closest?.(".histogram-bar");
  if (!bar) {
    hideHistogramTip();
    return;
  }
  const tip = document.getElementById("chartTip");
  if (!tip) return;
  tip.hidden = false;
  tip.innerHTML = `横坐标：${escapeHtml(bar.dataset.binRange || "")}<br>纵坐标：${escapeHtml(bar.dataset.binCount || "")}`;
  positionFloatingTipInRect(tip, bar.ownerSVGElement.getBoundingClientRect(), event);
}

function hideHistogramTip() {
  const tip = document.getElementById("chartTip");
  if (tip && !document.getElementById("chartCursor")?.hidden) return;
  if (tip) tip.hidden = true;
}

function renderSummary() {
  const box = document.getElementById("schemeSummary");
  const list = document.getElementById("validationList");
  const currentSchemeName = document.getElementById("currentSchemeName");
  if (!state.payload) {
    if (currentSchemeName) currentSchemeName.textContent = "未选择方案";
    box.innerHTML = "未选择方案";
    list.innerHTML = "";
    return;
  }
  if (currentSchemeName) currentSchemeName.textContent = state.currentScheme;
  if (state.isSwitchingScheme) {
    box.innerHTML = `<div>当前：<strong>${escapeHtml(state.currentScheme || "未选择方案")}</strong></div><div>正在切换方案...</div>`;
    list.innerHTML = '<div class="validation-item">正在加载方案数据...</div>';
    return;
  }
  const timeSeriesCount = isTimeSeriesLoaded() ? (state.payload.time_series || []).length : state.payload.time_series_count || 0;
  box.innerHTML = `<div>当前：<strong>${escapeHtml(state.currentScheme)}</strong></div><div>时序行数：${timeSeriesCount}</div><div>设备条目：${deviceSpecs.reduce((sum, [key]) => sum + (state.payload[key] || []).length, 0)}</div>`;
  const localMessages = validateLocal();
  list.innerHTML = localMessages.map((item) => `<div class="validation-item ${item.level}">${escapeHtml(item.message)}</div>`).join("");
}

function validateLocal() {
  const messages = [...(state.payload.validation || []), ...collectSaveWarnings()];
  if (messages.some((item) => item.level === "error")) {
    return messages;
  }
  return messages.length ? messages : [{ level: "ok", message: "当前数据通过基础校验" }];
}

function collectSaveWarnings() {
  if (!state.payload) return [];
  const messages = [];
  if (!isTimeSeriesLoaded()) {
    if (Number(state.payload.time_series_count || 0) !== 8760) {
      messages.push({ level: "error", message: `时序数据行数应为8760，当前为${state.payload.time_series_count || 0}` });
    }
  } else if ((state.payload.time_series || []).length !== 8760) {
    messages.push({ level: "error", message: `时序数据行数应为8760，当前为${(state.payload.time_series || []).length}` });
  }
  deviceSpecs.forEach(([key, title]) => {
    (state.payload[key] || []).forEach((row, index) => {
      const rowLabel = `${title}第${index + 1}行`;
      deviceFieldsForKey(key).forEach((field) => {
        const rule = deviceFieldRules[field];
        if (rule && !validateDeviceFieldValue(row[field], rule)) {
          messages.push({ level: "error", message: `${rowLabel}${rule.message}` });
        }
      });
      if (validateDeviceFieldValue(row.quantity_lower, deviceFieldRules.quantity_lower) && validateDeviceFieldValue(row.quantity_upper, deviceFieldRules.quantity_upper) && Number(row.quantity_upper) < Number(row.quantity_lower)) {
        messages.push({ level: "error", message: `${title}第${index + 1}行数量上限不能小于数量下限` });
      }
      if ((key === "storage_battery_packs" || key === "hydrogen_tanks") && validateDeviceFieldValue(row.soc_upper, deviceFieldRules.soc_upper) && validateDeviceFieldValue(row.soc_lower, deviceFieldRules.soc_lower) && Number(row.soc_upper) < Number(row.soc_lower)) {
        messages.push({ level: "error", message: `${title}第${index + 1}行SOC上限不能小于SOC下限` });
      }
    });
  });
  messages.push(...collectDuplicateNumericDeviceWarnings());
  messages.push(...collectPlanningParameterWarnings());
  return messages;
}

function collectDuplicateNumericDeviceWarnings() {
  if (!state.payload) return [];
  const messages = [];
  deviceSpecs.forEach(([key, title, fields]) => {
    const rows = state.payload[key] || [];
    const numericFields = fields.filter((field) => field !== "name");
    if (numericFields.length === 0 || rows.length < 2) return;
    const seen = new Map();
    rows.forEach((row, index) => {
      const signature = numericFields.map((field) => normalizeDeviceNumericSignatureValue(row[field])).join("|");
      const firstIndex = seen.get(signature);
      if (firstIndex !== undefined) {
        messages.push({
          level: "warning",
          message: `${title}第${firstIndex + 1}行与第${index + 1}行从第2列起所有数值相同，请确认是否为重复设备参数`,
        });
        return;
      }
      seen.set(signature, index);
    });
  });
  return messages;
}

function normalizeDeviceNumericSignatureValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "").trim();
  return String(number);
}

function collectPlanningParameterWarnings() {
  if (!state.payload) return [];
  const row = planningParameterRow();
  const messages = [];
  planningParameterSpecs.forEach(([key, label, type, options]) => {
    if (type === "boolean") return;
    if (type === "select") {
      const allowedValues = new Set((options.options || []).map(([value]) => String(value)));
      if (!allowedValues.has(String(row[key] ?? ""))) {
        messages.push({ level: "error", message: `${label}选项无效` });
      }
      return;
    }
    const value = Number(row[key]);
    if (!Number.isFinite(value)) {
      messages.push({ level: "error", message: `${label}必须为数值` });
      return;
    }
    if (options.integer && !Number.isInteger(value)) {
      messages.push({ level: "error", message: options.integerMessage || `${label}必须为整数` });
    }
    if (options.positive && value <= 0) {
      messages.push({ level: "error", message: `${label}必须大于0` });
    }
    if (options.min !== undefined && value < options.min) {
      messages.push({ level: "error", message: `${label}不能小于${options.min}` });
    }
    if (options.max !== undefined && value > options.max) {
      messages.push({ level: "error", message: `${label}不能大于${options.max}` });
    }
  });
  messages.push(...collectStorageInitialSocWarning(row));
  messages.push(...collectHydrogenInitialSocWarning(row));
  const nominalFrequency = Number(row.nominal_frequency_hz);
  const nadirLower = Number(row.frequency_nadir_lower_hz);
  const peakUpper = Number(row.frequency_peak_upper_hz);
  if (Number.isFinite(nominalFrequency) && Number.isFinite(nadirLower) && nadirLower > nominalFrequency) {
    messages.push({ level: "error", message: "频率最低点下限(Hz)不能大于额定频率(Hz)" });
  }
  if (Number.isFinite(nominalFrequency) && Number.isFinite(peakUpper) && peakUpper < nominalFrequency) {
    messages.push({ level: "error", message: "频率最高点上限(Hz)不能小于额定频率(Hz)" });
  }
  const steadyUpper = Number(row.steady_state_frequency_upper_hz);
  const steadyLower = Number(row.steady_state_frequency_lower_hz);
  if (Number.isFinite(nominalFrequency) && Number.isFinite(steadyLower) && steadyLower > nominalFrequency) {
    messages.push({ level: "error", message: "稳态频率下限(Hz)不能大于额定频率(Hz)" });
  }
  if (Number.isFinite(nominalFrequency) && Number.isFinite(steadyUpper) && steadyUpper < nominalFrequency) {
    messages.push({ level: "error", message: "稳态频率上限(Hz)不能小于额定频率(Hz)" });
  }
  if (Number.isFinite(steadyUpper) && Number.isFinite(steadyLower) && steadyUpper < steadyLower) {
    messages.push({ level: "error", message: "稳态频率上限(Hz)不能小于稳态频率下限(Hz)" });
  }
  messages.push(...collectWinterDateWarnings(row));
  return messages;
}

function collectWinterDateWarnings(row) {
  const messages = [];
  const startMonth = Number(row.winter_start_month);
  const startDay = Number(row.winter_start_day);
  const endMonth = Number(row.winter_end_month);
  const endDay = Number(row.winter_end_day);
  [
    [startMonth, startDay, "冬季开始日期"],
    [endMonth, endDay, "冬季结束日期"],
  ].forEach(([month, day, label]) => {
    if (!Number.isInteger(month) || !Number.isInteger(day) || month < 1 || month > 12 || day < 1 || day > 31) return;
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
    if (day > monthDays) {
      messages.push({ level: "error", message: `${label}不能超过${month}月${monthDays}日` });
    }
  });
  return messages;
}

function collectStorageInitialSocWarning(row) {
  const initialSoc = Number(row.initial_storage_soc_ratio);
  if (!Number.isFinite(initialSoc)) return [];
  const window = activeStorageBatterySocWindow();
  if (!window) return [];
  if (window.lower > window.upper) {
    return [{ level: "error", message: "储能电池组SOC范围不存在公共区间，初始电储SOC无法同时满足所有储能电池组" }];
  }
  if (initialSoc < window.lower || initialSoc > window.upper) {
    return [{
      level: "error",
      message: `初始电储SOC(0.0-1.0)必须位于储能电池组SOC范围${formatSocRatio(window.lower)}-${formatSocRatio(window.upper)}内`,
    }];
  }
  return [];
}

function collectHydrogenInitialSocWarning(row) {
  const initialSoc = Number(row.initial_hydrogen_storage_ratio);
  if (!Number.isFinite(initialSoc)) return [];
  const window = activeHydrogenTankSocWindow();
  if (!window) return [];
  if (window.lower > window.upper) {
    return [{ level: "error", message: "储氢罐SOC范围不存在公共区间，初始氢储SOC无法同时满足所有储氢罐" }];
  }
  if (initialSoc < window.lower || initialSoc > window.upper) {
    return [{
      level: "error",
      message: `初始氢储SOC(0.0-1.0)必须位于储氢罐SOC范围${formatSocRatio(window.lower)}-${formatSocRatio(window.upper)}内`,
    }];
  }
  return [];
}

function activeStorageBatterySocWindow() {
  return activeDeviceSocWindow({
    rows: state.payload?.storage_battery_packs || [],
    capacityField: "battery_capacity",
  });
}

function activeHydrogenTankSocWindow() {
  return activeDeviceSocWindow({
    rows: state.payload?.hydrogen_tanks || [],
    capacityField: "hydrogen_tank_capacity",
  });
}

function activeDeviceSocWindow({ rows, capacityField }) {
  if (!state.payload) return null;
  let lower = null;
  let upper = null;
  rows.forEach((row) => {
    if (!validateDeviceFieldValue(row[capacityField], deviceFieldRules[capacityField])
      || !validateDeviceFieldValue(row.quantity_upper, deviceFieldRules.quantity_upper)
      || !validateDeviceFieldValue(row.soc_upper, deviceFieldRules.soc_upper)
      || !validateDeviceFieldValue(row.soc_lower, deviceFieldRules.soc_lower)) {
      return;
    }
    if (Number(row[capacityField]) <= 0 || Number(row.quantity_upper) <= 0) {
      return;
    }
    const rowLower = Number(row.soc_lower);
    const rowUpper = Number(row.soc_upper);
    if (rowUpper < rowLower) {
      return;
    }
    lower = lower === null ? rowLower : Math.max(lower, rowLower);
    upper = upper === null ? rowUpper : Math.min(upper, rowUpper);
  });
  return lower === null || upper === null ? null : { lower, upper };
}

function formatSocRatio(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(4).replace(/\.?0+$/, "");
}

function deviceFieldsForKey(key) {
  const spec = deviceSpecs.find((item) => item[0] === key);
  return spec ? spec[2] : [];
}

function validateDeviceFieldValue(value, rule) {
  if (!rule) return true;
  if (value === "" || value === null || value === undefined) return false;
  const text = String(value).trim();
  if (text === "") return false;
  const number = Number(text);
  if (!Number.isFinite(number)) return false;
  if (rule.integer && (!/^\d+$/.test(text) || !Number.isInteger(number))) return false;
  if (rule.positive && number <= 0) return false;
  if (rule.nonNegative && number < 0) return false;
  if (rule.min !== undefined && number < rule.min) return false;
  if (rule.max !== undefined && number > rule.max) return false;
  return true;
}

function coerceInput(value) {
  const text = String(value);
  if (text.trim() === "") return "";
  const number = Number(text);
  return Number.isFinite(number) ? number : text;
}

function normalizeSchemeName(name) {
  return String(name || "").replace(/[\s\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\ufeff]/g, "");
}

function schemeNameExists(name, excludedName = "") {
  const cleanName = normalizeSchemeName(name);
  const cleanExcludedName = normalizeSchemeName(excludedName);
  return state.schemes.some((scheme) => normalizeSchemeName(scheme.name) === cleanName && normalizeSchemeName(scheme.name) !== cleanExcludedName);
}

function schemeItemByName(name) {
  const cleanName = normalizeSchemeName(name);
  return state.schemes.find((scheme) => normalizeSchemeName(scheme.name) === cleanName) || null;
}

function currentSchemeItem() {
  return schemeItemByName(state.currentScheme);
}

function currentSchemeCanManage() {
  const item = currentSchemeItem();
  return Boolean(state.currentScheme && (!item || item.can_manage !== false));
}

function syncSchemeActionState() {
  const hasScheme = Boolean(state.currentScheme);
  const canManage = currentSchemeCanManage();
  const states = {
    copyScheme: !hasScheme,
    exportScheme: !hasScheme,
    deleteScheme: !hasScheme || !canManage,
    renameScheme: !hasScheme || !canManage,
    saveScheme: !hasScheme || !canManage,
    shareScheme: !hasScheme || !canManage,
  };
  Object.entries(states).forEach(([id, disabled]) => {
    const button = document.getElementById(id);
    if (button) button.disabled = disabled;
  });
}

function normalizePayload(payload) {
  if (!payload) return payload;
  payload.timeSeriesLoaded = Boolean(payload.time_series_loaded || payload.timeSeriesLoaded || payload.time_series);
  if (Array.isArray(payload.time_series)) {
    payload.time_series = normalizeTimeSeriesRows(payload.time_series);
  }
  if (payload.time_series && payload.time_series_count === undefined) {
    payload.time_series_count = payload.time_series.length;
  }
  if (!Array.isArray(payload.planning_parameters)) {
    payload.planning_parameters = payload.planning_parameters ? [payload.planning_parameters] : [defaultPlanningParameterRow()];
  }
  payload.planning_parameters[0] = normalizePlanningParameterRow(payload.planning_parameters[0]);
  return payload;
}

function normalizeTimeSeriesRows(rows) {
  return Array.isArray(rows) ? rows.map((row) => normalizeTimeSeriesRow(row)) : [];
}

function normalizeTimeSeriesRow(row) {
  if (!row || typeof row !== "object") return row;
  const next = { ...row };
  timeSeriesValueKeys.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(next, key)) {
      next[key] = normalizeTimeSeriesCellValue(key, next[key]);
    }
  });
  return next;
}

function normalizeTimeSeriesCellValue(key, value) {
  if (!timeSeriesValueKeys.has(key)) return coerceInput(value);
  const text = String(value ?? "");
  if (text.trim() === "") return "";
  const number = Number(text);
  return Number.isFinite(number) ? roundTimeSeriesValue(number) : text;
}

function formatTimeSeriesCellValue(key, value) {
  if (!timeSeriesValueKeys.has(key)) return value ?? "";
  const text = String(value ?? "");
  if (text.trim() === "") return "";
  const number = Number(text);
  return Number.isFinite(number) ? roundTimeSeriesValue(number).toFixed(3) : text;
}

function roundTimeSeriesValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number * 1000) / 1000 : value;
}

function isTimeSeriesLoaded() {
  return Boolean(state.payload && state.payload.timeSeriesLoaded);
}

function setTimeSeriesLoaded(value) {
  if (!state.payload) return;
  state.payload.timeSeriesLoaded = value;
  state.payload.time_series_loaded = value;
}

function markTimeSeriesDirty() {
  setTimeSeriesLoaded(true);
  state.timeSeriesDirty = true;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
}

function showError(error) {
  alert(error.message || String(error));
  return null;
}
