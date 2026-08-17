"""MILP solver adapter for CVXPY and solver-native backends."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
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
    "solver_backend",
    "modeling_interface",
}
DEFAULT_SOLVER_ORDER = ("gurobi", "cplex", "mosek", "copt", "mindopt", "scipy")
SOLVER_BACKENDS = {
    "gurobi": "native",
    "cplex": "native",
    "mosek": "native",
    "copt": "native",
    "mindopt": "native",
    "scipy": "native",
}
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
    "copt": "copt",
    "mindopt": "mindopt",
    "mind opt": "mindopt",
    "highs": "scipy",
    "scipy": "scipy",
}
SOLVER_LABELS = {
    "gurobi": "Gurobi",
    "cplex": "CPLEX",
    "mosek": "MOSEK",
    "copt": "COPT",
    "mindopt": "MindOpt",
    "scipy": "SciPy",
}
MODELING_INTERFACE_ALIASES = {
    "": "cvxpy",
    "cvxpy": "cvxpy",
    "cvxpy通用接口": "cvxpy",
    "通用接口": "cvxpy",
    "native": "native",
    "原生接口": "native",
    "优化求解器原生接口": "native",
    "优化求解器内置": "native",
    "优化求解器内置接口": "native",
}
CVXPY_SOLVER_NAMES = {
    "gurobi": "GUROBI",
    "cplex": "CPLEX",
    "mosek": "MOSEK",
    "copt": "COPT",
    "scipy": "SCIPY",
}
NATIVE_SOLVER_MODULES = {
    "gurobi": "gurobipy",
    "cplex": "cplex",
    "mosek": "mosek",
    "copt": "coptpy",
    "mindopt": "mindoptpy",
    "scipy": "scipy",
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
    "user_limit",
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
    modeling_interface = normalize_modeling_interface(options.pop("modeling_interface", "cvxpy"))
    emit_solver_input_summary(
        objective,
        integrality,
        lower_bounds,
        upper_bounds,
        constraint_lower,
        constraint_upper,
        solver,
        modeling_interface,
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
            candidate_options = options_for_solver_backend(options, candidate, modeling_interface)
            if modeling_interface == "native":
                return solve_milp_with_backend(
                    candidate,
                    objective,
                    integrality,
                    lower_bounds,
                    upper_bounds,
                    constraint_matrix,
                    constraint_lower,
                    constraint_upper,
                    candidate_options,
                    log,
                    problem_name,
                )
            return solve_milp_with_cvxpy(
                candidate,
                objective,
                integrality,
                lower_bounds,
                upper_bounds,
                constraint_matrix,
                constraint_lower,
                constraint_upper,
                candidate_options,
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


def normalize_modeling_interface(value: Any) -> str:
    interface = str(value or "cvxpy").strip().lower()
    return MODELING_INTERFACE_ALIASES.get(interface, "cvxpy")


def options_for_solver_backend(options: dict[str, Any], solver: str, modeling_interface: str = "native") -> dict[str, Any]:
    next_options = dict(options or {})
    next_options["solver_backend"] = "cvxpy" if modeling_interface == "cvxpy" else SOLVER_BACKENDS.get(solver, "native")
    return next_options


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
    if solver == "copt":
        return solve_milp_with_copt(
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
    if solver == "mindopt":
        return solve_milp_with_mindopt(
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


def solver_capabilities() -> dict[str, Any]:
    """Report Python integration availability for each modeling interface."""

    try:
        import cvxpy as cp

        installed_cvxpy_solvers = {str(name).upper() for name in cp.installed_solvers()}
        cvxpy_version = str(getattr(cp, "__version__", ""))
    except Exception:
        installed_cvxpy_solvers = set()
        cvxpy_version = ""

    solvers: dict[str, dict[str, Any]] = {}
    for solver in DEFAULT_SOLVER_ORDER:
        cvxpy_name = CVXPY_SOLVER_NAMES.get(solver, "")
        solvers[solver] = {
            "label": SOLVER_LABELS[solver],
            "native": module_available(NATIVE_SOLVER_MODULES[solver]),
            "cvxpy": bool(cvxpy_name and cvxpy_name in installed_cvxpy_solvers),
        }
    return {
        "default_interface": "cvxpy",
        "interfaces": {
            "cvxpy": {"label": "CVXPY通用接口", "available": bool(cvxpy_version), "version": cvxpy_version},
            "native": {"label": "优化求解器原生接口", "available": True},
        },
        "solvers": solvers,
    }


def module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def solve_milp_with_cvxpy(
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
    import cvxpy as cp

    cvxpy_solver = CVXPY_SOLVER_NAMES.get(solver)
    if not cvxpy_solver:
        raise RuntimeError(f"CVXPY当前版本不支持{SOLVER_LABELS.get(solver, solver)}接口")
    installed_solvers = {str(name).upper() for name in cp.installed_solvers()}
    if cvxpy_solver not in installed_solvers:
        raise RuntimeError(f"CVXPY未检测到{SOLVER_LABELS.get(solver, solver)}求解器")

    emit(log, "info", f"调用CVXPY通用建模接口，当前求解器为{SOLVER_LABELS[solver]}", None)
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    lower_bounds = np.asarray(lower_bounds, dtype=float)
    upper_bounds = np.asarray(upper_bounds, dtype=float)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    matrix = constraint_matrix.tocsr()

    integer_indices = np.flatnonzero(integrality).astype(int).tolist()
    variable_attributes: dict[str, Any] = {}
    if integer_indices:
        variable_attributes["integer"] = (integer_indices,)
    variables = cp.Variable(len(objective), name="x", **variable_attributes)
    constraints: list[Any] = []
    finite_variable_lower = np.isfinite(lower_bounds)
    finite_variable_upper = np.isfinite(upper_bounds)
    if np.any(finite_variable_lower):
        constraints.append(variables[finite_variable_lower] >= lower_bounds[finite_variable_lower])
    if np.any(finite_variable_upper):
        constraints.append(variables[finite_variable_upper] <= upper_bounds[finite_variable_upper])

    finite_constraint_lower = np.isfinite(constraint_lower)
    finite_constraint_upper = np.isfinite(constraint_upper)
    equality = finite_constraint_lower & finite_constraint_upper & np.isclose(constraint_lower, constraint_upper)
    if np.any(equality):
        constraints.append(matrix[equality] @ variables == constraint_lower[equality])
    upper_only = finite_constraint_upper & ~equality
    if np.any(upper_only):
        constraints.append(matrix[upper_only] @ variables <= constraint_upper[upper_only])
    lower_only = finite_constraint_lower & ~equality
    if np.any(lower_only):
        constraints.append(matrix[lower_only] @ variables >= constraint_lower[lower_only])

    problem = cp.Problem(cp.Minimize(objective @ variables), constraints)
    solve_options = cvxpy_solve_options(solver, options)
    solve_options["verbose"] = False
    problem.solve(solver=cvxpy_solver, **solve_options)

    status = str(problem.status or "unknown")
    emit(log, "info", f"CVXPY调用{SOLVER_LABELS[solver]}完成：status={status}", None)
    solution = np.asarray(variables.value, dtype=float).reshape(-1) if variables.value is not None else None
    objective_value = float(problem.value) if problem.value is not None and np.isfinite(problem.value) else None
    return SimpleNamespace(
        success=status in {str(cp.OPTIMAL), str(cp.OPTIMAL_INACCURATE)},
        x=solution,
        fun=objective_value,
        message=f"CVXPY {SOLVER_LABELS[solver]} status {status}",
        solver=solver,
        backend="cvxpy",
        status=status,
    )


def cvxpy_solve_options(solver: str, options: dict[str, Any]) -> dict[str, Any]:
    time_limit = options.get("time_limit")
    mip_gap = options.get("mip_rel_gap")
    if solver == "gurobi":
        return compact_options({"TimeLimit": time_limit, "MIPGap": mip_gap})
    if solver == "cplex":
        return {
            "cplex_params": compact_options(
                {"timelimit": time_limit, "mip.tolerances.mipgap": mip_gap}
            )
        }
    if solver == "mosek":
        return {
            "mosek_params": compact_options(
                {
                    "MSK_DPAR_OPTIMIZER_MAX_TIME": time_limit,
                    "MSK_DPAR_MIO_TOL_REL_GAP": mip_gap,
                }
            )
        }
    if solver == "copt":
        return compact_options({"TimeLimit": time_limit, "RelGap": mip_gap})
    if solver == "scipy":
        return {
            "scipy_options": compact_options(
                {"method": "highs", "time_limit": time_limit, "mip_rel_gap": mip_gap}
            )
        }
    raise ValueError(f"CVXPY不支持求解器：{solver}")


def compact_options(options: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in options.items() if value is not None}


def emit_solver_input_summary(
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
    solver: str,
    modeling_interface: str,
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
            f"solver={solver or 'auto'}，interface={modeling_interface}，"
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

    emit(log, "info", "调用Gurobi原生后端求解混合整数线性规划", None)
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
        backend=options.get("solver_backend") or "native",
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

    emit(log, "info", "调用CPLEX原生后端求解混合整数线性规划", None)
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
        backend=options.get("solver_backend") or "native",
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

    emit(log, "info", "调用MOSEK原生Task API求解混合整数线性规划", None)
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
            put_mosek_linear_problem_data(
                mosek,
                task,
                objective,
                integrality,
                lower_bounds,
                upper_bounds,
                matrix,
                constraint_lower,
                constraint_upper,
            )
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
        backend=options.get("solver_backend") or "native",
        status=solution_status,
    )


def put_mosek_linear_problem_data(
    mosek_module: Any,
    task: Any,
    objective: np.ndarray,
    integrality: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    matrix: Any,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
) -> None:
    variable_count = len(objective)
    constraint_count = int(matrix.shape[0])
    variable_indices = np.arange(variable_count, dtype=np.int32).tolist()
    constraint_indices = np.arange(constraint_count, dtype=np.int32).tolist()

    task.appendvars(variable_count)
    if variable_indices:
        task.putclist(variable_indices, np.asarray(objective, dtype=float).tolist())
        variable_bounds = [mosek_bound(mosek_module, lower_bounds[index], upper_bounds[index]) for index in range(variable_count)]
        task.putvarboundlist(
            variable_indices,
            [item[0] for item in variable_bounds],
            [item[1] for item in variable_bounds],
            [item[2] for item in variable_bounds],
        )
        integer_indices = np.flatnonzero(np.asarray(integrality, dtype=int)).astype(np.int32).tolist()
        if integer_indices:
            task.putvartypelist(
                integer_indices,
                [mosek_module.variabletype.type_int] * len(integer_indices),
            )

    task.appendcons(constraint_count)
    if constraint_indices:
        constraint_bounds = [mosek_bound(mosek_module, constraint_lower[index], constraint_upper[index]) for index in range(constraint_count)]
        task.putconboundlist(
            constraint_indices,
            [item[0] for item in constraint_bounds],
            [item[1] for item in constraint_bounds],
            [item[2] for item in constraint_bounds],
        )

    coo = matrix.tocoo()
    coo.sum_duplicates()
    nonzero_mask = np.asarray(coo.data, dtype=float) != 0.0
    if np.any(nonzero_mask):
        task.putaijlist(
            coo.row[nonzero_mask].astype(np.int32).tolist(),
            coo.col[nonzero_mask].astype(np.int32).tolist(),
            coo.data[nonzero_mask].astype(float).tolist(),
        )


def solve_milp_with_copt(
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
    import coptpy

    emit(log, "info", "调用COPT原生后端求解混合整数线性规划", None)
    copt = coptpy.COPT
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    native_infinity = getattr(copt, "INFINITY", 1e20)
    lower_bounds = finite_native_bounds(np.asarray(lower_bounds, dtype=float), native_infinity)
    upper_bounds = finite_native_bounds(np.asarray(upper_bounds, dtype=float), native_infinity)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    matrix = constraint_matrix.tocsr()

    environment = coptpy.Envr()
    model = environment.createModel(problem_name or "MILP")
    try:
        time_limit = options.get("time_limit")
        if time_limit is not None:
            model.setParam(copt.Param.TimeLimit, float(time_limit))
        mip_gap = options.get("mip_rel_gap")
        if mip_gap is not None:
            model.setParam(copt.Param.RelGap, float(mip_gap))

        variable_types = np.array(
            [
                copt.BINARY
                if is_binary_integer(integrality[index], lower_bounds[index], upper_bounds[index])
                else copt.INTEGER
                if integrality[index]
                else copt.CONTINUOUS
                for index in range(len(objective))
            ]
        )
        variables = model.addMVar(
            len(objective),
            lb=lower_bounds,
            ub=upper_bounds,
            obj=objective,
            vtype=variable_types,
            nameprefix="x",
        )
        model.setObjective(objective @ variables, copt.MINIMIZE)
        add_copt_constraints(copt, model, matrix, variables, constraint_lower, constraint_upper)
        model.solve()

        status = model.status
        has_solution = bool(model.hasmipsol if np.any(integrality) else model.haslpsol)
        solution = np.asarray(variables.x, dtype=float).reshape(-1) if has_solution else None
        objective_value = float(model.objval) if has_solution else None
        status_text = "time limit" if status == getattr(copt, "TIMEOUT", None) else str(status)
        return SimpleNamespace(
            success=status == copt.OPTIMAL,
            x=solution,
            fun=objective_value,
            message=f"COPT status {status_text}",
            solver="copt",
            backend=options.get("solver_backend") or "native",
            status=status,
        )
    finally:
        close_optional_solver_object(model)
        close_optional_solver_object(environment)


def add_copt_constraints(
    copt: Any,
    model: Any,
    matrix: Any,
    variables: Any,
    lower: np.ndarray,
    upper: np.ndarray,
) -> None:
    add_native_matrix_constraint_blocks(
        model,
        matrix,
        variables,
        lower,
        upper,
        copt.EQUAL,
        copt.LESS_EQUAL,
        copt.GREATER_EQUAL,
    )


def solve_milp_with_mindopt(
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
    import mindoptpy

    emit(log, "info", "调用MindOpt原生后端求解混合整数线性规划", None)
    mdo = mindoptpy.MDO
    objective = np.asarray(objective, dtype=float)
    integrality = np.asarray(integrality, dtype=int)
    native_infinity = getattr(mdo, "INFINITY", 1e20)
    lower_bounds = finite_native_bounds(np.asarray(lower_bounds, dtype=float), native_infinity)
    upper_bounds = finite_native_bounds(np.asarray(upper_bounds, dtype=float), native_infinity)
    constraint_lower = np.asarray(constraint_lower, dtype=float)
    constraint_upper = np.asarray(constraint_upper, dtype=float)
    matrix = constraint_matrix.tocsr()

    model = mindoptpy.Model(problem_name or "MILP")
    try:
        time_limit = options.get("time_limit")
        if time_limit is not None:
            model.setParam(mdo.Param.MaxTime, float(time_limit))
        mip_gap = options.get("mip_rel_gap")
        if mip_gap is not None:
            model.setParam(mdo.Param.MIP_GapRel, float(mip_gap))

        variable_types = np.array(
            [
                mdo.BINARY
                if is_binary_integer(integrality[index], lower_bounds[index], upper_bounds[index])
                else mdo.INTEGER
                if integrality[index]
                else mdo.CONTINUOUS
                for index in range(len(objective))
            ]
        )
        variables = model.addMVar(
            shape=(len(objective),),
            lb=lower_bounds,
            ub=upper_bounds,
            obj=objective,
            vtype=variable_types,
            name="x",
        )
        model.setObjective(objective @ variables, mdo.MINIMIZE)
        add_native_matrix_constraint_blocks(
            model,
            matrix,
            variables,
            constraint_lower,
            constraint_upper,
            mdo.EQUAL,
            mdo.LESS_EQUAL,
            mdo.GREATER_EQUAL,
        )
        model.optimize()

        status = model.getAttr(mdo.Attr.Status)
        solution_count = int(model.getAttr(mdo.Attr.SolCount) or 0)
        solution = np.asarray(variables.getAttr(mdo.Attr.X), dtype=float).reshape(-1) if solution_count else None
        objective_value = float(model.getAttr(mdo.Attr.ObjVal)) if solution_count else None
        status_text = "time limit" if status == getattr(mdo.Status, "TIME_LIMIT", None) else str(status)
        return SimpleNamespace(
            success=status == mdo.Status.OPTIMAL,
            x=solution,
            fun=objective_value,
            message=f"MindOpt status {status_text}",
            solver="mindopt",
            backend=options.get("solver_backend") or "native",
            status=status,
        )
    finally:
        close_optional_solver_object(model)


def add_native_matrix_constraint_blocks(
    model: Any,
    matrix: Any,
    variables: Any,
    lower: np.ndarray,
    upper: np.ndarray,
    equal_sense: Any,
    less_equal_sense: Any,
    greater_equal_sense: Any,
) -> None:
    finite_lower = np.isfinite(lower)
    finite_upper = np.isfinite(upper)
    equality = finite_lower & finite_upper & np.isclose(lower, upper)
    for mask, sense, rhs in (
        (equality, equal_sense, lower),
        (finite_upper & ~equality, less_equal_sense, upper),
        (finite_lower & ~equality, greater_equal_sense, lower),
    ):
        if np.any(mask):
            model.addMConstr(matrix[mask], variables, sense, rhs[mask])


def finite_native_bounds(values: np.ndarray, infinity: float) -> np.ndarray:
    return np.where(np.isposinf(values), float(infinity), np.where(np.isneginf(values), -float(infinity), values))


def close_optional_solver_object(value: Any) -> None:
    for method_name in ("dispose", "close"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
            return


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
    result.backend = options.get("solver_backend") or "scipy-highs"
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
