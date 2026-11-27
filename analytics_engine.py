"""工程洞察、陈旧结果检测、自动诊断结论、敏感性龙卷风分析与 SSE 事件总线模块。"""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from file_cache import FileCache

# 工程洞察内存缓存（按结果文件签名自动失效，可被管理员一键清理）
INSIGHTS_MEMORY_CACHE = FileCache("analytics_insights", max_entries=32)

# 方案结果类文件后缀，不计入“输入参数文件最新修改时间”
_RESULT_FILE_MARKERS = (
    "_results.xlsx",
    "_results.curves.sqlite3",
    "_results.insights.npz",
    "_curves.xlsx",
    "_frequency.xlsx",
    "_reliability.json",
    "_reliability_results.xlsx",
)


class EventBroker:
    """线程安全的轻量级 SSE 事件总线。"""

    def __init__(self, max_subscribers: int = 64) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[tuple[str, dict[str, Any]]]] = set()
        self._max_subscribers = max(4, int(max_subscribers))
        self._seq = 0

    def subscribe(self) -> queue.Queue[tuple[str, dict[str, Any]]]:
        q: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=64)
        with self._lock:
            if len(self._subscribers) >= self._max_subscribers:
                # 丢弃最早的空闲订阅防止内存增长
                oldest = next(iter(self._subscribers))
                self._subscribers.discard(oldest)
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[tuple[str, dict[str, Any]]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            msg = (str(event_name or "message"), {"seq": self._seq, "ts": int(time.time() * 1000), **(payload or {})})
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(msg)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass


EVENT_BROKER = EventBroker()


def _format_ts(ts: float | None) -> str:
    if not ts or ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _is_input_config_file(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".") or name.startswith("~$"):
        return False
    for marker in _RESULT_FILE_MARKERS:
        if name.endswith(marker):
            return False
    if name.endswith(".sqlite3") or name.endswith(".npz") or name.endswith(".log"):
        return False
    return path.suffix.lower() in {".csv", ".json", ".xlsx"}


def compute_scheme_input_mtime(scheme_dir: Path) -> float:
    """扫描方案目录下输入参数/时序文件的最新修改时间戳。"""
    if not scheme_dir or not scheme_dir.exists() or not scheme_dir.is_dir():
        return 0.0
    latest = 0.0
    try:
        for child in scheme_dir.iterdir():
            if not child.is_file():
                continue
            if not _is_input_config_file(child):
                continue
            try:
                mt = child.stat().st_mtime
                if mt > latest:
                    latest = mt
            except OSError:
                continue
    except OSError:
        return 0.0
    return latest


def build_stale_info(scheme_dir: Path, artifact_path: Path | None) -> dict[str, Any]:
    """比对方案参数与结果文件修改时间，返回陈旧结果状态信息。"""
    input_mtime = compute_scheme_input_mtime(scheme_dir)
    if not artifact_path or not artifact_path.exists():
        return {
            "is_stale": False,
            "scheme_updated_at": _format_ts(input_mtime),
            "result_updated_at": "",
            "reason": "",
        }
    try:
        result_mtime = artifact_path.stat().st_mtime
    except OSError:
        result_mtime = 0.0
    # 留 1.5 秒文件系统时间戳容差，避免同一次求解写入误报
    is_stale = bool(input_mtime > 0 and result_mtime > 0 and (input_mtime - result_mtime) > 1.5)
    reason = ""
    if is_stale:
        reason = f"方案参数于 {_format_ts(input_mtime)} 更新，晚于当前结果（{_format_ts(result_mtime)}），建议重新计算"
    return {
        "is_stale": is_stale,
        "scheme_updated_at": _format_ts(input_mtime),
        "result_updated_at": _format_ts(result_mtime),
        "reason": reason,
    }


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        num = float(val)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def _lookup_metric(rows: list[dict], keywords: list[str]) -> tuple[float | None, str]:
    for kw in keywords:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("指标") or row.get("label") or "").strip()
            if kw in label:
                val = _to_float(row.get("数值") if "数值" in row else row.get("value"), float("nan"))
                if math.isfinite(val):
                    unit = str(row.get("单位") or row.get("unit") or "").strip()
                    return val, unit
    return None, ""


def insights_npz_path(result_path: Path) -> Path:
    return result_path.with_suffix(".insights.npz")


def _build_heatmaps_and_typical_days(hourly_rows: list[dict]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float]]:
    """使用 NumPy 向量化构造 365x24 热力图矩阵与 3 个典型日 24h 堆叠数据。"""
    n = len(hourly_rows)
    if n < 24:
        return {}, [], {}

    total_hours = min(n, 8760)
    days = max(1, total_hours // 24)
    used = days * 24

    def col(keys: tuple[str, ...]) -> np.ndarray:
        arr = np.zeros(used, dtype=np.float32)
        for i in range(used):
            row = hourly_rows[i]
            if not isinstance(row, dict):
                continue
            for k in keys:
                if k in row and row[k] not in ("", None):
                    arr[i] = _to_float(row[k], 0.0)
                    break
        return arr

    load = col(("load", "负荷"))
    wind = col(("wind_power", "风电出力"))
    pv = col(("pv_power", "光伏出力"))
    diesel = col(("diesel_power", "柴发出力"))
    curtailed = col(("curtailed_power", "弃电功率"))
    soc = col(("storage_soc", "储能SOC"))
    st_charge = col(("storage_charge", "储能充电功率"))
    st_discharge = col(("storage_discharge", "储能放电功率"))
    st_power = col(("storage_power", "储能功率"))
    h2_prod = col(("hydrogen_production_power", "制氢功率"))
    fc_power = col(("fuel_cell_power", "燃料电池功率"))
    unmet = col(("unmet_load", "缺电负荷"))

    # 若分项充放全为 0 但存在合并 storage_power，按正负拆分为放电/充电
    if float(np.max(np.abs(st_charge))) == 0.0 and float(np.max(np.abs(st_discharge))) == 0.0 and float(np.max(np.abs(st_power))) > 0.0:
        st_discharge = np.maximum(st_power, 0.0)
        st_charge = np.maximum(-st_power, 0.0)

    # 若 SOC 在 0..1 区间则转为百分比展示
    if float(np.max(soc)) <= 1.05 and float(np.max(soc)) > 0.0:
        soc_pct = soc * 100.0
    else:
        soc_pct = soc

    net_load = load - (wind + pv)

    def pack_matrix(arr: np.ndarray, unit: str, label: str) -> dict[str, Any]:
        mat = np.round(arr.reshape(days, 24), 2)
        return {
            "label": label,
            "unit": unit,
            "days": days,
            "min": round(float(np.min(mat)), 2),
            "max": round(float(np.max(mat)), 2),
            "avg": round(float(np.mean(mat)), 2),
            "matrix": mat.tolist(),
        }

    heatmaps = {
        "net_load": pack_matrix(net_load, "kW", "净负荷 (负荷-风光)"),
        "curtailed": pack_matrix(curtailed, "kW", "弃风弃光功率"),
        "diesel": pack_matrix(diesel, "kW", "柴发出力"),
        "soc": pack_matrix(soc_pct, "%", "储能 SOC"),
        "load": pack_matrix(load, "kW", "总用电负荷"),
    }

    # 自动甄选 3 个最具工程代表性的典型日
    daily_load = load.reshape(days, 24).sum(axis=1)
    daily_curt = curtailed.reshape(days, 24).sum(axis=1)
    daily_diesel = diesel.reshape(days, 24).sum(axis=1)
    daily_ren = (wind + pv).reshape(days, 24).sum(axis=1)

    peak_load_day = int(np.argmax(daily_load))
    max_curt_day = int(np.argmax(daily_curt)) if float(np.max(daily_curt)) > 0 else int(np.argmax(daily_ren))
    polar_night_day = int(np.argmax(daily_diesel)) if float(np.max(daily_diesel)) > 0 else int(np.argmin(daily_ren))

    # 避免 3 个典型日重合
    used_days: set[int] = set()
    picks = [
        ("peak_load", "峰值负荷日", peak_load_day, daily_load),
        ("max_curtail", "高风光/最大弃电日", max_curt_day, daily_curt if float(np.max(daily_curt)) > 0 else daily_ren),
        ("max_diesel", "极夜/最大柴发支撑日", polar_night_day, daily_diesel if float(np.max(daily_diesel)) > 0 else -daily_ren),
    ]
    typical_days: list[dict[str, Any]] = []
    for key, title, day_idx, score_vec in picks:
        if day_idx in used_days and days > 3:
            order = np.argsort(-score_vec)
            for cand in order:
                c = int(cand)
                if c not in used_days:
                    day_idx = c
                    break
        used_days.add(day_idx)
        s0 = day_idx * 24
        s1 = s0 + 24
        dt_str = str(hourly_rows[s0].get("datetime") or f"第 {day_idx + 1} 天")[:10]
        typical_days.append(
            {
                "key": key,
                "title": title,
                "day_index": day_idx + 1,
                "date": dt_str,
                "hours": [f"{h:02d}:00" for h in range(24)],
                "summary": {
                    "load_kwh": round(float(np.sum(load[s0:s1])), 1),
                    "wind_kwh": round(float(np.sum(wind[s0:s1])), 1),
                    "pv_kwh": round(float(np.sum(pv[s0:s1])), 1),
                    "diesel_kwh": round(float(np.sum(diesel[s0:s1])), 1),
                    "curtailed_kwh": round(float(np.sum(curtailed[s0:s1])), 1),
                },
                "series": {
                    "wind": np.round(wind[s0:s1], 2).tolist(),
                    "pv": np.round(pv[s0:s1], 2).tolist(),
                    "diesel": np.round(diesel[s0:s1], 2).tolist(),
                    "storage_discharge": np.round(st_discharge[s0:s1], 2).tolist(),
                    "fuel_cell": np.round(fc_power[s0:s1], 2).tolist(),
                    "storage_charge": np.round(st_charge[s0:s1], 2).tolist(),
                    "hydrogen_prod": np.round(h2_prod[s0:s1], 2).tolist(),
                    "curtailed": np.round(curtailed[s0:s1], 2).tolist(),
                    "load": np.round(load[s0:s1], 2).tolist(),
                },
            }
        )

    totals = {
        "load_kwh": float(np.sum(load)),
        "wind_kwh": float(np.sum(wind)),
        "pv_kwh": float(np.sum(pv)),
        "diesel_kwh": float(np.sum(diesel)),
        "storage_charge_kwh": float(np.sum(st_charge)),
        "storage_discharge_kwh": float(np.sum(st_discharge)),
        "hydrogen_prod_kwh": float(np.sum(h2_prod)),
        "fuel_cell_kwh": float(np.sum(fc_power)),
        "curtailed_kwh": float(np.sum(curtailed)),
        "unmet_kwh": float(np.sum(unmet)),
    }
    return heatmaps, typical_days, totals


def build_sankey_and_waterfall(
    green_table: list[dict],
    annual_rows: list[dict],
    hourly_totals: dict[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """构建年度能量流向桑基图与 LCOE 成本瀑布拆解。"""
    merged = [*(annual_rows or []), *(green_table or [])]
    ht = hourly_totals or {}

    def pick_kwh(keys: list[str], fallback_key: str) -> float:
        val, unit = _lookup_metric(merged, keys)
        if val is not None:
            if "mwh" in unit.lower() or "万kwh" in unit.lower():
                return val * (1000.0 if "mwh" in unit.lower() else 10000.0)
            return val
        return float(ht.get(fallback_key, 0.0))

    load_kwh = pick_kwh(["负荷总电量", "负荷用电量", "负荷电量"], "load_kwh")
    wind_kwh = pick_kwh(["风机总发电量", "风电总发电量", "风电发电量"], "wind_kwh")
    pv_kwh = pick_kwh(["光伏总发电量", "光伏发电量"], "pv_kwh")
    diesel_kwh = pick_kwh(["柴发总发电量", "柴油发电量", "柴发电量"], "diesel_kwh")
    st_chg = pick_kwh(["电储能总储电量", "储能充电量"], "storage_charge_kwh")
    st_dis = pick_kwh(["电储能总放电量", "储能放电量", "储能发电量"], "storage_discharge_kwh")
    h2_in = pick_kwh(["电制氢总用电量", "制氢用电量"], "hydrogen_prod_kwh")
    fc_out = pick_kwh(["燃料电池总发电量", "燃料电池发电量"], "fuel_cell_kwh")
    curt_kwh = pick_kwh(["弃电量", "新能源弃电量", "总弃电量"], "curtailed_kwh")
    if curt_kwh <= 0.0:
        wind_max = pick_kwh(["风力最大可发电量", "风电最大可发"], "")
        pv_max = pick_kwh(["光伏最大可发电量", "光伏最大可发"], "")
        if wind_max + pv_max > wind_kwh + pv_kwh:
            curt_kwh = max(0.0, (wind_max + pv_max) - (wind_kwh + pv_kwh))

    # 统一转为 MWh 便于阅读
    def mwh(v: float) -> float:
        return round(max(0.0, v) / 1000.0, 2)

    nodes = [
        {"id": "wind", "label": "风电", "col": 0, "color": "#38BDF8"},
        {"id": "pv", "label": "光伏", "col": 0, "color": "#FBBF24"},
        {"id": "diesel", "label": "柴发", "col": 0, "color": "#FB7185"},
        {"id": "bus", "label": "系统汇流", "col": 1, "color": "#818CF8"},
        {"id": "storage", "label": "电储能", "col": 1, "color": "#2DD4BF"},
        {"id": "hydrogen", "label": "氢储能", "col": 1, "color": "#A78BFA"},
        {"id": "load", "label": "站区负荷", "col": 2, "color": "#34D399"},
        {"id": "curtail", "label": "弃电/变换损耗", "col": 2, "color": "#94A3B8"},
    ]

    supply_total = max(0.001, wind_kwh + pv_kwh + diesel_kwh)
    direct_to_load = max(0.0, load_kwh - st_dis - fc_out)
    storage_loss = max(0.0, st_chg - st_dis)
    h2_loss = max(0.0, h2_in - fc_out)

    raw_links = [
        ("wind", "bus", mwh(wind_kwh)),
        ("pv", "bus", mwh(pv_kwh)),
        ("diesel", "bus", mwh(diesel_kwh)),
        ("bus", "load", mwh(min(supply_total, direct_to_load))),
        ("bus", "storage", mwh(st_chg)),
        ("bus", "hydrogen", mwh(h2_in)),
        ("storage", "load", mwh(st_dis)),
        ("hydrogen", "load", mwh(fc_out)),
        ("bus", "curtail", mwh(curt_kwh)),
        ("storage", "curtail", mwh(storage_loss)),
        ("hydrogen", "curtail", mwh(h2_loss)),
    ]
    links = [
        {"source": s, "target": t, "value": v}
        for s, t, v in raw_links
        if v > 0.01
    ]
    active_ids = {lk["source"] for lk in links} | {lk["target"] for lk in links}
    sankey = {
        "unit": "MWh",
        "nodes": [nd for nd in nodes if nd["id"] in active_ids],
        "links": links,
    }

    # LCOE / 年化成本瀑布拆解
    lcoe, lcoe_unit = _lookup_metric(merged, ["综合度电成本", "度电成本"])
    total_cost, total_unit = _lookup_metric(merged, ["年均总成本", "年总成本", "年化总成本", "总年化成本"])
    capex_cost, _ = _lookup_metric(merged, ["年均建设成本", "年化投资成本", "建设折旧成本", "初始投资年化"])
    opex_cost, _ = _lookup_metric(merged, ["年运行成本", "运行维护成本", "年运维成本"])
    fuel_cost, _ = _lookup_metric(merged, ["年柴油成本", "年燃油成本", "柴油燃料成本", "燃料成本"])

    cost_unit = total_unit or "万元"
    items: list[dict[str, Any]] = []
    if capex_cost is not None and capex_cost > 0:
        items.append({"key": "capex", "label": "年化建设投资", "value": round(capex_cost, 2), "kind": "part"})
    if fuel_cost is not None and fuel_cost > 0:
        items.append({"key": "fuel", "label": "年柴油燃料", "value": round(fuel_cost, 2), "kind": "part"})
        if opex_cost is not None and opex_cost > fuel_cost:
            items.append({"key": "om", "label": "年运维及其他", "value": round(opex_cost - fuel_cost, 2), "kind": "part"})
    elif opex_cost is not None and opex_cost > 0:
        items.append({"key": "opex", "label": "年运行与燃料", "value": round(opex_cost, 2), "kind": "part"})

    if total_cost is not None and total_cost > 0:
        parts_sum = sum(it["value"] for it in items)
        if items and abs(total_cost - parts_sum) > max(0.05, total_cost * 0.015) and total_cost > parts_sum:
            items.append({"key": "other", "label": "其他/置换惩罚", "value": round(total_cost - parts_sum, 2), "kind": "part"})
        items.append({"key": "total", "label": "年均总成本", "value": round(total_cost, 2), "kind": "total"})

    waterfall = {
        "unit": cost_unit,
        "lcoe": round(lcoe, 4) if lcoe is not None else None,
        "lcoe_unit": lcoe_unit or "元/kWh",
        "annual_load_mwh": mwh(load_kwh),
        "items": items,
    }
    return sankey, waterfall


def build_engineering_insights(
    result_path: Path,
    hourly_rows_loader: Callable[[], list[dict]],
    green_table: list[dict],
    annual_rows: list[dict],
    stale_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建并缓存结果文件的完整工程洞察（含 .npz 列存旁路缓存）。"""

    def _compute(resolved: Path) -> dict[str, Any]:
        npz_file = insights_npz_path(resolved)
        src_stat = resolved.stat()
        src_sig = f"{src_stat.st_mtime_ns}:{src_stat.st_size}"

        # 优先尝试读取 .npz 二进制旁路缓存
        if npz_file.exists():
            try:
                with np.load(npz_file, allow_pickle=False) as z:
                    if str(z["sig"].item()) == src_sig:
                        meta = json.loads(str(z["meta_json"].item()))
                        heatmaps: dict[str, Any] = {}
                        for hk, hmeta in (meta.get("heatmap_meta") or {}).items():
                            arr_key = f"hm_{hk}"
                            if arr_key in z:
                                mat = np.round(z[arr_key].astype(np.float32), 2)
                                heatmaps[hk] = {**hmeta, "matrix": mat.tolist()}
                        return {
                            "ok": True,
                            "cache_source": "npz",
                            "heatmaps": heatmaps,
                            "typical_days": meta.get("typical_days") or [],
                            "sankey": meta.get("sankey") or {},
                            "lcoe_waterfall": meta.get("lcoe_waterfall") or {},
                        }
            except Exception:
                pass

        hourly_rows = hourly_rows_loader() or []
        heatmaps, typical_days, hourly_totals = _build_heatmaps_and_typical_days(hourly_rows)
        sankey, waterfall = build_sankey_and_waterfall(green_table, annual_rows, hourly_totals)

        # 异步/轻量落盘 .npz 二进制列存旁路，加速跨重启读取
        try:
            save_kwargs: dict[str, Any] = {"sig": np.array(src_sig)}
            heatmap_meta: dict[str, Any] = {}
            for hk, hobj in heatmaps.items():
                mat = np.asarray(hobj["matrix"], dtype=np.float32)
                save_kwargs[f"hm_{hk}"] = mat
                heatmap_meta[hk] = {k: v for k, v in hobj.items() if k != "matrix"}
            meta_payload = {
                "heatmap_meta": heatmap_meta,
                "typical_days": typical_days,
                "sankey": sankey,
                "lcoe_waterfall": waterfall,
            }
            save_kwargs["meta_json"] = np.array(json.dumps(meta_payload, ensure_ascii=False))
            np.savez_compressed(npz_file, **save_kwargs)
        except Exception:
            pass

        return {
            "ok": True,
            "cache_source": "computed",
            "heatmaps": heatmaps,
            "typical_days": typical_days,
            "sankey": sankey,
            "lcoe_waterfall": waterfall,
        }

    data = INSIGHTS_MEMORY_CACHE.get(result_path, _compute, variant="insights_v1")
    return {
        **data,
        "stale_info": stale_info or {"is_stale": False},
    }


def build_diagnostic_conclusions(
    green_table: list[dict],
    safety_table: list[dict],
    reliability_rows: list[dict],
    site_summary: dict[str, Any] | None = None,
    stale_info: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """根据经济性、绿电、频率安全与供电可靠性指标自动生成工程诊断结论。"""
    conclusions: list[dict[str, str]] = []

    if stale_info and stale_info.get("is_stale"):
        conclusions.append(
            {
                "level": "warn",
                "category": "数据一致性",
                "title": "方案参数已变更，当前评估结果已过期",
                "detail": stale_info.get("reason") or "建议重新执行规划求解与评估，确保评审结论基于最新参数。",
            }
        )

    lcoe, lcoe_unit = _lookup_metric(green_table, ["综合度电成本", "度电成本"])
    green_ratio, green_unit = _lookup_metric(green_table, ["绿电占比", "绿色电量占比", "新能源供电占比", "新能源占比"])
    curtail_rate, curt_unit = _lookup_metric(green_table, ["新能源弃电率", "弃电率"])
    freq_min, _ = _lookup_metric(safety_table, ["最低频率"])
    freq_max, _ = _lookup_metric(safety_table, ["最高频率"])
    esr, _ = _lookup_metric(reliability_rows, ["供电可靠率", "ESR"])

    if green_ratio is not None:
        pct = green_ratio * 100.0 if green_ratio <= 1.0 and "%" not in green_unit else green_ratio
        if pct >= 75.0:
            conclusions.append(
                {
                    "level": "pass",
                    "category": "绿电替代",
                    "title": f"绿电占比达 {pct:.1f}%，清洁供能表现优良",
                    "detail": "新能源承担绝大部分站区负荷，显著降低极地柴油运输与储运依赖。",
                }
            )
        elif pct >= 50.0:
            conclusions.append(
                {
                    "level": "warn",
                    "category": "绿电替代",
                    "title": f"绿电占比 {pct:.1f}%，仍存在一定柴发依赖",
                    "detail": "可通过适度增配风电或长时储氢容量进一步压降燃油消耗。",
                }
            )
        else:
            conclusions.append(
                {
                    "level": "risk",
                    "category": "绿电替代",
                    "title": f"绿电占比偏低（{pct:.1f}%），系统高度依赖柴发",
                    "detail": "建议核查风光候选装机上限与绿电占比下限约束设置。",
                }
            )

    if curtail_rate is not None:
        cpct = curtail_rate * 100.0 if curtail_rate <= 1.0 and "%" not in curt_unit else curtail_rate
        if cpct > 25.0:
            conclusions.append(
                {
                    "level": "warn",
                    "category": "消纳效率",
                    "title": f"新能源弃电率偏高（{cpct:.1f}%）",
                    "detail": "建议扩大电储能或电解槽制氢消纳容量，或做储能造价敏感性扫描寻找最优配比。",
                }
            )
        elif cpct <= 15.0:
            conclusions.append(
                {
                    "level": "pass",
                    "category": "消纳效率",
                    "title": f"新能源弃电率控制在 {cpct:.1f}%，源荷匹配良好",
                    "detail": "风光装机与储能充放能力协调度较高，无明显过配浪费。",
                }
            )

    if freq_min is not None and freq_max is not None:
        if freq_min >= 49.5 and freq_max <= 50.5:
            conclusions.append(
                {
                    "level": "pass",
                    "category": "频率安全",
                    "title": f"频率波动范围 {freq_min:.2f}–{freq_max:.2f} Hz，满足 ±0.5 Hz 安全红线",
                    "detail": "构网型储能与柴发协同调频裕度充足，暂态扰动下系统稳定。",
                }
            )
        else:
            conclusions.append(
                {
                    "level": "risk",
                    "category": "频率安全",
                    "title": f"频率边界 {freq_min:.2f}–{freq_max:.2f} Hz 超出 ±0.5 Hz 常规红线",
                    "detail": "存在高频/低频越限风险，建议增大构网型储能功率配比或提高旋转备用容量。",
                }
            )

    if esr is not None:
        if esr >= 99.9:
            conclusions.append(
                {
                    "level": "pass",
                    "category": "供电可靠",
                    "title": f"供电可靠率达 {esr:.3f}%，满足高可靠运行要求",
                    "detail": "蒙特卡洛故障抽样下系统具备充分的冗余抗扰能力。",
                }
            )
        elif esr >= 99.0:
            conclusions.append(
                {
                    "level": "warn",
                    "category": "供电可靠",
                    "title": f"供电可靠率 {esr:.3f}%，接近临界水平",
                    "detail": "建议重点关注关键故障高发月份，评估增配 N-1 备用机组。",
                }
            )
        else:
            conclusions.append(
                {
                    "level": "risk",
                    "category": "供电可靠",
                    "title": f"供电可靠率偏低（{esr:.3f}%），存在停电风险",
                    "detail": "建议增加柴发备用台数或提升电/氢储能保底容量。",
                }
            )
    else:
        conclusions.append(
            {
                "level": "warn",
                "category": "供电可靠",
                "title": "尚未完成供电可靠性蒙特卡洛校核",
                "detail": "建议点击上方「可靠性校核」补充多维度故障停运风险评估。",
            }
        )

    if lcoe is not None and site_summary:
        conclusions.append(
            {
                "level": "pass" if lcoe <= 2.5 else "warn",
                "category": "经济性",
                "title": f"综合度电成本 {lcoe:.3f} {lcoe_unit or '元/kWh'}（年用电 {site_summary.get('annual_load_mwh', '—')} MWh）",
                "detail": "可结合「批量扫参」评估油价与负荷增长 ±20% 下的成本韧性。",
            }
        )

    return conclusions


def build_tornado_summary(rows: list[dict], metric_key: str = "lcoe") -> list[dict[str, Any]]:
    """汇总同一组扫参结果中各参数对目标指标的影响幅度（龙卷风图数据）。"""
    groups: dict[str, list[tuple[float | None, float, str]]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("has_result"):
            continue
        val = row.get(metric_key)
        if not isinstance(val, (int, float)) or not math.isfinite(val):
            continue
        # 从方案名推断参数组（例如 xxx_load_0p8 / xxx_wind_1p15 / xxx_diesel_1p5）
        scheme = str(row.get("scheme") or "")
        param_label = str(row.get("parameter_label") or "").strip()
        if not param_label:
            for token, lbl in (
                ("_load_", "负荷缩放系数"),
                ("_wind_", "风速缩放系数"),
                ("_solar_", "辐照缩放系数"),
                ("_diesel_", "柴油单价"),
                ("_green_", "绿电占比下限"),
                ("_stcost_", "储能造价系数"),
            ):
                if token in scheme:
                    param_label = lbl
                    break
        if not param_label:
            param_label = "综合方案组"
        pval = row.get("parameter_value")
        pnum = float(pval) if isinstance(pval, (int, float)) and math.isfinite(pval) else None
        groups.setdefault(param_label, []).append((pnum, float(val), scheme))

    items: list[dict[str, Any]] = []
    for label, entries in groups.items():
        if len(entries) < 2:
            continue
        vals = [e[1] for e in entries]
        min_v = min(vals)
        max_v = max(vals)
        # 基准值优先取 parameter_value 最接近 1.0 的点，否则取中位数
        base_entry = min(
            entries,
            key=lambda e: abs((e[0] if e[0] is not None else 1.0) - 1.0),
        )
        base_v = base_entry[1] if any(e[0] is not None for e in entries) else float(np.median(vals))
        items.append(
            {
                "label": label,
                "count": len(entries),
                "min": round(min_v, 4),
                "max": round(max_v, 4),
                "base": round(base_v, 4),
                "span": round(max_v - min_v, 4),
                "low_delta": round(min_v - base_v, 4),
                "high_delta": round(max_v - base_v, 4),
            }
        )
    items.sort(key=lambda x: x["span"], reverse=True)
    return items
