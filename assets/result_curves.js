(function () {
  const CHART_COLORS = ["#21d5ff", "#82e7b5", "#ffc857", "#ff7a90", "#b38cff", "#5ee7df", "#ff9f43", "#ff6bcb"];
  const LINE_PATTERNS = ["", "7 4", "2 4", "10 4 2 4"];
  const GROUP_DEFINITIONS = [
    { key: "hourly", title: "小时级曲线" },
    { key: "daily", title: "日级统计" },
    { key: "monthly", title: "月度统计" },
    { key: "annual", title: "年度统计" },
  ];
  const MONTH_RANGES = [
    ["1月", 0, 744, 1, 31],
    ["2月", 744, 1416, 32, 59],
    ["3月", 1416, 2160, 60, 90],
    ["4月", 2160, 2880, 91, 120],
    ["5月", 2880, 3624, 121, 151],
    ["6月", 3624, 4344, 152, 181],
    ["7月", 4344, 5088, 182, 212],
    ["8月", 5088, 5832, 213, 243],
    ["9月", 5832, 6552, 244, 273],
    ["10月", 6552, 7296, 274, 304],
    ["11月", 7296, 8016, 305, 334],
    ["12月", 8016, 8760, 335, 365],
  ];

  function create(options) {
    const state = {
      groups: emptyGroups(),
      annualTable: [],
      selectedCurvesByGroup: { hourly: [], daily: [], monthly: [] },
      hiddenSeriesByGroup: { hourly: [], daily: [], monthly: [] },
      curveRangeFilter: defaultCurveRangeFilter(),
      activeGroup: "hourly",
      hoverIndex: null,
      emptyText: options.emptyText || "暂无小时级曲线",
      promptText: options.promptText || "请选择小时级曲线",
    };

    function setData(payload) {
      state.groups = normalizeGroups(payload);
      state.annualTable = Array.isArray(payload?.annual_table) ? payload.annual_table : [];
      state.curveRangeFilter = normalizeCurveRangeFilter(state.curveRangeFilter, state.activeGroup);
      GROUP_DEFINITIONS.filter((group) => group.key !== "annual").forEach((group) => {
        const curveNames = state.groups[group.key]?.curves || [];
        state.selectedCurvesByGroup[group.key] = (state.selectedCurvesByGroup[group.key] || []).filter((name) => curveNames.includes(name));
        if (!state.selectedCurvesByGroup[group.key].length && curveNames.length) {
          state.selectedCurvesByGroup[group.key] = [curveNames[0]];
        }
        state.hiddenSeriesByGroup[group.key] = (state.hiddenSeriesByGroup[group.key] || []).filter((seriesId) =>
          availableSeriesIds(group.key).includes(seriesId),
        );
      });
      if (!groupHasData(state.activeGroup)) state.activeGroup = firstAvailableGroup();
      state.hoverIndex = null;
      render();
    }

    function clear(message) {
      state.groups = emptyGroups();
      state.annualTable = [];
      state.selectedCurvesByGroup = { hourly: [], daily: [], monthly: [] };
      state.hiddenSeriesByGroup = { hourly: [], daily: [], monthly: [] };
      state.curveRangeFilter = defaultCurveRangeFilter();
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
        item.addEventListener("click", (event) => toggleCurve(item.dataset.resultCurveName || "", { multi: isMultiCurveSelectionEvent(event) }));
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleCurve(item.dataset.resultCurveName || "", { multi: isMultiCurveSelectionEvent(event) });
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
          state.curveRangeFilter = normalizeCurveRangeFilter(state.curveRangeFilter, state.activeGroup);
          state.hoverIndex = null;
          render();
        });
      });
    }

    function toggleCurve(name, options = {}) {
      if (!name || state.activeGroup === "annual") return;
      const multi = Boolean(options.multi);
      const selected = selectedCurveNames();
      if (!multi) {
        state.selectedCurvesByGroup[state.activeGroup] = selected.length === 1 && selected[0] === name ? [name] : [name];
      } else {
        state.selectedCurvesByGroup[state.activeGroup] = selected.includes(name)
          ? selected.filter((item) => item !== name)
          : [...selected, name];
      }
      render();
    }

    function selectedCurveNames() {
      if (state.activeGroup === "annual") return [];
      const group = activeCurveGroup();
      return (state.selectedCurvesByGroup[state.activeGroup] || []).filter((name) => group.curves.includes(name));
    }

    function selectedCurveSeries() {
      const group = activeCurveGroup();
      let seriesIndex = 0;
      return filterSeriesByRange(
        selectedCurveNames().flatMap((curveName) =>
          (group.series[curveName] || []).map((item) => {
            const displayLabel = `${curveName} / ${item.label}`;
            const next = {
              ...item,
              curveName,
              displayLabel,
              seriesId: seriesKey(curveName, item.label),
              seriesIndex,
            };
            seriesIndex += 1;
            return next;
          }),
        ),
        state.activeGroup,
        state.curveRangeFilter,
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
      const allSeries = selectedCurveSeries();
      const visibleSeries = allSeries.filter((item) => !isSeriesHidden(item.seriesId));
      const controls = renderRangeControls();
      if (!curveNames.length || !allSeries.length) {
        target.innerHTML = `${controls}<div class="empty-summary">${escapeHtml(message || groupPromptText())}</div>`;
        bindRangeControls(target);
        return;
      }
      const width = 1080;
      const height = 360;
      const margin = { top: 18, right: 24, bottom: 28, left: 58 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const values = visibleSeries.flatMap((item) => item.points.map((point) => Number(point.y)).filter(Number.isFinite));
      const minY = values.length ? Math.min(...values, 0) : 0;
      const maxY = values.length ? Math.max(...values, 1) : 1;
      const ySpan = Math.max(maxY - minY, 1);
      const maxPoints = Math.max(...visibleSeries.map((item) => item.points.length), 1);
      const xAt = (index, total) => margin.left + (total <= 1 ? plotWidth / 2 : (index / (total - 1)) * plotWidth);
      const yAt = (value) => margin.top + plotHeight - ((value - minY) / ySpan) * plotHeight;
      const yTicks = [0, 0.5, 1].map((ratio) => {
        const value = minY + ySpan * ratio;
        return { ratio, value, y: yAt(value) };
      });

      target.innerHTML = `${controls}
        <div class="comparison-chart-frame" style="--comparison-chart-left:${((margin.left / width) * 100).toFixed(3)}%; --comparison-chart-right:${((margin.right / width) * 100).toFixed(3)}%; --comparison-chart-top:${((margin.top / height) * 100).toFixed(3)}%; --comparison-chart-bottom:${((margin.bottom / height) * 100).toFixed(3)}%;">
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(curveNames.join("、"))}曲线">
            <line class="comparison-chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
            <line class="comparison-chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
            ${yTicks.map((tick) => renderYAxisGrid(tick.y, margin.left, width - margin.right)).join("")}
            ${visibleSeries.map((item) => renderSeriesPath(item.points, xAt, yAt, item)).join("")}
            <g class="comparison-chart-hover-group" hidden>
              <line class="comparison-chart-hover-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
            </g>
            <rect class="comparison-chart-hover-capture" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"></rect>
          </svg>
          ${renderAxisLabels({ yTicks, series: visibleSeries, maxPoints })}
          ${renderCurveLegend(allSeries, visibleSeries)}
          ${visibleSeries.length ? "" : '<div class="result-curve-empty-overlay">暂无可显示曲线</div>'}
          <div class="comparison-chart-tooltip" data-result-curve-tooltip hidden></div>
        </div>`;
      bindRangeControls(target);
      bindCurveLegendToggles(target);
      if (visibleSeries.length) bindChartHover({ target, margin, plotWidth, series: visibleSeries });
    }

    function renderRangeControls() {
      if (state.activeGroup !== "hourly" && state.activeGroup !== "daily") return "";
      const filter = normalizeCurveRangeFilter(state.curveRangeFilter, state.activeGroup);
      const monthOptions = MONTH_RANGES.map(([label], index) => `<option value="${index}" ${index === filter.month ? "selected" : ""}>${label}</option>`).join("");
      const dayOptions = availableDaysInMonth(filter.month)
        .map((day) => `<option value="${day}" ${day === filter.day ? "selected" : ""}>${day}日</option>`)
        .join("");
      const dayDisabled = state.activeGroup !== "hourly" || filter.scope !== "day";
      return `
        <div class="curve-range-filter" aria-label="曲线时间范围筛选">
          <div class="curve-range-scope" role="group" aria-label="曲线时间范围">
            ${["year", "month", "day"].map((scope) => {
              const disabled = state.activeGroup === "daily" && scope === "day";
              const label = scope === "year" ? "全年" : scope === "month" ? "指定月" : "指定日";
              return `<button type="button" data-curve-range-scope="${scope}" class="${filter.scope === scope ? "active" : ""}" aria-pressed="${filter.scope === scope ? "true" : "false"}" ${disabled ? "disabled title=\"日级统计只支持全年或指定月筛选\"" : ""}>${label}</button>`;
            }).join("")}
          </div>
          <label>月份<select data-curve-range-month ${filter.scope === "year" ? "disabled" : ""}>${monthOptions}</select></label>
          <label>日期<select data-curve-range-day ${dayDisabled ? "disabled" : ""}>${dayOptions}</select></label>
        </div>`;
    }

    function bindRangeControls(target) {
      target.querySelectorAll("[data-curve-range-scope]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.disabled) return;
          state.curveRangeFilter = normalizeCurveRangeFilter({ ...state.curveRangeFilter, scope: button.dataset.curveRangeScope || "year" }, state.activeGroup);
          state.hoverIndex = null;
          render();
        });
      });
      const monthSelect = target.querySelector("[data-curve-range-month]");
      if (monthSelect) {
        monthSelect.addEventListener("change", () => {
          state.curveRangeFilter = normalizeCurveRangeFilter({ ...state.curveRangeFilter, month: Number(monthSelect.value), day: 1 }, state.activeGroup);
          state.hoverIndex = null;
          render();
        });
      }
      const daySelect = target.querySelector("[data-curve-range-day]");
      if (daySelect) {
        daySelect.addEventListener("change", () => {
          state.curveRangeFilter = normalizeCurveRangeFilter({ ...state.curveRangeFilter, day: Number(daySelect.value) }, state.activeGroup);
          state.hoverIndex = null;
          render();
        });
      }
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
              .map((row) => `<tr>${headers.map((header) => `<td>${escapeHtml(formatDisplayValue(row[header] ?? "", row, header))}</td>`).join("")}</tr>`)
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

    function renderCurveLegend(series, visibleSeries) {
      const visibleIds = new Set((visibleSeries || []).map((item) => item.seriesId));
      return `<div class="result-curve-legend" aria-label="曲线显示切换">${series
        .map((item) => {
          const hidden = isSeriesHidden(item.seriesId);
          const style = seriesLineStyle(item);
          const stats = curveStats(item);
          const dash = style.dash ? ` stroke-dasharray="${style.dash}"` : "";
          return `<button type="button" class="${hidden ? "is-hidden" : ""}" data-result-series-toggle="${escapeHtml(item.seriesId)}" aria-pressed="${visibleIds.has(item.seriesId) ? "true" : "false"}" title="显示/隐藏曲线">
              <span class="result-curve-legend-swatch" data-result-series-swatch aria-hidden="true">
                <svg viewBox="0 0 36 8" preserveAspectRatio="none"><line x1="1" y1="4" x2="35" y2="4" stroke="${style.color}"${dash}></line></svg>
              </span>
              <span class="result-curve-legend-label">${escapeHtml(item.displayLabel)}</span>
              <span class="result-curve-legend-stat">最小 ${escapeHtml(formatAxis(stats.min))}</span>
              <span class="result-curve-legend-stat">最大 ${escapeHtml(formatAxis(stats.max))}</span>
              <span class="result-curve-legend-stat">平均 ${escapeHtml(formatAxis(stats.average))}</span>
              <span class="result-curve-legend-stat">合计 ${escapeHtml(formatAxis(stats.sum))}</span>
            </button>`;
        })
        .join("")}</div>`;
    }

    function bindCurveLegendToggles(target) {
      target.querySelectorAll("[data-result-series-toggle]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleSeriesVisibility(button.dataset.resultSeriesToggle || "");
        });
      });
    }

    function toggleSeriesVisibility(seriesId) {
      if (!seriesId || state.activeGroup === "annual") return;
      const hidden = new Set(state.hiddenSeriesByGroup[state.activeGroup] || []);
      if (hidden.has(seriesId)) hidden.delete(seriesId);
      else hidden.add(seriesId);
      state.hiddenSeriesByGroup[state.activeGroup] = Array.from(hidden);
      state.hoverIndex = null;
      render();
    }

    function isSeriesHidden(seriesId) {
      return Boolean(seriesId && (state.hiddenSeriesByGroup[state.activeGroup] || []).includes(seriesId));
    }

    function availableSeriesIds(groupKey) {
      const group = state.groups[groupKey] || { curves: [], series: {} };
      return (group.curves || []).flatMap((curveName) => (group.series[curveName] || []).map((item) => seriesKey(curveName, item.label)));
    }

    function renderSeriesPath(points, xAt, yAt, item) {
      const style = seriesLineStyle(item);
      const sampled = downsample(points, 720);
      const path = sampled
        .map((point, index) => `${index === 0 ? "M" : "L"} ${xAt(index, sampled.length).toFixed(2)} ${yAt(Number(point.y)).toFixed(2)}`)
        .join(" ");
      return `<path class="comparison-series-line" d="${path}" stroke="${style.color}"${style.dash ? ` stroke-dasharray="${style.dash}"` : ""}></path>`;
    }

    function seriesLineStyle(item) {
      const index = Number.isFinite(Number(item?.seriesIndex)) ? Number(item.seriesIndex) : 0;
      const color = CHART_COLORS[index % CHART_COLORS.length];
      const dash = LINE_PATTERNS[Math.floor(index / CHART_COLORS.length) % LINE_PATTERNS.length] || "";
      return { color, dash };
    }

    function curveStats(item) {
      const values = (item?.points || []).map((point) => Number(point.y)).filter(Number.isFinite);
      const min = values.length ? Math.min(...values) : 0;
      const max = values.length ? Math.max(...values) : 0;
      const sum = values.reduce((total, value) => total + value, 0);
      const average = values.length ? sum / values.length : 0;
      return { min, max, sum, average };
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
        return { label: item.displayLabel || item.label, x: point.x ?? index + 1, y: point.y, style: seriesLineStyle(item) };
      });
      tooltip.innerHTML = `
        <h3>${escapeHtml(rows[0]?.x ?? "")}</h3>
        ${rows
          .map(
            (row) =>
              `<div><span><i class="result-curve-tooltip-swatch" style="background:${row.style.color}"></i>${escapeHtml(row.label)}</span><strong>${escapeHtml(formatAxis(row.y))}</strong></div>`,
          )
          .join("")}`;
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

    function isMultiCurveSelectionEvent(event) {
      return Boolean(event?.ctrlKey || event?.shiftKey || event?.metaKey);
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

  function defaultCurveRangeFilter() {
    return { scope: "year", month: 0, day: 1 };
  }

  function normalizeCurveRangeFilter(filter, groupKey) {
    const next = { ...defaultCurveRangeFilter(), ...(filter || {}) };
    if (!["year", "month", "day"].includes(next.scope)) next.scope = "year";
    if (groupKey === "daily" && next.scope === "day") next.scope = "month";
    if (groupKey !== "hourly" && groupKey !== "daily") next.scope = "year";
    next.month = Math.min(Math.max(Number.isFinite(Number(next.month)) ? Number(next.month) : 0, 0), 11);
    const days = availableDaysInMonth(next.month);
    next.day = Math.min(Math.max(Number.isFinite(Number(next.day)) ? Number(next.day) : 1, 1), days.length);
    return next;
  }

  function availableDaysInMonth(monthIndex) {
    const range = MONTH_RANGES[Math.min(Math.max(Number(monthIndex) || 0, 0), 11)] || MONTH_RANGES[0];
    return Array.from({ length: range[4] - range[3] + 1 }, (_, index) => index + 1);
  }

  function filterSeriesByRange(series, groupKey, filter) {
    const normalized = normalizeCurveRangeFilter(filter, groupKey);
    if (normalized.scope === "year" || (groupKey !== "hourly" && groupKey !== "daily")) return series;
    const range = MONTH_RANGES[normalized.month] || MONTH_RANGES[0];
    const [hourStart, hourEnd, dayStart, dayEnd] = [range[1], range[2], range[3], range[4]];
    return series
      .map((item) => {
        const points = (item.points || []).filter((point, index) => {
          if (groupKey === "hourly") {
            const hourIndex = numericPointIndex(point?.x, index + 1);
            if (normalized.scope === "month") return hourIndex >= hourStart + 1 && hourIndex <= hourEnd;
            const selectedDayStart = hourStart + (normalized.day - 1) * 24 + 1;
            return hourIndex >= selectedDayStart && hourIndex < selectedDayStart + 24;
          }
          if (groupKey === "daily") {
            const dayIndex = numericPointIndex(point?.x, index + 1);
            return dayIndex >= dayStart && dayIndex <= dayEnd;
          }
          return true;
        });
        return { ...item, points: relabelFilteredPoints(points, groupKey, normalized) };
      })
      .filter((item) => item.points.length);
  }

  function relabelFilteredPoints(points, groupKey, filter) {
    if (filter.scope === "month") {
      return points.map((point, index) => {
        const dayNumber = groupKey === "hourly" ? Math.floor(index / 24) + 1 : index + 1;
        return { ...point, x: `第${dayNumber}日` };
      });
    }
    if (filter.scope === "day" && groupKey === "hourly") {
      return points.map((point, index) => ({ ...point, x: `${index + 1}时` }));
    }
    return points;
  }

  function numericPointIndex(value, fallback) {
    const direct = Number(value);
    if (Number.isFinite(direct) && direct > 0) return Math.round(direct);
    const match = String(value ?? "").match(/\d+/);
    const parsed = match ? Number(match[0]) : Number(fallback);
    return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : 1;
  }

  function seriesKey(curveName, label) {
    return `${curveName || ""}::${label || ""}`;
  }

  function downsample(points, limit) {
    if (points.length <= limit) return points;
    const step = Math.ceil(points.length / limit);
    return points.filter((_, index) => index % step === 0);
  }

  function formatAxis(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "-";
    return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatDisplayValue(value) {
    const row = arguments[1] || null;
    const header = arguments[2] || "";
    if (row?.["指标"] === "度电成本" && header !== "指标") return formatLevelizedCostValue(value);
    if (typeof value !== "number" || !Number.isFinite(value)) return value ?? "";
    return Number.isInteger(value) ? value.toLocaleString("zh-CN") : formatAxis(value);
  }

  function formatLevelizedCostValue(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return value ?? "";
    return number.toLocaleString("zh-CN", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
  }

  window.ResultCurveViewer = { create };
})();
