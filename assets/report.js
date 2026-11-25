(() => {
  "use strict";

  const PAGE_STATE_KEY = "report";
  const state = {
    schemes: [],
    currentScheme: "",
    selectedFile: "",
    data: null,
  };

  function escapeHtml(val) {
    return String(val ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function api(path) {
    const resp = await fetch(path);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.message || data.error || "请求失败");
    return data;
  }

  function findMetric(rows, keywords) {
    for (const kw of keywords) {
      const hit = (rows || []).find((r) => String(r["指标"] || r.label || "").includes(kw));
      if (hit) {
        const val = hit["数值"] ?? hit.value ?? "";
        const unit = hit["单位"] ?? hit.unit ?? "";
        return { value: val === "" ? "—" : String(val), unit: String(unit || "") };
      }
    }
    return { value: "—", unit: "" };
  }

  function renderSimpleTable(id, rows, columns, emptyText) {
    const host = document.getElementById(id);
    if (!host) return;
    if (!Array.isArray(rows) || !rows.length) {
      host.innerHTML = `<div class="empty-summary">${escapeHtml(emptyText)}</div>`;
      return;
    }
    const cols = columns || Object.keys(rows[0]);
    host.innerHTML = `
      <table>
        <thead><tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows
            .map((r) => `<tr>${cols.map((c) => `<td>${escapeHtml(r[c] === "" || r[c] == null ? "—" : r[c])}</td>`).join("")}</tr>`)
            .join("")}
        </tbody>
      </table>
    `;
  }

  function renderMonthlyChart(monthlyRows) {
    const svg = document.getElementById("reportMonthlyChart");
    if (!svg) return;
    const width = svg.clientWidth || 960;
    const height = 240;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const pal = window.PowerPlanUI?.getChartPalette?.() || {
      wind: "#38BDF8",
      solar: "#FBBF24",
      diesel: "#FB7185",
      load: "#34D399",
      grid: "rgba(255,255,255,0.08)",
      axis: "rgba(148,163,184,0.35)",
      text: "#94A3B8",
    };

    if (!Array.isArray(monthlyRows) || !monthlyRows.length) {
      svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.text}" font-size="13">暂无月度供能曲线数据</text>`;
      return;
    }

    const num = (row, keys) => {
      for (const k of keys) {
        if (row[k] !== undefined && row[k] !== "" && Number.isFinite(Number(row[k]))) return Number(row[k]);
      }
      return 0;
    };

    const parsed = monthlyRows.map((row, idx) => {
      const wind = num(row, ["wind_energy", "风电电量", "风电发电量"]);
      const pv = num(row, ["pv_energy", "光伏电量", "光伏发电量"]);
      const diesel = num(row, ["diesel_energy", "柴发电量", "柴发发电量"]);
      const load = num(row, ["load_energy", "负荷电量", "总负荷电量"]);
      const label = String(row.month || row["月份"] || `${idx + 1}月`);
      return { label, wind, pv, diesel, load, total: Math.max(wind + pv + diesel, load) };
    });

    const maxVal = Math.max(1, ...parsed.map((p) => p.total));
    const padL = 56;
    const padR = 20;
    const padT = 26;
    const padB = 34;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const slotW = plotW / parsed.length;
    const barW = Math.max(8, Math.min(30, slotW * 0.56));
    const sy = (v) => padT + plotH - (v / maxVal) * plotH;

    const grid = [0, 0.25, 0.5, 0.75, 1]
      .map((r) => {
        const yv = maxVal * r;
        const yy = sy(yv);
        return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${pal.grid}"/><text x="${padL - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="10.5">${Math.round(yv)}</text>`;
      })
      .join("");

    const bars = parsed
      .map((p, i) => {
        const cx = padL + slotW * i + slotW / 2;
        const x0 = cx - barW / 2;
        let acc = 0;
        const seg = (val, color) => {
          if (val <= 0) return "";
          const yTop = sy(acc + val);
          const yBot = sy(acc);
          acc += val;
          return `<rect x="${x0.toFixed(1)}" y="${yTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.5, yBot - yTop).toFixed(1)}" fill="${color}"/>`;
        };
        return `${seg(p.wind, pal.wind)}${seg(p.pv, pal.solar)}${seg(p.diesel, pal.diesel)}<text x="${cx.toFixed(1)}" y="${height - 12}" text-anchor="middle" fill="${pal.text}" font-size="10.5">${escapeHtml(p.label)}</text>`;
      })
      .join("");

    const loadLine = parsed
      .map((p, i) => {
        const cx = padL + slotW * i + slotW / 2;
        return `${i === 0 ? "M" : "L"}${cx.toFixed(1)},${sy(p.load).toFixed(1)}`;
      })
      .join(" ");

    const legend = [
      ["风电", pal.wind],
      ["光伏", pal.solar],
      ["柴发", pal.diesel],
      ["负荷曲线", pal.load],
    ]
      .map(
        ([name, color], idx) =>
          `<g transform="translate(${padL + idx * 82}, 10)"><rect width="10" height="8" rx="2" fill="${color}"/><text x="14" y="8" fill="${pal.text}" font-size="11">${name}</text></g>`,
      )
      .join("");

    svg.innerHTML = `${grid}<line x1="${padL}" x2="${width - padR}" y1="${padT + plotH}" y2="${padT + plotH}" stroke="${pal.axis}"/>${bars}<path d="${loadLine}" fill="none" stroke="${pal.load}" stroke-width="2"/>${legend}`;
  }

  function renderReport() {
    const d = state.data;
    if (!d) return;
    document.getElementById("reportTitle").textContent = `${d.scheme} · 综合评审简报`;
    document.getElementById("reportSubtitle").textContent = d.filename ? `结果文件：${d.filename}` : "尚未生成求解结果文件";
    document.getElementById("reportGeneratedAt").textContent = `生成时间：${d.generated_at || "—"}`;

    const fileSelect = document.getElementById("reportFileSelect");
    if (fileSelect) {
      const files = d.result_files || [];
      fileSelect.innerHTML = files.length
        ? files.map((f) => `<option value="${escapeHtml(f.name)}"${f.name === d.filename ? " selected" : ""}>${escapeHtml(f.name)}</option>`).join("")
        : `<option value="">暂无结果文件</option>`;
    }

    const q = new URLSearchParams({ scheme: d.scheme, ...(d.filename ? { file: d.filename } : {}) }).toString();
    document.getElementById("reportLinkSensitivity").href = `sensitivity.html?scheme=${encodeURIComponent(d.scheme)}`;
    document.getElementById("reportLinkReliability").href = `reliability.html?${q}`;
    document.getElementById("reportLinkEvaluation").href = `evaluation.html?${q}`;

    const lcoe = findMetric(d.green_table, ["综合度电成本", "度电成本"]);
    const annualCost = findMetric(d.green_table, ["年均总成本", "年总成本", "年化总成本", "总年化成本"]);
    const greenRatio = findMetric(d.green_table, ["绿电占比", "绿色电量占比", "新能源供电占比", "新能源占比"]);
    const freqMin = findMetric(d.safety_table, ["最低频率"]);
    const freqMax = findMetric(d.safety_table, ["最高频率"]);
    const esr = findMetric(d.reliability_rows, ["供电可靠率"]);

    const kpis = [
      { label: "度电成本", value: lcoe.value, unit: lcoe.unit },
      { label: "年均总成本", value: annualCost.value, unit: annualCost.unit },
      { label: "绿电占比", value: greenRatio.value, unit: greenRatio.unit },
      { label: "频率范围", value: freqMin.value !== "—" && freqMax.value !== "—" ? `${freqMin.value} ~ ${freqMax.value}` : "—", unit: "Hz" },
      { label: "供电可靠率", value: esr.value, unit: esr.unit || "%" },
      { label: "年总用电量", value: String(d.site_summary?.annual_load_mwh ?? "—"), unit: "MWh" },
    ];
    document.getElementById("reportKpiStrip").innerHTML = kpis
      .map(
        (k) => `
      <div class="report-kpi-item">
        <span>${escapeHtml(k.label)}</span>
        <strong>${escapeHtml(k.value)}<em>${escapeHtml(k.unit)}</em></strong>
      </div>
    `,
      )
      .join("");

    const s = d.site_summary || {};
    renderSimpleTable(
      "reportSiteTable",
      [
        { 项目: "仿真时长", 数值: s.hours ?? "—", 单位: "h" },
        { 项目: "峰值负荷", 数值: s.peak_load_kw ?? "—", 单位: "kW" },
        { 项目: "平均负荷", 数值: s.avg_load_kw ?? "—", 单位: "kW" },
        { 项目: "年总用电量", 数值: s.annual_load_mwh ?? "—", 单位: "MWh" },
        { 项目: "年均风速", 数值: s.avg_wind_ms ?? "—", 单位: "m/s" },
        { 项目: "年均辐照", 数值: s.avg_solar_wm2 ?? "—", 单位: "W/m²" },
      ],
      ["项目", "数值", "单位"],
      "暂无站点数据",
    );

    renderSimpleTable("reportCapacityTable", d.planning_table, null, "暂无规划装机配置");
    renderSimpleTable("reportGreenTable", d.green_table, null, "暂无经济性与绿电指标");
    renderSimpleTable("reportSafetyTable", d.safety_table, null, "暂无频率安全指标");
    renderSimpleTable("reportReliabilityTable", d.reliability_rows, ["指标", "数值", "单位"], "尚未执行供电可靠性评估，点击上方「可靠性校核」即可运行");
    renderMonthlyChart(d.monthly_curve);

    if (window.PowerPlanI18n) {
      window.PowerPlanI18n.translate(document.body, window.PowerPlanI18n.currentLanguage());
    }
  }

  async function loadReport(scheme, filename = "") {
    if (!scheme) return;
    state.currentScheme = scheme;
    state.selectedFile = filename;
    window.PowerPlanPageState?.write?.(PAGE_STATE_KEY, { currentScheme: scheme, selectedResultFile: filename });
    const qs = new URLSearchParams({ scheme, ...(filename ? { filename } : {}) }).toString();
    state.data = await api(`/api/report/summary?${qs}`);
    state.selectedFile = state.data.filename || "";
    renderReport();
  }

  async function init() {
    const saved = window.PowerPlanPageState?.read?.(PAGE_STATE_KEY, {}) || {};
    const ctx = window.PowerPlanPageState?.getActiveContext?.() || {};
    const listRes = await api("/api/planning/schemes");
    state.schemes = Array.isArray(listRes.schemes) ? listRes.schemes : [];
    const targetScheme =
      [ctx.scheme, saved.currentScheme, state.schemes[0]?.name].find((n) => n && state.schemes.some((s) => s.name === n)) || "";
    const targetFile = ctx.filename || saved.selectedResultFile || "";

    const schemeSelect = document.getElementById("reportSchemeSelect");
    if (schemeSelect) {
      schemeSelect.innerHTML = state.schemes
        .map((s) => `<option value="${escapeHtml(s.name)}"${s.name === targetScheme ? " selected" : ""}>${escapeHtml(s.name)}</option>`)
        .join("");
      schemeSelect.addEventListener("change", () => {
        loadReport(schemeSelect.value, "").catch((e) => window.PowerPlanUI?.toast?.(e.message, { level: "error" }));
      });
    }
    document.getElementById("reportFileSelect")?.addEventListener("change", (e) => {
      loadReport(state.currentScheme, e.target.value).catch((err) => window.PowerPlanUI?.toast?.(err.message, { level: "error" }));
    });
    document.getElementById("reportPrintBtn")?.addEventListener("click", () => window.print());
    window.addEventListener("powerplan:themechange", () => state.data && renderMonthlyChart(state.data.monthly_curve));
    window.addEventListener("resize", () => state.data && renderMonthlyChart(state.data.monthly_curve));

    if (targetScheme) {
      await loadReport(targetScheme, targetFile);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((err) => window.PowerPlanUI?.toast?.(err.message || "加载简报失败", { level: "error" }));
  });
})();
