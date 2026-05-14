(() => {
  const STORAGE_KEY = "powerPlanLanguage";
  const LANGUAGES = [
    { code: "zh", label: "中文" },
    { code: "en", label: "English" },
  ];

  const dictionary = {
    "考察站风-光-氢-储-柴联合规划系统": "Station Wind-Solar-Hydrogen-Storage-Diesel Planning System",
    "系统首页": "Home",
    "参数维护": "Parameters",
    "规划求解": "Planning Solver",
    "方案评估": "Scenario Evaluation",
    "结果对比": "Result Comparison",
    "用户管理": "User Management",
    "结果比对": "Result Comparison",
    "当前用户:": "Current user:",
    "退出": "Logout",
    "管理员": "Admin",
    "普通用户": "User",
    "用户登录": "User Login",
    "用户注册": "User Registration",
    "用户名": "Username",
    "密码": "Password",
    "登录": "Login",
    "注册新用户": "Register",
    "注册并登录": "Register and Login",
    "返回登录": "Back to Login",
    "处理中...": "Processing...",
    "请求失败": "Request failed",
    "方案列表": "Scenario List",
    "当前方案:": "Current Scenario:",
    "未选择方案": "No scenario selected",
    "当前方案: 未选择方案": "Current Scenario: No scenario selected",
    "时序数据": "Time Series",
    "设备参数": "Device Parameters",
    "规划参数": "Planning Parameters",
    "方案概览": "Scenario Overview",
    "新建方案": "New Scenario",
    "复制方案": "Copy Scenario",
    "修改名称": "Rename",
    "保存方案": "Save Scenario",
    "删除方案": "Delete Scenario",
    "导入曲线": "Import Curves",
    "负荷生成": "Generate Load",
    "坐标选择": "Select Coordinates",
    "纬度": "Latitude",
    "经度": "Longitude",
    "历史数据年": "Historical Year",
    "获取历史气象": "Fetch Weather History",
    "风速": "Wind Speed",
    "太阳辐射": "Solar Irradiance",
    "环境温度": "Ambient Temperature",
    "负荷总功率": "Total Load Power",
    "启动优化": "Start Optimization",
    "启动评估": "Start Evaluation",
    "停止优化": "Stop Optimization",
    "停止评估": "Stop Evaluation",
    "运行日志": "Run Log",
    "评估日志": "Evaluation Log",
    "曲线展示": "Curves",
    "结果概览": "Result Overview",
    "供能分析": "Energy Analysis",
    "安全评估": "Safety Assessment",
    "评估概览": "Evaluation Overview",
    "经济性评估": "Economic Assessment",
    "当前状态": "Status",
    "启动时刻": "Start Time",
    "结束时刻": "End Time",
    "总成本": "Total Cost",
    "绿色电量占比": "Green Energy Ratio",
    "综合评分": "Score",
    "风险等级": "Risk Level",
    "当前规划结果": "Current Planning Result",
    "删除结果": "Delete Result",
    "复制结果": "Copy Result",
    "保存结果": "Save Result",
    "暂无结果文件": "No result files",
    "暂无可读取结果文件": "No readable result files",
    "无法读取": "Unreadable",
    "结果文件": "Result file",
    "结果文件无法读取，可能已损坏或格式不正确": "Result file cannot be read. It may be damaged or in an invalid format.",
    "无法读取，请重新生成或删除该文件。": "Cannot be read. Please regenerate or delete this file.",
    "设备类型": "Device Type",
    "设计台数": "Designed Units",
    "单台容量": "Single Unit Capacity",
    "暂无规划结果": "No planning result",
    "设计台数必须为非负整数": "Designed units must be a non-negative integer",
    "请先选择结果文件": "Please select a result file first",
    "请先选择方案": "Please select a scenario first",
    "请输入新结果名称": "Enter a new result name",
    "复制失败": "Copy failed",
    "结果文件已删除": "Result file deleted",
    "结果文件已复制：": "Result file copied: ",
    "结果文件已保存：": "Result file saved: ",
    "小时级曲线": "Hourly Curves",
    "日级统计": "Daily Statistics",
    "月度统计": "Monthly Statistics",
    "年度统计": "Annual Statistics",
    "暂无小时级曲线": "No hourly curves",
    "请选择小时级曲线": "Please select hourly curves",
    "正在加载小时级曲线": "Loading hourly curves",
    "年度统计以表格显示": "Annual statistics are shown as a table",
    "暂无年度统计": "No annual statistics",
    "规划容量对比": "Planning Capacity Comparison",
    "供能指标对比": "Energy Indicator Comparison",
    "安全指标对比": "Safety Indicator Comparison",
    "添加对比": "Add Comparison",
    "对比": "Comparison",
    "方案列表": "Scenario List",
    "结果列表": "Result List",
    "暂无方案": "No scenarios",
    "暂无结果": "No results",
    "暂无规划容量对比": "No planning capacity comparison",
    "暂无供能指标对比": "No energy indicator comparison",
    "暂无安全指标对比": "No safety indicator comparison",
    "平均": "Avg",
    "最大": "Max",
    "最小": "Min",
    "合计": "Total",
    "指标": "Metric",
    "数值": "Value",
    "单位": "Unit",
    "风机总功率": "Total Wind Power",
    "光伏总功率": "Total PV Power",
    "柴发总功率": "Total Diesel Power",
    "电储能总功率": "Total Battery Power",
    "电储电量": "Battery Energy",
    "电制氢总功率": "Total Electrolyzer Power",
    "储氢罐氢储量": "Hydrogen Storage",
    "燃料电池总功率": "Total Fuel Cell Power",
    "风力最大可发": "Wind Available Power",
    "光伏最大可发": "PV Available Power",
    "新能源最大可发": "Renewable Available Power",
    "弃风总功率": "Curtailed Wind Power",
    "弃光总功率": "Curtailed PV Power",
    "新能源弃电总功率": "Renewable Curtailment Power",
    "切负荷功率": "Unserved Load Power",
    "负荷总电量": "Total Load Energy",
    "柴发总发电量": "Total Diesel Generation",
    "风机总发电量": "Total Wind Generation",
    "光伏总发电量": "Total PV Generation",
    "电储能总储电量": "Battery Charge Energy",
    "电储能总放电量": "Battery Discharge Energy",
    "电制氢总用电量": "Electrolyzer Energy Use",
    "氢储总增加量": "Hydrogen Storage Increase",
    "氢储总消耗量": "Hydrogen Storage Consumption",
    "燃料电池总发电量": "Fuel Cell Generation",
    "风力最大可发电量": "Available Wind Energy",
    "光伏最大可发电量": "Available PV Energy",
    "新能源最大可发电量": "Available Renewable Energy",
    "新能源实发电量": "Actual Renewable Energy",
    "弃风总电量": "Curtailed Wind Energy",
    "弃光总电量": "Curtailed PV Energy",
    "新能源总弃电量": "Total Renewable Curtailment",
    "切负荷总电量": "Unserved Load Energy",
    "新能源占比": "Renewable Share",
    "新能源弃电率": "Renewable Curtailment Rate",
    "请求后台失败，请检查 WEB 服务是否正常运行，或查看服务器错误日志。": "Failed to reach the backend. Please check whether the WEB service is running or review the server error log.",
    "后台处理失败:": "Backend processing failed:",
  };

  const translations = new Map(Object.entries(dictionary).map(([zh, en]) => [normalizeText(zh), en]));
  const reverseTranslations = new Map(Object.entries(dictionary).map(([zh, en]) => [normalizeText(en), zh]));
  const ignoredTags = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "SVG", "CANVAS"]);
  let observer = null;
  let translating = false;
  let dialogsPatched = false;

  function currentLanguage() {
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh";
  }

  function setLanguage(language) {
    const next = language === "en" ? "en" : "zh";
    localStorage.setItem(STORAGE_KEY, next);
    document.documentElement.lang = next === "en" ? "en" : "zh-CN";
    updateLanguageControl(next);
    translateDocument(next);
  }

  function boot() {
    insertLanguageControl();
    patchDialogs();
    setLanguage(currentLanguage());
    observer = new MutationObserver(() => {
      if (translating) return;
      translateDocument(currentLanguage());
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function insertLanguageControl() {
    if (document.getElementById("languageSelect")) return;
    const wrap = document.createElement("label");
    wrap.className = "language-switch";
    wrap.innerHTML = `<span>语言</span><select id="languageSelect" aria-label="语言 / Language">${LANGUAGES.map((item) => `<option value="${item.code}">${item.label}</option>`).join("")}</select>`;
    const target = document.querySelector(".topbar .user-status") || document.querySelector(".home-user-status") || document.querySelector(".auth-card");
    if (target?.classList.contains("auth-card")) {
      target.insertBefore(wrap, target.firstElementChild);
    } else if (target) {
      target.parentNode.insertBefore(wrap, target);
    } else {
      document.body.insertBefore(wrap, document.body.firstChild);
    }
    wrap.querySelector("select").addEventListener("change", (event) => setLanguage(event.target.value));
  }

  function updateLanguageControl(language) {
    const select = document.getElementById("languageSelect");
    if (select) select.value = language;
  }

  function translateDocument(language) {
    translating = true;
    try {
      translateTextNodes(document.body, language);
      translateAttributes(document.body, language);
    } finally {
      translating = false;
    }
  }

  function translateTextNodes(root, language) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (isIgnored(node.parentElement)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      node.nodeValue = translateText(node.nodeValue, language);
    });
  }

  function translateAttributes(root, language) {
    root.querySelectorAll("[aria-label], [placeholder], [title]").forEach((element) => {
      ["aria-label", "placeholder", "title"].forEach((name) => {
        if (element.hasAttribute(name)) element.setAttribute(name, translateText(element.getAttribute(name), language));
      });
    });
  }

  function translateText(text, language) {
    const raw = String(text ?? "");
    const trimmed = raw.trim();
    if (!trimmed) return raw;
    const leading = raw.match(/^\s*/)?.[0] || "";
    const trailing = raw.match(/\s*$/)?.[0] || "";
    const normalized = normalizeText(trimmed);
    const translated = language === "en" ? translateToEnglish(normalized) : translateToChinese(normalized);
    return translated === normalized ? raw : `${leading}${translated}${trailing}`;
  }

  function translateToEnglish(text) {
    if (translations.has(text)) return translations.get(text);
    for (const [zh, en] of translations.entries()) {
      if (text.includes(zh)) return text.replaceAll(zh, en);
    }
    return text;
  }

  function translateToChinese(text) {
    if (reverseTranslations.has(text)) return reverseTranslations.get(text);
    for (const [en, zh] of reverseTranslations.entries()) {
      if (text.includes(en)) return text.replaceAll(en, zh);
    }
    return text;
  }

  function patchDialogs() {
    if (dialogsPatched) return;
    dialogsPatched = true;
    const nativeAlert = window.alert.bind(window);
    const nativeConfirm = window.confirm.bind(window);
    const nativePrompt = window.prompt.bind(window);
    window.alert = (message) => nativeAlert(translateText(message, currentLanguage()));
    window.confirm = (message) => nativeConfirm(translateText(message, currentLanguage()));
    window.prompt = (message, defaultValue) => nativePrompt(translateText(message, currentLanguage()), defaultValue);
  }

  function normalizeText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  function isIgnored(element) {
    return !element || ignoredTags.has(element.tagName) || element.closest("[data-i18n-ignore]");
  }

  window.PowerPlanI18n = { setLanguage, currentLanguage, translate: translateText };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
