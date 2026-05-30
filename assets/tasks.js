const taskState = {
  tasks: [],
  loading: false,
  pollTimer: null,
  heightSyncFrame: 0,
  activeTaskType: "optimization",
  evaluationSchemeFilter: "",
  frequencySchemeFilter: "",
  lastRenderedTaskSignature: "",
};
const TASKS_PAGE_STATE_KEY = "tasks";
const TASK_COLUMN_GROUP = `
      <colgroup>
        <col class="task-col-scheme">
        <col class="task-col-result">
        <col class="task-col-actions">
        <col class="task-col-status">
        <col class="task-col-process">
        <col class="task-col-start">
        <col class="task-col-end">
        <col class="task-col-elapsed">
        <col class="task-col-log">
      </colgroup>
`;

document.addEventListener("DOMContentLoaded", () => {
  restoreTasksPageState();
  document.getElementById("optimizationTaskTable")?.addEventListener("click", handleTaskAction);
  document.getElementById("evaluationTaskTable")?.addEventListener("click", handleTaskAction);
  document.getElementById("frequencyTaskTable")?.addEventListener("click", handleTaskAction);
  document.querySelectorAll("[data-task-page]").forEach((button) => {
    button.addEventListener("click", () => switchTaskPage(button.dataset.taskPage || "optimization"));
  });
  document.getElementById("evaluationSchemeFilter")?.addEventListener("change", handleEvaluationSchemeFilterChange);
  document.getElementById("frequencySchemeFilter")?.addEventListener("change", handleFrequencySchemeFilterChange);
  loadTasks().catch(showTaskError);
  taskState.pollTimer = window.setInterval(() => loadTasks({ silent: true }).catch(showTaskError), 4000);
});

function restoreTasksPageState() {
  const saved = window.PowerPlanPageState?.read?.(TASKS_PAGE_STATE_KEY, {}) || {};
  if (["optimization", "evaluation", "frequency"].includes(saved.activeTaskType)) {
    taskState.activeTaskType = saved.activeTaskType;
  }
  if (typeof saved.evaluationSchemeFilter === "string") taskState.evaluationSchemeFilter = saved.evaluationSchemeFilter;
  if (typeof saved.frequencySchemeFilter === "string") taskState.frequencySchemeFilter = saved.frequencySchemeFilter;
  updateTaskPageVisibility();
}

function tasksPageStateSnapshot() {
  return {
    activeTaskType: taskState.activeTaskType,
    evaluationSchemeFilter: taskState.evaluationSchemeFilter || "",
    frequencySchemeFilter: taskState.frequencySchemeFilter || "",
  };
}

function rememberTasksPageState(partial = {}) {
  window.PowerPlanPageState?.write?.(TASKS_PAGE_STATE_KEY, { ...tasksPageStateSnapshot(), ...(partial || {}) });
}

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
    applyTasksPayload(payload);
  } finally {
    taskState.loading = false;
  }
}

function applyTasksPayload(payload, options = {}) {
  const nextTasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  const signature = JSON.stringify(nextTasks);
  if (!options.force && signature === taskState.lastRenderedTaskSignature) return false;
  taskState.tasks = nextTasks;
  taskState.lastRenderedTaskSignature = signature;
  renderTasks();
  return true;
}

function renderTasks() {
  const hadEvaluationSchemeFilter = Boolean(taskState.evaluationSchemeFilter);
  const hadFrequencySchemeFilter = Boolean(taskState.frequencySchemeFilter);
  const evaluationFilterReset = renderSchemeFilter("evaluation", "evaluationSchemeFilter", "evaluationSchemeFilter");
  const frequencyFilterReset = renderSchemeFilter("frequency", "frequencySchemeFilter", "frequencySchemeFilter");
  renderTaskSection("optimization", "optimizationTaskTable", "暂无规划计算任务");
  renderTaskSection("evaluation", "evaluationTaskTable", "暂无方案评估任务");
  renderTaskSection("frequency", "frequencyTaskTable", "暂无频率计算任务");
  updateTaskPageVisibility();
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
          <th>操作</th>
          <th>任务状态</th>
          <th>进程号</th>
          <th>计算开始时刻</th>
          <th>计算结束时刻</th>
          <th>计算总用时(秒)</th>
          <th>最新更新日志</th>
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
  if (taskTypeKey === "evaluation" && taskState.evaluationSchemeFilter) {
    return tasks.filter((task) => String(task.scheme || "") === taskState.evaluationSchemeFilter);
  }
  if (taskTypeKey === "frequency" && taskState.frequencySchemeFilter) {
    return tasks.filter((task) => String(task.scheme || "") === taskState.frequencySchemeFilter);
  }
  return tasks;
}

function renderSchemeFilter(taskTypeKey, selectId, stateKey) {
  const select = document.getElementById(selectId);
  if (!select) return false;
  const schemeNames = Array.from(
    new Set(taskState.tasks.filter((task) => task.task_type_key === taskTypeKey).map((task) => String(task.scheme || "").trim()).filter(Boolean))
  ).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
  let filterReset = false;
  if (taskState[stateKey] && !schemeNames.includes(taskState[stateKey])) {
    taskState[stateKey] = "";
    filterReset = true;
    rememberTasksPageState({ [stateKey]: "" });
  }
  select.innerHTML = [`<option value="">全部方案</option>`, ...schemeNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)].join("");
  select.value = taskState[stateKey];
  translateNode(select);
  return filterReset;
}

function handleEvaluationSchemeFilterChange(event) {
  taskState.evaluationSchemeFilter = String(event.target?.value || "");
  rememberTasksPageState({ evaluationSchemeFilter: taskState.evaluationSchemeFilter });
  renderTaskSection("evaluation", "evaluationTaskTable", "暂无方案评估任务");
}

function handleFrequencySchemeFilterChange(event) {
  taskState.frequencySchemeFilter = String(event.target?.value || "");
  rememberTasksPageState({ frequencySchemeFilter: taskState.frequencySchemeFilter });
  renderTaskSection("frequency", "frequencyTaskTable", "暂无频率计算任务");
}

function switchTaskPage(taskTypeKey) {
  if (!["optimization", "evaluation", "frequency"].includes(taskTypeKey)) return;
  taskState.activeTaskType = taskTypeKey;
  rememberTasksPageState({ activeTaskType: taskState.activeTaskType });
  updateTaskPageVisibility();
}

function updateTaskPageVisibility() {
  document.querySelectorAll("[data-task-page]").forEach((button) => {
    const active = button.dataset.taskPage === taskState.activeTaskType;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-task-section]").forEach((section) => {
    const active = section.dataset.taskSection === taskState.activeTaskType;
    section.classList.toggle("active", active);
    section.hidden = !active;
  });
}

function renderTaskRow(task) {
  const statusClass = taskStatusClass(task.status);
  const queueText = task.queue_position ? `#${task.queue_position}` : "";
  const terminalAction = taskTerminalAction(task);
  return `
    <tr>
      <td>${escapeHtml(task.scheme || "-")}</td>
      <td>${escapeHtml(task.result || "-")}</td>
      <td class="task-actions-cell">
        <div class="task-actions">
          <button class="primary" type="button" data-task-action="start" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_start ? "" : "disabled"}>启动</button>
          <button type="button" data-task-action="queue" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_queue ? "" : "disabled"}>排队</button>
          <button class="danger" type="button" data-task-action="${escapeHtml(terminalAction.action)}" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${terminalAction.enabled ? "" : "disabled"}>${escapeHtml(terminalAction.label)}</button>
        </div>
      </td>
      <td><span class="task-status-pill ${statusClass}">${escapeHtml(task.status || "未计算")}${queueText ? ` <em>${escapeHtml(queueText)}</em>` : ""}</span></td>
      <td>${escapeHtml(task.process_id || "-")}</td>
      <td>${escapeHtml(task.start_time || "-")}</td>
      <td>${escapeHtml(task.end_time || "-")}</td>
      <td>${escapeHtml(task.elapsed_seconds ?? 0)}</td>
      <td class="task-log-cell" title="${escapeHtml(task.latest_log || "")}">${escapeHtml(task.latest_log || "-")}</td>
    </tr>
  `;
}

function taskTerminalAction(task) {
  if (task.queued) return { action: "cancel_queue", label: "离队", enabled: true };
  if (task.can_stop) return { action: "stop", label: "停止", enabled: true };
  return { action: "stop", label: "停止", enabled: false };
}

function taskStatusClass(status) {
  if (status === "计算中") return "running";
  if (status === "排队中") return "queued";
  if (status === "退出队列") return "dequeued";
  if (status === "完成计算") return "completed";
  if (status === "计算中止") return "interrupted";
  if (status === "计算失败") return "failed";
  if (status === "计算超时") return "timeout";
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
    applyTasksPayload(payload, { force: true });
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
