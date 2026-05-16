const taskState = {
  tasks: [],
  loading: false,
  pollTimer: null,
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refreshTasks")?.addEventListener("click", () => loadTasks().catch(showTaskError));
  document.getElementById("taskTable")?.addEventListener("click", handleTaskAction);
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
  const target = document.getElementById("taskTable");
  if (!target) return;
  if (!taskState.tasks.length) {
    target.innerHTML = '<div class="task-empty">暂无任务</div>';
    if (window.PowerPlanI18n) window.PowerPlanI18n.translate(target, window.PowerPlanI18n.currentLanguage());
    return;
  }
  target.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>任务类型</th>
          <th>任务所用方案</th>
          <th>任务所用结果</th>
          <th>任务状态</th>
          <th>进程号</th>
          <th>计算开始时刻</th>
          <th>计算总用时(秒)</th>
          <th>最新更新日志</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${taskState.tasks.map(renderTaskRow).join("")}
      </tbody>
    </table>
  `;
  if (window.PowerPlanI18n) window.PowerPlanI18n.translate(target, window.PowerPlanI18n.currentLanguage());
}

function renderTaskRow(task) {
  const statusClass = taskStatusClass(task.status);
  const queueText = task.queue_position ? `#${task.queue_position}` : "";
  return `
    <tr>
      <td>${escapeHtml(task.task_type || "-")}</td>
      <td>${escapeHtml(task.scheme || "-")}</td>
      <td>${escapeHtml(task.result || "-")}</td>
      <td><span class="task-status-pill ${statusClass}">${escapeHtml(task.status || "未计算")}${queueText ? ` <em>${escapeHtml(queueText)}</em>` : ""}</span></td>
      <td>${escapeHtml(task.process_id || "-")}</td>
      <td>${escapeHtml(task.start_time || "-")}</td>
      <td>${escapeHtml(task.elapsed_seconds ?? 0)}</td>
      <td class="task-log-cell" title="${escapeHtml(task.latest_log || "")}">${escapeHtml(task.latest_log || "-")}</td>
      <td>
        <div class="task-actions">
          <button class="primary" type="button" data-task-action="start" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_start ? "" : "disabled"}>立刻启动</button>
          <button type="button" data-task-action="queue" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_queue ? "" : "disabled"}>加入排队</button>
          <button class="danger" type="button" data-task-action="stop" data-task-type="${escapeHtml(task.task_type_key || "")}" data-scheme="${escapeHtml(task.scheme || "")}" data-result="${escapeHtml(task.result || "")}" ${task.can_stop ? "" : "disabled"}>停止</button>
        </div>
      </td>
    </tr>
  `;
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
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
