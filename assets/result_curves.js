(function () {
  const CHART_COLORS = ["#21d5ff", "#82e7b5", "#ffc857", "#ff7a90", "#b38cff", "#5ee7df", "#ff9f43", "#ff6bcb"];
  const GROUP_DEFINITIONS = [
    { key: "hourly", title: "小时级曲线" },
    { key: "daily", title: "日级统计" },
    { key: "monthly", title: "月度统计" },
    { key: "annual", title: "年度统计" },
  ];

  function create(options) {
    const state = {
      groups: emptyGroups(),
      annualTable: [],
      selectedCurvesByGroup: { hourly: [], daily: [], monthly: [] },
      activeGroup: "hourly",
      hoverIndex: null,
      emptyText: options.emptyText || "暂无小时级曲线",
      promptText: options.promptText || "请选择小时级曲线",
    };

    function setData(payload) {
      state.groups = normalizeGroups(payload);
      state.annualTable = Array.isArray(payload?.annual_table) ? payload.annual_table : [];
      GROUP_DEFINITIONS.filter((group) => group.key !== "annual").forEach((group) => {
        const curveNames = state.groups[group.key]?.curves || [];
        state.selectedCurvesByGroup[group.key] = (state.selectedCurvesByGroup[group.key] || []).filter((name) => curveNames.includes(name));
        if (!state.selectedCurvesByGroup[group.key].length && curveNames.length) {
          state.selectedCurvesByGroup[group.key] = [curveNames[0]];
        }
      });
      if (!groupHasData(state.activeGroup)) state.activeGroup = firstAvailableGroup();
      state.hoverIndex = null;
      render();
    }

    function clear(message) {
      state.groups = emptyGroups();
      state.annualTable = [];
      state.selectedCurvesByGroup = { hourly: [], daily: [], monthly: [] };
      state.activeGroup = "hourly";
      state.hoverIndex = null;
      render(message || state.emptyText);
    }

    function render(message) {
      renderCurveNameList(message);
      renderCurveChart(message);
    }

    function renderCurveNameList(message) {
      const target = document.getElementById(options.listId);
      if (!target) return;
      const group = activeCurveGroup();
      const tabs = renderGroupTabs();
      if (state.activeGroup === "annual") {
        target.innerHTML = `${tabs}<div class="empty-summary">${state.annualTable.length ? "年度统计以表格显示" : escapeHtml(message || "暂无年度统计")}</div>`;
        bindGroupTabs(target);
        return;
      }
      if (!group.curves.length) {
        target.innerHTML = `${tabs}<div class="empty-summary">${escapeHtml(message || groupEmptyText())}</div>`;
        bindGroupTabs(target);
        return;
      }
      target.innerHTML = `${tabs}<ul aria-multiselectable="true">${group.curves
        .map((name) => {
          const active = selectedCurveNames().includes(name);
          return `<li class="comparison-curve-name-item${active ? " active" : ""}" data-result-curve-name="${escapeHtml(name)}" role="option" aria-selected="${active ? "true" : "false"}" tabindex="0">${escapeHtml(name)}</li>`;
        })
        .join("")}</ul>`;
      bindGroupTabs(target);
      target.querySelectorAll("[data-result-curve-name]").forEach((item) => {
        item.addEventListener("click", () => toggleCurve(item.dataset.resultCurveName || ""));
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleCurve(item.dataset.resultCurveName || "");
          }
        });
      });
    }

    function renderGroupTabs() {
      return `<div class="curve-group-tabs" role="tablist" aria-label="曲线统计类型">${GROUP_DEFINITIONS.map((group) => {
        const active = group.key === state.activeGroup;
        return `<button class="curve-group-tab${active ? " active" : ""}" type="button" data-curve-group="${group.key}" role="tab" aria-selected="${active ? "true" : "false"}">${escapeHtml(group.title)}</button>`;
      }).join("")}</div>`;
    }

    function bindGroupTabs(target) {
      target.querySelectorAll("[data-curve-group]").forEach((button) => {
        button.addEventListener("click", () => {
          state.activeGroup = button.dataset.curveGroup || "hourly";
          state.hoverIndex = null;
          render();
        });
      });
    }

    function toggleCurve(name) {
      if (!name || state.activeGroup === "annual") return;
      const selected = selectedCurveNames();
      state.selectedCurvesByGroup[state.activeGroup] = selected.includes(name)
        ? selected.filter((item) => item !== name)
        : [...selected, name];
      render();
    }

    function selectedCurveNames() {
      if (state.activeGroup === "annual") return [];
      const group = activeCurveGroup();
      return (state.selectedCurvesByGroup[state.activeGroup] || []).filter((name) => group.curves.includes(name));
    }

    function selectedCurveSeries() {
      const group = activeCurveGroup();
      return selectedCurveNames().flatMap((curveName) =>
        (group.series[curveName] || []).map((item) => ({
          ...item,
          curveName,
          displayLabel: `${curveName} / ${item.label}`,
        })),
      );
    }

    function renderCurveChart(message) {
      const target = document.getElementById(options.chartId);
      if (!target) return;
      if (state.activeGroup === "annual") {
        renderAnnualTable(target, message);
        return;
      }
      const curveNames = selectedCurveNames();
      const series = selectedCurveSeries();
      if (!curveNames.length || !series.length) {
        target.innerHTML = `<div class="empty-summary">${escapeHtml(message || groupPromptText())}</div>`;
        return;
      }
      const width = 1080;
      const height = 360;
      const margin = { top: 18, right: 24, bottom: 28, left: 58 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const values = series.flatMap((item) => item.points.map((point) => Number(point.y)).filter(Number.isFinite));
      const minY = Math.min(...values, 0);
      const maxY = Math.max(...values, 1);
      const ySpan = Math.max(maxY - minY, 1);
      const maxPoints = Math.max(...series.map((item) => item.points.length), 1);
      const xAt = (index, total) => margin.left + (total <= 1 ? plotWidth / 2 : (index / (total - 1)) * plotWidth);
      const yAt = (value) => margin.top + plotHeight - ((value - minY) / ySpan) * plotHeight;
      const yTicks = [0, 0.5, 1].map((ratio) => {
        const value = minY + ySpan * ratio;
        return { ratio, value, y: yAt(value) };
      });

      target.innerHTML = `
        <div class="comparison-curve-legend">${series
          .map((item, index) => `<span><i style="background:${CHART_COLORS[index % CHART_COLORS.length]}"></i>${escapeHtml(item.displayLabel)}</span>`)
          .join("")}</div>
        <div class="comparison-chart-frame" style="--comparison-chart-left:${((margin.left / width) * 100).toFixed(3)}%; --comparison-chart-right:${((margin.right / width) * 100).toFixed(3)}%; --comparison-chart-top:${((margin.top / height) * 100).toFixed(3)}%; --comparison-chart-bottom:${((margin.bottom / height) * 100).toFixed(3)}%;">
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(curveNames.join("、"))}曲线">
            <line class="comparison-chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
            <line class="comparison-chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
            ${yTicks.map((tick) => renderYAxisGrid(tick.y, margin.left, width - margin.right)).join("")}
            ${series.map((item, index) => renderSeriesPath(item.points, xAt, yAt, CHART_COLORS[index % CHART_COLORS.length])).join("")}
            <g class="comparison-chart-hover-group" hidden>
              <line class="comparison-chart-hover-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
            </g>
            <rect class="comparison-chart-hover-capture" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"></rect>
          </svg>
          ${renderAxisLabels({ yTicks, series, maxPoints })}
          ${renderCurveStats(series)}
          <div class="comparison-chart-tooltip" data-result-curve-tooltip hidden></div>
        </div>`;
      bindChartHover({ target, margin, plotWidth, series });
    }

    function renderAnnualTable(target, message) {
      if (!state.annualTable.length) {
        target.innerHTML = `<div class="empty-summary">${escapeHtml(message || "暂无年度统计")}</div>`;
        return;
      }
      const headers = Object.keys(state.annualTable[0] || {});
      target.innerHTML = `
        <div class="data-table annual-stat-table">
          <table>
            <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
            <tbody>${state.annualTable
              .map((row) => `<tr>${headers.map((header) => `<td>${escapeHtml(row[header] ?? "")}</td>`).join("")}</tr>`)
              .join("")}</tbody>
          </table>
        </div>`;
    }

    function renderYAxisGrid(y, left, right) {
      return `<line class="comparison-chart-grid" x1="${left}" y1="${y.toFixed(2)}" x2="${right}" y2="${y.toFixed(2)}"></line>`;
    }

    function renderAxisLabels({ yTicks, series, maxPoints }) {
      const firstPoints = series[0]?.points || [];
      const xTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const index = Math.min(Math.round(ratio * Math.max(maxPoints - 1, 0)), Math.max(firstPoints.length - 1, 0));
        return {
          ratio,
          label: firstPoints[index]?.x ?? Math.round(ratio * Math.max(maxPoints - 1, 0)) + 1,
        };
      });
      return `
        <div class="comparison-chart-y-axis" aria-hidden="true">${yTicks
          .map((tick) => `<span style="bottom:${(tick.ratio * 100).toFixed(2)}%">${escapeHtml(formatAxis(tick.value))}</span>`)
          .join("")}</div>
        <div class="comparison-chart-x-axis" aria-hidden="true">${xTicks
          .map((tick) => `<span style="left:${(tick.ratio * 100).toFixed(2)}%">${escapeHtml(tick.label)}</span>`)
          .join("")}</div>`;
    }

    function renderCurveStats(series) {
      return `<div class="comparison-curve-stats" aria-label="当前曲线统计信息">${series
        .map((item) => {
          const values = item.points.map((point) => Number(point.y)).filter(Number.isFinite);
          const min = values.length ? Math.min(...values) : 0;
          const max = values.length ? Math.max(...values) : 0;
          const sum = values.reduce((total, value) => total + value, 0);
          const average = values.length ? sum / values.length : 0;
          return `<section><strong>${escapeHtml(item.displayLabel)}</strong><span>最小 ${escapeHtml(formatAxis(min))}</span><span>最大 ${escapeHtml(formatAxis(max))}</span><span>平均 ${escapeHtml(formatAxis(average))}</span><span>合计 ${escapeHtml(formatAxis(sum))}</span></section>`;
        })
        .join("")}</div>`;
    }

    function renderSeriesPath(points, xAt, yAt, color) {
      const sampled = downsample(points, 720);
      const path = sampled
        .map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index, sampled.length).toFixed(2)} ${yAt(Number(point.y)).toFixed(2)}`)
        .join(" ");
      return `<path class="comparison-series-line" d="${path}" stroke="${color}"></path>`;
    }

    function bindChartHover(chart) {
      const capture = chart.target.querySelector(".comparison-chart-hover-capture");
      const tooltip = chart.target.querySelector("[data-result-curve-tooltip]");
      if (!capture || !tooltip) return;
      capture.addEventListener("mousemove", (event) => {
        const rect = capture.getBoundingClientRect();
        const ratio = Math.min(Math.max((event.clientX - rect.left) / Math.max(rect.width, 1), 0), 1);
        const maxPoints = Math.max(...chart.series.map((item) => item.points.length), 1);
        const index = Math.round(ratio * (maxPoints - 1));
        state.hoverIndex = index;
        renderChartHover(chart, event, index);
      });
      capture.addEventListener("mouseleave", () => {
        state.hoverIndex = null;
        chart.target.querySelector(".comparison-chart-hover-group")?.setAttribute("hidden", "");
        tooltip.hidden = true;
      });
    }

    function renderChartHover(chart, event, pointIndex) {
      const hover = chart.target.querySelector(".comparison-chart-hover-group");
      const tooltip = chart.target.querySelector("[data-result-curve-tooltip]");
      if (!hover || !tooltip) return;
      const maxPoints = Math.max(...chart.series.map((item) => item.points.length), 1);
      const ratio = maxPoints <= 1 ? 0 : Math.min(Math.max(pointIndex / (maxPoints - 1), 0), 1);
      const x = chart.margin.left + ratio * chart.plotWidth;
      hover.removeAttribute("hidden");
      hover.querySelector("line")?.setAttribute("x1", x.toFixed(2));
      hover.querySelector("line")?.setAttribute("x2", x.toFixed(2));
      const rows = chart.series.map((item) => {
        const index = Math.min(Math.max(pointIndex, 0), item.points.length - 1);
        const point = item.points[index] || {};
        return { label: item.displayLabel || item.label, x: point.x ?? index + 1, y: point.y };
      });
      tooltip.innerHTML = `
        <h3>${escapeHtml(rows[0]?.x ?? "")}</h3>
        ${rows.map((row) => `<div><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(formatAxis(row.y))}</strong></div>`).join("")}`;
      tooltip.hidden = false;
      const bounds = chart.target.getBoundingClientRect();
      const tooltipX = Math.min(Math.max(event.clientX - bounds.left + 14, 8), Math.max(bounds.width - tooltip.offsetWidth - 8, 8));
      const tooltipY = Math.min(Math.max(event.clientY - bounds.top + 14, 8), Math.max(bounds.height - tooltip.offsetHeight - 8, 8));
      tooltip.style.left = `${Math.round(tooltipX)}px`;
      tooltip.style.top = `${Math.round(tooltipY)}px`;
    }

    function activeCurveGroup() {
      return state.groups[state.activeGroup] || state.groups.hourly || { curves: [], series: {} };
    }

    function groupHasData(key) {
      if (key === "annual") return state.annualTable.length > 0;
      return Boolean(state.groups[key]?.curves?.length);
    }

    function firstAvailableGroup() {
      return GROUP_DEFINITIONS.find((group) => groupHasData(group.key))?.key || "hourly";
    }

    function groupEmptyText() {
      const title = GROUP_DEFINITIONS.find((group) => group.key === state.activeGroup)?.title || "曲线";
      return state.activeGroup === "hourly" ? state.emptyText : `暂无${title}`;
    }

    function groupPromptText() {
      const title = GROUP_DEFINITIONS.find((group) => group.key === state.activeGroup)?.title || "曲线";
      return state.activeGroup === "hourly" ? state.promptText : `请选择${title}`;
    }

    clear();
    return { setData, clear, render };
  }

  function emptyGroups() {
    return GROUP_DEFINITIONS.filter((group) => group.key !== "annual").reduce((groups, group) => {
      groups[group.key] = { title: group.title, curves: [], series: {} };
      return groups;
    }, {});
  }

  function normalizeGroups(payload) {
    const groups = emptyGroups();
    if (payload?.curve_groups && typeof payload.curve_groups === "object") {
      Object.keys(groups).forEach((key) => {
        const source = payload.curve_groups[key] || {};
        groups[key] = {
          title: source.title || groups[key].title,
          curves: Array.isArray(source.curves) ? source.curves : [],
          series: source.series && typeof source.series === "object" ? source.series : {},
        };
      });
      return groups;
    }
    groups.hourly.curves = Array.isArray(payload?.curves) ? payload.curves : [];
    groups.hourly.series = payload?.series && typeof payload.series === "object" ? payload.series : {};
    return groups;
  }

  function downsample(points, limit) {
    if (points.length <= limit) return points;
    const step = Math.ceil(points.length / limit);
    return points.filter((_, index) => index % step === 0);
  }

  function formatAxis(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "-";
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
  }

  window.ResultCurveViewer = { create };
})();
