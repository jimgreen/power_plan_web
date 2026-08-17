import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy import sparse


WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))

import milp_solver


class MilpSolverTest(unittest.TestCase):
    def _tiny_problem(self):
        return (
            np.array([1.0]),
            np.array([1]),
            np.array([0.0]),
            np.array([10.0]),
            sparse.csr_matrix([[1.0]]),
            np.array([3.0]),
            np.array([np.inf]),
        )

    def _fake_result(self, solver):
        return SimpleNamespace(success=True, x=np.array([3.0]), fun=3.0, message="ok", solver=solver)

    def test_default_modeling_interface_uses_cvxpy(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_cvxpy", return_value=self._fake_result("scipy"), create=True) as cvxpy_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected native scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "scipy"}, problem_name="测试模型")

        self.assertEqual(result.solver, "scipy")
        cvxpy_mock.assert_called_once()

    def test_cvxpy_interface_does_not_call_native_cplex(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_cvxpy", return_value=self._fake_result("cplex"), create=True) as cvxpy_mock, \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=AssertionError("unexpected native cplex")):
            result = milp_solver.solve_milp(
                *args,
                options={"solver": "cplex", "modeling_interface": "cvxpy"},
                problem_name="测试模型",
            )

        self.assertEqual(result.solver, "cplex")
        cvxpy_mock.assert_called_once()

    def test_auto_tries_cplex_after_gurobi_failure(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=RuntimeError("no gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", return_value=self._fake_result("cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy") as scipy_mock:
            result = milp_solver.solve_milp(*args, options={"modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "cplex")
        cplex_mock.assert_called_once()
        scipy_mock.assert_not_called()

    def test_auto_falls_back_to_scipy_after_gurobi_and_cplex_failure(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=RuntimeError("no gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=RuntimeError("no cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_mosek", side_effect=RuntimeError("no mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_copt", side_effect=RuntimeError("no copt"), create=True), \
                patch.object(milp_solver, "solve_milp_with_mindopt", side_effect=RuntimeError("no mindopt"), create=True), \
                patch.object(milp_solver, "solve_milp_with_scipy", return_value=self._fake_result("scipy")) as scipy_mock:
            result = milp_solver.solve_milp(*args, options={"modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "scipy")
        cplex_mock.assert_called_once()
        mosek_mock.assert_called_once()
        scipy_mock.assert_called_once()

    def test_auto_tries_mosek_after_gurobi_and_cplex_failure(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=RuntimeError("no gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=RuntimeError("no cplex"), create=True), \
                patch.object(milp_solver, "solve_milp_with_mosek", return_value=self._fake_result("mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy") as scipy_mock:
            result = milp_solver.solve_milp(*args, options={"modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "mosek")
        mosek_mock.assert_called_once()
        scipy_mock.assert_not_called()

    def test_solver_option_cplex_calls_cplex_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", return_value=self._fake_result("cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "cplex", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "cplex")
        cplex_mock.assert_called_once()

    def test_solver_option_cplex_uses_native_backend(self):
        args = self._tiny_problem()
        seen_options = {}

        def fake_cplex(*call_args):
            seen_options.update(call_args[7])
            return self._fake_result("cplex")

        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=fake_cplex, create=True), \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            milp_solver.solve_milp(*args, options={"solver": "cplex", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(seen_options["solver_backend"], "native")

    def test_solver_option_gurobi_uses_native_backend(self):
        args = self._tiny_problem()
        seen_options = {}

        def fake_gurobi(*call_args):
            seen_options.update(call_args[7])
            return self._fake_result("gurobi")

        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=fake_gurobi), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=AssertionError("unexpected cplex"), create=True), \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            milp_solver.solve_milp(*args, options={"solver": "gurobi", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(seen_options["solver_backend"], "native")

    def test_solver_option_failure_falls_back_to_default_order(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_cplex", side_effect=RuntimeError("no cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_gurobi", return_value=self._fake_result("gurobi")) as gurobi_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy") as scipy_mock:
            result = milp_solver.solve_milp(*args, options={"solver": "cplex", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "gurobi")
        cplex_mock.assert_called_once()
        gurobi_mock.assert_called_once()
        scipy_mock.assert_not_called()

    def test_solver_option_cplx_alias_calls_cplex_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", return_value=self._fake_result("cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "cplx", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "cplex")
        cplex_mock.assert_called_once()

    def test_solver_option_mosek_calls_mosek_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=AssertionError("unexpected cplex"), create=True), \
                patch.object(milp_solver, "solve_milp_with_mosek", return_value=self._fake_result("mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "mosek", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "mosek")
        mosek_mock.assert_called_once()

    def test_solver_option_msk_alias_calls_mosek_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=AssertionError("unexpected cplex"), create=True), \
                patch.object(milp_solver, "solve_milp_with_mosek", return_value=self._fake_result("mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "msk", "modeling_interface": "native"}, problem_name="测试模型")

        self.assertEqual(result.solver, "mosek")
        mosek_mock.assert_called_once()

    def test_mosek_task_data_is_loaded_through_native_bulk_api(self):
        class FakeMosek:
            class boundkey:
                fx = "fx"
                ra = "ra"
                lo = "lo"
                up = "up"
                fr = "fr"

            class variabletype:
                type_int = "int"

        class FakeTask:
            def __init__(self):
                self.calls = []

            def appendvars(self, count):
                self.calls.append(("appendvars", count))

            def appendcons(self, count):
                self.calls.append(("appendcons", count))

            def putclist(self, indices, values):
                self.calls.append(("putclist", indices, values))

            def putvarboundlist(self, indices, keys, lower, upper):
                self.calls.append(("putvarboundlist", indices, keys, lower, upper))

            def putvartypelist(self, indices, types):
                self.calls.append(("putvartypelist", indices, types))

            def putconboundlist(self, indices, keys, lower, upper):
                self.calls.append(("putconboundlist", indices, keys, lower, upper))

            def putaijlist(self, rows, cols, values):
                self.calls.append(("putaijlist", rows, cols, values))

        task = FakeTask()
        milp_solver.put_mosek_linear_problem_data(
            FakeMosek,
            task,
            np.array([1.0, 2.0]),
            np.array([0, 1]),
            np.array([0.0, 0.0]),
            np.array([np.inf, 1.0]),
            sparse.csr_matrix([[1.0, 0.0], [2.0, 3.0]]),
            np.array([5.0, -np.inf]),
            np.array([5.0, 10.0]),
        )

        self.assertIn(("appendvars", 2), task.calls)
        self.assertIn(("appendcons", 2), task.calls)
        call_names = [call[0] for call in task.calls]
        self.assertIn("putclist", call_names)
        self.assertIn("putvarboundlist", call_names)
        self.assertIn("putvartypelist", call_names)
        self.assertIn("putconboundlist", call_names)
        self.assertIn("putaijlist", call_names)
        self.assertNotIn("putarow", call_names)

    def test_unknown_solver_option_raises_value_error(self):
        args = self._tiny_problem()
        with self.assertRaises(ValueError):
            milp_solver.solve_milp(*args, options={"solver": "unknown"}, problem_name="测试模型")

    def test_native_copt_and_mindopt_dispatch_to_their_adapters(self):
        args = self._tiny_problem()
        for solver, adapter_name in (("copt", "solve_milp_with_copt"), ("mindopt", "solve_milp_with_mindopt")):
            with self.subTest(solver=solver), \
                    patch.object(milp_solver, adapter_name, return_value=self._fake_result(solver), create=True) as adapter:
                result = milp_solver.solve_milp(
                    *args,
                    options={"solver": solver, "modeling_interface": "native"},
                    problem_name="测试模型",
                )

            self.assertEqual(result.solver, solver)
            adapter.assert_called_once()

    def test_native_selected_solver_failure_uses_default_fallback_order(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_copt", side_effect=RuntimeError("no copt"), create=True) as copt_mock, \
                patch.object(milp_solver, "solve_milp_with_gurobi", return_value=self._fake_result("gurobi")) as gurobi_mock:
            result = milp_solver.solve_milp(
                *args,
                options={"solver": "copt", "modeling_interface": "native"},
                problem_name="测试模型",
            )

        self.assertEqual(result.solver, "gurobi")
        copt_mock.assert_called_once()
        gurobi_mock.assert_called_once()

    def test_cvxpy_unsupported_selected_solver_uses_default_fallback_order(self):
        args = self._tiny_problem()
        calls = []

        def fake_cvxpy(solver, *call_args):
            calls.append(solver)
            if solver == "mindopt":
                raise RuntimeError("cvxpy does not support mindopt")
            return self._fake_result(solver)

        with patch.object(milp_solver, "solve_milp_with_cvxpy", side_effect=fake_cvxpy):
            result = milp_solver.solve_milp(
                *args,
                options={"solver": "mindopt", "modeling_interface": "cvxpy"},
                problem_name="测试模型",
            )

        self.assertEqual(result.solver, "gurobi")
        self.assertEqual(calls, ["mindopt", "gurobi"])

    def test_modeling_interface_aliases_are_normalized(self):
        self.assertEqual(milp_solver.normalize_modeling_interface("CVXPY通用接口"), "cvxpy")
        self.assertEqual(milp_solver.normalize_modeling_interface("优化求解器原生接口"), "native")
        self.assertEqual(milp_solver.normalize_modeling_interface("优化求解器内置"), "native")
        self.assertEqual(milp_solver.normalize_modeling_interface("unknown"), "cvxpy")

    def test_real_cvxpy_scipy_milp_succeeds(self):
        args = self._tiny_problem()
        result = milp_solver.solve_milp(
            *args,
            options={"solver": "scipy", "modeling_interface": "cvxpy", "solver_log": False},
            problem_name="CVXPY测试模型",
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(result.solver, "scipy")
        self.assertEqual(result.backend, "cvxpy")
        self.assertAlmostEqual(result.x[0], 3.0, places=6)

    def test_solver_log_stream_emits_complete_lines(self):
        events = []
        stream = milp_solver.SolverLogStream(events.append, prefix="求解器: ")

        stream.write("root relaxation\nnode 1")
        stream.write(" incumbent\n\nnode 2\n")
        stream.flush()

        self.assertEqual(
            [event["message"] for event in events],
            ["求解器: root relaxation", "求解器: node 1 incumbent", "求解器: node 2"],
        )

    def test_scipy_solver_log_is_forwarded_when_enabled(self):
        args = self._tiny_problem()
        events = []

        result = milp_solver.solve_milp(
            *args,
            options={"solver": "scipy", "modeling_interface": "native", "solver_log": True},
            log=events.append,
            problem_name="测试模型",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.solver, "scipy")
        messages = "\n".join(event["message"] for event in events)
        self.assertIn("调用SciPy HiGHS求解器", messages)
        self.assertTrue("HiGHS" in messages or "Presolving" in messages or "Solving report" in messages)


if __name__ == "__main__":
    unittest.main()
