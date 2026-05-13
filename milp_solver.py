"""MILP solver adapter with Gurobi, CPLEX, MOSEK, and SciPy backends."""

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
    """Solve a MILP using the selected solver, or auto fallback order."""

    options = dict(options or {})
    solver = str(options.pop("solver", "auto") or "auto").strip().lower()

    if solver in ("auto", ""):
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
            emit(log, "warn", f"Gurobi求解器不可用，改用CPLEX求解器：{exc}", None)
        try:
            return solve_milp_with_cplex(
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
            emit(log, "warn", f"CPLEX求解器不可用，改用MOSEK求解器：{exc}", None)
        try:
            return solve_milp_with_mosek(
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
            emit(log, "warn", f"MOSEK求解器不可用，改用SciPy求解器：{exc}", None)
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

    if solver in ("gurobi", "grb"):
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

    if solver in ("cplex", "cplx"):
        return solve_milp_with_cplex(
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

    if solver in ("mosek", "msk"):
        return solve_milp_with_mosek(
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

    if solver in ("scipy", "highs"):
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

    raise ValueError(f"未知MILP求解器：{solver}")


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


def solve_milp_with_cplex(
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
    import cplex

    emit(log, "info", "调用CPLEX求解器求解混合整数线性规划", None)
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    lower_bounds = finite_cplex_bounds(np.asarray(lower_bounds, dtype=float), cplex.infinity)
    upper_bounds = finite_cplex_bounds(np.asarray(upper_bounds, dtype=float), cplex.infinity)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    matrix = constraint_matrix.tocsr()

    model = cplex.Cplex()
    model.set_problem_name(problem_name or "MILP")
    model.objective.set_sense(model.objective.sense.minimize)
    model.set_log_stream(None)
    model.set_error_stream(None)
    model.set_warning_stream(None)
    model.set_results_stream(None)

    time_limit = options.get("time_limit")
    if time_limit is not None:
        model.parameters.timelimit.set(float(time_limit))
    mip_gap = options.get("mip_rel_gap")
    if mip_gap is not None:
        model.parameters.mip.tolerances.mipgap.set(float(mip_gap))

    variable_types = "".join(
        cplex_variable_type(model, integrality[index], lower_bounds[index], upper_bounds[index])
        for index in range(len(objective))
    )
    model.variables.add(
        obj=objective.tolist(),
        lb=lower_bounds.tolist(),
        ub=upper_bounds.tolist(),
        types=variable_types,
        names=[f"x{index}" for index in range(len(objective))],
    )
    add_cplex_constraints(cplex, model, matrix, constraint_lower, constraint_upper)
    model.solve()

    status = model.solution.get_status()
    status_string = model.solution.get_status_string()
    solution = None
    objective_value = None
    try:
        solution = np.array(model.solution.get_values(), dtype=float)
        objective_value = float(model.solution.get_objective_value())
    except Exception:
        pass

    return SimpleNamespace(
        success=is_cplex_optimal_status(model, status),
        x=solution,
        fun=objective_value,
        message=f"CPLEX status {status_string}",
        solver="cplex",
        status=status,
    )


def solve_milp_with_mosek(
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
    import mosek

    emit(log, "info", "调用MOSEK求解器求解混合整数线性规划", None)
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    lower_bounds = np.asarray(lower_bounds, dtype=float)
    upper_bounds = np.asarray(upper_bounds, dtype=float)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    matrix = constraint_matrix.tocsr()

    has_integer = bool(np.any(integrality))
    with mosek.Env() as env:
        with env.Task(0, 0) as task:
            configure_mosek_task(mosek, task, options, problem_name)
            task.appendvars(len(objective))
            for index in range(len(objective)):
                task.putcj(index, float(objective[index]))
                bound_key, lower, upper = mosek_bound(mosek, lower_bounds[index], upper_bounds[index])
                task.putvarbound(index, bound_key, lower, upper)
                if integrality[index]:
                    task.putvartype(index, mosek.variabletype.type_int)

            task.appendcons(matrix.shape[0])
            for row_index in range(matrix.shape[0]):
                row = matrix.getrow(row_index)
                task.putarow(
                    row_index,
                    row.indices.astype(int).tolist(),
                    row.data.astype(float).tolist(),
                )
                bound_key, lower, upper = mosek_bound(mosek, constraint_lower[row_index], constraint_upper[row_index])
                task.putconbound(row_index, bound_key, lower, upper)

            task.putobjsense(mosek.objsense.minimize)
            task.optimize()
            solution_type, problem_status, solution_status, solution, objective_value = get_mosek_solution(
                mosek,
                task,
                len(objective),
                has_integer,
            )

    status_text = mosek_status_text(problem_status, solution_status, solution_type)
    return SimpleNamespace(
        success=is_mosek_optimal_status(mosek, solution_status),
        x=solution,
        fun=objective_value,
        message=f"MOSEK status {status_text}",
        solver="mosek",
        status=solution_status,
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
    result = milp(
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
    result.solver = "scipy"
    return result


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


def finite_cplex_bounds(values: np.ndarray, infinity: float) -> np.ndarray:
    return np.where(np.isposinf(values), infinity, np.where(np.isneginf(values), -infinity, values))


def configure_mosek_task(mosek_module: Any, task: Any, options: dict[str, Any], problem_name: str) -> None:
    task.putintparam(mosek_module.iparam.log, 0)
    if hasattr(mosek_module.iparam, "log_mio"):
        task.putintparam(mosek_module.iparam.log_mio, 0)
    if problem_name:
        task.puttaskname(problem_name)
    time_limit = options.get("time_limit")
    if time_limit is not None:
        task.putdouparam(mosek_module.dparam.optimizer_max_time, float(time_limit))
    mip_gap = options.get("mip_rel_gap")
    if mip_gap is not None:
        task.putdouparam(mosek_module.dparam.mio_tol_rel_gap, float(mip_gap))


def mosek_bound(mosek_module: Any, lower: float, upper: float) -> tuple[Any, float, float]:
    has_lower = bool(np.isfinite(lower))
    has_upper = bool(np.isfinite(upper))
    if has_lower and has_upper and np.isclose(lower, upper):
        return mosek_module.boundkey.fx, float(lower), float(upper)
    if has_lower and has_upper:
        return mosek_module.boundkey.ra, float(lower), float(upper)
    if has_lower:
        return mosek_module.boundkey.lo, float(lower), 0.0
    if has_upper:
        return mosek_module.boundkey.up, 0.0, float(upper)
    return mosek_module.boundkey.fr, 0.0, 0.0


def get_mosek_solution(
    mosek_module: Any,
    task: Any,
    variable_count: int,
    has_integer: bool,
) -> tuple[Any | None, Any | None, Any | None, np.ndarray | None, float | None]:
    for solution_type in mosek_solution_types(mosek_module, has_integer):
        try:
            problem_status = task.getprosta(solution_type)
            solution_status = task.getsolsta(solution_type)
        except Exception:
            continue
        try:
            values = [0.0] * variable_count
            task.getxx(solution_type, values)
            objective_value = float(task.getprimalobj(solution_type))
            return (
                solution_type,
                problem_status,
                solution_status,
                np.array(values, dtype=float),
                objective_value,
            )
        except Exception:
            return solution_type, problem_status, solution_status, None, None
    return None, None, None, None, None


def mosek_solution_types(mosek_module: Any, has_integer: bool) -> list[Any]:
    if has_integer:
        return [mosek_module.soltype.itg]
    return [mosek_module.soltype.bas, mosek_module.soltype.itr]


def mosek_status_text(problem_status: Any | None, solution_status: Any | None, solution_type: Any | None) -> str:
    if solution_type is None:
        return "no solution status"
    return f"{solution_type}/{problem_status}/{solution_status}"


def is_mosek_optimal_status(mosek_module: Any, status: Any | None) -> bool:
    return status in {
        mosek_module.solsta.optimal,
        mosek_module.solsta.integer_optimal,
    }


def cplex_variable_type(model: Any, integrality: int, lower: float, upper: float) -> str:
    if is_binary_integer(integrality, lower, upper):
        return model.variables.type.binary
    if integrality:
        return model.variables.type.integer
    return model.variables.type.continuous


def add_cplex_constraints(cplex_module: Any, model: Any, matrix: Any, lower: np.ndarray, upper: np.ndarray) -> None:
    finite_lower = np.isfinite(lower)
    finite_upper = np.isfinite(upper)
    equality = finite_lower & finite_upper & np.isclose(lower, upper)
    add_cplex_constraint_block(cplex_module, model, matrix, equality, "E", lower)
    add_cplex_constraint_block(cplex_module, model, matrix, finite_upper & ~equality, "L", upper)
    add_cplex_constraint_block(cplex_module, model, matrix, finite_lower & ~equality, "G", lower)


def add_cplex_constraint_block(
    cplex_module: Any,
    model: Any,
    matrix: Any,
    mask: np.ndarray,
    sense: str,
    rhs: np.ndarray,
    chunk_size: int = 5000,
) -> None:
    row_indices = np.flatnonzero(mask)
    if len(row_indices) == 0:
        return
    for start in range(0, len(row_indices), chunk_size):
        chunk = row_indices[start:start + chunk_size]
        expressions = []
        for row_index in chunk:
            row = matrix.getrow(int(row_index))
            expressions.append(
                cplex_module.SparsePair(
                    ind=row.indices.tolist(),
                    val=row.data.astype(float).tolist(),
                )
            )
        model.linear_constraints.add(
            lin_expr=expressions,
            senses=sense * len(expressions),
            rhs=rhs[chunk].astype(float).tolist(),
        )


def is_binary_integer(integrality: int, lower: float, upper: float) -> bool:
    return bool(integrality) and abs(lower) < 1e-9 and abs(upper - 1.0) < 1e-9


def is_cplex_optimal_status(model: Any, status: int) -> bool:
    optimal_names = (
        "optimal",
        "optimal_tolerance",
        "MIP_optimal",
        "MIP_optimal_tolerance",
        "optimal_populated",
        "optimal_populated_tolerance",
    )
    optimal_statuses = {
        getattr(model.solution.status, name)
        for name in optimal_names
        if hasattr(model.solution.status, name)
    }
    return status in optimal_statuses


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
