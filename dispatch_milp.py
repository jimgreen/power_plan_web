"""Shared MILP construction helpers for planning optimization and dispatch evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy import sparse

from milp_solver import solve_milp


LogSink = Callable[[dict[str, Any]], None]
SolverFn = Callable[
    [
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        Any,
        np.ndarray,
        np.ndarray,
        dict[str, Any],
        LogSink | None,
        str,
    ],
    Any,
]


@dataclass
class MilpModelBuilder:
    """Incrementally builds a linear objective, bounds and sparse constraints."""

    variables: dict[tuple[Any, ...], int] = field(default_factory=dict)
    lower_bounds: list[float] = field(default_factory=list)
    upper_bounds: list[float] = field(default_factory=list)
    integrality: list[int] = field(default_factory=list)
    objective: list[float] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)
    cols: list[int] = field(default_factory=list)
    data: list[float] = field(default_factory=list)
    constraint_lower: list[float] = field(default_factory=list)
    constraint_upper: list[float] = field(default_factory=list)

    def add_var(
        self,
        key: tuple[Any, ...],
        lower: float = 0.0,
        upper: float = np.inf,
        integer: bool = False,
        cost: float = 0.0,
    ) -> int:
        if key in self.variables:
            raise KeyError(f"duplicate MILP variable key: {key}")
        index = len(self.objective)
        self.variables[key] = index
        self.lower_bounds.append(float(lower))
        self.upper_bounds.append(float(upper))
        self.integrality.append(1 if integer else 0)
        self.objective.append(float(cost))
        return index

    def var(self, key: tuple[Any, ...]) -> int:
        return self.variables[key]

    def add_constraint(self, terms: dict[int, float], lower: float, upper: float) -> None:
        row_index = len(self.constraint_lower)
        for column, value in terms.items():
            if value:
                self.rows.append(row_index)
                self.cols.append(column)
                self.data.append(float(value))
        self.constraint_lower.append(float(lower))
        self.constraint_upper.append(float(upper))

    def add_keyed_constraint(self, terms: dict[tuple[Any, ...], float], lower: float, upper: float) -> None:
        self.add_constraint({self.var(key): value for key, value in terms.items()}, lower, upper)

    @property
    def variable_count(self) -> int:
        return len(self.objective)

    @property
    def integer_variable_count(self) -> int:
        return sum(self.integrality)

    @property
    def constraint_count(self) -> int:
        return len(self.constraint_lower)

    @property
    def nonzero_count(self) -> int:
        return len(self.data)

    def constraint_matrix(self) -> Any:
        return sparse.coo_matrix(
            (self.data, (self.rows, self.cols)),
            shape=(self.constraint_count, self.variable_count),
        ).tocsr()

    def objective_array(self) -> np.ndarray:
        return np.array(self.objective, dtype=float)

    def integrality_array(self) -> np.ndarray:
        return np.array(self.integrality, dtype=int)

    def lower_bounds_array(self) -> np.ndarray:
        return np.array(self.lower_bounds, dtype=float)

    def upper_bounds_array(self) -> np.ndarray:
        return np.array(self.upper_bounds, dtype=float)

    def constraint_lower_array(self) -> np.ndarray:
        return np.array(self.constraint_lower, dtype=float)

    def constraint_upper_array(self) -> np.ndarray:
        return np.array(self.constraint_upper, dtype=float)


def solve_built_milp(
    builder: MilpModelBuilder,
    options: dict[str, Any],
    log: LogSink | None,
    problem_name: str,
    solve_fn: SolverFn = solve_milp,
) -> Any:
    """Solve a model assembled by MilpModelBuilder."""

    return solve_fn(
        builder.objective_array(),
        builder.integrality_array(),
        builder.lower_bounds_array(),
        builder.upper_bounds_array(),
        builder.constraint_matrix(),
        builder.constraint_lower_array(),
        builder.constraint_upper_array(),
        options,
        log,
        problem_name,
    )


def emit_builder_diagnostics(builder: MilpModelBuilder, log: LogSink | None, label: str = "MILP") -> None:
    if not log:
        return
    objective = builder.objective_array()
    lower_bounds = builder.lower_bounds_array()
    upper_bounds = builder.upper_bounds_array()
    constraint_lower = builder.constraint_lower_array()
    constraint_upper = builder.constraint_upper_array()
    integrality = builder.integrality_array()
    finite_variable_upper = np.isfinite(upper_bounds)
    finite_constraint_lower = np.isfinite(constraint_lower)
    finite_constraint_upper = np.isfinite(constraint_upper)
    equality_constraints = finite_constraint_lower & finite_constraint_upper & np.isclose(constraint_lower, constraint_upper)
    binary_variables = sum(
        1
        for index in range(len(objective))
        if integrality[index] and abs(lower_bounds[index]) < 1e-9 and abs(upper_bounds[index] - 1.0) < 1e-9
    )
    emit(
        log,
        "info",
        (
            f"{label}变量详情：连续变量={len(objective) - int(np.count_nonzero(integrality))}个，"
            f"整数变量={int(np.count_nonzero(integrality))}个，其中二进制变量={binary_variables}个，"
            f"有限上界变量={int(np.count_nonzero(finite_variable_upper))}个，"
            f"目标函数非零项={int(np.count_nonzero(np.abs(objective) > 1e-12))}个"
        ),
        None,
    )
    emit(
        log,
        "info",
        (
            f"{label}约束详情：等式约束={int(np.count_nonzero(equality_constraints))}条，"
            f"仅上界约束={int(np.count_nonzero(finite_constraint_upper & ~equality_constraints))}条，"
            f"仅下界约束={int(np.count_nonzero(finite_constraint_lower & ~equality_constraints))}条，"
            f"稀疏矩阵密度={matrix_density(builder):.6g}"
        ),
        None,
    )


def matrix_density(builder: MilpModelBuilder) -> float:
    total_slots = builder.variable_count * builder.constraint_count
    return 0.0 if total_slots <= 0 else builder.nonzero_count / total_slots


def emit(log: LogSink | None, level: str, message: str, progress: int | None = None) -> None:
    if not log:
        return
    event = {"level": level, "message": message}
    if progress is not None:
        event["progress"] = progress
    log(event)


def add_power_balance_constraint(
    builder: MilpModelBuilder,
    *,
    generation_indices: list[int],
    load: float,
    charge_indices: list[int] | None = None,
    consumption_indices: list[int] | None = None,
    unmet_index: int | None = None,
) -> None:
    # One equality row per hour keeps load, generation, storage and shedding
    # in a single accounting frame.
    terms: dict[int, float] = {}
    for index in generation_indices:
        terms[index] = terms.get(index, 0.0) + 1.0
    for index in charge_indices or []:
        terms[index] = terms.get(index, 0.0) - 1.0
    for index in consumption_indices or []:
        terms[index] = terms.get(index, 0.0) - 1.0
    if unmet_index is not None:
        terms[unmet_index] = terms.get(unmet_index, 0.0) + 1.0
    builder.add_constraint(terms, load, load)


def add_availability_constraint(
    builder: MilpModelBuilder,
    *,
    production_indices: list[int],
    curtailed_index: int,
    fixed_available: float = 0.0,
    available_terms: dict[int, float] | None = None,
) -> None:
    # Weather-derived availability is split between actual output and
    # curtailment, so the two variables always sum to the same resource total.
    terms: dict[int, float] = {curtailed_index: 1.0}
    for index in production_indices:
        terms[index] = terms.get(index, 0.0) + 1.0
    for column, coefficient in (available_terms or {}).items():
        terms[column] = terms.get(column, 0.0) - coefficient
    builder.add_constraint(terms, fixed_available, fixed_available)


def add_capacity_upper_constraint(
    builder: MilpModelBuilder,
    value_index: int,
    *,
    capacity_terms: dict[int, float] | None = None,
    fixed_capacity: float | None = None,
) -> None:
    # This helper is reused by multiple device families whenever an output
    # needs to be capped by a scalar or affine capacity expression.
    terms: dict[int, float] = {value_index: 1.0}
    for column, coefficient in (capacity_terms or {}).items():
        terms[column] = terms.get(column, 0.0) - coefficient
    upper = float(fixed_capacity) if fixed_capacity is not None else 0.0
    builder.add_constraint(terms, -np.inf, upper)


def add_unit_commitment_constraints(
    builder: MilpModelBuilder,
    *,
    power_index: int,
    on_indices: list[int],
    power_upper: float,
    power_lower: float,
    quantity_index: int | None = None,
) -> None:
    # Diesel and electrolyzer rows share the same commitment shape, so one
    # generic helper keeps the device-specific code short.
    if quantity_index is not None:
        builder.add_constraint({**{index: 1.0 for index in on_indices}, quantity_index: -1.0}, -np.inf, 0.0)
    builder.add_constraint(
        {power_index: 1.0, **{index: -float(power_upper) for index in on_indices}},
        -np.inf,
        0.0,
    )
    builder.add_constraint(
        {power_index: 1.0, **{index: -float(power_lower) for index in on_indices}},
        0.0,
        np.inf,
    )


def add_storage_constraints(
    builder: MilpModelBuilder,
    *,
    charge_index: int,
    discharge_index: int,
    charge_on_index: int,
    discharge_on_index: int,
    soc_index: int,
    previous_soc_index: int | None,
    power_capacity_upper: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    power_capacity_terms: dict[int, float] | None = None,
    fixed_power_capacity: float | None = None,
    energy_capacity_terms: dict[int, float] | None = None,
    fixed_energy_capacity: float | None = None,
    initial_ratio: float = 0.5,
    fixed_initial_value: float | None = None,
    soc_lower_ratio: float = 0.0,
    soc_upper_ratio: float = 1.0,
    self_discharge_rate_per_hour: float = 0.0,
) -> dict[str, int]:
    # Storage is the most coupled device family in the model: charge/discharge
    # binaries, SOC dynamics and SOC threshold flags all come from this block.
    if power_capacity_terms is not None or fixed_power_capacity is not None:
        add_capacity_upper_constraint(
            builder,
            charge_index,
            capacity_terms=power_capacity_terms,
            fixed_capacity=fixed_power_capacity,
        )
        add_capacity_upper_constraint(
            builder,
            discharge_index,
            capacity_terms=power_capacity_terms,
            fixed_capacity=fixed_power_capacity,
        )
    builder.add_constraint({charge_index: 1.0, charge_on_index: -float(power_capacity_upper)}, -np.inf, 0.0)
    builder.add_constraint({discharge_index: 1.0, discharge_on_index: -float(power_capacity_upper)}, -np.inf, 0.0)
    builder.add_constraint({charge_on_index: 1.0, discharge_on_index: 1.0}, -np.inf, 1.0)
    lower_margin_index = builder.add_var(("storage_soc_lower_margin", soc_index), 0.0, 1.0, integer=True)
    upper_margin_index = builder.add_var(("storage_soc_upper_margin", soc_index), 0.0, 1.0, integer=True)
    storage_energy_upper = storage_energy_capacity_upper(builder, energy_capacity_terms, fixed_energy_capacity)
    soc_lower_ratio = min(1.0, max(0.0, float(soc_lower_ratio)))
    soc_upper_ratio = min(1.0, max(soc_lower_ratio, float(soc_upper_ratio)))
    lower_threshold_terms = scaled_terms(energy_capacity_terms, soc_lower_ratio)
    upper_threshold_terms = scaled_terms(energy_capacity_terms, soc_upper_ratio)
    add_soc_threshold_indicator_constraints(
        builder,
        soc_index=soc_index,
        indicator_index=lower_margin_index,
        threshold_terms=lower_threshold_terms,
        fixed_threshold=soc_lower_ratio * float(fixed_energy_capacity or 0.0),
        big_m=storage_energy_upper,
        relation="above",
    )
    add_soc_threshold_indicator_constraints(
        builder,
        soc_index=soc_index,
        indicator_index=upper_margin_index,
        threshold_terms=upper_threshold_terms,
        fixed_threshold=soc_upper_ratio * float(fixed_energy_capacity or 0.0),
        big_m=storage_energy_upper,
        relation="below",
    )
    builder.add_constraint({discharge_on_index: 1.0, lower_margin_index: -1.0}, -np.inf, 0.0)
    builder.add_constraint({charge_on_index: 1.0, upper_margin_index: -1.0}, -np.inf, 0.0)
    if energy_capacity_terms is not None or fixed_energy_capacity is not None:
        add_capacity_upper_constraint(
            builder,
            soc_index,
            capacity_terms=energy_capacity_terms,
            fixed_capacity=fixed_energy_capacity,
        )

    terms: dict[int, float] = {
        soc_index: 1.0,
        charge_index: -float(charge_efficiency),
        discharge_index: 1.0 / max(0.0001, float(discharge_efficiency)),
    }
    retention_factor = min(1.0, max(0.0, 1.0 - float(self_discharge_rate_per_hour)))
    if previous_soc_index is None:
        if energy_capacity_terms:
            for column, coefficient in energy_capacity_terms.items():
                terms[column] = terms.get(column, 0.0) - retention_factor * float(initial_ratio) * coefficient
            builder.add_constraint(terms, 0.0, 0.0)
        else:
            initial_value = fixed_initial_value
            if initial_value is None:
                initial_value = float(initial_ratio) * float(fixed_energy_capacity or 0.0)
            builder.add_constraint(terms, retention_factor * float(initial_value), retention_factor * float(initial_value))
    else:
        terms[previous_soc_index] = terms.get(previous_soc_index, 0.0) - retention_factor
        builder.add_constraint(terms, 0.0, 0.0)
    return {"soc_above_lower": lower_margin_index, "soc_below_upper": upper_margin_index}


def scaled_terms(terms: dict[int, float] | None, multiplier: float) -> dict[int, float]:
    # Copy and scale coefficient dictionaries without mutating the caller.
    return {column: coefficient * float(multiplier) for column, coefficient in (terms or {}).items()}


def storage_energy_capacity_upper(
    builder: MilpModelBuilder,
    energy_capacity_terms: dict[int, float] | None,
    fixed_energy_capacity: float | None = None,
) -> float:
    # Big-M values should reflect the maximum feasible storage energy so the
    # threshold binaries remain permissive enough to stay feasible.
    if fixed_energy_capacity is not None:
        return max(0.0, float(fixed_energy_capacity))
    if not energy_capacity_terms:
        return 0.0
    total = 0.0
    for column, coefficient in energy_capacity_terms.items():
        upper = builder.upper_bounds[column] if column < len(builder.upper_bounds) else 1.0
        if np.isfinite(upper):
            total += max(0.0, float(coefficient)) * max(0.0, float(upper))
    return max(0.0, total)


def add_soc_threshold_indicator_constraints(
    builder: MilpModelBuilder,
    *,
    soc_index: int,
    indicator_index: int,
    threshold_terms: dict[int, float] | None = None,
    fixed_threshold: float = 0.0,
    big_m: float = 0.0,
    relation: str,
) -> None:
    # These indicator rows approximate "SOC above the lower bound" and "SOC
    # below the upper bound" with a finite Big-M.
    epsilon = 1e-6
    safe_m = max(float(big_m), abs(float(fixed_threshold)), 1.0) + epsilon
    base_terms: dict[int, float] = {soc_index: 1.0}
    for column, coefficient in (threshold_terms or {}).items():
        base_terms[column] = base_terms.get(column, 0.0) - float(coefficient)
    if relation == "above":
        builder.add_constraint({**base_terms, indicator_index: -safe_m}, float(fixed_threshold) + epsilon - safe_m, np.inf)
    elif relation == "below":
        builder.add_constraint({**base_terms, indicator_index: safe_m}, -np.inf, float(fixed_threshold) + safe_m - epsilon)
    else:
        raise ValueError(f"unknown SOC threshold relation: {relation}")


def add_grid_support_requirement(
    builder: MilpModelBuilder,
    *,
    diesel_on_indices: list[int],
    grid_storage_on_indices: list[int],
) -> bool:
    # Keep at least one controllable source online across the diesel and
    # grid-forming storage fleets.
    terms = {index: 1.0 for index in [*diesel_on_indices, *grid_storage_on_indices]}
    if terms:
        builder.add_constraint(terms, 1.0, np.inf)
        return True
    return False


def add_grid_storage_on_constraints(
    builder: MilpModelBuilder,
    *,
    on_indices: list[int],
    quantity_index: int | None = None,
) -> None:
    # A grid-forming storage unit can only count as online if its parent row is
    # actually built.
    if quantity_index is not None and on_indices:
        builder.add_constraint({**{index: 1.0 for index in on_indices}, quantity_index: -1.0}, -np.inf, 0.0)


def add_post_disturbance_balance_constraints(
    builder: MilpModelBuilder,
    *,
    load: float,
    load_up_factor: float,
    load_down_factor: float,
    renewable_down_factor: float,
    diesel_power_indices: list[int],
    diesel_on_terms: dict[int, float],
    grid_storage_charge_index: int,
    grid_storage_discharge_index: int,
    grid_storage_up_on_terms: dict[int, float],
    grid_storage_down_on_terms: dict[int, float],
    wind_power_indices: list[int],
    pv_power_indices: list[int],
) -> None:
    # This block turns the disturbance-security rules into linear reserve
    # inequalities for each hour.
    renewable_power_indices = [*wind_power_indices, *pv_power_indices]
    up_terms: dict[int, float] = {}
    down_terms: dict[int, float] = {}
    for index, upper in diesel_on_terms.items():
        up_terms[index] = up_terms.get(index, 0.0) + float(upper)
    for index in diesel_power_indices:
        up_terms[index] = up_terms.get(index, 0.0) - 1.0
        down_terms[index] = down_terms.get(index, 0.0) + 1.0
    for index, capacity in grid_storage_up_on_terms.items():
        up_terms[index] = up_terms.get(index, 0.0) + float(capacity)
    for index, capacity in grid_storage_down_on_terms.items():
        down_terms[index] = down_terms.get(index, 0.0) + float(capacity)
    up_terms[grid_storage_discharge_index] = up_terms.get(grid_storage_discharge_index, 0.0) - 1.0
    up_terms[grid_storage_charge_index] = up_terms.get(grid_storage_charge_index, 0.0) + 1.0
    down_terms[grid_storage_discharge_index] = down_terms.get(grid_storage_discharge_index, 0.0) + 1.0
    down_terms[grid_storage_charge_index] = down_terms.get(grid_storage_charge_index, 0.0) - 1.0

    load_up_requirement = max(0.0, float(load) * float(load_up_factor))
    if load_up_requirement > 0 or (renewable_down_factor > 0 and renewable_power_indices):
        terms = dict(up_terms)
        for index in renewable_power_indices:
            terms[index] = terms.get(index, 0.0) - float(renewable_down_factor)
        builder.add_constraint(terms, load_up_requirement, np.inf)
    if load_down_factor > 0:
        builder.add_constraint(down_terms, max(0.0, float(load) * float(load_down_factor)), np.inf)


def add_storage_cycle_constraint(
    builder: MilpModelBuilder,
    *,
    soc_index: int,
    energy_capacity_terms: dict[int, float] | None = None,
    initial_ratio: float = 0.5,
    fixed_initial_value: float | None = None,
) -> None:
    terms: dict[int, float] = {soc_index: 1.0}
    if energy_capacity_terms:
        for column, coefficient in energy_capacity_terms.items():
            terms[column] = terms.get(column, 0.0) - float(initial_ratio) * coefficient
        builder.add_constraint(terms, 0.0, 0.0)
    else:
        value = float(fixed_initial_value or 0.0)
        builder.add_constraint(terms, value, value)


def add_hydrogen_constraints(
    builder: MilpModelBuilder,
    *,
    storage_index: int,
    previous_storage_index: int | None,
    production_terms: dict[int, float],
    consumption_terms: dict[int, float],
    capacity_terms: dict[int, float] | None = None,
    fixed_capacity: float | None = None,
    initial_ratio: float = 0.5,
    fixed_initial_value: float | None = None,
    self_discharge_rate_per_hour: float = 0.0,
) -> None:
    if capacity_terms is not None or fixed_capacity is not None:
        add_capacity_upper_constraint(
            builder,
            storage_index,
            capacity_terms=capacity_terms,
            fixed_capacity=fixed_capacity,
        )

    terms: dict[int, float] = {storage_index: 1.0}
    for column, coefficient in production_terms.items():
        terms[column] = terms.get(column, 0.0) - coefficient
    for column, coefficient in consumption_terms.items():
        terms[column] = terms.get(column, 0.0) + coefficient
    retention_factor = min(1.0, max(0.0, 1.0 - float(self_discharge_rate_per_hour)))
    if previous_storage_index is None:
        if capacity_terms:
            for column, coefficient in capacity_terms.items():
                terms[column] = terms.get(column, 0.0) - retention_factor * float(initial_ratio) * coefficient
            builder.add_constraint(terms, 0.0, 0.0)
        else:
            initial_value = fixed_initial_value
            if initial_value is None:
                initial_value = float(initial_ratio) * float(fixed_capacity or 0.0)
            builder.add_constraint(terms, retention_factor * float(initial_value), retention_factor * float(initial_value))
    else:
        terms[previous_storage_index] = terms.get(previous_storage_index, 0.0) - retention_factor
        builder.add_constraint(terms, 0.0, 0.0)


def add_hydrogen_cycle_constraint(
    builder: MilpModelBuilder,
    *,
    storage_index: int,
    capacity_terms: dict[int, float] | None = None,
    initial_ratio: float = 0.5,
    fixed_initial_value: float | None = None,
) -> None:
    terms: dict[int, float] = {storage_index: 1.0}
    if capacity_terms:
        for column, coefficient in capacity_terms.items():
            terms[column] = terms.get(column, 0.0) - float(initial_ratio) * coefficient
        builder.add_constraint(terms, 0.0, 0.0)
    else:
        value = float(fixed_initial_value or 0.0)
        builder.add_constraint(terms, value, value)


def add_green_ratio_constraint(
    builder: MilpModelBuilder,
    *,
    green_power_indices: list[int],
    diesel_power_indices: list[int],
    ratio_lower: float,
) -> None:
    if ratio_lower <= 0:
        return
    coefficient = 1.0 - float(ratio_lower)
    terms: dict[int, float] = {}
    for index in green_power_indices:
        terms[index] = terms.get(index, 0.0) + coefficient
    for index in diesel_power_indices:
        terms[index] = terms.get(index, 0.0) - float(ratio_lower)
    builder.add_constraint(terms, 0.0, np.inf)
