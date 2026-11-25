(() => {
  "use strict";

  const PAGE_STATE_KEY = "sensitivity";
  const PRESETS = {
    load_scale: [
      { label: "±20% (5档)", values: "0.8, 0.9, 1.0, 1.1, 1.2" },
      { label: "±30% (7档)", values: "0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3" },
    ],
    wind_scale: [
      { label: "±15% (5档)", values: "0.85, 0.925, 1.0, 1.075, 1.15" },
      { label: "0.7~1.3 (5档)", values: "0.7, 0.85, 1.0, 1.15, 1.3" },
    ],
    solar_scale: [
      { label: "±20% (5档)", values: "0.8, 0.9, 1.0, 1.1, 1.2" },
    ],
    diesel_price: [
      { label: "0.6~1.8 (5档)", values: "0.6, 0.9, 1.2, 1.5, 1.8" },
      { label: "1~5元 (5档)", values: "1, 2, 3, 4, 5" },
    ],
    green_power_ratio_lower: [
      { label: "50%~90% (5档)", values: "0.5, 0.6, 0.7, 0.8, 0.9" },
      { label: "60%~95% (5档)", values: "0.6, 0.7, 0.8, 0.9, 0.95" },
    ],
    storage_cost_scale: [
      { label: "0.6~1.4 (5档)", values: "0.6, 0.8, 1.0, 1.2, 1.4" },
    ],
  };

  const METRIC_LABELS = {
    lcoe: "度电成本 (元/kWh)",
    annual_cost: "年均总成本 (万元)",
    green_ratio: "绿电占比 (%)",
    diesel_fuel: "柴发耗油量",
    curtail_rate: "弃电率 (%)",
  };

  const state = {
    schemes: [],
    trackedItems: [], // [{ scheme, parameter_value, parameter_label }]
    rows: [],
    viewMode: "trend",
    metricKey: "lcoe",
    pollTimer: 0,
  };

  function escapeHtml(val) {
    return String(val ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function api(path, options = {}) {
    const resp = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.message || data.error || "请求失败");
    return data;
  }

  function saveState() {
    window.PowerPlanPageState?.write?.(PAGE_STATE_KEY, {
      trackedItems: state.trackedItems,
      viewMode: state.viewMode,
      metricKey: state.metricKey,
      currentScheme: document.getElementById("sensBaseScheme")?.value || "",
    });
  }

  function restoreState() {
    const saved = window.PowerPlanPageState?.read?.(PAGE_STATE_KEY, {}) || {};
    if (Array.isArray(saved.trackedItems)) {
      state.trackedItems = saved.trackedItems.filter((it) => it && it.scheme);
    }
    if (["trend", "pareto"].includes(saved.viewMode)) state.viewMode = saved.viewMode;
    if (METRIC_LABELS[saved.metricKey]) state.metricKey = saved.metricKey;
    return saved;
  }

  function renderPresets() {
    const key = document.getElementById("sensParamKey")?.value || "load_scale";
    const host = document.getElementById("sensPresetChips");
    if (!host) return;
    const list = PRESETS[key] || [];
    host.innerHTML = list
      .map((item) => `<button type="button" class="sens-preset-chip" data-preset-values="${escapeHtml(item.values)}">${escapeHtml(item.label)}</button>`)
      .join("");
    host.querySelectorAll("[data-preset-values]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const input = document.getElementById("sensValuesInput");
        if (input) input.value = btn.dataset.presetValues || "";
      });
    });
    if (list[0]) {
      const input = document.getElementById("sensValuesInput");
      if (input && !input.dataset.userEdited) input.value = list[0].values;
    }
  }

  function renderSchemePicker() {
    const host = document.getElementById("sensSchemePicker");
    const countEl = document.getElementById("sensTrackedCount");
    if (countEl) countEl.textContent = String(state.trackedItems.length);
    if (!host) return;
    const trackedSet = new Set(state.trackedItems.map((it) => it.scheme));
    host.innerHTML = state.schemes
      .map(
        (s) => `
      <label class="sens-pick-item">
        <input type="checkbox" value="${escapeHtml(s.name)}" ${trackedSet.has(s.name) ? "checked" : ""}>
        <span title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
      </label>
    `,
      )
      .join("");
    host.querySelectorAll('input[type="checkbox"]').forEach((box) => {
      box.addEventListener("change", () => {
        const name = box.value;
        if (box.checked) {
          if (!state.trackedItems.some((it) => it.scheme === name)) {
            state.trackedItems.push({ scheme: name, parameter_value: null, parameter_label: "" });
          }
        } else {
          state.trackedItems = state.trackedItems.filter((it) => it.scheme !== name);
        }
        saveState();
        refreshSummary().catch((e) => window.PowerPlanUI?.toast?.(e.message, { level: "error" }));
      });
    });
  }

  async function loadSchemes() {
    const saved = restoreState();
    const data = await api("/api/planning/schemes");
    state.schemes = Array.isArray(data.schemes) ? data.schemes : [];
    const existingSet = new Set(state.schemes.map((s) => s.name));
    state.trackedItems = state.trackedItems.filter((it) => existingSet.has(it.scheme));
    if (!state.trackedItems.length && state.schemes.length) {
      // 默认勾选前 4 个已有方案以便立即可视化
      state.trackedItems = state.schemes.slice(0, Math.min(4, state.schemes.length)).map((s) => ({
        scheme: s.name,
        parameter_value: null,
        parameter_label: "",
      }));
    }

    const baseSelect = document.getElementById("sensBaseScheme");
    if (baseSelect) {
      const ctx = window.PowerPlanPageState?.getActiveContext?.() || {};
      const preferred = ctx.scheme || saved.currentScheme || state.schemes[0]?.name || "";
      baseSelect.innerHTML = state.schemes
        .map((s) => `<option value="${escapeHtml(s.name)}"${s.name === preferred ? " selected" : ""}>${escapeHtml(s.name)}</option>`)
        .join("");
    }
    const metricSelect = document.getElementById("sensMetricSelect");
    if (metricSelect) metricSelect.value = state.metricKey;
    document.querySelectorAll("[data-sens-view]").forEach((btn) => {
      const active = btn.dataset.sensView === state.viewMode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
    renderPresets();
    renderSchemePicker();
    await refreshSummary();
  }

  async function generateScenarios() {
    const baseScheme = document.getElementById("sensBaseScheme")?.value || "";
    const parameterKey = document.getElementById("sensParamKey")?.value || "load_scale";
    const rawText = document.getElementById("sensValuesInput")?.value || "";
    const prefix = document.getElementById("sensPrefixInput")?.value.trim() || "";
    const autoQueue = Boolean(document.getElementById("sensAutoQueue")?.checked);
    const values = rawText
      .split(/[,，\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    if (!baseScheme || !values.length) {
      window.PowerPlanUI?.toast?.("请选择基准方案并填写有效的扫描数值序列", { level: "warn" });
      return;
    }
    const btn = document.getElementById("sensGenerateBtn");
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/sensitivity/generate", {
        method: "POST",
        body: JSON.stringify({
          base_scheme: baseScheme,
          parameter_key: parameterKey,
          values,
          prefix,
          auto_queue: autoQueue,
        }),
      });
      state.trackedItems = (res.items || []).map((it) => ({
        scheme: it.scheme,
        parameter_value: it.parameter_value,
        parameter_label: it.parameter_label,
      }));
      saveState();
      window.PowerPlanUI?.toast?.(res.message || "情景已生成", { level: "success" });
      const latestSchemes = await api("/api/planning/schemes");
      state.schemes = Array.isArray(latestSchemes.schemes) ? latestSchemes.schemes : [];
      renderSchemePicker();
      await refreshSummary();
    } catch (err) {
      window.PowerPlanUI?.toast?.(err.message || "生成情景失败", { level: "error" });
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function refreshSummary() {
    const names = state.trackedItems.map((it) => it.scheme);
    if (!names.length) {
      state.rows = [];
      renderAll();
      return;
    }
    const metaMap = new Map(state.trackedItems.map((it) => [it.scheme, it]));
    const data = await api(`/api/sensitivity/summary?schemes=${encodeURIComponent(names.join(","))}`);
    state.rows = (data.rows || []).map((row) => {
      const meta = metaMap.get(row.scheme) || {};
      return {
        ...row,
        parameter_value: meta.parameter_value ?? null,
        parameter_label: meta.parameter_label || "",
      };
    });
    renderAll();
  }

  function renderAll() {
    renderStats();
    renderChart();
    renderTable();
    if (window.PowerPlanI18n) {
      window.PowerPlanI18n.translate(document.body, window.PowerPlanI18n.currentLanguage());
    }
  }

  function renderStats() {
    const total = state.rows.length;
    const done = state.rows.filter((r) => r.has_result).length;
    const lcoes = state.rows.map((r) => r.lcoe).filter((v) => Number.isFinite(v));
    const greens = state.rows.map((r) => r.green_ratio).filter((v) => Number.isFinite(v));
    document.getElementById("sensStatTotal").textContent = String(total);
    document.getElementById("sensStatDone").textContent = `${done}/${total}`;
    document.getElementById("sensStatMinLcoe").textContent = lcoes.length ? Math.min(...lcoes).toFixed(3) : "—";
    document.getElementById("sensStatMaxGreen").textContent = greens.length ? `${Math.max(...greens).toFixed(1)}%` : "—";
  }

  function renderChart() {
    const svg = document.getElementById("sensChartSvg");
    if (!svg) return;
    const width = svg.clientWidth || 860;
    const height = svg.clientHeight || 280;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const pal = window.PowerPlanUI?.getChartPalette?.() || {
      accent: "#38BDF8",
      ok: "#34D399",
      warn: "#FBBF24",
      grid: "rgba(255,255,255,0.08)",
      axis: "rgba(148,163,184,0.35)",
      text: "#94A3B8",
    };

    const completed = state.rows.filter((r) => r.has_result);
    if (!completed.length) {
      svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.text}" font-size="13">暂无已完成求解的情景结果</text>`;
      return;
    }

    const padL = 64;
    const padR = 28;
    const padT = 26;
    const padB = 42;
    const plotW = Math.max(10, width - padL - padR);
    const plotH = Math.max(10, height - padT - padB);

    if (state.viewMode === "pareto") {
      const pts = completed.filter((r) => Number.isFinite(r.lcoe) && Number.isFinite(r.green_ratio));
      if (!pts.length) {
        svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.text}" font-size="13">缺少度电成本与绿电占比数据</text>`;
        return;
      }
      const xs = pts.map((p) => p.green_ratio);
      const ys = pts.map((p) => p.lcoe);
      const rawMinX = Math.min(...xs);
      const rawMaxX = Math.max(...xs);
      const padSpanX = (rawMaxX - rawMinX || Math.max(2, Math.abs(rawMinX) * 0.1)) * 0.12;
      const minX = rawMinX - padSpanX;
      const maxX = rawMaxX + padSpanX;
      const spanX = maxX - minX || 1;
      const rawMinY = Math.min(...ys);
      const rawMaxY = Math.max(...ys);
      const padSpanY = (rawMaxY - rawMinY || Math.max(0.2, Math.abs(rawMinY) * 0.1)) * 0.14;
      const minY = rawMinY - padSpanY;
      const maxY = rawMaxY + padSpanY;
      const spanY = maxY - minY || 1;
      const sx = (v) => padL + ((v - minX) / spanX) * plotW;
      const sy = (v) => padT + plotH - ((v - minY) / spanY) * plotH;

      const grid = [0, 0.25, 0.5, 0.75, 1]
        .map((r) => {
          const yv = minY + spanY * r;
          const yy = sy(yv);
          return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${pal.grid}"/><text x="${padL - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="11">${yv.toFixed(3)}</text>`;
        })
        .join("");

      const sorted = [...pts].sort((a, b) => a.green_ratio - b.green_ratio);
      const linePath = sorted.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.green_ratio).toFixed(1)},${sy(p.lcoe).toFixed(1)}`).join(" ");
      let prevPx = -999;
      let prevPy = -999;
      let flipDown = false;
      const dots = sorted
        .map((p) => {
          const cx = sx(p.green_ratio);
          const cy = sy(p.lcoe);
          const tooClose = Math.abs(cx - prevPx) < 78 && Math.abs(cy - prevPy) < 24;
          flipDown = tooClose ? !flipDown : false;
          prevPx = cx;
          prevPy = cy;
          const labelY = flipDown ? Math.min(padT + plotH - 4, cy + 16) : Math.max(padT + 11, cy - 9);
          const anchor = cx < padL + 42 ? "start" : cx > width - padR - 42 ? "end" : "middle";
          const txt = p.parameter_value !== null ? String(p.parameter_value) : p.scheme.slice(0, 14);
          return `<g class="sens-dot" data-scheme="${escapeHtml(p.scheme)}"><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5" fill="${pal.ok}" stroke="var(--bg-surface)" stroke-width="1.5"><title>${escapeHtml(p.scheme)} | LCOE: ${p.lcoe.toFixed(3)} | 绿电: ${p.green_ratio.toFixed(2)}%</title></circle><text x="${cx.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="${anchor}" fill="${pal.text}" font-size="10.5">${escapeHtml(txt)}</text></g>`;
        })
        .join("");

      svg.innerHTML = `${grid}<line x1="${padL}" x2="${width - padR}" y1="${padT + plotH}" y2="${padT + plotH}" stroke="${pal.axis}"/><line x1="${padL}" x2="${padL}" y1="${padT}" y2="${padT + plotH}" stroke="${pal.axis}"/><path d="${linePath}" fill="none" stroke="${pal.accent}" stroke-width="1.8" stroke-dasharray="4 3"/>${dots}<text x="${padL}" y="16" fill="${pal.text}" font-size="12" font-weight="700">Pareto 前沿：度电成本 (Y) vs 绿电占比 % (X)</text><text x="${padL + plotW / 2}" y="${height - 10}" text-anchor="middle" fill="${pal.text}" font-size="11">绿电占比 (%)</text>`;
      return;
    }

    const metric = state.metricKey;
    const pts = completed.filter((r) => Number.isFinite(r[metric]));
    if (!pts.length) {
      svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.text}" font-size="13">当前指标暂无数值</text>`;
      return;
    }
    const vals = pts.map((p) => p[metric]);
    const minY = Math.min(...vals);
    const maxY = Math.max(...vals);
    const spanY = maxY - minY || Math.max(1, Math.abs(minY) * 0.2);
    const loY = minY === maxY ? minY - spanY * 0.5 : minY - spanY * 0.08;
    const hiY = minY === maxY ? maxY + spanY * 0.5 : maxY + spanY * 0.08;
    const denomX = Math.max(1, pts.length - 1);
    const sx = (i) => padL + (pts.length === 1 ? plotW / 2 : (i / denomX) * plotW);
    const sy = (v) => padT + plotH - ((v - loY) / (hiY - loY || 1)) * plotH;

    const grid = [0, 0.25, 0.5, 0.75, 1]
      .map((r) => {
        const yv = loY + (hiY - loY) * r;
        const yy = sy(yv);
        return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${pal.grid}"/><text x="${padL - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="11">${yv.toFixed(2)}</text>`;
      })
      .join("");

    const pathD = pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(1)},${sy(p[metric]).toFixed(1)}`).join(" ");
    const xTicks = pts
      .map((p, i) => {
        const xx = sx(i);
        const label = p.parameter_value !== null ? String(p.parameter_value) : p.scheme.length > 14 ? `${p.scheme.slice(0, 12)}…` : p.scheme;
        return `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${padT + plotH}" y2="${padT + plotH + 4}" stroke="${pal.axis}"/><text x="${xx.toFixed(1)}" y="${height - 14}" text-anchor="middle" fill="${pal.text}" font-size="11">${escapeHtml(label)}</text><circle cx="${xx.toFixed(1)}" cy="${sy(p[metric]).toFixed(1)}" r="4.5" fill="${pal.accent}" stroke="var(--bg-surface)" stroke-width="1.5"><title>${escapeHtml(p.scheme)}: ${p[metric]}</title></circle>`;
      })
      .join("");

    svg.innerHTML = `${grid}<line x1="${padL}" x2="${width - padR}" y1="${padT + plotH}" y2="${padT + plotH}" stroke="${pal.axis}"/><line x1="${padL}" x2="${padL}" y1="${padT}" y2="${padT + plotH}" stroke="${pal.axis}"/><path d="${pathD}" fill="none" stroke="${pal.accent}" stroke-width="2.2"/>${xTicks}<text x="${padL}" y="16" fill="${pal.text}" font-size="12" font-weight="700">${escapeHtml(METRIC_LABELS[metric] || metric)}</text>`;
  }

  function renderTable() {
    const host = document.getElementById("sensSummaryTable");
    if (!host) return;
    if (!state.rows.length) {
      host.innerHTML = `<div class="empty-summary">请在左侧生成情景或勾选已有方案</div>`;
      return;
    }
    const fmt = (v, d = 3) => (Number.isFinite(v) ? v.toFixed(d) : "—");
    host.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>情景方案</th>
            <th>参数值</th>
            <th>状态</th>
            <th>度电成本</th>
            <th>年均总成本</th>
            <th>绿电占比(%)</th>
            <th>弃电率(%)</th>
            <th>柴发耗油</th>
            <th>频率范围(Hz)</th>
            <th>可靠率(%)</th>
            <th>装机概要</th>
            <th>直达</th>
          </tr>
        </thead>
        <tbody>
          ${state.rows
            .map(
              (r) => `
            <tr>
              <td>${escapeHtml(r.scheme)}</td>
              <td>${r.parameter_value !== null ? escapeHtml(String(r.parameter_value)) : "—"}</td>
              <td><span class="task-status-pill">${escapeHtml(r.status || "未计算")}</span></td>
              <td>${fmt(r.lcoe, 3)}</td>
              <td>${fmt(r.annual_cost, 2)}</td>
              <td>${fmt(r.green_ratio, 2)}</td>
              <td>${fmt(r.curtail_rate, 2)}</td>
              <td>${fmt(r.diesel_fuel, 2)}</td>
              <td>${Number.isFinite(r.freq_min) && Number.isFinite(r.freq_max) ? `${r.freq_min.toFixed(2)} ~ ${r.freq_max.toFixed(2)}` : "—"}</td>
              <td>${fmt(r.reliability_pct, 3)}</td>
              <td title="${escapeHtml(r.capacity_summary || "")}">${escapeHtml(r.capacity_summary || "—")}</td>
              <td>
                <a class="task-view-link" href="optimize.html?scheme=${encodeURIComponent(r.scheme)}">求解</a>
                <a class="task-view-link" href="report.html?scheme=${encodeURIComponent(r.scheme)}&file=opt_results.xlsx">简报</a>
              </td>
            </tr>
          `,
            )
            .join("")}
        </tbody>
      </table>
    `;
  }

  function exportCsv() {
    if (!state.rows.length) {
      window.PowerPlanUI?.toast?.("暂无可导出的数据", { level: "warn" });
      return;
    }
    const headers = ["情景方案", "参数值", "状态", "度电成本", "年均总成本", "绿电占比(%)", "弃电率(%)", "柴发耗油", "最低频率", "最高频率", "可靠率(%)", "装机概要"];
    const esc = (v) => {
      const s = String(v ?? "");
      return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [
      headers.map(esc).join(","),
      ...state.rows.map((r) =>
        [
          r.scheme,
          r.parameter_value ?? "",
          r.status,
          r.lcoe ?? "",
          r.annual_cost ?? "",
          r.green_ratio ?? "",
          r.curtail_rate ?? "",
          r.diesel_fuel ?? "",
          r.freq_min ?? "",
          r.freq_max ?? "",
          r.reliability_pct ?? "",
          r.capacity_summary ?? "",
        ]
          .map(esc)
          .join(","),
      ),
    ];
    const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sensitivity_summary_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    window.PowerPlanUI?.toast?.("敏感性汇总 CSV 已导出", { level: "success" });
  }

  function compareAllDone() {
    const done = state.rows.filter((r) => r.has_result).slice(0, 8);
    if (!done.length) {
      window.PowerPlanUI?.toast?.("暂无已完成求解的情景可对比", { level: "warn" });
      return;
    }
    const tabs = done.map((r, i) => ({ id: `tab-${i + 1}`, scheme: r.scheme, result: "opt_results.xlsx" }));
    window.PowerPlanPageState?.write?.("comparison", { tabs, activeTabId: tabs[0].id });
    window.location.href = "comparison.html";
  }

  async function cleanupTrackedScenarios() {
    const names = state.trackedItems.map((it) => it.scheme);
    if (!names.length) return;
    const confirmed = window.PowerPlanUI
      ? await window.PowerPlanUI.dangerConfirm(
          `确认永久删除当前勾选的 ${names.length} 个情景方案及其结果文件？此操作不可撤销。\n${names.slice(0, 6).join("、")}${names.length > 6 ? " 等" : ""}`,
          { title: "高危操作：批量清理情景方案", confirmText: "确认永久删除" },
        )
      : confirm(`确认删除 ${names.length} 个方案？`);
    if (!confirmed) return;
    try {
      const res = await api("/api/sensitivity/cleanup", {
        method: "POST",
        body: JSON.stringify({ schemes: names }),
      });
      const deletedSet = new Set(res.deleted || []);
      state.trackedItems = state.trackedItems.filter((it) => !deletedSet.has(it.scheme));
      saveState();
      window.PowerPlanUI?.toast?.(`已清理 ${deletedSet.size} 个方案${res.skipped?.length ? `，跳过 ${res.skipped.length} 个` : ""}`, { level: "success" });
      await loadSchemes();
    } catch (err) {
      window.PowerPlanUI?.toast?.(err.message || "清理失败", { level: "error" });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("sensParamKey")?.addEventListener("change", () => {
      const input = document.getElementById("sensValuesInput");
      if (input) delete input.dataset.userEdited;
      renderPresets();
    });
    document.getElementById("sensValuesInput")?.addEventListener("input", (e) => {
      e.target.dataset.userEdited = "1";
    });
    document.getElementById("sensGenerateBtn")?.addEventListener("click", generateScenarios);
    document.getElementById("sensRefreshBtn")?.addEventListener("click", () => refreshSummary());
    document.getElementById("sensExportCsvBtn")?.addEventListener("click", exportCsv);
    document.getElementById("sensCompareAllBtn")?.addEventListener("click", compareAllDone);
    document.getElementById("sensCleanupBtn")?.addEventListener("click", cleanupTrackedScenarios);
    document.querySelectorAll("[data-sens-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.viewMode = btn.dataset.sensView || "trend";
        document.querySelectorAll("[data-sens-view]").forEach((b) => {
          const active = b.dataset.sensView === state.viewMode;
          b.classList.toggle("active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        saveState();
        renderChart();
      });
    });
    document.getElementById("sensMetricSelect")?.addEventListener("change", (e) => {
      state.metricKey = e.target.value || "lcoe";
      saveState();
      renderChart();
    });
    window.addEventListener("powerplan:themechange", renderChart);
    window.addEventListener("resize", renderChart);
    loadSchemes().catch((err) => window.PowerPlanUI?.toast?.(err.message || "初始化失败", { level: "error" }));
    state.pollTimer = window.setInterval(() => {
      if (!document.hidden && state.rows.some((r) => r.status === "计算中" || r.status === "排队中")) {
        refreshSummary().catch(() => null);
      }
    }, 5000);
  });
})();
