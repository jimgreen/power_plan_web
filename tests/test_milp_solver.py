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

    def test_auto_tries_cplex_after_gurobi_failure(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=RuntimeError("no gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", return_value=self._fake_result("cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy") as scipy_mock:
            result = milp_solver.solve_milp(*args, options={}, problem_name="测试模型")

        self.assertEqual(result.solver, "cplex")
        cplex_mock.assert_called_once()
        scipy_mock.assert_not_called()

    def test_auto_falls_back_to_scipy_after_gurobi_and_cplex_failure(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=RuntimeError("no gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=RuntimeError("no cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_mosek", side_effect=RuntimeError("no mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", return_value=self._fake_result("scipy")) as scipy_mock:
            result = milp_solver.solve_milp(*args, options={}, problem_name="测试模型")

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
            result = milp_solver.solve_milp(*args, options={}, problem_name="测试模型")

        self.assertEqual(result.solver, "mosek")
        mosek_mock.assert_called_once()
        scipy_mock.assert_not_called()

    def test_solver_option_cplex_calls_cplex_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", return_value=self._fake_result("cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "cplex"}, problem_name="测试模型")

        self.assertEqual(result.solver, "cplex")
        cplex_mock.assert_called_once()

    def test_solver_option_cplx_alias_calls_cplex_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", return_value=self._fake_result("cplex"), create=True) as cplex_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "cplx"}, problem_name="测试模型")

        self.assertEqual(result.solver, "cplex")
        cplex_mock.assert_called_once()

    def test_solver_option_mosek_calls_mosek_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=AssertionError("unexpected cplex"), create=True), \
                patch.object(milp_solver, "solve_milp_with_mosek", return_value=self._fake_result("mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "mosek"}, problem_name="测试模型")

        self.assertEqual(result.solver, "mosek")
        mosek_mock.assert_called_once()

    def test_solver_option_msk_alias_calls_mosek_only(self):
        args = self._tiny_problem()
        with patch.object(milp_solver, "solve_milp_with_gurobi", side_effect=AssertionError("unexpected gurobi")), \
                patch.object(milp_solver, "solve_milp_with_cplex", side_effect=AssertionError("unexpected cplex"), create=True), \
                patch.object(milp_solver, "solve_milp_with_mosek", return_value=self._fake_result("mosek"), create=True) as mosek_mock, \
                patch.object(milp_solver, "solve_milp_with_scipy", side_effect=AssertionError("unexpected scipy")):
            result = milp_solver.solve_milp(*args, options={"solver": "msk"}, problem_name="测试模型")

        self.assertEqual(result.solver, "mosek")
        mosek_mock.assert_called_once()

    def test_unknown_solver_option_raises_value_error(self):
        args = self._tiny_problem()
        with self.assertRaises(ValueError):
            milp_solver.solve_milp(*args, options={"solver": "unknown"}, problem_name="测试模型")

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

        result = milp_solver.solve_milp(*args, options={"solver": "scipy", "solver_log": True}, log=events.append, problem_name="测试模型")

        self.assertTrue(result.success)
        self.assertEqual(result.solver, "scipy")
        messages = "\n".join(event["message"] for event in events)
        self.assertIn("调用SciPy HiGHS求解器", messages)
        self.assertTrue("HiGHS" in messages or "Presolving" in messages or "Solving report" in messages)


if __name__ == "__main__":
    unittest.main()
