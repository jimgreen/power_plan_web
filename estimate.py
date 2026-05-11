#!/usr/bin/env python3
"""8760-hour evaluation dispatch for a fixed planning result."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

import planning_store


LogSink = Callable[[dict[str, Any]], None]


def run_estimation(scheme_payload: dict[str, Any], planning_result_rows: list[dict[str, Any]], log: LogSink | None = None) -> dict[str, Any]:
    """Dispatch a fixed equipment plan for 8760 hours with minimum diesel energy."""

    time_series = scheme_payload.get("time_series") if isinstance(scheme_payload.get("time_series"), list) else []
    if len(time_series) != 8760:
        raise ValueError(f"评估调度需要8760点时序数据，当前为{len(time_series)}")

    planning_parameters = first_row(scheme_payload.get("planning_parameters"))
    planning_load_factor = numeric(planning_parameters.get("planning_load_factor"), 1.0)
    devices = capacities_from_planning_rows(planning_result_rows)
    device_params = first_device_params(scheme_payload)
    fuel_rate = numeric(device_params.get("diesel_generators", {}).get("fuel_rate"), 0.26)
    battery_capacity = devices["storage_energy_capacity"]
    storage_power = devices["storage_power_capacity"] or battery_capacity
    storage_charge_efficiency = 0.95
    storage_discharge_efficiency = 0.95
    state_of_charge = battery_capacity * 0.5

    emit(log, "info", "开始8760点优化调度", 0)
    dispatch_rows: list[dict[str, Any]] = []
    totals = {
        "load_energy": 0.0,
        "wind_energy": 0.0,
        "pv_energy": 0.0,
        "storage_discharge_energy": 0.0,
        "storage_charge_energy": 0.0,
        "diesel_energy": 0.0,
        "curtailed_energy": 0.0,
        "diesel_consumption": 0.0,
    }
    next_progress = 10

    for index, row in enumerate(time_series):
        hour_index = int(numeric(row.get("hour_index"), index + 1) or index + 1)
        load = max(0.0, numeric(row.get("load"), 0.0) * planning_load_factor)
        wind_power = wind_generation(numeric(row.get("wind_speed"), 0.0), devices["wind_capacity"], device_params.get("wind_turbines", {}))
        pv_power = pv_generation(numeric(row.get("solar_irradiance"), 0.0), devices["pv_capacity"], device_params.get("photovoltaics", {}))
        renewable = wind_power + pv_power

        renewable_to_load = min(load, renewable)
        deficit = load - renewable_to_load
        surplus = renewable - renewable_to_load

        storage_discharge = min(deficit, storage_power, state_of_charge * storage_discharge_efficiency)
        state_of_charge -= storage_discharge / storage_discharge_efficiency if storage_discharge_efficiency else storage_discharge
        deficit -= storage_discharge

        diesel_energy = min(deficit, devices["diesel_capacity"])
        unmet_load = max(0.0, deficit - diesel_energy)

        storage_charge = min(surplus, storage_power, (battery_capacity - state_of_charge) / storage_charge_efficiency if storage_charge_efficiency else battery_capacity - state_of_charge)
        state_of_charge += storage_charge * storage_charge_efficiency
        curtailed = max(0.0, surplus - storage_charge)

        totals["load_energy"] += load
        totals["wind_energy"] += wind_power
        totals["pv_energy"] += pv_power
        totals["storage_discharge_energy"] += storage_discharge
        totals["storage_charge_energy"] += storage_charge
        totals["diesel_energy"] += diesel_energy
        totals["curtailed_energy"] += curtailed

        dispatch_rows.append(
            {
                "hour_index": hour_index,
                "datetime": row.get("datetime", f"H{hour_index:04d}"),
                "load": round(load, 4),
                "wind_power": round(wind_power, 4),
                "pv_power": round(pv_power, 4),
                "storage_charge": round(storage_charge, 4),
                "storage_discharge": round(storage_discharge, 4),
                "diesel_power": round(diesel_energy, 4),
                "curtailed_power": round(curtailed, 4),
                "unmet_load": round(unmet_load, 4),
                "storage_soc": round(state_of_charge, 4),
            }
        )

        progress = int((index + 1) * 100 / len(time_series))
        if progress >= next_progress:
            emit(log, "info", f"8760点优化调度进度 {next_progress}%", next_progress)
            next_progress += 10

    totals = {key: round(value, 4) for key, value in totals.items()}
    totals["diesel_consumption"] = round(totals["diesel_energy"] * fuel_rate / 1000, 4)
    renewable_energy = totals["wind_energy"] + totals["pv_energy"] + totals["storage_discharge_energy"]
    green_ratio = renewable_energy / totals["load_energy"] * 100 if totals["load_energy"] else 0
    curtailed_ratio = totals["curtailed_energy"] / max(totals["wind_energy"] + totals["pv_energy"], 0.0001) * 100
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
    daily = aggregate_daily(dispatch_rows)
    return {
        "overview_tables": [
            {"title": "规划结果", "rows": planning_result_rows},
            {
                "title": "规划年指标",
                "rows": [
                    {"指标": "负荷总电量", "数值": totals["load_energy"], "单位": "kWh"},
                    {"指标": "柴发总电量", "数值": totals["diesel_energy"], "单位": "kWh"},
                    {"指标": "风能总电量", "数值": totals["wind_energy"], "单位": "kWh"},
                    {"指标": "光伏总电量", "数值": totals["pv_energy"], "单位": "kWh"},
                    {"指标": "电储总发电量", "数值": totals["storage_discharge_energy"], "单位": "kWh"},
                    {"指标": "电储总充电量", "数值": totals["storage_charge_energy"], "单位": "kWh"},
                    {"指标": "弃电量", "数值": totals["curtailed_energy"], "单位": "kWh"},
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
            {"指标": "负荷总电量", "数值": totals["load_energy"], "单位": "kWh"},
            {"指标": "柴发总电量", "数值": totals["diesel_energy"], "单位": "kWh"},
            {"指标": "风机总发电量", "数值": totals["wind_energy"], "单位": "kWh"},
            {"指标": "光伏总发电量", "数值": totals["pv_energy"], "单位": "kWh"},
            {"指标": "电储总发电量", "数值": totals["storage_discharge_energy"], "单位": "kWh"},
            {"指标": "新能源总弃电量", "数值": round(curtailed_ratio, 2), "单位": "%"},
            {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨"},
        ],
        "safety_table": [
            {"指标": "最大未供负荷", "数值": max((row["unmet_load"] for row in dispatch_rows), default=0), "单位": "kW"},
            {"指标": "最低储能SOC", "数值": min((row["storage_soc"] for row in dispatch_rows), default=0), "单位": "kWh"},
            {"指标": "最高储能SOC", "数值": max((row["storage_soc"] for row in dispatch_rows), default=0), "单位": "kWh"},
            {"指标": "调度小时数", "数值": len(dispatch_rows), "单位": "h"},
        ],
        "curves": {
            "green_daily": daily,
            "green_hourly": dispatch_rows,
            "safety_daily": [
                {"day": row["day"], "frequency_max": 50.0 if row["unmet_load"] <= 0 else 49.8, "frequency_min": 50.0 if row["unmet_load"] <= 0 else 49.5}
                for row in daily
            ],
        },
    }


def aggregate_daily(dispatch_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    daily = []
    for day_index in range(365):
        rows = dispatch_rows[day_index * 24 : (day_index + 1) * 24]
        daily.append(
            {
                "day": day_index + 1,
                "diesel_energy": round(sum(row["diesel_power"] for row in rows), 4),
                "wind_energy": round(sum(row["wind_power"] for row in rows), 4),
                "pv_energy": round(sum(row["pv_power"] for row in rows), 4),
                "hydrogen_energy": 0,
                "storage_discharge_energy": round(sum(row["storage_discharge"] for row in rows), 4),
                "load_energy": round(sum(row["load"] for row in rows), 4),
                "hydrogen_production_energy": 0,
                "storage_charge_energy": round(sum(row["storage_charge"] for row in rows), 4),
                "unmet_load": round(sum(row["unmet_load"] for row in rows), 4),
            }
        )
    return daily


def capacities_from_planning_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    capacities = {
        "diesel_capacity": 0.0,
        "wind_capacity": 0.0,
        "pv_capacity": 0.0,
        "storage_power_capacity": 0.0,
        "storage_energy_capacity": 0.0,
    }
    for row in rows or []:
        device_type = str(row.get("设备类型", ""))
        total = numeric(row.get("总容量"), numeric(row.get("设计台数"), 0) * numeric(row.get("单台容量"), 0))
        if "柴" in device_type:
            capacities["diesel_capacity"] += total
        elif "风" in device_type:
            capacities["wind_capacity"] += total
        elif "光" in device_type:
            capacities["pv_capacity"] += total
        elif "储能" in device_type or "电储" in device_type:
            capacities["storage_power_capacity"] += total
            capacities["storage_energy_capacity"] += total
    return capacities


def first_device_params(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: first_row(payload.get(key))
        for key in (
            "diesel_generators",
            "wind_turbines",
            "photovoltaics",
            "storage_pcs",
            "storage_battery_packs",
        )
    }


def wind_generation(wind_speed: float, capacity: float, params: dict[str, Any]) -> float:
    if capacity <= 0:
        return 0.0
    cut_in = numeric(params.get("cut_in_wind_speed"), 3.0)
    cut_out = numeric(params.get("cut_out_wind_speed"), 25.0)
    rated = max(cut_in + 0.1, 12.0)
    if wind_speed < cut_in or wind_speed >= cut_out:
        return 0.0
    if wind_speed >= rated:
        return capacity
    return capacity * ((wind_speed - cut_in) / (rated - cut_in)) ** 3


def pv_generation(irradiance: float, capacity: float, params: dict[str, Any]) -> float:
    if capacity <= 0:
        return 0.0
    efficiency = numeric(params.get("generation_efficiency"), 1.0)
    return max(0.0, min(capacity, capacity * max(0.0, irradiance) / 1000 * efficiency))


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
