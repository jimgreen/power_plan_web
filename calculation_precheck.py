"""Fast feasibility checks shared by planning optimization and evaluation."""

from __future__ import annotations

import estimate
import plan_optimizer


FAST_FEASIBILITY_EPS = 1e-7


def validate_optimization_fast_feasibility(scheme_payload: dict) -> None:
    """Reject planning cases that are provably infeasible before spawning a solver."""

    _validate_fast_feasibility(scheme_payload, mode="optimization")


def validate_evaluation_fast_feasibility(scheme_payload: dict, planning_result_rows: list[dict]) -> None:
    """Reject fixed-result evaluation cases that are provably infeasible before spawning a solver."""

    fixed_payload = estimate.fixed_quantity_payload(scheme_payload, planning_result_rows)
    _validate_fast_feasibility(fixed_payload, mode="evaluation")


def _validate_fast_feasibility(scheme_payload: dict, *, mode: str) -> None:
    device_rows = plan_optimizer.normalized_device_rows(scheme_payload)
    planning_parameters = estimate.first_row(scheme_payload.get("planning_parameters"))
    green_ratio_lower = min(1.0, max(0.0, estimate.numeric(planning_parameters.get("green_power_ratio_lower"), 0.0)))
    initial_storage_soc_ratio = min(1.0, max(0.0, estimate.numeric(planning_parameters.get("initial_storage_soc_ratio"), 0.5)))
    initial_hydrogen_storage_ratio = min(
        1.0,
        max(0.0, estimate.numeric(planning_parameters.get("initial_hydrogen_storage_ratio"), 0.5)),
    )
    time_series = scheme_payload.get("time_series") if isinstance(scheme_payload.get("time_series"), list) else []
    prefix = "评估启动失败" if mode == "evaluation" else "规划求解启动失败"

    wind_upper_capacity = _fast_device_capacity(device_rows["wind_turbines"], "quantity_upper")
    pv_upper_capacity = _fast_device_capacity(device_rows["photovoltaics"], "quantity_upper")
    if green_ratio_lower > FAST_FEASIBILITY_EPS and wind_upper_capacity <= FAST_FEASIBILITY_EPS and pv_upper_capacity <= FAST_FEASIBILITY_EPS:
        if mode == "evaluation":
            raise ValueError(f"{prefix}：当前结果中风机和光伏设计台数均为0，但绿色电量占比下限大于0，无法满足绿电比例约束。")
        raise ValueError(f"{prefix}：风机数量上限和光伏数量上限均为0，但绿色电量占比下限大于0，无法满足绿电比例约束。")

    _validate_fast_renewable_energy_ratio(
        device_rows,
        time_series,
        green_ratio_lower=green_ratio_lower,
        prefix=prefix,
    )
    _validate_fast_hourly_supply(device_rows, time_series, prefix=prefix)

    if (
        initial_hydrogen_storage_ratio > FAST_FEASIBILITY_EPS
        and _fast_has_lower_bound_with_self_discharge(device_rows["hydrogen_tanks"])
        and _fast_device_capacity(device_rows["hydrogen_electrolyzers"], "quantity_upper") <= FAST_FEASIBILITY_EPS
    ):
        if mode == "evaluation":
            raise ValueError(
                f"{prefix}：当前结果包含储氢罐且储氢自损耗率大于0，但电制氢设计台数为0；"
                "模型要求期末氢储等于初始氢储，自损耗无法补偿，请增加电制氢台数、减少储氢罐台数或将储氢自损耗率设为0。"
            )
        raise ValueError(
            f"{prefix}：储氢罐数量下限大于0且储氢自损耗率大于0，但电制氢数量上限为0；"
            "模型要求期末氢储等于初始氢储，自损耗无法补偿，请调整储氢罐下限、电制氢上限或储氢自损耗率。"
        )

    if (
        initial_storage_soc_ratio > FAST_FEASIBILITY_EPS
        and _fast_has_lower_bound_with_self_discharge(device_rows["storage_battery_packs"])
        and _fast_device_capacity(device_rows["storage_pcs"], "quantity_upper") <= FAST_FEASIBILITY_EPS
    ):
        if mode == "evaluation":
            raise ValueError(
                f"{prefix}：当前结果包含储能电池且电池自损耗率大于0，但储能PCS设计台数为0；"
                "模型要求日末电储等于初始电储，自损耗无法补偿，请增加储能PCS台数、减少储能电池台数或将电池自损耗率设为0。"
            )
        raise ValueError(
            f"{prefix}：储能电池数量下限大于0且电池自损耗率大于0，但储能PCS数量上限为0；"
            "模型要求日末电储等于初始电储，自损耗无法补偿，请调整储能电池下限、储能PCS上限或电池自损耗率。"
        )


def _validate_fast_renewable_energy_ratio(
    device_rows: dict[str, list[dict]],
    time_series: list,
    *,
    green_ratio_lower: float,
    prefix: str,
) -> None:
    if green_ratio_lower <= FAST_FEASIBILITY_EPS or not time_series:
        return
    load_energy = sum(max(0.0, estimate.numeric(row.get("load"), 0.0)) for row in time_series if isinstance(row, dict))
    if load_energy <= FAST_FEASIBILITY_EPS:
        return
    renewable_energy = _fast_renewable_available_energy(device_rows, time_series)
    if renewable_energy + FAST_FEASIBILITY_EPS < load_energy * green_ratio_lower:
        actual_ratio = renewable_energy / load_energy if load_energy > 0 else 0.0
        raise ValueError(
            f"{prefix}：风机和光伏最大可发电量合计为{_format_fast_number(renewable_energy)}kWh，"
            f"负荷电量为{_format_fast_number(load_energy)}kWh，占比{actual_ratio:.2%}，"
            f"低于绿色电量占比要求{green_ratio_lower:.2%}，无法满足绿电比例约束。"
        )


def _validate_fast_hourly_supply(device_rows: dict[str, list[dict]], time_series: list, *, prefix: str) -> None:
    if not time_series:
        return
    diesel_power_upper = sum(
        max(0.0, estimate.numeric(device.get("power_upper"), device.get("capacity", 0.0)))
        * max(0, int(device.get("quantity_upper", 0)))
        for device in device_rows["diesel_generators"]
    )
    for index, row in enumerate(time_series):
        if not isinstance(row, dict):
            continue
        load = max(0.0, estimate.numeric(row.get("load"), 0.0))
        if load <= FAST_FEASIBILITY_EPS:
            continue
        wind_power = _fast_hourly_renewable_power(device_rows["wind_turbines"], row, "wind")
        pv_power = _fast_hourly_renewable_power(device_rows["photovoltaics"], row, "pv")
        max_supply = wind_power + pv_power + diesel_power_upper
        if max_supply + FAST_FEASIBILITY_EPS < load:
            raise ValueError(
                f"{prefix}：第{index + 1}小时风机、光伏和柴发最大供电功率之和小于负荷功率"
                f"（最大供电{_format_fast_number(max_supply)}kW，负荷{_format_fast_number(load)}kW），无法满足功率平衡约束。"
            )


def _fast_renewable_available_energy(device_rows: dict[str, list[dict]], time_series: list) -> float:
    total = 0.0
    for row in time_series:
        if not isinstance(row, dict):
            continue
        total += _fast_hourly_renewable_power(device_rows["wind_turbines"], row, "wind")
        total += _fast_hourly_renewable_power(device_rows["photovoltaics"], row, "pv")
    return total


def _fast_hourly_renewable_power(devices: list[dict], row: dict, family: str) -> float:
    total = 0.0
    for device in devices:
        count = max(0, int(device.get("quantity_upper", 0)))
        if count <= 0:
            continue
        capacity = max(0.0, estimate.numeric(device.get("capacity"), 0.0))
        if capacity <= 0:
            continue
        if family == "wind":
            per_unit = estimate.wind_generation(estimate.numeric(row.get("wind_speed"), 0.0), capacity, device.get("row", {}))
        else:
            per_unit = estimate.pv_generation(estimate.numeric(row.get("solar_irradiance"), 0.0), capacity, device.get("row", {}))
        total += count * per_unit
    return total


def _fast_device_capacity(devices: list[dict], quantity_field: str) -> float:
    return sum(
        max(0.0, estimate.numeric(device.get("capacity"), 0.0)) * max(0, int(device.get(quantity_field, 0)))
        for device in devices
    )


def _fast_has_lower_bound_with_self_discharge(devices: list[dict]) -> bool:
    return any(
        int(device.get("quantity_lower", 0)) > 0
        and estimate.numeric(device.get("capacity"), 0.0) > FAST_FEASIBILITY_EPS
        and estimate.numeric(device.get("self_discharge_rate"), 0.0) > FAST_FEASIBILITY_EPS
        for device in devices
    )


def _format_fast_number(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")
