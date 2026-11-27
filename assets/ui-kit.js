(() => {
  const THEME_STORAGE_KEY = "powerPlanTheme";
  const LEGACY_THEME_STORAGE_KEY = "powerPlanHomeTheme";
  const DEFAULT_THEME = "precision-dark";

  const THEMES = [
    { id: "precision-dark", label: "极光幻境", dark: true },
    { id: "sci-fi-cyan", label: "星海冰青", dark: true },
    { id: "scada-cobalt", label: "深海钴蓝", dark: true },
    { id: "sci-fi-purple", label: "紫霞星云", dark: true },
    { id: "sci-fi-matrix", label: "翠雾极光", dark: true },
    { id: "scada-amber", label: "琥珀鎏金", dark: true },
    { id: "scada-crimson", label: "赤霞星辰", dark: true },
    { id: "minimalist-light", label: "冰川月白", dark: false },
    { id: "arctic-jade", label: "青瓷雪雾", dark: false },
    { id: "warm-ivory", label: "晨曦暖玉", dark: false },
  ];

  /** 全站统一高可读线性微发光 SVG 图标库（16×16/24×24 圆润线条） */
  const UI_ICONS = {
    home: '<path d="M3 10.5L12 3l9 7.5"/><path d="M5.5 9.5V20h13V9.5"/><path d="M9.5 20v-5.5h5V20"/>',
    screen: '<rect x="2.5" y="3.5" width="19" height="13" rx="3"/><path d="M8 20.5h8"/><path d="M12 16.5v4"/><path d="M6.5 11.5l3-3 2.5 2.2 4.5-4.2"/>',
    sliders: '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2.5"/><path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/><path d="M10 12h4"/>',
    chart: '<path d="M4 19.5h16"/><rect x="6" y="11" width="3" height="6" rx="1"/><rect x="10.5" y="7" width="3" height="10" rx="1"/><rect x="15" y="4.5" width="3" height="12.5" rx="1"/>',
    shield: '<path d="M12 3l7 3v5.5c0 4.6-3 8.1-7 9.5-4-1.4-7-4.9-7-9.5V6l7-3z"/><path d="M9.2 12.2l2 2 3.8-4"/>',
    wave: '<path d="M2.5 12h3.2l2.3-6 3.2 12 2.6-8 1.9 2h5.8"/>',
    compare: '<rect x="3" y="4" width="7.5" height="16" rx="2"/><rect x="13.5" y="4" width="7.5" height="16" rx="2"/><path d="M6.5 9h1M6.5 13h1M17 9h1M17 13h1"/>',
    sweep: '<path d="M4 17c2.5-6 6-10 16-11"/><path d="M4 12c3-3 7-5 16-5.5"/><circle cx="10" cy="10.2" r="2"/><circle cx="16.5" cy="6.5" r="2"/>',
    report: '<path d="M6.5 3.5h8L19 8v12.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 20.5V5a1.5 1.5 0 0 1 1.5-1.5z"/><path d="M14 3.5V8.5h5"/><path d="M8.5 12.5h7M8.5 16h5"/>',
    tasks: '<rect x="4" y="4" width="16" height="4.5" rx="1.5"/><rect x="4" y="10" width="16" height="4.5" rx="1.5"/><rect x="4" y="16" width="10" height="4.5" rx="1.5"/><circle cx="18" cy="18.2" r="2"/>',
    users: '<circle cx="9.5" cy="8" r="3"/><path d="M3.5 19c0-3 2.7-5 6-5s6 2 6 5"/><circle cx="16.8" cy="9" r="2.2"/><path d="M16.5 14.3c2.2.4 4 1.9 4 4.2"/>',
    topology: '<circle cx="5.5" cy="6" r="2.3"/><circle cx="18.5" cy="6" r="2.3"/><circle cx="12" cy="18" r="2.5"/><path d="M7.8 6h8.4M6.8 8l4 7.8M17.2 8l-4 7.8"/>',
    play: '<polygon points="6.5,4.5 19.5,12 6.5,19.5"/>',
    pause: '<rect x="6" y="4.5" width="4" height="15" rx="1.2"/><rect x="14" y="4.5" width="4" height="15" rx="1.2"/>',
    queue: '<path d="M4 6.5h11M4 12h11M4 17.5h7"/><path d="M17.5 13v6M14.5 16h6"/>',
    stop: '<rect x="5.5" y="5.5" width="13" height="13" rx="2.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M5.5 15.5H5a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 5 3.5h9A1.5 1.5 0 0 1 15.5 5v.5"/>',
    edit: '<path d="M4 20h4l10.5-10.5a2 2 0 0 0-2.8-2.8L5.2 17.2 4 20z"/>',
    save: '<path d="M5 4h11l3 3v12.5a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 19.5v-14A1.5 1.5 0 0 1 5 4z"/><path d="M8 4v5h7V4"/><rect x="8" y="13.5" width="8" height="7" rx="1"/>',
    trash: '<path d="M4 6.5h16"/><path d="M9.5 3.5h5"/><path d="M6.5 6.5l1 13a1.5 1.5 0 0 0 1.5 1.5h6a1.5 1.5 0 0 0 1.5-1.5l1-13"/><path d="M10 10.5v6M14 10.5v6"/>',
    upload: '<path d="M12 15.5V4.5"/><path d="M7.5 9L12 4.5 16.5 9"/><path d="M4 16.5v2A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5v-2"/>',
    download: '<path d="M12 4.5v11"/><path d="M7.5 11.5L12 16l4.5-4.5"/><path d="M4 16.5v2A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5v-2"/>',
    share: '<circle cx="18" cy="5.5" r="2.3"/><circle cx="6" cy="12" r="2.3"/><circle cx="18" cy="18.5" r="2.3"/><path d="M8.1 10.9l7.8-4.3M8.1 13.1l7.8 4.3"/>',
    refresh: '<path d="M20 6v5h-5"/><path d="M19.2 14.5A7.5 7.5 0 1 1 17.6 6.8L20 11"/>',
    reset: '<path d="M4 7v5h5"/><path d="M5 12a7.2 7.2 0 1 0 2.1-5.1L4 12"/>',
    sparkles: '<path d="M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3z"/><path d="M18.5 16l.8 2.2L21.5 19l-2.2.8-.8 2.2-.8-2.2L15.5 19l2.2-.8.8-2.2z"/>',
    thermometer: '<path d="M14 14.5V5a2 2 0 0 0-4 0v9.5a3.5 3.5 0 1 0 4 0z"/><path d="M12 11v4.5"/>',
    snowflake: '<path d="M12 2.5v19M3.8 7.2l16.4 9.6M20.2 7.2L3.8 16.8"/><path d="M9.5 4.5L12 6.8l2.5-2.3M9.5 19.5L12 17.2l2.5 2.3"/>',
    wind: '<path d="M3 8.5h11.5a2.5 2.5 0 1 0-2.5-2.5"/><path d="M3 13h15a2.5 2.5 0 1 1-2.5 2.5"/><path d="M3 17.5h8.5a2 2 0 1 1-2 2"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M18.7 5.3l-1.8 1.8M7.1 16.9l-1.8 1.8"/>',
    moon: '<path d="M19.5 14.8A7.8 7.8 0 0 1 9.2 4.5a7.8 7.8 0 1 0 10.3 10.3z"/>',
    storm: '<path d="M6.5 16.5H18a3.5 3.5 0 0 0 .5-6.9A5.2 5.2 0 0 0 8.2 8 3.8 3.8 0 0 0 6.5 16.5z"/><path d="M12.5 13l-2 4.5h3l-1.5 4"/>',
    snowcloud: '<path d="M6.5 15H18a3.5 3.5 0 0 0 .5-6.9A5.2 5.2 0 0 0 8.2 6.5 3.8 3.8 0 0 0 6.5 15z"/><path d="M8.5 18.5h.01M12 19.5h.01M15.5 18.5h.01"/>',
    battery: '<rect x="3" y="7" width="16" height="10" rx="2.2"/><path d="M21 10.5v3"/><path d="M7 10.5v3M10.5 10.5v3"/>',
    flame: '<path d="M12.5 3.2c.4 3.4-2.8 4.8-2.8 8.3a3.8 3.8 0 0 0 7.6 0c0-3.2-2.2-5.4-4.8-8.3z"/><path d="M12 14.5a1.8 1.8 0 0 1 1.8 1.8"/>',
    bolt: '<path d="M13 2.5L5.5 13h5.5l-1 8.5L18.5 11H13l0-8.5z"/>',
    leaf: '<path d="M5 19C5 10.5 10.5 5 19.5 4.5c-.5 9-6 14.5-14.5 14.5z"/><path d="M5 19l8.5-8.5"/>',
    coin: '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.5h5M9.5 13h5M12 7.5v9"/>',
    check: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.8-4.8"/>',
    alert: '<path d="M12 3.5L21 19.5H3L12 3.5z"/><path d="M12 9.5v4.5"/><path d="M12 17h.01"/>',
    logs: '<path d="M5 6h14M5 11h10M5 16h14"/><circle cx="18.5" cy="11" r="1.5"/>',
    expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20 20"/>',
    compass: '<circle cx="12" cy="12" r="8.5"/><polygon points="15.5,8.5 13.4,13.4 8.5,15.5 10.6,10.6"/>',
  };

  function renderIcon(name, extraClass = "") {
    const body = UI_ICONS[name];
    if (!body) return "";
    const cls = extraClass ? `ui-ico ${extraClass}` : "ui-ico";
    return `<span class="${cls}" aria-hidden="true"><svg viewBox="0 0 24 24">${body}</svg></span>`;
  }

  const PAGE_ICON_MAP = {
    "index.html": "home",
    "scada.html": "screen",
    "planning.html": "sliders",
    "optimize.html": "cpu",
    "evaluation.html": "chart",
    "reliability.html": "shield",
    "frequency.html": "wave",
    "comparison.html": "compare",
    "sensitivity.html": "sweep",
    "report.html": "report",
    "tasks.html": "tasks",
    "users.html": "users",
  };

  const LEGACY_THEME_MAP = {
    bright: "minimalist-light",
    minimal: "minimalist-light",
    flat: "minimalist-light",
    illustration: "minimalist-light",
    material: "minimalist-light",
    magazine: "minimalist-light",
    "sci-fi": "sci-fi-cyan",
    "neon-future": "sci-fi-purple",
    fresh: "sci-fi-matrix",
    dark: "precision-dark",
    default: "precision-dark",
    solemn: "precision-dark",
    glassmorphism: "precision-dark",
    dynamic: "sci-fi-cyan",
  };

  const LIGHT_CHART_COLORS = [
    "#2563EB", // 钴蓝
    "#D97706", // 琥珀橙
    "#0D9488", // 青绿
    "#DC2626", // 绯红
    "#7C3AED", // 紫罗兰
    "#64748B", // 石板灰
    "#0284C7", // 天青
    "#EA580C", // 炽橙
  ];

  const DARK_CHART_COLORS = [
    "#38BDF8", // 天蓝
    "#FBBF24", // 暖金
    "#34D399", // 翠绿
    "#FB7185", // 玫瑰红
    "#A78BFA", // 淡紫
    "#94A3B8", // 浅灰
    "#2DD4BF", // 碧青
    "#FB923C", // 暖橙
  ];

  /** 翻译辅助函数，优先使用全局 PowerPlanI18n */
  function tr(text) {
    if (window.PowerPlanI18n && typeof window.PowerPlanI18n.translate === "function") {
      return window.PowerPlanI18n.translate(text, window.PowerPlanI18n.currentLanguage());
    }
    return String(text ?? "");
  }

  /** 归一化主题名称，兼容旧版 powerPlanHomeTheme 存储 */
  function normalizeTheme(value) {
    const raw = String(value || "").trim();
    if (THEMES.some((item) => item.id === raw)) return raw;
    if (LEGACY_THEME_MAP[raw]) return LEGACY_THEME_MAP[raw];
    return DEFAULT_THEME;
  }

  /** 读取当前持久化主题 */
  function getTheme() {
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      if (saved) return normalizeTheme(saved);
      const legacy = localStorage.getItem(LEGACY_THEME_STORAGE_KEY);
      if (legacy) return normalizeTheme(legacy);
    } catch (_) {
      // 忽略本地存储受限异常
    }
    return DEFAULT_THEME;
  }

  function isDarkTheme(themeId) {
    const target = THEMES.find((item) => item.id === normalizeTheme(themeId || getTheme()));
    return target ? target.dark : true;
  }

  /** 应用主题到根元素并派发主题变更事件 */
  function setTheme(themeId, options = {}) {
    const next = normalizeTheme(themeId);
    const prev = document.documentElement.dataset.theme;
    document.documentElement.dataset.theme = next;
    document.documentElement.dataset.colorMode = isDarkTheme(next) ? "dark" : "light";
    // 清理旧版 data-home-theme，防止历史样式表干扰
    if (document.documentElement.dataset.homeTheme) {
      delete document.documentElement.dataset.homeTheme;
    }
    if (document.body && document.body.dataset.homeTheme) {
      delete document.body.dataset.homeTheme;
    }
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch (_) {
      // 忽略本地存储受限异常
    }
    const select = document.getElementById("themeSelect");
    if (select && select.value !== next) select.value = next;

    if (!options.silent && prev !== next) {
      window.dispatchEvent(
        new CustomEvent("powerplan:themechange", {
          detail: { theme: next, isDark: isDarkTheme(next) },
        }),
      );
    }
    return next;
  }

  /** 获取当前主题的图表调色板（遵循 scientific-dashboard 色盲友好规范） */
  function getChartPalette() {
    const dark = isDarkTheme();
    const styles = getComputedStyle(document.documentElement);
    const readVar = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;
    return {
      isDark: dark,
      series: dark ? DARK_CHART_COLORS.slice() : LIGHT_CHART_COLORS.slice(),
      annualBars: dark
        ? ["#38BDF8", "#34D399", "#FBBF24", "#FB7185"]
        : ["#2563EB", "#0D9488", "#D97706", "#DC2626"],
      annualLine: dark ? "#A78BFA" : "#7C3AED",
      wind: dark ? "#38BDF8" : "#2563EB",
      solar: dark ? "#FBBF24" : "#D97706",
      temperature: dark ? "#A78BFA" : "#7C3AED",
      load: dark ? "#34D399" : "#0D9488",
      diesel: dark ? "#FB7185" : "#DC2626",
      reference: dark ? "#94A3B8" : "#64748B",
      grid: readVar("--chart-grid", dark ? "rgba(255,255,255,0.07)" : "#E2E8F0"),
      axis: readVar("--chart-axis", dark ? "rgba(148,163,184,0.34)" : "#CBD5E1"),
      text: readVar("--chart-text", dark ? "#94A3B8" : "#475569"),
      crosshair: readVar("--chart-crosshair", dark ? "rgba(56,189,248,0.52)" : "rgba(37,99,235,0.45)"),
      accent: readVar("--accent", dark ? "#38BDF8" : "#2563EB"),
      ok: readVar("--ok", dark ? "#34D399" : "#0D9488"),
      warn: readVar("--warn", dark ? "#FBBF24" : "#D97706"),
      danger: readVar("--danger", dark ? "#FB7185" : "#DC2626"),
    };
  }

  /** 根据提示语内容自动推断 Toast 严重级别 */
  function inferToastLevel(message) {
    const text = String(message || "");
    if (/(失败|错误|未通过|不能|不允许|无法|为空|无效|不存在|异常|failed|error|cannot|invalid|ошибк)/i.test(text)) {
      return "error";
    }
    if (/(成功|已保存|已删除|已分享|已取消分享|已复制|已确认|完成|saved|success|deleted|успеш|сохранен)/i.test(text)) {
      return "success";
    }
    if (/(请先|警告|正在运行|没有运行|已存在|未加载|warning|please select|выберите|предупрежд)/i.test(text)) {
      return "warn";
    }
    return "info";
  }

  function ensureToastStack() {
    let stack = document.getElementById("uiToastStack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "uiToastStack";
      stack.className = "ui-toast-stack";
      stack.setAttribute("aria-live", "polite");
      stack.setAttribute("aria-atomic", "false");
      document.body.appendChild(stack);
    }
    return stack;
  }

  /** 非阻塞右上角分级 Toast 通知 */
  function toast(message, options = {}) {
    const raw = String(message ?? "").trim();
    if (!raw) return;
    const translated = tr(raw);
    const level = options.level || inferToastLevel(raw);
    const duration = Number.isFinite(options.duration) ? options.duration : level === "error" ? 6500 : 4200;
    const stack = ensureToastStack();

    // 限制同时最多展示 4 条，避免消息风暴刷屏
    while (stack.children.length >= 4) {
      stack.firstElementChild.remove();
    }

    const item = document.createElement("div");
    item.className = "ui-toast";
    item.dataset.level = level;
    item.setAttribute("role", level === "error" ? "alert" : "status");

    const body = document.createElement("div");
    body.className = "ui-toast-body";
    body.textContent = translated;

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "ui-toast-close";
    closeBtn.setAttribute("aria-label", tr("关闭"));
    closeBtn.textContent = "×";

    const dismiss = () => {
      if (item.parentNode) item.remove();
    };
    closeBtn.addEventListener("click", dismiss);

    item.append(body, closeBtn);
    stack.appendChild(item);

    if (duration > 0) {
      window.setTimeout(dismiss, duration);
    }
  }

  /** 内部统一模态对话框构建器 */
  function openModal({
    title,
    message,
    variant = "default",
    confirmText = "确定",
    cancelText = "取消",
    showCancel = true,
    inputMode = false,
    defaultValue = "",
    placeholder = "",
    allowBackdropClose = true,
  }) {
    return new Promise((resolve) => {
      const prevActive = document.activeElement;
      const backdrop = document.createElement("div");
      backdrop.className = "ui-modal-backdrop";

      const dialog = document.createElement("div");
      dialog.className = "ui-modal";
      dialog.dataset.variant = variant;
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");

      const head = document.createElement("div");
      head.className = "ui-modal-head";
      const titleEl = document.createElement("h3");
      titleEl.className = "ui-modal-title";
      titleEl.textContent = tr(title || (variant === "danger" ? "确认操作" : "提示"));
      head.appendChild(titleEl);

      const body = document.createElement("div");
      body.className = "ui-modal-body";
      if (message) {
        const msgEl = document.createElement("div");
        msgEl.textContent = tr(message);
        body.appendChild(msgEl);
      }

      let inputEl = null;
      if (inputMode) {
        inputEl = document.createElement("input");
        inputEl.type = "text";
        inputEl.className = "ui-modal-input";
        inputEl.value = String(defaultValue ?? "");
        if (placeholder) inputEl.placeholder = tr(placeholder);
        body.appendChild(inputEl);
      }

      const foot = document.createElement("div");
      foot.className = "ui-modal-foot";

      let cancelBtn = null;
      if (showCancel) {
        cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "ui-btn-cancel";
        cancelBtn.textContent = tr(cancelText);
        foot.appendChild(cancelBtn);
      }

      const confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = `ui-btn-confirm${variant === "danger" ? " is-danger" : ""}`;
      confirmBtn.textContent = tr(confirmText);
      foot.appendChild(confirmBtn);

      dialog.append(head, body, foot);
      backdrop.appendChild(dialog);
      document.body.appendChild(backdrop);

      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        document.removeEventListener("keydown", onKeyDown, true);
        backdrop.remove();
        if (prevActive && typeof prevActive.focus === "function") {
          try {
            prevActive.focus();
          } catch (_) {
            // 忽略焦点恢复失败
          }
        }
        resolve(value);
      };

      const onKeyDown = (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          finish(inputMode ? null : false);
        } else if (event.key === "Enter" && inputMode) {
          event.preventDefault();
          event.stopPropagation();
          finish(inputEl.value);
        }
      };

      document.addEventListener("keydown", onKeyDown, true);

      if (cancelBtn) {
        cancelBtn.addEventListener("click", () => finish(inputMode ? null : false));
      }
      confirmBtn.addEventListener("click", () => finish(inputMode ? inputEl.value : true));
      backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop && allowBackdropClose && variant !== "danger") {
          finish(inputMode ? null : false);
        }
      });

      // 高危确认默认聚焦取消按钮，输入框模式聚焦并全选便于直接改写
      window.requestAnimationFrame(() => {
        if (inputEl) {
          inputEl.focus();
          inputEl.select();
        } else if (variant === "danger" && cancelBtn) {
          cancelBtn.focus();
        } else {
          confirmBtn.focus();
        }
      });
    });
  }

  /** 主题化确认对话框（支持高危模式：红色确认按钮 + 默认聚焦取消 + 禁误点遮罩） */
  function confirmDialog(message, options = {}) {
    const isDanger = Boolean(options.danger);
    return openModal({
      title: options.title || (isDanger ? "确认删除 / 覆盖" : "确认操作"),
      message,
      variant: isDanger ? "danger" : options.warn ? "warn" : "default",
      confirmText: options.confirmText || (isDanger ? "确认执行" : "确定"),
      cancelText: options.cancelText || "取消",
      showCancel: true,
      allowBackdropClose: !isDanger,
    });
  }

  /** 主题化输入对话框 */
  function promptDialog(message, defaultValue = "", options = {}) {
    return openModal({
      title: options.title || "输入名称",
      message,
      confirmText: options.confirmText || "确定",
      cancelText: options.cancelText || "取消",
      showCancel: true,
      inputMode: true,
      defaultValue,
      placeholder: options.placeholder || "",
      allowBackdropClose: true,
    });
  }

  /** 在全站顶栏注入统一的主题切换器、监控大屏导航与工具容器 */
  function mountTopbarUtilities() {
    const topbar = document.querySelector(".topbar");
    if (!topbar) return;

    // 自动在全站子页主导航中注入「规划大屏」入口
    const mainNav = topbar.querySelector(".main-nav");
    if (mainNav && !mainNav.querySelector('a[href="scada.html"]')) {
      const scadaLink = document.createElement("a");
      scadaLink.href = "scada.html";
      scadaLink.textContent = "规划大屏";
      const firstLink = mainNav.querySelector('a[href="index.html"]');
      if (firstLink && firstLink.nextSibling) {
        mainNav.insertBefore(scadaLink, firstLink.nextSibling);
      } else {
        mainNav.appendChild(scadaLink);
      }
    }

    let utilities = topbar.querySelector(".topbar-utilities");
    if (!utilities) {
      utilities = document.createElement("div");
      utilities.className = "topbar-utilities";
      const userStatus = topbar.querySelector(".user-status");
      if (userStatus) {
        topbar.insertBefore(utilities, userStatus);
        utilities.appendChild(userStatus);
      } else {
        topbar.appendChild(utilities);
      }
    }

    // 整合「主题切换 + 语言切换」为 1 个超紧凑柔光图标按钮 + 琉璃浮层，释放顶栏宽度
    const THEME_SWATCHES = {
      "precision-dark": "linear-gradient(135deg,#67E8F9,#A78BFA)",
      "sci-fi-cyan": "linear-gradient(135deg,#22D3EE,#818CF8)",
      "scada-cobalt": "linear-gradient(135deg,#3B82F6,#38BDF8)",
      "sci-fi-purple": "linear-gradient(135deg,#D8B4FE,#F472B6)",
      "sci-fi-matrix": "linear-gradient(135deg,#5EEAD4,#34D399)",
      "scada-amber": "linear-gradient(135deg,#FBBF24,#FB923C)",
      "scada-crimson": "linear-gradient(135deg,#FB7185,#FDBA74)",
      "minimalist-light": "linear-gradient(135deg,#E0F2FE,#0284C7)",
      "arctic-jade": "linear-gradient(135deg,#CCFBF1,#0D9488)",
      "warm-ivory": "linear-gradient(135deg,#FEF3C7,#C2690E)",
    };
    const LANG_OPTIONS = [
      { code: "zh-CN", short: "中文", label: "中文" },
      { code: "en-US", short: "EN", label: "English" },
      { code: "ru-RU", short: "RU", label: "Русский" },
    ];

    if (!utilities.querySelector(".ui-pref-host")) {
      const prefHost = document.createElement("div");
      prefHost.className = "ui-pref-host";

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.id = "uiPrefTrigger";
      trigger.className = "ui-pref-trigger";
      trigger.setAttribute("aria-haspopup", "true");
      trigger.setAttribute("aria-expanded", "false");
      trigger.setAttribute("aria-label", tr("外观与语言"));
      trigger.innerHTML = `<svg class="topbar-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3.6 9h16.8M3.6 15h16.8M12 3a13.5 13.5 0 0 1 0 18M12 3a13.5 13.5 0 0 0 0 18"/></svg>`;

      const popover = document.createElement("div");
      popover.className = "ui-pref-popover";
      popover.setAttribute("role", "dialog");
      popover.setAttribute("aria-label", tr("外观与语言"));

      // 保留原生 select 供全站既有脚本读写与监听（视觉隐藏）
      const themeSel = document.getElementById("themeSelect") || document.createElement("select");
      themeSel.id = "themeSelect";
      themeSel.className = "ui-sr-select";
      themeSel.setAttribute("aria-label", tr("显示主题"));
      if (!themeSel.options.length) {
        themeSel.innerHTML = THEMES.map((item) => `<option value="${item.id}">${item.label}</option>`).join("");
      }
      themeSel.value = getTheme();

      const existingLangWrap = topbar.querySelector(".language-switch") || document.querySelector(".language-switch");
      let langSel = document.getElementById("languageSelect");
      if (!langSel) {
        langSel = document.createElement("select");
        langSel.id = "languageSelect";
        langSel.setAttribute("aria-label", "Language");
        langSel.innerHTML = LANG_OPTIONS.map((item) => `<option value="${item.code}">${item.label}</option>`).join("");
        langSel.value = window.PowerPlanI18n?.currentLanguage?.() || "zh-CN";
        langSel.addEventListener("change", (ev) => {
          window.PowerPlanI18n?.setLanguage?.(ev.target.value);
        });
      }
      langSel.className = "ui-sr-select";
      if (existingLangWrap) existingLangWrap.remove();

      popover.innerHTML = `
        <div class="ui-pref-section">
          <div class="ui-pref-head">${renderIcon("sparkles", "ui-ico-sm ui-ico-accent")}<span>${tr("显示主题")}</span></div>
          <div class="ui-pref-theme-grid">
            ${THEMES.map(
              (item) => `<button type="button" class="ui-pref-chip" data-pref-theme="${item.id}"><i class="ui-pref-dot" style="background:${THEME_SWATCHES[item.id] || "var(--accent)"}"></i><span>${tr(item.label)}</span></button>`,
            ).join("")}
          </div>
        </div>
        <div class="ui-pref-section">
          <div class="ui-pref-head">${renderIcon("compass", "ui-ico-sm ui-ico-aurora")}<span>${tr("语言")}</span></div>
          <div class="ui-pref-lang-row">
            ${LANG_OPTIONS.map(
              (item) => `<button type="button" class="ui-pref-lang-btn" data-pref-lang="${item.code}">${item.short}</button>`,
            ).join("")}
          </div>
        </div>
      `;
      popover.append(themeSel, langSel);
      prefHost.append(trigger, popover);

      const userStatusNode = utilities.querySelector(".user-status");
      if (userStatusNode) utilities.insertBefore(prefHost, userStatusNode);
      else utilities.appendChild(prefHost);

      const syncPrefUi = () => {
        const curTheme = getTheme();
        const curLang = window.PowerPlanI18n?.currentLanguage?.() || langSel.value || "zh-CN";
        const themeObj = THEMES.find((t) => t.id === curTheme) || THEMES[0];
        const langObj = LANG_OPTIONS.find((l) => l.code === curLang) || LANG_OPTIONS[0];
        themeSel.value = curTheme;
        langSel.value = curLang;
        trigger.setAttribute("title", `${tr(themeObj.label)} · ${langObj.short}`);
        popover.querySelectorAll("[data-pref-theme]").forEach((btn) => {
          const act = btn.dataset.prefTheme === curTheme;
          btn.classList.toggle("active", act);
          btn.setAttribute("aria-pressed", String(act));
        });
        popover.querySelectorAll("[data-pref-lang]").forEach((btn) => {
          const act = btn.dataset.prefLang === curLang;
          btn.classList.toggle("active", act);
          btn.setAttribute("aria-pressed", String(act));
        });
      };

      const setOpen = (open) => {
        prefHost.classList.toggle("is-open", open);
        trigger.setAttribute("aria-expanded", String(open));
        if (open) syncPrefUi();
      };

      trigger.addEventListener("click", (event) => {
        event.stopPropagation();
        setOpen(!prefHost.classList.contains("is-open"));
      });
      popover.addEventListener("click", (event) => {
        const themeBtn = event.target.closest("[data-pref-theme]");
        if (themeBtn) {
          setTheme(themeBtn.dataset.prefTheme);
          syncPrefUi();
          return;
        }
        const langBtn = event.target.closest("[data-pref-lang]");
        if (langBtn) {
          const code = langBtn.dataset.prefLang;
          langSel.value = code;
          if (window.PowerPlanI18n?.setLanguage) {
            window.PowerPlanI18n.setLanguage(code);
          }
          langSel.dispatchEvent(new Event("change", { bubbles: true }));
          syncPrefUi();
        }
      });
      themeSel.addEventListener("change", (event) => {
        setTheme(event.target.value);
        syncPrefUi();
      });
      window.addEventListener("powerplan:themechange", syncPrefUi);
      window.addEventListener("powerplan:langchange", syncPrefUi);
      document.addEventListener("click", (event) => {
        if (!prefHost.contains(event.target)) setOpen(false);
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setOpen(false);
      });

      syncPrefUi();
    }

    const userStatus = utilities.querySelector(".user-status");

    // 确保管理员在任意子页面都能一键访问用户管理，并将用户区折叠为“用户名胶囊 + 悬停/点击浮层菜单”
    if (userStatus) {
      let adminLink = userStatus.querySelector('a[href="users.html"]');
      const logoutBtn = userStatus.querySelector("[data-logout]");
      if (!adminLink) {
        adminLink = document.createElement("a");
        adminLink.href = "users.html";
        adminLink.dataset.adminOnly = "";
        adminLink.hidden = true;
        adminLink.textContent = "用户管理";
        if (logoutBtn) userStatus.insertBefore(adminLink, logoutBtn);
        else userStatus.appendChild(adminLink);
      }

      if (!userStatus.classList.contains("user-menu-host")) {
        const usernameEl = userStatus.querySelector("[data-auth-username]");
        const roleEl = userStatus.querySelector("[data-auth-role]");

        userStatus.classList.add("user-menu-host");

        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.className = "user-menu-trigger";
        trigger.setAttribute("aria-haspopup", "menu");
        trigger.setAttribute("aria-expanded", "false");
        trigger.innerHTML =
          `<svg class="topbar-icon user-menu-avatar" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"></circle><path d="M4 20a8 8 0 0 1 16 0"></path></svg>` +
          `<svg class="user-menu-caret" viewBox="0 0 24 24" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
        const caret = trigger.querySelector(".user-menu-caret");
        if (usernameEl) {
          trigger.insertBefore(usernameEl, caret);
        }

        const popover = document.createElement("div");
        popover.className = "user-menu-popover";
        popover.setAttribute("role", "menu");

        const header = document.createElement("div");
        header.className = "user-menu-header";
        const mirrorName = document.createElement("span");
        mirrorName.className = "user-menu-name";
        mirrorName.dataset.authUsername = "";
        mirrorName.textContent = usernameEl?.textContent || "";
        header.appendChild(mirrorName);
        if (roleEl) header.appendChild(roleEl);

        const actions = document.createElement("div");
        actions.className = "user-menu-actions";
        adminLink.setAttribute("role", "menuitem");
        actions.appendChild(adminLink);
        if (logoutBtn) {
          logoutBtn.setAttribute("role", "menuitem");
          actions.appendChild(logoutBtn);
        }

        popover.append(header, actions);
        userStatus.innerHTML = "";
        userStatus.append(trigger, popover);

        const setOpen = (open) => {
          userStatus.classList.toggle("is-open", open);
          trigger.setAttribute("aria-expanded", String(open));
        };
        trigger.addEventListener("click", (event) => {
          event.stopPropagation();
          setOpen(!userStatus.classList.contains("is-open"));
        });
        document.addEventListener("click", (event) => {
          if (!userStatus.contains(event.target)) setOpen(false);
        });
        document.addEventListener("keydown", (event) => {
          if (event.key === "Escape") setOpen(false);
        });
      }
    }
  }

  /** 为左侧方案列表注入即时搜索框与方案计数徽标 */
  function enhanceSchemeRail() {
    const schemeList = document.getElementById("schemeList");
    if (!schemeList) return;
    const rail = schemeList.closest(".scheme-rail");
    if (!rail || rail.querySelector(".scheme-search-box")) return;

    const titleEl = rail.querySelector(".scheme-list-title");
    let countBadge = null;
    if (titleEl && !titleEl.querySelector(".scheme-count-badge")) {
      countBadge = document.createElement("span");
      countBadge.className = "scheme-count-badge";
      countBadge.textContent = "0";
      titleEl.appendChild(countBadge);
    }

    const searchBox = document.createElement("div");
    searchBox.className = "scheme-search-box";
    searchBox.innerHTML =
      `<svg class="scheme-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg>` +
      `<input type="search" id="schemeQuickFilter" placeholder="筛选方案..." aria-label="筛选方案">` +
      `<button type="button" class="scheme-search-clear" aria-label="清空筛选" hidden>×</button>`;

    schemeList.parentElement.insertBefore(searchBox, schemeList);

    const input = searchBox.querySelector("input");
    const clearBtn = searchBox.querySelector(".scheme-search-clear");

    const applyFilter = () => {
      const keyword = input.value.trim().toLowerCase();
      clearBtn.hidden = !keyword;
      const items = schemeList.querySelectorAll(".scheme-list-items > li, .scheme-node, .scheme-item");
      // 优先以 li 节点为单元过滤，兼顾树形展开结构（evaluation / frequency）
      const rowNodes = Array.from(schemeList.querySelectorAll(".scheme-list-items > li"));
      const targets = rowNodes.length
        ? rowNodes
        : Array.from(schemeList.querySelectorAll(":scope > .scheme-item, :scope > .scheme-node"));

      let visibleCount = 0;
      targets.forEach((node) => {
        const text = (node.textContent || "").toLowerCase();
        const match = !keyword || text.includes(keyword);
        node.style.display = match ? "" : "none";
        if (match) visibleCount += 1;
      });

      if (countBadge) {
        const total = targets.length;
        countBadge.textContent = keyword ? `${visibleCount}/${total}` : String(total);
      }
    };

    input.addEventListener("input", applyFilter);
    clearBtn.addEventListener("click", () => {
      input.value = "";
      applyFilter();
      input.focus();
    });

    let filterRaf = 0;
    const scheduleFilter = () => {
      if (filterRaf) return;
      filterRaf = window.requestAnimationFrame(() => {
        filterRaf = 0;
        applyFilter();
      });
    };
    const listObserver = new MutationObserver(scheduleFilter);
    listObserver.observe(schemeList, { childList: true, subtree: true });
    applyFilter();
  }

  /** 构造任务详情跳转链接 */
  function taskDetailHref(task) {
    const pageMap = {
      optimization: "optimize.html",
      evaluation: "evaluation.html",
      frequency: "frequency.html",
      reliability: "reliability.html",
    };
    const page = pageMap[task?.task_type_key] || "optimize.html";
    const params = new URLSearchParams();
    if (task?.scheme) params.set("scheme", task.scheme);
    if (task?.result && task?.task_type_key !== "optimization") params.set("file", task.result);
    const qs = params.toString();
    return qs ? `${page}?${qs}` : page;
  }

  /** 在顶栏工具区挂载全局任务状态胶囊与右侧滑出任务抽屉 */
  function mountGlobalTaskDrawer() {
    const topbar = document.querySelector(".topbar");
    const utilities = topbar?.querySelector(".topbar-utilities");
    if (!topbar || !utilities) return;
    if (document.getElementById("globalTaskPill")) return;

    const pill = document.createElement("button");
    pill.type = "button";
    pill.id = "globalTaskPill";
    pill.className = "global-task-pill";
    pill.setAttribute("aria-expanded", "false");
    pill.setAttribute("aria-controls", "globalTaskDrawer");
    pill.innerHTML = `<span class="global-task-dot" aria-hidden="true"></span><span class="global-task-label">任务</span><span id="globalTaskBadge" class="global-task-badge" hidden></span>`;
    utilities.insertBefore(pill, utilities.firstChild);

    const backdrop = document.createElement("div");
    backdrop.id = "globalTaskDrawerBackdrop";
    backdrop.className = "global-task-drawer-backdrop";
    backdrop.hidden = true;

    const drawer = document.createElement("aside");
    drawer.id = "globalTaskDrawer";
    drawer.className = "global-task-drawer";
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-label", tr("全局任务监控"));
    drawer.hidden = true;
    drawer.innerHTML = `
      <div class="global-task-drawer-head">
        <h3>全局任务监控</h3>
        <div class="global-task-drawer-head-actions">
          <button type="button" id="globalTaskRefreshBtn">刷新</button>
          <a href="tasks.html" class="global-task-all-link">全部任务</a>
          <button type="button" id="globalTaskCloseBtn" aria-label="关闭">×</button>
        </div>
      </div>
      <div id="globalTaskDrawerBody" class="global-task-drawer-body">
        <div class="global-task-empty">加载中...</div>
      </div>
    `;
    document.body.append(backdrop, drawer);

    let lastStatusMap = new Map();
    let initialized = false;
    let pollTimer = 0;
    let fetching = false;
    let latestTasks = [];

    const escapeHtml = (value) =>
      String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");

    const openDrawer = () => {
      backdrop.hidden = false;
      drawer.hidden = false;
      pill.setAttribute("aria-expanded", "true");
      refreshTasks({ forceRender: true });
      schedulePoll(12000);
    };

    const closeDrawer = () => {
      backdrop.hidden = true;
      drawer.hidden = true;
      pill.setAttribute("aria-expanded", "false");
      schedulePoll(30000);
    };

    const renderDrawer = () => {
      const running = latestTasks.filter((t) => t.status === "计算中");
      const queued = latestTasks.filter((t) => t.queued || t.status === "排队中");
      const finished = latestTasks.filter((t) => ["完成计算", "计算失败", "计算超时", "计算中止"].includes(t.status)).slice(0, 12);
      const activeCount = running.length + queued.length;

      pill.classList.toggle("is-running", running.length > 0);
      pill.classList.toggle("is-queued", running.length === 0 && queued.length > 0);
      const badge = document.getElementById("globalTaskBadge");
      if (badge) {
        if (running.length > 0) {
          badge.textContent = queued.length ? `${running.length}+${queued.length}` : String(running.length);
          badge.hidden = false;
        } else if (queued.length > 0) {
          badge.textContent = String(queued.length);
          badge.hidden = false;
        } else {
          badge.textContent = "";
          badge.hidden = true;
        }
      }
      if (drawer.hidden) return;

      const body = document.getElementById("globalTaskDrawerBody");
      if (!body) return;
      const renderItem = (task) => {
        const stopAction = task.queued ? "cancel_queue" : "stop";
        const stopLabel = task.queued ? "离队" : "停止";
        const canTerminate = Boolean(task.queued || task.can_stop);
        const href = taskDetailHref(task);
        return `
          <div class="global-task-item" data-status="${escapeHtml(task.status || "")}">
            <div class="global-task-item-top">
              <span class="global-task-type">${escapeHtml(task.task_type || "")}</span>
              <strong class="global-task-scheme" title="${escapeHtml(task.scheme || "")}">${escapeHtml(task.scheme || "-")}</strong>
              <span class="global-task-status">${escapeHtml(task.status || "未计算")}${task.queue_position ? ` #${task.queue_position}` : ""}</span>
            </div>
            <div class="global-task-item-meta">
              <span title="${escapeHtml(task.result || "")}">${escapeHtml(task.result || "-")}</span>
              <span>${escapeHtml(task.elapsed_seconds ? `${task.elapsed_seconds}s` : "")}</span>
            </div>
            ${task.latest_log ? `<div class="global-task-item-log" title="${escapeHtml(task.latest_log)}">${escapeHtml(task.latest_log)}</div>` : ""}
            <div class="global-task-item-actions">
              <a class="global-task-action-link" href="${escapeHtml(href)}">查看</a>
              ${
                canTerminate
                  ? `<button type="button" class="danger" data-drawer-action="${stopAction}" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}">${stopLabel}</button>`
                  : ""
              }
            </div>
          </div>
        `;
      };

      const sections = [];
      if (activeCount > 0) {
        sections.push(`<div class="global-task-section-title">进行中 / 排队中 (${activeCount})</div>${[...running, ...queued].map(renderItem).join("")}`);
      }
      if (finished.length > 0) {
        sections.push(`<div class="global-task-section-title">近期完成 / 异常 (${finished.length})</div>${finished.map(renderItem).join("")}`);
      }
      if (!sections.length) {
        sections.push(`<div class="global-task-empty">当前无运行中或近期任务</div>`);
      }
      body.innerHTML = sections.join("");
      if (window.PowerPlanI18n) {
        window.PowerPlanI18n.translate(drawer, window.PowerPlanI18n.currentLanguage());
      }
    };

    const refreshTasks = async () => {
      if (fetching || document.hidden) return;
      fetching = true;
      try {
        const data = await fetchJson("/api/tasks", { slot: "global-tasks-drawer", ttlMs: 0, useEtag: true });
        if (!data) return;
        const nextTasks = Array.isArray(data.tasks) ? data.tasks : [];
        if (initialized) {
          nextTasks.forEach((task) => {
            const prevStatus = lastStatusMap.get(task.id);
            if ((prevStatus === "计算中" || prevStatus === "排队中") && task.status === "完成计算") {
              toast(`${task.task_type}已完成：${task.scheme}`, { level: "success" });
            } else if ((prevStatus === "计算中" || prevStatus === "排队中") && (task.status === "计算失败" || task.status === "计算超时")) {
              toast(`${task.task_type}${task.status}：${task.scheme}`, { level: "error" });
            }
          });
        }
        lastStatusMap = new Map(nextTasks.map((t) => [t.id, t.status]));
        initialized = true;
        latestTasks = nextTasks;
        renderDrawer();
      } catch (err) {
        if (err && err.name === "AbortError") return;
      } finally {
        fetching = false;
      }
    };

    const schedulePoll = (delayMs) => {
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = window.setInterval(refreshTasks, delayMs);
    };

    // 订阅全站 SSE 任务事件实现毫秒级更新，空闲仅靠 30s 兜底
    sseHub.on("tasks", () => {
      if (!document.hidden) refreshTasks();
    });

    pill.addEventListener("click", () => (drawer.hidden ? openDrawer() : closeDrawer()));
    backdrop.addEventListener("click", closeDrawer);
    drawer.querySelector("#globalTaskCloseBtn")?.addEventListener("click", closeDrawer);
    drawer.querySelector("#globalTaskRefreshBtn")?.addEventListener("click", () => refreshTasks());
    drawer.addEventListener("click", async (event) => {
      const btn = event.target?.closest?.("[data-drawer-action]");
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      try {
        const resp = await fetch("/api/tasks/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: btn.dataset.drawerAction,
            task_type: btn.dataset.taskType,
            scheme: btn.dataset.scheme,
            result: btn.dataset.result,
          }),
        });
        if (resp.ok) {
          const payload = await resp.json().catch(() => ({}));
          if (Array.isArray(payload.tasks)) {
            latestTasks = payload.tasks;
            renderDrawer();
          } else {
            await refreshTasks();
          }
        }
      } finally {
        btn.disabled = false;
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !drawer.hidden) closeDrawer();
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refreshTasks();
    });

    window.setTimeout(refreshTasks, 400);
    schedulePoll(6000);
  }

  /** 将计算类页面「启动 / 排队 / 停止」3 联按钮合并为 1 个实时当前状态胶囊，悬停时悬浮弹出 3 按钮操作栏 */
  function mountCompactCommandActionHub() {
    document.querySelectorAll(".optimization-command-row, .reliability-command-row").forEach((row) => {
      const actions = row.querySelector(":scope > .optimization-actions");
      if (!actions || row.querySelector(".cmd-action-hub")) return;
      const buttons = actions.querySelectorAll("button");
      if (buttons.length < 2) return;

      const statusGrid = row.querySelector(".optimization-status-grid");
      const statusStrong =
        row.querySelector("#optimizationStatus, #reliabilityStatus, #frequencyStatus") ||
        statusGrid?.querySelector(".status-tile:first-child strong");
      const statusTile = statusStrong?.closest(".status-tile");

      // 隐藏右侧指标条内重复的「状态」格（保留 DOM 以便业务脚本持续更新文本供镜像同步）
      if (statusTile) {
        statusTile.classList.add("is-mirrored-status");
      }

      const hub = document.createElement("div");
      hub.className = "cmd-action-hub";

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "cmd-action-trigger";
      trigger.setAttribute("aria-haspopup", "true");
      trigger.setAttribute("aria-expanded", "false");
      trigger.innerHTML =
        `<i class="cmd-action-dot" aria-hidden="true"></i>` +
        `<span class="cmd-action-label">—</span>` +
        `<svg class="cmd-action-caret" viewBox="0 0 24 24" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>`;

      const popover = document.createElement("div");
      popover.className = "cmd-action-popover";
      popover.setAttribute("role", "toolbar");
      popover.setAttribute("aria-label", actions.getAttribute("aria-label") || tr("任务操作"));

      actions.parentNode.insertBefore(hub, actions);
      popover.appendChild(actions);
      hub.append(trigger, popover);

      const labelEl = trigger.querySelector(".cmd-action-label");

      const classifyState = (txt) => {
        const s = String(txt || "").trim();
        if (/(运行|计算中|评估中|执行中|running|solving)/i.test(s)) return "running";
        if (/(排队|等待|queued|pending)/i.test(s)) return "queued";
        if (/(完成|成功|已计算|done|completed|success)/i.test(s)) return "done";
        if (/(失败|错误|异常|failed|error)/i.test(s)) return "error";
        if (/(停止|中止|已取消|stopped|cancel)/i.test(s)) return "stopped";
        return "idle";
      };

      const syncStatus = () => {
        const text = (statusStrong?.textContent || "").trim() || tr("待启动");
        const stateKind = classifyState(text);
        if (labelEl) labelEl.textContent = text;
        trigger.dataset.state = stateKind;
        trigger.setAttribute("title", `${text} — ${tr("悬停展开操作栏")}`);
      };

      syncStatus();

      if (statusStrong) {
        const obs = new MutationObserver(syncStatus);
        obs.observe(statusStrong, { childList: true, characterData: true, subtree: true });
      }

      let closeTimer = 0;
      const setOpen = (open) => {
        if (closeTimer) {
          window.clearTimeout(closeTimer);
          closeTimer = 0;
        }
        hub.classList.toggle("is-open", open);
        trigger.setAttribute("aria-expanded", String(open));
      };
      const scheduleClose = () => {
        if (closeTimer) window.clearTimeout(closeTimer);
        closeTimer = window.setTimeout(() => setOpen(false), 160);
      };

      hub.addEventListener("mouseenter", () => setOpen(true));
      hub.addEventListener("mouseleave", scheduleClose);
      trigger.addEventListener("click", (ev) => {
        ev.stopPropagation();
        setOpen(!hub.classList.contains("is-open"));
      });
      actions.addEventListener("click", (ev) => {
        if (ev.target.closest("button")) {
          window.setTimeout(() => setOpen(false), 120);
        }
      });
      document.addEventListener("click", (ev) => {
        if (!hub.contains(ev.target)) setOpen(false);
      });
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") setOpen(false);
      });
    });
  }

  /** 全站左侧栏纵向可拖拽分割条与一键隐藏/展开引擎（支持持久化记忆与图表重绘） */
  function mountSidebarSplitter() {
    const pageKey = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    const STORAGE_PREFIX = "powerPlanSidebarLayout:";

    const readLayout = () => {
      try {
        const raw = localStorage.getItem(STORAGE_PREFIX + pageKey);
        return raw ? JSON.parse(raw) : {};
      } catch (_) {
        return {};
      }
    };

    const writeLayout = (data) => {
      try {
        localStorage.setItem(STORAGE_PREFIX + pageKey, JSON.stringify(data));
      } catch (_) {
        // 忽略本地存储受限异常
      }
    };

    const triggerResize = () => {
      window.requestAnimationFrame(() => {
        window.dispatchEvent(new Event("resize"));
      });
    };

    const createToggleButton = (collapsed) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sidebar-splitter-toggle";
      const syncBtn = (isCollapsed) => {
        btn.setAttribute("aria-label", tr(isCollapsed ? "展开左侧栏" : "隐藏左侧栏"));
        btn.setAttribute("title", tr(isCollapsed ? "展开左侧栏" : "隐藏左侧栏"));
        btn.setAttribute("aria-expanded", String(!isCollapsed));
        btn.innerHTML = isCollapsed
          ? `<svg viewBox="0 0 16 16" aria-hidden="true"><polyline points="6 3 11 8 6 13"></polyline></svg>`
          : `<svg viewBox="0 0 16 16" aria-hidden="true"><polyline points="10 3 5 8 10 13"></polyline></svg>`;
      };
      syncBtn(collapsed);
      btn._syncCollapsed = syncBtn;
      return btn;
    };

    // 模式 A：evaluation.html / frequency.html 已有原生纵向分割条，统一接管拖拽调宽 + 拖至吸附隐藏 + 一键收起/展开
    const existingHandle = document.querySelector("#evaluationMainResizeHandle, #frequencyMainResizeHandle");
    const evalWorkspace = existingHandle?.closest(".evaluation-workspace");
    if (existingHandle && evalWorkspace && !existingHandle.querySelector(".sidebar-splitter-toggle")) {
      const saved = readLayout();
      const defaultEvalWidth = 340;
      const minEvalWidth = 180;
      const maxEvalWidth = 600;
      let collapsed = Boolean(saved.collapsed);
      let lastWidth = Number.isFinite(Number(saved.width))
        ? Math.min(maxEvalWidth, Math.max(minEvalWidth, Number(saved.width)))
        : defaultEvalWidth;
      const toggleBtn = createToggleButton(collapsed);

      const applyEvalState = (nextWidth, nextCollapsed, persist = true) => {
        lastWidth = Math.min(maxEvalWidth, Math.max(minEvalWidth, Math.round(nextWidth)));
        collapsed = Boolean(nextCollapsed);
        evalWorkspace.classList.toggle("is-sidebar-collapsed", collapsed);
        toggleBtn._syncCollapsed(collapsed);
        if (!collapsed) {
          document.documentElement.style.setProperty("--evaluation-result-rail-width", `${lastWidth}px`);
        }
        existingHandle.setAttribute("aria-valuenow", String(collapsed ? 0 : lastWidth));
        if (persist) writeLayout({ collapsed, width: lastWidth });
        triggerResize();
      };

      existingHandle.classList.add("has-sidebar-toggle");
      existingHandle.appendChild(toggleBtn);
      toggleBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
      toggleBtn.addEventListener("mousedown", (e) => e.stopPropagation());
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyEvalState(lastWidth, !collapsed, true);
      });
      existingHandle.addEventListener("dblclick", (e) => {
        if (e.target.closest(".sidebar-splitter-toggle")) return;
        if (collapsed) applyEvalState(lastWidth, false, true);
        else applyEvalState(defaultEvalWidth, false, true);
      });
      existingHandle.addEventListener(
        "pointerdown",
        (event) => {
          if (event.button !== 0 || event.target.closest(".sidebar-splitter-toggle")) return;
          event.preventDefault();
          event.stopImmediatePropagation();
          const wsRect = evalWorkspace.getBoundingClientRect();
          const wsPadLeft = parseFloat(getComputedStyle(evalWorkspace).paddingLeft) || 8;
          existingHandle.classList.add("is-dragging");
          document.body.classList.add("is-sidebar-resizing");
          try {
            existingHandle.setPointerCapture(event.pointerId);
          } catch (_) {}

          let liveWidth = lastWidth;
          let liveCollapsed = collapsed;

          const onMove = (moveEvent) => {
            const raw = moveEvent.clientX - wsRect.left - wsPadLeft;
            if (raw < 108) {
              liveCollapsed = true;
              evalWorkspace.classList.add("is-sidebar-collapsed");
              toggleBtn._syncCollapsed(true);
            } else {
              liveCollapsed = false;
              liveWidth = Math.min(maxEvalWidth, Math.max(minEvalWidth, Math.round(raw)));
              evalWorkspace.classList.remove("is-sidebar-collapsed");
              document.documentElement.style.setProperty("--evaluation-result-rail-width", `${liveWidth}px`);
              toggleBtn._syncCollapsed(false);
            }
          };

          const onUp = () => {
            existingHandle.classList.remove("is-dragging");
            document.body.classList.remove("is-sidebar-resizing");
            existingHandle.removeEventListener("pointermove", onMove);
            existingHandle.removeEventListener("pointerup", onUp);
            existingHandle.removeEventListener("pointercancel", onUp);
            applyEvalState(liveWidth, liveCollapsed, true);
          };

          existingHandle.addEventListener("pointermove", onMove);
          existingHandle.addEventListener("pointerup", onUp);
          existingHandle.addEventListener("pointercancel", onUp);
        },
        true,
      );
      if (saved.width || collapsed) applyEvalState(lastWidth, collapsed, false);
      return;
    }

    if (pageKey === "comparison.html") {
      const board = document.querySelector(".comparison-curve-board");
      if (!board || board.querySelector(".sidebar-splitter")) return;
      const defaultW = 220;
      const minW = 150;
      const maxW = 380;
      const savedBoard = readLayout();
      let curW = Number.isFinite(Number(savedBoard.width)) ? Math.min(maxW, Math.max(minW, Number(savedBoard.width))) : defaultW;
      let isCollapsed = Boolean(savedBoard.collapsed);

      const boardSplitter = document.createElement("div");
      boardSplitter.className = "sidebar-splitter";
      boardSplitter.setAttribute("role", "separator");
      boardSplitter.setAttribute("tabindex", "0");
      boardSplitter.setAttribute("aria-orientation", "vertical");
      boardSplitter.setAttribute("aria-label", tr("调整曲线列表宽度，双击重置"));

      const boardToggle = createToggleButton(isCollapsed);
      boardSplitter.appendChild(boardToggle);
      board.classList.add("has-curve-sidebar-splitter");
      board.appendChild(boardSplitter);

      const applyBoard = (nextW, nextCollapsed, persist = true) => {
        curW = Math.min(maxW, Math.max(minW, Math.round(nextW)));
        isCollapsed = Boolean(nextCollapsed);
        board.style.setProperty("--curve-sidebar-width", `${curW}px`);
        board.classList.toggle("is-sidebar-collapsed", isCollapsed);
        boardSplitter.setAttribute("aria-valuenow", String(isCollapsed ? 0 : curW));
        boardToggle._syncCollapsed(isCollapsed);
        if (persist) writeLayout({ width: curW, collapsed: isCollapsed });
        triggerResize();
      };

      applyBoard(curW, isCollapsed, false);

      boardToggle.addEventListener("pointerdown", (e) => e.stopPropagation());
      boardToggle.addEventListener("click", (e) => {
        e.stopPropagation();
        applyBoard(curW, !isCollapsed, true);
      });
      boardSplitter.addEventListener("dblclick", (e) => {
        if (e.target.closest(".sidebar-splitter-toggle")) return;
        applyBoard(isCollapsed ? curW : defaultW, false, true);
      });
      boardSplitter.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || event.target.closest(".sidebar-splitter-toggle")) return;
        event.preventDefault();
        const bRect = board.getBoundingClientRect();
        const bPad = parseFloat(getComputedStyle(board).paddingLeft) || 12;
        boardSplitter.classList.add("is-dragging");
        document.body.classList.add("is-sidebar-resizing");
        try {
          boardSplitter.setPointerCapture(event.pointerId);
        } catch (_) {}

        let liveW = curW;
        let liveC = isCollapsed;
        const onMove = (moveEvent) => {
          const raw = moveEvent.clientX - bRect.left - bPad;
          if (raw < 96) {
            liveC = true;
            board.classList.add("is-sidebar-collapsed");
            boardToggle._syncCollapsed(true);
          } else {
            liveC = false;
            liveW = Math.min(maxW, Math.max(minW, Math.round(raw)));
            board.classList.remove("is-sidebar-collapsed");
            board.style.setProperty("--curve-sidebar-width", `${liveW}px`);
            boardToggle._syncCollapsed(false);
          }
        };
        const onUp = () => {
          boardSplitter.classList.remove("is-dragging");
          document.body.classList.remove("is-sidebar-resizing");
          boardSplitter.removeEventListener("pointermove", onMove);
          boardSplitter.removeEventListener("pointerup", onUp);
          boardSplitter.removeEventListener("pointercancel", onUp);
          applyBoard(liveW, liveC, true);
        };
        boardSplitter.addEventListener("pointermove", onMove);
        boardSplitter.addEventListener("pointerup", onUp);
        boardSplitter.addEventListener("pointercancel", onUp);
      });
      return;
    }

    // 模式 B：planning / optimize / reliability / sensitivity 统一注入可拖拽 + 可收起纵向分割条
    let workspace = null;
    let defaultWidth = 236;
    let minWidth = 170;
    let maxWidth = 520;

    if (pageKey === "planning.html") {
      workspace = document.querySelector("section.workspace");
      defaultWidth = 240;
    } else if (pageKey === "optimize.html") {
      workspace = document.querySelector("section.optimization-workspace");
      defaultWidth = 236;
    } else if (pageKey === "reliability.html") {
      workspace = document.querySelector("section.reliability-workspace");
      defaultWidth = 336;
      minWidth = 240;
      maxWidth = 560;
    } else if (pageKey === "sensitivity.html") {
      workspace = document.querySelector("section.sensitivity-workspace");
      defaultWidth = 296;
      minWidth = 220;
      maxWidth = 520;
    }

    if (!workspace || workspace.querySelector(".sidebar-splitter")) return;

    const saved = readLayout();
    let width = Number.isFinite(Number(saved.width)) ? Math.min(maxWidth, Math.max(minWidth, Number(saved.width))) : defaultWidth;
    let collapsed = Boolean(saved.collapsed);

    const splitter = document.createElement("div");
    splitter.className = "sidebar-splitter";
    splitter.setAttribute("role", "separator");
    splitter.setAttribute("tabindex", "0");
    splitter.setAttribute("aria-orientation", "vertical");
    splitter.setAttribute("aria-label", tr("调整左侧栏宽度，双击重置"));

    const toggleBtn = createToggleButton(collapsed);
    splitter.appendChild(toggleBtn);
    workspace.classList.add("has-sidebar-splitter");
    workspace.appendChild(splitter);

    const applyState = (nextWidth, nextCollapsed, persist = true) => {
      width = Math.min(maxWidth, Math.max(minWidth, Math.round(nextWidth)));
      collapsed = Boolean(nextCollapsed);
      workspace.style.setProperty("--sidebar-width", `${width}px`);
      workspace.classList.toggle("is-sidebar-collapsed", collapsed);
      splitter.setAttribute("aria-valuenow", String(collapsed ? 0 : width));
      toggleBtn._syncCollapsed(collapsed);
      if (persist) writeLayout({ width, collapsed });
      triggerResize();
    };

    applyState(width, collapsed, false);

    toggleBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
    toggleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      applyState(width, !collapsed, true);
    });

    splitter.addEventListener("dblclick", (e) => {
      if (e.target.closest(".sidebar-splitter-toggle")) return;
      if (collapsed) applyState(width, false, true);
      else applyState(defaultWidth, false, true);
    });

    splitter.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        applyState(width, !collapsed, true);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        if (!collapsed) applyState(width - 16, false, true);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        applyState(collapsed ? width : width + 16, false, true);
      }
    });

    splitter.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest(".sidebar-splitter-toggle")) return;
      event.preventDefault();
      const wsRect = workspace.getBoundingClientRect();
      const wsPadLeft = parseFloat(getComputedStyle(workspace).paddingLeft) || 8;
      splitter.classList.add("is-dragging");
      document.body.classList.add("is-sidebar-resizing");
      try {
        splitter.setPointerCapture(event.pointerId);
      } catch (_) {}

      let liveWidth = width;
      let liveCollapsed = collapsed;

      const onMove = (moveEvent) => {
        const raw = moveEvent.clientX - wsRect.left - wsPadLeft;
        if (raw < 108) {
          liveCollapsed = true;
          workspace.classList.add("is-sidebar-collapsed");
          toggleBtn._syncCollapsed(true);
        } else {
          liveCollapsed = false;
          liveWidth = Math.min(maxWidth, Math.max(minWidth, Math.round(raw)));
          workspace.classList.remove("is-sidebar-collapsed");
          workspace.style.setProperty("--sidebar-width", `${liveWidth}px`);
          toggleBtn._syncCollapsed(false);
        }
      };

      const onUp = () => {
        splitter.classList.remove("is-dragging");
        document.body.classList.remove("is-sidebar-resizing");
        splitter.removeEventListener("pointermove", onMove);
        splitter.removeEventListener("pointerup", onUp);
        splitter.removeEventListener("pointercancel", onUp);
        applyState(liveWidth, liveCollapsed, true);
      };

      splitter.addEventListener("pointermove", onMove);
      splitter.addEventListener("pointerup", onUp);
      splitter.addEventListener("pointercancel", onUp);
    });
  }

  // =========================================================================
  // 统一请求层：AbortController 竞态取消 + 客户端 LRU 缓存 + ETag/304 协商
  // =========================================================================
  const INFLIGHT_SLOTS = new Map();
  const CLIENT_LRU_CACHE = new Map(); // url -> { data, etag, ts }
  const CLIENT_LRU_MAX = 64;

  function lruSet(key, entry) {
    if (CLIENT_LRU_CACHE.has(key)) CLIENT_LRU_CACHE.delete(key);
    CLIENT_LRU_CACHE.set(key, entry);
    while (CLIENT_LRU_CACHE.size > CLIENT_LRU_MAX) {
      const oldest = CLIENT_LRU_CACHE.keys().next().value;
      CLIENT_LRU_CACHE.delete(oldest);
    }
  }

  function clearClientCache(prefix = "") {
    if (!prefix) {
      CLIENT_LRU_CACHE.clear();
      return;
    }
    for (const k of Array.from(CLIENT_LRU_CACHE.keys())) {
      if (k.startsWith(prefix)) CLIENT_LRU_CACHE.delete(k);
    }
  }

  async function fetchJson(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const slot = options.slot ? String(options.slot) : "";
    const ttlMs = Number.isFinite(Number(options.ttlMs)) ? Number(options.ttlMs) : 0;
    const useEtag = options.useEtag !== false && method === "GET";

    if (method === "GET" && ttlMs > 0) {
      const hit = CLIENT_LRU_CACHE.get(url);
      if (hit && Date.now() - hit.ts <= ttlMs) {
        return hit.data;
      }
    }

    let controller = null;
    if (slot) {
      const prev = INFLIGHT_SLOTS.get(slot);
      if (prev) {
        try { prev.abort(); } catch (_) {}
      }
      controller = new AbortController();
      INFLIGHT_SLOTS.set(slot, controller);
    }

    const headers = { ...(options.headers || {}) };
    const cached = method === "GET" ? CLIENT_LRU_CACHE.get(url) : null;
    if (useEtag && cached && cached.etag) {
      headers["If-None-Match"] = cached.etag;
    }

    try {
      const resp = await fetch(url, {
        ...options,
        method,
        headers,
        signal: controller ? controller.signal : options.signal,
      });
      if (resp.status === 304 && cached) {
        cached.ts = Date.now();
        lruSet(url, cached);
        return cached.data;
      }
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        if (resp.status === 401 && !["/login.html", "/register.html"].includes(window.location.pathname)) {
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.href = `/login.html?next=${next}`;
        }
        throw new Error(data.message || data.error || `请求失败 (${resp.status})`);
      }
      if (method === "GET") {
        const etag = resp.headers.get("ETag") || "";
        if (etag || ttlMs > 0) {
          lruSet(url, { data, etag, ts: Date.now() });
        }
      } else {
        // 写操作后清理只读缓存，避免脏数据
        clearClientCache();
      }
      return data;
    } finally {
      if (slot && INFLIGHT_SLOTS.get(slot) === controller) {
        INFLIGHT_SLOTS.delete(slot);
      }
    }
  }

  // =========================================================================
  // 全站单连接 SSE 事件总线（替代多处高频 setInterval 轮询）
  // =========================================================================
  function createSseHub() {
    const listeners = new Map();
    let es = null;
    let reconnectDelay = 2000;
    let reconnectTimer = 0;
    let connected = false;

    const emit = (eventName, payload) => {
      const set = listeners.get(eventName);
      if (!set) return;
      set.forEach((fn) => {
        try { fn(payload); } catch (_) {}
      });
    };

    const close = () => {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = 0;
      }
      if (es) {
        try { es.close(); } catch (_) {}
        es = null;
      }
      connected = false;
    };

    const connect = () => {
      if (typeof window.EventSource !== "function") return;
      if (["/login.html", "/register.html"].includes(window.location.pathname)) return;
      if (document.hidden || es) return;
      try {
        es = new EventSource("/api/events");
        es.addEventListener("ready", () => {
          connected = true;
          reconnectDelay = 2000;
          emit("ready", { connected: true });
        });
        es.addEventListener("tasks", (ev) => {
          let parsed = {};
          try { parsed = JSON.parse(ev.data || "{}"); } catch (_) {}
          clearClientCache("/api/tasks");
          emit("tasks", parsed);
        });
        es.onerror = () => {
          close();
          if (!document.hidden) {
            reconnectTimer = window.setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(30000, Math.round(reconnectDelay * 1.6));
          }
        };
      } catch (_) {
        close();
      }
    };

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) close();
      else connect();
    });
    window.addEventListener("beforeunload", close);

    return {
      connect,
      isConnected: () => connected,
      on(eventName, handler) {
        if (!listeners.has(eventName)) listeners.set(eventName, new Set());
        listeners.get(eventName).add(handler);
        if (!es && !document.hidden) connect();
        return () => listeners.get(eventName)?.delete(handler);
      },
    };
  }
  const sseHub = createSseHub();
  window.PowerPlanEvents = sseHub;

  // =========================================================================
  // 骨架屏、陈旧结果提醒条与通用导出工具（PNG / SVG / CSV）
  // =========================================================================
  function renderSkeleton(target, kind = "chart") {
    const el = typeof target === "string" ? document.querySelector(target) : target;
    if (!el) return;
    if (kind === "table") {
      el.innerHTML = `<div class="ui-skeleton-wrap" aria-busy="true"><div class="ui-skeleton-row"></div><div class="ui-skeleton-row"></div><div class="ui-skeleton-row"></div><div class="ui-skeleton-row short"></div></div>`;
    } else if (kind === "cards") {
      el.innerHTML = `<div class="ui-skeleton-grid" aria-busy="true"><div class="ui-skeleton-card"></div><div class="ui-skeleton-card"></div><div class="ui-skeleton-card"></div></div>`;
    } else {
      el.innerHTML = `<div class="ui-skeleton-chart" aria-busy="true"><div class="ui-skeleton-row short"></div><div class="ui-skeleton-box"></div></div>`;
    }
  }

  function renderStaleBanner(staleInfo, options = {}) {
    if (!staleInfo || !staleInfo.is_stale) return "";
    const reason = staleInfo.reason || tr("方案参数已变更，当前结果已过期，建议重新计算");
    const btnHtml = options.actionAttr
      ? `<button type="button" class="stale-recalc-btn" ${options.actionAttr}>${tr(options.actionLabel || "立即重算")}</button>`
      : "";
    return `<div class="stale-result-banner" role="status">
      <span class="stale-badge-dot" aria-hidden="true"></span>
      <span class="stale-banner-text">${String(reason).replace(/</g, "&lt;")}</span>
      ${btnHtml}
    </div>`;
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function serializeSvgForExport(svgEl) {
    if (!svgEl) return null;
    const clone = svgEl.cloneNode(true);
    const rect = svgEl.getBoundingClientRect();
    const vb = svgEl.getAttribute("viewBox");
    const w = Math.max(320, Math.round(rect.width || 960));
    const h = Math.max(200, Math.round(rect.height || 360));
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    if (!vb) clone.setAttribute("viewBox", `0 0 ${w} ${h}`);
    clone.setAttribute("width", String(w));
    clone.setAttribute("height", String(h));
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || (isDarkTheme() ? "#0F172A" : "#FFFFFF");
    const bgRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bgRect.setAttribute("x", "0");
    bgRect.setAttribute("y", "0");
    bgRect.setAttribute("width", "100%");
    bgRect.setAttribute("height", "100%");
    bgRect.setAttribute("fill", bg);
    clone.insertBefore(bgRect, clone.firstChild);
    const text = new XMLSerializer().serializeToString(clone);
    return { text, w, h, bg };
  }

  function exportSvgAsSvg(svgEl, filename = "chart.svg") {
    const info = serializeSvgForExport(svgEl);
    if (!info) return;
    triggerDownload(new Blob([info.text], { type: "image/svg+xml;charset=utf-8" }), filename);
    toast(`${tr("已导出")} ${filename}`, { level: "success" });
  }

  function exportSvgAsPng(svgEl, filename = "chart.png", overlayCanvas = null) {
    const info = serializeSvgForExport(svgEl);
    if (!info) return;
    const scale = 2;
    const img = new Image();
    const svgBlob = new Blob([info.text], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    img.onload = () => {
      const out = document.createElement("canvas");
      out.width = info.w * scale;
      out.height = info.h * scale;
      const ctx = out.getContext("2d");
      ctx.fillStyle = info.bg;
      ctx.fillRect(0, 0, out.width, out.height);
      ctx.drawImage(img, 0, 0, out.width, out.height);
      if (overlayCanvas && overlayCanvas.width > 0 && overlayCanvas.height > 0) {
        ctx.drawImage(overlayCanvas, 0, 0, out.width, out.height);
      }
      URL.revokeObjectURL(url);
      out.toBlob((blob) => {
        if (blob) {
          triggerDownload(blob, filename);
          toast(`${tr("已导出")} ${filename}`, { level: "success" });
        }
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      exportSvgAsSvg(svgEl, filename.replace(/\.png$/i, ".svg"));
    };
    img.src = url;
  }

  function exportCanvasAsPng(canvasEl, filename = "chart.png") {
    if (!canvasEl) return;
    const out = document.createElement("canvas");
    out.width = canvasEl.width;
    out.height = canvasEl.height;
    const ctx = out.getContext("2d");
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || (isDarkTheme() ? "#0F172A" : "#FFFFFF");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(canvasEl, 0, 0);
    out.toBlob((blob) => {
      if (blob) {
        triggerDownload(blob, filename);
        toast(`${tr("已导出")} ${filename}`, { level: "success" });
      }
    }, "image/png");
  }

  function exportRowsAsCsv(headers, rows, filename = "data.csv") {
    const esc = (v) => {
      const s = String(v ?? "");
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [headers.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))];
    triggerDownload(new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), filename);
    toast(`${tr("已导出")} ${filename}`, { level: "success" });
  }

  // =========================================================================
  // 全局快捷命令面板（Ctrl+K / Cmd+K）
  // =========================================================================
  function mountCommandPalette() {
    const topbar = document.querySelector(".topbar");
    const utilities = topbar?.querySelector(".topbar-utilities");
    if (!topbar || !utilities || document.getElementById("cmdPaletteTrigger")) return;

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.id = "cmdPaletteTrigger";
    trigger.className = "cmd-palette-trigger";
    trigger.title = tr("全局快捷命令 (Ctrl+K)");
    trigger.innerHTML = `<svg class="topbar-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg><kbd>Ctrl K</kbd>`;
    utilities.insertBefore(trigger, utilities.firstChild);

    const backdrop = document.createElement("div");
    backdrop.id = "cmdPaletteBackdrop";
    backdrop.className = "cmd-palette-backdrop";
    backdrop.hidden = true;
    backdrop.innerHTML = `
      <div class="cmd-palette-dialog" role="dialog" aria-modal="true" aria-label="快捷命令面板">
        <div class="cmd-palette-input-row">
          <input id="cmdPaletteInput" type="search" placeholder="搜索方案、页面、主题或语言..." autocomplete="off">
          <kbd>Esc</kbd>
        </div>
        <div id="cmdPaletteList" class="cmd-palette-list" role="listbox"></div>
      </div>
    `;
    document.body.appendChild(backdrop);

    const input = backdrop.querySelector("#cmdPaletteInput");
    const listEl = backdrop.querySelector("#cmdPaletteList");
    let cachedSchemes = [];
    let filtered = [];
    let activeIdx = 0;

    const STATIC_COMMANDS = [
      { group: "导航", label: "联合规划总览大屏", sub: "scada.html", run: () => { window.location.href = "scada.html"; } },
      { group: "导航", label: "系统首页", sub: "index.html", run: () => { window.location.href = "index.html"; } },
      { group: "导航", label: "参数维护", sub: "planning.html", run: () => { window.location.href = "planning.html"; } },
      { group: "导航", label: "规划求解", sub: "optimize.html", run: () => { window.location.href = "optimize.html"; } },
      { group: "导航", label: "方案评估", sub: "evaluation.html", run: () => { window.location.href = "evaluation.html"; } },
      { group: "导航", label: "供电可靠性", sub: "reliability.html", run: () => { window.location.href = "reliability.html"; } },
      { group: "导航", label: "频率计算", sub: "frequency.html", run: () => { window.location.href = "frequency.html"; } },
      { group: "导航", label: "结果对比", sub: "comparison.html", run: () => { window.location.href = "comparison.html"; } },
      { group: "导航", label: "批量扫参 / 敏感性分析", sub: "sensitivity.html", run: () => { window.location.href = "sensitivity.html"; } },
      { group: "导航", label: "综合评审简报", sub: "report.html", run: () => { window.location.href = "report.html"; } },
      { group: "导航", label: "任务并发监控", sub: "tasks.html", run: () => { window.location.href = "tasks.html"; } },
      ...THEMES.map((t) => ({ group: "主题", label: `切换主题：${t.label}`, sub: t.id, run: () => setTheme(t.id) })),
      { group: "语言", label: "切换语言：简体中文", sub: "zh-CN", run: () => window.PowerPlanI18n?.setLanguage?.("zh-CN") },
      { group: "语言", label: "Switch Language: English", sub: "en-US", run: () => window.PowerPlanI18n?.setLanguage?.("en-US") },
      { group: "语言", label: "Сменить язык: Русский", sub: "ru-RU", run: () => window.PowerPlanI18n?.setLanguage?.("ru-RU") },
    ];

    const renderList = () => {
      const q = String(input.value || "").trim().toLowerCase();
      const schemeCmds = cachedSchemes.flatMap((s) => [
        {
          group: "方案",
          label: `${s.name} · 方案评估`,
          sub: "evaluation.html",
          run: () => { window.location.href = `evaluation.html?scheme=${encodeURIComponent(s.name)}`; },
        },
        {
          group: "方案",
          label: `${s.name} · 参数维护`,
          sub: "planning.html",
          run: () => { window.location.href = `planning.html?scheme=${encodeURIComponent(s.name)}`; },
        },
        {
          group: "方案",
          label: `${s.name} · 综合简报`,
          sub: "report.html",
          run: () => { window.location.href = `report.html?scheme=${encodeURIComponent(s.name)}`; },
        },
      ]);
      const all = [...schemeCmds, ...STATIC_COMMANDS];
      filtered = q
        ? all.filter((item) => `${item.group} ${item.label} ${item.sub}`.toLowerCase().includes(q)).slice(0, 18)
        : [...STATIC_COMMANDS.slice(0, 10), ...schemeCmds.slice(0, 6)];
      activeIdx = Math.min(activeIdx, Math.max(0, filtered.length - 1));
      if (!filtered.length) {
        listEl.innerHTML = `<div class="cmd-palette-empty">${tr("未找到匹配命令或方案")}</div>`;
        return;
      }
      listEl.innerHTML = filtered
        .map(
          (item, idx) => `
        <button type="button" class="cmd-palette-item${idx === activeIdx ? " is-active" : ""}" data-cmd-idx="${idx}" role="option" aria-selected="${idx === activeIdx}">
          <span class="cmd-palette-group">${tr(item.group)}</span>
          <span class="cmd-palette-label">${item.label}</span>
          <span class="cmd-palette-sub">${item.sub}</span>
        </button>`,
        )
        .join("");
    };

    const close = () => {
      backdrop.hidden = true;
    };

    const open = async () => {
      backdrop.hidden = false;
      input.value = "";
      activeIdx = 0;
      renderList();
      input.focus();
      try {
        const res = await fetchJson("/api/planning/schemes", { slot: "cmd-palette-schemes", ttlMs: 15000 });
        cachedSchemes = Array.isArray(res?.schemes) ? res.schemes : [];
        if (!backdrop.hidden) renderList();
      } catch (_) {}
    };

    const runSelected = (idx) => {
      const target = filtered[idx];
      if (!target) return;
      close();
      target.run();
    };

    trigger.addEventListener("click", open);
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) close();
    });
    input.addEventListener("input", () => {
      activeIdx = 0;
      renderList();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIdx = filtered.length ? (activeIdx + 1) % filtered.length : 0;
        renderList();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIdx = filtered.length ? (activeIdx - 1 + filtered.length) % filtered.length : 0;
        renderList();
      } else if (e.key === "Enter") {
        e.preventDefault();
        runSelected(activeIdx);
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    });
    listEl.addEventListener("click", (e) => {
      const item = e.target.closest("[data-cmd-idx]");
      if (item) runSelected(Number(item.dataset.cmdIdx));
    });

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (backdrop.hidden) open();
        else close();
      }
    });
  }

  /** 注册全局快捷键：Ctrl+S 快捷保存、Esc 关闭右键菜单与原生弹窗 */
  function bindGlobalShortcuts() {
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        const saveBtn =
          document.getElementById("saveScheme") ||
          document.getElementById("saveEvaluationResult") ||
          document.getElementById("saveReliabilityParameters");
        if (saveBtn && !saveBtn.disabled && saveBtn.offsetParent !== null) {
          event.preventDefault();
          saveBtn.click();
        }
      } else if (event.key === "Escape") {
        // 关闭可见的右键菜单
        document.querySelectorAll(".device-context-menu:not([hidden])").forEach((menu) => {
          menu.hidden = true;
        });
      }
    });
  }

  // =========================================================================
  // 全局网页目录树左栏（默认隐藏满屏 · 左边缘触发悬浮 · 支持悬浮/内嵌切换 · 双模式均可隐藏）
  // =========================================================================
  function mountGlobalNavTree() {
    const curFile = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    if (["login.html", "register.html"].includes(curFile)) return;
    if (document.getElementById("globalNavTree")) return;

    const STORAGE_KEY = "powerPlanNavTreeState_v1";
    const readPrefs = () => {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : {};
        return {
          mode: parsed.mode === "dock" ? "dock" : "float",
          dockVisible: Boolean(parsed.dockVisible),
          collapsedGroups: Array.isArray(parsed.collapsedGroups) ? parsed.collapsedGroups : [],
        };
      } catch (_) {
        return { mode: "float", dockVisible: false, collapsedGroups: [] };
      }
    };
    const writePrefs = (next) => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch (_) {}
    };

    const prefs = readPrefs();
    let mode = prefs.mode; // "float" | "dock"
    let dockVisible = mode === "dock" ? prefs.dockVisible : false;
    let floatVisible = false;
    let suppressHoverUntil = 0;
    let hideTimer = 0;
    const collapsedGroups = new Set(prefs.collapsedGroups || []);

    const TREE_GROUPS = [
      {
        id: "overview",
        label: "总览与驾驶舱",
        items: [
          { page: "index.html", label: "系统首页" },
          { page: "scada.html", label: "规划大屏", withContext: true },
        ],
      },
      {
        id: "modeling",
        label: "规划建模与求解",
        items: [
          { page: "planning.html", label: "参数维护", withScheme: true },
          { page: "optimize.html", label: "规划求解", withScheme: true },
          { page: "sensitivity.html", label: "批量扫参", withScheme: true },
        ],
      },
      {
        id: "evaluation",
        label: "评估校核与决策",
        items: [
          { page: "evaluation.html", label: "方案评估", withContext: true },
          { page: "reliability.html", label: "供电可靠性", withContext: true },
          { page: "frequency.html", label: "频率计算", withContext: true },
          { page: "comparison.html", label: "结果对比" },
          { page: "report.html", label: "综合简报", withContext: true },
        ],
      },
      {
        id: "system",
        label: "运行与系统管理",
        items: [
          { page: "tasks.html", label: "任务并发" },
          { page: "users.html", label: "用户与诊断", adminOnly: true },
        ],
      },
    ];

    // 左边缘极简视觉提示柄（不拦截页面点击，仅提示左侧可呼出目录树）
    const edgeCue = document.createElement("div");
    edgeCue.id = "globalNavTreeEdgeCue";
    edgeCue.className = "nav-tree-edge-cue";
    edgeCue.setAttribute("aria-hidden", "true");

    const aside = document.createElement("aside");
    aside.id = "globalNavTree";
    aside.className = "global-nav-tree";
    aside.setAttribute("aria-label", tr("网页目录树"));

    const buildHref = (item) => {
      const ctx = window.PowerPlanPageState?.getActiveContext?.() || {};
      if (item.withContext && ctx.scheme) {
        const qs = new URLSearchParams({ scheme: ctx.scheme, ...(ctx.filename ? { file: ctx.filename } : {}) }).toString();
        return `${item.page}?${qs}`;
      }
      if (item.withScheme && ctx.scheme) {
        return `${item.page}?scheme=${encodeURIComponent(ctx.scheme)}`;
      }
      return item.page;
    };

    const renderTreeContent = () => {
      const treeBody = aside.querySelector("#globalNavTreeBody");
      if (!treeBody) return;
      const isAdmin = Boolean(document.querySelector('[data-admin-only]:not([hidden])')) || window.PowerPlanAuth?.currentUser?.role === "admin";
      treeBody.innerHTML = TREE_GROUPS.map((group) => {
        const visibleItems = group.items.filter((it) => !it.adminOnly || isAdmin);
        if (!visibleItems.length) return "";
        const isCollapsed = collapsedGroups.has(group.id);
        return `
          <div class="nav-tree-group${isCollapsed ? " is-collapsed" : ""}" data-nav-group="${group.id}">
            <button type="button" class="nav-tree-group-head" data-nav-group-toggle="${group.id}" aria-expanded="${!isCollapsed}">
              <span class="nav-tree-chevron" aria-hidden="true">▾</span>
              <span class="nav-tree-group-label">${tr(group.label)}</span>
            </button>
            <ul class="nav-tree-list" ${isCollapsed ? "hidden" : ""}>
              ${visibleItems
                .map((it) => {
                  const active = it.page === curFile;
                  const icoName = PAGE_ICON_MAP[it.page] || "compass";
                  return `<li><a class="nav-tree-link${active ? " is-active" : ""}" href="${buildHref(it)}"${active ? ' aria-current="page"' : ""} title="${tr(it.label)}">${renderIcon(icoName, "ui-ico-sm")}<span>${tr(it.label)}</span></a></li>`;
                })
                .join("")}
            </ul>
          </div>`;
      }).join("");
      if (window.PowerPlanI18n) {
        window.PowerPlanI18n.translate(aside, window.PowerPlanI18n.currentLanguage());
      }
    };

    aside.innerHTML = `
      <div class="nav-tree-head">
        <span class="nav-tree-title">${tr("网页目录")}</span>
        <div class="nav-tree-controls">
          <div class="nav-tree-mode-switch" role="group" aria-label="目录栏显示模式">
            <button type="button" class="nav-tree-mode-btn" data-nav-mode="float" aria-pressed="true">${tr("悬浮")}</button>
            <button type="button" class="nav-tree-mode-btn" data-nav-mode="dock" aria-pressed="false">${tr("内嵌")}</button>
          </div>
          <button type="button" id="globalNavTreeHideBtn" class="nav-tree-hide-btn" title="${tr("隐藏目录栏")}" aria-label="${tr("隐藏目录栏")}">×</button>
        </div>
      </div>
      <nav id="globalNavTreeBody" class="nav-tree-body"></nav>
    `;

    document.body.append(edgeCue, aside);

    // 动态同步顶栏实际高度，保证左栏始终严格位于通栏顶栏正下方，不遮挡不挤压顶栏
    const syncNavTreeTopOffset = () => {
      const bar = document.querySelector(".scada-topbar, .topbar");
      const h = bar ? Math.round(bar.getBoundingClientRect().height) : 44;
      if (h > 0) {
        document.documentElement.style.setProperty("--nav-tree-top", `${h}px`);
      }
    };
    syncNavTreeTopOffset();
    window.addEventListener("resize", syncNavTreeTopOffset);

    const triggerLayoutResize = () => {
      window.setTimeout(() => window.dispatchEvent(new Event("resize")), 210);
    };

    const syncUi = (persist = false) => {
      const isDockedOpen = mode === "dock" && dockVisible;
      const isFloatingOpen = floatVisible && !isDockedOpen;
      const isVisible = isDockedOpen || isFloatingOpen;

      aside.classList.toggle("is-visible", isVisible);
      aside.classList.toggle("is-docked", isDockedOpen);
      aside.classList.toggle("is-floating", isFloatingOpen);
      edgeCue.classList.toggle("is-hidden", isVisible);

      const prevDocked = document.body.classList.contains("has-nav-tree-docked");
      document.body.classList.toggle("has-nav-tree-docked", isDockedOpen);
      if (prevDocked !== isDockedOpen) {
        triggerLayoutResize();
      }

      aside.querySelectorAll("[data-nav-mode]").forEach((btn) => {
        const active = btn.dataset.navMode === mode;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", String(active));
      });

      if (persist) {
        writePrefs({
          mode,
          dockVisible,
          collapsedGroups: Array.from(collapsedGroups),
        });
      }
    };

    const cancelHide = () => {
      if (hideTimer) {
        window.clearTimeout(hideTimer);
        hideTimer = 0;
      }
    };

    const scheduleAutoHide = () => {
      cancelHide();
      // 悬浮展示态（包括内嵌隐藏后鼠标移至左边缘临时唤出）离开后自动隐藏
      if (mode === "dock" && dockVisible) return;
      hideTimer = window.setTimeout(() => {
        floatVisible = false;
        syncUi(false);
      }, 240);
    };

    const showFloating = () => {
      if (Date.now() < suppressHoverUntil) return;
      if (mode === "dock" && dockVisible) return;
      cancelHide();
      if (!floatVisible) {
        floatVisible = true;
        renderTreeContent();
        syncUi(false);
      }
    };

    const hideNavTree = () => {
      cancelHide();
      floatVisible = false;
      if (mode === "dock") dockVisible = false;
      // 点击隐藏后短暂抑制 600ms 边缘悬浮触发，防止鼠标尚未移出左栏立刻又弹回
      suppressHoverUntil = Date.now() + 600;
      syncUi(true);
    };

    // 鼠标移到左边框或附近（<= 14px）自动悬浮呼出
    document.addEventListener("mousemove", (event) => {
      if (event.clientX <= 14) {
        showFloating();
      } else if (floatVisible && event.clientX > 228 && !aside.matches(":hover")) {
        scheduleAutoHide();
      }
    });

    aside.addEventListener("mouseenter", cancelHide);
    aside.addEventListener("mouseleave", scheduleAutoHide);

    aside.addEventListener("click", (event) => {
      const modeBtn = event.target.closest("[data-nav-mode]");
      if (modeBtn) {
        const nextMode = modeBtn.dataset.navMode === "dock" ? "dock" : "float";
        mode = nextMode;
        if (mode === "dock") {
          dockVisible = true;
          floatVisible = false;
        } else {
          dockVisible = false;
          floatVisible = true;
        }
        syncUi(true);
        return;
      }
      if (event.target.closest("#globalNavTreeHideBtn")) {
        hideNavTree();
        return;
      }
      const groupBtn = event.target.closest("[data-nav-group-toggle]");
      if (groupBtn) {
        const gid = groupBtn.dataset.navGroupToggle;
        if (collapsedGroups.has(gid)) collapsedGroups.delete(gid);
        else collapsedGroups.add(gid);
        renderTreeContent();
        syncUi(true);
      }
    });

    // 语言切换或权限更新后刷新目录树文案
    document.getElementById("languageSelect")?.addEventListener("change", () => {
      window.setTimeout(renderTreeContent, 30);
    });
    window.setTimeout(renderTreeContent, 600);

    renderTreeContent();
    syncUi(false);

    window.PowerPlanNavTree = {
      show: () => {
        if (mode === "dock") dockVisible = true;
        else floatVisible = true;
        renderTreeContent();
        syncUi(true);
      },
      hide: hideNavTree,
      setMode: (nextMode) => {
        mode = nextMode === "dock" ? "dock" : "float";
        if (mode === "dock") {
          dockVisible = true;
          floatVisible = false;
        } else {
          dockVisible = false;
          floatVisible = true;
        }
        syncUi(true);
      },
      getState: () => ({ mode, dockVisible, floatVisible, visible: (mode === "dock" && dockVisible) || floatVisible }),
    };
  }

  /** 全站图标自动增强引擎：为顶栏、高频按钮、结果分页与流转链接自动注入统一矢量图标 */
  function enhanceIconicUI() {
    const injectIcon = (el, iconName, extraClass = "ui-ico-sm") => {
      if (!el || !iconName || !UI_ICONS[iconName]) return;
      if (el.querySelector(".ui-ico, svg")) return;
      el.insertAdjacentHTML("afterbegin", renderIcon(iconName, extraClass));
    };

    // 1. 顶栏导航链接：按目标页面自动挂载页面图标
    document.querySelectorAll(".topbar a[href], .topnav a[href], .scada-nav-link[href], .scada-mini-link[href]").forEach((a) => {
      const href = String(a.getAttribute("href") || "").split("?")[0].split("/").pop().toLowerCase();
      if (PAGE_ICON_MAP[href]) {
        injectIcon(a, PAGE_ICON_MAP[href], "ui-ico-sm");
      }
    });

    // 2. 全站高频操作按钮与结果分页：按语义规则挂载高可读线性图标
    const TEXT_ICON_RULES = [
      [/^(启动|开始|运行|播放|Run|Start)/i, "play", "ui-ico-sm ui-ico-accent"],
      [/^(暂停|Pause)/i, "pause", "ui-ico-sm ui-ico-warn"],
      [/^(排队|加入队列|Queue)/i, "queue", "ui-ico-sm ui-ico-warn"],
      [/^(停止|中止|Stop)/i, "stop", "ui-ico-sm ui-ico-danger"],
      [/^(新建|新增|添加|New|Add)/i, "plus", "ui-ico-sm ui-ico-accent"],
      [/^(保存|Save)/i, "save", "ui-ico-sm ui-ico-ok"],
      [/^(复制|Copy)/i, "copy", "ui-ico-sm"],
      [/^(修改名称|重命名|Rename)/i, "edit", "ui-ico-sm"],
      [/^(删除|清理|清空|Delete|Clear)/i, "trash", "ui-ico-sm ui-ico-danger"],
      [/^(导入|Import)/i, "upload", "ui-ico-sm"],
      [/^(导出|下载|打印|Export|Print)/i, "download", "ui-ico-sm"],
      [/^(分享|Share)/i, "share", "ui-ico-sm ui-ico-aurora"],
      [/^(刷新|Refresh)/i, "refresh", "ui-ico-sm"],
      [/^(重置|Reset)/i, "reset", "ui-ico-sm"],
      [/^(生成工况方案|生成并排队|生成|Create)/i, "sparkles", "ui-ico-sm ui-ico-accent"],
      [/^(潮流接线图|Power Flow)/i, "topology", "ui-ico-sm ui-ico-accent"],
      [/^(结果概览|概览|Overview)/i, "chart", "ui-ico-sm"],
      [/^(经济性|经济|成本|Cost|Econ)/i, "coin", "ui-ico-sm ui-ico-warn"],
      [/^(安全性|可靠|Safety|Reliab)/i, "shield", "ui-ico-sm ui-ico-ok"],
      [/^(曲线|频率|Curve|Freq)/i, "wave", "ui-ico-sm ui-ico-accent"],
      [/^(工程洞察|洞察|Insight)/i, "sparkles", "ui-ico-sm ui-ico-aurora"],
      [/^(运行日志|日志|Log)/i, "logs", "ui-ico-sm"],
      [/^(对比|加入对比|深度对比|Compare)/i, "compare", "ui-ico-sm ui-ico-aurora"],
      [/^(扫参|批量扫参|Sweep)/i, "sweep", "ui-ico-sm ui-ico-accent"],
      [/^(简报|综合简报|Report)/i, "report", "ui-ico-sm"],
      [/^(南极气象|气象|Weather)/i, "snowflake", "ui-ico-sm ui-ico-accent"],
      [/^(规划配置与年流)/i, "topology", "ui-ico-sm"],
      [/^(典型日校核)/i, "sun", "ui-ico-sm"],
    ];

    document.querySelectorAll("button:not(.nav-tree-group-head):not(.nav-tree-hide-btn):not(.ui-toast-close)").forEach((btn) => {
      if (btn.closest("td")) return; // 严禁干扰表格单元格内嵌控件
      const label = (btn.textContent || "").trim();
      if (!label) return;
      for (const [re, iconName, cls] of TEXT_ICON_RULES) {
        if (re.test(label)) {
          injectIcon(btn, iconName, cls);
          break;
        }
      }
    });
  }

  /** 立即在脚本加载时预设主题，消除首屏闪烁 */
  setTheme(getTheme(), { silent: true });

  function boot() {
    setTheme(getTheme(), { silent: true });
    mountTopbarUtilities();
    mountGlobalTaskDrawer();
    mountCommandPalette();
    mountGlobalNavTree();
    mountCompactCommandActionHub();
    mountSidebarSplitter();
    enhanceSchemeRail();
    bindGlobalShortcuts();
    enhanceIconicUI();
  }

  window.PowerPlanUI = {
    THEMES,
    UI_ICONS,
    icon: renderIcon,
    getTheme,
    setTheme,
    isDarkTheme,
    getChartPalette,
    toast,
    confirm: confirmDialog,
    dangerConfirm: (message, options = {}) => confirmDialog(message, { ...options, danger: true }),
    prompt: promptDialog,
    alert: (message, options = {}) => toast(message, options),
    mountTopbarUtilities,
    enhanceIconicUI,
    fetchJson,
    clearClientCache,
    renderSkeleton,
    renderStaleBanner,
    exportSvgAsPng,
    exportSvgAsSvg,
    exportCanvasAsPng,
    exportRowsAsCsv,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
