const taskState = {
  tasks: [],
  loading: false,
  pollTimer: null,
  heightSyncFrame: 0,
  evaluationSchemeFilter: "",
};
const TASK_SECTION_MIN_HEIGHT = 140;
const TASK_COLUMN_GROUP = `
      <colgroup>
        <col class="task-col-scheme">
        <col class="task-col-result">
        <col class="task-col-status">
        <col class="task-col-process">
        <col class="task-col-start">
        <col class="task-col-end">
        <col class="task-col-elapsed">
        <col class="task-col-log">
        <col class="task-col-actions">
      </colgroup>
`;

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("optimizationTaskTable")?.addEventListener("click", handleTaskAction);
  document.getElementById("evaluationTaskTable")?.addEventListener("click", handleTaskAction);
  document.getElementById("evaluationSchemeFilter")?.addEventListener("change", handleEvaluationSchemeFilterChange);
  window.addEventListener("resize", scheduleTaskSectionHeights);
  loadTasks().catch(showTaskError);
  taskState.pollTimer = window.setInterval(() => loadTasks({ silent: true }).catch(showTaskError), 4000);
});

async function taskApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.error || "请求失败");
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

async function loadTasks(options = {}) {
  if (taskState.loading) return;
  taskState.loading = true;
  if (!options.silent) setTaskError("");
  try {
    const payload = await taskApi("/api/tasks");
    taskState.tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
    renderTasks();
  } finally {
    taskState.loading = false;
  }
}

function renderTasks() {
  const hadEvaluationSchemeFilter = Boolean(taskState.evaluationSchemeFilter);
  const filterReset = renderEvaluationSchemeFilter();
  renderTaskSection("optimization", "optimizationTaskTable", "暂无规划计算任务");
  renderTaskSection("evaluation", "evaluationTaskTable", "暂无方案评估任务");
  if (!hadEvaluationSchemeFilter || filterReset || !taskState.evaluationSchemeFilter) {
    scheduleTaskSectionHeights();
  }
}

function renderTaskSection(taskTypeKey, targetId, emptyText) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const tasks = filteredTasksForSection(taskTypeKey);
  if (!tasks.length) {
    target.innerHTML = `<div class="task-empty">${escapeHtml(emptyText)}</div>`;
    translateNode(target);
    return;
  }
  target.innerHTML = `
    <table>
      ${TASK_COLUMN_GROUP}
      <thead>
        <tr>
          <th>任务所用方案</th>
          <th>任务所用结果</th>
          <th>任务状态</th>
          <th>进程号</th>
          <th>计算开始时刻</th>
          <th>计算结束时刻</th>
          <th>计算总用时(秒)</th>
          <th>最新更新日志</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${tasks.map(renderTaskRow).join("")}
      </tbody>
    </table>
  `;
  translateNode(target);
}

function filteredTasksForSection(taskTypeKey) {
  const tasks = taskState.tasks.filter((task) => task.task_type_key === taskTypeKey);
  if (taskTypeKey !== "evaluation" || !taskState.evaluationSchemeFilter) return tasks;
  return tasks.filter((task) => String(task.scheme || "") === taskState.evaluationSchemeFilter);
}

function renderEvaluationSchemeFilter() {
  const select = document.getElementById("evaluationSchemeFilter");
  if (!select) return false;
  const schemeNames = Array.from(
    new Set(taskState.tasks.filter((task) => task.task_type_key === "evaluation").map((task) => String(task.scheme || "").trim()).filter(Boolean))
  ).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
  let filterReset = false;
  if (taskState.evaluationSchemeFilter && !schemeNames.includes(taskState.evaluationSchemeFilter)) {
    taskState.evaluationSchemeFilter = "";
    filterReset = true;
  }
  select.innerHTML = [`<option value="">全部方案</option>`, ...schemeNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)].join("");
  select.value = taskState.evaluationSchemeFilter;
  translateNode(select);
  return filterReset;
}

function handleEvaluationSchemeFilterChange(event) {
  taskState.evaluationSchemeFilter = String(event.target?.value || "");
  renderTaskSection("evaluation", "evaluationTaskTable", "暂无方案评估任务");
  if (!taskState.evaluationSchemeFilter) {
    scheduleTaskSectionHeights();
  }
}

function renderTaskRow(task) {
  const statusClass = taskStatusClass(task.status);
  const queueText = task.queue_position ? `#${task.queue_position}` : "";
  const terminalAction = taskTerminalAction(task);
  return `
    <tr>
      <td>${escapeHtml(task.scheme || "-")}</td>
      <td>${escapeHtml(task.result || "-")}</td>
      <td><span class="task-status-pill ${statusClass}">${escapeHtml(task.status || "未计算")}${queueText ? ` <em>${escapeHtml(queueText)}</em>` : ""}</span></td>
      <td>${escapeHtml(task.process_id || "-")}</td>
      <td>${escapeHtml(task.start_time || "-")}</td>
      <td>${escapeHtml(task.end_time || "-")}</td>
      <td>${escapeHtml(task.elapsed_seconds ?? 0)}</td>
      <td class="task-log-cell" title="${escapeHtml(task.latest_log || "")}">${escapeHtml(task.latest_log || "-")}</td>
      <td>
        <div class="task-actions">
          <button class="primary" type="button" data-task-action="start" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_start ? "" : "disabled"}>立刻启动</button>
          <button type="button" data-task-action="queue" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_queue ? "" : "disabled"}>加入排队</button>
          <button class="danger" type="button" data-task-action="${escapeHtml(terminalAction.action)}" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${terminalAction.enabled ? "" : "disabled"}>${escapeHtml(terminalAction.label)}</button>
        </div>
      </td>
    </tr>
  `;
}

function taskTerminalAction(task) {
  if (task.queued) return { action: "cancel_queue", label: "退出队列", enabled: true };
  if (task.can_stop) return { action: "stop", label: "停止计算", enabled: true };
  return { action: "stop", label: "停止计算", enabled: false };
}

function taskStatusClass(status) {
  if (status === "计算中") return "running";
  if (status === "排队中") return "queued";
  if (status === "完成计算") return "completed";
  return "idle";
}

async function handleTaskAction(event) {
  const button = event.target?.closest?.("[data-task-action]");
  if (!button || button.disabled) return;
  button.disabled = true;
  setTaskError("");
  try {
    const payload = await taskApi("/api/tasks/control", {
      method: "POST",
      body: JSON.stringify({
        action: button.dataset.taskAction,
        task_type: button.dataset.taskType,
        scheme: button.dataset.scheme,
        result: button.dataset.result,
      }),
    });
    taskState.tasks = Array.isArray(payload.tasks) ? payload.tasks : taskState.tasks;
    renderTasks();
  } catch (error) {
    showTaskError(error);
    await loadTasks({ silent: true }).catch(() => null);
  }
}

function showTaskError(error) {
  setTaskError(error?.message || "请求失败");
}

function setTaskError(message) {
  const target = document.getElementById("taskError");
  if (!target) return;
  target.textContent = message || "";
  target.hidden = !message;
  scheduleTaskSectionHeights();
}

function scheduleTaskSectionHeights() {
  if (taskState.heightSyncFrame) {
    window.cancelAnimationFrame(taskState.heightSyncFrame);
  }
  taskState.heightSyncFrame = window.requestAnimationFrame(() => {
    taskState.heightSyncFrame = 0;
    syncTaskSectionHeights();
  });
}

function syncTaskSectionHeights() {
  const panel = document.querySelector(".tasks-panel");
  const optimizationSection = panel?.querySelector(".task-section-optimization");
  const evaluationSection = panel?.querySelector(".task-section-evaluation");
  if (!panel || !optimizationSection || !evaluationSection) return;

  const styles = window.getComputedStyle(panel);
  const paddingTop = parseFloat(styles.paddingTop || "0") || 0;
  const paddingBottom = parseFloat(styles.paddingBottom || "0") || 0;
  const rowGap = parseFloat(styles.rowGap || styles.gap || "0") || 0;
  const errorHeight = document.getElementById("taskError")?.hidden ? 0 : (document.getElementById("taskError")?.getBoundingClientRect().height || 0);
  const panelContentHeight = Math.max(0, panel.clientHeight - paddingTop - paddingBottom);
  const availableHeight = Math.max(TASK_SECTION_MIN_HEIGHT * 2, panelContentHeight - rowGap);

  const optimizationDesiredHeight = measureTaskSectionHeight(optimizationSection);
  const evaluationDesiredHeight = measureTaskSectionHeight(evaluationSection);
  const totalDesiredHeight = Math.max(optimizationDesiredHeight + evaluationDesiredHeight, 1);

  let optimizationHeight;
  if (totalDesiredHeight <= availableHeight) {
    const remainingHeight = availableHeight - totalDesiredHeight;
    optimizationHeight = optimizationDesiredHeight + remainingHeight * (optimizationDesiredHeight / totalDesiredHeight);
  } else {
    optimizationHeight = (availableHeight * optimizationDesiredHeight) / totalDesiredHeight;
  }
  optimizationHeight = clamp(optimizationHeight, TASK_SECTION_MIN_HEIGHT, availableHeight - TASK_SECTION_MIN_HEIGHT);
  const evaluationHeight = Math.max(TASK_SECTION_MIN_HEIGHT, availableHeight - optimizationHeight);

  panel.style.setProperty("--optimization-task-section-height", `${Math.round(optimizationHeight)}px`);
  panel.style.setProperty("--evaluation-task-section-height", `${Math.round(evaluationHeight)}px`);
}

function measureTaskSectionHeight(section) {
  const styles = window.getComputedStyle(section);
  const rowGap = parseFloat(styles.rowGap || styles.gap || "0") || 0;
  const headHeight = section.querySelector(".task-section-head")?.getBoundingClientRect().height || 0;
  const tableElement = section.querySelector(".task-table table");
  const emptyElement = section.querySelector(".task-empty");
  const contentHeight = tableElement?.getBoundingClientRect().height || emptyElement?.getBoundingClientRect().height || 0;
  return Math.max(TASK_SECTION_MIN_HEIGHT, Math.ceil(headHeight + rowGap + contentHeight));
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
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
