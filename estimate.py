#!/usr/bin/env python3
"""8760-hour evaluation dispatch for a fixed planning result."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import planning_store

import dispatch_milp
from milp_solver import solve_milp


LogSink = Callable[[dict[str, Any]], None]

VARIABLES = {
    "diesel_power": 0,
    "diesel_on": 1,
    "wind_power": 2,
    "pv_power": 3,
    "storage_charge": 4,
    "storage_discharge": 5,
    "storage_soc": 6,
    "electrolyzer_power": 7,
    "electrolyzer_on": 8,
    "hydrogen_storage": 9,
    "fuel_cell_power": 10,
    "curtailed_power": 11,
    "unmet_load": 12,
}
VARIABLE_COUNT = len(VARIABLES)
LOAD_SHED_PENALTY = 1_000_000.0
DIESEL_ON_PENALTY = 0.001
ELECTROLYZER_ON_PENALTY = 0.0001
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


def run_estimation(scheme_payload: dict[str, Any], planning_result_rows: list[dict[str, Any]], log: LogSink | None = None) -> dict[str, Any]:
    """Dispatch a fixed equipment plan as one 8760-hour MILP."""

    # Evaluation shares the dispatch model with planning, but all equipment
    # counts come from the selected result file instead of being optimized.
    time_series = scheme_payload.get("time_series") if isinstance(scheme_payload.get("time_series"), list) else []
    if len(time_series) != 8760:
        raise ValueError(f"评估调度需要8760点时序数据，当前为{len(time_series)}")

    emit(log, "info", "开始8760点混合整数线性优化调度", 0)
    model = build_dispatch_model(scheme_payload, planning_result_rows)
    emit(log, "info", "已建立全年联合优化模型：柴发启停、制氢启停、储能、氢储、弃电和切负荷", 10)
    dispatch_rows = direct_dispatch_rows(model, log)
    if dispatch_rows is None:
        dispatch_rows = solve_dispatch_model(model, log)
    totals = dispatch_totals(dispatch_rows, model["fuel_rate"], model["electric_to_hydrogen_efficiency"])
    totals = {key: round(value, 4) for key, value in totals.items()}
    green_ratio = totals["renewable_ratio"]
    curtailed_ratio = totals["renewable_curtailed_rate"]
    results = build_results(planning_result_rows, dispatch_rows, totals, green_ratio, curtailed_ratio)
    metrics = [
        {"label": "当前状态", "value": "已完成", "unit": ""},
        {"label": "柴油消耗", "value": totals["diesel_consumption"], "unit": "吨"},
        {"label": "柴发总电量", "value": totals["diesel_energy"], "unit": "kWh"},
        {"label": "绿电占比", "value": round(green_ratio, 2), "unit": "%"},
        {"label": "弃电率", "value": round(curtailed_ratio, 2), "unit": "%"},
    ]
    emit(log, "ok", "8760点优化调度完成", 100)
    return {
        "status": "已完成",
        "progress": 100,
        "metrics": metrics,
        "results": results,
        "dispatch_rows": dispatch_rows,
        "totals": totals,
    }


def build_results(
    planning_result_rows: list[dict[str, Any]],
    dispatch_rows: list[dict[str, Any]],
    totals: dict[str, float],
    green_ratio: float,
    curtailed_ratio: float,
) -> dict[str, Any]:
    # One evaluation run fans out into tables, disks and curve sets so the UI
    # can switch views without recomputing aggregates.
    daily = aggregate_daily(dispatch_rows)
    monthly = aggregate_monthly(daily)
    annual_rows = annual_energy_rows(totals, green_ratio, curtailed_ratio)
    return {
        "overview_tables": [
            {"title": "规划结果", "rows": planning_result_rows},
            {
                "title": "规划年指标",
                "rows": [
                    *annual_rows,
                    {"指标": "负荷总电量", "数值": totals["load_energy"], "单位": "kWh"},
                    {"指标": "柴发总电量", "数值": totals["diesel_energy"], "单位": "kWh"},
                    {"指标": "风能总电量", "数值": totals["wind_energy"], "单位": "kWh"},
                    {"指标": "光伏总电量", "数值": totals["pv_energy"], "单位": "kWh"},
                    {"指标": "电储总发电量", "数值": totals["storage_discharge_energy"], "单位": "kWh"},
                    {"指标": "电储总充电量", "数值": totals["storage_charge_energy"], "单位": "kWh"},
                    {"指标": "弃电量", "数值": totals["curtailed_energy"], "单位": "kWh"},
                    {"指标": "切负荷量", "数值": totals["unmet_load_energy"], "单位": "kWh"},
                    {"指标": "制氢总量", "数值": totals["hydrogen_production"], "单位": "Nm3"},
                    {"指标": "燃料电池发电量", "数值": totals["fuel_cell_energy"], "单位": "kWh"},
                    {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨"},
                    {"指标": "绿电占比", "数值": round(green_ratio, 2), "单位": "%"},
                ],
            },
        ],
        "overview_disks": [
            {"title": "柴油消耗", "left_label": "柴发电量", "left_value": totals["diesel_energy"], "right_label": "绿电电量", "right_value": totals["wind_energy"] + totals["pv_energy"] + totals["storage_discharge_energy"], "unit": "kWh"},
            {"title": "新能源利用", "left_label": "弃电量", "left_value": totals["curtailed_energy"], "right_label": "消纳电量", "right_value": totals["wind_energy"] + totals["pv_energy"] - totals["curtailed_energy"], "unit": "kWh"},
        ],
        "green_table": [
            *annual_rows,
            {"指标": "负荷总电量", "数值": totals["load_energy"], "单位": "kWh"},
            {"指标": "柴发总电量", "数值": totals["diesel_energy"], "单位": "kWh"},
            {"指标": "风机总发电量", "数值": totals["wind_energy"], "单位": "kWh"},
            {"指标": "光伏总发电量", "数值": totals["pv_energy"], "单位": "kWh"},
            {"指标": "电储总发电量", "数值": totals["storage_discharge_energy"], "单位": "kWh"},
            {"指标": "新能源弃电率", "数值": round(curtailed_ratio, 2), "单位": "%"},
            {"指标": "切负荷量", "数值": totals["unmet_load_energy"], "单位": "kWh"},
            {"指标": "制氢总量", "数值": totals["hydrogen_production"], "单位": "Nm3"},
            {"指标": "燃料电池发电量", "数值": totals["fuel_cell_energy"], "单位": "kWh"},
            {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨"},
        ],
        "safety_table": [
            {"指标": "最大未供负荷", "数值": max((row["unmet_load"] for row in dispatch_rows), default=0), "单位": "kW"},
            {"指标": "最低储能SOC", "数值": min((row["storage_soc"] for row in dispatch_rows), default=0), "单位": "kWh"},
            {"指标": "最高储能SOC", "数值": max((row["storage_soc"] for row in dispatch_rows), default=0), "单位": "kWh"},
            {"指标": "最低氢储量", "数值": min((row["hydrogen_storage"] for row in dispatch_rows), default=0), "单位": "Nm3"},
            {"指标": "最高氢储量", "数值": max((row["hydrogen_storage"] for row in dispatch_rows), default=0), "单位": "Nm3"},
            {"指标": "调度小时数", "数值": len(dispatch_rows), "单位": "h"},
        ],
        "curves": {
            "green_daily": daily,
            "green_monthly": monthly,
            "green_hourly": dispatch_rows,
            "safety_daily": [
                {"day": row["day"], "frequency_max": 50.0 if row["unmet_load"] <= 0 else 49.8, "frequency_min": 50.0 if row["unmet_load"] <= 0 else 49.5}
                for row in daily
            ],
        },
    }


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


def build_dispatch_model(scheme_payload: dict[str, Any], planning_result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Convert the selected planning result back into aggregate capacities and
    # unit counts before constructing the fixed-dispatch model.
    time_series = scheme_payload["time_series"]
    planning_parameters = first_row(scheme_payload.get("planning_parameters"))
    initial_storage_soc_ratio = min(1.0, max(0.0, numeric(planning_parameters.get("initial_storage_soc_ratio"), 0.5)))
    initial_hydrogen_storage_ratio = min(
        1.0,
        max(0.0, numeric(planning_parameters.get("initial_hydrogen_storage_ratio"), 0.5)),
    )
    raw_time_limit_minutes = planning_parameters.get(
        "optimization_time_limit_minutes",
        numeric(planning_parameters.get("optimization_time_limit_seconds"), 3600) / 60,
    )
    optimization_time_limit_minutes = int(min(120, max(10, round(numeric(raw_time_limit_minutes, 60)))))
    post_disturbance_power_balance_enabled = truthy_flag(planning_parameters.get("post_disturbance_power_balance_enabled"), True)
    capacities = capacities_from_planning_rows(planning_result_rows)
    device_params = first_device_params(scheme_payload)
    diesel_params = device_params.get("diesel_generators", {})
    storage_pcs_params = device_params.get("storage_pcs", {})
    storage_battery_params = device_params.get("storage_battery_packs", {})
    electrolyzer_params = device_params.get("hydrogen_electrolyzers", {})
    hydrogen_tank_params = device_params.get("hydrogen_tanks", {})
    fuel_cell_params = device_params.get("fuel_cells", {})
    storage_charge_efficiency = storage_efficiency_value(
        storage_pcs_params.get("storage_charge_efficiency"),
        planning_parameters.get("storage_charge_efficiency"),
        0.95,
    )
    storage_discharge_efficiency = storage_efficiency_value(
        storage_pcs_params.get("storage_discharge_efficiency"),
        planning_parameters.get("storage_discharge_efficiency"),
        0.95,
    )

    loads = np.array([max(0.0, numeric(row.get("load"), 0.0)) for row in time_series], dtype=float)
    wind_available = np.array([
        wind_generation(numeric(row.get("wind_speed"), 0.0), capacities["wind_capacity"], device_params.get("wind_turbines", {}))
        for row in time_series
    ], dtype=float)
    pv_available = np.array([
        pv_generation(numeric(row.get("solar_irradiance"), 0.0), capacities["pv_capacity"], device_params.get("photovoltaics", {}))
        for row in time_series
    ], dtype=float)

    diesel_capacity = capacities["diesel_capacity"]
    unit_capacity = max(0.0, numeric(diesel_params.get("capacity"), diesel_capacity))
    diesel_units = max(1, int(round(diesel_capacity / unit_capacity))) if diesel_capacity > 0 and unit_capacity > 0 else 0
    diesel_unit_power_upper = min(unit_capacity, max(0.0, numeric(diesel_params.get("power_upper"), unit_capacity))) if diesel_units else 0.0
    if diesel_unit_power_upper <= 0 and unit_capacity > 0:
        diesel_unit_power_upper = unit_capacity
    diesel_unit_power_lower = min(diesel_unit_power_upper, max(0.0, numeric(diesel_params.get("power_lower"), 0.0))) if diesel_unit_power_upper > 0 else 0.0
    diesel_power_upper = diesel_unit_power_upper * diesel_units
    diesel_power_lower = diesel_unit_power_lower * diesel_units

    electrolyzer_power_upper = capacities["electrolyzer_power_capacity"]
    electrolyzer_unit_capacity = max(0.0, numeric(electrolyzer_params.get("power_capacity"), electrolyzer_power_upper))
    electrolyzer_units = max(1, int(round(electrolyzer_power_upper / electrolyzer_unit_capacity))) if electrolyzer_power_upper > 0 and electrolyzer_unit_capacity > 0 else 0
    electrolyzer_unit_power_upper = electrolyzer_unit_capacity if electrolyzer_units else 0.0
    electrolyzer_unit_power_lower = min(
        electrolyzer_unit_power_upper,
        max(0.0, numeric(electrolyzer_params.get("power_lower"), 0.0)),
    ) if electrolyzer_unit_power_upper > 0 else 0.0
    electrolyzer_power_upper = electrolyzer_unit_power_upper * electrolyzer_units
    electrolyzer_power_lower = electrolyzer_unit_power_lower * electrolyzer_units
    storage_unit_capacity = max(0.0, numeric(storage_pcs_params.get("power_capacity"), capacities["storage_power_capacity"]))
    storage_units = max(1, int(round(capacities["storage_power_capacity"] / storage_unit_capacity))) if capacities["storage_power_capacity"] > 0 and storage_unit_capacity > 0 else 0
    grid_storage_units = storage_units if truthy_flag(storage_pcs_params.get("is_grid_forming"), False) else 0
    grid_storage_unit_capacity = storage_unit_capacity if grid_storage_units else 0.0
    storage_soc_upper_ratio = min(1.0, max(0.0, numeric(storage_battery_params.get("soc_upper"), 0.9)))
    storage_soc_lower_ratio = min(1.0, max(0.0, numeric(storage_battery_params.get("soc_lower"), 0.1)))
    if storage_soc_upper_ratio < storage_soc_lower_ratio:
        storage_soc_upper_ratio, storage_soc_lower_ratio = storage_soc_lower_ratio, storage_soc_upper_ratio
    storage_self_discharge_rate = min(0.01, max(0.0, numeric(storage_battery_params.get("self_discharge_rate"), 0.01)))
    hydrogen_self_discharge_rate = min(0.01, max(0.0, numeric(hydrogen_tank_params.get("self_discharge_rate"), 0.001)))

    return {
        "time_series": time_series,
        "loads": loads,
        "wind_available": wind_available,
        "pv_available": pv_available,
        "wind_speed": np.array([numeric(row.get("wind_speed"), 0.0) for row in time_series], dtype=float),
        "solar_irradiance": np.array([numeric(row.get("solar_irradiance"), 0.0) for row in time_series], dtype=float),
        "temperature": np.array([numeric(row.get("temperature"), 0.0) for row in time_series], dtype=float),
        "diesel_power_upper": diesel_power_upper,
        "diesel_power_lower": diesel_power_lower,
        "diesel_units": diesel_units,
        "diesel_unit_power_upper": diesel_unit_power_upper,
        "diesel_unit_power_lower": diesel_unit_power_lower,
        "storage_power_capacity": capacities["storage_power_capacity"],
        "storage_energy_capacity": capacities["storage_energy_capacity"],
        "storage_units": storage_units,
        "storage_unit_capacity": storage_unit_capacity,
        "grid_storage_units": grid_storage_units,
        "grid_storage_unit_capacity": grid_storage_unit_capacity,
        "storage_soc_upper_ratio": storage_soc_upper_ratio,
        "storage_soc_lower_ratio": storage_soc_lower_ratio,
        "electrolyzer_power_upper": electrolyzer_power_upper,
        "electrolyzer_power_lower": electrolyzer_power_lower,
        "electrolyzer_units": electrolyzer_units,
        "electrolyzer_unit_power_upper": electrolyzer_unit_power_upper,
        "electrolyzer_unit_power_lower": electrolyzer_unit_power_lower,
        "hydrogen_tank_capacity": capacities["hydrogen_tank_capacity"],
        "fuel_cell_power_capacity": capacities["fuel_cell_power_capacity"],
        "initial_storage_soc_ratio": initial_storage_soc_ratio,
        "initial_hydrogen_storage_ratio": initial_hydrogen_storage_ratio,
        "optimization_time_limit_seconds": optimization_time_limit_minutes * 60,
        "storage_charge_efficiency": storage_charge_efficiency,
        "storage_discharge_efficiency": storage_discharge_efficiency,
        "storage_self_discharge_rate": storage_self_discharge_rate,
        "hydrogen_self_discharge_rate": hydrogen_self_discharge_rate,
        "post_disturbance_power_balance_enabled": post_disturbance_power_balance_enabled,
        "load_up_disturbance_factor": max(0.0, numeric(planning_parameters.get("load_up_disturbance_factor"), numeric(planning_parameters.get("load_disturbance_factor"), 0.0))),
        "load_down_disturbance_factor": max(0.0, numeric(planning_parameters.get("load_down_disturbance_factor"), numeric(planning_parameters.get("load_disturbance_factor"), 0.0))),
        "renewable_down_disturbance_factor": max(0.0, numeric(planning_parameters.get("renewable_down_disturbance_factor"), 0.0)),
        "fuel_rate": numeric(diesel_params.get("fuel_rate"), 0.26),
        "electric_to_hydrogen_efficiency": numeric(electrolyzer_params.get("electric_to_hydrogen_efficiency"), 0.7),
        "hydrogen_to_electric_efficiency": numeric(fuel_cell_params.get("hydrogen_to_electric_efficiency"), 0.55),
    }


def direct_dispatch_rows(model: dict[str, Any], log: LogSink | None = None) -> list[dict[str, Any]] | None:
    """Return an exact per-hour optimum when no storage or hydrogen coupling is present."""

    # This fast path is only valid when no inventory state links one hour to
    # the next; otherwise the MILP path is required.
    coupled_capacities = (
        "storage_power_capacity",
        "storage_energy_capacity",
        "electrolyzer_power_upper",
        "hydrogen_tank_capacity",
        "fuel_cell_power_capacity",
    )
    if any(numeric(model.get(key), 0.0) > 1e-9 for key in coupled_capacities):
        return None

    emit(log, "info", "检测到无储能/氢能跨时段耦合，使用逐时解析调度快速求解", 20)
    rows: list[dict[str, Any]] = []
    for hour, source_row in enumerate(model["time_series"]):
        load = round(float(model["loads"][hour]), 4)
        wind_available = round(float(model["wind_available"][hour]), 4)
        pv_available = round(float(model["pv_available"][hour]), 4)
        renewable_available = round(wind_available + pv_available, 4)
        renewable_used, diesel_power, unmet_load, diesel_on = direct_hour_dispatch(
            load,
            renewable_available,
            model["diesel_power_upper"],
            model["diesel_units"],
            model["diesel_unit_power_upper"],
            model["diesel_unit_power_lower"],
        )
        wind_power, pv_power = allocate_renewable_power(renewable_used, wind_available, pv_available)
        wind_curtailed = max(0.0, round(wind_available - wind_power, 4))
        pv_curtailed = max(0.0, round(pv_available - pv_power, 4))
        curtailed_power = round(wind_curtailed + pv_curtailed, 4)
        hour_index = int(numeric(source_row.get("hour_index"), hour + 1) or hour + 1)
        rows.append(
            {
                "hour_index": hour_index,
                "datetime": source_row.get("datetime", f"H{hour_index:04d}"),
                "wind_speed": round(float(model["wind_speed"][hour]), 4),
                "solar_irradiance": round(float(model["solar_irradiance"][hour]), 4),
                "temperature": round(float(model["temperature"][hour]), 4),
                "load": load,
                "diesel_power": diesel_power,
                "wind_available": wind_available,
                "wind_power": wind_power,
                "pv_available": pv_available,
                "pv_power": pv_power,
                "renewable_available": renewable_available,
                "renewable_ratio": round(percent(wind_power + pv_power, load), 4),
                "storage_power": 0.0,
                "storage_charge": 0.0,
                "storage_discharge": 0.0,
                "storage_soc": 0.0,
                "diesel_on": diesel_on,
                "hydrogen_production_power": 0.0,
                "electrolyzer_on": 0,
                "fuel_cell_power": 0.0,
                "hydrogen_storage": 0.0,
                "wind_curtailed_power": wind_curtailed,
                "pv_curtailed_power": pv_curtailed,
                "curtailed_power": curtailed_power,
                "renewable_curtailed_rate": round(percent(curtailed_power, renewable_available), 4),
                "unmet_load": unmet_load,
            }
        )
    emit(log, "info", "逐时解析调度完成，正在整理8760点调度曲线", 85)
    return rows


def direct_hour_dispatch(
    load: float,
    renewable_available: float,
    diesel_power_upper: float,
    diesel_units: int,
    diesel_unit_power_upper: float,
    diesel_unit_power_lower: float,
) -> tuple[float, float, float, int]:
    renewable_used = min(max(0.0, renewable_available), max(0.0, load))
    residual = max(0.0, load - renewable_used)
    diesel_power = 0.0
    diesel_on = 0
    if residual > 1e-9 and diesel_power_upper > 1e-9 and diesel_units > 0 and diesel_unit_power_upper > 1e-9:
        diesel_power = min(diesel_power_upper, residual)
        diesel_on = max(1, min(diesel_units, int(math.ceil(diesel_power / diesel_unit_power_upper - 1e-9))))
        minimum_power = diesel_on * max(0.0, diesel_unit_power_lower)
        if minimum_power > diesel_power + 1e-9:
            extra_power = minimum_power - diesel_power
            if extra_power <= renewable_used + 1e-9:
                renewable_used -= extra_power
                diesel_power = minimum_power
            elif minimum_power <= load + 1e-9:
                diesel_power = minimum_power
                renewable_used = max(0.0, load - diesel_power)
            else:
                diesel_power = 0.0
                diesel_on = 0
                renewable_used = min(max(0.0, renewable_available), max(0.0, load))
        diesel_power = min(diesel_power, diesel_power_upper)
    unmet_load = max(0.0, load - renewable_used - diesel_power)
    if diesel_power <= 1e-9:
        diesel_power = 0.0
        diesel_on = 0
    return round(renewable_used, 4), round(diesel_power, 4), round(unmet_load, 4), diesel_on


def allocate_renewable_power(renewable_used: float, wind_available: float, pv_available: float) -> tuple[float, float]:
    wind_power = min(max(0.0, wind_available), max(0.0, renewable_used))
    pv_power = min(max(0.0, pv_available), max(0.0, renewable_used - wind_power))
    return round(wind_power, 4), round(pv_power, 4)


def solve_dispatch_model(model: dict[str, Any], log: LogSink | None = None) -> list[dict[str, Any]]:
    loads = model["loads"]
    n = len(loads)
    builder = dispatch_milp.MilpModelBuilder()

    for hour in range(n):
        builder.add_var(("diesel_power", hour), 0.0, max(0.0, model["diesel_power_upper"]), cost=1.0)
        builder.add_var(("wind_power", hour), 0.0, max(0.0, model["wind_available"][hour]))
        builder.add_var(("pv_power", hour), 0.0, max(0.0, model["pv_available"][hour]))
        builder.add_var(("storage_charge", hour), 0.0, max(0.0, model["storage_power_capacity"]))
        builder.add_var(("storage_discharge", hour), 0.0, max(0.0, model["storage_power_capacity"]))
        builder.add_var(("storage_charge_on", hour), 0.0, 1.0, integer=True)
        builder.add_var(("storage_discharge_on", hour), 0.0, 1.0, integer=True)
        builder.add_var(("storage_soc", hour), 0.0, max(0.0, model["storage_energy_capacity"]))
        builder.add_var(("electrolyzer_power", hour), 0.0, max(0.0, model["electrolyzer_power_upper"]))
        builder.add_var(("hydrogen_storage", hour), 0.0, max(0.0, model["hydrogen_tank_capacity"]))
        builder.add_var(("fuel_cell_power", hour), 0.0, max(0.0, model["fuel_cell_power_capacity"]))
        builder.add_var(
            ("curtailed_power", hour),
            0.0,
            max(0.0, model["wind_available"][hour] + model["pv_available"][hour]),
        )
        builder.add_var(("unmet_load", hour), 0.0, max(0.0, loads[hour]), cost=LOAD_SHED_PENALTY)
        if model["diesel_units"]:
            builder.add_var(("diesel_on_count", hour), 0.0, model["diesel_units"], integer=True, cost=DIESEL_ON_PENALTY)
        if model["grid_storage_units"]:
            builder.add_var(("grid_storage_on_count", hour), 0.0, model["grid_storage_units"], integer=True)
            builder.add_var(("grid_storage_up_available_count", hour), 0.0, model["grid_storage_units"], integer=True)
            builder.add_var(("grid_storage_down_available_count", hour), 0.0, model["grid_storage_units"], integer=True)
        if model["electrolyzer_units"]:
            builder.add_var(("electrolyzer_on_count", hour), 0.0, model["electrolyzer_units"], integer=True, cost=ELECTROLYZER_ON_PENALTY)

    def var(key: tuple[Any, ...]) -> int:
        return builder.var(key)

    storage_charge_efficiency = model["storage_charge_efficiency"]
    storage_discharge_efficiency = model["storage_discharge_efficiency"]
    storage_self_discharge_per_hour = model["storage_self_discharge_rate"] / 24.0
    hydrogen_self_discharge_per_hour = model["hydrogen_self_discharge_rate"] / 24.0
    electric_to_hydrogen_efficiency = max(0.0, model["electric_to_hydrogen_efficiency"])
    hydrogen_to_electric_efficiency = max(0.0001, model["hydrogen_to_electric_efficiency"])
    initial_storage = model["storage_energy_capacity"] * model["initial_storage_soc_ratio"]
    initial_hydrogen = model["hydrogen_tank_capacity"] * model["initial_hydrogen_storage_ratio"]

    for hour in range(n):
        load = loads[hour]
        dispatch_milp.add_power_balance_constraint(
            builder,
            generation_indices=[
                var(("diesel_power", hour)),
                var(("wind_power", hour)),
                var(("pv_power", hour)),
                var(("storage_discharge", hour)),
                var(("fuel_cell_power", hour)),
            ],
            charge_indices=[var(("storage_charge", hour))],
            consumption_indices=[var(("electrolyzer_power", hour))],
            unmet_index=var(("unmet_load", hour)),
            load=load,
        )
        dispatch_milp.add_availability_constraint(
            builder,
            production_indices=[var(("wind_power", hour)), var(("pv_power", hour))],
            curtailed_index=var(("curtailed_power", hour)),
            fixed_available=model["wind_available"][hour] + model["pv_available"][hour],
        )
        diesel_on_indices = [var(("diesel_on_count", hour))] if model["diesel_units"] else []
        if diesel_on_indices:
            dispatch_milp.add_unit_commitment_constraints(
                builder,
                power_index=var(("diesel_power", hour)),
                on_indices=diesel_on_indices,
                power_upper=model["diesel_unit_power_upper"],
                power_lower=model["diesel_unit_power_lower"],
            )
        else:
            builder.add_constraint({var(("diesel_power", hour)): 1.0}, 0.0, 0.0)
        grid_storage_on_indices = [var(("grid_storage_on_count", hour))] if model["grid_storage_units"] else []
        grid_storage_up_indices = [var(("grid_storage_up_available_count", hour))] if model["grid_storage_units"] else []
        grid_storage_down_indices = [var(("grid_storage_down_available_count", hour))] if model["grid_storage_units"] else []
        for on_index, up_index, down_index in zip(grid_storage_on_indices, grid_storage_up_indices, grid_storage_down_indices):
            builder.add_constraint({up_index: 1.0, on_index: -1.0}, -np.inf, 0.0)
            builder.add_constraint({down_index: 1.0, on_index: -1.0}, -np.inf, 0.0)
        electrolyzer_on_indices = [var(("electrolyzer_on_count", hour))] if model["electrolyzer_units"] else []
        if electrolyzer_on_indices:
            dispatch_milp.add_unit_commitment_constraints(
                builder,
                power_index=var(("electrolyzer_power", hour)),
                on_indices=electrolyzer_on_indices,
                power_upper=model["electrolyzer_unit_power_upper"],
                power_lower=model["electrolyzer_unit_power_lower"],
            )
        else:
            builder.add_constraint({var(("electrolyzer_power", hour)): 1.0}, 0.0, 0.0)
        storage_flags = dispatch_milp.add_storage_constraints(
            builder,
            charge_index=var(("storage_charge", hour)),
            discharge_index=var(("storage_discharge", hour)),
            charge_on_index=var(("storage_charge_on", hour)),
            discharge_on_index=var(("storage_discharge_on", hour)),
            soc_index=var(("storage_soc", hour)),
            previous_soc_index=var(("storage_soc", hour - 1)) if hour > 0 else None,
            power_capacity_upper=model["storage_power_capacity"],
            fixed_power_capacity=model["storage_power_capacity"],
            fixed_energy_capacity=model["storage_energy_capacity"],
            fixed_initial_value=initial_storage,
            charge_efficiency=storage_charge_efficiency,
            discharge_efficiency=storage_discharge_efficiency,
            soc_lower_ratio=model["storage_soc_lower_ratio"],
            soc_upper_ratio=model["storage_soc_upper_ratio"],
            self_discharge_rate_per_hour=storage_self_discharge_per_hour,
        )
        for index in grid_storage_up_indices:
            builder.add_constraint({index: 1.0, storage_flags["soc_above_lower"]: -float(model["grid_storage_units"])}, -np.inf, 0.0)
        for index in grid_storage_down_indices:
            builder.add_constraint({index: 1.0, storage_flags["soc_below_upper"]: -float(model["grid_storage_units"])}, -np.inf, 0.0)
        dispatch_milp.add_grid_support_requirement(
            builder,
            diesel_on_indices=diesel_on_indices,
            grid_storage_on_indices=grid_storage_on_indices,
        )
        if model["post_disturbance_power_balance_enabled"]:
            dispatch_milp.add_post_disturbance_balance_constraints(
                builder,
                load=load,
                load_up_factor=model["load_up_disturbance_factor"],
                load_down_factor=model["load_down_disturbance_factor"],
                renewable_down_factor=model["renewable_down_disturbance_factor"],
                diesel_power_indices=[var(("diesel_power", hour))],
                diesel_on_terms={
                    index: model["diesel_unit_power_upper"]
                    for index in diesel_on_indices
                },
                grid_storage_charge_index=var(("storage_charge", hour)),
                grid_storage_discharge_index=var(("storage_discharge", hour)),
                grid_storage_up_on_terms={
                    index: model["grid_storage_unit_capacity"]
                    for index in grid_storage_up_indices
                },
                grid_storage_down_on_terms={
                    index: model["grid_storage_unit_capacity"]
                    for index in grid_storage_down_indices
                },
                wind_power_indices=[var(("wind_power", hour))],
                pv_power_indices=[var(("pv_power", hour))],
            )
        dispatch_milp.add_hydrogen_constraints(
            builder,
            storage_index=var(("hydrogen_storage", hour)),
            previous_storage_index=var(("hydrogen_storage", hour - 1)) if hour > 0 else None,
            production_terms={
                var(("electrolyzer_power", hour)): electric_to_hydrogen_efficiency
            } if model["electrolyzer_power_upper"] > 1e-9 else {},
            consumption_terms={
                var(("fuel_cell_power", hour)): 1.0 / hydrogen_to_electric_efficiency
            } if model["fuel_cell_power_capacity"] > 1e-9 else {},
            fixed_capacity=model["hydrogen_tank_capacity"],
            fixed_initial_value=initial_hydrogen,
            self_discharge_rate_per_hour=hydrogen_self_discharge_per_hour,
        )

    for day_end_hour in range(23, n, 24):
        dispatch_milp.add_storage_cycle_constraint(
            builder,
            soc_index=var(("storage_soc", day_end_hour)),
            fixed_initial_value=initial_storage,
        )
    if n:
        dispatch_milp.add_hydrogen_cycle_constraint(
            builder,
            storage_index=var(("hydrogen_storage", n - 1)),
            fixed_initial_value=initial_hydrogen,
        )

    emit(
        log,
        "info",
        f"评估模型规模：变量{builder.variable_count}个（整数{builder.integer_variable_count}个），约束{builder.constraint_count}条，非零系数{builder.nonzero_count}个",
        18,
    )
    dispatch_milp.emit_builder_diagnostics(builder, log, "方案评估MILP")
    emit(log, "info", "求解8760点联合混合整数线性优化问题", 20)
    model["variables"] = builder.variables
    model["objective"] = builder.objective
    model["integrality"] = builder.integrality
    result = dispatch_milp.solve_built_milp(
        builder,
        options={
            "time_limit": model["optimization_time_limit_seconds"],
            "mip_rel_gap": 0.01,
            "disp": False,
            "solver_log": True,
            "solver_log_interval": 2.0,
        },
        log=log,
        problem_name="方案评估",
        solve_fn=solve_milp,
    )
    if not result.success:
        raise ValueError(f"8760点联合优化失败：{result.message}")
    emit(log, "info", "联合优化求解完成，正在整理8760点调度曲线", 85)
    return dispatch_rows_from_solution(model, result.x)


def dispatch_rows_from_solution(model: dict[str, Any], solution: np.ndarray) -> list[dict[str, Any]]:
    # Convert solver vectors back into hourly records used by charts, tables
    # and XLSX export.
    rows = []
    variables = model.get("variables")

    def value(hour: int, key: str) -> float:
        if variables:
            return rounded_solution_from_index(solution, variables[(key, hour)])
        return rounded_solution(solution, hour, key)

    def count_value(key: str, hour: int) -> int:
        if variables and (key, hour) in variables:
            return int(round(rounded_solution_from_index(solution, variables[(key, hour)])))
        if variables:
            return 0
        return round_binary_solution(solution, hour, key)

    for hour, row in enumerate(model["time_series"]):
        hour_index = int(numeric(row.get("hour_index"), hour + 1) or hour + 1)
        wind_available = round(float(model["wind_available"][hour]), 4)
        pv_available = round(float(model["pv_available"][hour]), 4)
        wind_power = value(hour, "wind_power")
        pv_power = value(hour, "pv_power")
        wind_curtailed = max(0.0, round(wind_available - wind_power, 4))
        pv_curtailed = max(0.0, round(pv_available - pv_power, 4))
        storage_charge = value(hour, "storage_charge")
        storage_discharge = value(hour, "storage_discharge")
        renewable_available = round(wind_available + pv_available, 4)
        renewable_energy = round(wind_power + pv_power, 4)
        curtailed_power = round(wind_curtailed + pv_curtailed, 4)
        load = round(float(model["loads"][hour]), 4)
        item = {
            "hour_index": hour_index,
            "datetime": row.get("datetime", f"H{hour_index:04d}"),
            "wind_speed": round(float(model["wind_speed"][hour]), 4),
            "solar_irradiance": round(float(model["solar_irradiance"][hour]), 4),
            "temperature": round(float(model["temperature"][hour]), 4),
            "load": load,
            "diesel_power": value(hour, "diesel_power"),
            "wind_available": wind_available,
            "wind_power": wind_power,
            "pv_available": pv_available,
            "pv_power": pv_power,
            "renewable_available": renewable_available,
            "renewable_ratio": round(percent(renewable_energy, load), 4),
            "storage_power": round(storage_discharge - storage_charge, 4),
            "storage_charge": storage_charge,
            "storage_discharge": storage_discharge,
            "storage_soc": value(hour, "storage_soc"),
            "diesel_on": count_value("diesel_on_count", hour),
            "hydrogen_production_power": value(hour, "electrolyzer_power"),
            "electrolyzer_on": count_value("electrolyzer_on_count", hour),
            "fuel_cell_power": value(hour, "fuel_cell_power"),
            "hydrogen_storage": value(hour, "hydrogen_storage"),
            "wind_curtailed_power": wind_curtailed,
            "pv_curtailed_power": pv_curtailed,
            "curtailed_power": curtailed_power,
            "renewable_curtailed_rate": round(percent(curtailed_power, renewable_available), 4),
            "unmet_load": value(hour, "unmet_load"),
        }
        rows.append(item)
    return rows


def rounded_solution_from_index(solution: np.ndarray, index: int) -> float:
    value = float(solution[index])
    return round(0.0 if abs(value) < 1e-7 else value, 4)


def dispatch_totals(dispatch_rows: list[dict[str, Any]], fuel_rate: float, electric_to_hydrogen_efficiency: float) -> dict[str, float]:
    # Totals are computed from the hourly rows so summary numbers always match
    # the curves visible in the UI.
    totals = {
        "load_energy": sum_numeric(dispatch_rows, "load"),
        "wind_energy": sum_numeric(dispatch_rows, "wind_power"),
        "pv_energy": sum_numeric(dispatch_rows, "pv_power"),
        "storage_discharge_energy": sum_numeric(dispatch_rows, "storage_discharge"),
        "storage_charge_energy": sum_numeric(dispatch_rows, "storage_charge"),
        "diesel_energy": sum_numeric(dispatch_rows, "diesel_power"),
        "curtailed_energy": sum_numeric(dispatch_rows, "curtailed_power"),
        "unmet_load_energy": sum_numeric(dispatch_rows, "unmet_load"),
        "hydrogen_production_energy": sum_numeric(dispatch_rows, "hydrogen_production_power"),
        "fuel_cell_energy": sum_numeric(dispatch_rows, "fuel_cell_power"),
        "wind_available_energy": sum_numeric(dispatch_rows, "wind_available"),
        "pv_available_energy": sum_numeric(dispatch_rows, "pv_available"),
        "renewable_available_energy": sum(numeric(row.get("renewable_available"), numeric(row.get("wind_available"), 0.0) + numeric(row.get("pv_available"), 0.0)) for row in dispatch_rows),
        "renewable_energy": sum(numeric(row.get("wind_power"), 0.0) + numeric(row.get("pv_power"), 0.0) for row in dispatch_rows),
        "wind_curtailed_energy": sum_numeric(dispatch_rows, "wind_curtailed_power"),
        "pv_curtailed_energy": sum_numeric(dispatch_rows, "pv_curtailed_power"),
        "hydrogen_storage_increase": sum(positive_delta(dispatch_rows, "hydrogen_storage", 0.0)),
        "hydrogen_storage_decrease": sum(negative_delta(dispatch_rows, "hydrogen_storage", 0.0)),
    }
    totals["hydrogen_production"] = totals["hydrogen_production_energy"] * max(0.0, electric_to_hydrogen_efficiency)
    totals["diesel_consumption"] = totals["diesel_energy"] * fuel_rate / 1000
    totals["renewable_ratio"] = percent(totals["renewable_energy"], totals["load_energy"])
    totals["renewable_curtailed_rate"] = percent(totals["curtailed_energy"], totals["renewable_available_energy"])
    return totals


def rounded_solution(solution: np.ndarray, hour: int, key: str) -> float:
    value = float(solution[var_index(hour, key)])
    return round(0.0 if abs(value) < 1e-7 else value, 4)


def round_binary_solution(solution: np.ndarray, hour: int, key: str) -> int:
    return int(round(float(solution[var_index(hour, key)])))


def var_index(hour: int, key: str) -> int:
    return hour * VARIABLE_COUNT + VARIABLES[key]


def capacities_from_planning_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    # Result files store planning output as display rows; this function maps
    # those rows back to aggregate capacities for the evaluation model.
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
        device_type = str(row.get("设备类型", ""))
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


def first_device_params(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: first_row(payload.get(key))
        for key in (
            "diesel_generators",
            "wind_turbines",
            "photovoltaics",
            "storage_pcs",
            "storage_battery_packs",
            "hydrogen_electrolyzers",
            "hydrogen_tanks",
            "fuel_cells",
        )
    }


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


def storage_efficiency_value(primary: Any, legacy: Any, default: float) -> float:
    value = primary if primary not in ("", None) else legacy
    return min(1.0, max(0.0001, numeric(value, default)))


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
    parser = argparse.ArgumentParser(description="Run 8760-hour evaluation dispatch.")
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
