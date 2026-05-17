#!/usr/bin/env python3
"""Evaluation entry point implemented as a fixed-quantity planning MILP."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any, Callable

import planning_store

from milp_solver import solve_milp


LogSink = Callable[[dict[str, Any]], None]

ENERGY_AGGREGATE_FIELDS = [
    "load_energy",
    "diesel_energy",
    "wind_energy",
    "pv_energy",
    "storage_charge_energy",
    "storage_discharge_energy",
    "hydrogen_production_energy",
    "hydrogen_storage_increase",
    "hydrogen_storage_decrease",
    "fuel_cell_energy",
    "wind_available_energy",
    "pv_available_energy",
    "renewable_available_energy",
    "renewable_energy",
    "wind_curtailed_energy",
    "pv_curtailed_energy",
    "curtailed_energy",
    "unmet_load_energy",
]

EVALUATION_DEVICE_SPECS: dict[str, dict[str, str]] = {
    "diesel_generators": {"label": "柴发", "capacity_field": "capacity"},
    "wind_turbines": {"label": "风机", "capacity_field": "capacity"},
    "photovoltaics": {"label": "光伏", "capacity_field": "capacity"},
    "storage_pcs": {"label": "储能PCS", "capacity_field": "power_capacity"},
    "storage_battery_packs": {"label": "储能电池组", "capacity_field": "battery_capacity"},
    "hydrogen_electrolyzers": {"label": "电制氢", "capacity_field": "power_capacity"},
    "hydrogen_tanks": {"label": "储氢罐", "capacity_field": "hydrogen_tank_capacity"},
    "fuel_cells": {"label": "燃料电池", "capacity_field": "power_capacity"},
}


def run_estimation(
    scheme_payload: dict[str, Any],
    planning_result_rows: list[dict[str, Any]],
    log: LogSink | None = None,
) -> dict[str, Any]:
    """Evaluate the selected result by fixing quantities in the planning MILP."""

    # The planning optimizer owns the shared objective and constraints:
    # construction cost, diesel consumption, load shedding, unit commitment,
    # storage, hydrogen, curtailment, disturbance and frequency-security hooks.
    # Evaluation only fixes every quantity bound to the selected result file.
    time_series = scheme_payload.get("time_series") if isinstance(scheme_payload.get("time_series"), list) else []
    if len(time_series) != 8760:
        raise ValueError(f"评估调度需要8760点时序数据，当前为{len(time_series)}")

    emit(log, "info", "开始8760点混合整数线性优化调度（固定建设台数）", 0)
    fixed_payload = fixed_quantity_payload(scheme_payload, planning_result_rows)
    emit(log, "info", "已将当前规划结果转换为固定台数规划问题，复用规划求解模型", 8)

    import plan_optimizer

    result = plan_optimizer.run_optimization(fixed_payload, log=log, allow_direct_result=False)
    emit(log, "ok", "8760点优化调度完成", 100)
    return result


def annual_energy_rows(totals: dict[str, float], green_ratio: float, curtailed_ratio: float) -> list[dict[str, Any]]:
    # Annual rows are reused by planning, evaluation and result comparison.
    return [
        {"指标": "负荷总电量", "数值": totals["load_energy"], "单位": "kWh"},
        {"指标": "柴发总发电量", "数值": totals["diesel_energy"], "单位": "kWh"},
        {"指标": "风机总发电量", "数值": totals["wind_energy"], "单位": "kWh"},
        {"指标": "光伏总发电量", "数值": totals["pv_energy"], "单位": "kWh"},
        {"指标": "电储能总储电量", "数值": totals["storage_charge_energy"], "单位": "kWh"},
        {"指标": "电储能总放电量", "数值": totals["storage_discharge_energy"], "单位": "kWh"},
        {"指标": "电制氢总用电量", "数值": totals["hydrogen_production_energy"], "单位": "kWh"},
        {"指标": "氢储总增加量", "数值": totals["hydrogen_storage_increase"], "单位": "Nm3"},
        {"指标": "氢储总消耗量", "数值": totals["hydrogen_storage_decrease"], "单位": "Nm3"},
        {"指标": "燃料电池总发电量", "数值": totals["fuel_cell_energy"], "单位": "kWh"},
        {"指标": "风力最大可发电量", "数值": totals["wind_available_energy"], "单位": "kWh"},
        {"指标": "光伏最大可发电量", "数值": totals["pv_available_energy"], "单位": "kWh"},
        {"指标": "新能源最大可发电量", "数值": totals["renewable_available_energy"], "单位": "kWh"},
        {"指标": "新能源实发电量", "数值": totals["renewable_energy"], "单位": "kWh"},
        {"指标": "弃风总电量", "数值": totals["wind_curtailed_energy"], "单位": "kWh"},
        {"指标": "弃光总电量", "数值": totals["pv_curtailed_energy"], "单位": "kWh"},
        {"指标": "新能源总弃电量", "数值": totals["curtailed_energy"], "单位": "kWh"},
        {"指标": "切负荷总电量", "数值": totals["unmet_load_energy"], "单位": "kWh"},
        {"指标": "新能源占比", "数值": round(green_ratio, 2), "单位": "%"},
        {"指标": "新能源弃电率", "数值": round(curtailed_ratio, 2), "单位": "%"},
        {"指标": "绿电占比", "数值": round(green_ratio, 2), "单位": "%"},
    ]


def aggregate_daily(dispatch_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Daily statistics are derived from hourly dispatch rows, preserving the
    # same values that are shown in the curve panel.
    daily = []
    for day_index in range(365):
        rows = dispatch_rows[day_index * 24 : (day_index + 1) * 24]
        previous_hydrogen_storage = numeric(dispatch_rows[day_index * 24 - 1].get("hydrogen_storage"), 0.0) if day_index > 0 else 0.0
        hydrogen_storage_increase = sum(positive_delta(rows, "hydrogen_storage", previous_hydrogen_storage))
        hydrogen_storage_decrease = sum(negative_delta(rows, "hydrogen_storage", previous_hydrogen_storage))
        daily_row = {
            "day": day_index + 1,
            "load_energy": round(sum_numeric(rows, "load"), 4),
            "diesel_energy": round(sum_numeric(rows, "diesel_power"), 4),
            "wind_energy": round(sum_numeric(rows, "wind_power"), 4),
            "pv_energy": round(sum_numeric(rows, "pv_power"), 4),
            "hydrogen_energy": round(sum_numeric(rows, "fuel_cell_power"), 4),
            "fuel_cell_energy": round(sum_numeric(rows, "fuel_cell_power"), 4),
            "storage_charge_energy": round(sum_numeric(rows, "storage_charge"), 4),
            "storage_discharge_energy": round(sum_numeric(rows, "storage_discharge"), 4),
            "hydrogen_production_energy": round(sum_numeric(rows, "hydrogen_production_power"), 4),
            "hydrogen_storage_increase": round(hydrogen_storage_increase, 4),
            "hydrogen_storage_decrease": round(hydrogen_storage_decrease, 4),
            "wind_available_energy": round(sum_numeric(rows, "wind_available"), 4),
            "pv_available_energy": round(sum_numeric(rows, "pv_available"), 4),
            "renewable_available_energy": round(sum(numeric(row.get("renewable_available"), numeric(row.get("wind_available"), 0.0) + numeric(row.get("pv_available"), 0.0)) for row in rows), 4),
            "renewable_energy": round(sum(numeric(row.get("wind_power"), 0.0) + numeric(row.get("pv_power"), 0.0) for row in rows), 4),
            "wind_curtailed_energy": round(sum_numeric(rows, "wind_curtailed_power"), 4),
            "pv_curtailed_energy": round(sum_numeric(rows, "pv_curtailed_power"), 4),
            "curtailed_energy": round(sum_numeric(rows, "curtailed_power"), 4),
            "unmet_load_energy": round(sum_numeric(rows, "unmet_load"), 4),
            "unmet_load": round(sum_numeric(rows, "unmet_load"), 4),
        }
        add_energy_ratios(daily_row)
        daily.append(daily_row)
    return daily


def aggregate_monthly(daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Monthly values are built from daily rollups to keep aggregation order
    # deterministic and easy to audit.
    month_lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    result = []
    start = 0
    for month, days in enumerate(month_lengths, start=1):
        rows = daily_rows[start : start + days]
        monthly_row = {"month": month, **{field: round(sum(numeric(row.get(field), 0.0) for row in rows), 4) for field in ENERGY_AGGREGATE_FIELDS}}
        add_energy_ratios(monthly_row)
        result.append(monthly_row)
        start += days
    return result


def positive_delta(rows: list[dict[str, Any]], field: str, initial_value: float | None = None) -> list[float]:
    values = [numeric(row.get(field), 0.0) for row in rows]
    if initial_value is not None:
        values = [initial_value, *values]
    return [max(0.0, values[index] - values[index - 1]) for index in range(1, len(values))]


def negative_delta(rows: list[dict[str, Any]], field: str, initial_value: float | None = None) -> list[float]:
    values = [numeric(row.get(field), 0.0) for row in rows]
    if initial_value is not None:
        values = [initial_value, *values]
    return [max(0.0, values[index - 1] - values[index]) for index in range(1, len(values))]


def sum_numeric(rows: list[dict[str, Any]], field: str) -> float:
    return sum(numeric(row.get(field), 0.0) for row in rows)


def percent(part: float, total: float) -> float:
    return part / total * 100 if total else 0.0


def add_energy_ratios(row: dict[str, Any]) -> None:
    row["renewable_ratio"] = round(percent(numeric(row.get("renewable_energy"), 0.0), numeric(row.get("load_energy"), 0.0)), 4)
    row["renewable_curtailed_rate"] = round(percent(numeric(row.get("curtailed_energy"), 0.0), numeric(row.get("renewable_available_energy"), 0.0)), 4)


def result_row_device_key(row: dict[str, Any]) -> str:
    device_type = str(row.get("设备类型", "") or "")
    name = str(row.get("名称", "") or "")
    unit = str(row.get("单位", "") or "")
    text = f"{device_type} {name}"
    if "燃料电池" in text:
        return "fuel_cells"
    if "储能PCS" in text or "电储PCS" in text or "PCS" in text:
        return "storage_pcs"
    if "储能" in text or "电储" in text or "电池" in text:
        return "storage_battery_packs" if "kWh" in unit or "电池" in text else "storage_pcs"
    if "电制氢" in text or "制氢" in text:
        return "hydrogen_electrolyzers"
    if "储氢" in text:
        return "hydrogen_tanks"
    if "柴" in text:
        return "diesel_generators"
    if "风" in text:
        return "wind_turbines"
    if "光" in text:
        return "photovoltaics"
    return ""


def normalized_text(value: Any) -> str:
    return str(value or "").strip()


def non_negative_int(value: Any, default: int = 0) -> int:
    number = numeric(value, float(default))
    return max(0, int(round(number)))


def fixed_quantity_payload(scheme_payload: dict[str, Any], planning_result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a deep-copied scheme payload with every device quantity fixed."""

    payload = copy.deepcopy(scheme_payload)
    payload["_optimization_problem_name"] = "方案评估"
    payload["_diesel_objective_price"] = max(1.0, numeric(first_row(payload.get("planning_parameters")).get("diesel_price"), 0.0))
    row_positions: dict[str, int] = {}
    counts_by_position: dict[tuple[str, int], int] = {}

    for result_row in planning_result_rows or []:
        if not isinstance(result_row, dict):
            continue
        key = result_row_device_key(result_row)
        if not key:
            continue
        row_index = matching_device_parameter_index(payload, key, result_row, row_positions)
        if row_index is None:
            continue
        count = non_negative_int(result_row.get("设计台数"), 0)
        counts_by_position[(key, row_index)] = count
        if key == "storage_battery_packs" and "PCS" not in str(result_row.get("设备类型", "")):
            mirror_storage_battery_count_to_pcs(payload, row_index, count, counts_by_position)

    for key in EVALUATION_DEVICE_SPECS:
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            count = counts_by_position.get((key, index), 0)
            row["quantity_lower"] = count
            row["quantity_upper"] = count
    return payload


def mirror_storage_battery_count_to_pcs(
    payload: dict[str, Any],
    battery_index: int,
    count: int,
    counts_by_position: dict[tuple[str, int], int],
) -> None:
    """Treat legacy '储能' rows as both battery and PCS when no PCS row exists."""

    pcs_rows = payload.get("storage_pcs") if isinstance(payload.get("storage_pcs"), list) else []
    if ("storage_pcs", battery_index) in counts_by_position:
        return
    if not pcs_rows:
        return
    counts_by_position[("storage_pcs", min(battery_index, len(pcs_rows) - 1))] = count


def matching_device_parameter_index(
    scheme_payload: dict[str, Any],
    key: str,
    result_row: dict[str, Any],
    row_positions: dict[str, int],
) -> int | None:
    rows = [row for row in scheme_payload.get(key, []) if isinstance(row, dict)]
    if not rows:
        return None
    position = row_positions.get(key, 0)
    row_positions[key] = position + 1
    result_name = normalized_text(result_row.get("名称"))
    if result_name:
        for index, row in enumerate(rows):
            if normalized_text(row.get("name")) == result_name:
                return index
    capacity = numeric(result_row.get("单台容量"), math.nan)
    capacity_field = EVALUATION_DEVICE_SPECS[key]["capacity_field"]
    if not math.isnan(capacity):
        for index, row in enumerate(rows):
            if abs(numeric(row.get(capacity_field), -1.0) - capacity) <= 1e-6:
                return index
    return min(position, len(rows) - 1)


def build_dispatch_model(scheme_payload: dict[str, Any], planning_result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Backward-compatible entry used by tests and scripts: the returned object
    # is the planning model with quantity bounds fixed to the result rows.
    import plan_optimizer

    payload = fixed_quantity_payload(scheme_payload, planning_result_rows)
    return plan_optimizer.build_planning_model(payload, payload["time_series"])


def solve_dispatch_model(model: dict[str, Any], log: LogSink | None = None) -> list[dict[str, Any]]:
    """Solve a fixed-quantity planning model and return hourly dispatch rows."""

    if "device_rows" not in model:
        raise ValueError("方案评估只支持固定台数规划MILP模型")

    import plan_optimizer

    original_solve_milp = plan_optimizer.solve_milp
    try:
        # Keep this indirection so tests and scripts that patch
        # estimate.solve_milp still exercise the shared planning model.
        plan_optimizer.solve_milp = solve_milp
        solution = plan_optimizer.solve_planning_model(model, log)
    finally:
        plan_optimizer.solve_milp = original_solve_milp
    return plan_optimizer.dispatch_rows_from_solution(model, solution)


def capacities_from_planning_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    # Result files store planning output as display rows; this function maps
    # those rows back to aggregate capacities for logs and comparison views.
    capacities = {
        "diesel_capacity": 0.0,
        "wind_capacity": 0.0,
        "pv_capacity": 0.0,
        "storage_power_capacity": 0.0,
        "storage_energy_capacity": 0.0,
        "electrolyzer_power_capacity": 0.0,
        "hydrogen_tank_capacity": 0.0,
        "fuel_cell_power_capacity": 0.0,
    }
    for row in rows or []:
        device_type = str(row.get("设备类型") or row.get("名称") or "")
        total = planning_row_total_capacity(row)
        if "柴" in device_type:
            capacities["diesel_capacity"] += total
        elif "风" in device_type:
            capacities["wind_capacity"] += total
        elif "光" in device_type:
            capacities["pv_capacity"] += total
        elif "储能PCS" in device_type or "电储PCS" in device_type or ("PCS" in device_type and "储" in device_type):
            capacities["storage_power_capacity"] += total
        elif "燃料电池" in device_type:
            capacities["fuel_cell_power_capacity"] += total
        elif "电池" in device_type or "储能" in device_type or "电储" in device_type:
            capacities["storage_energy_capacity"] += total
        elif "电制氢" in device_type or "制氢" in device_type:
            capacities["electrolyzer_power_capacity"] += total
        elif "储氢" in device_type:
            capacities["hydrogen_tank_capacity"] += total
    if capacities["storage_power_capacity"] <= 0 and capacities["storage_energy_capacity"] > 0:
        capacities["storage_power_capacity"] = capacities["storage_energy_capacity"]
    return capacities


def planning_row_total_capacity(row: dict[str, Any]) -> float:
    if "设计台数" in row and "单台容量" in row:
        return numeric(row.get("设计台数"), 0) * numeric(row.get("单台容量"), 0)
    return numeric(row.get("总容量"), 0)


def wind_generation(wind_speed: float, capacity: float, params: dict[str, Any]) -> float:
    if capacity <= 0:
        return 0.0
    cut_in = numeric(params.get("cut_in_wind_speed"), 3.0)
    cut_out = numeric(params.get("cut_out_wind_speed"), 25.0)
    rated = max(cut_in + 0.1, numeric(params.get("rated_wind_speed"), 12.0))
    if wind_speed < cut_in or wind_speed >= cut_out:
        return 0.0
    if wind_speed >= rated:
        return capacity
    return capacity * ((wind_speed - cut_in) / (rated - cut_in)) ** 3


def pv_generation(irradiance: float, capacity: float, params: dict[str, Any] | None = None) -> float:
    if capacity <= 0:
        return 0.0
    return max(0.0, min(capacity, capacity * max(0.0, irradiance) / 1000.0))


def first_row(rows: Any) -> dict[str, Any]:
    if isinstance(rows, dict):
        return rows
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def numeric(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def truthy_flag(value: Any, default: bool = False) -> bool:
    if value in ("", None):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def emit(log: LogSink | None, level: str, message: str, progress: int | None = None) -> None:
    if not log:
        return
    event = {"level": level, "message": message}
    if progress is not None:
        event["progress"] = progress
    log(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fixed-quantity planning MILP evaluation.")
    parser.add_argument("scheme_workbook", type=Path)
    parser.add_argument("planning_result_json", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    payload = planning_store.read_workbook(args.scheme_workbook, args.scheme_workbook.parent.name)
    planning_rows = json.loads(args.planning_result_json.read_text(encoding="utf-8"))
    result = run_estimation(payload, planning_rows, log=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    args.output_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
