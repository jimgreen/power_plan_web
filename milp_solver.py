"""MILP solver adapter with Gurobi, CPLEX, MOSEK, and SciPy backends."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from typing import Any, Callable
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


LogSink = Callable[[dict[str, Any]], None]
CUSTOM_SOLVER_OPTIONS = {
    "solver_log",
    "solver_log_prefix",
    "solver_log_line_limit",
    "solver_log_interval",
}
DEFAULT_SOLVER_ORDER = ("gurobi", "cplex", "mosek", "scipy")
SOLVER_ALIASES = {
    "": "auto",
    "auto": "auto",
    "automatic": "auto",
    "grb": "gurobi",
    "gurobi": "gurobi",
    "cplx": "cplex",
    "cplex": "cplex",
    "msk": "mosek",
    "mosek": "mosek",
    "highs": "scipy",
    "scipy": "scipy",
}
SOLVER_LABELS = {
    "gurobi": "Gurobi",
    "cplex": "CPLEX",
    "mosek": "MOSEK",
    "scipy": "SciPy",
}

TIMEOUT_TEXT_MARKERS = (
    "time_limit",
    "time limit",
    "timelimit",
    "time_limit_reached",
    "time limit reached",
    "timeout",
    "timed out",
    "time out",
    "maximum time",
    "max time",
    "optimizer_max_time",
    "最大用时",
    "时间上限",
    "计算超时",
    "超时",
)


class CalculationTimeoutError(RuntimeError):
    """Raised when the backend solver stops because the configured time limit is reached."""


def is_timeout_text(text: object) -> bool:
    """Return True when solver text indicates a time-limit stop."""

    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    compact = normalized.replace("-", "_")
    return any(marker in normalized or marker in compact for marker in TIMEOUT_TEXT_MARKERS)


def is_timeout_result(result: Any) -> bool:
    """Return True when a backend OptimizeResult-like object timed out."""

    if result is None:
        return False
    message = getattr(result, "message", "")
    if is_timeout_text(message):
        return True
    solver = str(getattr(result, "solver", "") or "").strip().lower()
    status = getattr(result, "status", None)
    if solver in ("gurobi", "grb", ""):
        try:
            if int(status) == 9:
                return True
        except (TypeError, ValueError):
            pass
    return False


class SolverLogStream:
    """File-like stream that forwards solver text output to the UI log sink."""

    def __init__(
        self,
        log: LogSink | None,
        *,
        prefix: str = "",
        level: str = "info",
        max_line_length: int = 1200,
    ) -> None:
        self.log = log
        self.prefix = prefix
        self.level = level
        self.max_line_length = max(120, int(max_line_length or 1200))
        self._buffer = ""

    def write(self, text: object) -> int:
        chunk = str(text or "")
        if not chunk:
            return 0
        self._buffer += chunk.replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit_line(line)
        return len(chunk)

    def flush(self) -> None:
        if self._buffer:
            line = self._buffer
            self._buffer = ""
            self._emit_line(line)

    def _emit_line(self, line: str) -> None:
        clean_line = " ".join(str(line or "").strip().split())
        if not clean_line:
            return
        if len(clean_line) > self.max_line_length:
            clean_line = clean_line[: self.max_line_length - 3] + "..."
        emit(self.log, self.level, f"{self.prefix}{clean_line}", None)


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

    # The solver adapter keeps backend selection and logging behavior in one
    # place so planning and evaluation can share the same solve entry point.
    options = dict(options or {})
    solver = normalize_solver_name(options.pop("solver", "auto"))
    emit_solver_input_summary(
        objective,
        integrality,
        lower_bounds,
        upper_bounds,
        constraint_lower,
        constraint_upper,
        solver,
        log,
    )

    if solver == "auto":
        solver_order = list(DEFAULT_SOLVER_ORDER)
    elif solver in DEFAULT_SOLVER_ORDER:
        solver_order = [solver, *(candidate for candidate in DEFAULT_SOLVER_ORDER if candidate != solver)]
    else:
        raise ValueError(f"未知MILP求解器：{solver}")

    for index, candidate in enumerate(solver_order):
        try:
            return solve_milp_with_backend(
                candidate,
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
            next_solver = solver_order[index + 1] if index + 1 < len(solver_order) else ""
            if not next_solver:
                raise
            emit(log, "warn", f"{SOLVER_LABELS[candidate]}求解器不可用，改用{SOLVER_LABELS[next_solver]}求解器：{exc}", None)

    raise RuntimeError("没有可用的MILP求解器")


def normalize_solver_name(value: Any) -> str:
    solver = str(value or "auto").strip().lower()
    return SOLVER_ALIASES.get(solver, solver)


def solve_milp_with_backend(
    solver: str,
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
    if solver == "gurobi":
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
    if solver == "cplex":
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
    if solver == "mosek":
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
    if solver == "scipy":
        return solve_milp_with_scipy(
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
    raise ValueError(f"未知MILP求解器：{solver}")


def emit_solver_input_summary(
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
    solver: str,
    log: LogSink | None,
) -> None:
    # Record a compact view of the model before solving so runtime logs are
    # useful even when the backend solver itself is noisy.
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    lower_bounds = np.asarray(lower_bounds, dtype=float)
    upper_bounds = np.asarray(upper_bounds, dtype=float)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    finite_lower = np.isfinite(constraint_lower)
    finite_upper = np.isfinite(constraint_upper)
    equality = finite_lower & finite_upper & np.isclose(constraint_lower, constraint_upper)
    binary_count = sum(
        1
        for index in range(len(objective))
        if is_binary_integer(int(integrality[index]), float(lower_bounds[index]), float(upper_bounds[index]))
    )
    integer_count = int(np.count_nonzero(integrality))
    nonzero_objective_count = int(np.count_nonzero(np.abs(objective) > 1e-12))
    emit(
        log,
        "info",
        (
            "求解器输入："
            f"solver={solver or 'auto'}，"
            f"变量={len(objective)}个，二进制={binary_count}个，整数={integer_count}个，"
            f"目标非零项={nonzero_objective_count}个，"
            f"等式约束={int(np.count_nonzero(equality))}条，"
            f"上界约束={int(np.count_nonzero(finite_upper & ~equality))}条，"
            f"下界约束={int(np.count_nonzero(finite_lower & ~equality))}条"
        ),
        None,
    )


def solver_log_requested(options: dict[str, Any]) -> bool:
    return bool(options.get("solver_log", True))


def solver_log_enabled(options: dict[str, Any], log: LogSink | None) -> bool:
    return solver_log_requested(options) and log is not None


def solver_log_line_limit(options: dict[str, Any]) -> int:
    try:
        return int(options.get("solver_log_line_limit", 1200))
    except (TypeError, ValueError):
        return 1200


def solver_log_interval(options: dict[str, Any]) -> float:
    try:
        return max(0.2, float(options.get("solver_log_interval", 2.0)))
    except (TypeError, ValueError):
        return 2.0


def scipy_milp_options(options: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in options.items() if key not in CUSTOM_SOLVER_OPTIONS}


def gurobi_progress_callback(gp: Any, log: LogSink | None, options: dict[str, Any]) -> Callable[[Any, int], None]:
    interval = solver_log_interval(options)
    last_emit = {"time": 0.0}

    def callback(model: Any, where: int) -> None:
        if where not in (gp.GRB.Callback.MIP, gp.GRB.Callback.MIPSOL):
            return
        now = time.monotonic()
        if now - last_emit["time"] < interval and where != gp.GRB.Callback.MIPSOL:
            return
        last_emit["time"] = now
        try:
            if where == gp.GRB.Callback.MIPSOL:
                incumbent = model.cbGet(gp.GRB.Callback.MIPSOL_OBJ)
                emit(log, "info", f"Gurobi找到新可行解：目标值={format_solver_number(incumbent)}", None)
                return
            node_count = model.cbGet(gp.GRB.Callback.MIP_NODCNT)
            best_objective = model.cbGet(gp.GRB.Callback.MIP_OBJBST)
            best_bound = model.cbGet(gp.GRB.Callback.MIP_OBJBND)
            solution_count = model.cbGet(gp.GRB.Callback.MIP_SOLCNT)
            gap_text = gurobi_gap_text(best_objective, best_bound)
            emit(
                log,
                "info",
                (
                    "Gurobi迭代："
                    f"节点={format_solver_number(node_count)}，"
                    f"可行解={format_solver_number(solution_count)}，"
                    f"当前最优={format_solver_number(best_objective)}，"
                    f"最优界={format_solver_number(best_bound)}，"
                    f"Gap={gap_text}"
                ),
                None,
            )
        except Exception as exc:
            emit(log, "warn", f"Gurobi迭代日志读取失败：{exc}", None)

    return callback


def gurobi_gap_text(best_objective: float, best_bound: float) -> str:
    if not np.isfinite(best_objective) or not np.isfinite(best_bound):
        return "-"
    denominator = max(1.0, abs(float(best_objective)))
    return f"{abs(float(best_objective) - float(best_bound)) / denominator * 100:.4g}%"


def format_solver_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "-"
    if abs(number) >= 10000 or (0 < abs(number) < 0.001):
        return f"{number:.4e}"
    return f"{number:.6g}"


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
    callback = gurobi_progress_callback(gp, log, options) if solver_log_enabled(options, log) else None
    if callback:
        model.optimize(callback)
    else:
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
    cplex_log_stream = (
        SolverLogStream(log, prefix="CPLEX: ", max_line_length=solver_log_line_limit(options))
        if solver_log_enabled(options, log)
        else None
    )
    cplex_warning_stream = (
        SolverLogStream(log, prefix="CPLEX警告: ", level="warn", max_line_length=solver_log_line_limit(options))
        if solver_log_enabled(options, log)
        else None
    )
    model.set_log_stream(cplex_log_stream)
    model.set_error_stream(cplex_warning_stream)
    model.set_warning_stream(cplex_warning_stream)
    model.set_results_stream(cplex_log_stream)

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
    if cplex_log_stream:
        cplex_log_stream.flush()
    if cplex_warning_stream:
        cplex_warning_stream.flush()

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
            configure_mosek_task(mosek, task, options, problem_name, log)
            mosek_log_stream = (
                SolverLogStream(log, prefix="MOSEK: ", max_line_length=solver_log_line_limit(options))
                if solver_log_enabled(options, log)
                else None
            )
            if mosek_log_stream:
                task.set_Stream(mosek.streamtype.log, mosek_log_stream.write)
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
            if mosek_log_stream:
                mosek_log_stream.flush()
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
    log: LogSink | None = None,
    problem_name: str = "MILP",
) -> Any:
    emit(log, "info", f"调用SciPy HiGHS求解器求解混合整数线性规划：{problem_name}", None)
    scipy_options = scipy_milp_options(options)
    solver_output = solver_log_enabled(options, log)
    if solver_output:
        scipy_options["disp"] = True
        stream = SolverLogStream(log, prefix="HiGHS: ", max_line_length=solver_log_line_limit(options))
        with redirect_stdout(stream), redirect_stderr(stream):
            result = run_scipy_milp(
                objective,
                integrality,
                lower_bounds,
                upper_bounds,
                constraint_matrix,
                constraint_lower,
                constraint_upper,
                scipy_options,
            )
        stream.flush()
    else:
        result = run_scipy_milp(
            objective,
            integrality,
            lower_bounds,
            upper_bounds,
            constraint_matrix,
            constraint_lower,
            constraint_upper,
            scipy_options,
        )
    result.solver = "scipy"
    return result


def run_scipy_milp(
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


def finite_cplex_bounds(values: np.ndarray, infinity: float) -> np.ndarray:
    return np.where(np.isposinf(values), infinity, np.where(np.isneginf(values), -infinity, values))


def configure_mosek_task(mosek_module: Any, task: Any, options: dict[str, Any], problem_name: str, log: LogSink | None) -> None:
    if solver_log_enabled(options, log):
        task.putintparam(mosek_module.iparam.log, 1)
    else:
        task.putintparam(mosek_module.iparam.log, 0)
    if hasattr(mosek_module.iparam, "log_mio"):
        task.putintparam(mosek_module.iparam.log_mio, 1 if solver_log_enabled(options, log) else 0)
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
