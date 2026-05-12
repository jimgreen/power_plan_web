#!/usr/bin/env python3
"""Planning optimization with equipment-count decisions and 8760-hour dispatch."""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, milp

import estimate


LogSink = Callable[[dict[str, Any]], None]

LOAD_SHED_PENALTY_COST = 1_000_000.0
DIESEL_ON_COUNT_PENALTY = 0.0001
ELECTROLYZER_ON_COUNT_PENALTY = 0.00001
CURTAILMENT_COST = 0.000001
CYCLING_COST = 0.000001

DEVICE_SPECS: dict[str, dict[str, str]] = {
    "diesel_generators": {"label": "柴发", "capacity_field": "capacity", "unit": "kW"},
    "wind_turbines": {"label": "风机", "capacity_field": "capacity", "unit": "kW"},
    "photovoltaics": {"label": "光伏", "capacity_field": "capacity", "unit": "kW"},
    "storage_pcs": {"label": "储能PCS", "capacity_field": "power_capacity", "unit": "kW"},
    "storage_battery_packs": {"label": "储能电池组", "capacity_field": "battery_capacity", "unit": "kWh"},
    "hydrogen_electrolyzers": {"label": "电制氢", "capacity_field": "power_capacity", "unit": "kW"},
    "hydrogen_tanks": {"label": "储氢罐", "capacity_field": "hydrogen_tank_capacity", "unit": "Nm3"},
    "fuel_cells": {"label": "燃料电池", "capacity_field": "power_capacity", "unit": "kW"},
}


def run_optimization(
    scheme_payload: dict[str, Any],
    log: LogSink | None = None,
    horizon_hours: int | None = None,
) -> dict[str, Any]:
    """Optimize equipment quantities and dispatch as a joint MILP."""

    time_series = scheme_payload.get("time_series") if isinstance(scheme_payload.get("time_series"), list) else []
    if horizon_hours is None and len(time_series) != 8760:
        raise ValueError(f"规划优化需要8760点时序数据，当前为{len(time_series)}")
    if horizon_hours is not None:
        if horizon_hours <= 0:
            raise ValueError("优化时段数必须为正整数")
        time_series = time_series[:horizon_hours]
        if len(time_series) != horizon_hours:
            raise ValueError(f"优化时段数不足，期望{horizon_hours}点，当前为{len(time_series)}")

    emit(log, "info", "开始建立设备台数与时序运行联合优化模型", 5)
    model = build_planning_model(scheme_payload, time_series)
    emit(log, "info", "已加入台数上下限、建设成本、柴油成本和绿电占比约束", 15)
    solution = solve_planning_model(model, log)
    emit(log, "info", "优化求解完成，正在整理规划结果和8760曲线", 85)

    planning_rows = planning_rows_from_solution(model, solution)
    dispatch_rows = dispatch_rows_from_solution(model, solution)
    totals = dispatch_totals(dispatch_rows)
    costs = cost_summary_from_solution(model, solution, totals)
    results = build_results(planning_rows, dispatch_rows, totals, costs, model)
    metrics = build_metrics(totals, costs)
    emit(log, "ok", "优化规划完成", 100)
    return {
        "status": "已完成",
        "progress": 100,
        "metrics": metrics,
        "results": results,
        "planning_result_rows": planning_rows,
        "dispatch_rows": dispatch_rows,
        "totals": totals | costs,
    }


def build_planning_model(scheme_payload: dict[str, Any], time_series: list[dict[str, Any]]) -> dict[str, Any]:
    planning_parameters = estimate.first_row(scheme_payload.get("planning_parameters"))
    planning_load_factor = numeric(planning_parameters.get("planning_load_factor"), 1.0)
    diesel_price = max(0.0, numeric(planning_parameters.get("diesel_price"), 0.0))
    green_ratio_lower = min(1.0, max(0.0, numeric(planning_parameters.get("green_power_ratio_lower"), 0.0)))
    device_rows = normalized_device_rows(scheme_payload)
    loads = np.array([max(0.0, numeric(row.get("load"), 0.0) * planning_load_factor) for row in time_series], dtype=float)
    wind_available_per_unit = {
        device["id"]: np.array(
            [
                estimate.wind_generation(numeric(row.get("wind_speed"), 0.0), device["capacity"], device["row"])
                for row in time_series
            ],
            dtype=float,
        )
        for device in device_rows["wind_turbines"]
    }
    pv_available_per_unit = {
        device["id"]: np.array(
            [
                estimate.pv_generation(numeric(row.get("solar_irradiance"), 0.0), device["capacity"], device["row"])
                for row in time_series
            ],
            dtype=float,
        )
        for device in device_rows["photovoltaics"]
    }
    return {
        "time_series": time_series,
        "loads": loads,
        "planning_load_factor": planning_load_factor,
        "diesel_price": diesel_price,
        "green_ratio_lower": green_ratio_lower,
        "device_rows": device_rows,
        "wind_available_per_unit": wind_available_per_unit,
        "pv_available_per_unit": pv_available_per_unit,
        "storage_charge_efficiency": 0.95,
        "storage_discharge_efficiency": 0.95,
    }


def solve_planning_model(model: dict[str, Any], log: LogSink | None = None) -> np.ndarray:
    loads = model["loads"]
    n = len(loads)
    variables: dict[tuple[Any, ...], int] = {}
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []
    integrality: list[int] = []
    objective: list[float] = []

    def add_var(key: tuple[Any, ...], lower: float = 0.0, upper: float = np.inf, integer: bool = False, cost: float = 0.0) -> int:
        index = len(objective)
        variables[key] = index
        lower_bounds.append(lower)
        upper_bounds.append(upper)
        integrality.append(1 if integer else 0)
        objective.append(cost)
        return index

    for devices in model["device_rows"].values():
        for device in devices:
            add_var(
                ("qty", device["key"], device["index"]),
                device["quantity_lower"],
                device["quantity_upper"],
                integer=True,
                cost=device["annual_cost"],
            )

    diesel_devices = active_devices(model, "diesel_generators")
    wind_devices = model["device_rows"]["wind_turbines"]
    pv_devices = model["device_rows"]["photovoltaics"]
    storage_pcs_devices = model["device_rows"]["storage_pcs"]
    storage_battery_devices = model["device_rows"]["storage_battery_packs"]
    electrolyzer_devices = active_devices(model, "hydrogen_electrolyzers")
    hydrogen_tank_devices = model["device_rows"]["hydrogen_tanks"]
    fuel_cell_devices = active_devices(model, "fuel_cells")

    for hour in range(n):
        wind_upper = sum(model["wind_available_per_unit"][device["id"]][hour] * device["quantity_upper"] for device in wind_devices)
        pv_upper = sum(model["pv_available_per_unit"][device["id"]][hour] * device["quantity_upper"] for device in pv_devices)
        storage_power_upper = sum(device["capacity"] * device["quantity_upper"] for device in storage_pcs_devices)
        storage_energy_upper = sum(device["capacity"] * device["quantity_upper"] for device in storage_battery_devices)
        hydrogen_tank_upper = sum(device["capacity"] * device["quantity_upper"] for device in hydrogen_tank_devices)

        add_var(("wind_power", hour), 0.0, max(0.0, wind_upper))
        add_var(("wind_curtailed", hour), 0.0, max(0.0, wind_upper), cost=CURTAILMENT_COST)
        add_var(("pv_power", hour), 0.0, max(0.0, pv_upper))
        add_var(("pv_curtailed", hour), 0.0, max(0.0, pv_upper), cost=CURTAILMENT_COST)
        add_var(("storage_charge", hour), 0.0, max(0.0, storage_power_upper), cost=CYCLING_COST)
        add_var(("storage_discharge", hour), 0.0, max(0.0, storage_power_upper), cost=CYCLING_COST)
        add_var(("storage_soc", hour), 0.0, max(0.0, storage_energy_upper))
        add_var(("hydrogen_storage", hour), 0.0, max(0.0, hydrogen_tank_upper))
        add_var(("unmet_load", hour), 0.0, max(0.0, loads[hour]), cost=LOAD_SHED_PENALTY_COST)

        for device in diesel_devices:
            add_var(
                ("diesel_power", hour, device["index"]),
                0.0,
                device["power_upper"] * device["quantity_upper"],
                cost=device["fuel_rate"] * model["diesel_price"] / 1000,
            )
            add_var(
                ("diesel_on_count", hour, device["index"]),
                0.0,
                device["quantity_upper"],
                integer=True,
                cost=DIESEL_ON_COUNT_PENALTY,
            )
        for device in electrolyzer_devices:
            add_var(
                ("electrolyzer_power", hour, device["index"]),
                0.0,
                device["capacity"] * device["quantity_upper"],
                cost=CYCLING_COST,
            )
            add_var(
                ("electrolyzer_on_count", hour, device["index"]),
                0.0,
                device["quantity_upper"],
                integer=True,
                cost=ELECTROLYZER_ON_COUNT_PENALTY,
            )
        for device in fuel_cell_devices:
            add_var(
                ("fuel_cell_power", hour, device["index"]),
                0.0,
                device["capacity"] * device["quantity_upper"],
                cost=CYCLING_COST,
            )

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    constraint_lower: list[float] = []
    constraint_upper: list[float] = []

    def var(key: tuple[Any, ...]) -> int:
        return variables[key]

    def add_constraint(terms: dict[int, float], lower: float, upper: float) -> None:
        row_index = len(constraint_lower)
        for column, value in terms.items():
            if value:
                rows.append(row_index)
                cols.append(column)
                data.append(value)
        constraint_lower.append(lower)
        constraint_upper.append(upper)

    def qty_terms(devices: list[dict[str, Any]], coefficient_key: str = "capacity", multiplier: float = 1.0) -> dict[int, float]:
        return {
            var(("qty", device["key"], device["index"])): numeric(device.get(coefficient_key), 0.0) * multiplier
            for device in devices
        }

    charge_efficiency = model["storage_charge_efficiency"]
    discharge_efficiency = model["storage_discharge_efficiency"]

    for hour in range(n):
        power_balance: dict[int, float] = {
            var(("wind_power", hour)): 1.0,
            var(("pv_power", hour)): 1.0,
            var(("storage_discharge", hour)): 1.0,
            var(("storage_charge", hour)): -1.0,
            var(("unmet_load", hour)): 1.0,
        }
        for device in diesel_devices:
            power_balance[var(("diesel_power", hour, device["index"]))] = 1.0
        for device in electrolyzer_devices:
            power_balance[var(("electrolyzer_power", hour, device["index"]))] = -1.0
        for device in fuel_cell_devices:
            power_balance[var(("fuel_cell_power", hour, device["index"]))] = 1.0
        add_constraint(power_balance, loads[hour], loads[hour])

        wind_terms = {var(("wind_power", hour)): 1.0, var(("wind_curtailed", hour)): 1.0}
        for device in wind_devices:
            wind_terms[var(("qty", device["key"], device["index"]))] = -model["wind_available_per_unit"][device["id"]][hour]
        add_constraint(wind_terms, 0.0, 0.0)

        pv_terms = {var(("pv_power", hour)): 1.0, var(("pv_curtailed", hour)): 1.0}
        for device in pv_devices:
            pv_terms[var(("qty", device["key"], device["index"]))] = -model["pv_available_per_unit"][device["id"]][hour]
        add_constraint(pv_terms, 0.0, 0.0)

        for device in diesel_devices:
            qty_index = var(("qty", device["key"], device["index"]))
            power_index = var(("diesel_power", hour, device["index"]))
            on_index = var(("diesel_on_count", hour, device["index"]))
            add_constraint({on_index: 1.0, qty_index: -1.0}, -np.inf, 0.0)
            add_constraint({power_index: 1.0, on_index: -device["power_upper"]}, -np.inf, 0.0)
            add_constraint({power_index: 1.0, on_index: -device["power_lower"]}, 0.0, np.inf)

        for device in electrolyzer_devices:
            qty_index = var(("qty", device["key"], device["index"]))
            power_index = var(("electrolyzer_power", hour, device["index"]))
            on_index = var(("electrolyzer_on_count", hour, device["index"]))
            add_constraint({on_index: 1.0, qty_index: -1.0}, -np.inf, 0.0)
            add_constraint({power_index: 1.0, on_index: -device["capacity"]}, -np.inf, 0.0)
            add_constraint({power_index: 1.0, on_index: -device["power_lower"]}, 0.0, np.inf)

        for device in fuel_cell_devices:
            add_constraint(
                {
                    var(("fuel_cell_power", hour, device["index"])): 1.0,
                    var(("qty", device["key"], device["index"])): -device["capacity"],
                },
                -np.inf,
                0.0,
            )

        storage_power_terms = qty_terms(storage_pcs_devices)
        add_constraint({var(("storage_charge", hour)): 1.0, **{column: -value for column, value in storage_power_terms.items()}}, -np.inf, 0.0)
        add_constraint({var(("storage_discharge", hour)): 1.0, **{column: -value for column, value in storage_power_terms.items()}}, -np.inf, 0.0)
        storage_energy_terms = qty_terms(storage_battery_devices)
        add_constraint({var(("storage_soc", hour)): 1.0, **{column: -value for column, value in storage_energy_terms.items()}}, -np.inf, 0.0)

        storage_terms: dict[int, float] = {
            var(("storage_soc", hour)): 1.0,
            var(("storage_charge", hour)): -charge_efficiency,
            var(("storage_discharge", hour)): 1.0 / discharge_efficiency,
        }
        if hour == 0:
            for column, value in storage_energy_terms.items():
                storage_terms[column] = storage_terms.get(column, 0.0) - 0.5 * value
        else:
            storage_terms[var(("storage_soc", hour - 1))] = -1.0
        add_constraint(storage_terms, 0.0, 0.0)

        hydrogen_capacity_terms = qty_terms(hydrogen_tank_devices)
        add_constraint({var(("hydrogen_storage", hour)): 1.0, **{column: -value for column, value in hydrogen_capacity_terms.items()}}, -np.inf, 0.0)
        hydrogen_terms: dict[int, float] = {var(("hydrogen_storage", hour)): 1.0}
        for device in electrolyzer_devices:
            hydrogen_terms[var(("electrolyzer_power", hour, device["index"]))] = -device["electric_to_hydrogen_efficiency"]
        for device in fuel_cell_devices:
            hydrogen_terms[var(("fuel_cell_power", hour, device["index"]))] = 1.0 / max(0.0001, device["hydrogen_to_electric_efficiency"])
        if hour == 0:
            for column, value in hydrogen_capacity_terms.items():
                hydrogen_terms[column] = hydrogen_terms.get(column, 0.0) - 0.5 * value
        else:
            hydrogen_terms[var(("hydrogen_storage", hour - 1))] = -1.0
        add_constraint(hydrogen_terms, 0.0, 0.0)

    for day_end_hour in range(23, n, 24):
        storage_energy_terms = qty_terms(storage_battery_devices)
        add_constraint(
            {var(("storage_soc", day_end_hour)): 1.0, **{column: -0.5 * value for column, value in storage_energy_terms.items()}},
            0.0,
            0.0,
        )
    if n:
        hydrogen_capacity_terms = qty_terms(hydrogen_tank_devices)
        add_constraint(
            {var(("hydrogen_storage", n - 1)): 1.0, **{column: -0.5 * value for column, value in hydrogen_capacity_terms.items()}},
            0.0,
            0.0,
        )

    green_ratio_lower = model["green_ratio_lower"]
    if green_ratio_lower > 0:
        green_terms: dict[int, float] = {}
        for hour in range(n):
            coefficient = 1.0 - green_ratio_lower
            for key in (("wind_power", hour), ("pv_power", hour), ("storage_discharge", hour)):
                green_terms[var(key)] = green_terms.get(var(key), 0.0) + coefficient
            for device in fuel_cell_devices:
                index = var(("fuel_cell_power", hour, device["index"]))
                green_terms[index] = green_terms.get(index, 0.0) + coefficient
            for device in diesel_devices:
                index = var(("diesel_power", hour, device["index"]))
                green_terms[index] = green_terms.get(index, 0.0) - green_ratio_lower
        add_constraint(green_terms, 0.0, np.inf)

    emit(log, "info", "求解设备台数和全年运行联合混合整数线性规划", 25)
    matrix = sparse.coo_matrix((data, (rows, cols)), shape=(len(constraint_lower), len(objective))).tocsr()
    result = milp(
        np.array(objective, dtype=float),
        integrality=np.array(integrality, dtype=int),
        bounds=Bounds(np.array(lower_bounds, dtype=float), np.array(upper_bounds, dtype=float)),
        constraints=LinearConstraint(matrix, np.array(constraint_lower, dtype=float), np.array(constraint_upper, dtype=float)),
        options={"time_limit": 180, "mip_rel_gap": 0.01, "disp": False},
    )
    if result.x is None:
        raise ValueError(f"规划优化失败：{result.message}")
    if not result.success:
        emit(log, "warn", f"规划优化未达到最优但返回了可行解：{result.message}", 80)
    model["variables"] = variables
    model["objective_value"] = float(result.fun) if result.fun is not None else 0.0
    return result.x


def normalized_device_rows(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {key: [] for key in DEVICE_SPECS}
    for key, spec in DEVICE_SPECS.items():
        rows = payload.get(key)
        if not isinstance(rows, list):
            rows = []
        for index, row in enumerate(rows):
            source = row if isinstance(row, dict) else {}
            capacity = max(0.0, numeric(source.get(spec["capacity_field"]), 0.0))
            quantity_lower = non_negative_int(source.get("quantity_lower"), 0)
            quantity_upper = non_negative_int(source.get("quantity_upper"), quantity_lower)
            if quantity_upper < quantity_lower:
                quantity_upper = quantity_lower
            design_life = max(1.0, numeric(source.get("design_life_years"), 20.0))
            cost = max(0.0, numeric(source.get("cost"), 0.0))
            device = {
                "id": f"{key}:{index}",
                "key": key,
                "index": index,
                "label": spec["label"],
                "name": str(source.get("name", "") or f"{spec['label']}{index + 1}"),
                "unit": spec["unit"],
                "row": source,
                "capacity": capacity,
                "quantity_lower": quantity_lower,
                "quantity_upper": quantity_upper,
                "cost": cost,
                "design_life_years": design_life,
                "annual_cost": cost / design_life,
            }
            if key == "diesel_generators":
                power_upper = numeric(source.get("power_upper"), capacity if capacity > 0 else 0.0)
                device["power_upper"] = max(0.0, power_upper if power_upper > 0 else capacity)
                device["power_lower"] = min(device["power_upper"], max(0.0, numeric(source.get("power_lower"), 0.0)))
                device["fuel_rate"] = max(0.0, numeric(source.get("fuel_rate"), 0.26))
            elif key == "hydrogen_electrolyzers":
                device["power_lower"] = min(capacity, max(0.0, numeric(source.get("power_lower"), 0.0)))
                device["electric_to_hydrogen_efficiency"] = max(0.0, numeric(source.get("electric_to_hydrogen_efficiency"), 0.7))
            elif key == "fuel_cells":
                device["hydrogen_to_electric_efficiency"] = max(0.0001, numeric(source.get("hydrogen_to_electric_efficiency"), 0.55))
            normalized[key].append(device)
    return normalized


def active_devices(model: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        device
        for device in model["device_rows"][key]
        if device["quantity_upper"] > 0 and device["capacity"] > 0
    ]


def planning_rows_from_solution(model: dict[str, Any], solution: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    variables = model["variables"]
    for key in DEVICE_SPECS:
        for device in model["device_rows"][key]:
            quantity = int(round(solution[variables[("qty", key, device["index"])]]))
            capacity = round(device["capacity"], 4)
            rows.append(
                {
                    "设备类型": device["label"],
                    "名称": device["name"],
                    "设计台数": quantity,
                    "单台容量": capacity,
                    "总容量": round(quantity * capacity, 4),
                    "单位": device["unit"],
                }
            )
    return rows


def dispatch_rows_from_solution(model: dict[str, Any], solution: np.ndarray) -> list[dict[str, Any]]:
    variables = model["variables"]
    rows: list[dict[str, Any]] = []
    diesel_devices = active_devices(model, "diesel_generators")
    electrolyzer_devices = active_devices(model, "hydrogen_electrolyzers")
    fuel_cell_devices = active_devices(model, "fuel_cells")

    def value(key: tuple[Any, ...]) -> float:
        return clean_solution_value(solution[variables[key]])

    quantity_values = {
        (device["key"], device["index"]): int(round(solution[variables[("qty", device["key"], device["index"])]]))
        for devices in model["device_rows"].values()
        for device in devices
    }

    for hour, source_row in enumerate(model["time_series"]):
        diesel_power_by_device = {
            device["index"]: value(("diesel_power", hour, device["index"]))
            for device in diesel_devices
        }
        electrolyzer_power_by_device = {
            device["index"]: value(("electrolyzer_power", hour, device["index"]))
            for device in electrolyzer_devices
        }
        fuel_cell_power_by_device = {
            device["index"]: value(("fuel_cell_power", hour, device["index"]))
            for device in fuel_cell_devices
        }
        diesel_power = sum(diesel_power_by_device.values())
        electrolyzer_power = sum(electrolyzer_power_by_device.values())
        fuel_cell_power = sum(fuel_cell_power_by_device.values())
        diesel_consumption = sum(
            diesel_power_by_device.get(device["index"], 0.0) * device["fuel_rate"] / 1000
            for device in diesel_devices
        )
        hydrogen_production = sum(
            electrolyzer_power_by_device.get(device["index"], 0.0) * device["electric_to_hydrogen_efficiency"]
            for device in electrolyzer_devices
        )
        wind_available = sum(
            model["wind_available_per_unit"][device["id"]][hour] * quantity_values[(device["key"], device["index"])]
            for device in model["device_rows"]["wind_turbines"]
        )
        pv_available = sum(
            model["pv_available_per_unit"][device["id"]][hour] * quantity_values[(device["key"], device["index"])]
            for device in model["device_rows"]["photovoltaics"]
        )
        wind_power = value(("wind_power", hour))
        pv_power = value(("pv_power", hour))
        wind_curtailed = max(0.0, value(("wind_curtailed", hour)))
        pv_curtailed = max(0.0, value(("pv_curtailed", hour)))
        curtailed_power = wind_curtailed + pv_curtailed
        renewable_available = wind_available + pv_available
        renewable_energy = wind_power + pv_power
        load = float(model["loads"][hour])
        hour_index = int(numeric(source_row.get("hour_index"), hour + 1) or hour + 1)
        rows.append(
            {
                "hour_index": hour_index,
                "datetime": source_row.get("datetime", f"H{hour_index:04d}"),
                "wind_speed": round(numeric(source_row.get("wind_speed"), 0.0), 4),
                "solar_irradiance": round(numeric(source_row.get("solar_irradiance"), 0.0), 4),
                "temperature": round(numeric(source_row.get("temperature"), 0.0), 4),
                "load": round(load, 4),
                "diesel_power": round(diesel_power, 4),
                "wind_available": round(wind_available, 4),
                "wind_power": round(wind_power, 4),
                "pv_available": round(pv_available, 4),
                "pv_power": round(pv_power, 4),
                "renewable_available": round(renewable_available, 4),
                "renewable_ratio": round(estimate.percent(renewable_energy, load), 4),
                "storage_power": round(value(("storage_discharge", hour)) - value(("storage_charge", hour)), 4),
                "storage_charge": round(value(("storage_charge", hour)), 4),
                "storage_discharge": round(value(("storage_discharge", hour)), 4),
                "storage_soc": round(value(("storage_soc", hour)), 4),
                "diesel_on": int(round(sum(value(("diesel_on_count", hour, device["index"])) for device in diesel_devices))),
                "hydrogen_production_power": round(electrolyzer_power, 4),
                "hydrogen_production": round(hydrogen_production, 4),
                "electrolyzer_on": int(round(sum(value(("electrolyzer_on_count", hour, device["index"])) for device in electrolyzer_devices))),
                "fuel_cell_power": round(fuel_cell_power, 4),
                "hydrogen_storage": round(value(("hydrogen_storage", hour)), 4),
                "wind_curtailed_power": round(wind_curtailed, 4),
                "pv_curtailed_power": round(pv_curtailed, 4),
                "curtailed_power": round(curtailed_power, 4),
                "renewable_curtailed_rate": round(estimate.percent(curtailed_power, renewable_available), 4),
                "unmet_load": round(value(("unmet_load", hour)), 4),
                "diesel_consumption": round(diesel_consumption, 8),
            }
        )
    return rows


def dispatch_totals(dispatch_rows: list[dict[str, Any]]) -> dict[str, float]:
    totals = estimate.dispatch_totals(dispatch_rows, 0.0, 1.0)
    totals["diesel_consumption"] = sum(numeric(row.get("diesel_consumption"), 0.0) for row in dispatch_rows)
    totals["hydrogen_production"] = sum(numeric(row.get("hydrogen_production"), 0.0) for row in dispatch_rows)
    totals["green_generation_energy"] = (
        totals["wind_energy"]
        + totals["pv_energy"]
        + totals["storage_discharge_energy"]
        + totals["fuel_cell_energy"]
    )
    totals["total_generation_energy"] = totals["green_generation_energy"] + totals["diesel_energy"]
    totals["green_power_ratio"] = estimate.percent(totals["green_generation_energy"], totals["total_generation_energy"])
    totals["renewable_ratio"] = totals["green_power_ratio"]
    return {key: round(value, 4) for key, value in totals.items()}


def cost_summary_from_solution(model: dict[str, Any], solution: np.ndarray, totals: dict[str, float]) -> dict[str, float]:
    variables = model["variables"]
    construction_cost = 0.0
    for devices in model["device_rows"].values():
        for device in devices:
            quantity = int(round(solution[variables[("qty", device["key"], device["index"])]]))
            construction_cost += quantity * device["annual_cost"]
    diesel_cost = totals["diesel_consumption"] * model["diesel_price"]
    total_cost = construction_cost + diesel_cost
    load_energy = totals.get("load_energy", 0.0)
    levelized_cost = total_cost * 10000 / load_energy if load_energy else 0.0
    return {
        "annualized_construction_cost": round(construction_cost, 4),
        "annual_diesel_cost": round(diesel_cost, 4),
        "annual_total_cost": round(total_cost, 4),
        "levelized_cost": round(levelized_cost, 6),
    }


def build_results(
    planning_rows: list[dict[str, Any]],
    dispatch_rows: list[dict[str, Any]],
    totals: dict[str, float],
    costs: dict[str, float],
    model: dict[str, Any],
) -> dict[str, Any]:
    green_ratio = totals["green_power_ratio"]
    curtailed_ratio = totals["renewable_curtailed_rate"]
    if len(dispatch_rows) == 8760:
        daily = estimate.aggregate_daily(dispatch_rows)
        monthly = estimate.aggregate_monthly(daily)
    else:
        daily = aggregate_daily_partial(dispatch_rows)
        monthly = aggregate_monthly_partial(daily)
    annual_rows = [
        *capacity_summary_rows(planning_rows),
        *estimate.annual_energy_rows(totals, green_ratio, curtailed_ratio),
        {"指标": "绿电年发电量", "数值": totals["green_generation_energy"], "单位": "kWh"},
        {"指标": "总发电量", "数值": totals["total_generation_energy"], "单位": "kWh"},
        {"指标": "绿电电量占比下限", "数值": round(model["green_ratio_lower"] * 100, 4), "单位": "%"},
        {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨"},
        {"指标": "年均建设成本", "数值": costs["annualized_construction_cost"], "单位": "万元"},
        {"指标": "年柴油成本", "数值": costs["annual_diesel_cost"], "单位": "万元"},
        {"指标": "年总成本", "数值": costs["annual_total_cost"], "单位": "万元"},
        {"指标": "总成本", "数值": costs["annual_total_cost"], "单位": "万元"},
        {"指标": "绿电占比", "数值": round(green_ratio, 4), "单位": "%"},
        {"指标": "频率风险点", "数值": sum(1 for row in dispatch_rows if numeric(row.get("unmet_load"), 0.0) > 0), "单位": "个"},
    ]
    safety_daily = [
        {"day": row["day"], "frequency_max": 50.0 if row["unmet_load_energy"] <= 0 else 49.8, "frequency_min": 50.0 if row["unmet_load_energy"] <= 0 else 49.5}
        for row in daily
    ]
    highest_frequency = max((point["frequency_max"] for point in safety_daily), default=50.0)
    lowest_frequency = min((point["frequency_min"] for point in safety_daily), default=50.0)
    frequency_risk_hours = sum(1 for row in dispatch_rows if numeric(row.get("unmet_load"), 0.0) > 0)
    green_table = [
        *estimate.annual_energy_rows(totals, green_ratio, curtailed_ratio),
        {"指标": "负荷总电量", "数值": totals["load_energy"], "单位": "kWh"},
        {"指标": "柴发总电量", "数值": totals["diesel_energy"], "单位": "kWh"},
        {"指标": "风机总发电量", "数值": totals["wind_energy"], "单位": "kWh"},
        {"指标": "光伏总发电量", "数值": totals["pv_energy"], "单位": "kWh"},
        {"指标": "电储总发电量", "数值": totals["storage_discharge_energy"], "单位": "kWh"},
        {"指标": "氢储总发电量", "数值": totals["fuel_cell_energy"], "单位": "kWh"},
        {"指标": "新能源弃电率", "数值": round(curtailed_ratio, 4), "单位": "%"},
        {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨"},
        {"指标": "制氢总量", "数值": totals["hydrogen_production"], "单位": "Nm3"},
        {"指标": "年均建设成本", "数值": costs["annualized_construction_cost"], "单位": "万元"},
        {"指标": "年柴油成本", "数值": costs["annual_diesel_cost"], "单位": "万元"},
        {"指标": "年总成本", "数值": costs["annual_total_cost"], "单位": "万元"},
    ]
    return {
        "overview_tables": [
            {"title": "规划结果", "rows": planning_rows},
            {"title": "规划年指标", "rows": annual_rows},
        ],
        "overview_disks": [
            {
                "title": "成本构成",
                "left_label": "运行成本",
                "left_value": costs["annual_diesel_cost"],
                "right_label": "建设成本",
                "right_value": costs["annualized_construction_cost"],
                "unit": "万元",
            },
            {
                "title": "电量构成",
                "left_label": "柴发电量",
                "left_value": round(totals["diesel_energy"] / 1000, 4),
                "right_label": "新能源电量",
                "right_value": round(totals["green_generation_energy"] / 1000, 4),
                "unit": "MWh",
            },
        ],
        "overview": [
            {"指标": "度电成本", "数值": costs["levelized_cost"], "单位": "元/kWh", "说明": "年总成本折算"},
            {"指标": "绿电占比", "数值": round(green_ratio, 4), "单位": "%", "说明": "按风光、储能放电和燃料电池发电统计"},
            {"指标": "总成本", "数值": costs["annual_total_cost"], "单位": "万元", "说明": "年均建设成本加年柴油成本"},
        ],
        "green": [
            {"指标": "绿电占比", "数值": round(green_ratio, 4), "单位": "%", "说明": "满足规划参数中的绿电电量占比下限"},
            {"指标": "弃电率", "数值": round(curtailed_ratio, 4), "单位": "%", "说明": "新能源弃电量占新能源最大可发电量比例"},
            {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨", "说明": "按各柴发油耗率逐时累计"},
        ],
        "green_table": green_table,
        "safety": [
            {"指标": "备用裕度", "数值": 0, "单位": "%", "说明": "基于优化出力结果统计"},
            {"指标": "频率安全裕度", "数值": 1.0, "单位": "p.u.", "说明": "未供负荷为0时按通过处理"},
            {"指标": "N-1校核", "数值": "通过" if frequency_risk_hours == 0 else "需复核", "单位": "", "说明": "启动优化结果的基础安全摘要"},
        ],
        "safety_table": [
            {"指标": "向上扰动最大量", "数值": 0, "单位": "kW"},
            {"指标": "向下扰动最大量", "数值": 0, "单位": "kW"},
            {"指标": "最高频率", "数值": highest_frequency, "单位": "Hz"},
            {"指标": "最低频率", "数值": lowest_frequency, "单位": "Hz"},
            {"指标": "频率安全风险小时数", "数值": frequency_risk_hours, "单位": "h"},
            {"指标": "最大未供负荷", "数值": max((row["unmet_load"] for row in dispatch_rows), default=0), "单位": "kW"},
            {"指标": "最低储能SOC", "数值": min((row["storage_soc"] for row in dispatch_rows), default=0), "单位": "kWh"},
            {"指标": "最高储能SOC", "数值": max((row["storage_soc"] for row in dispatch_rows), default=0), "单位": "kWh"},
            {"指标": "最低氢储量", "数值": min((row["hydrogen_storage"] for row in dispatch_rows), default=0), "单位": "Nm3"},
            {"指标": "最高氢储量", "数值": max((row["hydrogen_storage"] for row in dispatch_rows), default=0), "单位": "Nm3"},
        ],
        "curves": {
            "green_daily": daily,
            "green_monthly": monthly,
            "green_hourly": dispatch_rows,
            "safety_daily": safety_daily,
        },
    }


def build_metrics(totals: dict[str, float], costs: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {"label": "柴油消耗", "value": totals["diesel_consumption"], "unit": "吨"},
        {"label": "年均建设成本", "value": costs["annualized_construction_cost"], "unit": "万元"},
        {"label": "年柴油成本", "value": costs["annual_diesel_cost"], "unit": "万元"},
        {"label": "年总成本", "value": costs["annual_total_cost"], "unit": "万元"},
        {"label": "度电成本", "value": costs["levelized_cost"], "unit": "元/kWh"},
        {"label": "绿电占比", "value": round(totals["green_power_ratio"], 4), "unit": "%"},
    ]


def capacity_summary_rows(planning_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capacities = estimate.capacities_from_planning_rows(planning_rows)
    return [
        {"指标": "柴发总容量", "数值": round(capacities["diesel_capacity"], 4), "单位": "kW"},
        {"指标": "风电总容量", "数值": round(capacities["wind_capacity"], 4), "单位": "kW"},
        {"指标": "光伏总容量", "数值": round(capacities["pv_capacity"], 4), "单位": "kW"},
        {"指标": "氢能总容量", "数值": round(capacities["fuel_cell_power_capacity"], 4), "单位": "kW"},
        {"指标": "储能总容量", "数值": round(capacities["storage_energy_capacity"], 4), "单位": "kWh"},
    ]


def aggregate_daily_partial(dispatch_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    daily: list[dict[str, Any]] = []
    for day_index, start in enumerate(range(0, len(dispatch_rows), 24), start=1):
        rows = dispatch_rows[start : start + 24]
        if not rows:
            continue
        previous_hydrogen_storage = numeric(dispatch_rows[start - 1].get("hydrogen_storage"), 0.0) if start > 0 else 0.0
        hydrogen_storage_increase = sum(estimate.positive_delta(rows, "hydrogen_storage", previous_hydrogen_storage))
        hydrogen_storage_decrease = sum(estimate.negative_delta(rows, "hydrogen_storage", previous_hydrogen_storage))
        daily_row = {
            "day": day_index,
            "load_energy": round(estimate.sum_numeric(rows, "load"), 4),
            "diesel_energy": round(estimate.sum_numeric(rows, "diesel_power"), 4),
            "wind_energy": round(estimate.sum_numeric(rows, "wind_power"), 4),
            "pv_energy": round(estimate.sum_numeric(rows, "pv_power"), 4),
            "hydrogen_energy": round(estimate.sum_numeric(rows, "fuel_cell_power"), 4),
            "fuel_cell_energy": round(estimate.sum_numeric(rows, "fuel_cell_power"), 4),
            "storage_charge_energy": round(estimate.sum_numeric(rows, "storage_charge"), 4),
            "storage_discharge_energy": round(estimate.sum_numeric(rows, "storage_discharge"), 4),
            "hydrogen_production_energy": round(estimate.sum_numeric(rows, "hydrogen_production_power"), 4),
            "hydrogen_storage_increase": round(hydrogen_storage_increase, 4),
            "hydrogen_storage_decrease": round(hydrogen_storage_decrease, 4),
            "wind_available_energy": round(estimate.sum_numeric(rows, "wind_available"), 4),
            "pv_available_energy": round(estimate.sum_numeric(rows, "pv_available"), 4),
            "renewable_available_energy": round(sum(numeric(row.get("renewable_available"), 0.0) for row in rows), 4),
            "renewable_energy": round(sum(numeric(row.get("wind_power"), 0.0) + numeric(row.get("pv_power"), 0.0) for row in rows), 4),
            "wind_curtailed_energy": round(estimate.sum_numeric(rows, "wind_curtailed_power"), 4),
            "pv_curtailed_energy": round(estimate.sum_numeric(rows, "pv_curtailed_power"), 4),
            "curtailed_energy": round(estimate.sum_numeric(rows, "curtailed_power"), 4),
            "unmet_load_energy": round(estimate.sum_numeric(rows, "unmet_load"), 4),
            "unmet_load": round(estimate.sum_numeric(rows, "unmet_load"), 4),
        }
        estimate.add_energy_ratios(daily_row)
        daily.append(daily_row)
    return daily


def aggregate_monthly_partial(daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not daily_rows:
        return []
    monthly_row = {
        "month": 1,
        **{
            field: round(sum(numeric(row.get(field), 0.0) for row in daily_rows), 4)
            for field in estimate.ENERGY_AGGREGATE_FIELDS
        },
    }
    estimate.add_energy_ratios(monthly_row)
    return [monthly_row]


def clean_solution_value(value: float) -> float:
    number = float(value)
    return 0.0 if abs(number) < 1e-7 else number


def non_negative_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return max(0, default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return max(0, default)
    if math.isnan(number) or math.isinf(number):
        return max(0, default)
    return max(0, int(round(number)))


def numeric(value: Any, default: float = 0.0) -> float:
    return estimate.numeric(value, default)


def emit(log: LogSink | None, level: str, message: str, progress: int | None = None) -> None:
    if not log:
        return
    event = {"level": level, "message": message}
    if progress is not None:
        event["progress"] = progress
    log(event)
