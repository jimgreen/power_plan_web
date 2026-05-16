const taskState = {
  tasks: [],
  loading: false,
  pollTimer: null,
  optimizationTaskTableHeight: null,
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refreshTasks")?.addEventListener("click", () => loadTasks().catch(showTaskError));
  document.getElementById("optimizationTaskTable")?.addEventListener("click", handleTaskAction);
  document.getElementById("evaluationTaskTable")?.addEventListener("click", handleTaskAction);
  bindTaskTableResizeHandle();
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
  renderTaskSection("optimization", "optimizationTaskTable", "暂无规划计算任务");
  renderTaskSection("evaluation", "evaluationTaskTable", "暂无方案评估任务");
}

function renderTaskSection(taskTypeKey, targetId, emptyText) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const tasks = taskState.tasks.filter((task) => task.task_type_key === taskTypeKey);
  if (!tasks.length) {
    target.innerHTML = `<div class="task-empty">${escapeHtml(emptyText)}</div>`;
    translateNode(target);
    return;
  }
  target.innerHTML = `
    <table>
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

function bindTaskTableResizeHandle() {
  const handle = document.getElementById("taskTableResizeHandle");
  const panel = handle?.closest(".tasks-panel");
  if (!handle || !panel) return;

  const applyHeight = (height) => setOptimizationTaskTableHeight(panel, handle, height);
  const currentHeight = () =>
    taskState.optimizationTaskTableHeight ||
    panel.querySelector(".task-section-optimization")?.getBoundingClientRect().height ||
    300;

  applyHeight(currentHeight());

  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = currentHeight();
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
    const steps = { ArrowUp: -18, ArrowDown: 18, PageUp: -72, PageDown: 72 };
    if (event.key in steps) {
      event.preventDefault();
      applyHeight(currentHeight() + steps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      applyHeight(taskTableHeightBounds(panel).min);
    } else if (event.key === "End") {
      event.preventDefault();
      applyHeight(taskTableHeightBounds(panel).max);
    }
  });
}

function setOptimizationTaskTableHeight(panel, handle, height) {
  const bounds = taskTableHeightBounds(panel);
  const numericHeight = Number(height);
  const safeHeight = Math.min(Math.max(Number.isFinite(numericHeight) ? numericHeight : bounds.min, bounds.min), bounds.max);
  const roundedHeight = Math.round(safeHeight);
  taskState.optimizationTaskTableHeight = roundedHeight;
  panel.style.setProperty("--optimization-task-table-height", `${roundedHeight}px`);
  handle?.setAttribute("aria-valuenow", String(roundedHeight));
  handle?.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
  handle?.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
}

function taskTableHeightBounds(panel) {
  const min = 120;
  const height = panel?.clientHeight || window.innerHeight;
  return {
    min,
    max: Math.max(min, height - 220),
  };
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
