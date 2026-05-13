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


def add_power_balance_constraint(
    builder: MilpModelBuilder,
    *,
    generation_indices: list[int],
    load: float,
    charge_indices: list[int] | None = None,
    consumption_indices: list[int] | None = None,
    unmet_index: int | None = None,
) -> None:
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
) -> None:
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
    if previous_soc_index is None:
        if energy_capacity_terms:
            for column, coefficient in energy_capacity_terms.items():
                terms[column] = terms.get(column, 0.0) - float(initial_ratio) * coefficient
            builder.add_constraint(terms, 0.0, 0.0)
        else:
            initial_value = fixed_initial_value
            if initial_value is None:
                initial_value = float(initial_ratio) * float(fixed_energy_capacity or 0.0)
            builder.add_constraint(terms, float(initial_value), float(initial_value))
    else:
        terms[previous_soc_index] = terms.get(previous_soc_index, 0.0) - 1.0
        builder.add_constraint(terms, 0.0, 0.0)


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
    if previous_storage_index is None:
        if capacity_terms:
            for column, coefficient in capacity_terms.items():
                terms[column] = terms.get(column, 0.0) - float(initial_ratio) * coefficient
            builder.add_constraint(terms, 0.0, 0.0)
        else:
            initial_value = fixed_initial_value
            if initial_value is None:
                initial_value = float(initial_ratio) * float(fixed_capacity or 0.0)
            builder.add_constraint(terms, float(initial_value), float(initial_value))
    else:
        terms[previous_storage_index] = terms.get(previous_storage_index, 0.0) - 1.0
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
