/**
 * 工程级高阶可视化与 HiDPI Canvas 2D 曲线渲染引擎。
 * 提供：HiDPI 折线 Canvas、365x24 热力图、典型日 24h 堆叠平衡图、
 * 年度能量流向桑基图、LCOE 成本瀑布拆解、5 维对比雷达图与敏感性龙卷风图。
 */
(() => {
  "use strict";

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
    const fallback = {
      series: ["#38BDF8", "#FBBF24", "#34D399", "#FB7185", "#A78BFA", "#2DD4BF", "#FB923C", "#94A3B8"],
      grid: "rgba(148,163,184,0.16)",
      axis: "rgba(148,163,184,0.38)",
      text: "#94A3B8",
      surface: "#0F172A",
      wind: "#38BDF8",
      solar: "#FBBF24",
      diesel: "#FB7185",
      load: "#34D399",
      storage: "#2DD4BF",
      hydrogen: "#A78BFA",
      curtail: "#94A3B8",
    };
    const p = window.PowerPlanUI?.getChartPalette?.();
    return p ? { ...fallback, ...p } : fallback;
  }

  /** 计算视觉友好的纵轴刻度值（Nice Ticks） */
  function niceTicks(minVal, maxVal, tickCount = 5) {
    let min = Number.isFinite(minVal) ? minVal : 0;
    let max = Number.isFinite(maxVal) ? maxVal : 1;
    if (max <= min) {
      const pad = Math.abs(min) > 1e-6 ? Math.abs(min) * 0.1 : 1;
      min -= pad;
      max += pad;
    }
    const span = max - min;
    const rawStep = span / Math.max(1, tickCount - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const norm = rawStep / mag;
    let step = mag;
    if (norm <= 1.2) step = 1 * mag;
    else if (norm <= 2.2) step = 2 * mag;
    else if (norm <= 3.5) step = 2.5 * mag;
    else if (norm <= 6.0) step = 5 * mag;
    else step = 10 * mag;

    const niceMin = Math.floor(min / step) * step;
    const niceMax = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = niceMin; v <= niceMax + step * 0.25; v += step) {
      ticks.push(Math.abs(v) < 1e-10 ? 0 : Number(v.toFixed(6)));
      if (ticks.length > 12) break;
    }
    return { min: niceMin, max: niceMax, step, ticks };
  }

  /** 智能紧凑格式化数值（避免 1250000 溢出坐标轴） */
  function formatCompact(val) {
    const n = Number(val);
    if (!Number.isFinite(n)) return "—";
    const abs = Math.abs(n);
    if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
    if (abs >= 1e4) return `${(n / 1e3).toFixed(1)}k`;
    if (abs >= 100) return String(Math.round(n));
    if (abs >= 10) return Number(n.toFixed(1)).toString();
    if (abs >= 1) return Number(n.toFixed(2)).toString();
    return Number(n.toFixed(3)).toString();
  }

  /** 高帧率 HiDPI Canvas 2D 多折线渲染器（供 8760 点高频曲线与缩放使用） */
  function drawHiDpiPolylines(canvas, { width, height, margin, seriesList, xAt, yAtForSeries }) {
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = Math.max(1, Math.round(canvas.clientWidth || width));
    const cssH = Math.max(1, Math.round(canvas.clientHeight || height));
    const targetW = Math.round(cssW * dpr);
    const targetH = Math.round(cssH * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const scaleX = cssW / Math.max(1, width);
    const scaleY = cssH / Math.max(1, height);
    const clipX = margin.left * scaleX;
    const clipY = margin.top * scaleY;
    const clipW = (width - margin.left - margin.right) * scaleX;
    const clipH = (height - margin.top - margin.bottom) * scaleY;

    ctx.save();
    ctx.beginPath();
    ctx.rect(clipX, clipY, clipW, clipH);
    ctx.clip();

    seriesList.forEach((item) => {
      const pts = item.points || [];
      if (!pts.length) return;
      const yFn = yAtForSeries(item);
      const total = pts.length;
      const strokeColor = item.color || "#38BDF8";

      ctx.beginPath();
      let started = false;
      // 超过 2 倍像素宽度时做 Min-Max 垂直包络采样，保持极值不丢且绘制 < 2ms
      const maxBuckets = Math.max(120, Math.round(clipW * 1.4));
      if (total > maxBuckets * 2) {
        const step = total / maxBuckets;
        for (let b = 0; b < maxBuckets; b += 1) {
          const i0 = Math.floor(b * step);
          const i1 = Math.min(total, Math.floor((b + 1) * step));
          let minV = Infinity;
          let maxV = -Infinity;
          let minI = i0;
          let maxI = i0;
          for (let i = i0; i < i1; i += 1) {
            const v = Number(pts[i]?.y);
            if (!Number.isFinite(v)) continue;
            if (v < minV) { minV = v; minI = i; }
            if (v > maxV) { maxV = v; maxI = i; }
          }
          if (!Number.isFinite(minV)) continue;
          const ordered = minI <= maxI ? [[minI, minV], [maxI, maxV]] : [[maxI, maxV], [minI, minV]];
          for (const [idx, val] of ordered) {
            const px = xAt(idx, total) * scaleX;
            const py = yFn(val) * scaleY;
            if (!started) {
              ctx.moveTo(px, py);
              started = true;
            } else {
              ctx.lineTo(px, py);
            }
          }
        }
      } else {
        for (let i = 0; i < total; i += 1) {
          const v = Number(pts[i]?.y);
          if (!Number.isFinite(v)) continue;
          const px = xAt(i, total) * scaleX;
          const py = yFn(v) * scaleY;
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        }
      }

      if (item.dash) {
        ctx.setLineDash(
          String(item.dash)
            .split(/\s+/)
            .map((v) => Number(v))
            .filter((n) => Number.isFinite(n) && n > 0),
        );
      } else {
        ctx.setLineDash([]);
      }
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = seriesList.length <= 2 ? 1.8 : 1.45;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();

      // 单曲线时填充柔和面积渐变提升层次感
      if (seriesList.length === 1 && started) {
        ctx.setLineDash([]);
        ctx.lineTo(xAt(total - 1, total) * scaleX, clipY + clipH);
        ctx.lineTo(xAt(0, total) * scaleX, clipY + clipH);
        ctx.closePath();
        const grad = ctx.createLinearGradient(0, clipY, 0, clipY + clipH);
        grad.addColorStop(0, `${strokeColor}33`);
        grad.addColorStop(1, `${strokeColor}03`);
        ctx.fillStyle = grad;
        ctx.fill();
      }
    });

    ctx.restore();
  }

  /** 热力图色阶插值（色盲友好：深海蓝 -> 蓝绿 -> 琥珀 -> 绯红） */
  function heatmapColor(ratio, isDiverging = false) {
    const t = Math.max(0, Math.min(1, ratio));
    const stops = isDiverging
      ? [
          [0.0, [14, 165, 233]],
          [0.42, [30, 41, 59]],
          [0.58, [51, 65, 85]],
          [0.8, [245, 158, 11]],
          [1.0, [244, 63, 94]],
        ]
      : [
          [0.0, [15, 23, 42]],
          [0.25, [14, 116, 144]],
          [0.55, [52, 211, 153]],
          [0.8, [251, 191, 36]],
          [1.0, [244, 63, 94]],
        ];
    for (let i = 0; i < stops.length - 1; i += 1) {
      const [t0, c0] = stops[i];
      const [t1, c1] = stops[i + 1];
      if (t >= t0 && t <= t1) {
        const f = (t - t0) / Math.max(1e-6, t1 - t0);
        const r = Math.round(c0[0] + (c1[0] - c0[0]) * f);
        const g = Math.round(c0[1] + (c1[1] - c0[1]) * f);
        const b = Math.round(c0[2] + (c1[2] - c0[2]) * f);
        return `rgb(${r},${g},${b})`;
      }
    }
    const last = stops[stops.length - 1][1];
    return `rgb(${last[0]},${last[1]},${last[2]})`;
  }

  /** 渲染 365x24 全年工程热力图（Canvas 2D + 指标切换 + 悬浮读数 + PNG导出） */
  function renderHeatmap365x24(container, heatmaps, options = {}) {
    if (!container) return;
    const keys = Object.keys(heatmaps || {}).filter((k) => Array.isArray(heatmaps[k]?.matrix) && heatmaps[k].matrix.length);
    if (!keys.length) {
      container.innerHTML = `<div class="empty-summary">${escapeHtml(tr("暂无全年 365×24 小时热力图数据"))}</div>`;
      return;
    }
    let activeKey = options.activeKey && heatmaps[options.activeKey] ? options.activeKey : keys[0];

    container.innerHTML = `
      <div class="insight-card-head">
        <div class="insight-card-title">${escapeHtml(tr("全年 365×24 时段热力图"))}</div>
        <div class="insight-card-controls">
          <div class="insight-chip-group" data-hm-chips>
            ${keys
              .map(
                (k) =>
                  `<button type="button" class="insight-chip${k === activeKey ? " active" : ""}" data-hm-key="${escapeHtml(k)}">${escapeHtml(tr(heatmaps[k].label || k))}</button>`,
              )
              .join("")}
          </div>
          <button type="button" class="insight-export-btn" data-hm-export>PNG</button>
        </div>
      </div>
      <div class="insight-heatmap-stage">
        <canvas class="insight-heatmap-canvas"></canvas>
        <div class="insight-tooltip" hidden></div>
      </div>
      <div class="insight-heatmap-footer" data-hm-legend></div>
    `;

    const canvas = container.querySelector(".insight-heatmap-canvas");
    const tip = container.querySelector(".insight-tooltip");
    const legendEl = container.querySelector("[data-hm-legend]");

    const draw = () => {
      const hm = heatmaps[activeKey];
      if (!hm || !canvas) return;
      const mat = hm.matrix;
      const days = mat.length;
      const hours = 24;
      const pal = getPalette();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cssW = Math.max(360, Math.round(canvas.parentElement?.clientWidth || 720));
      const cssH = 224;
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${cssH}px`;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);

      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);

      const padL = 44;
      const padR = 14;
      const padT = 10;
      const padB = 26;
      const plotW = cssW - padL - padR;
      const plotH = cssH - padT - padB;
      const cw = plotW / days;
      const ch = plotH / hours;
      const minV = Number(hm.min ?? 0);
      const maxV = Number(hm.max ?? 1);
      const span = Math.max(1e-6, maxV - minV);
      const isDiverging = activeKey === "net_load" && minV < 0 && maxV > 0;

      for (let d = 0; d < days; d += 1) {
        const row = mat[d];
        const x = padL + d * cw;
        const w = Math.max(1, Math.ceil(cw + 0.35));
        for (let h = 0; h < hours; h += 1) {
          const val = Number(row[h] ?? 0);
          const ratio = (val - minV) / span;
          ctx.fillStyle = heatmapColor(ratio, isDiverging);
          ctx.fillRect(x, padT + (hours - 1 - h) * ch, w, Math.ceil(ch + 0.35));
        }
      }

      // 坐标轴刻度
      ctx.fillStyle = pal.text;
      ctx.font = "10.5px ui-monospace, SFMono-Regular, Consolas, monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      [0, 6, 12, 18, 23].forEach((h) => {
        const y = padT + (hours - 1 - h + 0.5) * ch;
        ctx.fillText(`${String(h).padStart(2, "0")}:00`, padL - 6, y);
      });
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const monthStarts = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
      monthStarts.forEach((dStart, mIdx) => {
        if (dStart < days) {
          const x = padL + (dStart + 15) * cw;
          ctx.fillText(`${mIdx + 1}${tr("月")}`, x, padT + plotH + 6);
        }
      });

      if (legendEl) {
        const gradStops = [0, 0.25, 0.5, 0.75, 1].map((r) => heatmapColor(r, isDiverging)).join(",");
        legendEl.innerHTML = `
          <span>${escapeHtml(tr("最小"))}: <b>${formatCompact(minV)} ${escapeHtml(hm.unit)}</b></span>
          <span class="insight-colorbar" style="background:linear-gradient(90deg, ${gradStops});"></span>
          <span>${escapeHtml(tr("均值"))}: <b>${formatCompact(hm.avg)} ${escapeHtml(hm.unit)}</b> · ${escapeHtml(tr("最大"))}: <b>${formatCompact(maxV)} ${escapeHtml(hm.unit)}</b></span>
        `;
      }

      canvas._hmMeta = { padL, padT, plotW, plotH, days, hours, hm };
    };

    draw();

    container.querySelectorAll("[data-hm-key]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeKey = btn.dataset.hmKey;
        container.querySelectorAll("[data-hm-key]").forEach((b) => b.classList.toggle("active", b === btn));
        draw();
      });
    });

    container.querySelector("[data-hm-export]")?.addEventListener("click", () => {
      const hm = heatmaps[activeKey];
      window.PowerPlanUI?.exportCanvasAsPng?.(canvas, `heatmap_${activeKey}.png`, hm?.label || activeKey);
    });

    canvas?.addEventListener("mousemove", (e) => {
      const meta = canvas._hmMeta;
      if (!meta || !tip) return;
      const rect = canvas.getBoundingClientRect();
      const rx = e.clientX - rect.left - meta.padL;
      const ry = e.clientY - rect.top - meta.padT;
      if (rx < 0 || ry < 0 || rx > meta.plotW || ry > meta.plotH) {
        tip.hidden = true;
        return;
      }
      const d = Math.min(meta.days - 1, Math.max(0, Math.floor((rx / meta.plotW) * meta.days)));
      const h = Math.min(23, Math.max(0, 23 - Math.floor((ry / meta.plotH) * 24)));
      const val = meta.hm.matrix[d]?.[h];
      tip.hidden = false;
      tip.innerHTML = `<strong>${tr("第")} ${d + 1} ${tr("天")} · ${String(h).padStart(2, "0")}:00</strong><div>${escapeHtml(tr(meta.hm.label))}: <b>${Number(val).toFixed(2)} ${escapeHtml(meta.hm.unit)}</b></div>`;
      const left = Math.min(rect.width - 170, Math.max(8, e.clientX - rect.left + 12));
      const top = Math.max(6, e.clientY - rect.top - 48);
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    });
    canvas?.addEventListener("mouseleave", () => {
      if (tip) tip.hidden = true;
    });

    return { redraw: draw };
  }

  /** 渲染典型日 24h 源-储-氢-柴堆叠功率平衡图 */
  function renderTypicalDayStack(container, typicalDays) {
    if (!container) return;
    if (!Array.isArray(typicalDays) || !typicalDays.length) {
      container.innerHTML = `<div class="empty-summary">${escapeHtml(tr("暂无典型日功率平衡数据"))}</div>`;
      return;
    }
    let activeIdx = 0;

    container.innerHTML = `
      <div class="insight-card-head">
        <div class="insight-card-title">${escapeHtml(tr("典型日 24h 功率堆叠平衡"))}</div>
        <div class="insight-card-controls">
          <div class="insight-chip-group">
            ${typicalDays
              .map(
                (d, idx) =>
                  `<button type="button" class="insight-chip${idx === 0 ? " active" : ""}" data-td-idx="${idx}">${escapeHtml(tr(d.title))} (${escapeHtml(d.date)})</button>`,
              )
              .join("")}
          </div>
          <button type="button" class="insight-export-btn" data-td-export-png>PNG</button>
          <button type="button" class="insight-export-btn" data-td-export-svg>SVG</button>
        </div>
      </div>
      <div class="insight-svg-stage">
        <svg class="insight-typical-svg" role="img" aria-label="典型日功率平衡"></svg>
        <div class="insight-tooltip" hidden></div>
      </div>
      <div class="insight-typical-meta" data-td-meta></div>
    `;

    const svg = container.querySelector(".insight-typical-svg");
    const tip = container.querySelector(".insight-tooltip");
    const metaEl = container.querySelector("[data-td-meta]");

    const draw = () => {
      const day = typicalDays[activeIdx];
      if (!day || !svg) return;
      const pal = getPalette();
      const s = day.series || {};
      const width = Math.max(460, Math.round(svg.parentElement?.clientWidth || 700));
      const height = 240;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

      const posKeys = [
        { k: "wind", label: tr("风电"), color: pal.wind },
        { k: "pv", label: tr("光伏"), color: pal.solar },
        { k: "storage_discharge", label: tr("储能放电"), color: pal.storage },
        { k: "fuel_cell", label: tr("燃料电池"), color: pal.hydrogen },
        { k: "diesel", label: tr("柴发"), color: pal.diesel },
      ];
      const negKeys = [
        { k: "storage_charge", label: tr("储能充电"), color: "#0284C7" },
        { k: "hydrogen_prod", label: tr("电制氢"), color: "#7C3AED" },
        { k: "curtailed", label: tr("弃电"), color: pal.curtail },
      ];

      let maxPos = 1;
      let maxNeg = 0;
      for (let h = 0; h < 24; h += 1) {
        const pSum = posKeys.reduce((acc, it) => acc + Math.max(0, Number(s[it.k]?.[h] || 0)), 0);
        const nSum = negKeys.reduce((acc, it) => acc + Math.max(0, Number(s[it.k]?.[h] || 0)), 0);
        const ld = Number(s.load?.[h] || 0);
        maxPos = Math.max(maxPos, pSum, ld);
        maxNeg = Math.max(maxNeg, nSum);
      }
      const tickInfo = niceTicks(-maxNeg, maxPos, 5);
      const minY = Math.min(0, tickInfo.min);
      const maxY = Math.max(1, tickInfo.max);
      const span = Math.max(1e-6, maxY - minY);

      const padL = 52;
      const padR = 16;
      const padT = 26;
      const padB = 26;
      const plotW = width - padL - padR;
      const plotH = height - padT - padB;
      const slotW = plotW / 24;
      const barW = Math.max(6, Math.min(22, slotW * 0.66));
      const sy = (v) => padT + plotH - ((v - minY) / span) * plotH;
      const y0 = sy(0);

      const gridSvg = tickInfo.ticks
        .map((tv) => {
          const yy = sy(tv);
          return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${tv === 0 ? pal.axis : pal.grid}" stroke-dasharray="${tv === 0 ? "" : "3 3"}"/>
                  <text x="${padL - 7}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="10.5">${formatCompact(tv)}</text>`;
        })
        .join("");

      const barsSvg = Array.from({ length: 24 }, (_, h) => {
        const cx = padL + slotW * h + slotW / 2;
        const x0 = cx - barW / 2;
        let pAcc = 0;
        const posRects = posKeys
          .map((it) => {
            const v = Math.max(0, Number(s[it.k]?.[h] || 0));
            if (v <= 0.01) return "";
            const yt = sy(pAcc + v);
            const yb = sy(pAcc);
            pAcc += v;
            return `<rect x="${x0.toFixed(1)}" y="${yt.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.6, yb - yt).toFixed(1)}" fill="${it.color}" opacity="0.92"/>`;
          })
          .join("");
        let nAcc = 0;
        const negRects = negKeys
          .map((it) => {
            const v = Math.max(0, Number(s[it.k]?.[h] || 0));
            if (v <= 0.01) return "";
            const yt = sy(-nAcc);
            const yb = sy(-(nAcc + v));
            nAcc += v;
            return `<rect x="${x0.toFixed(1)}" y="${yt.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.6, yb - yt).toFixed(1)}" fill="${it.color}" opacity="0.72"/>`;
          })
          .join("");
        const xLabel = h % 3 === 0 ? `<text x="${cx.toFixed(1)}" y="${height - 8}" text-anchor="middle" fill="${pal.text}" font-size="10">${String(h).padStart(2, "0")}:00</text>` : "";
        return `${posRects}${negRects}${xLabel}<rect class="insight-hit-col" data-td-hour="${h}" x="${(padL + slotW * h).toFixed(1)}" y="${padT}" width="${slotW.toFixed(1)}" height="${plotH}" fill="transparent"/>`;
      }).join("");

      const loadPath = Array.from({ length: 24 }, (_, h) => {
        const cx = padL + slotW * h + slotW / 2;
        return `${h === 0 ? "M" : "L"}${cx.toFixed(1)},${sy(Number(s.load?.[h] || 0)).toFixed(1)}`;
      }).join(" ");

      const legendItems = [...posKeys, { k: "load", label: tr("负荷"), color: pal.load }, ...negKeys];
      const legendSvg = legendItems
        .map((it, idx) => {
          const lx = padL + idx * Math.min(82, (plotW - 10) / legendItems.length);
          return `<g transform="translate(${lx.toFixed(1)}, 8)"><rect width="9" height="7" rx="2" fill="${it.color}"/><text x="12" y="7" fill="${pal.text}" font-size="10">${escapeHtml(it.label)}</text></g>`;
        })
        .join("");

      svg.innerHTML = `${gridSvg}<line x1="${padL}" x2="${width - padR}" y1="${y0.toFixed(1)}" y2="${y0.toFixed(1)}" stroke="${pal.axis}"/>${barsSvg}<path d="${loadPath}" fill="none" stroke="${pal.load}" stroke-width="2.2"/>${legendSvg}`;

      if (metaEl && day.summary) {
        const sm = day.summary;
        metaEl.innerHTML = `
          <span>${tr("日负荷")}: <b>${formatCompact(sm.load_kwh)} kWh</b></span>
          <span>${tr("风电")}: <b>${formatCompact(sm.wind_kwh)} kWh</b></span>
          <span>${tr("光伏")}: <b>${formatCompact(sm.pv_kwh)} kWh</b></span>
          <span>${tr("柴发")}: <b>${formatCompact(sm.diesel_kwh)} kWh</b></span>
          <span>${tr("弃电")}: <b>${formatCompact(sm.curtailed_kwh)} kWh</b></span>
        `;
      }

      svg.querySelectorAll("[data-td-hour]").forEach((colEl) => {
        colEl.addEventListener("mousemove", (e) => {
          if (!tip) return;
          const h = Number(colEl.dataset.tdHour);
          const rect = svg.parentElement.getBoundingClientRect();
          const lines = [
            `<div class="insight-tip-row"><span>${tr("负荷")}</span><b>${Number(s.load?.[h] || 0).toFixed(1)} kW</b></div>`,
            ...posKeys
              .filter((it) => Number(s[it.k]?.[h] || 0) > 0.05)
              .map((it) => `<div class="insight-tip-row"><span style="color:${it.color}">${escapeHtml(it.label)}</span><b>${Number(s[it.k][h]).toFixed(1)} kW</b></div>`),
            ...negKeys
              .filter((it) => Number(s[it.k]?.[h] || 0) > 0.05)
              .map((it) => `<div class="insight-tip-row"><span style="color:${it.color}">${escapeHtml(it.label)}</span><b>-${Number(s[it.k][h]).toFixed(1)} kW</b></div>`),
          ];
          tip.hidden = false;
          tip.innerHTML = `<strong>${escapeHtml(day.date)} · ${String(h).padStart(2, "0")}:00</strong>${lines.join("")}`;
          tip.style.left = `${Math.min(rect.width - 175, Math.max(8, e.clientX - rect.left + 12))}px`;
          tip.style.top = `${Math.max(6, e.clientY - rect.top - 36)}px`;
        });
        colEl.addEventListener("mouseleave", () => {
          if (tip) tip.hidden = true;
        });
      });
    };

    draw();

    container.querySelectorAll("[data-td-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeIdx = Number(btn.dataset.tdIdx) || 0;
        container.querySelectorAll("[data-td-idx]").forEach((b) => b.classList.toggle("active", b === btn));
        draw();
      });
    });
    container.querySelector("[data-td-export-png]")?.addEventListener("click", () => {
      window.PowerPlanUI?.exportSvgAsPng?.(svg, `typical_day_${typicalDays[activeIdx]?.key || "day"}.png`);
    });
    container.querySelector("[data-td-export-svg]")?.addEventListener("click", () => {
      window.PowerPlanUI?.exportSvgAsSvg?.(svg, `typical_day_${typicalDays[activeIdx]?.key || "day"}.svg`);
    });

    return { redraw: draw };
  }

  /** 渲染年度能量流向桑基图（Sankey） */
  function renderEnergySankey(container, sankey) {
    if (!container) return;
    const nodes = sankey?.nodes || [];
    const links = sankey?.links || [];
    if (!nodes.length || !links.length) {
      container.innerHTML = `<div class="empty-summary">${escapeHtml(tr("暂无年度能量流向数据"))}</div>`;
      return;
    }

    container.innerHTML = `
      <div class="insight-card-head">
        <div class="insight-card-title">${escapeHtml(tr("年度能量流向桑基图"))} (${escapeHtml(sankey.unit || "MWh")})</div>
        <div class="insight-card-controls">
          <button type="button" class="insight-export-btn" data-sk-png>PNG</button>
          <button type="button" class="insight-export-btn" data-sk-svg>SVG</button>
        </div>
      </div>
      <div class="insight-svg-stage">
        <svg class="insight-sankey-svg" role="img" aria-label="年度能量流向"></svg>
        <div class="insight-tooltip" hidden></div>
      </div>
    `;

    const svg = container.querySelector(".insight-sankey-svg");
    const tip = container.querySelector(".insight-tooltip");

    const draw = () => {
      const pal = getPalette();
      const width = Math.max(400, Math.round(svg.parentElement?.clientWidth || 560));
      const height = 228;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

      const padX = 16;
      const padY = 16;
      const nodeW = 14;
      const colXs = [padX + 76, width * 0.48 - nodeW / 2, width - padX - 138];

      const inSum = new Map();
      const outSum = new Map();
      links.forEach((lk) => {
        outSum.set(lk.source, (outSum.get(lk.source) || 0) + lk.value);
        inSum.set(lk.target, (inSum.get(lk.target) || 0) + lk.value);
      });

      const cols = [[], [], []];
      nodes.forEach((nd) => {
        const val = Math.max(inSum.get(nd.id) || 0, outSum.get(nd.id) || 0);
        cols[Math.min(2, Math.max(0, nd.col || 0))].push({ ...nd, val });
      });

      const maxColVal = Math.max(
        1,
        ...cols.map((arr) => arr.reduce((a, b) => a + b.val, 0)),
      );
      const availH = height - padY * 2;
      const nodeMap = new Map();

      cols.forEach((arr, cIdx) => {
        const gap = 14;
        const usableH = Math.max(40, availH - Math.max(0, arr.length - 1) * gap);
        const total = arr.reduce((a, b) => a + b.val, 0) || 1;
        const scale = Math.min(usableH / maxColVal, usableH / total);
        let yCursor = padY + (availH - (total * scale + Math.max(0, arr.length - 1) * gap)) / 2;
        arr.forEach((nd) => {
          const h = Math.max(10, nd.val * scale);
          nodeMap.set(nd.id, {
            ...nd,
            x: colXs[cIdx],
            y: yCursor,
            h,
            outOff: 0,
            inOff: 0,
          });
          yCursor += h + gap;
        });
      });

      const linkPaths = links
        .map((lk, idx) => {
          const src = nodeMap.get(lk.source);
          const dst = nodeMap.get(lk.target);
          if (!src || !dst) return "";
          const srcScale = src.h / Math.max(1e-6, outSum.get(src.id) || src.val);
          const dstScale = dst.h / Math.max(1e-6, inSum.get(dst.id) || dst.val);
          const thickness = Math.max(2, Math.min(lk.value * srcScale, lk.value * dstScale));
          const sy = src.y + src.outOff + thickness / 2;
          const dy = dst.y + dst.inOff + thickness / 2;
          src.outOff += lk.value * srcScale;
          dst.inOff += lk.value * dstScale;
          const x0 = src.x + nodeW;
          const x1 = dst.x;
          const mx = (x0 + x1) / 2;
          return `<path class="insight-sankey-link" data-sk-link="${idx}" d="M${x0.toFixed(1)},${sy.toFixed(1)} C${mx.toFixed(1)},${sy.toFixed(1)} ${mx.toFixed(1)},${dy.toFixed(1)} ${x1.toFixed(1)},${dy.toFixed(1)}" fill="none" stroke="${src.color}" stroke-width="${thickness.toFixed(1)}" stroke-opacity="0.42"/>`;
        })
        .join("");

      const nodeRects = Array.from(nodeMap.values())
        .map((nd) => {
          const labelX = nd.col === 0 ? nd.x - 7 : nd.col === 2 ? nd.x + nodeW + 7 : nd.x + nodeW / 2;
          const anchor = nd.col === 0 ? "end" : nd.col === 2 ? "start" : "middle";
          const labelY = nd.col === 1 ? nd.y - 5 : nd.y + nd.h / 2 + 3.5;
          return `<g>
            <rect x="${nd.x.toFixed(1)}" y="${nd.y.toFixed(1)}" width="${nodeW}" height="${nd.h.toFixed(1)}" rx="3" fill="${nd.color}"/>
            <text x="${labelX.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="${anchor}" fill="${pal.text}" font-size="11">${escapeHtml(tr(nd.label))} (${formatCompact(nd.val)})</text>
          </g>`;
        })
        .join("");

      svg.innerHTML = `${linkPaths}${nodeRects}`;

      svg.querySelectorAll("[data-sk-link]").forEach((el) => {
        el.addEventListener("mousemove", (e) => {
          const lk = links[Number(el.dataset.skLink)];
          if (!lk || !tip) return;
          const src = nodeMap.get(lk.source);
          const dst = nodeMap.get(lk.target);
          const rect = svg.parentElement.getBoundingClientRect();
          tip.hidden = false;
          tip.innerHTML = `<strong>${escapeHtml(tr(src?.label || lk.source))} → ${escapeHtml(tr(dst?.label || lk.target))}</strong><div>${lk.value.toFixed(2)} ${escapeHtml(sankey.unit || "MWh")}</div>`;
          tip.style.left = `${Math.min(rect.width - 170, Math.max(8, e.clientX - rect.left + 12))}px`;
          tip.style.top = `${Math.max(6, e.clientY - rect.top - 40)}px`;
        });
        el.addEventListener("mouseleave", () => {
          if (tip) tip.hidden = true;
        });
      });
    };

    draw();
    container.querySelector("[data-sk-png]")?.addEventListener("click", () => window.PowerPlanUI?.exportSvgAsPng?.(svg, "energy_sankey.png"));
    container.querySelector("[data-sk-svg]")?.addEventListener("click", () => window.PowerPlanUI?.exportSvgAsSvg?.(svg, "energy_sankey.svg"));
    return { redraw: draw };
  }

  /** 渲染 LCOE 成本构成瀑布拆解图 */
  function renderLcoeWaterfall(container, waterfall) {
    if (!container) return;
    const items = waterfall?.items || [];
    if (!items.length) {
      container.innerHTML = `<div class="empty-summary">${escapeHtml(tr("暂无成本构成拆解数据"))}</div>`;
      return;
    }

    const lcoeText = waterfall.lcoe != null ? `${waterfall.lcoe} ${waterfall.lcoe_unit || "元/kWh"}` : "—";
    container.innerHTML = `
      <div class="insight-card-head">
        <div class="insight-card-title">${escapeHtml(tr("年化成本与 LCOE 瀑布拆解"))} · <em>${escapeHtml(lcoeText)}</em></div>
        <div class="insight-card-controls">
          <button type="button" class="insight-export-btn" data-wf-png>PNG</button>
          <button type="button" class="insight-export-btn" data-wf-svg>SVG</button>
        </div>
      </div>
      <div class="insight-svg-stage">
        <svg class="insight-waterfall-svg" role="img" aria-label="成本构成瀑布图"></svg>
        <div class="insight-tooltip" hidden></div>
      </div>
    `;

    const svg = container.querySelector(".insight-waterfall-svg");
    const tip = container.querySelector(".insight-tooltip");

    const draw = () => {
      const pal = getPalette();
      const width = Math.max(360, Math.round(svg.parentElement?.clientWidth || 520));
      const height = 228;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

      const totalVal = Math.max(1e-6, ...items.map((it) => Number(it.value) || 0));
      const tickInfo = niceTicks(0, totalVal * 1.12, 4);
      const maxY = Math.max(1, tickInfo.max);

      const padL = 52;
      const padR = 16;
      const padT = 20;
      const padB = 34;
      const plotW = width - padL - padR;
      const plotH = height - padT - padB;
      const slotW = plotW / items.length;
      const barW = Math.max(22, Math.min(54, slotW * 0.52));
      const sy = (v) => padT + plotH - (v / maxY) * plotH;

      const gridSvg = tickInfo.ticks
        .map((tv) => {
          const yy = sy(tv);
          return `<line x1="${padL}" x2="${width - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${pal.grid}" stroke-dasharray="3 3"/>
                  <text x="${padL - 7}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="10.5">${formatCompact(tv)}</text>`;
        })
        .join("");

      const colors = { capex: pal.wind, fuel: pal.diesel, om: pal.solar, opex: pal.diesel, other: pal.hydrogen, total: pal.load };
      let acc = 0;
      const bars = items
        .map((it, idx) => {
          const cx = padL + slotW * idx + slotW / 2;
          const x0 = cx - barW / 2;
          const isTotal = it.kind === "total";
          const start = isTotal ? 0 : acc;
          const end = isTotal ? it.value : acc + it.value;
          if (!isTotal) acc = end;
          const yTop = sy(end);
          const yBot = sy(start);
          const h = Math.max(2, yBot - yTop);
          const color = colors[it.key] || pal.series[idx % pal.series.length];
          const connector = !isTotal && idx < items.length - 1
            ? `<line x1="${(x0 + barW).toFixed(1)}" x2="${(padL + slotW * (idx + 1) + slotW / 2 - barW / 2).toFixed(1)}" y1="${yTop.toFixed(1)}" y2="${yTop.toFixed(1)}" stroke="${pal.axis}" stroke-dasharray="2 2"/>`
            : "";
          return `${connector}
            <rect class="insight-wf-bar" data-wf-idx="${idx}" x="${x0.toFixed(1)}" y="${yTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${color}"/>
            <text x="${cx.toFixed(1)}" y="${(yTop - 5).toFixed(1)}" text-anchor="middle" fill="${pal.text}" font-size="10.5">${formatCompact(it.value)}</text>
            <text x="${cx.toFixed(1)}" y="${height - 12}" text-anchor="middle" fill="${pal.text}" font-size="10.5">${escapeHtml(tr(it.label))}</text>`;
        })
        .join("");

      svg.innerHTML = `${gridSvg}<line x1="${padL}" x2="${width - padR}" y1="${padT + plotH}" y2="${padT + plotH}" stroke="${pal.axis}"/>${bars}`;

      const grandTotal = items.find((i) => i.kind === "total")?.value || items.reduce((a, b) => a + (b.value || 0), 0) || 1;
      svg.querySelectorAll("[data-wf-idx]").forEach((el) => {
        el.addEventListener("mousemove", (e) => {
          const it = items[Number(el.dataset.wfIdx)];
          if (!it || !tip) return;
          const rect = svg.parentElement.getBoundingClientRect();
          const pct = ((it.value / grandTotal) * 100).toFixed(1);
          tip.hidden = false;
          tip.innerHTML = `<strong>${escapeHtml(tr(it.label))}</strong><div>${it.value.toFixed(2)} ${escapeHtml(waterfall.unit || "万元")} (${pct}%)</div>`;
          tip.style.left = `${Math.min(rect.width - 170, Math.max(8, e.clientX - rect.left + 12))}px`;
          tip.style.top = `${Math.max(6, e.clientY - rect.top - 40)}px`;
        });
        el.addEventListener("mouseleave", () => {
          if (tip) tip.hidden = true;
        });
      });
    };

    draw();
    container.querySelector("[data-wf-png]")?.addEventListener("click", () => window.PowerPlanUI?.exportSvgAsPng?.(svg, "lcoe_waterfall.png"));
    container.querySelector("[data-wf-svg]")?.addEventListener("click", () => window.PowerPlanUI?.exportSvgAsSvg?.(svg, "lcoe_waterfall.svg"));
    return { redraw: draw };
  }

  /** 渲染多方案对比 5 维归一化雷达图 + 实时权重决策评分器 */
  function renderComparisonRadar(container, items, tables) {
    if (!container) return;
    if (!Array.isArray(items) || !items.length) {
      container.innerHTML = `<div class="empty-summary">${escapeHtml(tr("请至少选择 2 个方案进行多维综合评估"))}</div>`;
      return;
    }

    const extract = (rows, keywords, item) => {
      const colKeys = [item.label, `${item.scheme} / ${item.result_display_name}`, item.id].filter(Boolean);
      for (const kw of keywords) {
        const hit = (rows || []).find((r) => String(r["指标"] || "").includes(kw));
        if (!hit) continue;
        for (const colKey of colKeys) {
          if (hit[colKey] !== undefined && hit[colKey] !== "" && hit[colKey] !== "-") {
            const num = parseFloat(String(hit[colKey]).replace(/,/g, "").replace(/%/g, "").trim());
            if (Number.isFinite(num)) return { val: num, unit: String(hit["单位"] || "") };
          }
        }
      }
      return null;
    };

    const dims = [
      { key: "econ", label: tr("经济性 (低LCOE)"), weight: 30, higherBetter: false },
      { key: "green", label: tr("绿电占比"), weight: 25, higherBetter: true },
      { key: "curtail", label: tr("新能源消纳"), weight: 15, higherBetter: true },
      { key: "freq", label: tr("频率安全裕度"), weight: 15, higherBetter: true },
      { key: "rel", label: tr("供电可靠率"), weight: 15, higherBetter: true },
    ];

    const rawRecords = items.map((it) => {
      const lcoe = extract(tables?.energy, ["综合度电成本", "度电成本"], it);
      const green = extract(tables?.energy, ["绿电占比", "绿色电量占比", "新能源占比"], it);
      const curt = extract(tables?.energy, ["新能源弃电率", "弃电率"], it);
      const fMin = extract(tables?.safety, ["最低频率"], it);
      const fMax = extract(tables?.safety, ["最高频率"], it);
      const esr = extract(tables?.reliability, ["供电可靠率"], it);

      const greenPct = green ? (green.val <= 1 && !green.unit.includes("%") ? green.val * 100 : green.val) : null;
      const curtPct = curt ? (curt.val <= 1 && !curt.unit.includes("%") ? curt.val * 100 : curt.val) : null;
      const absorbPct = curtPct != null ? Math.max(0, 100 - curtPct) : null;
      const freqMargin = fMin && fMax ? Math.max(0, 1 - Math.max(Math.abs(50 - fMin.val), Math.abs(fMax.val - 50)) / 1.0) * 100 : null;

      return {
        id: it.id,
        label: it.label || `${it.scheme} / ${it.result_display_name}`,
        stale: Boolean(it.stale),
        raw: {
          econ: lcoe ? lcoe.val : null,
          green: greenPct,
          curtail: absorbPct,
          freq: freqMargin,
          rel: esr ? esr.val : null,
        },
      };
    });

    // 归一化到 20..100 分区间，避免单维度压成零点
    const normalized = rawRecords.map((rec) => ({ ...rec, scores: {} }));
    dims.forEach((d) => {
      const vals = rawRecords.map((r) => r.raw[d.key]).filter((v) => Number.isFinite(v));
      if (!vals.length) {
        normalized.forEach((r) => { r.scores[d.key] = 60; });
        return;
      }
      const minV = Math.min(...vals);
      const maxV = Math.max(...vals);
      const span = maxV - minV;
      normalized.forEach((r) => {
        const v = r.raw[d.key];
        if (!Number.isFinite(v)) {
          r.scores[d.key] = 50;
        } else if (span < 1e-6) {
          r.scores[d.key] = 85;
        } else {
          const ratio = d.higherBetter ? (v - minV) / span : (maxV - v) / span;
          r.scores[d.key] = Math.round((30 + ratio * 70) * 10) / 10;
        }
      });
    });

    container.innerHTML = `
      <div class="insight-card-head">
        <div class="insight-card-title">${escapeHtml(tr("多方案 5 维雷达图与加权推荐"))}</div>
        <div class="insight-card-controls">
          <button type="button" class="insight-export-btn" data-radar-png>PNG</button>
          <button type="button" class="insight-export-btn" data-radar-svg>SVG</button>
        </div>
      </div>
      <div class="comparison-radar-layout">
        <div class="comparison-radar-canvas-wrap">
          <svg class="comparison-radar-svg" role="img" aria-label="多方案五维雷达图"></svg>
        </div>
        <div class="comparison-radar-controls">
          <div class="radar-weights" data-radar-weights>
            ${dims
              .map(
                (d, idx) => `
              <label class="radar-weight-row">
                <span>${escapeHtml(d.label)}</span>
                <input type="range" min="0" max="60" step="5" value="${d.weight}" data-weight-idx="${idx}">
                <em data-weight-val="${idx}">${d.weight}%</em>
              </label>`,
              )
              .join("")}
          </div>
          <div class="radar-ranking" data-radar-ranking></div>
        </div>
      </div>
    `;

    const svg = container.querySelector(".comparison-radar-svg");
    const rankEl = container.querySelector("[data-radar-ranking]");

    const draw = () => {
      const pal = getPalette();
      const svgW = 340;
      const svgH = 268;
      const cx = svgW / 2;
      const cy = svgH / 2 + 4;
      const maxR = 82;
      svg.setAttribute("viewBox", `0 0 ${svgW} ${svgH}`);

      const angleAt = (idx) => -Math.PI / 2 + (idx * 2 * Math.PI) / dims.length;
      const ptAt = (idx, pct) => {
        const r = (Math.max(0, Math.min(100, pct)) / 100) * maxR;
        const a = angleAt(idx);
        return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
      };

      const rings = [25, 50, 75, 100]
        .map((lv) => {
          const pts = dims.map((_, i) => ptAt(i, lv).map((v) => v.toFixed(1)).join(",")).join(" ");
          return `<polygon points="${pts}" fill="none" stroke="${pal.grid}" stroke-dasharray="${lv === 100 ? "" : "2 2"}"/>`;
        })
        .join("");

      const spokes = dims
        .map((d, i) => {
          const [x, y] = ptAt(i, 100);
          const [lx, ly] = ptAt(i, 120);
          const anchor = Math.abs(lx - cx) < 10 ? "middle" : lx > cx ? "start" : "end";
          return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${pal.grid}"/>
                  <text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" text-anchor="${anchor}" fill="${pal.text}" font-size="10.5">${escapeHtml(d.label)}</text>`;
        })
        .join("");

      const totalW = Math.max(1, dims.reduce((acc, d) => acc + d.weight, 0));
      const ranked = normalized
        .map((rec, idx) => {
          const totalScore = dims.reduce((acc, d) => acc + (rec.scores[d.key] || 0) * (d.weight / totalW), 0);
          return { ...rec, color: pal.series[idx % pal.series.length], totalScore: Math.round(totalScore * 10) / 10 };
        })
        .sort((a, b) => b.totalScore - a.totalScore);

      const polygons = ranked
        .map((rec) => {
          const pts = dims.map((d, i) => ptAt(i, rec.scores[d.key]).map((v) => v.toFixed(1)).join(",")).join(" ");
          return `<polygon points="${pts}" fill="${rec.color}" fill-opacity="0.18" stroke="${rec.color}" stroke-width="2"/>`;
        })
        .join("");

      svg.innerHTML = `${rings}${spokes}${polygons}`;

      if (rankEl) {
        rankEl.innerHTML = ranked
          .map(
            (rec, idx) => `
          <div class="radar-rank-item${idx === 0 ? " is-top" : ""}">
            <span class="radar-rank-dot" style="background:${rec.color}"></span>
            <span class="radar-rank-name" title="${escapeHtml(rec.label)}">${escapeHtml(rec.label)}${rec.stale ? ` <em class="stale-inline-tag">${escapeHtml(tr("待重算"))}</em>` : ""}</span>
            ${idx === 0 ? `<span class="radar-rec-badge">${escapeHtml(tr("推荐"))}</span>` : ""}
            <strong class="radar-rank-score">${rec.totalScore.toFixed(1)}</strong>
          </div>`,
          )
          .join("");
      }
    };

    draw();

    container.querySelectorAll("[data-weight-idx]").forEach((slider) => {
      slider.addEventListener("input", () => {
        const idx = Number(slider.dataset.weightIdx);
        dims[idx].weight = Number(slider.value);
        const total = Math.max(1, dims.reduce((a, b) => a + b.weight, 0));
        dims.forEach((d, i) => {
          const el = container.querySelector(`[data-weight-val="${i}"]`);
          if (el) el.textContent = `${Math.round((d.weight / total) * 100)}%`;
        });
        draw();
      });
    });

    container.querySelector("[data-radar-png]")?.addEventListener("click", () => window.PowerPlanUI?.exportSvgAsPng?.(svg, "comparison_radar.png"));
    container.querySelector("[data-radar-svg]")?.addEventListener("click", () => window.PowerPlanUI?.exportSvgAsSvg?.(svg, "comparison_radar.svg"));
    return { redraw: draw };
  }

  /** 渲染敏感性分析龙卷风排序图（Tornado Chart） */
  function renderTornadoChart(svg, items, metricLabel) {
    if (!svg) return;
    const pal = getPalette();
    const width = Math.max(460, Math.round(svg.clientWidth || 860));
    const height = Math.max(240, Math.min(380, (items?.length || 1) * 44 + 78));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    if (!Array.isArray(items) || !items.length) {
      svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="${pal.text}" font-size="13">${escapeHtml(tr("需要至少 2 个已完成扫参情景才可绘制龙卷风敏感度排行"))}</text>`;
      return;
    }

    const padL = 138;
    const padR = 72;
    const padT = 30;
    const padB = 28;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const maxAbs = Math.max(
      1e-4,
      ...items.map((it) => Math.max(Math.abs(it.low_delta || 0), Math.abs(it.high_delta || 0))),
    );
    const cx = padL + plotW / 2;
    const sx = (delta) => cx + (delta / (maxAbs * 1.12)) * (plotW / 2);
    const rowH = plotH / items.length;
    const barH = Math.max(14, Math.min(26, rowH * 0.56));

    const bars = items
      .map((it, idx) => {
        const yMid = padT + rowH * idx + rowH / 2;
        const y0 = yMid - barH / 2;
        const xLow = sx(it.low_delta);
        const xHigh = sx(it.high_delta);
        const lowW = Math.max(1, cx - xLow);
        const highW = Math.max(1, xHigh - cx);
        return `
          <text x="${padL - 10}" y="${(yMid + 4).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="11.5">${escapeHtml(tr(it.label))}</text>
          <rect x="${xLow.toFixed(1)}" y="${y0.toFixed(1)}" width="${lowW.toFixed(1)}" height="${barH.toFixed(1)}" rx="3" fill="${pal.wind}" opacity="0.88"/>
          <rect x="${cx.toFixed(1)}" y="${y0.toFixed(1)}" width="${highW.toFixed(1)}" height="${barH.toFixed(1)}" rx="3" fill="${pal.diesel}" opacity="0.88"/>
          <text x="${(xLow - 5).toFixed(1)}" y="${(yMid + 3.5).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="10">${formatCompact(it.min)}</text>
          <text x="${(xHigh + 5).toFixed(1)}" y="${(yMid + 3.5).toFixed(1)}" text-anchor="start" fill="${pal.text}" font-size="10">${formatCompact(it.max)}</text>
          <text x="${width - 8}" y="${(yMid + 3.5).toFixed(1)}" text-anchor="end" fill="${pal.text}" font-size="10">Δ${formatCompact(it.span)}</text>
        `;
      })
      .join("");

    svg.innerHTML = `
      <text x="${padL}" y="17" fill="${pal.text}" font-size="11.5">${escapeHtml(tr("龙卷风敏感度排行"))} · ${escapeHtml(metricLabel || "")}</text>
      <text x="${cx.toFixed(1)}" y="${height - 8}" text-anchor="middle" fill="${pal.text}" font-size="10.5">${escapeHtml(tr("基准值 (Δ = 0)"))}</text>
      <line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${padT - 4}" y2="${padT + plotH + 4}" stroke="${pal.axis}" stroke-width="1.5"/>
      ${bars}
    `;
  }

  /** 统一渲染「工程洞察」完整四联视图（热力图 + 典型日 + 桑基图 + LCOE 瀑布） */
  async function loadAndRenderInsightsPanel(container, { scheme, filename = "", slot = "insights-panel" } = {}) {
    if (!container) return;
    if (!scheme) {
      container.innerHTML = `<div class="empty-summary">${escapeHtml(tr("请先选择已有求解结果的方案"))}</div>`;
      return;
    }
    window.PowerPlanUI?.renderSkeleton?.(container, "cards");
    try {
      const qs = new URLSearchParams({ scheme, ...(filename ? { filename } : {}) }).toString();
      const data = await (window.PowerPlanUI?.fetchJson
        ? window.PowerPlanUI.fetchJson(`/api/analysis/insights?${qs}`, { slot, ttlMs: 20000 })
        : fetch(`/api/analysis/insights?${qs}`).then((r) => r.json()));
      if (!data || !data.ok) {
        container.innerHTML = `<div class="empty-summary">${escapeHtml(data?.message || tr("当前方案尚无可用于工程洞察的结果数据"))}</div>`;
        return;
      }
      container.innerHTML = `
        <div class="insights-grid">
          <section class="insight-card insight-card-wide" data-insight-heatmap></section>
          <section class="insight-card insight-card-wide" data-insight-typical></section>
          <section class="insight-card" data-insight-sankey></section>
          <section class="insight-card" data-insight-waterfall></section>
        </div>
      `;
      const hm = renderHeatmap365x24(container.querySelector("[data-insight-heatmap]"), data.heatmaps);
      const td = renderTypicalDayStack(container.querySelector("[data-insight-typical]"), data.typical_days);
      const sk = renderEnergySankey(container.querySelector("[data-insight-sankey]"), data.sankey);
      const wf = renderLcoeWaterfall(container.querySelector("[data-insight-waterfall]"), data.lcoe_waterfall);

      const redrawAll = () => {
        try { hm?.redraw?.(); } catch (_) {}
        try { td?.redraw?.(); } catch (_) {}
        try { sk?.redraw?.(); } catch (_) {}
        try { wf?.redraw?.(); } catch (_) {}
      };
      if (container._insightRedrawHandler) {
        window.removeEventListener("powerplan:themechange", container._insightRedrawHandler);
        window.removeEventListener("resize", container._insightRedrawHandler);
      }
      container._insightRedrawHandler = redrawAll;
      window.addEventListener("powerplan:themechange", redrawAll);
      window.addEventListener("resize", redrawAll);
      if (window.PowerPlanI18n) {
        window.PowerPlanI18n.translate(container, window.PowerPlanI18n.currentLanguage());
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
      container.innerHTML = `<div class="empty-summary">${escapeHtml(err?.message || tr("当前方案尚无可用于工程洞察的结果数据"))}</div>`;
    }
  }

  window.PowerPlanCharts = {
    niceTicks,
    formatCompact,
    drawHiDpiPolylines,
    renderHeatmap365x24,
    renderTypicalDayStack,
    renderEnergySankey,
    renderLcoeWaterfall,
    renderComparisonRadar,
    renderTornadoChart,
    loadAndRenderInsightsPanel,
  };
})();
