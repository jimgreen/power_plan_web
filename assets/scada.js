/**
 * 考察站风-光-氢-储-柴联合规划总览大屏引擎（参考 SCADA 精密工业视觉风格，聚焦联合规划主题）
 * 核心视图：
 * 1) 默认视图「规划配置与年流」：规划装机拓扑 + 全年能量流 (MWh/a) + 12 月源荷季节平衡 + 年化经济性构成 + 多方案速览
 * 2) 校核视图「典型日校核」：8760 极端典型日 24h 逐时功率潮流运行校核仿真
 */
(() => {
  "use strict";

  const PAGE_STATE_KEY = "planning_dashboard";

  const state = {
    schemes: [],
    currentScheme: "",
    selectedFile: "",
    report: null,
    insights: null,
    compareRows: [],
    mode: "annual", // "annual" | "typical"
    dayIndex: 0,
    hour: 12,
    playing: false,
    playTimer: 0,
    selectedNode: "pv",
  };

  function escapeHtml(val) {
    return String(val ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function tr(text) {
    if (window.PowerPlanI18n && typeof window.PowerPlanI18n.translate === "function") {
      return window.PowerPlanI18n.translate(text, window.PowerPlanI18n.currentLanguage());
    }
    return String(text ?? "");
  }

  function getPalette() {
    const dark = window.PowerPlanUI?.isDarkTheme?.() ?? true;
    const p = window.PowerPlanUI?.getChartPalette?.() || {};
    return {
      dark,
      wind: p.wind || (dark ? "#38BDF8" : "#0284C7"),
      solar: p.solar || (dark ? "#FBBF24" : "#D97706"),
      bess: p.storage || (dark ? "#2DD4BF" : "#0D9488"),
      h2: p.hydrogen || (dark ? "#A78BFA" : "#7C3AED"),
      diesel: p.diesel || (dark ? "#FB7185" : "#DC2626"),
      load: p.load || (dark ? "#34D399" : "#059669"),
      curtail: p.curtail || "#94A3B8",
      busAc: dark ? "#38BDF8" : "#2563EB",
      busDc: dark ? "#A78BFA" : "#7C3AED",
      nodeFill: dark ? "#111827" : "#FFFFFF",
      nodeFillAlt: dark ? "#162032" : "#F1F5F9",
      nodeBorder: dark ? "rgba(148,163,184,0.32)" : "#CBD5E1",
      pillBg: dark ? "rgba(15,23,42,0.92)" : "rgba(255,255,255,0.95)",
      text: dark ? "#F8FAFC" : "#0F172A",
      muted: dark ? "#94A3B8" : "#64748B",
      grid: dark ? "rgba(148,163,184,0.14)" : "#E2E8F0",
      axis: dark ? "rgba(148,163,184,0.38)" : "#94A3B8",
      ok: dark ? "#34D399" : "#0D9488",
      warn: dark ? "#FBBF24" : "#D97706",
      danger: dark ? "#FB7185" : "#DC2626",
    };
  }

  function num(val, fallback = 0) {
    if (val === null || val === undefined || val === "") return fallback;
    const n = parseFloat(String(val).replace(/,/g, "").replace(/%/g, "").trim());
    return Number.isFinite(n) ? n : fallback;
  }

  function findMetric(rows, keywords) {
    for (const kw of keywords) {
      const hit = (rows || []).find((r) => String(r["指标"] || r.label || "").includes(kw));
      if (hit) {
        const raw = hit["数值"] ?? hit.value ?? "";
        const unit = String(hit["单位"] ?? hit.unit ?? "").trim();
        const val = num(raw, NaN);
        return { raw: raw === "" ? "—" : String(raw), val, unit };
      }
    }
    return { raw: "—", val: NaN, unit: "" };
  }

  function findCapacity(planningTable, keywords) {
    let total = 0;
    let count = 0;
    let unit = "kW";
    let matched = false;
    (planningTable || []).forEach((r) => {
      const dtype = String(r["设备类型"] || "");
      if (keywords.some((kw) => dtype.includes(kw))) {
        matched = true;
        total += num(r["总容量"], 0);
        count += num(r["设计台数"], 0);
        if (r["单位"]) unit = String(r["单位"]).trim();
      }
    });
    return { total: Math.round(total * 10) / 10, count: Math.round(count), unit, matched };
  }

  function toMwh(metricObj) {
    if (!Number.isFinite(metricObj.val)) return 0;
    const u = (metricObj.unit || "").toLowerCase();
    if (u.includes("mwh")) return metricObj.val;
    if (u.includes("万kwh")) return metricObj.val * 10;
    return metricObj.val / 1000;
  }

  /** 汇总当前规划方案的年度规划装机、电量与经济安全指标 */
  function buildPlanSummary() {
    const rep = state.report || {};
    const greenTable = rep.green_table || [];
    const safetyTable = rep.safety_table || [];
    const relRows = rep.reliability_rows || [];
    const planTable = rep.planning_table || [];
    const site = rep.site_summary || {};

    const caps = {
      wtg: findCapacity(planTable, ["风机", "风电"]),
      pv: findCapacity(planTable, ["光伏"]),
      bess: findCapacity(planTable, ["电池", "电储能", "储能"]),
      h2: findCapacity(planTable, ["电解", "氢", "燃料电池"]),
      diesel: findCapacity(planTable, ["柴发", "柴油"]),
      load: { total: num(site.peak_load_kw, 0), count: 1, unit: "kW" },
    };

    const totalPowerCap = caps.wtg.total + caps.pv.total + caps.diesel.total;
    const loadMwh = num(site.annual_load_mwh, toMwh(findMetric(greenTable, ["负荷总电量", "负荷用电量"])));
    const windMwh = toMwh(findMetric(greenTable, ["风机总发电量", "风电总发电量", "风电发电量"]));
    const pvMwh = toMwh(findMetric(greenTable, ["光伏总发电量", "光伏发电量"]));
    const dieselMwh = toMwh(findMetric(greenTable, ["柴发总发电量", "柴油发电量", "柴发电量"]));
    const stChgMwh = toMwh(findMetric(greenTable, ["电储能总储电量", "储能充电量"]));
    const stDisMwh = toMwh(findMetric(greenTable, ["电储能总放电量", "储能放电量", "储能发电量"]));
    const h2InMwh = toMwh(findMetric(greenTable, ["电制氢总用电量", "制氢用电量"]));
    const fcOutMwh = toMwh(findMetric(greenTable, ["燃料电池总发电量", "燃料电池发电量"]));

    const windMax = toMwh(findMetric(greenTable, ["风力最大可发电量", "风电最大可发"]));
    const pvMax = toMwh(findMetric(greenTable, ["光伏最大可发电量", "光伏最大可发"]));
    let curtMwh = toMwh(findMetric(greenTable, ["弃电量", "新能源弃电量", "总弃电量"]));
    if (curtMwh <= 0 && windMax + pvMax > windMwh + pvMwh) {
      curtMwh = Math.max(0, windMax + pvMax - (windMwh + pvMwh));
    }

    const lcoe = findMetric(greenTable, ["综合度电成本", "度电成本"]);
    const annualCost = findMetric(greenTable, ["年均总成本", "年总成本", "年化总成本", "总年化成本"]);
    const greenRaw = findMetric(greenTable, ["绿电占比", "绿色电量占比", "新能源供电占比", "新能源占比"]);
    const greenPct = Number.isFinite(greenRaw.val)
      ? (greenRaw.val <= 1 && !greenRaw.unit.includes("%") ? greenRaw.val * 100 : greenRaw.val)
      : loadMwh > 0
        ? Math.min(100, ((windMwh + pvMwh) / loadMwh) * 100)
        : 0;
    const curtRaw = findMetric(greenTable, ["新能源弃电率", "弃电率"]);
    const curtPct = Number.isFinite(curtRaw.val)
      ? (curtRaw.val <= 1 && !curtRaw.unit.includes("%") ? curtRaw.val * 100 : curtRaw.val)
      : windMwh + pvMwh + curtMwh > 0
        ? (curtMwh / (windMwh + pvMwh + curtMwh)) * 100
        : 0;

    const fMin = findMetric(safetyTable, ["最低频率"]).val;
    const fMax = findMetric(safetyTable, ["最高频率"]).val;
    const rel = findMetric(relRows, ["供电可靠率", "ESR"]).val;
    const conclusions = Array.isArray(rep.conclusions) ? rep.conclusions : [];
    const riskCnt = conclusions.filter((c) => c.level === "risk").length;
    const warnCnt = conclusions.filter((c) => c.level === "warn").length;

    return {
      caps,
      totalPowerCap,
      loadMwh,
      windMwh,
      pvMwh,
      dieselMwh,
      stChgMwh,
      stDisMwh,
      stEffPct: stChgMwh > 0.01 ? Math.min(100, (stDisMwh / stChgMwh) * 100) : 0,
      h2InMwh,
      fcOutMwh,
      curtMwh,
      pcsAnnualMwh: pvMwh + stDisMwh + fcOutMwh,
      lcoe: lcoe.val,
      annualCost: annualCost.val,
      annualCostUnit: annualCost.unit || "万元",
      greenPct,
      curtPct,
      absorbPct: Math.max(0, Math.min(100, 100 - curtPct)),
      fMin: Number.isFinite(fMin) ? fMin : NaN,
      fMax: Number.isFinite(fMax) ? fMax : NaN,
      relPct: Number.isFinite(rel) ? rel : NaN,
      conclusions,
      riskCnt,
      warnCnt,
      site,
      hasResult: Boolean(rep.has_result),
      stale: Boolean(rep.stale),
    };
  }

  function currentTypicalDay() {
    const days = state.insights?.typical_days || [];
    if (!days.length) return null;
    return days[Math.min(Math.max(0, state.dayIndex), days.length - 1)] || days[0];
  }

  function currentTypicalSnapshot(plan) {
    const day = currentTypicalDay();
    const h = Math.min(23, Math.max(0, state.hour));
    const s = day?.series || {};
    const wind = Math.max(0, num(s.wind?.[h], 0));
    const pv = Math.max(0, num(s.pv?.[h], 0));
    const diesel = Math.max(0, num(s.diesel?.[h], 0));
    const stDis = Math.max(0, num(s.storage_discharge?.[h], 0));
    const stChg = Math.max(0, num(s.storage_charge?.[h], 0));
    const fc = Math.max(0, num(s.fuel_cell?.[h], 0));
    const h2Prod = Math.max(0, num(s.hydrogen_prod?.[h], 0));
    const curtailed = Math.max(0, num(s.curtailed?.[h], 0));
    const load = Math.max(0, num(s.load?.[h], 0));

    let soc = 55;
    const socMat = state.insights?.heatmaps?.soc?.matrix;
    if (Array.isArray(socMat) && socMat.length) {
      const dIdx = Math.min(socMat.length - 1, Math.max(0, (day?.day_index || 1) - 1));
      const v = num(socMat[dIdx]?.[h], NaN);
      if (Number.isFinite(v)) soc = Math.max(0, Math.min(100, v));
    }
    return {
      hour: h,
      timeLabel: `${String(h).padStart(2, "0")}:00`,
      date: day?.date || "—",
      dayTitle: day?.title || "—",
      wind,
      pv,
      diesel,
      stDis,
      stChg,
      bessNet: stDis - stChg,
      fc,
      h2Prod,
      h2Net: fc - h2Prod,
      curtailed,
      load,
      soc,
      pcsNet: pv + stDis + fc - stChg - h2Prod,
      caps: plan.caps,
      daySummary: day?.summary || {},
    };
  }

  function flowSpeed(val, ref = 150) {
    const abs = Math.abs(val);
    if (abs < 0.05) return "0s";
    const ratio = Math.min(1, abs / Math.max(10, ref));
    return `${(2.3 - ratio * 1.45).toFixed(2)}s`;
  }

  /** 渲染顶部规划决策 KPI 带 */
  function renderKpiStrip(plan) {
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    set("kpiTotalCapVal", plan.totalPowerCap > 0 ? plan.totalPowerCap.toFixed(0) : "—");
    set("kpiLcoeVal", Number.isFinite(plan.lcoe) ? plan.lcoe.toFixed(3) : "—");
    set("kpiAnnualCostVal", Number.isFinite(plan.annualCost) ? plan.annualCost.toFixed(1) : "—");
    set("kpiAnnualCostUnit", tr(plan.annualCostUnit));
    set("kpiGreenPct", plan.hasResult ? plan.greenPct.toFixed(1) : "—");
    set("kpiCurtailVal", plan.hasResult ? plan.curtPct.toFixed(1) : "—");
    set("kpiFreqVal", Number.isFinite(plan.fMin) && Number.isFinite(plan.fMax) ? `${plan.fMin.toFixed(2)}–${plan.fMax.toFixed(2)}` : "—");
    set("kpiRelVal", Number.isFinite(plan.relPct) ? plan.relPct.toFixed(3) : "—");

    const checkEl = document.getElementById("kpiCheckSummary");
    const statusPill = document.getElementById("scadaPlanStatusText");
    if (!plan.hasResult) {
      set("kpiCheckStatus", tr("待求解"));
      if (statusPill) statusPill.textContent = tr("尚未求解");
    } else if (plan.riskCnt > 0) {
      set("kpiCheckStatus", `${plan.riskCnt} ${tr("项越限")}`);
      if (statusPill) statusPill.textContent = tr("存在越限");
    } else if (plan.warnCnt > 0) {
      set("kpiCheckStatus", `${plan.warnCnt} ${tr("项待优化")}`);
      if (statusPill) statusPill.textContent = plan.stale ? tr("参数待重算") : tr("规划已求解");
    } else {
      set("kpiCheckStatus", tr("全部达标"));
      if (statusPill) statusPill.textContent = tr("全部达标");
    }
    if (checkEl) {
      checkEl.classList.toggle("has-risk", plan.riskCnt > 0);
      checkEl.classList.toggle("has-warn", plan.riskCnt === 0 && plan.warnCnt > 0);
    }

    const staleTag = document.getElementById("scadaStaleTag");
    if (staleTag) staleTag.hidden = !plan.stale;
    set("scadaSiteLoadMeta", plan.loadMwh > 0 ? `${tr("年负荷")} ${plan.loadMwh.toFixed(1)} MWh` : "—");
  }

  /** 渲染工业半圆弧形规划目标表盘 */
  function renderArcGauge(svg, { value, min, max, title, unit, color, subText, zones }) {
    if (!svg) return;
    const pal = getPalette();
    svg.setAttribute("viewBox", "0 0 140 98");
    const cx = 70;
    const cy = 62;
    const r = 44;
    const angle = (v) => Math.PI + Math.max(0, Math.min(1, (v - min) / Math.max(1e-6, max - min))) * Math.PI;
    const arcPath = (v0, v1) => {
      const a0 = angle(v0);
      const a1 = angle(v1);
      const x0 = cx + r * Math.cos(a0);
      const y0 = cy + r * Math.sin(a0);
      const x1 = cx + r * Math.cos(a1);
      const y1 = cy + r * Math.sin(a1);
      const large = Math.abs(a1 - a0) > Math.PI ? 1 : 0;
      return `M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${large} 1 ${x1.toFixed(1)},${y1.toFixed(1)}`;
    };

    const aVal = angle(value);
    const nx = cx + (r - 10) * Math.cos(aVal);
    const ny = cy + (r - 10) * Math.sin(aVal);
    const zonePaths = (zones || [])
      .map((z) => `<path d="${arcPath(z.from, z.to)}" fill="none" stroke="${z.color}" stroke-width="7" opacity="0.26"/>`)
      .join("");

    svg.innerHTML = `
      <path d="${arcPath(min, max)}" fill="none" stroke="${pal.grid}" stroke-width="7" stroke-linecap="round"/>
      ${zonePaths}
      <path d="${arcPath(min, value)}" fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round"/>
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${pal.text}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="3.2" fill="${color}"/>
      <text x="${cx}" y="${cy - 14}" text-anchor="middle" fill="${pal.text}" font-size="13.5" font-weight="700" font-family="var(--font-mono)">${value.toFixed(1)}</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle" fill="${pal.muted}" font-size="10">${escapeHtml(title)} (${escapeHtml(unit)})</text>
      <text x="${cx}" y="94" text-anchor="middle" fill="${pal.muted}" font-size="9.5" font-family="var(--font-mono)">${escapeHtml(subText)}</text>
    `;
  }

  function renderGauges(plan) {
    const pal = getPalette();
    renderArcGauge(document.getElementById("scadaGreenGauge"), {
      value: plan.greenPct,
      min: 0,
      max: 100,
      title: tr("年度绿电占比"),
      unit: "%",
      color: plan.greenPct >= 75 ? pal.ok : plan.greenPct >= 50 ? pal.warn : pal.diesel,
      subText: `${tr("风光")} ${(plan.windMwh + plan.pvMwh).toFixed(0)} MWh`,
      zones: [
        { from: 0, to: 50, color: pal.diesel },
        { from: 50, to: 75, color: pal.warn },
        { from: 75, to: 100, color: pal.ok },
      ],
    });

    const freqRangeText = Number.isFinite(plan.fMin) && Number.isFinite(plan.fMax)
      ? `${plan.fMin.toFixed(2)}–${plan.fMax.toFixed(2)} Hz`
      : `${tr("弃电")} ${plan.curtPct.toFixed(1)}%`;
    renderArcGauge(document.getElementById("scadaSafetyGauge"), {
      value: plan.absorbPct,
      min: 0,
      max: 100,
      title: tr("新能源消纳率"),
      unit: "%",
      color: plan.absorbPct >= 80 ? pal.ok : plan.absorbPct >= 65 ? pal.warn : pal.diesel,
      subText: freqRangeText,
      zones: [
        { from: 0, to: 65, color: pal.diesel },
        { from: 65, to: 85, color: pal.warn },
        { from: 85, to: 100, color: pal.ok },
      ],
    });
  }

  /** 渲染左侧「规划装机与年发电配置」紧凑 3 列表 */
  function renderPlanConfigTable(plan) {
    const host = document.getElementById("scadaTelemetryTable");
    if (!host) return;
    const pal = getPalette();
    const maxEnergy = Math.max(1, plan.loadMwh, plan.windMwh, plan.pvMwh, plan.dieselMwh);
    const rows = [
      { id: "wtg", name: tr("风电 WTG"), color: pal.wind, capText: plan.caps.wtg.total > 0 ? `${plan.caps.wtg.total}` : "0", mwh: plan.windMwh },
      { id: "pv", name: tr("光伏 PV"), color: pal.solar, capText: plan.caps.pv.total > 0 ? `${plan.caps.pv.total}` : "0", mwh: plan.pvMwh },
      { id: "bess", name: tr("储能 BESS"), color: pal.bess, capText: plan.caps.bess.total > 0 ? `${plan.caps.bess.total}` : "0", mwh: plan.stDisMwh },
      { id: "h2", name: tr("氢能 H₂"), color: pal.h2, capText: plan.caps.h2.total > 0 ? `${plan.caps.h2.total}` : "0", mwh: plan.fcOutMwh + plan.h2InMwh },
      { id: "diesel", name: tr("柴发 DG"), color: pal.diesel, capText: plan.caps.diesel.total > 0 ? `${plan.caps.diesel.total}` : "0", mwh: plan.dieselMwh },
      { id: "load", name: tr("站区负荷"), color: pal.load, capText: plan.caps.load.total > 0 ? `${plan.caps.load.total.toFixed(0)}` : "—", mwh: plan.loadMwh },
    ];

    host.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>${escapeHtml(tr("规划子系统"))}</th>
            <th class="num">${escapeHtml(tr("规划装机"))}</th>
            <th class="num">${escapeHtml(tr("年电量(MWh)"))}</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map((r) => {
              const pct = Math.min(100, (r.mwh / maxEnergy) * 100);
              return `<tr class="scada-telemetry-row${state.selectedNode === r.id ? " is-selected" : ""}" data-scada-select="${r.id}">
                <td>
                  <div><i class="scada-dev-dot" style="background:${r.color}"></i>${escapeHtml(r.name)}</div>
                  <div class="scada-load-bar"><i style="width:${pct.toFixed(0)}%;background:${r.color}"></i></div>
                </td>
                <td class="num">${escapeHtml(r.capText)}</td>
                <td class="num">${r.mwh.toFixed(1)}</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    `;

    host.querySelectorAll("[data-scada-select]").forEach((trEl) => {
      trEl.addEventListener("click", () => {
        state.selectedNode = trEl.dataset.scadaSelect;
        renderMainView();
      });
    });
  }

  /** 渲染左下「年化经济性构成」横条 */
  function renderCostBreakdown(plan) {
    const host = document.getElementById("scadaCostBreakdown");
    if (!host) return;
    const pal = getPalette();
    const wf = state.report?.lcoe_waterfall || {};
    const items = (wf.items || []).filter((it) => it.kind !== "total");
    const total = (wf.items || []).find((it) => it.kind === "total")?.value || items.reduce((a, b) => a + (b.value || 0), 0);
    if (!items.length || total <= 0) {
      host.innerHTML = `<div class="empty-summary">${escapeHtml(tr("暂无成本构成明细"))}</div>`;
      return;
    }
    const colors = { capex: pal.wind, fuel: pal.diesel, om: pal.solar, opex: pal.diesel, other: pal.h2 };
    const unit = tr(wf.unit || plan.annualCostUnit);
    host.innerHTML = items
      .map((it, idx) => {
        const pct = Math.min(100, (it.value / total) * 100);
        const c = colors[it.key] || pal.wind;
        return `<div class="scada-cost-row">
          <div class="scada-cost-row-top">
            <span>${escapeHtml(tr(it.label))}</span>
            <strong>${it.value.toFixed(1)} ${escapeHtml(unit)} (${pct.toFixed(0)}%)</strong>
          </div>
          <div class="scada-cost-track"><i style="width:${pct.toFixed(1)}%;background:${c}"></i></div>
        </div>`;
      })
      .join("");
  }

  /** 渲染中央 C 位：联合规划拓扑图（支持「规划配置与年流」和「典型日校核」双模式） */
  function renderPlanningTopology(plan) {
    const svg = document.getElementById("scadaMimicSvg");
    if (!svg) return;
    const pal = getPalette();
    const isTypical = state.mode === "typical";
    const snap = isTypical ? currentTypicalSnapshot(plan) : null;

    const branch = ({ pathD, flowVal, refVal, color, reverse = false, labelX, labelY, labelText }) => {
      const active = Math.abs(flowVal) >= 0.05;
      const stroke = active ? color : pal.nodeBorder;
      const speed = flowSpeed(flowVal, refVal);
      const pill = labelText
        ? `<g transform="translate(${labelX}, ${labelY})">
            <rect x="-46" y="-10" width="92" height="19" rx="9.5" fill="${pal.pillBg}" stroke="${active ? color : pal.nodeBorder}" stroke-width="1"/>
            <text x="0" y="3.5" text-anchor="middle" fill="${active ? pal.text : pal.muted}" font-size="10" font-weight="600" font-family="var(--font-mono)">${escapeHtml(labelText)}</text>
          </g>`
        : "";
      return `
        <path class="scada-flow-line" d="${pathD}" stroke="${stroke}" stroke-width="${active ? 3.2 : 1.8}" stroke-opacity="${active ? 0.36 : 0.45}"/>
        <path class="scada-flow-particles${reverse ? " is-reverse" : ""}${active ? "" : " is-idle"}" d="${pathD}" stroke="${color}" stroke-width="2.6" style="--flow-speed:${speed}"/>
        ${pill}
      `;
    };

    const nodeCard = ({ id, x, y, w, h, title, code, valueText, subText, accent, iconSvg, active }) => {
      const sel = state.selectedNode === id;
      return `
        <g class="scada-node${sel ? " is-selected" : ""}" data-scada-node="${id}" transform="translate(${x}, ${y})">
          <rect class="scada-node-box" width="${w}" height="${h}" rx="8" fill="${pal.nodeFill}" stroke="${sel ? accent : pal.nodeBorder}" stroke-width="${sel ? 2.2 : 1.2}"/>
          <rect x="0" y="0" width="${w}" height="4" rx="2" fill="${active ? accent : pal.nodeBorder}"/>
          <circle cx="${w - 13}" cy="17" r="3.8" fill="${active ? accent : pal.muted}"/>
          <g transform="translate(10, 12)">${iconSvg}</g>
          <text x="42" y="21" fill="${pal.text}" font-size="12.5" font-weight="700">${escapeHtml(title)}</text>
          <text x="42" y="34" fill="${pal.muted}" font-size="9.5" font-family="var(--font-mono)">${escapeHtml(code)}</text>
          <text x="12" y="${h - 24}" fill="${active ? accent : pal.muted}" font-size="15.5" font-weight="700" font-family="var(--font-mono)">${escapeHtml(valueText)}</text>
          <text x="12" y="${h - 9}" fill="${pal.muted}" font-size="10" font-family="var(--font-mono)">${escapeHtml(subText)}</text>
        </g>
      `;
    };

    const windActive = isTypical ? snap.wind > 0.05 : plan.caps.wtg.total > 0 || plan.windMwh > 0.05;
    const windIcon = `<g stroke="${pal.wind}" fill="none" stroke-width="1.8">
      <line x1="13" y1="14" x2="13" y2="26"/>
      <g class="scada-rotor${windActive ? "" : " is-idle"}">
        <circle cx="13" cy="12" r="2" fill="${pal.wind}"/>
        <line x1="13" y1="10" x2="13" y2="2"/><line x1="14.7" y1="13" x2="21.5" y2="17"/><line x1="11.3" y1="13" x2="4.5" y2="17"/>
      </g></g>`;
    const dieselIcon = `<g stroke="${pal.diesel}" fill="none" stroke-width="1.8">
      <rect x="3" y="6" width="20" height="14" rx="3"/><path d="M8 13h3l1.5-3 2 6 1.5-3h2"/>
    </g>`;
    const loadIcon = `<g stroke="${pal.load}" fill="none" stroke-width="1.8">
      <polygon points="13 3 3 11 6 11 6 22 20 22 20 11 23 11 13 3"/><line x1="11" y1="15" x2="15" y2="15"/>
    </g>`;
    const pvIcon = `<g stroke="${pal.solar}" fill="none" stroke-width="1.7">
      <rect x="3" y="6" width="20" height="14" rx="2"/><line x1="3" y1="13" x2="23" y2="13"/><line x1="10" y1="6" x2="10" y2="20"/><line x1="16" y1="6" x2="16" y2="20"/>
    </g>`;
    const bessFillRatio = isTypical ? snap.soc / 100 : plan.caps.bess.total > 0 ? 0.72 : 0.12;
    const socH = Math.max(2, Math.round(bessFillRatio * 14));
    const bessIcon = `<g stroke="${pal.bess}" fill="none" stroke-width="1.7">
      <rect x="5" y="5" width="16" height="18" rx="2"/><rect x="10" y="2" width="6" height="3" fill="${pal.bess}"/>
      <rect x="7.5" y="${21 - socH}" width="11" height="${socH}" rx="1" fill="${pal.bess}" stroke="none" opacity="0.8"/>
    </g>`;
    const h2Icon = `<g stroke="${pal.h2}" fill="none" stroke-width="1.7">
      <rect x="6" y="4" width="14" height="18" rx="6"/>
      <text x="13" y="16" text-anchor="middle" fill="${pal.h2}" stroke="none" font-size="9" font-weight="700" font-family="var(--font-mono)">H2</text>
    </g>`;

    const refFlow = isTypical ? Math.max(snap.load, 80) : Math.max(plan.loadMwh, 100);
    const fWind = isTypical ? snap.wind : plan.windMwh;
    const fDiesel = isTypical ? snap.diesel : plan.dieselMwh;
    const fLoad = isTypical ? snap.load : plan.loadMwh;
    const fCurt = isTypical ? snap.curtailed : plan.curtMwh;
    const fPv = isTypical ? snap.pv : plan.pvMwh;
    const fBess = isTypical ? snap.bessNet : plan.stDisMwh;
    const fH2 = isTypical ? snap.h2Net : plan.fcOutMwh - plan.h2InMwh;
    const fPcs = isTypical ? snap.pcsNet : plan.pcsAnnualMwh;
    const unitFlow = isTypical ? "kW" : "MWh";

    const busAcLabel = isTypical
      ? `AC 交流母线 · ${snap.date} ${snap.timeLabel}`
      : `AC 交流汇流母线 · ${tr("年度能量平衡")} · ${Number.isFinite(plan.fMin) ? `${plan.fMin.toFixed(2)}–${plan.fMax.toFixed(2)} Hz` : "50 Hz"}`;

    svg.innerHTML = `
      <!-- 支路与能量/功率流 -->
      ${branch({ pathD: "M150,104 L150,162", flowVal: fWind, refVal: refFlow, color: pal.wind, labelX: 150, labelY: 132, labelText: `${fWind.toFixed(1)} ${unitFlow}` })}
      ${branch({ pathD: "M460,104 L460,162", flowVal: fDiesel, refVal: refFlow, color: pal.diesel, labelX: 460, labelY: 132, labelText: `${fDiesel.toFixed(1)} ${unitFlow}` })}
      ${branch({ pathD: "M770,162 L770,104", flowVal: fLoad, refVal: refFlow, color: pal.load, labelX: 770, labelY: 132, labelText: `${fLoad.toFixed(1)} ${unitFlow}` })}
      ${branch({ pathD: "M840,162 L878,162 L878,242", flowVal: fCurt, refVal: refFlow, color: pal.warn, labelX: 854, labelY: 204, labelText: `${tr("弃电")} ${fCurt.toFixed(1)}` })}
      ${branch({ pathD: "M460,278 L460,162", flowVal: fPcs, refVal: refFlow, color: fPcs >= 0 ? pal.bess : pal.busAc, reverse: fPcs < 0, labelX: 556, labelY: 220, labelText: `PCS ${fPcs >= 0 ? "↑" : "↓"} ${Math.abs(fPcs).toFixed(1)} ${unitFlow}` })}
      ${branch({ pathD: "M190,322 L190,278", flowVal: fPv, refVal: refFlow, color: pal.solar, labelX: 190, labelY: 300, labelText: `${fPv.toFixed(1)} ${unitFlow}` })}
      ${branch({ pathD: "M460,322 L460,278", flowVal: fBess, refVal: refFlow, color: fBess >= 0 ? pal.bess : pal.busAc, reverse: fBess < 0, labelX: 460, labelY: 300, labelText: isTypical ? `${fBess >= 0 ? "+" : ""}${fBess.toFixed(1)} kW` : `${plan.stDisMwh.toFixed(1)} MWh` })}
      ${branch({ pathD: "M730,322 L730,278", flowVal: fH2, refVal: refFlow, color: pal.h2, reverse: fH2 < 0, labelX: 730, labelY: 300, labelText: isTypical ? `${fH2 >= 0 ? "+" : ""}${fH2.toFixed(1)} kW` : `${(plan.fcOutMwh + plan.h2InMwh).toFixed(1)} MWh` })}

      <!-- AC / DC 主母线 -->
      <rect x="64" y="158" width="780" height="8" rx="4" fill="${pal.busAc}" opacity="0.86"/>
      <text x="72" y="152" fill="${pal.busAc}" font-size="10.5" font-weight="700" font-family="var(--font-mono)">${escapeHtml(busAcLabel)}</text>
      <rect x="128" y="274" width="664" height="7" rx="3.5" fill="${pal.busDc}" opacity="0.84"/>
      <text x="134" y="268" fill="${pal.busDc}" font-size="10.5" font-weight="700" font-family="var(--font-mono)">DC ${escapeHtml(tr("直流汇流母线"))} · 750V DC</text>

      <!-- PCS 双向变流器 -->
      <g transform="translate(422, 198)">
        <rect width="76" height="44" rx="6" fill="${pal.nodeFillAlt}" stroke="${pal.busAc}" stroke-width="1.6"/>
        <line x1="6" y1="38" x2="70" y2="6" stroke="${pal.nodeBorder}" stroke-width="1"/>
        <text x="14" y="18" fill="${pal.busAc}" font-size="10" font-weight="700" font-family="var(--font-mono)">AC</text>
        <text x="48" y="34" fill="${pal.busDc}" font-size="10" font-weight="700" font-family="var(--font-mono)">DC</text>
        <text x="38" y="56" text-anchor="middle" fill="${pal.muted}" font-size="9.5" font-family="var(--font-mono)">PCS</text>
      </g>

      <!-- 弃电/消纳余量终端 -->
      <g transform="translate(838, 242)">
        <rect width="76" height="34" rx="5" fill="${pal.nodeFillAlt}" stroke="${fCurt > 0.05 ? pal.warn : pal.nodeBorder}"/>
        <text x="38" y="14" text-anchor="middle" fill="${pal.muted}" font-size="9.5">${escapeHtml(isTypical ? tr("时段弃电") : tr("年度弃电"))}</text>
        <text x="38" y="27" text-anchor="middle" fill="${fCurt > 0.05 ? pal.warn : pal.muted}" font-size="10.5" font-weight="700" font-family="var(--font-mono)">${fCurt.toFixed(1)} ${unitFlow}</text>
      </g>

      <!-- 六大规划子系统卡片 -->
      ${nodeCard({
        id: "wtg",
        x: 56,
        y: 18,
        w: 188,
        h: 86,
        title: tr("风电规划配置"),
        code: plan.caps.wtg.count > 0 ? `${plan.caps.wtg.count} ${tr("台")} · AC ${tr("接入")}` : "WTG · AC",
        valueText: isTypical ? `${snap.wind.toFixed(1)} kW` : `${plan.caps.wtg.total} ${plan.caps.wtg.unit}`,
        subText: isTypical ? `${tr("规划装机")} ${plan.caps.wtg.total} kW` : `${tr("年发电")} ${plan.windMwh.toFixed(1)} MWh`,
        accent: pal.wind,
        iconSvg: windIcon,
        active: windActive,
      })}

      ${nodeCard({
        id: "diesel",
        x: 366,
        y: 18,
        w: 188,
        h: 86,
        title: tr("柴发备用配置"),
        code: plan.caps.diesel.count > 0 ? `${plan.caps.diesel.count} ${tr("台")} · ${tr("保底电源")}` : "DG · AC",
        valueText: isTypical ? `${snap.diesel.toFixed(1)} kW` : `${plan.caps.diesel.total} ${plan.caps.diesel.unit}`,
        subText: isTypical ? `${tr("规划装机")} ${plan.caps.diesel.total} kW` : `${tr("年发电")} ${plan.dieselMwh.toFixed(1)} MWh`,
        accent: pal.diesel,
        iconSvg: dieselIcon,
        active: isTypical ? snap.diesel > 0.05 : plan.caps.diesel.total > 0,
      })}

      ${nodeCard({
        id: "load",
        x: 676,
        y: 18,
        w: 188,
        h: 86,
        title: tr("考察站规划负荷"),
        code: `${tr("峰值")} ${plan.caps.load.total.toFixed(0)} kW · 8760h`,
        valueText: isTypical ? `${snap.load.toFixed(1)} kW` : `${plan.loadMwh.toFixed(1)} MWh`,
        subText: isTypical ? `${tr("典型日")} ${num(snap.daySummary.load_kwh, 0).toFixed(0)} kWh` : `${tr("均荷")} ${num(plan.site.avg_load_kw, 0).toFixed(1)} kW`,
        accent: pal.load,
        iconSvg: loadIcon,
        active: true,
      })}

      ${nodeCard({
        id: "pv",
        x: 96,
        y: 322,
        w: 188,
        h: 86,
        title: tr("光伏规划配置"),
        code: plan.caps.pv.count > 0 ? `${plan.caps.pv.count} ${tr("组")} · DC ${tr("接入")}` : "PV · DC",
        valueText: isTypical ? `${snap.pv.toFixed(1)} kW` : `${plan.caps.pv.total} ${plan.caps.pv.unit}`,
        subText: isTypical ? `${tr("规划装机")} ${plan.caps.pv.total} kW` : `${tr("年发电")} ${plan.pvMwh.toFixed(1)} MWh`,
        accent: pal.solar,
        iconSvg: pvIcon,
        active: isTypical ? snap.pv > 0.05 : plan.caps.pv.total > 0,
      })}

      ${nodeCard({
        id: "bess",
        x: 366,
        y: 322,
        w: 188,
        h: 86,
        title: tr("电化学储能配置"),
        code: isTypical ? `BESS · SOC ${snap.soc.toFixed(1)}%` : `BESS · ${tr("效率")} ${plan.stEffPct > 0 ? `${plan.stEffPct.toFixed(0)}%` : "—"}`,
        valueText: isTypical
          ? (snap.bessNet >= 0 ? `${tr("放")} +${snap.bessNet.toFixed(1)} kW` : `${tr("充")} ${snap.bessNet.toFixed(1)} kW`)
          : `${plan.caps.bess.total} ${plan.caps.bess.unit}`,
        subText: isTypical ? `${tr("规划容量")} ${plan.caps.bess.total} ${plan.caps.bess.unit}` : `${tr("年充/放")} ${plan.stChgMwh.toFixed(1)}/${plan.stDisMwh.toFixed(1)} MWh`,
        accent: pal.bess,
        iconSvg: bessIcon,
        active: isTypical ? Math.abs(snap.bessNet) > 0.05 : plan.caps.bess.total > 0,
      })}

      ${nodeCard({
        id: "h2",
        x: 636,
        y: 322,
        w: 188,
        h: 86,
        title: tr("绿氢储能配置"),
        code: "ELZ / H2 / FC · DC",
        valueText: isTypical
          ? (snap.fc > 0.05 ? `FC +${snap.fc.toFixed(1)} kW` : snap.h2Prod > 0.05 ? `ELZ -${snap.h2Prod.toFixed(1)} kW` : "0.0 kW")
          : `${plan.caps.h2.total} ${plan.caps.h2.unit}`,
        subText: isTypical ? `${tr("规划配置")} ${plan.caps.h2.total} ${plan.caps.h2.unit}` : `${tr("制氢/发电")} ${plan.h2InMwh.toFixed(1)}/${plan.fcOutMwh.toFixed(1)} MWh`,
        accent: pal.h2,
        iconSvg: h2Icon,
        active: isTypical ? Math.abs(snap.h2Net) > 0.05 : plan.caps.h2.total > 0,
      })}
    `;

    if (!svg._scadaDelegated) {
      svg._scadaDelegated = true;
      svg.addEventListener("pointerdown", (e) => {
        const nodeEl = e.target?.closest?.("[data-scada-node]");
        if (!nodeEl) return;
        state.selectedNode = nodeEl.dataset.scadaNode;
        renderMainView();
      });
    }
  }

  /** 渲染中央底部趋势图：年流模式展示 12 月源荷季节平衡，典型日模式展示 24h 逐时功率平衡 */
  function renderBottomChart(plan) {
    const svg = document.getElementById("scadaTimelineSvg");
    const tip = document.getElementById("scadaTimelineTip");
    const titleEl = document.getElementById("scadaBottomChartTitle");
    const summaryEl = document.getElementById("scadaDaySummary");
    if (!svg) return;
    const pal = getPalette();
    const width = Math.max(460, Math.round(svg.parentElement?.clientWidth || 720));
    const height = Math.max(115, Math.round(svg.parentElement?.clientHeight || 126));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    if (state.mode === "typical") {
      const day = currentTypicalDay();
      if (titleEl) titleEl.textContent = tr("24h 极端典型日运行校核功率平衡 (kW)");
      if (!day) {
        svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.muted}" font-size="12">${escapeHtml(tr("暂无典型日校验数据"))}</text>`;
        return;
      }
      if (summaryEl) summaryEl.textContent = `${tr(day.title)} (${day.date}) · ${tr("日负荷")} ${num(day.summary?.load_kwh, 0).toFixed(0)} kWh`;
      const s = day.series || {};
      const keys = [
        { k: "wind", color: pal.wind },
        { k: "pv", color: pal.solar },
        { k: "storage_discharge", color: pal.bess },
        { k: "fuel_cell", color: pal.h2 },
        { k: "diesel", color: pal.diesel },
      ];
      let maxY = 1;
      for (let h = 0; h < 24; h += 1) {
        const sum = keys.reduce((a, it) => a + Math.max(0, num(s[it.k]?.[h], 0)), 0);
        maxY = Math.max(maxY, sum, num(s.load?.[h], 0));
      }
      const padL = 42, padR = 10, padT = 8, padB = 20;
      const plotW = width - padL - padR, plotH = height - padT - padB;
      const slotW = plotW / 24, barW = Math.max(5, Math.min(20, slotW * 0.64));
      const sy = (v) => padT + plotH - (v / (maxY * 1.08)) * plotH;

      const grids = [0, 0.5, 1]
        .map((r) => {
          const yv = maxY * 1.08 * r, yy = sy(yv);
          return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${pal.grid}" stroke-dasharray="3 3"/>
                  <text x="${padL - 5}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end" fill="${pal.muted}" font-size="9.5" font-family="var(--font-mono)">${Math.round(yv)}</text>`;
        }).join("");
      const activeX = padL + slotW * state.hour;
      const cursor = `<rect x="${activeX.toFixed(1)}" y="${padT}" width="${slotW.toFixed(1)}" height="${plotH}" fill="${pal.busAc}" opacity="0.16"/>
                      <line x1="${(activeX + slotW / 2).toFixed(1)}" x2="${(activeX + slotW / 2).toFixed(1)}" y1="${padT}" y2="${padT + plotH}" stroke="${pal.busAc}" stroke-width="1.5" stroke-dasharray="3 2"/>`;
      const bars = Array.from({ length: 24 }, (_, h) => {
        const cx = padL + slotW * h + slotW / 2, x0 = cx - barW / 2;
        let acc = 0;
        const segs = keys.map((it) => {
          const v = Math.max(0, num(s[it.k]?.[h], 0));
          if (v <= 0.05) return "";
          const yt = sy(acc + v), yb = sy(acc);
          acc += v;
          return `<rect x="${x0.toFixed(1)}" y="${yt.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.5, yb - yt).toFixed(1)}" fill="${it.color}" opacity="${h === state.hour ? "1" : "0.78"}"/>`;
        }).join("");
        const lbl = h % 3 === 0 ? `<text x="${cx.toFixed(1)}" y="${height - 5}" text-anchor="middle" fill="${h === state.hour ? pal.busAc : pal.muted}" font-size="9.5" font-family="var(--font-mono)">${String(h).padStart(2, "0")}</text>` : "";
        return `${segs}${lbl}<rect data-tl-hour="${h}" x="${(padL + slotW * h).toFixed(1)}" y="${padT}" width="${slotW.toFixed(1)}" height="${plotH}" fill="transparent" style="cursor:pointer"/>`;
      }).join("");
      const loadPath = Array.from({ length: 24 }, (_, h) => `${h === 0 ? "M" : "L"}${(padL + slotW * h + slotW / 2).toFixed(1)},${sy(num(s.load?.[h], 0)).toFixed(1)}`).join(" ");
      svg.innerHTML = `${grids}${cursor}${bars}<path d="${loadPath}" fill="none" stroke="${pal.load}" stroke-width="2"/>`;

      svg.querySelectorAll("[data-tl-hour]").forEach((el) => {
        el.addEventListener("click", () => {
          state.hour = Number(el.dataset.tlHour) || 0;
          const slider = document.getElementById("scadaHourSlider");
          if (slider) slider.value = String(state.hour);
          renderMainView();
        });
      });
      return;
    }

    // 默认模式：全年 12 月源荷季节平衡与供能结构 (MWh)
    if (titleEl) titleEl.textContent = tr("全年 12 月源荷季节平衡与供能结构 (MWh)");
    const rows = state.report?.monthly_curve || [];
    if (summaryEl) summaryEl.textContent = `${tr("风电")} ${plan.windMwh.toFixed(0)} · ${tr("光伏")} ${plan.pvMwh.toFixed(0)} · ${tr("柴发")} ${plan.dieselMwh.toFixed(0)} MWh`;
    if (!rows.length) {
      svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.muted}" font-size="12">${escapeHtml(tr("暂无月度供能规划数据"))}</text>`;
      return;
    }
    const parsed = rows.map((r, i) => ({
      label: `${i + 1}${tr("月")}`,
      w: num(r.wind_energy ?? r["风电电量"], 0) / 1000,
      p: num(r.pv_energy ?? r["光伏电量"], 0) / 1000,
      d: num(r.diesel_energy ?? r["柴发电量"], 0) / 1000,
      l: num(r.load_energy ?? r["负荷电量"], 0) / 1000,
    }));
    const maxV = Math.max(1, ...parsed.map((x) => Math.max(x.w + x.p + x.d, x.l)));
    const padL = 42, padR = 12, padT = 8, padB = 20;
    const plotW = width - padL - padR, plotH = height - padT - padB;
    const slotW = plotW / parsed.length;
    const barW = Math.max(10, Math.min(34, slotW * 0.56));
    const sy = (v) => padT + plotH - (v / (maxV * 1.1)) * plotH;

    const grids = [0, 0.5, 1]
      .map((r) => {
        const yv = maxV * 1.1 * r, yy = sy(yv);
        return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${pal.grid}" stroke-dasharray="3 3"/>
                <text x="${padL - 5}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end" fill="${pal.muted}" font-size="9.5" font-family="var(--font-mono)">${yv.toFixed(0)}</text>`;
      }).join("");

    const bars = parsed
      .map((x, idx) => {
        const cx = padL + slotW * idx + slotW / 2, x0 = cx - barW / 2;
        let acc = 0;
        const seg = (v, c) => {
          if (v <= 0.01) return "";
          const yt = sy(acc + v), yb = sy(acc);
          acc += v;
          return `<rect x="${x0.toFixed(1)}" y="${yt.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.6, yb - yt).toFixed(1)}" fill="${c}" opacity="0.9"/>`;
        };
        return `${seg(x.w, pal.wind)}${seg(x.p, pal.solar)}${seg(x.d, pal.diesel)}
          <text x="${cx.toFixed(1)}" y="${height - 5}" text-anchor="middle" fill="${pal.muted}" font-size="9.5" font-family="var(--font-mono)">${escapeHtml(x.label)}</text>
          <rect data-m-idx="${idx}" x="${(padL + slotW * idx).toFixed(1)}" y="${padT}" width="${slotW.toFixed(1)}" height="${plotH}" fill="transparent"/>`;
      }).join("");

    const loadPath = parsed.map((x, idx) => `${idx === 0 ? "M" : "L"}${(padL + slotW * idx + slotW / 2).toFixed(1)},${sy(x.l).toFixed(1)}`).join(" ");
    svg.innerHTML = `${grids}${bars}<path d="${loadPath}" fill="none" stroke="${pal.load}" stroke-width="2.2"/>`;

    svg.querySelectorAll("[data-m-idx]").forEach((el) => {
      el.addEventListener("mousemove", (e) => {
        if (!tip) return;
        const m = parsed[Number(el.dataset.mIdx)];
        if (!m) return;
        const rect = svg.parentElement.getBoundingClientRect();
        tip.hidden = false;
        tip.innerHTML = `<strong>${escapeHtml(m.label)}</strong>
          <div class="insight-tip-row"><span>${tr("风电")}</span><b>${m.w.toFixed(1)} MWh</b></div>
          <div class="insight-tip-row"><span>${tr("光伏")}</span><b>${m.p.toFixed(1)} MWh</b></div>
          <div class="insight-tip-row"><span>${tr("柴发")}</span><b>${m.d.toFixed(1)} MWh</b></div>
          <div class="insight-tip-row"><span>${tr("负荷")}</span><b>${m.l.toFixed(1)} MWh</b></div>`;
        tip.style.left = `${Math.min(rect.width - 165, Math.max(8, e.clientX - rect.left + 10))}px`;
        tip.style.top = `${Math.max(4, e.clientY - rect.top - 72)}px`;
      });
      el.addEventListener("mouseleave", () => {
        if (tip) tip.hidden = true;
      });
    });
  }

  /** 渲染右侧「子系统规划配置详情」卡 */
  function renderInspector(plan) {
    const body = document.getElementById("scadaInspectorBody");
    const codeEl = document.getElementById("scadaInspectorCode");
    if (!body) return;

    const q = new URLSearchParams({
      scheme: state.currentScheme,
      ...(state.selectedFile ? { file: state.selectedFile } : {}),
    }).toString();

    const share = (mwh) => (plan.loadMwh > 0 ? `${((mwh / plan.loadMwh) * 100).toFixed(1)}%` : "—");
    const specs = {
      wtg: {
        title: tr("风电规划配置"),
        code: "PLAN / WTG",
        badge: plan.caps.wtg.total > 0 ? { text: tr("已配置"), cls: "is-run" } : { text: tr("未配置"), cls: "is-idle" },
        metrics: [
          [tr("规划装机"), `${plan.caps.wtg.total} ${plan.caps.wtg.unit}`],
          [tr("设计台数"), plan.caps.wtg.count > 0 ? `${plan.caps.wtg.count} ${tr("台")}` : "—"],
          [tr("年发电量"), `${plan.windMwh.toFixed(1)} MWh`],
          [tr("负荷贡献"), share(plan.windMwh)],
        ],
      },
      pv: {
        title: tr("光伏规划配置"),
        code: "PLAN / PV",
        badge: plan.caps.pv.total > 0 ? { text: tr("已配置"), cls: "is-run" } : { text: tr("未配置"), cls: "is-idle" },
        metrics: [
          [tr("规划装机"), `${plan.caps.pv.total} ${plan.caps.pv.unit}`],
          [tr("设计组数"), plan.caps.pv.count > 0 ? `${plan.caps.pv.count} ${tr("组")}` : "—"],
          [tr("年发电量"), `${plan.pvMwh.toFixed(1)} MWh`],
          [tr("负荷贡献"), share(plan.pvMwh)],
        ],
      },
      bess: {
        title: tr("电化学储能配置"),
        code: "PLAN / BESS",
        badge: plan.caps.bess.total > 0 ? { text: tr("日内调峰"), cls: "is-chg" } : { text: tr("未配置"), cls: "is-idle" },
        metrics: [
          [tr("规划容量"), `${plan.caps.bess.total} ${plan.caps.bess.unit}`],
          [tr("年充电量"), `${plan.stChgMwh.toFixed(1)} MWh`],
          [tr("年放电量"), `${plan.stDisMwh.toFixed(1)} MWh`],
          [tr("充放效率"), plan.stEffPct > 0 ? `${plan.stEffPct.toFixed(1)} %` : "—"],
        ],
      },
      h2: {
        title: tr("绿氢储能配置"),
        code: "PLAN / H2",
        badge: plan.caps.h2.total > 0 ? { text: tr("跨季储备"), cls: "is-chg" } : { text: tr("未配置"), cls: "is-idle" },
        metrics: [
          [tr("规划规模"), `${plan.caps.h2.total} ${plan.caps.h2.unit}`],
          [tr("年制氢耗电"), `${plan.h2InMwh.toFixed(1)} MWh`],
          [tr("燃料电池发电"), `${plan.fcOutMwh.toFixed(1)} MWh`],
          [tr("系统定位"), tr("极夜长时保供")],
        ],
      },
      diesel: {
        title: tr("柴发备用配置"),
        code: "PLAN / DG",
        badge: plan.caps.diesel.total > 0 ? { text: tr("极端兜底"), cls: "is-warn" } : { text: tr("未配置"), cls: "is-idle" },
        metrics: [
          [tr("规划装机"), `${plan.caps.diesel.total} ${plan.caps.diesel.unit}`],
          [tr("设计台数"), plan.caps.diesel.count > 0 ? `${plan.caps.diesel.count} ${tr("台")}` : "—"],
          [tr("年发电量"), `${plan.dieselMwh.toFixed(1)} MWh`],
          [tr("柴发占比"), share(plan.dieselMwh)],
        ],
      },
      load: {
        title: tr("考察站规划负荷"),
        code: "PLAN / LOAD",
        badge: { text: "8760h", cls: "is-run" },
        metrics: [
          [tr("年总用电量"), `${plan.loadMwh.toFixed(1)} MWh`],
          [tr("年峰值负荷"), `${plan.caps.load.total.toFixed(1)} kW`],
          [tr("年均负荷"), `${num(plan.site.avg_load_kw, 0).toFixed(1)} kW`],
          [tr("年度弃电量"), `${plan.curtMwh.toFixed(1)} MWh`],
        ],
      },
    };

    const spec = specs[state.selectedNode] || specs.pv;
    if (codeEl) codeEl.textContent = spec.code;
    body.innerHTML = `
      <div class="scada-insp-header">
        <span class="scada-insp-title">${escapeHtml(spec.title)}</span>
        <span class="scada-status-pill ${spec.badge.cls}">${escapeHtml(spec.badge.text)}</span>
      </div>
      <div class="scada-insp-grid">
        ${spec.metrics.map(([k, v]) => `<div class="scada-insp-metric"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("")}
      </div>
      <div class="scada-insp-actions">
        <a href="planning.html?scheme=${encodeURIComponent(state.currentScheme)}">${escapeHtml(tr("参数维护"))}</a>
        <a href="optimize.html?scheme=${encodeURIComponent(state.currentScheme)}">${escapeHtml(tr("规划求解"))}</a>
        <a href="evaluation.html?${q}">${escapeHtml(tr("方案评估"))}</a>
      </div>
    `;
  }

  /** 渲染右侧「规划校核与优化建议」列表 */
  function renderReviewConclusions(plan) {
    const host = document.getElementById("scadaReviewList");
    if (!host) return;
    if (!plan.conclusions.length) {
      host.innerHTML = `<div class="empty-summary">${escapeHtml(tr("当前方案尚未生成规划校核结论"))}</div>`;
      return;
    }
    const lvlMap = { pass: tr("达标"), warn: tr("优化"), risk: tr("越限") };
    host.innerHTML = plan.conclusions
      .map(
        (c) => `<div class="scada-alarm-item is-${escapeHtml(c.level || "warn")}">
          <div class="scada-alarm-top">
            <span><span class="scada-alarm-lvl">${escapeHtml(lvlMap[c.level] || tr("提示"))}</span> ${escapeHtml(tr(c.category || "综合"))}</span>
          </div>
          <div class="scada-alarm-title">${escapeHtml(c.title || "")}</div>
          <div class="scada-alarm-detail">${escapeHtml(c.detail || "")}</div>
        </div>`,
      )
      .join("");
  }

  /** 渲染右下「多方案 LCOE / 绿电速览」（点击方案名直接切换大屏） */
  function renderSchemeCompareList() {
    const host = document.getElementById("scadaSchemeCompareList");
    if (!host) return;
    const rows = (state.compareRows || []).filter((r) => r && r.has_result);
    if (!rows.length) {
      host.innerHTML = `<div class="empty-summary">${escapeHtml(tr("暂无可横向对比的已求解方案"))}</div>`;
      return;
    }
    host.innerHTML = rows
      .map(
        (r) => `<div class="scada-compare-row${r.scheme === state.currentScheme ? " is-current" : ""}" data-switch-scheme="${escapeHtml(r.scheme)}" title="${escapeHtml(r.scheme)}">
          <span class="scada-compare-name">${escapeHtml(r.scheme)}</span>
          <span class="scada-compare-lcoe">${Number.isFinite(r.lcoe) ? r.lcoe.toFixed(3) : "—"}</span>
          <span class="scada-compare-green">${Number.isFinite(r.green_ratio) ? `${r.green_ratio.toFixed(1)}%` : "—"}</span>
        </div>`,
      )
      .join("");

    host.querySelectorAll("[data-switch-scheme]").forEach((el) => {
      el.addEventListener("click", () => {
        const name = el.dataset.switchScheme;
        if (!name || name === state.currentScheme) return;
        const sel = document.getElementById("scadaSchemeSelect");
        if (sel) sel.value = name;
        loadScenarioData(name, "").catch((e) => window.PowerPlanUI?.toast?.(e.message, { level: "error" }));
      });
    });
  }

  function syncModeHeader() {
    const isTypical = state.mode === "typical";
    const heading = document.getElementById("scadaMimicHeading");
    const badge = document.getElementById("scadaBusBadge");
    const typBar = document.getElementById("scadaTypicalBar");
    const annLegend = document.getElementById("scadaAnnualLegend");
    if (heading) heading.textContent = isTypical ? tr("极端典型日 24h 功率潮流运行校核 (kW)") : tr("联合规划装机配置与年度能量流拓扑 (MWh/a)");
    if (badge) badge.textContent = isTypical ? tr("24h 运行校核") : tr("8760h MILP 联合优化");
    if (typBar) typBar.hidden = !isTypical;
    if (annLegend) annLegend.hidden = isTypical;
    document.querySelectorAll("[data-plan-mode]").forEach((btn) => {
      const active = btn.dataset.planMode === state.mode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
    const timeEl = document.getElementById("scadaTimeDisplay");
    if (timeEl) timeEl.textContent = `${String(state.hour).padStart(2, "0")}:00`;
  }

  function renderMainView() {
    const plan = buildPlanSummary();
    syncModeHeader();
    renderKpiStrip(plan);
    renderGauges(plan);
    renderPlanConfigTable(plan);
    renderCostBreakdown(plan);
    renderPlanningTopology(plan);
    renderBottomChart(plan);
    renderInspector(plan);
    renderReviewConclusions(plan);
    renderSchemeCompareList();
    if (window.PowerPlanI18n) {
      window.PowerPlanI18n.translate(document.body, window.PowerPlanI18n.currentLanguage());
    }
  }

  function updateLinks() {
    const q = new URLSearchParams({
      scheme: state.currentScheme,
      ...(state.selectedFile ? { file: state.selectedFile } : {}),
    }).toString();
    const repLink = document.getElementById("scadaLinkReport");
    const sensLink = document.getElementById("scadaLinkSens");
    if (repLink) repLink.href = `report.html?${q}`;
    if (sensLink) sensLink.href = `sensitivity.html?scheme=${encodeURIComponent(state.currentScheme)}`;
  }

  async function loadScenarioData(scheme, filename = "") {
    if (!scheme) return;
    state.currentScheme = scheme;
    state.selectedFile = filename;
    window.PowerPlanPageState?.write?.(PAGE_STATE_KEY, { currentScheme: scheme, selectedResultFile: filename });

    const qs = new URLSearchParams({ scheme, ...(filename ? { filename } : {}) }).toString();
    const [repRes, insRes] = await Promise.all([
      window.PowerPlanUI.fetchJson(`/api/report/summary?${qs}`, { slot: "plan-dash-report", ttlMs: 10000 }).catch(() => null),
      window.PowerPlanUI.fetchJson(`/api/analysis/insights?${qs}`, { slot: "plan-dash-insights", ttlMs: 20000 }).catch(() => null),
    ]);
    if (repRes) {
      state.report = repRes;
      state.selectedFile = repRes.filename || filename;
    }
    state.insights = insRes && insRes.ok ? insRes : null;

    const fileSelect = document.getElementById("scadaFileSelect");
    if (fileSelect) {
      const files = state.report?.result_files || [];
      fileSelect.innerHTML = files.length
        ? files.map((f) => `<option value="${escapeHtml(f.name)}"${f.name === state.selectedFile ? " selected" : ""}>${escapeHtml(f.name.replace(/_results\.xlsx$/i, ""))}</option>`).join("")
        : `<option value="">${escapeHtml(tr("无求解结果"))}</option>`;
    }
    const daySelect = document.getElementById("scadaDaySelect");
    if (daySelect) {
      const days = state.insights?.typical_days || [];
      state.dayIndex = Math.min(state.dayIndex, Math.max(0, days.length - 1));
      daySelect.innerHTML = days.length
        ? days.map((d, idx) => `<option value="${idx}"${idx === state.dayIndex ? " selected" : ""}>${escapeHtml(tr(d.title))} (${escapeHtml(d.date)})</option>`).join("")
        : `<option value="0">${escapeHtml(tr("无典型日"))}</option>`;
    }

    updateLinks();
    renderMainView();
  }

  async function loadCrossSchemeSummary() {
    const names = state.schemes.slice(0, 8).map((s) => s.name);
    if (!names.length) return;
    try {
      const res = await window.PowerPlanUI.fetchJson(`/api/sensitivity/summary?schemes=${encodeURIComponent(names.join(","))}`, {
        slot: "plan-dash-compare",
        ttlMs: 20000,
      });
      state.compareRows = Array.isArray(res?.rows) ? res.rows : [];
      renderSchemeCompareList();
    } catch (_) {}
  }

  function startPlayback() {
    stopPlayback();
    state.playing = true;
    const btn = document.getElementById("scadaPlayBtn");
    if (btn) {
      btn.setAttribute("aria-pressed", "true");
      btn.textContent = tr("暂停");
    }
    state.playTimer = window.setInterval(() => {
      if (document.hidden || state.mode !== "typical") return;
      state.hour = (state.hour + 1) % 24;
      const slider = document.getElementById("scadaHourSlider");
      if (slider) slider.value = String(state.hour);
      renderMainView();
    }, 850);
  }

  function stopPlayback() {
    state.playing = false;
    if (state.playTimer) {
      window.clearInterval(state.playTimer);
      state.playTimer = 0;
    }
    const btn = document.getElementById("scadaPlayBtn");
    if (btn) {
      btn.setAttribute("aria-pressed", "false");
      btn.textContent = tr("播放");
    }
  }

  async function init() {
    const saved = window.PowerPlanPageState?.read?.(PAGE_STATE_KEY, {}) || {};
    const ctx = window.PowerPlanPageState?.getActiveContext?.() || {};
    const res = await window.PowerPlanUI.fetchJson("/api/planning/schemes", { slot: "plan-dash-schemes", ttlMs: 10000 });
    state.schemes = Array.isArray(res?.schemes) ? res.schemes : [];

    const targetScheme =
      [ctx.scheme, saved.currentScheme, state.schemes[0]?.name].find((n) => n && state.schemes.some((s) => s.name === n)) || "";
    const targetFile = ctx.filename || saved.selectedResultFile || "";

    const schemeSelect = document.getElementById("scadaSchemeSelect");
    if (schemeSelect) {
      schemeSelect.innerHTML = state.schemes
        .map((s) => `<option value="${escapeHtml(s.name)}"${s.name === targetScheme ? " selected" : ""}>${escapeHtml(s.name)}</option>`)
        .join("");
      schemeSelect.addEventListener("change", () => {
        loadScenarioData(schemeSelect.value, "").catch((e) => window.PowerPlanUI?.toast?.(e.message, { level: "error" }));
      });
    }

    document.getElementById("scadaFileSelect")?.addEventListener("change", (e) => {
      loadScenarioData(state.currentScheme, e.target.value).catch((err) => window.PowerPlanUI?.toast?.(err.message, { level: "error" }));
    });
    document.getElementById("scadaDaySelect")?.addEventListener("change", (e) => {
      state.dayIndex = Number(e.target.value) || 0;
      renderMainView();
    });

    document.querySelectorAll("[data-plan-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.mode = btn.dataset.planMode === "typical" ? "typical" : "annual";
        if (state.mode !== "typical") stopPlayback();
        renderMainView();
      });
    });

    document.getElementById("scadaPlayBtn")?.addEventListener("click", () => {
      if (state.playing) stopPlayback();
      else startPlayback();
    });
    document.getElementById("scadaPrevHourBtn")?.addEventListener("click", () => {
      state.hour = (state.hour + 23) % 24;
      const slider = document.getElementById("scadaHourSlider");
      if (slider) slider.value = String(state.hour);
      renderMainView();
    });
    document.getElementById("scadaNextHourBtn")?.addEventListener("click", () => {
      state.hour = (state.hour + 1) % 24;
      const slider = document.getElementById("scadaHourSlider");
      if (slider) slider.value = String(state.hour);
      renderMainView();
    });
    document.getElementById("scadaHourSlider")?.addEventListener("input", (e) => {
      state.hour = Number(e.target.value) || 0;
      renderMainView();
    });

    document.getElementById("scadaFullscreenBtn")?.addEventListener("click", () => {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
      else document.exitFullscreen?.().catch(() => {});
    });

    window.addEventListener("powerplan:themechange", renderMainView);
    document.getElementById("languageSelect")?.addEventListener("change", () => {
      window.setTimeout(renderMainView, 30);
    });
    window.addEventListener("resize", () => renderBottomChart(buildPlanSummary()));

    window.PowerPlanEvents?.on?.("tasks", () => {
      if (!document.hidden && state.currentScheme) {
        loadScenarioData(state.currentScheme, state.selectedFile).catch(() => {});
        loadCrossSchemeSummary().catch(() => {});
      }
    });

    if (targetScheme) {
      await loadScenarioData(targetScheme, targetFile);
    }
    loadCrossSchemeSummary();
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((err) => window.PowerPlanUI?.toast?.(err.message || "规划大屏加载失败", { level: "error" }));
  });
})();
