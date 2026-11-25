(() => {
  const THEME_STORAGE_KEY = "powerPlanTheme";
  const LEGACY_THEME_STORAGE_KEY = "powerPlanHomeTheme";
  const DEFAULT_THEME = "precision-dark";

  const THEMES = [
    { id: "precision-dark", label: "精密暗黑", dark: true },
    { id: "minimalist-light", label: "极简明亮", dark: false },
    { id: "sci-fi-cyan", label: "科幻 · 电光青", dark: true },
    { id: "sci-fi-purple", label: "科幻 · 赛博紫", dark: true },
    { id: "sci-fi-matrix", label: "科幻 · 矩阵绿", dark: true },
  ];

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

  /** 在全站顶栏注入统一的主题切换器与工具容器 */
  function mountTopbarUtilities() {
    const topbar = document.querySelector(".topbar");
    if (!topbar) return;

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

    // 注入主题切换器
    if (!document.getElementById("themeSelect")) {
      const themeWrap = document.createElement("label");
      themeWrap.className = "theme-switch";
      themeWrap.setAttribute("title", tr("显示主题"));
      themeWrap.innerHTML =
        `<svg class="topbar-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"></path></svg>` +
        `<select id="themeSelect" class="topbar-select" aria-label="显示主题">${THEMES.map(
          (item) => `<option value="${item.id}">${item.label}</option>`,
        ).join("")}</select>`;
      const firstChild = utilities.firstChild;
      utilities.insertBefore(themeWrap, firstChild);

      const select = themeWrap.querySelector("select");
      select.value = getTheme();
      select.addEventListener("change", (event) => setTheme(event.target.value));
    }

    // 如果语言切换器已由 i18n.js 插入，将其归位到工具容器内保持整齐对齐
    const langWrap = topbar.querySelector(".language-switch");
    const userStatus = utilities.querySelector(".user-status");
    if (langWrap && langWrap.parentElement !== utilities) {
      if (userStatus) utilities.insertBefore(langWrap, userStatus);
      else utilities.appendChild(langWrap);
    }

    // 确保管理员在任意子页面都能一键访问用户管理
    if (userStatus && !userStatus.querySelector('a[href="users.html"]')) {
      const logoutBtn = userStatus.querySelector("[data-logout]");
      const adminLink = document.createElement("a");
      adminLink.href = "users.html";
      adminLink.dataset.adminOnly = "";
      adminLink.hidden = true;
      adminLink.textContent = "用户管理";
      if (logoutBtn) userStatus.insertBefore(adminLink, logoutBtn);
      else userStatus.appendChild(adminLink);
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

  /** 立即在脚本加载时预设主题，消除首屏闪烁 */
  setTheme(getTheme(), { silent: true });

  function boot() {
    setTheme(getTheme(), { silent: true });
    mountTopbarUtilities();
    enhanceSchemeRail();
    bindGlobalShortcuts();
  }

  window.PowerPlanUI = {
    THEMES,
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
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
