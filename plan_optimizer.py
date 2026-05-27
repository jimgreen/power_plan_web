#!/usr/bin/env python3
"""Planning optimization with equipment-count decisions and 8760-hour dispatch."""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

import dispatch_milp
import estimate
from milp_solver import CalculationTimeoutError, is_timeout_result, solve_milp


LogSink = Callable[[dict[str, Any]], None]

LOAD_SHED_PENALTY_COST = 1_000_000.0
DIESEL_ON_COUNT_PENALTY = 0.0001
ELECTROLYZER_ON_COUNT_PENALTY = 0.00001
FREQUENCY_EPS = 1e-9
NOMINAL_FREQUENCY_HZ = 50.0

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


def _safe_linspace(v_min: float, v_max: float, n_points: int) -> np.ndarray:
    if float(v_max) - float(v_min) <= FREQUENCY_EPS:
        return np.array([(float(v_min) + float(v_max)) / 2.0], dtype=float)
    return np.linspace(float(v_min), float(v_max), max(2, int(n_points)))


def _shrink_interval(v_min: float, v_max: float, fraction: float) -> tuple[float, float]:
    if float(v_max) - float(v_min) <= FREQUENCY_EPS:
        return float(v_min), float(v_max)
    frac = min(max(float(fraction), FREQUENCY_EPS), 1.0)
    center = 0.5 * (float(v_min) + float(v_max))
    half_width = 0.5 * (float(v_max) - float(v_min)) * frac
    return float(center - half_width), float(center + half_width)


def second_order_coefficients(m_eq: float, k_eq: float, d_eq: float, t_d: float) -> tuple[float, float]:
    alpha = (m_eq + d_eq * t_d) / (m_eq * t_d)
    beta = (d_eq + k_eq / (2.0 * math.pi)) / (m_eq * t_d)
    return alpha, beta


def frequency_rocof_initial_hz_per_s(delta_p_mw: float, m_eq: float) -> float:
    if m_eq <= FREQUENCY_EPS:
        return math.nan
    return -float(delta_p_mw) / (2.0 * math.pi * float(m_eq))


def steady_state_frequency_hz(
    m_eq: float,
    k_eq: float,
    d_eq: float,
    delta_p_mw: float,
    *,
    nominal_frequency_hz: float = NOMINAL_FREQUENCY_HZ,
) -> float:
    del m_eq
    denom = float(d_eq) + float(k_eq) / (2.0 * math.pi)
    if denom <= FREQUENCY_EPS:
        return math.nan
    omega_ss = -float(delta_p_mw) / denom
    return float(nominal_frequency_hz) + omega_ss / (2.0 * math.pi)


def frequency_extreme_hz_exact(
    m_eq: float,
    k_eq: float,
    d_eq: float,
    t_d: float,
    delta_p_mw: float,
    *,
    t_end: float,
    seek: str,
    nominal_frequency_hz: float = NOMINAL_FREQUENCY_HZ,
) -> float:
    if seek not in {"min", "max"}:
        raise ValueError(f"unsupported frequency extreme selector: {seek}")
    if m_eq <= FREQUENCY_EPS or t_d <= FREQUENCY_EPS:
        return math.nan

    alpha, beta = second_order_coefficients(m_eq, k_eq, d_eq, t_d)
    if beta <= FREQUENCY_EPS:
        return math.nan

    denom = d_eq + k_eq / (2.0 * math.pi)
    if denom <= FREQUENCY_EPS:
        return math.nan
    omega_ss = -delta_p_mw / denom
    disc = alpha**2 - 4.0 * beta
    candidates = [0.0, float(t_end)]

    def omega_under(t_star: float) -> float | None:
        omega_n = math.sqrt(beta)
        zeta = alpha / (2.0 * omega_n)
        if zeta >= 1.0:
            return None
        omega_d_sq = beta * (1.0 - zeta**2)
        if omega_d_sq <= FREQUENCY_EPS:
            return None
        omega_d = math.sqrt(omega_d_sq)
        a = -omega_ss
        b = (-delta_p_mw / m_eq + zeta * omega_n * a) / omega_d
        return omega_ss + math.exp(-zeta * omega_n * t_star) * (
            a * math.cos(omega_d * t_star) + b * math.sin(omega_d * t_star)
        )

    def omega_over(t_star: float) -> float | None:
        sqrt_disc = math.sqrt(max(disc, 0.0))
        lam1 = -0.5 * alpha + 0.5 * sqrt_disc
        lam2 = -0.5 * alpha - 0.5 * sqrt_disc
        denom_lam = lam1 - lam2
        if abs(denom_lam) <= FREQUENCY_EPS:
            return None
        c1 = (-delta_p_mw / m_eq + omega_ss * lam2) / denom_lam
        c2 = -omega_ss - c1
        return omega_ss + c1 * math.exp(lam1 * t_star) + c2 * math.exp(lam2 * t_star)

    if disc < -FREQUENCY_EPS:
        omega_n = math.sqrt(beta)
        zeta = alpha / (2.0 * omega_n)
        omega_d_sq = beta * (1.0 - zeta**2)
        if omega_d_sq <= FREQUENCY_EPS:
            return math.nan
        omega_d = math.sqrt(omega_d_sq)
        a = -omega_ss
        b = (-delta_p_mw / m_eq + zeta * omega_n * a) / omega_d
        angle = math.atan2(
            omega_d * b - zeta * omega_n * a,
            zeta * omega_n * b + omega_d * a,
        )
        if angle <= 0.0:
            angle += math.pi
        t_star = angle / omega_d
        if 0.0 < t_star < t_end:
            candidates.append(float(t_star))
        omega_values = [omega_under(t_star) for t_star in candidates]
    elif disc > FREQUENCY_EPS:
        sqrt_disc = math.sqrt(disc)
        lam1 = -0.5 * alpha + 0.5 * sqrt_disc
        lam2 = -0.5 * alpha - 0.5 * sqrt_disc
        if lam1 >= 0.0 or lam2 >= 0.0:
            return math.nan
        denom_lam = lam1 - lam2
        c1 = (-delta_p_mw / m_eq + omega_ss * lam2) / denom_lam
        c2 = -omega_ss - c1
        numer = -c2 * lam2
        denom_ratio = c1 * lam1
        if abs(denom_ratio) > FREQUENCY_EPS and numer > 0.0:
            ratio = numer / denom_ratio
            if ratio > 0.0:
                t_star = math.log(ratio) / (lam1 - lam2)
                if 0.0 < t_star < t_end:
                    candidates.append(float(t_star))
        omega_values = [omega_over(t_star) for t_star in candidates]
    else:
        lam = -0.5 * alpha
        if lam >= 0.0:
            return math.nan
        c1 = -omega_ss
        c2 = -delta_p_mw / m_eq + lam * omega_ss
        if abs(lam * c2) > FREQUENCY_EPS:
            t_star = (delta_p_mw / m_eq) / (lam * c2)
            if 0.0 < t_star < t_end:
                candidates.append(float(t_star))
        omega_values = [
            omega_ss + (c1 + c2 * t_star) * math.exp(lam * t_star)
            for t_star in candidates
        ]

    finite_values = [value for value in omega_values if value is not None and np.isfinite(value)]
    if not finite_values:
        return math.nan
    omega_extreme = min(finite_values) if seek == "min" else max(finite_values)
    return float(nominal_frequency_hz) + omega_extreme / (2.0 * math.pi)


def normalized_frequency_parameters(planning_parameters: dict[str, Any], loads: np.ndarray) -> dict[str, Any]:
    load_ref = max(0.0, numeric(planning_parameters.get("network_synchronization_reference_load_kw"), 0.0))
    if load_ref <= 0:
        load_ref = float(np.max(loads)) if len(loads) else 0.0
    load_ref = max(load_ref, FREQUENCY_EPS)
    nominal_frequency_hz = min(65.0, max(45.0, numeric(planning_parameters.get("nominal_frequency_hz"), NOMINAL_FREQUENCY_HZ)))
    lower_limit = min(nominal_frequency_hz, max(45.0, numeric(planning_parameters.get("frequency_nadir_lower_hz"), 49.5)))
    upper_limit = max(nominal_frequency_hz, min(65.0, numeric(planning_parameters.get("frequency_peak_upper_hz"), 50.5)))
    steady_lower = min(nominal_frequency_hz, max(0.0, numeric(planning_parameters.get("steady_state_frequency_lower_hz"), 49.5)))
    steady_upper = max(nominal_frequency_hz, min(65.0, numeric(planning_parameters.get("steady_state_frequency_upper_hz"), 50.5)))
    return {
        "enabled": truthy_flag(planning_parameters.get("frequency_security_constraint_enabled"), False),
        "storage_frequency_regulation_enabled": truthy_flag(
            planning_parameters.get("storage_frequency_regulation_enabled"), False
        ),
        "nominal_frequency_hz": nominal_frequency_hz,
        "omega0_rad_per_s": 2.0 * math.pi * nominal_frequency_hz,
        "nadir_lower_hz": lower_limit,
        "peak_upper_hz": upper_limit,
        "lower_security_margin_hz": min(2.0, max(0.0, numeric(planning_parameters.get("frequency_lower_security_margin_hz"), 0.0))),
        "upper_security_margin_hz": min(2.0, max(0.0, numeric(planning_parameters.get("frequency_upper_security_margin_hz"), 0.0))),
        "load_frequency_coefficient_d": min(20.0, max(0.0, numeric(planning_parameters.get("load_frequency_coefficient_d"), 0.0))),
        "rocof_upper_hz_per_s": min(20.0, max(FREQUENCY_EPS, numeric(planning_parameters.get("rocof_upper_hz_per_s"), 1.0))),
        "steady_state_frequency_lower_hz": steady_lower,
        "steady_state_frequency_upper_hz": steady_upper,
        "governor_time_constant_s": max(0.0, numeric(planning_parameters.get("frequency_governor_time_constant_s"), 0.6)),
        "nadir_evaluation_duration_s": min(200.0, max(1.0, numeric(planning_parameters.get("frequency_nadir_evaluation_duration_s"), 20.0))),
        "linearization_samples_per_axis": int(min(7, max(2, round(numeric(planning_parameters.get("nadir_linearization_samples_per_axis"), 4))))),
        "linearization_interval_ratio": min(1.0, max(0.05, numeric(planning_parameters.get("nadir_linearization_interval_ratio"), 0.5))),
        "network_synchronization_coefficient_base": min(100.0, max(-100.0, numeric(planning_parameters.get("network_synchronization_coefficient_base"), 1.0))),
        "network_synchronization_coefficient_slope": min(100.0, max(-100.0, numeric(planning_parameters.get("network_synchronization_coefficient_slope"), 0.0))),
        "lower_disturbance_kw": max(0.0, numeric(planning_parameters.get("frequency_lower_disturbance_kw"), 0.0)),
        "upper_disturbance_kw": max(0.0, numeric(planning_parameters.get("frequency_upper_disturbance_kw"), 0.0)),
        "load_ref_kw": load_ref,
        "context_cache": {},
    }


def representative_governor_time_constant(model: dict[str, Any]) -> float:
    configured = float(model.get("frequency", {}).get("governor_time_constant_s", 0.0))
    if configured > FREQUENCY_EPS:
        return configured
    weighted_sum = 0.0
    weight = 0.0
    for device in model["device_rows"].get("diesel_generators", []):
        capacity = max(0.0, float(device.get("power_upper", device.get("capacity", 0.0)))) * max(0, int(device.get("quantity_upper", 0)))
        if capacity <= 0:
            continue
        weighted_sum += capacity * max(FREQUENCY_EPS, float(device.get("governor_time_constant_t", 0.6)))
        weight += capacity
    return weighted_sum / weight if weight > 0 else 0.6


def renewable_available_upper_kw(model: dict[str, Any], hour: int) -> float:
    total = 0.0
    for device in renewable_candidate_devices(model, "wind_turbines"):
        total += float(model["wind_available_per_unit"][device["id"]][hour]) * max(0, int(device.get("quantity_upper", 0)))
    for device in renewable_candidate_devices(model, "photovoltaics"):
        total += float(model["pv_available_per_unit"][device["id"]][hour]) * max(0, int(device.get("quantity_upper", 0)))
    return max(total, 0.0)


def frequency_delta_p_mw(model: dict[str, Any], hour: int, seek: str) -> float:
    freq = model["frequency"]
    if seek == "min":
        disturbance_kw = float(freq.get("lower_disturbance_kw", 0.0))
        if disturbance_kw <= 0:
            disturbance_kw = (
                float(model["loads"][hour]) * float(model.get("load_up_disturbance_factor", 0.0))
                + renewable_available_upper_kw(model, hour) * float(model.get("renewable_down_disturbance_factor", 0.0))
            )
        return max(disturbance_kw, FREQUENCY_EPS) / 1000.0
    disturbance_kw = float(freq.get("upper_disturbance_kw", 0.0))
    if disturbance_kw <= 0:
        disturbance_kw = float(model["loads"][hour]) * float(model.get("load_down_disturbance_factor", 0.0))
    return -max(disturbance_kw, FREQUENCY_EPS) / 1000.0


def frequency_physical_bounds(model: dict[str, Any]) -> dict[str, float]:
    freq = model["frequency"]
    ref = max(float(freq["load_ref_kw"]), FREQUENCY_EPS)
    loads = model["loads"]
    wind_upper = np.zeros(len(loads), dtype=float)
    pv_upper = np.zeros(len(loads), dtype=float)
    for device in renewable_candidate_devices(model, "wind_turbines"):
        wind_upper += model["wind_available_per_unit"][device["id"]] * float(device["quantity_upper"])
    for device in renewable_candidate_devices(model, "photovoltaics"):
        pv_upper += model["pv_available_per_unit"][device["id"]] * float(device["quantity_upper"])
    if len(loads):
        net_ratio_min = float(np.min(-loads / ref))
        net_ratio_max = float(np.max((wind_upper + pv_upper - loads) / ref))
        load_ratio_min = float(np.min(loads / ref))
        load_ratio_max = float(np.max(loads / ref))
    else:
        net_ratio_min = net_ratio_max = load_ratio_min = load_ratio_max = 0.0

    diesel_m_hi = 0.0
    diesel_k_hi = 0.0
    diesel_d_hi = 0.0
    for device in model["device_rows"].get("diesel_generators", []):
        capacity_mw = max(0.0, float(device.get("power_upper", 0.0))) * max(0, int(device.get("quantity_upper", 0))) / 1000.0
        diesel_m_hi += float(device.get("inertia_constant_h", 3.5)) * capacity_mw
        diesel_k_hi += float(device.get("primary_frequency_coefficient_k", 0.4)) * capacity_mw
        diesel_d_hi += float(device.get("damping_coefficient_d", 0.01)) * capacity_mw

    storage_m_hi = 0.0
    storage_k_hi = 0.0
    storage_d_hi = 0.0
    if freq["storage_frequency_regulation_enabled"]:
        for device in model["device_rows"].get("storage_pcs", []):
            if not device.get("is_grid_forming"):
                continue
            capacity_mw = max(0.0, float(device.get("capacity", 0.0))) * max(0, int(device.get("quantity_upper", 0))) / 1000.0
            storage_m_hi += float(device.get("storage_equivalent_inertia_constant_h", 2.5)) * capacity_mw
            storage_k_hi += float(device.get("storage_equivalent_primary_frequency_coefficient_k", 0.5)) * capacity_mw
            storage_d_hi += float(device.get("storage_equivalent_damping_coefficient_d", 0.05)) * capacity_mw

    k_net_candidates = [
        freq["network_synchronization_coefficient_base"] + freq["network_synchronization_coefficient_slope"] * net_ratio_min,
        freq["network_synchronization_coefficient_base"] + freq["network_synchronization_coefficient_slope"] * net_ratio_max,
    ]
    m_hi = 2.0 / float(freq["omega0_rad_per_s"]) * (diesel_m_hi + storage_m_hi)
    k_lo = min(k_net_candidates)
    k_hi = max(k_net_candidates) + diesel_k_hi + storage_k_hi
    d_lo = freq["load_frequency_coefficient_d"] * load_ratio_min
    d_hi = freq["load_frequency_coefficient_d"] * load_ratio_max + diesel_d_hi + storage_d_hi
    return {
        "M_lo": 0.0,
        "M_hi": max(0.0, float(m_hi)),
        "K_lo": float(k_lo),
        "K_hi": float(k_hi),
        "D_lo": float(d_lo),
        "D_hi": float(d_hi),
    }


def build_frequency_linearization_context(model: dict[str, Any], hour: int, seek: str) -> dict[str, float | str]:
    freq = model["frequency"]
    delta_p_mw = frequency_delta_p_mw(model, hour, seek)
    bounds = frequency_physical_bounds(model)
    m_lo, m_hi = _shrink_interval(bounds["M_lo"], bounds["M_hi"], freq["linearization_interval_ratio"])
    k_lo, k_hi = _shrink_interval(bounds["K_lo"], bounds["K_hi"], freq["linearization_interval_ratio"])
    d_lo, d_hi = _shrink_interval(bounds["D_lo"], bounds["D_hi"], freq["linearization_interval_ratio"])
    sample_points = max(2, int(freq["linearization_samples_per_axis"]))
    rows: list[list[float]] = []
    values: list[float] = []
    for m_eq in _safe_linspace(m_lo, m_hi, sample_points):
        for k_eq in _safe_linspace(k_lo, k_hi, sample_points):
            for d_eq in _safe_linspace(d_lo, d_hi, sample_points):
                f_extreme = frequency_extreme_hz_exact(
                    float(m_eq),
                    float(k_eq),
                    float(d_eq),
                    representative_governor_time_constant(model),
                    delta_p_mw,
                    t_end=freq["nadir_evaluation_duration_s"],
                    seek=seek,
                    nominal_frequency_hz=freq["nominal_frequency_hz"],
                )
                if np.isfinite(f_extreme):
                    rows.append([float(m_eq), float(k_eq), float(d_eq), 1.0])
                    values.append(float(f_extreme))
    if len(rows) < 4:
        raise ValueError("频率安全约束无法建立：可行运行区间内有效频率采样点不足，请检查柴发/构网储能容量和频率参数")
    a_matrix = np.asarray(rows, dtype=float)
    y_vector = np.asarray(values, dtype=float)
    coef = np.linalg.lstsq(a_matrix, y_vector, rcond=None)[0]
    pred = a_matrix @ coef
    if seek == "min":
        fit_error = float(max(0.0, np.max(pred - y_vector)))
        freq_ss_limit_hz = float(freq["steady_state_frequency_lower_hz"])
        steady_dk_min = float(abs(delta_p_mw) / max(freq["nominal_frequency_hz"] - freq_ss_limit_hz, FREQUENCY_EPS))
    else:
        fit_error = float(max(0.0, np.max(y_vector - pred)))
        freq_ss_limit_hz = float(freq["steady_state_frequency_upper_hz"])
        steady_dk_min = float(abs(delta_p_mw) / max(freq_ss_limit_hz - freq["nominal_frequency_hz"], FREQUENCY_EPS))
    return {
        "seek": seek,
        "M_lo": float(m_lo),
        "M_hi": float(m_hi),
        "K_lo": float(k_lo),
        "K_hi": float(k_hi),
        "D_lo": float(d_lo),
        "D_hi": float(d_hi),
        "a_M": float(coef[0]),
        "a_K": float(coef[1]),
        "a_D": float(coef[2]),
        "c0": float(coef[3]),
        "fit_error": fit_error,
        "fit_rmse": float(np.sqrt(np.mean((pred - y_vector) ** 2))),
        "delta_p_mw": float(delta_p_mw),
        "rocof_m_min": float(abs(delta_p_mw) / (2.0 * math.pi * max(freq["rocof_upper_hz_per_s"], FREQUENCY_EPS))),
        "steady_dk_min": steady_dk_min,
        "freq_ss_limit_hz": freq_ss_limit_hz,
    }


def frequency_context(model: dict[str, Any], hour: int, seek: str) -> dict[str, Any]:
    freq = model["frequency"]
    delta_key = round(frequency_delta_p_mw(model, hour, seek), 9)
    key = (seek, delta_key)
    cache = freq.setdefault("context_cache", {})
    if key not in cache:
        cache[key] = build_frequency_linearization_context(model, hour, seek)
    return cache[key]

def run_optimization(
    scheme_payload: dict[str, Any],
    log: LogSink | None = None,
    horizon_hours: int | None = None,
    allow_direct_result: bool = True,
) -> dict[str, Any]:
    """Optimize equipment quantities and dispatch as a joint MILP."""

    # Keep validation, model construction, solving and result formatting in
    # separate stages so each stage can be inspected independently.
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
    emit_model_input_summary(model, log)
    emit_device_candidate_summary(model, log)
    emit(log, "info", "已加入台数上下限、建设成本、柴油成本和绿电占比约束", 15)
    direct_result = direct_zero_load_result(model, log) if allow_direct_result else None
    if direct_result is None:
        solution = solve_planning_model(model, log)
        emit(log, "info", "优化求解完成，正在整理规划结果和8760曲线", 85)
        planning_rows = planning_rows_from_solution(model, solution)
        dispatch_rows = dispatch_rows_from_solution(model, solution)
        totals = dispatch_totals(dispatch_rows)
        costs = cost_summary_from_solution(model, solution, totals)
    else:
        planning_rows = direct_result["planning_rows"]
        dispatch_rows = direct_result["dispatch_rows"]
        totals = direct_result["totals"]
        costs = direct_result["costs"]
        emit(log, "info", "解析规划结果完成，正在整理规划结果和8760曲线", 85)
    emit_solution_summary(planning_rows, totals, costs, log)
    results = build_results(planning_rows, dispatch_rows, totals, costs, model)
    metrics = build_metrics(totals, costs)
    emit(log, "ok", "规划求解完成", 100)
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
    # Normalize workbook/UI payload data into arrays and typed device records
    # before the MILP builder sees it.
    planning_parameters = estimate.first_row(scheme_payload.get("planning_parameters"))
    diesel_price = max(0.0, numeric(planning_parameters.get("diesel_price"), 0.0))
    diesel_objective_price = max(
        0.0,
        numeric(scheme_payload.get("_diesel_objective_price"), diesel_price),
    )
    green_ratio_lower = min(1.0, max(0.0, numeric(planning_parameters.get("green_power_ratio_lower"), 0.0)))
    raw_time_limit_minutes = planning_parameters.get(
        "optimization_time_limit_minutes",
        numeric(planning_parameters.get("optimization_time_limit_seconds"), 3600) / 60,
    )
    optimization_time_limit_minutes = int(min(120, max(10, round(numeric(raw_time_limit_minutes, 60)))))
    optimization_time_limit_seconds = optimization_time_limit_minutes * 60
    preferred_solver = normalize_preferred_solver(planning_parameters.get("preferred_solver"))
    initial_storage_soc_ratio = min(1.0, max(0.0, numeric(planning_parameters.get("initial_storage_soc_ratio"), 0.5)))
    initial_hydrogen_storage_ratio = min(
        1.0,
        max(0.0, numeric(planning_parameters.get("initial_hydrogen_storage_ratio"), 0.5)),
    )
    post_disturbance_power_balance_enabled = truthy_flag(planning_parameters.get("post_disturbance_power_balance_enabled"), True)
    device_rows = normalized_device_rows(scheme_payload)
    storage_charge_efficiency, storage_discharge_efficiency = storage_efficiencies(
        device_rows["storage_pcs"],
        numeric(planning_parameters.get("storage_charge_efficiency"), 0.95),
        numeric(planning_parameters.get("storage_discharge_efficiency"), 0.95),
    )
    storage_soc_lower_ratio, storage_soc_upper_ratio = storage_soc_limits(device_rows["storage_battery_packs"])
    storage_self_discharge_rate = fleet_self_discharge_rate(device_rows["storage_battery_packs"], 0.01)
    hydrogen_self_discharge_rate = fleet_self_discharge_rate(device_rows["hydrogen_tanks"], 0.001)
    loads = np.array([max(0.0, numeric(row.get("load"), 0.0)) for row in time_series], dtype=float)
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
    frequency = normalized_frequency_parameters(planning_parameters, loads)
    return {
        "problem_name": str(scheme_payload.get("_optimization_problem_name") or "规划求解"),
        "time_series": time_series,
        "loads": loads,
        "diesel_price": diesel_price,
        "diesel_objective_price": diesel_objective_price,
        "green_ratio_lower": green_ratio_lower,
        "optimization_time_limit_minutes": optimization_time_limit_minutes,
        "optimization_time_limit_seconds": optimization_time_limit_seconds,
        "preferred_solver": preferred_solver,
        "initial_storage_soc_ratio": initial_storage_soc_ratio,
        "initial_hydrogen_storage_ratio": initial_hydrogen_storage_ratio,
        "storage_charge_efficiency": storage_charge_efficiency,
        "storage_discharge_efficiency": storage_discharge_efficiency,
        "storage_self_discharge_rate": storage_self_discharge_rate,
        "hydrogen_self_discharge_rate": hydrogen_self_discharge_rate,
        "post_disturbance_power_balance_enabled": post_disturbance_power_balance_enabled,
        "load_up_disturbance_factor": max(0.0, numeric(planning_parameters.get("load_up_disturbance_factor"), numeric(planning_parameters.get("load_disturbance_factor"), 0.0))),
        "load_down_disturbance_factor": max(0.0, numeric(planning_parameters.get("load_down_disturbance_factor"), numeric(planning_parameters.get("load_disturbance_factor"), 0.0))),
        "renewable_down_disturbance_factor": max(0.0, numeric(planning_parameters.get("renewable_down_disturbance_factor"), 0.0)),
        "frequency": frequency,
        "storage_soc_lower_ratio": storage_soc_lower_ratio,
        "storage_soc_upper_ratio": storage_soc_upper_ratio,
        "device_rows": device_rows,
        "wind_available_per_unit": wind_available_per_unit,
        "pv_available_per_unit": pv_available_per_unit,
    }


def solve_planning_model(model: dict[str, Any], log: LogSink | None = None) -> np.ndarray:
    loads = model["loads"]
    n = len(loads)
    builder = dispatch_milp.MilpModelBuilder()

    for devices in model["device_rows"].values():
        for device in devices:
            builder.add_var(
                ("qty", device["key"], device["index"]),
                device["quantity_lower"],
                device["quantity_upper"],
                integer=True,
                cost=device["annual_cost"],
            )

    def var(key: tuple[Any, ...]) -> int:
        return builder.var(key)

    diesel_devices = active_devices(model, "diesel_generators")
    wind_devices = renewable_candidate_devices(model, "wind_turbines")
    pv_devices = renewable_candidate_devices(model, "photovoltaics")
    renewable_devices = [*wind_devices, *pv_devices]
    storage_pcs_devices = model["device_rows"]["storage_pcs"]
    grid_storage_pcs_devices = [device for device in storage_pcs_devices if device.get("is_grid_forming")]
    following_storage_pcs_devices = [device for device in storage_pcs_devices if not device.get("is_grid_forming")]
    storage_battery_devices = model["device_rows"]["storage_battery_packs"]
    electrolyzer_devices = active_devices(model, "hydrogen_electrolyzers")
    hydrogen_tank_devices = model["device_rows"]["hydrogen_tanks"]
    fuel_cell_devices = active_devices(model, "fuel_cells")

    for hour in range(n):
        wind_upper = sum(model["wind_available_per_unit"][device["id"]][hour] * device["quantity_upper"] for device in wind_devices)
        pv_upper = sum(model["pv_available_per_unit"][device["id"]][hour] * device["quantity_upper"] for device in pv_devices)
        storage_power_upper = sum(device["capacity"] * device["quantity_upper"] for device in storage_pcs_devices)
        grid_storage_power_upper = sum(device["capacity"] * device["quantity_upper"] for device in grid_storage_pcs_devices)
        storage_energy_upper = sum(device["capacity"] * device["quantity_upper"] for device in storage_battery_devices)
        hydrogen_tank_upper = sum(device["capacity"] * device["quantity_upper"] for device in hydrogen_tank_devices)

        builder.add_var(("wind_power", hour), 0.0, max(0.0, wind_upper))
        builder.add_var(("wind_curtailed", hour), 0.0, max(0.0, wind_upper))
        builder.add_var(("pv_power", hour), 0.0, max(0.0, pv_upper))
        builder.add_var(("pv_curtailed", hour), 0.0, max(0.0, pv_upper))
        add_renewable_hour_variables(builder, hour, renewable_devices)
        builder.add_var(("storage_charge", hour), 0.0, max(0.0, storage_power_upper))
        builder.add_var(("storage_discharge", hour), 0.0, max(0.0, storage_power_upper))
        builder.add_var(("grid_storage_charge", hour), 0.0, max(0.0, grid_storage_power_upper))
        builder.add_var(("grid_storage_discharge", hour), 0.0, max(0.0, grid_storage_power_upper))
        builder.add_var(("storage_charge_on", hour), 0.0, 1.0, integer=True)
        builder.add_var(("storage_discharge_on", hour), 0.0, 1.0, integer=True)
        builder.add_var(("storage_soc", hour), 0.0, max(0.0, storage_energy_upper))
        builder.add_var(("hydrogen_storage", hour), 0.0, max(0.0, hydrogen_tank_upper))
        builder.add_var(("unmet_load", hour), 0.0, max(0.0, loads[hour]), cost=LOAD_SHED_PENALTY_COST)

        for device in diesel_devices:
            builder.add_var(
                ("diesel_power", hour, device["index"]),
                0.0,
                device["power_upper"] * device["quantity_upper"],
                cost=device["fuel_rate"] * model["diesel_objective_price"] / 1000,
            )
            builder.add_var(
                ("diesel_on_count", hour, device["index"]),
                0.0,
                device["quantity_upper"],
                integer=True,
                cost=DIESEL_ON_COUNT_PENALTY,
            )
        for device in grid_storage_pcs_devices:
            builder.add_var(("grid_storage_on_count", hour, device["index"]), 0.0, device["quantity_upper"], integer=True)
            builder.add_var(("grid_storage_up_available_count", hour, device["index"]), 0.0, device["quantity_upper"], integer=True)
            builder.add_var(("grid_storage_down_available_count", hour, device["index"]), 0.0, device["quantity_upper"], integer=True)
        for device in electrolyzer_devices:
            builder.add_var(
                ("electrolyzer_power", hour, device["index"]),
                0.0,
                device["capacity"] * device["quantity_upper"],
            )
            builder.add_var(
                ("electrolyzer_on_count", hour, device["index"]),
                0.0,
                device["quantity_upper"],
                integer=True,
                cost=ELECTROLYZER_ON_COUNT_PENALTY,
            )
        for device in fuel_cell_devices:
            builder.add_var(
                ("fuel_cell_power", hour, device["index"]),
                0.0,
                device["capacity"] * device["quantity_upper"],
            )
        if model["frequency"]["enabled"]:
            for device in diesel_devices:
                response_upper = device["power_upper"] * device["quantity_upper"]
                builder.add_var(("frequency_diesel_up_response", hour, device["index"]), 0.0, response_upper)
                builder.add_var(("frequency_diesel_down_response", hour, device["index"]), 0.0, response_upper)
            if model["frequency"]["storage_frequency_regulation_enabled"]:
                for device in grid_storage_pcs_devices:
                    response_upper = device["capacity"] * device["quantity_upper"]
                    builder.add_var(("frequency_storage_up_response", hour, device["index"]), 0.0, response_upper)
                    builder.add_var(("frequency_storage_down_response", hour, device["index"]), 0.0, response_upper)

    def qty_terms(devices: list[dict[str, Any]], coefficient_key: str = "capacity", multiplier: float = 1.0) -> dict[int, float]:
        return {
            var(("qty", device["key"], device["index"])): numeric(device.get(coefficient_key), 0.0) * multiplier
            for device in devices
        }

    charge_efficiency = model["storage_charge_efficiency"]
    discharge_efficiency = model["storage_discharge_efficiency"]
    storage_self_discharge_per_hour = model["storage_self_discharge_rate"] / 24.0
    hydrogen_self_discharge_per_hour = model["hydrogen_self_discharge_rate"] / 24.0

    for hour in range(n):
        dispatch_milp.add_power_balance_constraint(
            builder,
            generation_indices=[
                var(("wind_power", hour)),
                var(("pv_power", hour)),
                var(("storage_discharge", hour)),
                *[var(("diesel_power", hour, device["index"])) for device in diesel_devices],
                *[var(("fuel_cell_power", hour, device["index"])) for device in fuel_cell_devices],
            ],
            charge_indices=[var(("storage_charge", hour))],
            consumption_indices=[var(("electrolyzer_power", hour, device["index"])) for device in electrolyzer_devices],
            unmet_index=var(("unmet_load", hour)),
            load=loads[hour],
        )

        add_renewable_curtailment_linearization(builder, hour, renewable_devices)
        add_exact_renewable_aggregate_constraints(
            builder,
            model=model,
            hour=hour,
            devices=wind_devices,
            power_key="wind_power",
            curtailed_key="wind_curtailed",
        )
        add_exact_renewable_aggregate_constraints(
            builder,
            model=model,
            hour=hour,
            devices=pv_devices,
            power_key="pv_power",
            curtailed_key="pv_curtailed",
        )

        for device in diesel_devices:
            qty_index = var(("qty", device["key"], device["index"]))
            power_index = var(("diesel_power", hour, device["index"]))
            on_index = var(("diesel_on_count", hour, device["index"]))
            dispatch_milp.add_unit_commitment_constraints(
                builder,
                power_index=power_index,
                on_indices=[on_index],
                power_upper=device["power_upper"],
                power_lower=device["power_lower"],
                quantity_index=qty_index,
            )

        grid_storage_on_indices = []
        grid_storage_up_indices = []
        grid_storage_down_indices = []
        grid_storage_up_on_terms = {}
        grid_storage_down_on_terms = {}
        grid_storage_up_soc_limits = {}
        grid_storage_down_soc_limits = {}
        for device in grid_storage_pcs_devices:
            qty_index = var(("qty", device["key"], device["index"]))
            on_index = var(("grid_storage_on_count", hour, device["index"]))
            up_index = var(("grid_storage_up_available_count", hour, device["index"]))
            down_index = var(("grid_storage_down_available_count", hour, device["index"]))
            dispatch_milp.add_grid_storage_on_constraints(builder, on_indices=[on_index], quantity_index=qty_index)
            grid_storage_on_indices.append(on_index)
            grid_storage_up_indices.append(up_index)
            grid_storage_down_indices.append(down_index)
            grid_storage_up_on_terms[up_index] = device["capacity"]
            grid_storage_down_on_terms[down_index] = device["capacity"]
            grid_storage_up_soc_limits[up_index] = device["quantity_upper"]
            grid_storage_down_soc_limits[down_index] = device["quantity_upper"]
            builder.add_constraint({up_index: 1.0, on_index: -1.0}, -np.inf, 0.0)
            builder.add_constraint({down_index: 1.0, on_index: -1.0}, -np.inf, 0.0)

        for device in electrolyzer_devices:
            qty_index = var(("qty", device["key"], device["index"]))
            power_index = var(("electrolyzer_power", hour, device["index"]))
            on_index = var(("electrolyzer_on_count", hour, device["index"]))
            dispatch_milp.add_unit_commitment_constraints(
                builder,
                power_index=power_index,
                on_indices=[on_index],
                power_upper=device["capacity"],
                power_lower=device["power_lower"],
                quantity_index=qty_index,
            )

        for device in fuel_cell_devices:
            dispatch_milp.add_capacity_upper_constraint(
                builder,
                var(("fuel_cell_power", hour, device["index"])),
                capacity_terms={var(("qty", device["key"], device["index"])): device["capacity"]},
            )

        storage_power_terms = qty_terms(storage_pcs_devices)
        grid_storage_power_terms = qty_terms(grid_storage_pcs_devices)
        following_storage_power_terms = qty_terms(following_storage_pcs_devices)
        storage_power_upper = sum(device["capacity"] * device["quantity_upper"] for device in storage_pcs_devices)
        storage_energy_terms = qty_terms(storage_battery_devices)
        storage_flags = dispatch_milp.add_storage_constraints(
            builder,
            charge_index=var(("storage_charge", hour)),
            discharge_index=var(("storage_discharge", hour)),
            charge_on_index=var(("storage_charge_on", hour)),
            discharge_on_index=var(("storage_discharge_on", hour)),
            soc_index=var(("storage_soc", hour)),
            previous_soc_index=var(("storage_soc", hour - 1)) if hour > 0 else None,
            power_capacity_upper=storage_power_upper,
            power_capacity_terms=storage_power_terms,
            energy_capacity_terms=storage_energy_terms,
            initial_ratio=model["initial_storage_soc_ratio"],
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            soc_lower_ratio=model["storage_soc_lower_ratio"],
            soc_upper_ratio=model["storage_soc_upper_ratio"],
            self_discharge_rate_per_hour=storage_self_discharge_per_hour,
        )
        builder.add_constraint({var(("grid_storage_charge", hour)): 1.0, var(("storage_charge", hour)): -1.0}, -np.inf, 0.0)
        builder.add_constraint({var(("grid_storage_discharge", hour)): 1.0, var(("storage_discharge", hour)): -1.0}, -np.inf, 0.0)
        dispatch_milp.add_capacity_upper_constraint(
            builder,
            var(("grid_storage_charge", hour)),
            capacity_terms=grid_storage_power_terms,
        )
        dispatch_milp.add_capacity_upper_constraint(
            builder,
            var(("grid_storage_discharge", hour)),
            capacity_terms=grid_storage_power_terms,
        )
        builder.add_constraint(
            {
                var(("storage_charge", hour)): 1.0,
                var(("grid_storage_charge", hour)): -1.0,
                **{index: -value for index, value in following_storage_power_terms.items()},
            },
            -np.inf,
            0.0,
        )
        builder.add_constraint(
            {
                var(("storage_discharge", hour)): 1.0,
                var(("grid_storage_discharge", hour)): -1.0,
                **{index: -value for index, value in following_storage_power_terms.items()},
            },
            -np.inf,
            0.0,
        )
        for index, upper_count in grid_storage_up_soc_limits.items():
            builder.add_constraint({index: 1.0, storage_flags["soc_above_lower"]: -float(upper_count)}, -np.inf, 0.0)
        for index, upper_count in grid_storage_down_soc_limits.items():
            builder.add_constraint({index: 1.0, storage_flags["soc_below_upper"]: -float(upper_count)}, -np.inf, 0.0)

        all_diesel_on_indices = [
            var(("diesel_on_count", hour, device["index"]))
            for device in diesel_devices
        ]
        dispatch_milp.add_grid_support_requirement(
            builder,
            diesel_on_indices=all_diesel_on_indices,
            grid_storage_on_indices=grid_storage_on_indices,
        )
        if model["post_disturbance_power_balance_enabled"]:
            dispatch_milp.add_post_disturbance_balance_constraints(
                builder,
                load=loads[hour],
                load_up_factor=model["load_up_disturbance_factor"],
                load_down_factor=model["load_down_disturbance_factor"],
                renewable_down_factor=model["renewable_down_disturbance_factor"],
                diesel_power_indices=[var(("diesel_power", hour, device["index"])) for device in diesel_devices],
                diesel_on_terms={
                    var(("diesel_on_count", hour, device["index"])): device["power_upper"]
                    for device in diesel_devices
                },
                grid_storage_charge_index=var(("grid_storage_charge", hour)),
                grid_storage_discharge_index=var(("grid_storage_discharge", hour)),
                grid_storage_up_on_terms=grid_storage_up_on_terms,
                grid_storage_down_on_terms=grid_storage_down_on_terms,
                wind_power_indices=[var(("wind_power", hour))],
                pv_power_indices=[var(("pv_power", hour))],
            )
        if model["frequency"]["enabled"]:
            add_frequency_security_constraints(
                builder,
                model=model,
                hour=hour,
                diesel_devices=diesel_devices,
                grid_storage_pcs_devices=grid_storage_pcs_devices,
                grid_storage_power_terms=grid_storage_power_terms,
                grid_storage_charge_index=var(("grid_storage_charge", hour)),
                grid_storage_discharge_index=var(("grid_storage_discharge", hour)),
                wind_power_index=var(("wind_power", hour)),
                pv_power_index=var(("pv_power", hour)),
                load=loads[hour],
            )

        hydrogen_capacity_terms = qty_terms(hydrogen_tank_devices)
        dispatch_milp.add_hydrogen_constraints(
            builder,
            storage_index=var(("hydrogen_storage", hour)),
            previous_storage_index=var(("hydrogen_storage", hour - 1)) if hour > 0 else None,
            production_terms={
                var(("electrolyzer_power", hour, device["index"])): device["electric_to_hydrogen_efficiency"]
                for device in electrolyzer_devices
            },
            consumption_terms={
                var(("fuel_cell_power", hour, device["index"])): 1.0 / max(0.0001, device["hydrogen_to_electric_efficiency"])
                for device in fuel_cell_devices
            },
            capacity_terms=hydrogen_capacity_terms,
            initial_ratio=model["initial_hydrogen_storage_ratio"],
            self_discharge_rate_per_hour=hydrogen_self_discharge_per_hour,
        )

    for day_end_hour in range(23, n, 24):
        storage_energy_terms = qty_terms(storage_battery_devices)
        dispatch_milp.add_storage_cycle_constraint(
            builder,
            soc_index=var(("storage_soc", day_end_hour)),
            energy_capacity_terms=storage_energy_terms,
            initial_ratio=model["initial_storage_soc_ratio"],
        )
    if n:
        hydrogen_capacity_terms = qty_terms(hydrogen_tank_devices)
        dispatch_milp.add_hydrogen_cycle_constraint(
            builder,
            storage_index=var(("hydrogen_storage", n - 1)),
            capacity_terms=hydrogen_capacity_terms,
            initial_ratio=model["initial_hydrogen_storage_ratio"],
        )

    green_ratio_lower = model["green_ratio_lower"]
    dispatch_milp.add_green_ratio_constraint(
        builder,
        green_power_indices=[
            index
            for hour in range(n)
            for index in [
                var(("wind_power", hour)),
                var(("pv_power", hour)),
                var(("storage_discharge", hour)),
                *[var(("fuel_cell_power", hour, device["index"])) for device in fuel_cell_devices],
            ]
        ],
        diesel_power_indices=[
            var(("diesel_power", hour, device["index"]))
            for hour in range(n)
            for device in diesel_devices
        ],
        ratio_lower=green_ratio_lower,
    )

    variable_count = builder.variable_count
    integer_variable_count = builder.integer_variable_count
    constraint_count = builder.constraint_count
    emit(
        log,
        "info",
        f"模型规模：变量{variable_count}个（整数{integer_variable_count}个），约束{constraint_count}条，非零系数{builder.nonzero_count}个",
        20,
    )
    dispatch_milp.emit_builder_diagnostics(builder, log, "规划求解MILP")
    emit(
        log,
        "info",
        f"求解参数：time_limit={model['optimization_time_limit_seconds']}秒，mip_rel_gap=0.01",
        22,
    )
    emit(log, "info", "求解设备台数和全年运行联合混合整数线性规划", 25)
    result = dispatch_milp.solve_built_milp(
        builder,
        options={
            "time_limit": model["optimization_time_limit_seconds"],
            "solver": model.get("preferred_solver", "auto"),
            "mip_rel_gap": 0.01,
            "disp": False,
            "solver_log": True,
            "solver_log_interval": 2.0,
        },
        log=log,
        problem_name=model.get("problem_name", "规划求解"),
        solve_fn=solve_milp,
    )
    objective_value = float(result.fun) if result.fun is not None else 0.0
    emit(
        log,
        "info",
        f"求解器返回：success={result.success}，目标函数值={format_log_number(objective_value)}，状态={result.message}",
        80,
    )
    raise_if_solver_timed_out(result, model.get("problem_name", "规划求解"))
    if result.x is None:
        raise ValueError(f"{model.get('problem_name', '规划求解')}失败：{result.message}")
    if not result.success:
        feasibility = dispatch_milp.solution_feasibility_report(builder, result.x)
        if not feasibility["feasible"]:
            detail = dispatch_milp.format_feasibility_report(feasibility)
            raise ValueError(
                f"{model.get('problem_name', '规划求解')}失败：求解器未返回可行解，"
                f"不能使用该结果。状态={result.message}；{detail}"
            )
        emit(log, "warn", f"规划优化未达到最优但返回了可行解：{result.message}", 80)
    model["variables"] = builder.variables
    model["objective_value"] = objective_value
    return result.x


def raise_if_solver_timed_out(result: Any, problem_name: str = "规划求解") -> None:
    """Convert backend time-limit statuses into a domain-level timeout error."""

    if not is_timeout_result(result):
        return
    message = str(getattr(result, "message", "") or "求解器达到时间上限")
    raise CalculationTimeoutError(f"{problem_name}达到优化求解时间上限，计算超时：{message}")


def normalize_preferred_solver(value: Any) -> str:
    solver = str(value or "auto").strip().lower()
    aliases = {
        "": "auto",
        "automatic": "auto",
        "自动": "auto",
        "自动选择": "auto",
        "grb": "gurobi",
        "gurobi": "gurobi",
        "cplx": "cplex",
        "cplex": "cplex",
        "msk": "mosek",
        "mosek": "mosek",
        "highs": "scipy",
        "scipy": "scipy",
        "scipy highs": "scipy",
        "scipy-highs": "scipy",
    }
    return aliases.get(solver, "auto")


def normalized_device_rows(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    # This is the single place where workbook rows become numbers, booleans and
    # annualized costs used by the optimization model.
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
                device["inertia_constant_h"] = max(0.0, numeric(source.get("inertia_constant_h"), 3.5))
                device["primary_frequency_coefficient_k"] = max(0.0, numeric(source.get("primary_frequency_coefficient_k"), 0.4))
                device["damping_coefficient_d"] = max(0.0, numeric(source.get("damping_coefficient_d"), 0.01))
                device["governor_time_constant_t"] = max(FREQUENCY_EPS, numeric(source.get("governor_time_constant_t"), 0.6))
            elif key == "storage_pcs":
                device["is_grid_forming"] = truthy_flag(source.get("is_grid_forming"), False)
                device["storage_charge_efficiency"] = optional_efficiency(source.get("storage_charge_efficiency"))
                device["storage_discharge_efficiency"] = optional_efficiency(source.get("storage_discharge_efficiency"))
                device["storage_equivalent_inertia_constant_h"] = max(0.0, numeric(source.get("storage_equivalent_inertia_constant_h"), 2.5))
                device["storage_equivalent_primary_frequency_coefficient_k"] = max(0.0, numeric(source.get("storage_equivalent_primary_frequency_coefficient_k"), 0.5))
                device["storage_equivalent_damping_coefficient_d"] = max(0.0, numeric(source.get("storage_equivalent_damping_coefficient_d"), 0.05))
            elif key == "storage_battery_packs":
                soc_upper = min(1.0, max(0.0, numeric(source.get("soc_upper"), 0.9)))
                soc_lower = min(1.0, max(0.0, numeric(source.get("soc_lower"), 0.1)))
                if soc_upper < soc_lower:
                    soc_upper, soc_lower = soc_lower, soc_upper
                device["soc_upper"] = soc_upper
                device["soc_lower"] = soc_lower
                device["self_discharge_rate"] = min(0.01, max(0.0, numeric(source.get("self_discharge_rate"), 0.01)))
            elif key == "hydrogen_electrolyzers":
                device["power_lower"] = min(capacity, max(0.0, numeric(source.get("power_lower"), 0.0)))
                device["electric_to_hydrogen_efficiency"] = max(0.0, numeric(source.get("electric_to_hydrogen_efficiency"), 0.7))
            elif key == "fuel_cells":
                device["hydrogen_to_electric_efficiency"] = max(0.0001, numeric(source.get("hydrogen_to_electric_efficiency"), 0.55))
            elif key == "hydrogen_tanks":
                device["self_discharge_rate"] = min(0.01, max(0.0, numeric(source.get("self_discharge_rate"), 0.001)))
            normalized[key].append(device)
    return normalized


def storage_soc_limits(storage_battery_devices: list[dict[str, Any]]) -> tuple[float, float]:
    # The MILP currently tracks one aggregate battery SOC, so per-row SOC
    # windows are compressed into fleet-level lower and upper ratios.
    total_capacity = sum(max(0.0, device["capacity"] * device["quantity_upper"]) for device in storage_battery_devices)
    if total_capacity <= 0:
        return 0.1, 0.9
    lower = sum(device["capacity"] * device["quantity_upper"] * numeric(device.get("soc_lower"), 0.1) for device in storage_battery_devices) / total_capacity
    upper = sum(device["capacity"] * device["quantity_upper"] * numeric(device.get("soc_upper"), 0.9) for device in storage_battery_devices) / total_capacity
    lower = min(1.0, max(0.0, lower))
    upper = min(1.0, max(0.0, upper))
    if upper < lower:
        upper, lower = lower, upper
    return lower, upper


def fleet_self_discharge_rate(devices: list[dict[str, Any]], default: float) -> float:
    active_rates = [
        min(0.01, max(0.0, numeric(device.get("self_discharge_rate"), default)))
        for device in devices
        if device["quantity_upper"] > 0 and device["capacity"] > 0
    ]
    if not active_rates:
        return min(0.01, max(0.0, float(default)))
    return max(active_rates)


def storage_efficiencies(storage_pcs_devices: list[dict[str, Any]], legacy_charge: float, legacy_discharge: float) -> tuple[float, float]:
    active_devices = [
        device
        for device in storage_pcs_devices
        if device["quantity_upper"] > 0 and device["capacity"] > 0
    ]
    if not active_devices:
        active_devices = storage_pcs_devices
    if not active_devices:
        return (
            min(1.0, max(0.0001, legacy_charge)),
            min(1.0, max(0.0001, legacy_discharge)),
        )
    charge_values = [
        numeric(device.get("storage_charge_efficiency"), legacy_charge)
        for device in active_devices
        if device.get("storage_charge_efficiency") not in ("", None)
    ]
    discharge_values = [
        numeric(device.get("storage_discharge_efficiency"), legacy_discharge)
        for device in active_devices
        if device.get("storage_discharge_efficiency") not in ("", None)
    ]
    charge = sum(charge_values) / len(charge_values) if charge_values else legacy_charge
    discharge = sum(discharge_values) / len(discharge_values) if discharge_values else legacy_discharge
    return min(1.0, max(0.0001, charge)), min(1.0, max(0.0001, discharge))


def optional_efficiency(value: Any) -> float | str:
    if value in ("", None):
        return ""
    return min(1.0, max(0.0001, numeric(value, 0.95)))


def truthy_flag(value: Any, default: bool = False) -> bool:
    if value in ("", None):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def active_devices(model: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        device
        for device in model["device_rows"][key]
        if device["quantity_upper"] > 0 and device["capacity"] > 0
    ]


def renewable_candidate_devices(model: dict[str, Any], key: str) -> list[dict[str, Any]]:
    # Wind/PV curtailment is modeled by physical candidate slots. Rows with no
    # possible capacity cannot affect dispatch, so they stay as plain qty rows.
    return [
        device
        for device in model["device_rows"][key]
        if device["quantity_upper"] > 0 and device["capacity"] > 0
    ]


def dispatch_security_curve_fields(
    model: dict[str, Any],
    *,
    load: float,
    wind_power: float,
    pv_power: float,
    renewable_single_unit_power_max: float,
    diesel_capacity: float,
    diesel_power: float,
    grid_storage_power: float,
    grid_storage_up_capacity: float,
    grid_storage_down_capacity: float,
) -> dict[str, float]:
    # These derived curves mirror the disturbance-security constraints using
    # signed power directions: upward values are positive, downward demand and
    # capability are shown as negative numbers for visual comparison.
    renewable_power = max(0.0, float(wind_power) + float(pv_power))
    load_up_disturbance = max(0.0, float(load)) * model["load_up_disturbance_factor"]
    load_down_disturbance = -1.0 * max(0.0, float(load)) * model["load_down_disturbance_factor"]
    renewable_down_disturbance = renewable_power * model["renewable_down_disturbance_factor"]
    grid_up_capacity = (
        float(diesel_capacity)
        - float(diesel_power)
        + float(grid_storage_up_capacity)
        - float(grid_storage_power)
    )
    grid_down_capacity = -1.0 * (
        float(diesel_power)
        + float(grid_storage_power)
        + float(grid_storage_down_capacity)
    )
    return {
        "load_up_disturbance_power": round(load_up_disturbance, 4),
        "load_down_disturbance_power": round(load_down_disturbance, 4),
        "renewable_down_disturbance_power": round(renewable_down_disturbance, 4),
        "renewable_single_unit_power_max": round(max(0.0, float(renewable_single_unit_power_max)), 4),
        "grid_up_regulation_capacity": round(grid_up_capacity, 4),
        "grid_down_regulation_capacity": round(grid_down_capacity, 4),
        "grid_up_regulation_requirement": round(load_up_disturbance + renewable_down_disturbance, 4),
        "grid_down_regulation_requirement": round(load_down_disturbance, 4),
    }





def finite_or_default(value: float, default: float) -> float:
    return float(value) if np.isfinite(value) else float(default)


def solved_frequency_terms(
    model: dict[str, Any],
    *,
    hour: int,
    scenario: str,
    load: float,
    wind_power: float,
    pv_power: float,
    diesel_devices: list[dict[str, Any]],
    grid_storage_pcs_devices: list[dict[str, Any]],
    optional_value,
) -> tuple[float, float, float]:
    freq = model["frequency"]
    response_key = "up" if scenario == "min" else "down"
    m_eq = 0.0
    k_eq = 0.0
    d_eq = float(freq["load_frequency_coefficient_d"]) * float(load) / max(float(freq["load_ref_kw"]), FREQUENCY_EPS)
    for device in diesel_devices:
        on_count = optional_value(("diesel_on_count", hour, device["index"]), 0.0)
        online_capacity_mw = on_count * float(device["power_upper"]) / 1000.0
        response_mw = optional_value((f"frequency_diesel_{response_key}_response", hour, device["index"]), 0.0) / 1000.0
        m_eq += 2.0 / float(freq["omega0_rad_per_s"]) * float(device["inertia_constant_h"]) * online_capacity_mw
        k_eq += float(device["primary_frequency_coefficient_k"]) * response_mw
        d_eq += float(device["damping_coefficient_d"]) * online_capacity_mw
    if freq["storage_frequency_regulation_enabled"]:
        for device in grid_storage_pcs_devices:
            response_mw = optional_value((f"frequency_storage_{response_key}_response", hour, device["index"]), 0.0) / 1000.0
            m_eq += 2.0 / float(freq["omega0_rad_per_s"]) * float(device["storage_equivalent_inertia_constant_h"]) * response_mw
            k_eq += float(device["storage_equivalent_primary_frequency_coefficient_k"]) * response_mw
            d_eq += float(device["storage_equivalent_damping_coefficient_d"]) * response_mw
    net_ratio = (float(wind_power) + float(pv_power) - float(load)) / max(float(freq["load_ref_kw"]), FREQUENCY_EPS)
    k_eq += float(freq["network_synchronization_coefficient_base"]) + float(freq["network_synchronization_coefficient_slope"]) * net_ratio
    return m_eq, k_eq, d_eq


def evaluate_frequency_fields(
    model: dict[str, Any],
    *,
    hour: int,
    load: float,
    wind_power: float,
    pv_power: float,
    diesel_devices: list[dict[str, Any]],
    grid_storage_pcs_devices: list[dict[str, Any]],
    optional_value,
) -> dict[str, float]:
    if not model.get("frequency", {}).get("enabled"):
        return {}
    freq = model["frequency"]
    lower_context = frequency_context(model, hour, "min")
    upper_context = frequency_context(model, hour, "max")
    m_eq, k_eq, d_eq = solved_frequency_terms(
        model,
        hour=hour,
        scenario="min",
        load=load,
        wind_power=wind_power,
        pv_power=pv_power,
        diesel_devices=diesel_devices,
        grid_storage_pcs_devices=grid_storage_pcs_devices,
        optional_value=optional_value,
    )
    m_upper, k_upper, d_upper = solved_frequency_terms(
        model,
        hour=hour,
        scenario="max",
        load=load,
        wind_power=wind_power,
        pv_power=pv_power,
        diesel_devices=diesel_devices,
        grid_storage_pcs_devices=grid_storage_pcs_devices,
        optional_value=optional_value,
    )
    nadir_linear = (
        lower_context["a_M"] * m_eq
        + lower_context["a_K"] * k_eq
        + lower_context["a_D"] * d_eq
        + lower_context["c0"]
    )
    peak_linear = (
        upper_context["a_M"] * m_upper
        + upper_context["a_K"] * k_upper
        + upper_context["a_D"] * d_upper
        + upper_context["c0"]
    )
    nadir_safe = nadir_linear - lower_context["fit_error"] - freq["lower_security_margin_hz"]
    peak_safe = peak_linear + upper_context["fit_error"] + freq["upper_security_margin_hz"]
    nadir_exact = frequency_extreme_hz_exact(
        m_eq,
        k_eq,
        d_eq,
        representative_governor_time_constant(model),
        lower_context["delta_p_mw"],
        t_end=freq["nadir_evaluation_duration_s"],
        seek="min",
        nominal_frequency_hz=freq["nominal_frequency_hz"],
    )
    peak_exact = frequency_extreme_hz_exact(
        m_upper,
        k_upper,
        d_upper,
        representative_governor_time_constant(model),
        upper_context["delta_p_mw"],
        t_end=freq["nadir_evaluation_duration_s"],
        seek="max",
        nominal_frequency_hz=freq["nominal_frequency_hz"],
    )
    nadir_display = min(nadir_safe, nadir_exact) if np.isfinite(nadir_exact) else nadir_safe
    peak_display = max(peak_safe, peak_exact) if np.isfinite(peak_exact) else peak_safe
    steady_lower = steady_state_frequency_hz(
        m_eq,
        k_eq,
        d_eq,
        lower_context["delta_p_mw"],
        nominal_frequency_hz=freq["nominal_frequency_hz"],
    )
    steady_upper = steady_state_frequency_hz(
        m_upper,
        k_upper,
        d_upper,
        upper_context["delta_p_mw"],
        nominal_frequency_hz=freq["nominal_frequency_hz"],
    )
    rocof = frequency_rocof_initial_hz_per_s(lower_context["delta_p_mw"], m_eq)
    rocof_upper = frequency_rocof_initial_hz_per_s(upper_context["delta_p_mw"], m_upper)
    return {
        "frequency_min": round(finite_or_default(nadir_display, freq["nominal_frequency_hz"]), 4),
        "frequency_max": round(finite_or_default(peak_display, freq["nominal_frequency_hz"]), 4),
        "frequency_nadir_est_hz": round(finite_or_default(nadir_safe, freq["nominal_frequency_hz"]), 4),
        "frequency_peak_est_hz": round(finite_or_default(peak_safe, freq["nominal_frequency_hz"]), 4),
        "frequency_nadir_exact_hz": round(finite_or_default(nadir_exact, nadir_safe), 4),
        "frequency_peak_exact_hz": round(finite_or_default(peak_exact, peak_safe), 4),
        "steady_state_frequency_min_hz": round(finite_or_default(steady_lower, freq["nominal_frequency_hz"]), 4),
        "steady_state_frequency_max_hz": round(finite_or_default(steady_upper, freq["nominal_frequency_hz"]), 4),
        "rocof_hz_per_s": round(finite_or_default(rocof, 0.0), 6),
        "rocof_upper_hz_per_s": round(finite_or_default(rocof_upper, 0.0), 6),
        "frequency_lower_margin_hz": round(finite_or_default(nadir_display - freq["nadir_lower_hz"], 0.0), 4),
        "frequency_upper_margin_hz": round(finite_or_default(freq["peak_upper_hz"] - peak_display, 0.0), 4),
        "equivalent_inertia_m": round(finite_or_default(m_eq, 0.0), 8),
        "equivalent_primary_frequency_k": round(finite_or_default(k_eq, 0.0), 8),
        "equivalent_damping_d": round(finite_or_default(d_eq, 0.0), 8),
        "frequency_delta_p_mw": round(finite_or_default(lower_context["delta_p_mw"], 0.0), 8),
        "frequency_upper_delta_p_mw": round(finite_or_default(upper_context["delta_p_mw"], 0.0), 8),
        "frequency_fit_error_hz": round(finite_or_default(lower_context["fit_error"], 0.0), 6),
        "frequency_upper_fit_error_hz": round(finite_or_default(upper_context["fit_error"], 0.0), 6),
    }


def add_renewable_hour_variables(
    builder: dispatch_milp.MilpModelBuilder,
    hour: int,
    devices: list[dict[str, Any]],
) -> None:
    # One common rate per hour enforces equal curtailment percentage across
    # wind/PV rows. z_{t,i} represents built_quantity_i * rate_t, so the model
    # avoids expanding a binary for every candidate unit.
    if not devices:
        return
    builder.add_var(("renewable_curtailment_rate", hour), 0.0, 1.0)
    for device in devices:
        builder.add_var(
            ("renewable_curtailment_product", hour, device["key"], device["index"]),
            0.0,
            device["quantity_upper"],
        )


def add_renewable_curtailment_linearization(
    builder: dispatch_milp.MilpModelBuilder,
    hour: int,
    devices: list[dict[str, Any]],
) -> None:
    if not devices:
        return
    rate_index = builder.var(("renewable_curtailment_rate", hour))
    for device in devices:
        qty_index = builder.var(("qty", device["key"], device["index"]))
        product_index = builder.var(("renewable_curtailment_product", hour, device["key"], device["index"]))
        quantity_upper = float(device["quantity_upper"])
        builder.add_constraint({product_index: 1.0, rate_index: -quantity_upper}, -np.inf, 0.0)
        builder.add_constraint({product_index: 1.0, qty_index: -1.0}, -np.inf, 0.0)
        builder.add_constraint({product_index: 1.0, rate_index: -quantity_upper, qty_index: -1.0}, -quantity_upper, np.inf)


def add_exact_renewable_aggregate_constraints(
    builder: dispatch_milp.MilpModelBuilder,
    *,
    model: dict[str, Any],
    hour: int,
    devices: list[dict[str, Any]],
    power_key: str,
    curtailed_key: str,
) -> None:
    # Aggregate variables remain the public interface for power balance,
    # reports and existing safety constraints. The equalities below bind them
    # to exact row-level output/curtailment under the shared hourly rate.
    power_terms: dict[int, float] = {builder.var((power_key, hour)): 1.0}
    curtailed_terms: dict[int, float] = {builder.var((curtailed_key, hour)): 1.0}
    availability_map_key = "wind_available_per_unit" if power_key == "wind_power" else "pv_available_per_unit"
    for device in devices:
        availability = float(model[availability_map_key][device["id"]][hour])
        qty_index = builder.var(("qty", device["key"], device["index"]))
        product_index = builder.var(("renewable_curtailment_product", hour, device["key"], device["index"]))
        power_terms[qty_index] = power_terms.get(qty_index, 0.0) - availability
        power_terms[product_index] = power_terms.get(product_index, 0.0) + availability
        curtailed_terms[product_index] = curtailed_terms.get(product_index, 0.0) - availability
    builder.add_constraint(power_terms, 0.0, 0.0)
    builder.add_constraint(curtailed_terms, 0.0, 0.0)





def add_expression_constraint(
    builder: dispatch_milp.MilpModelBuilder,
    terms: dict[int, float],
    constant: float,
    lower: float,
    upper: float,
) -> None:
    builder.add_constraint(terms, float(lower) - float(constant), float(upper) - float(constant))


def add_scaled_terms(target: dict[int, float], source: dict[int, float], scale: float = 1.0) -> None:
    for index, coefficient in source.items():
        target[index] = target.get(index, 0.0) + float(coefficient) * float(scale)


def frequency_expression_components(
    builder: dispatch_milp.MilpModelBuilder,
    *,
    model: dict[str, Any],
    hour: int,
    diesel_devices: list[dict[str, Any]],
    grid_storage_pcs_devices: list[dict[str, Any]],
    scenario: str,
    wind_power_index: int,
    pv_power_index: int,
    load: float,
) -> tuple[dict[int, float], float, dict[int, float], float, dict[int, float], float]:
    freq = model["frequency"]
    response_key = "up" if scenario == "min" else "down"
    m_terms: dict[int, float] = {}
    k_terms: dict[int, float] = {}
    d_terms: dict[int, float] = {}
    for device in diesel_devices:
        on_index = builder.var(("diesel_on_count", hour, device["index"]))
        online_capacity_mw_coeff = float(device["power_upper"]) / 1000.0
        response_index = builder.var((f"frequency_diesel_{response_key}_response", hour, device["index"]))
        m_terms[on_index] = m_terms.get(on_index, 0.0) + 2.0 / float(freq["omega0_rad_per_s"]) * float(device["inertia_constant_h"]) * online_capacity_mw_coeff
        k_terms[response_index] = k_terms.get(response_index, 0.0) + float(device["primary_frequency_coefficient_k"]) / 1000.0
        d_terms[on_index] = d_terms.get(on_index, 0.0) + float(device["damping_coefficient_d"]) * online_capacity_mw_coeff
    if freq["storage_frequency_regulation_enabled"]:
        for device in grid_storage_pcs_devices:
            response_index = builder.var((f"frequency_storage_{response_key}_response", hour, device["index"]))
            m_terms[response_index] = m_terms.get(response_index, 0.0) + 2.0 / float(freq["omega0_rad_per_s"]) * float(device["storage_equivalent_inertia_constant_h"]) / 1000.0
            k_terms[response_index] = k_terms.get(response_index, 0.0) + float(device["storage_equivalent_primary_frequency_coefficient_k"]) / 1000.0
            d_terms[response_index] = d_terms.get(response_index, 0.0) + float(device["storage_equivalent_damping_coefficient_d"]) / 1000.0
    ref = max(float(freq["load_ref_kw"]), FREQUENCY_EPS)
    network_slope = float(freq["network_synchronization_coefficient_slope"])
    k_terms[wind_power_index] = k_terms.get(wind_power_index, 0.0) + network_slope / ref
    k_terms[pv_power_index] = k_terms.get(pv_power_index, 0.0) + network_slope / ref
    k_constant = float(freq["network_synchronization_coefficient_base"]) - network_slope * float(load) / ref
    d_constant = float(freq["load_frequency_coefficient_d"]) * float(load) / ref
    return m_terms, 0.0, k_terms, k_constant, d_terms, d_constant


def add_frequency_response_constraints(
    builder: dispatch_milp.MilpModelBuilder,
    *,
    model: dict[str, Any],
    hour: int,
    diesel_devices: list[dict[str, Any]],
    grid_storage_pcs_devices: list[dict[str, Any]],
    grid_storage_power_terms: dict[int, float],
    grid_storage_charge_index: int,
    grid_storage_discharge_index: int,
) -> None:
    for device in diesel_devices:
        power_index = builder.var(("diesel_power", hour, device["index"]))
        on_index = builder.var(("diesel_on_count", hour, device["index"]))
        up_index = builder.var(("frequency_diesel_up_response", hour, device["index"]))
        down_index = builder.var(("frequency_diesel_down_response", hour, device["index"]))
        builder.add_constraint({up_index: 1.0, power_index: 1.0, on_index: -float(device["power_upper"])}, -np.inf, 0.0)
        builder.add_constraint({down_index: 1.0, power_index: -1.0, on_index: float(device["power_lower"])}, -np.inf, 0.0)
    if not model["frequency"]["storage_frequency_regulation_enabled"] or not grid_storage_pcs_devices:
        return
    up_response_terms: dict[int, float] = {}
    down_response_terms: dict[int, float] = {}
    for device in grid_storage_pcs_devices:
        up_index = builder.var(("frequency_storage_up_response", hour, device["index"]))
        down_index = builder.var(("frequency_storage_down_response", hour, device["index"]))
        up_available_index = builder.var(("grid_storage_up_available_count", hour, device["index"]))
        down_available_index = builder.var(("grid_storage_down_available_count", hour, device["index"]))
        builder.add_constraint({up_index: 1.0, up_available_index: -float(device["capacity"])}, -np.inf, 0.0)
        builder.add_constraint({down_index: 1.0, down_available_index: -float(device["capacity"])}, -np.inf, 0.0)
        up_response_terms[up_index] = 1.0
        down_response_terms[down_index] = 1.0
    up_headroom_terms = dict(up_response_terms)
    up_headroom_terms[grid_storage_discharge_index] = up_headroom_terms.get(grid_storage_discharge_index, 0.0) + 1.0
    up_headroom_terms[grid_storage_charge_index] = up_headroom_terms.get(grid_storage_charge_index, 0.0) - 1.0
    for index, coefficient in grid_storage_power_terms.items():
        up_headroom_terms[index] = up_headroom_terms.get(index, 0.0) - coefficient
    builder.add_constraint(up_headroom_terms, -np.inf, 0.0)

    down_headroom_terms = dict(down_response_terms)
    down_headroom_terms[grid_storage_discharge_index] = down_headroom_terms.get(grid_storage_discharge_index, 0.0) - 1.0
    down_headroom_terms[grid_storage_charge_index] = down_headroom_terms.get(grid_storage_charge_index, 0.0) + 1.0
    for index, coefficient in grid_storage_power_terms.items():
        down_headroom_terms[index] = down_headroom_terms.get(index, 0.0) - coefficient
    builder.add_constraint(down_headroom_terms, -np.inf, 0.0)


def add_frequency_security_constraints(
    builder: dispatch_milp.MilpModelBuilder,
    *,
    model: dict[str, Any],
    hour: int,
    diesel_devices: list[dict[str, Any]],
    grid_storage_pcs_devices: list[dict[str, Any]],
    grid_storage_power_terms: dict[int, float],
    grid_storage_charge_index: int,
    grid_storage_discharge_index: int,
    wind_power_index: int,
    pv_power_index: int,
    load: float,
) -> None:
    add_frequency_response_constraints(
        builder,
        model=model,
        hour=hour,
        diesel_devices=diesel_devices,
        grid_storage_pcs_devices=grid_storage_pcs_devices,
        grid_storage_power_terms=grid_storage_power_terms,
        grid_storage_charge_index=grid_storage_charge_index,
        grid_storage_discharge_index=grid_storage_discharge_index,
    )
    for scenario in ("min", "max"):
        context = frequency_context(model, hour, scenario)
        m_terms, m_constant, k_terms, k_constant, d_terms, d_constant = frequency_expression_components(
            builder,
            model=model,
            hour=hour,
            diesel_devices=diesel_devices,
            grid_storage_pcs_devices=grid_storage_pcs_devices,
            scenario=scenario,
            wind_power_index=wind_power_index,
            pv_power_index=pv_power_index,
            load=load,
        )
        add_expression_constraint(builder, m_terms, m_constant, context["M_lo"], context["M_hi"])
        add_expression_constraint(builder, k_terms, k_constant, context["K_lo"], context["K_hi"])
        add_expression_constraint(builder, d_terms, d_constant, context["D_lo"], context["D_hi"])
        add_expression_constraint(builder, m_terms, m_constant, context["rocof_m_min"], np.inf)
        steady_terms = dict(k_terms)
        add_scaled_terms(steady_terms, d_terms, 2.0 * math.pi)
        add_expression_constraint(
            builder,
            steady_terms,
            k_constant + 2.0 * math.pi * d_constant,
            context["steady_dk_min"],
            np.inf,
        )
        fitted_terms: dict[int, float] = {}
        add_scaled_terms(fitted_terms, m_terms, context["a_M"])
        add_scaled_terms(fitted_terms, k_terms, context["a_K"])
        add_scaled_terms(fitted_terms, d_terms, context["a_D"])
        fitted_constant = (
            context["a_M"] * m_constant
            + context["a_K"] * k_constant
            + context["a_D"] * d_constant
            + context["c0"]
        )
        if scenario == "min":
            lower = model["frequency"]["nadir_lower_hz"] + model["frequency"]["lower_security_margin_hz"] + context["fit_error"]
            add_expression_constraint(builder, fitted_terms, fitted_constant, lower, np.inf)
        else:
            upper = model["frequency"]["peak_upper_hz"] - model["frequency"]["upper_security_margin_hz"] - context["fit_error"]
            add_expression_constraint(builder, fitted_terms, fitted_constant, -np.inf, upper)


def emit_model_input_summary(model: dict[str, Any], log: LogSink | None = None) -> None:
    loads = model["loads"]
    hours = len(loads)
    load_energy = float(np.sum(loads)) if hours else 0.0
    peak_load = float(np.max(loads)) if hours else 0.0
    emit(
        log,
        "info",
        (
            "模型输入："
            f"时段={hours}小时，"
            f"负荷总电量={format_log_number(load_energy)}kWh，"
            f"最大负荷={format_log_number(peak_load)}kW，"
            f"柴油价格={format_log_number(model['diesel_price'])}万元/吨，"
            f"绿电下限={format_log_number(model['green_ratio_lower'] * 100)}%，"
            f"初始电储={format_log_number(model['initial_storage_soc_ratio'] * 100)}%，"
            f"初始氢储={format_log_number(model['initial_hydrogen_storage_ratio'] * 100)}%，"
            f"储能效率={format_log_number(model['storage_charge_efficiency'] * 100)}%/"
            f"{format_log_number(model['storage_discharge_efficiency'] * 100)}%，"
            f"电储自损耗={format_log_number(model['storage_self_discharge_rate'] * 100)}%/天，"
            f"氢储自损耗={format_log_number(model['hydrogen_self_discharge_rate'] * 100)}%/天，"
            f"求解上限={model['optimization_time_limit_seconds']}秒"
        ),
        8,
    )


def emit_device_candidate_summary(model: dict[str, Any], log: LogSink | None = None) -> None:
    parts = []
    for key, devices in model["device_rows"].items():
        if not devices:
            continue
        label = DEVICE_SPECS[key]["label"]
        lower_count = sum(int(device["quantity_lower"]) for device in devices)
        upper_count = sum(int(device["quantity_upper"]) for device in devices)
        max_capacity = sum(device["capacity"] * device["quantity_upper"] for device in devices)
        min_annual_cost = sum(device["annual_cost"] * device["quantity_lower"] for device in devices)
        max_annual_cost = sum(device["annual_cost"] * device["quantity_upper"] for device in devices)
        parts.append(
            (
                f"{label}{len(devices)}行"
                f"(台数{lower_count}-{upper_count}, "
                f"上限容量{format_log_number(max_capacity)}{DEVICE_SPECS[key]['unit']}, "
                f"年均成本{format_log_number(min_annual_cost)}-{format_log_number(max_annual_cost)}万元)"
            )
        )
    emit(log, "info", f"候选设备：{'；'.join(parts) if parts else '无'}", 12)


def emit_solution_summary(
    planning_rows: list[dict[str, Any]],
    totals: dict[str, float],
    costs: dict[str, float],
    log: LogSink | None = None,
) -> None:
    capacities = estimate.capacities_from_planning_rows(planning_rows)
    emit(
        log,
        "info",
        (
            "成本汇总："
            f"年均建设成本={format_log_number(costs['annualized_construction_cost'])}万元，"
            f"年柴油成本={format_log_number(costs['annual_diesel_cost'])}万元，"
            f"年总成本={format_log_number(costs['annual_total_cost'])}万元，"
            f"柴油消耗={format_log_number(totals['diesel_consumption'])}吨，"
            f"绿电占比={format_log_number(totals['green_power_ratio'])}%"
        ),
        92,
    )
    emit(
        log,
        "info",
        (
            "容量结果："
            f"柴发={format_log_number(capacities['diesel_capacity'])}kW，"
            f"风电={format_log_number(capacities['wind_capacity'])}kW，"
            f"光伏={format_log_number(capacities['pv_capacity'])}kW，"
            f"储能PCS={format_log_number(capacities['storage_power_capacity'])}kW，"
            f"电池={format_log_number(capacities['storage_energy_capacity'])}kWh，"
            f"电制氢={format_log_number(capacities['electrolyzer_power_capacity'])}kW，"
            f"储氢={format_log_number(capacities['hydrogen_tank_capacity'])}Nm3，"
            f"燃料电池={format_log_number(capacities['fuel_cell_power_capacity'])}kW"
        ),
        95,
    )


def direct_zero_load_result(model: dict[str, Any], log: LogSink | None = None) -> dict[str, Any] | None:
    """Return the optimum directly when the full-year load is zero."""

    if model.get("frequency", {}).get("enabled"):
        return None
    if any(float(load) > 1e-9 for load in model["loads"]):
        return None
    quantities = {
        (device["key"], device["index"]): int(device["quantity_lower"])
        for devices in model["device_rows"].values()
        for device in devices
    }
    emit(log, "info", "全年负荷为0，使用台数下限和解析调度快速生成规划结果", 25)
    planning_rows = planning_rows_from_quantities(model, quantities)
    dispatch_rows = dispatch_rows_from_quantities(model, quantities)
    totals = dispatch_totals(dispatch_rows)
    costs = cost_summary_from_quantities(model, quantities, totals)
    return {
        "planning_rows": planning_rows,
        "dispatch_rows": dispatch_rows,
        "totals": totals,
        "costs": costs,
    }


def planning_rows_from_quantities(model: dict[str, Any], quantities: dict[tuple[str, int], int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in DEVICE_SPECS:
        for device in model["device_rows"][key]:
            quantity = int(quantities.get((device["key"], device["index"]), 0))
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


def dispatch_rows_from_quantities(model: dict[str, Any], quantities: dict[tuple[str, int], int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    storage_energy_capacity = sum(
        device["capacity"] * quantities.get((device["key"], device["index"]), 0)
        for device in model["device_rows"]["storage_battery_packs"]
    )
    hydrogen_capacity = sum(
        device["capacity"] * quantities.get((device["key"], device["index"]), 0)
        for device in model["device_rows"]["hydrogen_tanks"]
    )
    initial_storage = round(storage_energy_capacity * model["initial_storage_soc_ratio"], 4)
    initial_hydrogen = round(hydrogen_capacity * model["initial_hydrogen_storage_ratio"], 4)
    for hour, source_row in enumerate(model["time_series"]):
        load = round(float(model["loads"][hour]), 4)
        wind_available = sum(
            model["wind_available_per_unit"][device["id"]][hour] * quantities.get((device["key"], device["index"]), 0)
            for device in model["device_rows"]["wind_turbines"]
        )
        pv_available = sum(
            model["pv_available_per_unit"][device["id"]][hour] * quantities.get((device["key"], device["index"]), 0)
            for device in model["device_rows"]["photovoltaics"]
        )
        renewable_available = wind_available + pv_available
        renewable_power = 0.0
        hour_index = int(numeric(source_row.get("hour_index"), hour + 1) or hour + 1)
        security_fields = dispatch_security_curve_fields(
            model,
            load=load,
            wind_power=0.0,
            pv_power=0.0,
            renewable_single_unit_power_max=0.0,
            diesel_capacity=0.0,
            diesel_power=0.0,
            grid_storage_power=0.0,
            grid_storage_up_capacity=0.0,
            grid_storage_down_capacity=0.0,
        )
        rows.append(
            {
                "hour_index": hour_index,
                "datetime": source_row.get("datetime", f"H{hour_index:04d}"),
                "wind_speed": round(numeric(source_row.get("wind_speed"), 0.0), 4),
                "solar_irradiance": round(numeric(source_row.get("solar_irradiance"), 0.0), 4),
                "temperature": round(numeric(source_row.get("temperature"), 0.0), 4),
                "load": load,
                "diesel_power": 0.0,
                "diesel_capacity": 0.0,
                "wind_available": round(wind_available, 4),
                "wind_power": 0.0,
                "pv_available": round(pv_available, 4),
                "pv_power": 0.0,
                "renewable_power": round(renewable_power, 4),
                "renewable_available": round(renewable_available, 4),
                "renewable_ratio": 0.0,
                "storage_power": 0.0,
                "grid_storage_capacity": 0.0,
                "grid_storage_power": 0.0,
                "storage_charge": 0.0,
                "storage_discharge": 0.0,
                "storage_soc": initial_storage,
                "diesel_on": 0,
                "hydrogen_production_power": 0.0,
                "hydrogen_production": 0.0,
                "electrolyzer_on": 0,
                "fuel_cell_power": 0.0,
                "hydrogen_storage": initial_hydrogen,
                "wind_curtailed_power": round(wind_available, 4),
                "pv_curtailed_power": round(pv_available, 4),
                "curtailed_power": round(renewable_available, 4),
                "renewable_curtailed_rate": round(estimate.percent(renewable_available, renewable_available), 4),
                "unmet_load": 0.0,
                "diesel_consumption": 0.0,
                **security_fields,
            }
        )
    return rows


def cost_summary_from_quantities(
    model: dict[str, Any],
    quantities: dict[tuple[str, int], int],
    totals: dict[str, float],
) -> dict[str, float]:
    construction_cost = 0.0
    for devices in model["device_rows"].values():
        for device in devices:
            construction_cost += quantities.get((device["key"], device["index"]), 0) * device["annual_cost"]
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


def planning_rows_from_solution(model: dict[str, Any], solution: np.ndarray) -> list[dict[str, Any]]:
    # Translate optimized equipment quantities back into the table shape used
    # by the result page and workbook export.
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
    # Reconstruct hourly curves from the solution vector so charts and
    # statistics are generated from the same solved schedule.
    variables = model["variables"]
    rows: list[dict[str, Any]] = []
    diesel_devices = active_devices(model, "diesel_generators")
    electrolyzer_devices = active_devices(model, "hydrogen_electrolyzers")
    fuel_cell_devices = active_devices(model, "fuel_cells")
    grid_storage_pcs_devices = [
        device
        for device in model["device_rows"]["storage_pcs"]
        if device.get("is_grid_forming")
    ]

    def value(key: tuple[Any, ...]) -> float:
        return clean_solution_value(solution[variables[key]])

    def optional_value(key: tuple[Any, ...], default: float = 0.0) -> float:
        index = variables.get(key)
        return clean_solution_value(solution[index]) if index is not None else default

    def renewable_single_unit_power_max(hour: int) -> float:
        rate = min(1.0, max(0.0, optional_value(("renewable_curtailment_rate", hour), 0.0)))
        maximum = 0.0
        for device in model["device_rows"]["wind_turbines"]:
            if quantity_values.get((device["key"], device["index"]), 0) <= 0:
                continue
            per_unit = float(model["wind_available_per_unit"][device["id"]][hour])
            maximum = max(maximum, per_unit * (1.0 - rate))
        for device in model["device_rows"]["photovoltaics"]:
            if quantity_values.get((device["key"], device["index"]), 0) <= 0:
                continue
            per_unit = float(model["pv_available_per_unit"][device["id"]][hour])
            maximum = max(maximum, per_unit * (1.0 - rate))
        return maximum

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
        storage_charge = value(("storage_charge", hour))
        storage_discharge = value(("storage_discharge", hour))
        storage_power = storage_discharge - storage_charge
        grid_storage_charge = optional_value(("grid_storage_charge", hour), 0.0)
        grid_storage_discharge = optional_value(("grid_storage_discharge", hour), 0.0)
        grid_storage_power = grid_storage_discharge - grid_storage_charge
        diesel_capacity = sum(
            optional_value(("diesel_on_count", hour, device["index"])) * device["power_upper"]
            for device in diesel_devices
        )
        grid_storage_capacity = sum(
            optional_value(("grid_storage_on_count", hour, device["index"])) * device["capacity"]
            for device in grid_storage_pcs_devices
        )
        grid_storage_up_capacity = sum(
            optional_value(("grid_storage_up_available_count", hour, device["index"])) * device["capacity"]
            for device in grid_storage_pcs_devices
        )
        grid_storage_down_capacity = sum(
            optional_value(("grid_storage_down_available_count", hour, device["index"])) * device["capacity"]
            for device in grid_storage_pcs_devices
        )
        security_fields = dispatch_security_curve_fields(
            model,
            load=load,
            wind_power=wind_power,
            pv_power=pv_power,
            renewable_single_unit_power_max=renewable_single_unit_power_max(hour),
            diesel_capacity=diesel_capacity,
            diesel_power=diesel_power,
            grid_storage_power=grid_storage_power,
            grid_storage_up_capacity=grid_storage_up_capacity,
            grid_storage_down_capacity=grid_storage_down_capacity,
        )
        frequency_fields = evaluate_frequency_fields(
            model,
            hour=hour,
            load=load,
            wind_power=wind_power,
            pv_power=pv_power,
            diesel_devices=diesel_devices,
            grid_storage_pcs_devices=grid_storage_pcs_devices,
            optional_value=optional_value,
        )
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
                "diesel_capacity": round(diesel_capacity, 4),
                "wind_available": round(wind_available, 4),
                "wind_power": round(wind_power, 4),
                "pv_available": round(pv_available, 4),
                "pv_power": round(pv_power, 4),
                "renewable_power": round(renewable_energy, 4),
                "renewable_available": round(renewable_available, 4),
                "renewable_ratio": round(estimate.percent(renewable_energy, load), 4),
                "storage_power": round(storage_power, 4),
                "grid_storage_capacity": round(grid_storage_capacity, 4),
                "grid_storage_power": round(grid_storage_power, 4),
                "storage_charge": round(storage_charge, 4),
                "storage_discharge": round(storage_discharge, 4),
                "storage_soc": round(value(("storage_soc", hour)), 4),
                "diesel_on": int(round(sum(
                    value(("diesel_on_count", hour, device["index"]))
                    for device in diesel_devices
                ))),
                "hydrogen_production_power": round(electrolyzer_power, 4),
                "hydrogen_production": round(hydrogen_production, 4),
                "electrolyzer_on": int(round(sum(
                    value(("electrolyzer_on_count", hour, device["index"]))
                    for device in electrolyzer_devices
                ))),
                "fuel_cell_power": round(fuel_cell_power, 4),
                "hydrogen_storage": round(value(("hydrogen_storage", hour)), 4),
                "wind_curtailed_power": round(wind_curtailed, 4),
                "pv_curtailed_power": round(pv_curtailed, 4),
                "curtailed_power": round(curtailed_power, 4),
                "renewable_curtailed_rate": round(estimate.percent(curtailed_power, renewable_available), 4),
                "unmet_load": round(value(("unmet_load", hour)), 4),
                "diesel_consumption": round(diesel_consumption, 8),
                **security_fields,
                **frequency_fields,
            }
        )
    return rows


def dispatch_totals(dispatch_rows: list[dict[str, Any]]) -> dict[str, float]:
    totals = {
        "load_energy": estimate.sum_numeric(dispatch_rows, "load"),
        "wind_energy": estimate.sum_numeric(dispatch_rows, "wind_power"),
        "pv_energy": estimate.sum_numeric(dispatch_rows, "pv_power"),
        "storage_discharge_energy": estimate.sum_numeric(dispatch_rows, "storage_discharge"),
        "storage_charge_energy": estimate.sum_numeric(dispatch_rows, "storage_charge"),
        "diesel_energy": estimate.sum_numeric(dispatch_rows, "diesel_power"),
        "curtailed_energy": estimate.sum_numeric(dispatch_rows, "curtailed_power"),
        "unmet_load_energy": estimate.sum_numeric(dispatch_rows, "unmet_load"),
        "hydrogen_production_energy": estimate.sum_numeric(dispatch_rows, "hydrogen_production_power"),
        "fuel_cell_energy": estimate.sum_numeric(dispatch_rows, "fuel_cell_power"),
        "wind_available_energy": estimate.sum_numeric(dispatch_rows, "wind_available"),
        "pv_available_energy": estimate.sum_numeric(dispatch_rows, "pv_available"),
        "renewable_available_energy": sum(
            numeric(row.get("renewable_available"), numeric(row.get("wind_available"), 0.0) + numeric(row.get("pv_available"), 0.0))
            for row in dispatch_rows
        ),
        "renewable_energy": sum(
            numeric(row.get("wind_power"), 0.0) + numeric(row.get("pv_power"), 0.0)
            for row in dispatch_rows
        ),
        "wind_curtailed_energy": estimate.sum_numeric(dispatch_rows, "wind_curtailed_power"),
        "pv_curtailed_energy": estimate.sum_numeric(dispatch_rows, "pv_curtailed_power"),
        "hydrogen_storage_increase": sum(estimate.positive_delta(dispatch_rows, "hydrogen_storage", 0.0)),
        "hydrogen_storage_decrease": sum(estimate.negative_delta(dispatch_rows, "hydrogen_storage", 0.0)),
    }
    totals["renewable_curtailed_rate"] = estimate.percent(totals["curtailed_energy"], totals["renewable_available_energy"])
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
    # Reported costs match the business objective: annualized construction
    # cost plus diesel cost. Load-shed/startup penalties only guide feasibility
    # and dispatch selection, so they are not displayed as economic costs.
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



def build_safety_daily_rows(
    dispatch_rows: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
    nominal_frequency_hz: float,
) -> list[dict[str, Any]]:
    safety_rows: list[dict[str, Any]] = []
    for day_index, daily_row in enumerate(daily_rows):
        rows = dispatch_rows[day_index * 24 : (day_index + 1) * 24]
        if not rows:
            rows = dispatch_rows
        if rows and any("frequency_min" in row or "frequency_max" in row for row in rows):
            frequency_max = max(numeric(row.get("frequency_max"), nominal_frequency_hz) for row in rows)
            frequency_min = min(numeric(row.get("frequency_min"), nominal_frequency_hz) for row in rows)
        else:
            unmet = numeric(daily_row.get("unmet_load_energy"), 0.0)
            frequency_max = nominal_frequency_hz if unmet <= 0 else nominal_frequency_hz - 0.2
            frequency_min = nominal_frequency_hz if unmet <= 0 else nominal_frequency_hz - 0.5
        safety_rows.append(
            {
                "day": daily_row.get("day", day_index + 1),
                "frequency_max": round(frequency_max, 4),
                "frequency_min": round(frequency_min, 4),
            }
        )
    return safety_rows


def frequency_risk_hour_count(dispatch_rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in dispatch_rows:
        lower_margin = row.get("frequency_lower_margin_hz")
        upper_margin = row.get("frequency_upper_margin_hz")
        if lower_margin is not None or upper_margin is not None:
            if numeric(lower_margin, 0.0) < -1e-7 or numeric(upper_margin, 0.0) < -1e-7:
                count += 1
        elif numeric(row.get("unmet_load"), 0.0) > 0:
            count += 1
    return count


def min_frequency_margin(dispatch_rows: list[dict[str, Any]], field: str) -> float:
    values = [numeric(row.get(field), math.inf) for row in dispatch_rows if row.get(field) is not None]
    return round(min(values), 4) if values else 0.0


def max_up_disturbance_requirement(dispatch_rows: list[dict[str, Any]]) -> float:
    values = []
    for row in dispatch_rows:
        if row.get("grid_up_regulation_requirement") is not None:
            values.append(max(0.0, numeric(row.get("grid_up_regulation_requirement"), 0.0)))
        else:
            values.append(
                max(0.0, numeric(row.get("load_up_disturbance_power"), 0.0))
                + max(0.0, numeric(row.get("renewable_down_disturbance_power"), 0.0))
            )
    return round(max(values), 4) if values else 0.0


def max_down_disturbance_requirement(dispatch_rows: list[dict[str, Any]]) -> float:
    values = []
    for row in dispatch_rows:
        value = row.get("grid_down_regulation_requirement")
        if value is None:
            value = row.get("load_down_disturbance_power")
        values.append(abs(numeric(value, 0.0)))
    return round(max(values), 4) if values else 0.0


def build_results(
    planning_rows: list[dict[str, Any]],
    dispatch_rows: list[dict[str, Any]],
    totals: dict[str, float],
    costs: dict[str, float],
    model: dict[str, Any],
) -> dict[str, Any]:
    # Keep result tables, cards and curve data grouped by view so the front end
    # can switch panels without reformatting raw solver output.
    green_ratio = totals["green_power_ratio"]
    curtailed_ratio = totals["renewable_curtailed_rate"]
    if len(dispatch_rows) == 8760:
        daily = estimate.aggregate_daily(dispatch_rows)
        monthly = estimate.aggregate_monthly(daily)
    else:
        daily = aggregate_daily_partial(dispatch_rows)
        monthly = aggregate_monthly_partial(daily)
    frequency_risk_hours = frequency_risk_hour_count(dispatch_rows)
    annual_rows = [
        *capacity_summary_rows(planning_rows),
        *estimate.annual_energy_rows(totals, green_ratio, curtailed_ratio),
        {"指标": "绿电年发电量", "数值": totals["green_generation_energy"], "单位": "kWh"},
        {"指标": "总发电量", "数值": totals["total_generation_energy"], "单位": "kWh"},
        {"指标": "绿色电量占比下限", "数值": round(model["green_ratio_lower"] * 100, 4), "单位": "%"},
        {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨"},
        {"指标": "年均建设成本", "数值": costs["annualized_construction_cost"], "单位": "万元"},
        {"指标": "年柴油成本", "数值": costs["annual_diesel_cost"], "单位": "万元"},
        {"指标": "年总成本", "数值": costs["annual_total_cost"], "单位": "万元"},
        {"指标": "总成本", "数值": costs["annual_total_cost"], "单位": "万元"},
        {"指标": "度电成本", "数值": costs["levelized_cost"], "单位": "元"},
        {"指标": "绿电占比", "数值": round(green_ratio, 4), "单位": "%"},
        {"指标": "频率风险点", "数值": frequency_risk_hours, "单位": "个"},
    ]
    nominal_frequency_hz = float(model.get("frequency", {}).get("nominal_frequency_hz", NOMINAL_FREQUENCY_HZ))
    safety_daily = build_safety_daily_rows(dispatch_rows, daily, nominal_frequency_hz)
    highest_frequency = max((point["frequency_max"] for point in safety_daily), default=nominal_frequency_hz)
    lowest_frequency = min((point["frequency_min"] for point in safety_daily), default=nominal_frequency_hz)
    min_lower_margin = min_frequency_margin(dispatch_rows, "frequency_lower_margin_hz")
    min_upper_margin = min_frequency_margin(dispatch_rows, "frequency_upper_margin_hz")
    upward_disturbance = max_up_disturbance_requirement(dispatch_rows)
    downward_disturbance = max_down_disturbance_requirement(dispatch_rows)
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
        {"指标": "度电成本", "数值": costs["levelized_cost"], "单位": "元"},
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
            capacity_composition_disk(planning_rows),
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
            {"指标": "度电成本", "数值": costs["levelized_cost"], "单位": "元", "说明": "年总成本折算"},
            {"指标": "绿电占比", "数值": round(green_ratio, 4), "单位": "%", "说明": "按风光、储能放电和燃料电池发电统计"},
            {"指标": "总成本", "数值": costs["annual_total_cost"], "单位": "万元", "说明": "年均建设成本加年柴油成本"},
        ],
        "green": [
            {"指标": "绿电占比", "数值": round(green_ratio, 4), "单位": "%", "说明": "满足规划参数中的绿色电量占比下限"},
            {"指标": "弃电率", "数值": round(curtailed_ratio, 4), "单位": "%", "说明": "新能源弃电量占新能源最大可发电量比例"},
            {"指标": "柴油消耗", "数值": totals["diesel_consumption"], "单位": "吨", "说明": "按各柴发油耗率逐时累计"},
        ],
        "green_table": green_table,
        "safety": [
            {"指标": "备用裕度", "数值": 0, "单位": "%", "说明": "基于优化出力结果统计"},
            {"指标": "频率下限裕度", "数值": min_lower_margin, "单位": "Hz", "说明": "频率最低点约束的最小裕度"},
            {"指标": "频率上限裕度", "数值": min_upper_margin, "单位": "Hz", "说明": "频率最高点约束的最小裕度"},
            {"指标": "频率安全校核", "数值": "通过" if frequency_risk_hours == 0 else "需复核", "单位": "", "说明": "规划求解结果的动态频率安全摘要"},
        ],
        "safety_table": [
            {"指标": "额定频率", "数值": round(nominal_frequency_hz, 4), "单位": "Hz"},
            {"指标": "向上扰动最大量", "数值": upward_disturbance, "单位": "kW"},
            {"指标": "向下扰动最大量", "数值": downward_disturbance, "单位": "kW"},
            {"指标": "最高频率", "数值": highest_frequency, "单位": "Hz"},
            {"指标": "最低频率", "数值": lowest_frequency, "单位": "Hz"},
            {"指标": "频率下限最小裕度", "数值": min_lower_margin, "单位": "Hz"},
            {"指标": "频率上限最小裕度", "数值": min_upper_margin, "单位": "Hz"},
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
    # The top-line metrics are a curated subset of the complete totals table.
    return [
        {"label": "柴油消耗", "value": totals["diesel_consumption"], "unit": "吨"},
        {"label": "年均建设成本", "value": costs["annualized_construction_cost"], "unit": "万元"},
        {"label": "年柴油成本", "value": costs["annual_diesel_cost"], "unit": "万元"},
        {"label": "年总成本", "value": costs["annual_total_cost"], "unit": "万元"},
        {"label": "度电成本", "value": costs["levelized_cost"], "unit": "元"},
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


def capacity_composition_disk(planning_rows: list[dict[str, Any]]) -> dict[str, Any]:
    capacities = estimate.capacities_from_planning_rows(planning_rows)
    return capacity_composition_disk_from_values(
        diesel_capacity=capacities["diesel_capacity"],
        wind_capacity=capacities["wind_capacity"],
        pv_capacity=capacities["pv_capacity"],
        storage_energy_capacity=capacities["storage_energy_capacity"],
        fuel_cell_power_capacity=capacities["fuel_cell_power_capacity"],
    )


def capacity_composition_disk_from_values(
    *,
    diesel_capacity: float = 0.0,
    wind_capacity: float = 0.0,
    pv_capacity: float = 0.0,
    storage_energy_capacity: float = 0.0,
    fuel_cell_power_capacity: float = 0.0,
) -> dict[str, Any]:
    return {
        "title": "容量构成",
        "unit": "kW/kWh",
        "segments": [
            {"label": "柴发容量", "value": round(numeric(diesel_capacity), 4), "unit": "kW"},
            {"label": "风电容量", "value": round(numeric(wind_capacity), 4), "unit": "kW"},
            {"label": "光伏容量", "value": round(numeric(pv_capacity), 4), "unit": "kW"},
            {"label": "电储能容量", "value": round(numeric(storage_energy_capacity), 4), "unit": "kWh"},
            {"label": "燃料电池容量", "value": round(numeric(fuel_cell_power_capacity), 4), "unit": "kW"},
        ],
    }


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


def format_log_number(value: Any) -> str:
    number = numeric(value, 0.0)
    if abs(number) >= 1000:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{number:.4f}".rstrip("0").rstrip(".")


def emit(log: LogSink | None, level: str, message: str, progress: int | None = None) -> None:
    if not log:
        return
    event = {"level": level, "message": message}
    if progress is not None:
        event["progress"] = progress
    log(event)
