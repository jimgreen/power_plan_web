#!/usr/bin/env python3
"""Independent supply-reliability assessment for a fixed microgrid design.

The planning MILP intentionally enforces zero load shedding.  This module does
not alter that contract.  It is a post-planning checker that applies
deterministic N-1 outages and sequential two-state equipment outages to a
fixed equipment configuration, then performs an hourly adequacy dispatch.

All public entry points are pure calculation functions: they do not read or
write files, use global random state, or mutate caller-owned dictionaries.
Returned payloads contain only JSON-serializable Python values.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any, Mapping, Sequence

import estimate


SCHEMA_VERSION = "1.0"
HOURS_PER_CALENDAR_YEAR = 8760.0
NUMERIC_EPSILON = 1e-12
DEFAULT_UNSERVED_THRESHOLD_KW = 1e-6

DEVICE_TYPE_LABELS = {
    "diesel": "柴发",
    "wind": "风机",
    "pv": "光伏",
    "pcs": "储能PCS",
    "battery": "储能电池组",
}

SOURCE_KEY_TO_DEVICE_TYPE = {
    "diesel_generators": "diesel",
    "wind_turbines": "wind",
    "photovoltaics": "pv",
    "storage_pcs": "pcs",
    "storage_battery_packs": "battery",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "seed": 20260712,
    "simulation_years": 100,
    "hours_per_year": None,
    "confidence_level": 0.95,
    "initial_availability": "stationary",
    "initial_storage_soc_ratio": 0.5,
    "unserved_threshold_kw": DEFAULT_UNSERVED_THRESHOLD_KW,
    "include_annual_samples": True,
    "include_device_contributions": True,
    "run_n_minus_one": True,
    "dispatch_policy": "renewable_storage_diesel",
}


def numeric(value: Any, default: float = 0.0) -> float:
    """Return a finite float without allowing NaN/Infinity into the payload."""

    if value in (None, ""):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def truthy(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "启用", "开启"}


def first_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        first = value[0]
        return dict(first) if isinstance(first, Mapping) else {}
    return {}


def fraction(value: Any, default: float = 0.0, *, field_name: str = "比例") -> float:
    """Normalize a fraction, accepting either 0..1 or an explicit percentage."""

    number = numeric(value, default)
    if 1.0 < number <= 100.0:
        number /= 100.0
    if number < 0.0 or number > 1.0:
        raise ValueError(f"{field_name}必须位于0~1（或0~100%）之间，当前值为{value}")
    return float(number)


def non_negative_int(value: Any, default: int = 0, *, field_name: str = "数量") -> int:
    number = numeric(value, float(default))
    if number < -NUMERIC_EPSILON:
        raise ValueError(f"{field_name}不能为负数，当前值为{value}")
    return max(0, int(round(number)))


def device_value(row: Mapping[str, Any], aliases: Sequence[str], default: Any = None) -> Any:
    """Read a device field from the row or a nested reliability dictionary."""

    sources: list[Mapping[str, Any]] = [row]
    for nested_key in ("reliability", "reliability_parameters", "可靠性参数"):
        nested = row.get(nested_key)
        if isinstance(nested, Mapping):
            sources.append(nested)
    for source in sources:
        for alias in aliases:
            if alias in source and source.get(alias) not in (None, ""):
                return source.get(alias)
    return default


def normalize_config(scheme_payload: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge defaults, payload reliability settings, and explicit overrides."""

    payload_config = first_mapping(scheme_payload.get("reliability_parameters"))
    planning_parameters = first_mapping(scheme_payload.get("planning_parameters"))
    explicit = dict(config or {})

    aliases = {
        "seed": ("seed", "random_seed", "monte_carlo_seed"),
        "simulation_years": ("simulation_years", "monte_carlo_years", "sample_years"),
        "hours_per_year": ("hours_per_year", "simulation_hours_per_year"),
        "confidence_level": ("confidence_level",),
        "initial_availability": ("initial_availability", "initial_equipment_state"),
        "initial_storage_soc_ratio": ("initial_storage_soc_ratio", "storage_initial_soc"),
        "unserved_threshold_kw": ("unserved_threshold_kw", "loss_of_load_threshold_kw"),
        "include_annual_samples": ("include_annual_samples",),
        "include_device_contributions": ("include_device_contributions",),
        "run_n_minus_one": ("run_n_minus_one", "n_minus_one_enabled"),
        "dispatch_policy": ("dispatch_policy", "reliability_dispatch_policy"),
    }

    merged = dict(DEFAULT_CONFIG)
    for canonical, names in aliases.items():
        for source in (planning_parameters, payload_config, explicit):
            for name in names:
                if name in source and source.get(name) not in (None, ""):
                    merged[canonical] = source.get(name)

    merged["seed"] = int(round(numeric(merged.get("seed"), DEFAULT_CONFIG["seed"])))
    merged["simulation_years"] = non_negative_int(
        merged.get("simulation_years"),
        DEFAULT_CONFIG["simulation_years"],
        field_name="蒙特卡洛年数",
    )
    if merged["simulation_years"] <= 0:
        raise ValueError("蒙特卡洛年数必须大于0")
    if merged.get("hours_per_year") in (None, ""):
        merged["hours_per_year"] = None
    else:
        merged["hours_per_year"] = non_negative_int(
            merged.get("hours_per_year"), 0, field_name="每年模拟小时数"
        )
        if merged["hours_per_year"] <= 0:
            raise ValueError("每年模拟小时数必须大于0")
    merged["confidence_level"] = fraction(
        merged.get("confidence_level"), 0.95, field_name="置信水平"
    )
    if not 0.5 < merged["confidence_level"] < 1.0:
        raise ValueError("置信水平必须大于0.5且小于1")
    initial_availability = str(merged.get("initial_availability") or "stationary").strip().lower()
    initial_aliases = {
        "stationary": "stationary",
        "稳态": "stationary",
        "随机稳态": "stationary",
        "all_up": "all_up",
        "all-up": "all_up",
        "全部可用": "all_up",
    }
    if initial_availability not in initial_aliases:
        raise ValueError("初始设备状态仅支持stationary或all_up")
    merged["initial_availability"] = initial_aliases[initial_availability]
    merged["initial_storage_soc_ratio"] = fraction(
        merged.get("initial_storage_soc_ratio"), 0.5, field_name="储能初始SOC"
    )
    merged["unserved_threshold_kw"] = max(
        0.0, numeric(merged.get("unserved_threshold_kw"), DEFAULT_UNSERVED_THRESHOLD_KW)
    )
    for key in ("include_annual_samples", "include_device_contributions", "run_n_minus_one"):
        merged[key] = truthy(merged.get(key), bool(DEFAULT_CONFIG[key]))
    policy = str(merged.get("dispatch_policy") or "renewable_storage_diesel").strip().lower()
    policy_aliases = {
        "renewable_storage_diesel": "renewable_storage_diesel",
        "storage_first": "renewable_storage_diesel",
        "储能优先": "renewable_storage_diesel",
        "renewable_diesel_storage": "renewable_diesel_storage",
        "diesel_first": "renewable_diesel_storage",
        "柴发优先": "renewable_diesel_storage",
    }
    if policy not in policy_aliases:
        raise ValueError("快速调度策略仅支持储能优先或柴发优先")
    merged["dispatch_policy"] = policy_aliases[policy]
    return merged


def installed_count(row: Mapping[str, Any]) -> tuple[int, str]:
    """Resolve the fixed installed count and report how it was obtained."""

    explicit_aliases = (
        "installed_quantity",
        "design_quantity",
        "selected_quantity",
        "fixed_quantity",
        "quantity",
        "设计台数",
    )
    value = device_value(row, explicit_aliases, None)
    if value not in (None, ""):
        return non_negative_int(value, field_name="设备安装台数"), "explicit"

    lower = device_value(row, ("quantity_lower",), None)
    upper = device_value(row, ("quantity_upper",), None)
    if lower not in (None, "") and upper not in (None, ""):
        lower_count = non_negative_int(lower, field_name="设备台数下限")
        upper_count = non_negative_int(upper, field_name="设备台数上限")
        if lower_count == upper_count:
            return lower_count, "fixed_bounds"
        return upper_count, "quantity_upper"
    if upper not in (None, ""):
        return non_negative_int(upper, field_name="设备台数上限"), "quantity_upper"
    if lower not in (None, ""):
        return non_negative_int(lower, field_name="设备台数下限"), "quantity_lower"
    return 0, "default_zero"


def forced_outage_parameters(row: Mapping[str, Any], name: str) -> tuple[float, float]:
    raw_for = device_value(
        row,
        (
            "forced_outage_rate",
            "forced_outage_rate_for",
            "forced_outage_probability",
            "FOR",
            "for",
            "强迫停运率",
        ),
        0.0,
    )
    forced_outage_rate = fraction(raw_for, 0.0, field_name=f"{name}强迫停运率FOR")
    mttr_hours = max(
        0.0,
        numeric(
            device_value(
                row,
                (
                    "mttr_hours",
                    "mean_time_to_repair_hours",
                    "repair_time_hours",
                    "MTTR",
                    "mttr",
                    "平均修复时间",
                ),
                0.0,
            ),
            0.0,
        ),
    )
    if 0.0 < forced_outage_rate < 1.0 and mttr_hours <= 0.0:
        raise ValueError(f"{name}设置了非零FOR，必须同时提供大于0的MTTR小时数")
    return forced_outage_rate, mttr_hours


def output_derating_factor(row: Mapping[str, Any], device_type: str) -> float:
    factor_fields = ["output_derating_factor", "capacity_derating_factor"]
    loss_fields = ["output_loss_rate"]
    if device_type == "wind":
        factor_fields += ["cold_derating_factor", "icing_derating_factor"]
        loss_fields += ["cold_loss_rate", "icing_loss_rate"]
    elif device_type == "pv":
        factor_fields += [
            "inverter_efficiency",
            "system_derating_factor",
            "snow_derating_factor",
            "temperature_derating_factor",
        ]
        loss_fields += ["system_loss_rate", "snow_loss_rate", "temperature_loss_rate"]

    result = 1.0
    for field in factor_fields:
        value = device_value(row, (field,), None)
        if value not in (None, ""):
            result *= fraction(value, 1.0, field_name=field)
    for field in loss_fields:
        value = device_value(row, (field,), None)
        if value not in (None, ""):
            result *= 1.0 - fraction(value, 0.0, field_name=field)
    return min(1.0, max(0.0, float(result)))


def profile_value(row: Mapping[str, Any], aliases: Sequence[str]) -> float | None:
    for alias in aliases:
        if alias in row and row.get(alias) not in (None, ""):
            return max(0.0, numeric(row.get(alias), 0.0))
    return None


def renewable_profile(
    device_type: str,
    row: Mapping[str, Any],
    time_series: Sequence[Mapping[str, Any]],
    capacity_kw: float,
) -> list[float]:
    derating = output_derating_factor(row, device_type)
    profile: list[float] = []
    for time_row in time_series:
        if device_type == "wind":
            explicit = profile_value(
                time_row,
                ("wind_available_per_unit_kw", "wind_power_per_unit_kw", "wind_unit_power_kw"),
            )
            if explicit is None and time_row.get("wind_capacity_factor") not in (None, ""):
                explicit = capacity_kw * fraction(
                    time_row.get("wind_capacity_factor"), 0.0, field_name="风电容量因子"
                )
            generation = (
                explicit
                if explicit is not None
                else estimate.wind_generation(
                    numeric(time_row.get("wind_speed"), 0.0), capacity_kw, dict(row)
                )
            )
        else:
            explicit = profile_value(
                time_row,
                ("pv_available_per_unit_kw", "pv_power_per_unit_kw", "pv_unit_power_kw"),
            )
            if explicit is None and time_row.get("pv_capacity_factor") not in (None, ""):
                explicit = capacity_kw * fraction(
                    time_row.get("pv_capacity_factor"), 0.0, field_name="光伏容量因子"
                )
            generation = (
                explicit
                if explicit is not None
                else estimate.pv_generation(
                    numeric(time_row.get("solar_irradiance"), 0.0), capacity_kw, dict(row)
                )
            )
        profile.append(round(min(capacity_kw, max(0.0, generation * derating)), 10))
    return profile


def build_device_group(
    source_key: str,
    row_index: int,
    row: Mapping[str, Any],
    time_series: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    device_type = SOURCE_KEY_TO_DEVICE_TYPE[source_key]
    name = str(row.get("name") or f"{DEVICE_TYPE_LABELS[device_type]}{row_index + 1}")
    count, quantity_source = installed_count(row)
    if quantity_source == "quantity_upper":
        warnings.append(f"{name}未提供固定设计台数，可靠性计算暂按quantity_upper={count}处理")

    forced_outage_rate, mttr_hours = forced_outage_parameters(row, name)
    group: dict[str, Any] = {
        "id": f"{source_key}:{row_index}",
        "source_key": source_key,
        "source_index": row_index,
        "device_type": device_type,
        "device_type_label": DEVICE_TYPE_LABELS[device_type],
        "name": name,
        "unit_count": count,
        "quantity_source": quantity_source,
        "forced_outage_rate": forced_outage_rate,
        "mttr_hours": mttr_hours,
        "cost_per_unit_10k_cny": max(0.0, numeric(row.get("cost"), 0.0)),
    }

    if device_type == "diesel":
        capacity = max(0.0, numeric(row.get("power_upper"), numeric(row.get("capacity"), 0.0)))
        group["unit_capacity_kw"] = capacity
        group["minimum_power_kw"] = max(0.0, numeric(row.get("power_lower"), 0.0))
    elif device_type == "wind":
        capacity = max(0.0, numeric(row.get("capacity"), 0.0))
        group["unit_capacity_kw"] = capacity
        group["output_derating_factor"] = output_derating_factor(row, device_type)
        group["available_power_per_unit_kw"] = renewable_profile(
            device_type, row, time_series, capacity
        )
    elif device_type == "pv":
        capacity = max(0.0, numeric(row.get("capacity"), 0.0))
        group["unit_capacity_kw"] = capacity
        group["output_derating_factor"] = output_derating_factor(row, device_type)
        group["available_power_per_unit_kw"] = renewable_profile(
            device_type, row, time_series, capacity
        )
    elif device_type == "pcs":
        group["unit_capacity_kw"] = max(0.0, numeric(row.get("power_capacity"), 0.0))
        group["charge_efficiency"] = fraction(
            row.get("storage_charge_efficiency"), 0.95, field_name=f"{name}充电效率"
        )
        group["discharge_efficiency"] = fraction(
            row.get("storage_discharge_efficiency"), 0.95, field_name=f"{name}放电效率"
        )
        if group["charge_efficiency"] <= 0 or group["discharge_efficiency"] <= 0:
            raise ValueError(f"{name}充放电效率必须大于0")
    elif device_type == "battery":
        group["unit_capacity_kwh"] = max(0.0, numeric(row.get("battery_capacity"), 0.0))
        group["soc_lower"] = fraction(row.get("soc_lower"), 0.1, field_name=f"{name} SOC下限")
        group["soc_upper"] = fraction(row.get("soc_upper"), 0.9, field_name=f"{name} SOC上限")
        if group["soc_lower"] > group["soc_upper"]:
            raise ValueError(f"{name} SOC下限不能高于SOC上限")
        initial_soc = device_value(row, ("initial_soc_ratio", "initial_storage_soc_ratio"), None)
        group["initial_soc_ratio"] = (
            fraction(initial_soc, config["initial_storage_soc_ratio"], field_name=f"{name}初始SOC")
            if initial_soc not in (None, "")
            else float(config["initial_storage_soc_ratio"])
        )
        if not group["soc_lower"] <= group["initial_soc_ratio"] <= group["soc_upper"]:
            raise ValueError(f"{name}初始SOC必须位于SOC上下限之间")
        group["self_discharge_rate_per_day"] = fraction(
            row.get("self_discharge_rate"), 0.0, field_name=f"{name}日自损耗率"
        )
    return group


def build_reliability_case(
    scheme_payload: Mapping[str, Any],
    planning_result_rows: list[dict[str, Any]] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a scheme and fixed planning result into a reliability case.

    ``planning_result_rows`` is optional.  When supplied, the existing
    evaluation mapping is reused to fix every device quantity to the selected
    planning result.  Without it, explicit quantity fields or fixed lower/upper
    bounds are used; a non-fixed upper bound is accepted with a warning.
    """

    if not isinstance(scheme_payload, Mapping):
        raise TypeError("scheme_payload必须是字典")
    payload = (
        estimate.fixed_quantity_payload(dict(scheme_payload), planning_result_rows)
        if planning_result_rows is not None
        else dict(scheme_payload)
    )
    time_series_raw = payload.get("time_series")
    if not isinstance(time_series_raw, Sequence) or isinstance(time_series_raw, (str, bytes)):
        raise ValueError("可靠性评估需要小时级time_series列表")
    time_series = [dict(row) for row in time_series_raw if isinstance(row, Mapping)]
    if not time_series:
        raise ValueError("可靠性评估至少需要1个小时的时序数据")

    normalized_config = normalize_config(payload, config)
    load_kw = [max(0.0, numeric(row.get("load"), 0.0)) for row in time_series]
    warnings: list[str] = []
    groups: list[dict[str, Any]] = []
    for source_key in SOURCE_KEY_TO_DEVICE_TYPE:
        rows = payload.get(source_key)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            groups.append(
                build_device_group(
                    source_key,
                    index,
                    row,
                    time_series,
                    normalized_config,
                    warnings,
                )
            )

    if not any(group["device_type"] == "pcs" and group["unit_count"] > 0 for group in groups):
        if any(group["device_type"] == "battery" and group["unit_count"] > 0 for group in groups):
            warnings.append("已配置储能电池组但没有已安装PCS，快速调度中储能无法充放电")
    if not any(group["device_type"] == "battery" and group["unit_count"] > 0 for group in groups):
        if any(group["device_type"] == "pcs" and group["unit_count"] > 0 for group in groups):
            warnings.append("已配置储能PCS但没有已安装电池组，快速调度中储能无法充放电")

    return {
        "schema_version": SCHEMA_VERSION,
        "scheme": str(payload.get("scheme") or payload.get("name") or ""),
        "time_step_hours": 1.0,
        "source_hours": len(time_series),
        "load_kw": load_kw,
        "groups": groups,
        "config": normalized_config,
        "warnings": unique_strings(warnings),
    }


def two_state_transition_probabilities(
    forced_outage_rate: float,
    mttr_hours: float,
    time_step_hours: float = 1.0,
) -> dict[str, float | None]:
    """Return exact CTMC transition probabilities sampled at fixed intervals.

    FOR is the stationary down-state probability.  With repair rate
    ``mu=1/MTTR`` and failure rate ``lambda=FOR/(1-FOR)*mu``, the transition
    matrix exponential preserves the requested stationary FOR at hourly sample
    points instead of using a small-probability approximation.
    """

    q = fraction(forced_outage_rate, field_name="强迫停运率FOR")
    dt = numeric(time_step_hours, 1.0)
    if dt <= 0:
        raise ValueError("抽样时间步长必须大于0")
    repair_hours = max(0.0, numeric(mttr_hours, 0.0))
    if q <= 0.0:
        return {
            "up_to_down": 0.0,
            "down_to_up": 0.0,
            "mttf_hours": None,
            "mttr_hours": repair_hours,
        }
    if q >= 1.0:
        return {
            "up_to_down": 1.0,
            "down_to_up": 0.0,
            "mttf_hours": 0.0,
            "mttr_hours": repair_hours,
        }
    if repair_hours <= 0:
        raise ValueError("非零FOR必须配套大于0的MTTR小时数")
    repair_rate = 1.0 / repair_hours
    failure_rate = q / (1.0 - q) * repair_rate
    relaxation = 1.0 - math.exp(-(failure_rate + repair_rate) * dt)
    return {
        "up_to_down": min(1.0, max(0.0, q * relaxation)),
        "down_to_up": min(1.0, max(0.0, (1.0 - q) * relaxation)),
        "mttf_hours": 1.0 / failure_rate,
        "mttr_hours": repair_hours,
    }


def sample_two_state_unit_availability(
    unit_count: int,
    forced_outage_rate: float,
    mttr_hours: float,
    hours: int,
    *,
    seed: int = 0,
    initial_state: str = "stationary",
    time_step_hours: float = 1.0,
) -> list[list[bool]]:
    """Sample independent sequential up/down states for every physical unit."""

    count = non_negative_int(unit_count, field_name="设备台数")
    horizon = non_negative_int(hours, field_name="抽样小时数")
    if horizon <= 0:
        raise ValueError("抽样小时数必须大于0")
    q = fraction(forced_outage_rate, field_name="强迫停运率FOR")
    initial = str(initial_state or "stationary").strip().lower()
    if initial not in {"stationary", "all_up"}:
        raise ValueError("初始状态仅支持stationary或all_up")
    transition = two_state_transition_probabilities(q, mttr_hours, time_step_hours)
    rng = random.Random(int(seed))
    states: list[list[bool]] = []
    for _ in range(count):
        up = True if initial == "all_up" else rng.random() >= q
        unit_states: list[bool] = []
        for _hour in range(horizon):
            unit_states.append(bool(up))
            draw = rng.random()
            if up:
                if draw < transition["up_to_down"]:
                    up = False
            elif draw < transition["down_to_up"]:
                up = True
        states.append(unit_states)
    return states


def sample_two_state_availability(
    unit_count: int,
    forced_outage_rate: float,
    mttr_hours: float,
    hours: int,
    *,
    seed: int = 0,
    initial_state: str = "stationary",
    time_step_hours: float = 1.0,
) -> list[int]:
    """Return the available-unit count for each hour using a fixed seed."""

    states = sample_two_state_unit_availability(
        unit_count,
        forced_outage_rate,
        mttr_hours,
        hours,
        seed=seed,
        initial_state=initial_state,
        time_step_hours=time_step_hours,
    )
    if not states:
        return [0 for _ in range(non_negative_int(hours, field_name="抽样小时数"))]
    return [sum(1 for unit in states if unit[hour]) for hour in range(len(states[0]))]


def sample_fleet_availability(
    case: Mapping[str, Any],
    hours: int,
    *,
    seed: int,
    initial_state: str | None = None,
) -> dict[str, list[list[bool]]]:
    """Sample every group with deterministic independent child seeds."""

    horizon = non_negative_int(hours, field_name="每年模拟小时数")
    if horizon <= 0:
        raise ValueError("每年模拟小时数必须大于0")
    master = random.Random(int(seed))
    initial = str(initial_state or case.get("config", {}).get("initial_availability") or "stationary")
    result: dict[str, list[list[bool]]] = {}
    for group in case.get("groups", []):
        group_seed = master.getrandbits(63)
        result[str(group["id"])] = sample_two_state_unit_availability(
            int(group["unit_count"]),
            float(group["forced_outage_rate"]),
            float(group["mttr_hours"]),
            horizon,
            seed=group_seed,
            initial_state=initial,
            time_step_hours=numeric(case.get("time_step_hours"), 1.0),
        )
    return result


def availability_spec(
    group: Mapping[str, Any],
    raw: Any,
    hours: int,
) -> dict[str, Any]:
    count = int(group.get("unit_count", 0))
    if raw is None:
        return {"mode": "all_up", "unit_count": count}
    if isinstance(raw, Mapping):
        raw = raw.get("unit_states", raw.get("available_counts"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"{group.get('name')}可用状态必须是逐小时台数或逐台布尔序列")
    values = list(raw)
    if not values:
        if count == 0:
            return {"mode": "all_up", "unit_count": 0}
        raise ValueError(f"{group.get('name')}可用状态不能为空")

    if all(isinstance(value, Sequence) and not isinstance(value, (str, bytes)) for value in values):
        if len(values) != count:
            raise ValueError(f"{group.get('name')}逐台状态数量与安装台数不一致")
        unit_states = [list(unit) for unit in values]
        if any(len(unit) < hours for unit in unit_states):
            raise ValueError(f"{group.get('name')}逐台状态长度不足{hours}小时")
        return {"mode": "unit_states", "unit_count": count, "values": unit_states}

    if len(values) < hours:
        raise ValueError(f"{group.get('name')}可用台数序列长度不足{hours}小时")
    counts = [min(count, non_negative_int(value, field_name=f"{group.get('name')}可用台数")) for value in values]
    return {"mode": "counts", "unit_count": count, "values": counts}


def normalize_availability(
    case: Mapping[str, Any],
    availability: Mapping[str, Any] | None,
    hours: int,
) -> dict[str, dict[str, Any]]:
    source = availability or {}
    return {
        str(group["id"]): availability_spec(group, source.get(str(group["id"])), hours)
        for group in case.get("groups", [])
    }


def available_unit_indices(spec: Mapping[str, Any], hour: int) -> list[int]:
    count = int(spec.get("unit_count", 0))
    mode = spec.get("mode")
    if mode == "all_up":
        return list(range(count))
    if mode == "counts":
        return list(range(int(spec["values"][hour])))
    return [index for index, unit in enumerate(spec["values"]) if bool(unit[hour])]


def available_unit_count(spec: Mapping[str, Any], hour: int) -> int:
    mode = spec.get("mode")
    if mode == "all_up":
        return int(spec.get("unit_count", 0))
    if mode == "counts":
        return int(spec["values"][hour])
    return sum(1 for unit in spec["values"] if bool(unit[hour]))


def weighted_pcs_efficiency(
    pcs_groups: Sequence[Mapping[str, Any]],
    specs: Mapping[str, Mapping[str, Any]],
    hour: int,
    field: str,
) -> tuple[float, float]:
    capacity = 0.0
    weighted = 0.0
    for group in pcs_groups:
        available = available_unit_count(specs[str(group["id"])], hour)
        power = available * float(group.get("unit_capacity_kw", 0.0))
        capacity += power
        weighted += power * float(group.get(field, 0.95))
    return capacity, weighted / capacity if capacity > NUMERIC_EPSILON else 0.0


def allocate_battery_energy(
    battery_groups: Sequence[Mapping[str, Any]],
    battery_energy: dict[str, list[float]],
    available_indices: Mapping[str, Sequence[int]],
    energy_kwh: float,
    *,
    direction: str,
) -> float:
    """Charge or discharge available packs proportionally to their room."""

    requested = max(0.0, float(energy_kwh))
    candidates: list[tuple[str, int, float]] = []
    for group in battery_groups:
        group_id = str(group["id"])
        unit_capacity = float(group.get("unit_capacity_kwh", 0.0))
        lower = unit_capacity * float(group.get("soc_lower", 0.0))
        upper = unit_capacity * float(group.get("soc_upper", 1.0))
        for unit_index in available_indices.get(group_id, []):
            current = battery_energy[group_id][unit_index]
            room = max(0.0, upper - current) if direction == "charge" else max(0.0, current - lower)
            if room > NUMERIC_EPSILON:
                candidates.append((group_id, int(unit_index), room))
    total_room = sum(item[2] for item in candidates)
    applied = min(requested, total_room)
    if applied <= NUMERIC_EPSILON:
        return 0.0
    remaining = applied
    for position, (group_id, unit_index, room) in enumerate(candidates):
        portion = remaining if position == len(candidates) - 1 else applied * room / total_room
        portion = min(portion, room)
        if direction == "charge":
            battery_energy[group_id][unit_index] += portion
        else:
            battery_energy[group_id][unit_index] -= portion
        remaining -= portion
    return applied


def summarize_storage(
    battery_groups: Sequence[Mapping[str, Any]],
    battery_energy: Mapping[str, Sequence[float]],
    available_indices: Mapping[str, Sequence[int]],
) -> dict[str, float]:
    installed_capacity = 0.0
    installed_energy = 0.0
    available_capacity = 0.0
    available_energy = 0.0
    for group in battery_groups:
        group_id = str(group["id"])
        unit_capacity = float(group.get("unit_capacity_kwh", 0.0))
        energies = battery_energy.get(group_id, [])
        installed_capacity += unit_capacity * len(energies)
        installed_energy += sum(float(value) for value in energies)
        indices = available_indices.get(group_id, [])
        available_capacity += unit_capacity * len(indices)
        available_energy += sum(float(energies[index]) for index in indices)
    return {
        "installed_capacity_kwh": installed_capacity,
        "stored_energy_kwh": installed_energy,
        "soc_ratio": installed_energy / installed_capacity if installed_capacity > 0 else 0.0,
        "available_capacity_kwh": available_capacity,
        "available_stored_energy_kwh": available_energy,
        "available_soc_ratio": available_energy / available_capacity if available_capacity > 0 else 0.0,
    }


def dispatch_hourly(
    case: Mapping[str, Any],
    availability: Mapping[str, Any] | None = None,
    *,
    hours: int | None = None,
    include_hourly: bool = False,
    unserved_threshold_kw: float | None = None,
    dispatch_policy: str | None = None,
) -> dict[str, Any]:
    """Run a fast hourly adequacy dispatch for one fixed availability trace.

    Renewable output is used first.  The default policy then discharges
    storage before diesel; an optional diesel-first policy is also available.
    Surplus renewable generation charges storage subject to PCS power,
    efficiency, battery availability, and per-pack SOC limits.  A failed
    battery retains its energy (and self-discharges) but cannot charge or
    discharge until repaired.
    """

    load_profile = [max(0.0, numeric(value, 0.0)) for value in case.get("load_kw", [])]
    if not load_profile:
        raise ValueError("可靠性case缺少load_kw时序")
    horizon = len(load_profile) if hours is None else non_negative_int(hours, field_name="调度小时数")
    if horizon <= 0:
        raise ValueError("调度小时数必须大于0")
    dt = numeric(case.get("time_step_hours"), 1.0)
    if dt <= 0:
        raise ValueError("调度时间步长必须大于0")
    config = dict(case.get("config") or {})
    threshold = (
        max(0.0, numeric(unserved_threshold_kw, 0.0))
        if unserved_threshold_kw is not None
        else max(0.0, numeric(config.get("unserved_threshold_kw"), DEFAULT_UNSERVED_THRESHOLD_KW))
    )
    policy = str(dispatch_policy or config.get("dispatch_policy") or "renewable_storage_diesel")
    if policy not in {"renewable_storage_diesel", "renewable_diesel_storage"}:
        raise ValueError("未知快速调度策略")

    groups = [dict(group) for group in case.get("groups", [])]
    groups_by_type = {
        device_type: [group for group in groups if group.get("device_type") == device_type]
        for device_type in DEVICE_TYPE_LABELS
    }
    specs = normalize_availability(case, availability, horizon)

    battery_groups = groups_by_type["battery"]
    battery_energy: dict[str, list[float]] = {}
    for group in battery_groups:
        group_id = str(group["id"])
        initial_energy = float(group.get("unit_capacity_kwh", 0.0)) * float(group.get("initial_soc_ratio", 0.5))
        battery_energy[group_id] = [initial_energy for _ in range(int(group.get("unit_count", 0)))]

    load_energy = 0.0
    renewable_energy = 0.0
    diesel_energy = 0.0
    storage_charge_energy = 0.0
    storage_discharge_energy = 0.0
    curtailed_energy = 0.0
    ens = 0.0
    lole = 0.0
    lolf = 0
    max_deficit = 0.0
    longest_outage = 0.0
    current_outage = 0.0
    previous_shortage = False
    hourly_rows: list[dict[str, Any]] = []
    available_unit_hours = {str(group["id"]): 0.0 for group in groups}

    for hour in range(horizon):
        source_hour = hour % len(load_profile)
        load = load_profile[source_hour]
        load_energy += load * dt

        for group in battery_groups:
            group_id = str(group["id"])
            self_discharge = float(group.get("self_discharge_rate_per_day", 0.0)) / 24.0 * dt
            if self_discharge <= 0:
                continue
            battery_energy[group_id] = [max(0.0, value * (1.0 - self_discharge)) for value in battery_energy[group_id]]

        counts: dict[str, int] = {}
        for group in groups:
            group_id = str(group["id"])
            count = available_unit_count(specs[group_id], hour)
            counts[group_id] = count
            available_unit_hours[group_id] += count * dt

        wind_power = 0.0
        for group in groups_by_type["wind"]:
            profile = group.get("available_power_per_unit_kw") or [0.0]
            wind_power += counts[str(group["id"])] * float(profile[source_hour % len(profile)])
        pv_power = 0.0
        for group in groups_by_type["pv"]:
            profile = group.get("available_power_per_unit_kw") or [0.0]
            pv_power += counts[str(group["id"])] * float(profile[source_hour % len(profile)])
        renewable_power = max(0.0, wind_power + pv_power)

        diesel_capacity = sum(
            counts[str(group["id"])] * float(group.get("unit_capacity_kw", 0.0))
            for group in groups_by_type["diesel"]
        )
        pcs_charge_capacity, charge_efficiency = weighted_pcs_efficiency(
            groups_by_type["pcs"], specs, hour, "charge_efficiency"
        )
        pcs_discharge_capacity, discharge_efficiency = weighted_pcs_efficiency(
            groups_by_type["pcs"], specs, hour, "discharge_efficiency"
        )
        battery_available_indices = {
            str(group["id"]): available_unit_indices(specs[str(group["id"])], hour)
            for group in battery_groups
        }

        battery_headroom = 0.0
        battery_drawable = 0.0
        for group in battery_groups:
            group_id = str(group["id"])
            unit_capacity = float(group.get("unit_capacity_kwh", 0.0))
            lower = unit_capacity * float(group.get("soc_lower", 0.0))
            upper = unit_capacity * float(group.get("soc_upper", 1.0))
            for unit_index in battery_available_indices[group_id]:
                energy = battery_energy[group_id][unit_index]
                battery_headroom += max(0.0, upper - energy)
                battery_drawable += max(0.0, energy - lower)

        storage_charge = 0.0
        storage_discharge = 0.0
        diesel_power = 0.0
        unmet = 0.0
        curtailment = 0.0

        net = renewable_power - load
        if net >= 0.0:
            if pcs_charge_capacity > 0.0 and charge_efficiency > 0.0 and battery_headroom > 0.0:
                storage_charge = min(
                    net,
                    pcs_charge_capacity,
                    battery_headroom / max(charge_efficiency * dt, NUMERIC_EPSILON),
                )
                internal_charge = storage_charge * charge_efficiency * dt
                allocate_battery_energy(
                    battery_groups,
                    battery_energy,
                    battery_available_indices,
                    internal_charge,
                    direction="charge",
                )
            curtailment = max(0.0, net - storage_charge)
        else:
            deficit = -net

            def discharge_storage(remaining: float) -> tuple[float, float]:
                if (
                    remaining <= 0.0
                    or pcs_discharge_capacity <= 0.0
                    or discharge_efficiency <= 0.0
                    or battery_drawable <= 0.0
                ):
                    return 0.0, remaining
                power = min(
                    remaining,
                    pcs_discharge_capacity,
                    battery_drawable * discharge_efficiency / dt,
                )
                internal_draw = power * dt / discharge_efficiency
                applied = allocate_battery_energy(
                    battery_groups,
                    battery_energy,
                    battery_available_indices,
                    internal_draw,
                    direction="discharge",
                )
                delivered = applied * discharge_efficiency / dt
                return delivered, max(0.0, remaining - delivered)

            if policy == "renewable_storage_diesel":
                storage_discharge, deficit = discharge_storage(deficit)
                diesel_power = min(deficit, diesel_capacity)
                deficit -= diesel_power
            else:
                diesel_power = min(deficit, diesel_capacity)
                deficit -= diesel_power
                storage_discharge, deficit = discharge_storage(deficit)
            unmet = max(0.0, deficit)

        renewable_energy += min(load + storage_charge, renewable_power) * dt
        diesel_energy += diesel_power * dt
        storage_charge_energy += storage_charge * dt
        storage_discharge_energy += storage_discharge * dt
        curtailed_energy += curtailment * dt
        ens += unmet * dt
        max_deficit = max(max_deficit, unmet)
        shortage = unmet > threshold
        if shortage:
            lole += dt
            current_outage += dt
            longest_outage = max(longest_outage, current_outage)
            if not previous_shortage:
                lolf += 1
        else:
            current_outage = 0.0
        previous_shortage = shortage

        if include_hourly:
            storage = summarize_storage(battery_groups, battery_energy, battery_available_indices)
            hourly_rows.append(
                {
                    "hour": hour + 1,
                    "source_hour": source_hour + 1,
                    "load_kw": round(load, 6),
                    "wind_power_kw": round(wind_power, 6),
                    "pv_power_kw": round(pv_power, 6),
                    "storage_charge_kw": round(storage_charge, 6),
                    "storage_discharge_kw": round(storage_discharge, 6),
                    "diesel_power_kw": round(diesel_power, 6),
                    "unmet_load_kw": round(unmet, 6),
                    "curtailed_power_kw": round(curtailment, 6),
                    "storage_soc_ratio": round(storage["soc_ratio"], 8),
                    "available_units": {group_id: int(value) for group_id, value in counts.items()},
                }
            )

    final_available_indices = {
        str(group["id"]): available_unit_indices(specs[str(group["id"])], horizon - 1)
        for group in battery_groups
    }
    end_storage = summarize_storage(battery_groups, battery_energy, final_available_indices)
    duration = horizon * dt
    lpsp = ens / load_energy if load_energy > NUMERIC_EPSILON else 0.0
    lolp = lole / duration if duration > NUMERIC_EPSILON else 0.0
    availability_stats = []
    for group in groups:
        group_id = str(group["id"])
        installed_unit_hours = int(group.get("unit_count", 0)) * duration
        observed_unavailability = (
            1.0 - available_unit_hours[group_id] / installed_unit_hours
            if installed_unit_hours > NUMERIC_EPSILON
            else 0.0
        )
        availability_stats.append(
            {
                "device_id": group_id,
                "device_type": group["device_type"],
                "device_name": group["name"],
                "installed_units": int(group["unit_count"]),
                "available_unit_hours": round(available_unit_hours[group_id], 8),
                "mean_available_units": round(available_unit_hours[group_id] / duration, 8),
                "mean_unavailable_units": round(
                    int(group["unit_count"]) - available_unit_hours[group_id] / duration, 8
                ),
                "observed_unavailability": round(max(0.0, min(1.0, observed_unavailability)), 10),
            }
        )
    summary = {
        "hours": horizon,
        "time_step_hours": dt,
        "load_energy_kwh": round(load_energy, 8),
        "served_energy_kwh": round(max(0.0, load_energy - ens), 8),
        "renewable_energy_kwh": round(renewable_energy, 8),
        "diesel_energy_kwh": round(diesel_energy, 8),
        "storage_charge_energy_kwh": round(storage_charge_energy, 8),
        "storage_discharge_energy_kwh": round(storage_discharge_energy, 8),
        "curtailed_energy_kwh": round(curtailed_energy, 8),
        "ens_kwh": round(ens, 8),
        "lole_hours": round(lole, 8),
        "lolp": round(lolp, 12),
        "lolf_events": int(lolf),
        "lpsp": round(lpsp, 12),
        "energy_supply_reliability": round(max(0.0, min(1.0, 1.0 - lpsp)), 12),
        "time_supply_availability": round(max(0.0, min(1.0, 1.0 - lolp)), 12),
        "max_deficit_kw": round(max_deficit, 8),
        "longest_consecutive_outage_hours": round(longest_outage, 8),
        "end_storage": {key: round(value, 8) for key, value in end_storage.items()},
    }
    result: dict[str, Any] = {
        "summary": summary,
        "availability_stats": availability_stats,
    }
    if include_hourly:
        result["hourly"] = hourly_rows
    return result


def n_minus_one_device_types(value: Any) -> set[str]:
    if value in (None, "", []):
        return set(DEVICE_TYPE_LABELS)
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    aliases = {
        "diesel": "diesel",
        "diesel_generators": "diesel",
        "柴发": "diesel",
        "wind": "wind",
        "wind_turbines": "wind",
        "风机": "wind",
        "pv": "pv",
        "photovoltaics": "pv",
        "光伏": "pv",
        "pcs": "pcs",
        "storage_pcs": "pcs",
        "储能pcs": "pcs",
        "battery": "battery",
        "storage_battery_packs": "battery",
        "电池": "battery",
        "储能电池组": "battery",
    }
    result = set()
    for item in values:
        normalized = str(item).strip().lower()
        if normalized not in aliases:
            raise ValueError(f"未知N-1设备类型：{item}")
        result.add(aliases[normalized])
    return result


def run_n_minus_one(
    case: Mapping[str, Any],
    *,
    hours: int | None = None,
    device_types: Any = None,
    unserved_threshold_kw: float | None = None,
) -> dict[str, Any]:
    """Evaluate the all-up base case and every single-unit full-horizon outage."""

    horizon = int(hours or case.get("source_hours") or len(case.get("load_kw", [])))
    selected_types = n_minus_one_device_types(device_types)
    base = dispatch_hourly(
        case,
        hours=horizon,
        include_hourly=False,
        unserved_threshold_kw=unserved_threshold_kw,
    )["summary"]
    scenarios: list[dict[str, Any]] = []
    for group in case.get("groups", []):
        if group.get("device_type") not in selected_types or int(group.get("unit_count", 0)) <= 0:
            continue
        unit_count = int(group["unit_count"])
        states = [[True for _ in range(horizon)] for _ in range(unit_count)]
        states[0] = [False for _ in range(horizon)]
        availability = {str(group["id"]): states}
        summary = dispatch_hourly(
            case,
            availability,
            hours=horizon,
            include_hourly=False,
            unserved_threshold_kw=unserved_threshold_kw,
        )["summary"]
        scenario = {
            "scenario_id": f"n-1:{group['id']}",
            "scenario_name": f"{group['name']}停运1台",
            "device_id": group["id"],
            "device_type": group["device_type"],
            "device_type_label": group["device_type_label"],
            "device_name": group["name"],
            "installed_units": unit_count,
            "removed_units": 1,
            "ens_kwh": summary["ens_kwh"],
            "lole_hours": summary["lole_hours"],
            "lolp": summary["lolp"],
            "lolf_events": summary["lolf_events"],
            "lpsp": summary["lpsp"],
            "energy_supply_reliability": summary["energy_supply_reliability"],
            "time_supply_availability": summary["time_supply_availability"],
            "max_deficit_kw": summary["max_deficit_kw"],
            "longest_consecutive_outage_hours": summary["longest_consecutive_outage_hours"],
            "passed": summary["ens_kwh"] <= NUMERIC_EPSILON,
        }
        if group["device_type"] == "battery":
            scenario["removed_capacity_kwh"] = float(group.get("unit_capacity_kwh", 0.0))
        else:
            scenario["removed_capacity_kw"] = float(group.get("unit_capacity_kw", 0.0))
        scenarios.append(scenario)
    scenarios.sort(key=lambda item: (-float(item["ens_kwh"]), -float(item["lole_hours"]), item["scenario_id"]))
    critical = scenarios[0]["scenario_id"] if scenarios else None
    return {
        "base_case": base,
        "scenarios": scenarios,
        "scenario_count": len(scenarios),
        "all_passed": all(bool(item["passed"]) for item in scenarios),
        "critical_scenario_id": critical,
    }


def quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    p = min(1.0, max(0.0, float(probability)))
    position = (len(ordered) - 1) * p
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def mean_confidence_interval(values: Sequence[float], confidence_level: float) -> dict[str, float]:
    if not values:
        return {"lower": 0.0, "upper": 0.0, "half_width": 0.0, "relative_half_width": 0.0}
    sample = [float(value) for value in values]
    mean = statistics.fmean(sample)
    if len(sample) <= 1:
        half_width = 0.0
    else:
        standard_error = statistics.stdev(sample) / math.sqrt(len(sample))
        z_score = statistics.NormalDist().inv_cdf((1.0 + confidence_level) / 2.0)
        half_width = z_score * standard_error
    return {
        "lower": round(max(0.0, mean - half_width), 8),
        "upper": round(mean + half_width, 8),
        "half_width": round(half_width, 8),
        "relative_half_width": round(half_width / mean, 8) if mean > NUMERIC_EPSILON else 0.0,
    }


def annualized_sample(summary: Mapping[str, Any], factor: float, year: int, year_seed: int) -> dict[str, Any]:
    return {
        "year": year,
        "seed": int(year_seed),
        "ens_kwh_per_year": round(float(summary["ens_kwh"]) * factor, 8),
        "lole_hours_per_year": round(float(summary["lole_hours"]) * factor, 8),
        "lolf_events_per_year": round(float(summary["lolf_events"]) * factor, 8),
        "lolp": float(summary["lolp"]),
        "lpsp": float(summary["lpsp"]),
        "energy_supply_reliability": float(summary["energy_supply_reliability"]),
        "time_supply_availability": float(summary["time_supply_availability"]),
        "max_deficit_kw": float(summary["max_deficit_kw"]),
        "longest_consecutive_outage_hours": float(summary["longest_consecutive_outage_hours"]),
    }


def run_sequential_monte_carlo(
    case: Mapping[str, Any],
    *,
    simulation_years: int | None = None,
    hours_per_year: int | None = None,
    seed: int | None = None,
    confidence_level: float | None = None,
    include_annual_samples: bool | None = None,
    include_device_contributions: bool | None = None,
) -> dict[str, Any]:
    """Run independent sequential years and aggregate probability metrics."""

    config = dict(case.get("config") or {})
    years = non_negative_int(
        simulation_years if simulation_years is not None else config.get("simulation_years", 100),
        field_name="蒙特卡洛年数",
    )
    if years <= 0:
        raise ValueError("蒙特卡洛年数必须大于0")
    source_hours = int(case.get("source_hours") or len(case.get("load_kw", [])))
    horizon = non_negative_int(
        hours_per_year
        if hours_per_year is not None
        else (config.get("hours_per_year") if config.get("hours_per_year") is not None else source_hours),
        field_name="每年模拟小时数",
    )
    if horizon <= 0:
        raise ValueError("每年模拟小时数必须大于0")
    master_seed = int(seed if seed is not None else config.get("seed", DEFAULT_CONFIG["seed"]))
    confidence = fraction(
        confidence_level if confidence_level is not None else config.get("confidence_level", 0.95),
        0.95,
        field_name="置信水平",
    )
    if not 0.5 < confidence < 1.0:
        raise ValueError("置信水平必须大于0.5且小于1")
    keep_samples = (
        bool(include_annual_samples)
        if include_annual_samples is not None
        else truthy(config.get("include_annual_samples"), True)
    )
    calculate_contributions = (
        bool(include_device_contributions)
        if include_device_contributions is not None
        else truthy(config.get("include_device_contributions"), True)
    )
    annualization_factor = HOURS_PER_CALENDAR_YEAR / (horizon * numeric(case.get("time_step_hours"), 1.0))
    master = random.Random(master_seed)
    samples: list[dict[str, Any]] = []
    contribution_samples: dict[str, dict[str, list[float]]] = {
        str(group["id"]): {"ens": [], "lole": []} for group in case.get("groups", [])
    }
    observed_stats: dict[str, dict[str, float]] = {
        str(group["id"]): {"available_unit_hours": 0.0, "duration_hours": 0.0}
        for group in case.get("groups", [])
    }

    for year_index in range(years):
        year_seed = master.getrandbits(63)
        availability = sample_fleet_availability(
            case,
            horizon,
            seed=year_seed,
            initial_state=str(config.get("initial_availability") or "stationary"),
        )
        result = dispatch_hourly(case, availability, hours=horizon, include_hourly=False)
        sample = annualized_sample(result["summary"], annualization_factor, year_index + 1, year_seed)
        samples.append(sample)
        for item in result["availability_stats"]:
            device_id = str(item["device_id"])
            observed_stats[device_id]["available_unit_hours"] += float(item["available_unit_hours"])
            observed_stats[device_id]["duration_hours"] += horizon * numeric(case.get("time_step_hours"), 1.0)

        if calculate_contributions and result["summary"]["ens_kwh"] > NUMERIC_EPSILON:
            for group in case.get("groups", []):
                device_id = str(group["id"])
                if int(group.get("unit_count", 0)) <= 0 or float(group.get("forced_outage_rate", 0.0)) <= 0.0:
                    contribution_samples[device_id]["ens"].append(0.0)
                    contribution_samples[device_id]["lole"].append(0.0)
                    continue
                counterfactual = dict(availability)
                counterfactual.pop(device_id, None)
                perfect_result = dispatch_hourly(case, counterfactual, hours=horizon, include_hourly=False)["summary"]
                contribution_samples[device_id]["ens"].append(
                    max(0.0, float(result["summary"]["ens_kwh"]) - float(perfect_result["ens_kwh"]))
                    * annualization_factor
                )
                contribution_samples[device_id]["lole"].append(
                    max(0.0, float(result["summary"]["lole_hours"]) - float(perfect_result["lole_hours"]))
                    * annualization_factor
                )
        elif calculate_contributions:
            for group in case.get("groups", []):
                device_id = str(group["id"])
                contribution_samples[device_id]["ens"].append(0.0)
                contribution_samples[device_id]["lole"].append(0.0)

    ens_values = [float(sample["ens_kwh_per_year"]) for sample in samples]
    lole_values = [float(sample["lole_hours_per_year"]) for sample in samples]
    lolf_values = [float(sample["lolf_events_per_year"]) for sample in samples]
    lolp_values = [float(sample["lolp"]) for sample in samples]
    lpsp_values = [float(sample["lpsp"]) for sample in samples]
    mean_eens = statistics.fmean(ens_values)
    mean_lole = statistics.fmean(lole_values)
    mean_lolf = statistics.fmean(lolf_values)
    mean_lolp = statistics.fmean(lolp_values)
    mean_lpsp = statistics.fmean(lpsp_values)

    summary = {
        "simulated_years": years,
        "ens_total_kwh_over_simulated_years": round(sum(ens_values), 8),
        "eens_kwh_per_year": round(mean_eens, 8),
        "lole_hours_per_year": round(mean_lole, 8),
        "lolp": round(mean_lolp, 12),
        "lolf_events_per_year": round(mean_lolf, 8),
        "lpsp": round(mean_lpsp, 12),
        "energy_supply_reliability": round(max(0.0, min(1.0, 1.0 - mean_lpsp)), 12),
        "time_supply_availability": round(max(0.0, min(1.0, 1.0 - mean_lolp)), 12),
        "p95_ens_kwh_per_year": round(quantile(ens_values, 0.95), 8),
        "p99_ens_kwh_per_year": round(quantile(ens_values, 0.99), 8),
        "p95_lole_hours_per_year": round(quantile(lole_values, 0.95), 8),
        "p99_lole_hours_per_year": round(quantile(lole_values, 0.99), 8),
        "max_deficit_kw": round(max(float(sample["max_deficit_kw"]) for sample in samples), 8),
        "longest_consecutive_outage_hours": round(
            max(float(sample["longest_consecutive_outage_hours"]) for sample in samples), 8
        ),
        "mean_annual_max_deficit_kw": round(
            statistics.fmean(float(sample["max_deficit_kw"]) for sample in samples), 8
        ),
    }
    confidence_intervals = {
        "confidence_level": confidence,
        "eens_kwh_per_year": mean_confidence_interval(ens_values, confidence),
        "lole_hours_per_year": mean_confidence_interval(lole_values, confidence),
        "lolf_events_per_year": mean_confidence_interval(lolf_values, confidence),
    }

    contributions: list[dict[str, Any]] = []
    for group in case.get("groups", []):
        device_id = str(group["id"])
        ens_reduction = (
            statistics.fmean(contribution_samples[device_id]["ens"])
            if contribution_samples[device_id]["ens"]
            else 0.0
        )
        lole_reduction = (
            statistics.fmean(contribution_samples[device_id]["lole"])
            if contribution_samples[device_id]["lole"]
            else 0.0
        )
        observed = observed_stats[device_id]
        installed_units = int(group.get("unit_count", 0))
        duration = observed["duration_hours"]
        mean_available = observed["available_unit_hours"] / duration if duration > 0 else 0.0
        observed_unavailability = (
            1.0 - mean_available / installed_units if installed_units > 0 else 0.0
        )
        contributions.append(
            {
                "device_id": device_id,
                "device_type": group["device_type"],
                "device_type_label": group["device_type_label"],
                "device_name": group["name"],
                "installed_units": installed_units,
                "input_forced_outage_rate": float(group["forced_outage_rate"]),
                "input_mttr_hours": float(group["mttr_hours"]),
                "observed_unavailability": round(max(0.0, min(1.0, observed_unavailability)), 10),
                "mean_unavailable_units": round(max(0.0, installed_units - mean_available), 8),
                "marginal_eens_reduction_kwh_per_year": round(ens_reduction, 8),
                "marginal_lole_reduction_hours_per_year": round(lole_reduction, 8),
                "marginal_reduction_share_of_eens": round(
                    ens_reduction / mean_eens if mean_eens > NUMERIC_EPSILON else 0.0, 10
                ),
            }
        )
    positive_total = sum(max(0.0, float(item["marginal_eens_reduction_kwh_per_year"])) for item in contributions)
    for item in contributions:
        item["normalized_contribution_share"] = round(
            max(0.0, float(item["marginal_eens_reduction_kwh_per_year"])) / positive_total
            if positive_total > NUMERIC_EPSILON
            else 0.0,
            10,
        )
    contributions.sort(
        key=lambda item: (-float(item["marginal_eens_reduction_kwh_per_year"]), item["device_id"])
    )

    warnings: list[str] = []
    if years < 30:
        warnings.append("蒙特卡洛样本少于30年，P95/P99和均值置信区间仅适合功能验证，不宜直接用于设计定案")
    if horizon != int(HOURS_PER_CALENDAR_YEAR):
        warnings.append(
            f"每个样本仅模拟{horizon}小时，EENS/LOLE/LOLF已按8760/{horizon}线性年化"
        )
    if horizon > source_hours:
        warnings.append(f"每年模拟小时数超过源时序{source_hours}小时，负荷和资源曲线按周期重复")

    result: dict[str, Any] = {
        "method": {
            "availability_model": "two_state_continuous_time_markov_chain_sampled_hourly",
            "dispatch_model": "hourly_priority_dispatch",
            "dispatch_policy": str(config.get("dispatch_policy") or "renewable_storage_diesel"),
            "random_seed": master_seed,
            "simulation_years": years,
            "hours_per_year": horizon,
            "annualization_factor": round(annualization_factor, 12),
            "initial_availability": str(config.get("initial_availability") or "stationary"),
        },
        "summary": summary,
        "confidence_intervals": confidence_intervals,
        "device_contributions": contributions,
        "warnings": warnings,
    }
    if keep_samples:
        result["annual_samples"] = samples
    return result


def input_summary(case: Mapping[str, Any]) -> dict[str, Any]:
    devices = []
    for group in case.get("groups", []):
        row = {
            "device_id": group["id"],
            "device_type": group["device_type"],
            "device_type_label": group["device_type_label"],
            "device_name": group["name"],
            "installed_units": int(group["unit_count"]),
            "forced_outage_rate": float(group["forced_outage_rate"]),
            "mttr_hours": float(group["mttr_hours"]),
        }
        if group["device_type"] == "battery":
            row["unit_capacity_kwh"] = float(group.get("unit_capacity_kwh", 0.0))
            row["total_capacity_kwh"] = row["unit_capacity_kwh"] * row["installed_units"]
            row["soc_lower"] = float(group.get("soc_lower", 0.0))
            row["soc_upper"] = float(group.get("soc_upper", 1.0))
        else:
            row["unit_capacity_kw"] = float(group.get("unit_capacity_kw", 0.0))
            row["total_capacity_kw"] = row["unit_capacity_kw"] * row["installed_units"]
        devices.append(row)
    load = [float(value) for value in case.get("load_kw", [])]
    return {
        "scheme": str(case.get("scheme") or ""),
        "source_hours": int(case.get("source_hours", len(load))),
        "load_energy_kwh": round(sum(load) * numeric(case.get("time_step_hours"), 1.0), 8),
        "peak_load_kw": round(max(load) if load else 0.0, 8),
        "devices": devices,
    }


def run_reliability_assessment(
    scheme_payload: Mapping[str, Any],
    planning_result_rows: list[dict[str, Any]] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One-call reliability assessment for later use by the HTTP server."""

    case = build_reliability_case(scheme_payload, planning_result_rows, config)
    monte_carlo = run_sequential_monte_carlo(case)
    n_minus_one = (
        run_n_minus_one(case)
        if truthy(case["config"].get("run_n_minus_one"), True)
        else {
            "base_case": dispatch_hourly(case)["summary"],
            "scenarios": [],
            "scenario_count": 0,
            "all_passed": True,
            "critical_scenario_id": None,
        }
    )
    warnings = unique_strings(
        [
            *case.get("warnings", []),
            *monte_carlo.get("warnings", []),
            "概率可靠性结果是规划完成后的独立校核，不改变规划模型严格零切负荷约束",
        ]
    )
    result = {
        "status": "completed",
        "schema_version": SCHEMA_VERSION,
        "input": input_summary(case),
        "method": monte_carlo["method"],
        "summary": monte_carlo["summary"],
        "confidence_intervals": monte_carlo["confidence_intervals"],
        "n_minus_one": n_minus_one,
        "device_contributions": monte_carlo["device_contributions"],
        "warnings": warnings,
    }
    if "annual_samples" in monte_carlo:
        result["annual_samples"] = monte_carlo["annual_samples"]
    return result


def unique_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


__all__ = [
    "build_reliability_case",
    "dispatch_hourly",
    "mean_confidence_interval",
    "quantile",
    "run_n_minus_one",
    "run_reliability_assessment",
    "run_sequential_monte_carlo",
    "sample_fleet_availability",
    "sample_two_state_availability",
    "sample_two_state_unit_availability",
    "two_state_transition_probabilities",
]
