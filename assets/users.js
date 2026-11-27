(() => {
  const tableHost = document.getElementById("usersTable");
  const status = document.getElementById("usersStatus");

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.message || "请求失败");
    }
    return data;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
  }

  function render(users) {
    if (!tableHost) return;
    tableHost.innerHTML = `<table><thead><tr><th>用户名称</th><th>权限</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${users
      .map((user) => `<tr data-user-id="${user.id}">
        <td>${escapeHtml(user.username)}</td>
        <td><select data-role><option value="admin" ${user.role === "admin" ? "selected" : ""}>管理员</option><option value="user" ${user.role === "user" ? "selected" : ""}>普通用户</option></select></td>
        <td>${escapeHtml(user.created_at)}</td>
        <td><button class="danger" data-delete-user type="button">删除</button></td>
      </tr>`)
      .join("")}</tbody></table>`;
    tableHost.querySelectorAll("[data-role]").forEach((select) => {
      select.addEventListener("change", () => updateRole(select.closest("[data-user-id]").dataset.userId, select.value));
    });
    tableHost.querySelectorAll("[data-delete-user]").forEach((button) => {
      button.addEventListener("click", () => deleteUser(button.closest("[data-user-id]").dataset.userId));
    });
  }

  async function loadUsers() {
    const data = await requestJson("/api/users");
    render(data.users || []);
  }

  async function updateRole(id, role) {
    if (status) status.textContent = "正在保存...";
    try {
      await requestJson(`/api/users/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ role }) });
      if (status) status.textContent = "已保存";
      await loadUsers();
    } catch (error) {
      if (status) status.textContent = error.message;
      await loadUsers().catch(() => null);
    }
  }

  async function deleteUser(id) {
    const row = tableHost?.querySelector(`tr[data-user-id="${id}"]`);
    const username = row?.querySelector("td")?.textContent?.trim() || `#${id}`;
    const okDelete = window.PowerPlanUI ? await window.PowerPlanUI.dangerConfirm(`删除用户「${username}」？`, { confirmText: "删除" }) : confirm("确定删除该用户？");
    if (!okDelete) return;
    if (status) status.textContent = "正在删除...";
    try {
      await requestJson(`/api/users/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (status) status.textContent = "已删除";
      window.PowerPlanUI?.toast("已删除", { level: "success" });
      await loadUsers();
    } catch (error) {
      if (status) status.textContent = error.message;
    }
  }

  async function loadSystemStatus() {
    const data = await requestJson("/api/admin/system-status");
    renderSystemStatus(data);
  }

  function renderSystemStatus(data) {
    const env = data.environment || {};
    const tsEl = document.getElementById("sysDiagTimestamp");
    if (tsEl) tsEl.textContent = `更新时间：${data.timestamp || "—"} · Python ${env.python_version || "—"} · CVXPY ${env.cvxpy_version || "—"}`;

    const kpiHost = document.getElementById("sysDiagKpiStrip");
    if (kpiHost) {
      const kpis = [
        ["CPU 核数", String(env.cpu_count ?? "—")],
        ["规划方案数", String(env.schemes_count ?? 0)],
        ["运行 / 排队任务", `${env.running_tasks ?? 0} / ${env.queued_tasks ?? 0}`],
        ["SSE 实时连接", String(env.sse_subscribers ?? 0)],
        ["已缓存条目", String(env.total_cached_entries ?? 0)],
      ];
      kpiHost.innerHTML = kpis
        .map(([label, val]) => `<div class="sys-diag-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(val)}</strong></div>`)
        .join("");
    }

    const solverHost = document.getElementById("sysDiagSolverTable");
    if (solverHost) {
      const rows = Array.isArray(data.solvers) ? data.solvers : [];
      const badge = (ok) => (ok ? `<span class="sys-badge-ok">可用</span>` : `<span class="sys-badge-off">不可用</span>`);
      solverHost.innerHTML = `<table><thead><tr><th>求解器</th><th>原生接口</th><th>CVXPY 接口</th></tr></thead><tbody>${rows
        .map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${badge(r.native)}</td><td>${badge(r.cvxpy)}</td></tr>`)
        .join("")}</tbody></table>`;
    }

    const cacheHost = document.getElementById("sysDiagCacheTable");
    if (cacheHost) {
      const rows = Array.isArray(data.caches) ? data.caches : [];
      cacheHost.innerHTML = `<table><thead><tr><th>缓存模块</th><th>当前条目</th><th>上限</th></tr></thead><tbody>${rows
        .map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${escapeHtml(r.entries)}</td><td>${escapeHtml(r.max_entries || "—")}</td></tr>`)
        .join("")}</tbody></table>`;
    }

    if (window.PowerPlanI18n) {
      window.PowerPlanI18n.translate(document.getElementById("adminSystemPanel"), window.PowerPlanI18n.currentLanguage());
    }
  }

  async function clearAllCaches() {
    const ok = window.PowerPlanUI
      ? await window.PowerPlanUI.dangerConfirm("确认清空所有后端只读缓存与响应字节缓存？下次访问将自动重新加载。", {
          title: "确认清空缓存",
          confirmText: "清空缓存",
        })
      : confirm("确认清空所有缓存？");
    if (!ok) return;
    const btn = document.getElementById("sysDiagClearCacheBtn");
    if (btn) btn.disabled = true;
    try {
      const res = await requestJson("/api/admin/clear-caches", { method: "POST", body: "{}" });
      renderSystemStatus(res);
      window.PowerPlanUI?.toast?.(res.message || "缓存已清空", { level: "success" });
    } catch (error) {
      window.PowerPlanUI?.toast?.(error.message || "清空缓存失败", { level: "error" });
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindAdminTabs() {
    const tabBtns = document.querySelectorAll("[data-admin-tab]");
    const panels = document.querySelectorAll("[data-admin-panel]");
    const switchTab = (key) => {
      tabBtns.forEach((b) => {
        const active = b.dataset.adminTab === key;
        b.classList.toggle("active", active);
        b.setAttribute("aria-selected", String(active));
      });
      panels.forEach((p) => {
        const active = p.dataset.adminPanel === key;
        p.hidden = !active;
        p.classList.toggle("active", active);
      });
      const diagTools = document.getElementById("sysDiagHeaderTools");
      if (diagTools) diagTools.hidden = key !== "system";
      if (status) status.hidden = key === "system";
      if (key === "system") {
        loadSystemStatus().catch((error) => {
          if (status) status.textContent = error.message;
        });
      }
    };
    tabBtns.forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.adminTab || "users")));
    document.getElementById("sysDiagRefreshBtn")?.addEventListener("click", () => {
      loadSystemStatus()
        .then(() => window.PowerPlanUI?.toast?.("系统状态已刷新", { level: "info" }))
        .catch((err) => window.PowerPlanUI?.toast?.(err.message, { level: "error" }));
    });
    document.getElementById("sysDiagClearCacheBtn")?.addEventListener("click", clearAllCaches);
  }

  bindAdminTabs();
  loadUsers().catch((error) => {
    if (status) status.textContent = error.message;
  });
})();
