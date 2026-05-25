(function () {
  const CHART_COLORS = ["#21d5ff", "#82e7b5", "#ffc857", "#ff7a90", "#b38cff", "#5ee7df", "#ff9f43", "#ff6bcb"];
  const LINE_PATTERNS = ["", "7 4", "2 4", "10 4 2 4"];
  const GROUP_DEFINITIONS = [
    { key: "hourly", title: "小时级曲线" },
    { key: "daily", title: "日级统计" },
    { key: "monthly", title: "月度统计" },
    { key: "annual", title: "年度统计" },
  ];
  const ANNUAL_META_HEADERS = new Set(["指标", "单位", "数值", "说明"]);
  const ANNUAL_BAR_COLORS = ["#21d5ff", "#82e7b5", "#ffc857", "#ff7a90"];
  const ANNUAL_LINE_COLOR = "#ff6bcb";
  const ANNUAL_GRID_SPLIT_MIN = 3;
  const ANNUAL_COMPARISON_DEFINITIONS = [
    {
      title: "成本对比",
      bars: [
        { label: "年均总成本", aliases: ["年均总成本", "年总成本", "总成本"] },
        { label: "年均建设成本", aliases: ["年均建设成本"] },
        { label: "年运行成本", aliases: ["年运行成本", "年柴油成本", "运行成本"] },
      ],
      line: { label: "度电成本", aliases: ["度电成本"] },
    },
    {
      title: "电量对比",
      bars: [
        { label: "负荷用电量", aliases: ["负荷用电量", "负荷总电量", "负荷电量"] },
        { label: "柴油发电量", aliases: ["柴油发电量", "柴发总发电量", "柴发总电量", "柴发电量"] },
        {
          label: "新能源总发电量",
          sum: [
            ["风机总发电量", "风电总发电量", "风机总电量", "风电总电量"],
            ["光伏总发电量", "光伏总电量"],
          ],
          fallbackAliases: ["新能源总发电量", "新能源实发电量", "新能源实际电量"],
        },
      ],
      line: { label: "新能源占比", aliases: ["新能源占比", "绿电占比", "绿色电量占比"] },
    },
    {
      title: "新能源利用对比",
      bars: [
        { label: "新能源最大可发", aliases: ["新能源最大可发", "新能源最大可发电量"] },
        { label: "新能源实际电量", aliases: ["新能源实际电量", "新能源实发电量", "新能源总发电量"] },
      ],
      line: { label: "新能源弃电率", aliases: ["新能源弃电率", "弃电率"] },
    },
    {
      title: "储能氢能发电对比",
      bars: [
        { label: "储能发电量", aliases: ["储能发电量", "电储能总放电量", "电储总发电量", "储能放电量"] },
        { label: "燃料电池发电量", aliases: ["燃料电池发电量", "燃料电池总发电量", "氢储总发电量"] },
      ],
    },
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
      annualHiddenSeries: [],
      curveRangeFilter: defaultCurveRangeFilter(),
      activeGroup: "hourly",
      annualViewMode: "table",
      annualGridSplit: { column: 50, row: 50 },
      statsVisible: true,
      statsPosition: null,
      statsDrag: null,
      suppressStatsPanelClick: false,
      listInteractionsBound: false,
      chartControlsBound: false,
      annualLegendBound: false,
      hoverIndex: null,
      emptyText: options.emptyText || "暂无小时级曲线",
      promptText: options.promptText || "请选择小时级曲线",
      loadingText: options.loadingText || "小时级曲线正在后台加载",
    };

    function setData(payload) {
      state.groups = normalizeGroups(payload);
      state.annualTable = Array.isArray(payload?.annual_table) ? payload.annual_table : [];
      state.annualHiddenSeries = state.annualHiddenSeries.filter((seriesId) => availableAnnualSeriesIds().includes(seriesId));
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
      state.annualHiddenSeries = [];
      state.curveRangeFilter = defaultCurveRangeFilter();
      state.activeGroup = "hourly";
      state.annualViewMode = "table";
      state.annualGridSplit = { column: 50, row: 50 };
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
        target.innerHTML = state.annualTable.length && options.enableAnnualBarComparison
          ? `${tabs}${renderAnnualModeSwitch()}`
          : `${tabs}<div class="empty-summary">${state.annualTable.length ? "年度统计以表格显示" : escapeHtml(message || "暂无年度统计")}</div>`;
        bindCurveNameListInteractions(target);
        return;
      }
      if (!group.curves.length) {
        target.innerHTML = `${tabs}<div class="empty-summary">${escapeHtml(message || groupEmptyText())}</div>`;
        bindCurveNameListInteractions(target);
        return;
      }
      target.innerHTML = `${tabs}<ul aria-multiselectable="true">${group.curves
        .map((name) => {
          const active = selectedCurveNames().includes(name);
          return `<li class="comparison-curve-name-item${active ? " active" : ""}" data-result-curve-name="${escapeHtml(name)}" role="option" aria-selected="${active ? "true" : "false"}" tabindex="0">${escapeHtml(name)}</li>`;
        })
        .join("")}</ul>`;
      bindCurveNameListInteractions(target);
    }

    function renderGroupTabs() {
      return `<div class="curve-group-tabs" role="tablist" aria-label="曲线统计类型">${GROUP_DEFINITIONS.map((group) => {
        const active = group.key === state.activeGroup;
        return `<button class="curve-group-tab${active ? " active" : ""}" type="button" data-curve-group="${group.key}" role="tab" aria-selected="${active ? "true" : "false"}">${escapeHtml(group.title)}</button>`;
      }).join("")}</div>`;
    }

    function renderAnnualModeSwitch() {
      return `<div class="empty-summary annual-view-switch" role="group" aria-label="年度统计显示方式">
        ${["table", "bar"].map((mode) => {
          const active = state.annualViewMode === mode;
          const label = mode === "table" ? "表格显示" : "柱图对比";
          return `<button type="button" class="annual-view-toggle${active ? " active" : ""}" data-annual-view-mode="${mode}" aria-pressed="${active ? "true" : "false"}">${label}</button>`;
        }).join("")}
      </div>`;
    }

    function bindCurveNameListInteractions(target) {
      if (!target || state.listInteractionsBound) return;
      state.listInteractionsBound = true;
      target.addEventListener("click", (event) => {
        const groupButton = event.target.closest("[data-curve-group]");
        if (groupButton && target.contains(groupButton)) {
          activateCurveGroup(groupButton.dataset.curveGroup || "hourly");
          return;
        }
        const modeButton = event.target.closest("[data-annual-view-mode]");
        if (modeButton && target.contains(modeButton)) {
          activateAnnualViewMode(modeButton.dataset.annualViewMode || "table");
          return;
        }
        const curveItem = event.target.closest("[data-result-curve-name]");
        if (curveItem && target.contains(curveItem)) {
          toggleCurve(curveItem.dataset.resultCurveName || "", { multi: isMultiCurveSelectionEvent(event) });
        }
      });
      target.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const curveItem = event.target.closest("[data-result-curve-name]");
        if (!curveItem || !target.contains(curveItem)) return;
        event.preventDefault();
        toggleCurve(curveItem.dataset.resultCurveName || "", { multi: isMultiCurveSelectionEvent(event) });
      });
    }

    function activateCurveGroup(groupKey) {
      const nextGroup = GROUP_DEFINITIONS.some((group) => group.key === groupKey) ? groupKey : "hourly";
      if (state.activeGroup === nextGroup) return;
      state.activeGroup = nextGroup;
      state.curveRangeFilter = normalizeCurveRangeFilter(state.curveRangeFilter, state.activeGroup);
      state.hoverIndex = null;
      render();
      notifySelectionChange();
    }

    function activateAnnualViewMode(modeValue) {
      const mode = modeValue === "bar" ? "bar" : "table";
      if (state.annualViewMode === mode) return;
      state.annualViewMode = mode;
      render();
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
      notifySelectionChange();
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
        if (options.enableAnnualBarComparison && state.annualViewMode === "bar") renderAnnualBarComparison(target, message);
        else renderAnnualTable(target, message);
        return;
      }
      const curveNames = selectedCurveNames();
      const allSeries = selectedCurveSeries();
      const visibleSeries = allSeries.filter((item) => !isSeriesHidden(item.seriesId));
      const controls = renderRangeControls();
      if (!curveNames.length || !allSeries.length) {
        const emptyMessage = curveNames.length && !allSeries.length && state.activeGroup === "hourly"
          ? state.loadingText
          : message || groupPromptText();
        target.innerHTML = `${controls}<div class="empty-summary">${escapeHtml(emptyMessage)}</div>`;
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
          ${renderStatsContextMenu()}
        </div>`;
      bindRangeControls(target);
      bindCurveLegendToggles(target);
      bindStatsPanelInteractions(target);
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
      if (!target || state.chartControlsBound) return;
      state.chartControlsBound = true;
      target.addEventListener("click", (event) => {
        const scopeButton = event.target.closest("[data-curve-range-scope]");
        if (!scopeButton || !target.contains(scopeButton) || scopeButton.disabled) return;
        state.curveRangeFilter = normalizeCurveRangeFilter({ ...state.curveRangeFilter, scope: scopeButton.dataset.curveRangeScope || "year" }, state.activeGroup);
        state.hoverIndex = null;
        render();
      });
      target.addEventListener("change", (event) => {
        if (event.target.matches("[data-curve-range-month]")) {
          state.curveRangeFilter = normalizeCurveRangeFilter({ ...state.curveRangeFilter, month: Number(event.target.value), day: 1 }, state.activeGroup);
          state.hoverIndex = null;
          render();
        }
        if (event.target.matches("[data-curve-range-day]")) {
          state.curveRangeFilter = normalizeCurveRangeFilter({ ...state.curveRangeFilter, day: Number(event.target.value) }, state.activeGroup);
          state.hoverIndex = null;
          render();
        }
      });
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

    function renderAnnualBarComparison(target, message) {
      if (!state.annualTable.length) {
        target.innerHTML = `<div class="empty-summary">${escapeHtml(message || "暂无年度统计")}</div>`;
        return;
      }
      const caseHeaders = annualCaseHeaders();
      if (!caseHeaders.length) {
        target.innerHTML = `<div class="empty-summary">${escapeHtml(message || "暂无柱图对比数据")}</div>`;
        return;
      }
      const charts = ANNUAL_COMPARISON_DEFINITIONS.map((definition) => renderAnnualComparisonChart(definition, caseHeaders)).join("");
      target.innerHTML = charts
        ? `<div class="annual-comparison-grid" style="${annualGridStyle()}">${charts}${renderAnnualGridResizers()}</div>`
        : `<div class="empty-summary">${escapeHtml(message || "暂无柱图对比数据")}</div>`;
      bindAnnualGridResizers(target);
      bindAnnualChartHover(target);
      bindAnnualLegendToggles(target);
    }

    function renderAnnualComparisonChart(definition, caseHeaders) {
      const barMetrics = (definition.bars || [])
        .map((item) => annualMetricFromDefinition(item, caseHeaders))
        .filter(Boolean)
        .map((metric) => ({ ...metric, seriesId: annualSeriesId(definition.title, metric.label) }));
      const lineMetric = definition.line
        ? (() => {
            const metric = annualMetricFromDefinition(definition.line, caseHeaders);
            return metric ? { ...metric, seriesId: annualSeriesId(definition.title, metric.label) } : null;
          })()
        : null;
      if (!barMetrics.length && !lineMetric) {
        return `<section class="annual-comparison-card"><h3>${escapeHtml(definition.title)}</h3><div class="empty-summary">暂无柱图对比数据</div></section>`;
      }
      const visibleBarMetrics = barMetrics.filter((metric) => !isAnnualSeriesHidden(metric.seriesId));
      const visibleLineMetric = lineMetric && !isAnnualSeriesHidden(lineMetric.seriesId) ? lineMetric : null;
      if (!visibleBarMetrics.length && !visibleLineMetric) {
        return `<section class="annual-comparison-card">
          ${renderAnnualComparisonHead(definition, barMetrics, lineMetric)}
          <div class="annual-comparison-chart">
            <div class="empty-summary">暂无可显示曲线</div>
          </div>
        </section>`;
      }

      const width = 920;
      const height = 220;
      const margin = { top: 18, right: visibleLineMetric ? 64 : 24, bottom: 44, left: 68 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const leftValues = visibleBarMetrics.flatMap((metric) => metric.values).filter(Number.isFinite);
      const rightValues = visibleLineMetric ? visibleLineMetric.values.filter(Number.isFinite) : [];
      const leftMax = Math.max(...leftValues, 1);
      const rightMax = Math.max(...rightValues, 1);
      const groupWidth = plotWidth / Math.max(caseHeaders.length, 1);
      const gap = Math.min(8, Math.max(3, groupWidth * 0.04));
      const barWidth = Math.max(5, Math.min(26, (groupWidth - 22) / Math.max(visibleBarMetrics.length + 0.5, 1)));
      const groupedWidth = visibleBarMetrics.length * barWidth + Math.max(visibleBarMetrics.length - 1, 0) * gap;
      const xCenter = (index) => margin.left + groupWidth * index + groupWidth / 2;
      const yLeft = (value) => margin.top + plotHeight - (Math.max(Number(value) || 0, 0) / leftMax) * plotHeight;
      const yRight = (value) => margin.top + plotHeight - (Math.max(Number(value) || 0, 0) / rightMax) * plotHeight;
      const linePoints = visibleLineMetric
        ? visibleLineMetric.values.map((value, index) => `${xCenter(index).toFixed(2)},${yRight(value).toFixed(2)}`)
        : [];
      const linePointOverlays = visibleLineMetric ? renderAnnualLinePoints({ width, height, xCenter, yRight, lineMetric: visibleLineMetric, caseHeaders }) : "";
      const overlays = renderAnnualChartLabels({
        width,
        height,
        margin,
        groupWidth,
        xCenter,
        caseHeaders,
        leftMax,
        rightMax,
        lineMetric: visibleLineMetric,
      });

      return `<section class="annual-comparison-card">
        ${renderAnnualComparisonHead(definition, barMetrics, lineMetric)}
        <div class="annual-comparison-chart">
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(definition.title)}">
            <line class="annual-axis-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
            <line class="annual-axis-line" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
            ${visibleLineMetric ? `<line class="annual-axis-line" x1="${width - margin.right}" y1="${margin.top}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>` : ""}
            ${[0, 0.5, 1].map((ratio) => {
              const y = margin.top + plotHeight - ratio * plotHeight;
              return `<line class="annual-grid-line" x1="${margin.left}" y1="${y.toFixed(2)}" x2="${width - margin.right}" y2="${y.toFixed(2)}"></line>`;
            }).join("")}
            ${visibleBarMetrics.map((metric, metricIndex) =>
              metric.values
                .map((value, caseIndex) => {
                  const safeValue = Math.max(Number(value) || 0, 0);
                  const x = xCenter(caseIndex) - groupedWidth / 2 + metricIndex * (barWidth + gap);
                  const y = yLeft(safeValue);
                  const h = Math.max(height - margin.bottom - y, 0);
                  return `<rect class="annual-bar" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${h.toFixed(2)}" fill="${ANNUAL_BAR_COLORS[metricIndex % ANNUAL_BAR_COLORS.length]}" data-annual-chart-hit="bar" data-annual-chart-title="${escapeHtml(definition.title)}" data-annual-chart-case="${escapeHtml(caseHeaders[caseIndex])}" data-annual-chart-metric="${escapeHtml(metric.label)}" data-annual-chart-value="${escapeHtml(formatAnnualMetricValue(safeValue, metric))}" data-annual-chart-unit="${escapeHtml(metric.unit || "")}"></rect>`;
                })
                .join(""),
            ).join("")}
            ${visibleLineMetric ? `<polyline class="annual-line" points="${linePoints.join(" ")}"></polyline>` : ""}
          </svg>
          ${overlays}
          ${linePointOverlays}
          <div class="comparison-chart-tooltip annual-chart-tooltip" data-annual-chart-tooltip hidden></div>
        </div>
      </section>`;
    }

    function renderAnnualComparisonHead(definition, barMetrics, lineMetric) {
      const axisText = `${translateDisplay("左轴")} ${barMetrics[0]?.unit || ""}${lineMetric ? ` / ${translateDisplay("右轴")} ${lineMetric.unit || ""}` : ""}`;
      return `<div class="annual-comparison-head">
        <h3>${escapeHtml(definition.title)}</h3>
        ${renderAnnualComparisonLegend(barMetrics, lineMetric)}
        <span class="annual-axis-note">${escapeHtml(axisText)}</span>
      </div>`;
    }

    function renderAnnualChartLabels({ width, height, margin, groupWidth, xCenter, caseHeaders, leftMax, rightMax, lineMetric }) {
      const pctX = (value) => ((value / Math.max(width, 1)) * 100).toFixed(2);
      const pctY = (value) => ((value / Math.max(height, 1)) * 100).toFixed(2);
      const leftX = pctX(margin.left);
      const rightX = pctX(width - margin.right);
      const topY = pctY(margin.top + 2);
      const bottomY = pctY(height - margin.bottom);
      const xLabelY = pctY(height - 14);
      const xLabelWidth = Math.max(6, Math.min(18, (groupWidth / Math.max(width, 1)) * 82)).toFixed(2);
      const leftLabelStyle = `left:4px; width:max(0px, calc(${leftX}% - 12px));`;
      const rightLabelStyle = `left:calc(${rightX}% + 8px); width:max(0px, calc(100% - ${rightX}% - 12px));`;
      const rightAxisLabels = lineMetric
        ? `<span class="annual-chart-axis-label annual-chart-axis-label-right" style="${rightLabelStyle} top:${topY}%">${escapeHtml(formatAnnualAxisValue(rightMax, lineMetric))}</span>
          <span class="annual-chart-axis-label annual-chart-axis-label-right" style="${rightLabelStyle} top:${bottomY}%">0</span>`
        : "";
      return `<div class="annual-chart-axis-labels" aria-hidden="true">
          <span class="annual-chart-axis-label annual-chart-axis-label-left" style="${leftLabelStyle} top:${topY}%">${escapeHtml(formatAxis(leftMax))}</span>
          <span class="annual-chart-axis-label annual-chart-axis-label-left" style="${leftLabelStyle} top:${bottomY}%">0</span>
          ${rightAxisLabels}
        </div>
        <div class="annual-chart-x-axis" aria-hidden="true" style="--annual-x-label-width:${xLabelWidth}%">${caseHeaders
          .map((label, index) => `<span title="${escapeHtml(label)}" style="left:${pctX(xCenter(index))}%; top:${xLabelY}%">${escapeHtml(shortCaseLabel(label))}</span>`)
          .join("")}</div>`;
    }

    function renderAnnualLinePoints({ width, height, xCenter, yRight, lineMetric, caseHeaders }) {
      const pctX = (value) => ((value / Math.max(width, 1)) * 100).toFixed(2);
      const pctY = (value) => ((value / Math.max(height, 1)) * 100).toFixed(2);
      return `<div class="annual-line-points" aria-hidden="true">${lineMetric.values
        .map((value, index) => {
          const safeValue = Math.max(Number(value) || 0, 0);
          return `<span class="annual-line-point" style="left:${pctX(xCenter(index))}%; top:${pctY(yRight(safeValue))}%" data-annual-chart-hit="line" data-annual-chart-title="${escapeHtml(lineMetric.label)}" data-annual-chart-case="${escapeHtml(caseHeaders[index])}" data-annual-chart-metric="${escapeHtml(lineMetric.label)}" data-annual-chart-value="${escapeHtml(formatAnnualMetricValue(safeValue, lineMetric))}" data-annual-chart-unit="${escapeHtml(lineMetric.unit || "")}"></span>`;
        })
        .join("")}</div>`;
    }

    function renderAnnualComparisonLegend(barMetrics, lineMetric) {
      const barLegends = barMetrics
        .map((metric, index) => renderAnnualLegendButton(metric, ANNUAL_BAR_COLORS[index % ANNUAL_BAR_COLORS.length]))
        .join("");
      const lineLegend = lineMetric ? renderAnnualLegendButton(lineMetric, ANNUAL_LINE_COLOR, "line") : "";
      return `<div class="annual-comparison-legend">${barLegends}${lineLegend}</div>`;
    }

    function renderAnnualLegendButton(metric, color, iconClass = "") {
      const hidden = isAnnualSeriesHidden(metric.seriesId);
      return `<button type="button" class="${hidden ? "is-hidden" : ""}" data-annual-series-toggle="${escapeHtml(metric.seriesId)}" aria-pressed="${hidden ? "false" : "true"}" title="显示/隐藏曲线">
        <i class="${escapeHtml(iconClass)}" style="background:${escapeHtml(color)}"></i>${escapeHtml(metric.label)}
      </button>`;
    }

    function bindAnnualLegendToggles(target) {
      if (!target || state.annualLegendBound) return;
      state.annualLegendBound = true;
      target.addEventListener("click", (event) => {
        const button = event.target.closest("[data-annual-series-toggle]");
        if (!button || !target.contains(button)) return;
        event.preventDefault();
        event.stopPropagation();
        toggleAnnualSeriesVisibility(button.dataset.annualSeriesToggle || "");
      });
    }

    function toggleAnnualSeriesVisibility(seriesId) {
      if (!seriesId) return;
      const hidden = new Set(state.annualHiddenSeries || []);
      if (hidden.has(seriesId)) hidden.delete(seriesId);
      else hidden.add(seriesId);
      state.annualHiddenSeries = Array.from(hidden);
      render();
    }

    function isAnnualSeriesHidden(seriesId) {
      return Boolean(seriesId && (state.annualHiddenSeries || []).includes(seriesId));
    }

    function annualSeriesId(chartTitle, label) {
      return `${chartTitle || ""}::${label || ""}`;
    }

    function availableAnnualSeriesIds() {
      if (!state.annualTable.length) return [];
      const caseHeaders = annualCaseHeaders();
      return ANNUAL_COMPARISON_DEFINITIONS.flatMap((definition) => {
        const barIds = (definition.bars || [])
          .map((item) => annualMetricFromDefinition(item, caseHeaders))
          .filter(Boolean)
          .map((metric) => annualSeriesId(definition.title, metric.label));
        const lineMetric = definition.line ? annualMetricFromDefinition(definition.line, caseHeaders) : null;
        return lineMetric ? [...barIds, annualSeriesId(definition.title, lineMetric.label)] : barIds;
      });
    }

    function renderAnnualGridResizers() {
      return `<div class="annual-grid-resizer annual-grid-resizer-col" data-annual-grid-resizer="column" role="separator" tabindex="0" aria-label="调整年度柱图左右宽度" aria-orientation="vertical" aria-valuemin="${ANNUAL_GRID_SPLIT_MIN}" aria-valuemax="${100 - ANNUAL_GRID_SPLIT_MIN}" aria-valuenow="${Math.round(state.annualGridSplit.column)}"></div>
        <div class="annual-grid-resizer annual-grid-resizer-row" data-annual-grid-resizer="row" role="separator" tabindex="0" aria-label="调整年度柱图上下高度" aria-orientation="horizontal" aria-valuemin="${ANNUAL_GRID_SPLIT_MIN}" aria-valuemax="${100 - ANNUAL_GRID_SPLIT_MIN}" aria-valuenow="${Math.round(state.annualGridSplit.row)}"></div>`;
    }

    function bindAnnualGridResizers(target) {
      target.querySelectorAll("[data-annual-grid-resizer]").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => {
          const grid = handle.closest(".annual-comparison-grid");
          if (!grid) return;
          event.preventDefault();
          handle.setPointerCapture?.(event.pointerId);
          handle.classList.add("dragging");
          const axis = handle.dataset.annualGridResizer === "row" ? "row" : "column";
          const onMove = (moveEvent) => updateAnnualGridSplitFromPointer(grid, axis, moveEvent);
          const onEnd = () => {
            handle.classList.remove("dragging");
            handle.removeEventListener("pointermove", onMove);
            handle.removeEventListener("pointerup", onEnd);
            handle.removeEventListener("pointercancel", onEnd);
          };
          handle.addEventListener("pointermove", onMove);
          handle.addEventListener("pointerup", onEnd);
          handle.addEventListener("pointercancel", onEnd);
          updateAnnualGridSplitFromPointer(grid, axis, event);
        });
        handle.addEventListener("keydown", (event) => {
          const axis = handle.dataset.annualGridResizer === "row" ? "row" : "column";
          const keyDelta = event.shiftKey ? 8 : 3;
          const deltaMap = axis === "row"
            ? { ArrowUp: -keyDelta, ArrowDown: keyDelta }
            : { ArrowLeft: -keyDelta, ArrowRight: keyDelta };
          if (!(event.key in deltaMap)) return;
          event.preventDefault();
          const grid = handle.closest(".annual-comparison-grid");
          if (!grid) return;
          setAnnualGridSplit(grid, axis, state.annualGridSplit[axis] + deltaMap[event.key]);
        });
      });
    }

    function updateAnnualGridSplitFromPointer(grid, axis, event) {
      const rect = grid.getBoundingClientRect();
      const ratio = axis === "row"
        ? ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100
        : ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
      setAnnualGridSplit(grid, axis, ratio);
    }

    function setAnnualGridSplit(grid, axis, value) {
      const next = Math.min(Math.max(Number(value) || 50, ANNUAL_GRID_SPLIT_MIN), 100 - ANNUAL_GRID_SPLIT_MIN);
      state.annualGridSplit[axis] = next;
      applyAnnualGridStyle(grid);
    }

    function annualGridStyle() {
      const column = Math.min(Math.max(Number(state.annualGridSplit.column) || 50, ANNUAL_GRID_SPLIT_MIN), 100 - ANNUAL_GRID_SPLIT_MIN);
      const row = Math.min(Math.max(Number(state.annualGridSplit.row) || 50, ANNUAL_GRID_SPLIT_MIN), 100 - ANNUAL_GRID_SPLIT_MIN);
      return [
        `--annual-grid-left:${column.toFixed(3)}fr`,
        `--annual-grid-right:${(100 - column).toFixed(3)}fr`,
        `--annual-grid-top:${row.toFixed(3)}fr`,
        `--annual-grid-bottom:${(100 - row).toFixed(3)}fr`,
        `--annual-grid-col-position:${column.toFixed(3)}%`,
        `--annual-grid-row-position:${row.toFixed(3)}%`,
      ].join("; ");
    }

    function applyAnnualGridStyle(grid) {
      grid.setAttribute("style", annualGridStyle());
      grid.querySelector('[data-annual-grid-resizer="column"]')?.setAttribute("aria-valuenow", String(Math.round(state.annualGridSplit.column)));
      grid.querySelector('[data-annual-grid-resizer="row"]')?.setAttribute("aria-valuenow", String(Math.round(state.annualGridSplit.row)));
    }

    function bindAnnualChartHover(target) {
      target.querySelectorAll("[data-annual-chart-hit]").forEach((hit) => {
        hit.addEventListener("pointerenter", (event) => renderAnnualChartHover(hit, event));
        hit.addEventListener("pointermove", (event) => renderAnnualChartHover(hit, event));
        hit.addEventListener("pointerleave", () => {
          const tooltip = hit.closest(".annual-comparison-chart")?.querySelector("[data-annual-chart-tooltip]");
          if (tooltip) tooltip.hidden = true;
        });
      });
    }

    function renderAnnualChartHover(hit, event) {
      const chart = hit.closest(".annual-comparison-chart");
      const tooltip = chart?.querySelector("[data-annual-chart-tooltip]");
      if (!chart || !tooltip) return;
      const unit = hit.dataset.annualChartUnit || "";
      tooltip.innerHTML = `
        <h3>${escapeHtml(translateDisplay(hit.dataset.annualChartTitle || ""))}</h3>
        <div><span>${escapeHtml(translateDisplay("对比项"))}</span><strong>${escapeHtml(hit.dataset.annualChartCase || "")}</strong></div>
        <div><span>${escapeHtml(translateDisplay("指标"))}</span><strong>${escapeHtml(translateDisplay(hit.dataset.annualChartMetric || ""))}</strong></div>
        <div><span>${escapeHtml(translateDisplay("数值"))}</span><strong>${escapeHtml(hit.dataset.annualChartValue || "")}${unit ? ` ${escapeHtml(unit)}` : ""}</strong></div>`;
      tooltip.hidden = false;
      const bounds = chart.getBoundingClientRect();
      const tooltipX = Math.min(Math.max(event.clientX - bounds.left + 14, 8), Math.max(bounds.width - tooltip.offsetWidth - 8, 8));
      const tooltipY = Math.min(Math.max(event.clientY - bounds.top + 14, 8), Math.max(bounds.height - tooltip.offsetHeight - 8, 8));
      tooltip.style.left = `${Math.round(tooltipX)}px`;
      tooltip.style.top = `${Math.round(tooltipY)}px`;
    }

    function annualCaseHeaders() {
      const headers = [];
      state.annualTable.forEach((row) => {
        Object.keys(row || {}).forEach((key) => {
          if (ANNUAL_META_HEADERS.has(key) || headers.includes(key)) return;
          if (state.annualTable.some((item) => Number.isFinite(toNumber(item?.[key])))) headers.push(key);
        });
      });
      return headers;
    }

    function annualMetricFromDefinition(definition, caseHeaders) {
      if (definition.sum) {
        const summed = sumAnnualMetric(definition.label, definition.sum, caseHeaders);
        if (summed) return summed;
        return readAnnualMetric(definition.fallbackAliases || [], definition.label, caseHeaders);
      }
      return readAnnualMetric(definition.aliases || [definition.label], definition.label, caseHeaders);
    }

    function sumAnnualMetric(label, aliasGroups, caseHeaders) {
      const metrics = aliasGroups.map((aliases) => readAnnualMetric(aliases, aliases[0], caseHeaders)).filter(Boolean);
      if (!metrics.length) return null;
      return {
        label,
        unit: metrics.find((metric) => metric.unit)?.unit || "",
        values: caseHeaders.map((_, index) => metrics.reduce((sum, metric) => sum + (Number(metric.values[index]) || 0), 0)),
      };
    }

    function readAnnualMetric(aliases, label, caseHeaders) {
      const row = annualMetricRow(aliases);
      if (!row) return null;
      const values = caseHeaders.map((header) => {
        const value = toNumber(row[header]);
        return Number.isFinite(value) ? value : 0;
      });
      if (!values.some(Number.isFinite)) return null;
      return { label, unit: row["单位"] || "", values };
    }

    function annualMetricRow(aliases) {
      const names = aliases.map((item) => String(item || "").trim()).filter(Boolean);
      return (
        state.annualTable.find((row) => names.includes(String(row?.["指标"] || "").trim())) ||
        state.annualTable.find((row) => names.some((name) => String(row?.["指标"] || "").includes(name)))
      );
    }

    function toNumber(value) {
      if (typeof value === "number") return value;
      const normalized = String(value ?? "").replace(/,/g, "").replace(/%/g, "").trim();
      if (!normalized) return NaN;
      const number = Number(normalized);
      return Number.isFinite(number) ? number : NaN;
    }

    function shortCaseLabel(label) {
      const text = String(label || "");
      return text.length > 12 ? `${text.slice(0, 10)}…` : text;
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
      const hiddenClass = state.statsVisible ? "" : " stats-hidden";
      const style = statsPanelStyle();
      return `<div class="result-curve-legend${hiddenClass}" data-result-stats-panel aria-label="曲线显示和统计信息" title="拖动可移动统计信息，右键显示菜单"${style ? ` style="${style}"` : ""}>${series
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

    function renderStatsContextMenu() {
      const label = state.statsVisible ? "隐藏统计信息" : "显示统计信息";
      return `<div class="result-curve-context-menu" data-result-stats-menu hidden role="menu" aria-label="统计信息菜单">
        <button type="button" data-result-stats-action="toggle" role="menuitem">${label}</button>
        <button type="button" data-result-stats-action="reset" role="menuitem">恢复统计位置</button>
      </div>`;
    }

    function statsPanelStyle() {
      if (!state.statsPosition) return "";
      const left = Math.min(Math.max(Number(state.statsPosition.left) || 0, 0), 100);
      const top = Math.min(Math.max(Number(state.statsPosition.top) || 0, 0), 100);
      return `left:${left.toFixed(3)}%; top:${top.toFixed(3)}%; right:auto;`;
    }

    function bindCurveLegendToggles(target) {
      if (!target || target.dataset.resultLegendToggleBound === "true") return;
      target.dataset.resultLegendToggleBound = "true";
      target.addEventListener("click", (event) => {
        const button = event.target.closest("[data-result-series-toggle]");
        if (!button || !target.contains(button)) return;
        if (state.suppressStatsPanelClick) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        toggleSeriesVisibility(button.dataset.resultSeriesToggle || "");
      });
    }

    function bindStatsPanelInteractions(target) {
      const frame = target.querySelector(".comparison-chart-frame");
      const panel = target.querySelector("[data-result-stats-panel]");
      const menu = target.querySelector("[data-result-stats-menu]");
      if (panel) {
        panel.addEventListener("pointerdown", startStatsPanelDrag);
      }
      if (!frame || !menu) return;
      frame.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        showStatsContextMenu(frame, menu, event);
      });
      frame.addEventListener("click", (event) => {
        if (!event.target.closest("[data-result-stats-menu]")) hideStatsContextMenu(menu);
      });
      menu.addEventListener("click", (event) => {
        const action = event.target.closest("[data-result-stats-action]")?.dataset.resultStatsAction || "";
        if (!action) return;
        event.preventDefault();
        event.stopPropagation();
        if (action === "toggle") state.statsVisible = !state.statsVisible;
        if (action === "reset") state.statsPosition = null;
        state.hoverIndex = null;
        render();
      });
    }

    function showStatsContextMenu(frame, menu, event) {
      const bounds = frame.getBoundingClientRect();
      menu.hidden = false;
      const width = menu.offsetWidth || 150;
      const height = menu.offsetHeight || 76;
      const padding = 8;
      const left = Math.min(Math.max(event.clientX - bounds.left, padding), Math.max(padding, bounds.width - width - padding));
      const top = Math.min(Math.max(event.clientY - bounds.top, padding), Math.max(padding, bounds.height - height - padding));
      menu.style.left = `${Math.round(left)}px`;
      menu.style.top = `${Math.round(top)}px`;
    }

    function hideStatsContextMenu(menu) {
      if (menu) menu.hidden = true;
    }

    function startStatsPanelDrag(event) {
      if (event.button !== undefined && event.button !== 0) return;
      if (event.target.closest("[data-result-series-toggle]")) return;
      const panel = event.currentTarget;
      const frame = panel.closest(".comparison-chart-frame");
      if (!panel || !frame || event.target.closest("[data-result-stats-menu]")) return;
      const frameRect = frame.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      event.preventDefault();
      state.statsDrag = {
        pointerId: event.pointerId,
        frame,
        panel,
        startX: event.clientX,
        startY: event.clientY,
        startLeft: panelRect.left - frameRect.left,
        startTop: panelRect.top - frameRect.top,
        moved: false,
      };
      panel.classList.add("dragging");
      panel.setPointerCapture?.(event.pointerId);
      hideStatsContextMenu(frame.querySelector("[data-result-stats-menu]"));
      window.addEventListener("pointermove", onStatsPanelDragMove);
      window.addEventListener("pointerup", endStatsPanelDrag);
      window.addEventListener("pointercancel", endStatsPanelDrag);
    }

    function onStatsPanelDragMove(event) {
      const drag = state.statsDrag;
      if (!drag) return;
      if (event.pointerId !== undefined && drag.pointerId !== undefined && event.pointerId !== drag.pointerId) return;
      const deltaX = event.clientX - drag.startX;
      const deltaY = event.clientY - drag.startY;
      if (Math.abs(deltaX) + Math.abs(deltaY) > 3) drag.moved = true;
      const frameWidth = Math.max(drag.frame.clientWidth, 1);
      const frameHeight = Math.max(drag.frame.clientHeight, 1);
      const maxLeft = Math.max(0, frameWidth - drag.panel.offsetWidth);
      const maxTop = Math.max(0, frameHeight - drag.panel.offsetHeight);
      const nextLeft = Math.min(Math.max(drag.startLeft + deltaX, 0), maxLeft);
      const nextTop = Math.min(Math.max(drag.startTop + deltaY, 0), maxTop);
      state.statsPosition = {
        left: (nextLeft / frameWidth) * 100,
        top: (nextTop / frameHeight) * 100,
      };
      drag.panel.style.left = `${state.statsPosition.left.toFixed(3)}%`;
      drag.panel.style.top = `${state.statsPosition.top.toFixed(3)}%`;
      drag.panel.style.right = "auto";
    }

    function endStatsPanelDrag(event) {
      const drag = state.statsDrag;
      if (!drag) return;
      if (event?.pointerId !== undefined && drag.pointerId !== undefined && event.pointerId !== drag.pointerId) return;
      drag.panel.classList.remove("dragging");
      drag.panel.releasePointerCapture?.(drag.pointerId);
      if (drag.moved) {
        state.suppressStatsPanelClick = true;
        setTimeout(() => {
          state.suppressStatsPanelClick = false;
        }, 0);
      }
      state.statsDrag = null;
      window.removeEventListener("pointermove", onStatsPanelDragMove);
      window.removeEventListener("pointerup", endStatsPanelDrag);
      window.removeEventListener("pointercancel", endStatsPanelDrag);
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

    function currentSelection() {
      return {
        group: state.activeGroup,
        curves: selectedCurveNames(),
      };
    }

    function notifySelectionChange() {
      if (typeof options.onSelectionChange === "function") {
        options.onSelectionChange(currentSelection());
      }
    }

    clear();
    return { setData, clear, render, getSelection: currentSelection };
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

  function formatAnnualAxisValue(value, metric) {
    if (metric?.label === "度电成本") return formatLevelizedCostValue(value);
    return formatAxis(value);
  }

  function formatAnnualMetricValue(value, metric) {
    return formatAnnualAxisValue(value, metric);
  }

  function translateDisplay(value) {
    return window.PowerPlanI18n?.translate ? window.PowerPlanI18n.translate(value) : value;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
  }

  window.ResultCurveViewer = { create };
})();
