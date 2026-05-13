"""MILP solver adapter with Gurobi primary and SciPy fallback."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


LogSink = Callable[[dict[str, Any]], None]


def solve_milp(
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    constraint_matrix: Any,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
    options: dict[str, Any] | None = None,
    log: LogSink | None = None,
    problem_name: str = "MILP",
) -> SimpleNamespace:
    """Solve a MILP using Gurobi first, falling back to SciPy if unavailable."""

    options = options or {}
    try:
        return solve_milp_with_gurobi(
            objective,
            integrality,
            lower_bounds,
            upper_bounds,
            constraint_matrix,
            constraint_lower,
            constraint_upper,
            options,
            log,
            problem_name,
        )
    except Exception as exc:
        emit(log, "warn", f"Gurobi求解器不可用，改用SciPy求解器：{exc}", None)
        return solve_milp_with_scipy(
            objective,
            integrality,
            lower_bounds,
            upper_bounds,
            constraint_matrix,
            constraint_lower,
            constraint_upper,
            options,
        )


def solve_milp_with_gurobi(
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    constraint_matrix: Any,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
    options: dict[str, Any],
    log: LogSink | None,
    problem_name: str,
) -> SimpleNamespace:
    import gurobipy as gp

    emit(log, "info", "调用Gurobi求解器求解混合整数线性规划", None)
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    lower_bounds = finite_gurobi_bounds(np.asarray(lower_bounds, dtype=float), gp.GRB.INFINITY)
    upper_bounds = finite_gurobi_bounds(np.asarray(upper_bounds, dtype=float), gp.GRB.INFINITY)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    matrix = constraint_matrix.tocsr()

    model = gp.Model(problem_name or "MILP")
    model.Params.OutputFlag = 0
    time_limit = options.get("time_limit")
    if time_limit is not None:
        model.Params.TimeLimit = float(time_limit)
    mip_gap = options.get("mip_rel_gap")
    if mip_gap is not None:
        model.Params.MIPGap = float(mip_gap)

    vtypes = np.array(
        [
            gp.GRB.BINARY if is_binary_integer(integrality[index], lower_bounds[index], upper_bounds[index]) else gp.GRB.INTEGER if integrality[index] else gp.GRB.CONTINUOUS
            for index in range(len(objective))
        ],
        dtype="U1",
    )
    variables = model.addMVar(len(objective), lb=lower_bounds, ub=upper_bounds, vtype=vtypes, name="x")
    model.setObjective(objective @ variables, gp.GRB.MINIMIZE)
    add_gurobi_constraints(model, matrix, variables, constraint_lower, constraint_upper)
    model.optimize()

    status_name = gurobi_status_name(gp, model.Status)
    has_solution = int(model.SolCount) > 0
    solution = np.array(variables.X, dtype=float) if has_solution else None
    objective_value = float(model.ObjVal) if has_solution else None
    success = model.Status == gp.GRB.OPTIMAL
    return SimpleNamespace(
        success=success,
        x=solution,
        fun=objective_value,
        message=f"Gurobi status {status_name}",
        solver="gurobi",
        status=model.Status,
    )


def solve_milp_with_scipy(
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    constraint_matrix: Any,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
    options: dict[str, Any],
) -> Any:
    return milp(
        np.asarray(objective, dtype=float),
        integrality=np.asarray(integrality, dtype=int),
        bounds=Bounds(np.asarray(lower_bounds, dtype=float), np.asarray(upper_bounds, dtype=float)),
        constraints=LinearConstraint(
            constraint_matrix,
            np.asarray(constraint_lower, dtype=float),
            np.asarray(constraint_upper, dtype=float),
        ),
        options=options,
    )


def add_gurobi_constraints(model: Any, matrix: Any, variables: Any, lower: np.ndarray, upper: np.ndarray) -> None:
    finite_lower = np.isfinite(lower)
    finite_upper = np.isfinite(upper)
    equality = finite_lower & finite_upper & np.isclose(lower, upper)
    add_gurobi_constraint_block(model, matrix, variables, equality, "=", lower)
    add_gurobi_constraint_block(model, matrix, variables, finite_upper & ~equality, "<", upper)
    add_gurobi_constraint_block(model, matrix, variables, finite_lower & ~equality, ">", lower)


def add_gurobi_constraint_block(model: Any, matrix: Any, variables: Any, mask: np.ndarray, sense: str, rhs: np.ndarray) -> None:
    if not np.any(mask):
        return
    count = int(np.count_nonzero(mask))
    model.addMConstr(matrix[mask], variables, np.full(count, sense), rhs[mask])


def finite_gurobi_bounds(values: np.ndarray, infinity: float) -> np.ndarray:
    return np.where(np.isposinf(values), infinity, np.where(np.isneginf(values), -infinity, values))


def is_binary_integer(integrality: int, lower: float, upper: float) -> bool:
    return bool(integrality) and abs(lower) < 1e-9 and abs(upper - 1.0) < 1e-9


def gurobi_status_name(gp: Any, status: int) -> str:
    for name in (
        "OPTIMAL",
        "INFEASIBLE",
        "INF_OR_UNBD",
        "UNBOUNDED",
        "CUTOFF",
        "ITERATION_LIMIT",
        "NODE_LIMIT",
        "TIME_LIMIT",
        "SOLUTION_LIMIT",
        "INTERRUPTED",
        "NUMERIC",
        "SUBOPTIMAL",
        "USER_OBJ_LIMIT",
    ):
        if getattr(gp.GRB, name, None) == status:
            return name
    return str(status)


def emit(log: LogSink | None, level: str, message: str, progress: int | None = None) -> None:
    if not log:
        return
    event = {"level": level, "message": message}
    if progress is not None:
        event["progress"] = progress
    log(event)
