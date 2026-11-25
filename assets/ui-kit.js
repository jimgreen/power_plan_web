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
      schedulePoll(3000);
    };

    const closeDrawer = () => {
      backdrop.hidden = true;
      drawer.hidden = true;
      pill.setAttribute("aria-expanded", "false");
      schedulePoll(6000);
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
        const resp = await fetch("/api/tasks");
        if (!resp.ok) return;
        const data = await resp.json().catch(() => ({}));
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
      } catch (_) {
        // 静默忽略后台轮询偶发失败
      } finally {
        fetching = false;
      }
    };

    const schedulePoll = (delayMs) => {
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = window.setInterval(refreshTasks, delayMs);
    };

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

  /** 在规划/评估/可靠性/频率页面命令卡底部挂载跨页工作流直达动作条 */
  function mountWorkflowNextStrip() {
    const file = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    const targetPages = new Set(["optimize.html", "evaluation.html", "reliability.html", "frequency.html"]);
    if (!targetPages.has(file)) return;
    const hostCard = document.querySelector(".optimization-command-card, .reliability-main > .optimization-command-card");
    if (!hostCard || hostCard.querySelector(".workflow-next-strip")) return;

    const strip = document.createElement("div");
    strip.className = "workflow-next-strip";
    strip.setAttribute("aria-label", tr("工作流直达"));
    hostCard.appendChild(strip);

    const linksDef = [
      { page: "planning.html", label: "参数维护", needFile: false },
      { page: "optimize.html", label: "规划求解", needFile: false },
      { page: "evaluation.html", label: "方案评估", needFile: true },
      { page: "reliability.html", label: "供电可靠性", needFile: true },
      { page: "frequency.html", label: "频率计算", needFile: true },
      { page: "comparison.html", label: "加入对比", isCompare: true },
      { page: "sensitivity.html", label: "批量扫参", needFile: false },
      { page: "report.html", label: "综合简报", needFile: true },
    ];

    const renderStrip = () => {
      const ctx = window.PowerPlanPageState?.getActiveContext?.() || { scheme: "", filename: "" };
      const scheme = ctx.scheme || "";
      const filename = ctx.filename || (file === "optimize.html" ? "opt_results.xlsx" : "");
      const items = linksDef
        .filter((item) => item.page !== file)
        .map((item) => {
          let href = item.page;
          if (item.isCompare && scheme && filename) {
            href = `comparison.html?add=${encodeURIComponent(`${scheme}|${filename}`)}`;
          } else if (scheme) {
            const p = new URLSearchParams();
            p.set("scheme", scheme);
            if (item.needFile && filename) p.set("file", filename);
            href = `${item.page}?${p.toString()}`;
          }
          return `<a class="workflow-next-link" href="${href}">${item.label}</a>`;
        });
      strip.innerHTML = `<span class="workflow-next-label">快捷流转</span><div class="workflow-next-links">${items.join("")}</div>`;
      if (window.PowerPlanI18n) {
        window.PowerPlanI18n.translate(strip, window.PowerPlanI18n.currentLanguage());
      }
    };

    renderStrip();
    window.addEventListener("powerplan:contextchange", renderStrip);
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

    // 模式 A：evaluation.html / frequency.html 已有原生纵向分割条，直接叠加一键隐藏/展开与折叠恢复能力
    const existingHandle = document.querySelector("#evaluationMainResizeHandle, #frequencyMainResizeHandle");
    const evalWorkspace = existingHandle?.closest(".evaluation-workspace");
    if (existingHandle && evalWorkspace && !existingHandle.querySelector(".sidebar-splitter-toggle")) {
      const saved = readLayout();
      let collapsed = Boolean(saved.collapsed);
      let lastWidth = Number(saved.width) || 340;
      const toggleBtn = createToggleButton(collapsed);

      const applyEvalCollapsed = (nextCollapsed, persist = true) => {
        if (nextCollapsed && !collapsed) {
          const curVar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--evaluation-result-rail-width"));
          if (Number.isFinite(curVar) && curVar >= 160) lastWidth = Math.round(curVar);
        }
        collapsed = Boolean(nextCollapsed);
        evalWorkspace.classList.toggle("is-sidebar-collapsed", collapsed);
        toggleBtn._syncCollapsed(collapsed);
        if (!collapsed && lastWidth >= 160) {
          document.documentElement.style.setProperty("--evaluation-result-rail-width", `${lastWidth}px`);
        }
        if (persist) writeLayout({ collapsed, width: lastWidth });
        triggerResize();
      };

      existingHandle.classList.add("has-sidebar-toggle");
      existingHandle.appendChild(toggleBtn);
      toggleBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
      toggleBtn.addEventListener("mousedown", (e) => e.stopPropagation());
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyEvalCollapsed(!collapsed);
      });
      existingHandle.addEventListener("dblclick", (e) => {
        if (e.target.closest(".sidebar-splitter-toggle")) return;
        applyEvalCollapsed(!collapsed);
      });
      if (collapsed) applyEvalCollapsed(true, false);
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
    mountGlobalTaskDrawer();
    mountWorkflowNextStrip();
    mountSidebarSplitter();
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
