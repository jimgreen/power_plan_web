import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))

import dispatch_milp


class DispatchMilpTest(unittest.TestCase):
    def test_builder_solves_with_injected_solver(self):
        builder = dispatch_milp.MilpModelBuilder()
        x = builder.add_var(("x",), lower=0, upper=10, integer=True, cost=2)
        builder.add_constraint({x: 1.0}, 5.0, 5.0)
        seen = {}

        def fake_solver(objective, integrality, lower_bounds, upper_bounds, matrix, constraint_lower, constraint_upper, options, log, problem_name):
            seen["objective"] = objective
            seen["integrality"] = integrality
            seen["lower_bounds"] = lower_bounds
            seen["upper_bounds"] = upper_bounds
            seen["matrix_shape"] = matrix.shape
            seen["constraint_lower"] = constraint_lower
            seen["constraint_upper"] = constraint_upper
            seen["options"] = options
            seen["problem_name"] = problem_name
            return SimpleNamespace(success=True, x=np.array([5.0]), fun=10.0, message="ok")

        result = dispatch_milp.solve_built_milp(
            builder,
            options={"time_limit": 30},
            log=None,
            problem_name="测试模型",
            solve_fn=fake_solver,
        )

        self.assertTrue(result.success)
        self.assertEqual(seen["matrix_shape"], (1, 1))
        self.assertEqual(seen["problem_name"], "测试模型")
        self.assertEqual(seen["options"]["time_limit"], 30)
        self.assertEqual(seen["integrality"].tolist(), [1])
        self.assertEqual(seen["lower_bounds"].tolist(), [0.0])
        self.assertEqual(seen["upper_bounds"].tolist(), [10.0])
        self.assertEqual(seen["constraint_lower"].tolist(), [5.0])
        self.assertEqual(seen["constraint_upper"].tolist(), [5.0])

    def test_common_dispatch_constraints_are_reusable(self):
        builder = dispatch_milp.MilpModelBuilder()
        power = builder.add_var(("power",), lower=0, upper=20)
        on_1 = builder.add_var(("on", 1), lower=0, upper=1, integer=True)
        on_2 = builder.add_var(("on", 2), lower=0, upper=1, integer=True)
        quantity = builder.add_var(("quantity",), lower=0, upper=2, integer=True)
        charge = builder.add_var(("charge",), lower=0, upper=10)
        discharge = builder.add_var(("discharge",), lower=0, upper=10)
        charge_on = builder.add_var(("charge_on",), lower=0, upper=1, integer=True)
        discharge_on = builder.add_var(("discharge_on",), lower=0, upper=1, integer=True)
        soc = builder.add_var(("soc",), lower=0, upper=100)
        hydrogen = builder.add_var(("hydrogen",), lower=0, upper=50)

        dispatch_milp.add_unit_commitment_constraints(
            builder,
            power_index=power,
            on_indices=[on_1, on_2],
            power_upper=10,
            power_lower=2,
            quantity_index=quantity,
        )
        dispatch_milp.add_storage_constraints(
            builder,
            charge_index=charge,
            discharge_index=discharge,
            charge_on_index=charge_on,
            discharge_on_index=discharge_on,
            soc_index=soc,
            previous_soc_index=None,
            power_capacity_upper=10,
            energy_capacity_terms={quantity: 50},
            initial_ratio=0.5,
            charge_efficiency=0.9,
            discharge_efficiency=0.8,
        )
        dispatch_milp.add_hydrogen_constraints(
            builder,
            storage_index=hydrogen,
            previous_storage_index=None,
            production_terms={power: 0.7},
            consumption_terms={discharge: 2.0},
            capacity_terms={quantity: 25},
            initial_ratio=0.5,
        )

        self.assertEqual(builder.variable_count, 12)
        self.assertEqual(builder.integer_variable_count, 7)
        self.assertGreaterEqual(builder.constraint_count, 9)
        self.assertGreater(builder.nonzero_count, 0)

    def test_minimum_commitment_duration_constraints_use_aggregate_counts(self):
        builder = dispatch_milp.MilpModelBuilder()
        quantity = builder.add_var(("quantity",), lower=0, upper=2, integer=True)
        on_indices = [builder.add_var(("on", hour), lower=0, upper=2, integer=True) for hour in range(3)]
        startup_indices = [builder.add_var(("startup", hour), lower=0, upper=2, integer=True) for hour in range(3)]
        shutdown_indices = [builder.add_var(("shutdown", hour), lower=0, upper=2, integer=True) for hour in range(3)]

        dispatch_milp.add_minimum_commitment_duration_constraints(
            builder,
            on_indices=on_indices,
            quantity_index=quantity,
            startup_indices=startup_indices,
            shutdown_indices=shutdown_indices,
            minimum_on_hours=2,
            minimum_off_hours=2,
        )

        index_to_key = {index: key for key, index in builder.variables.items()}
        matrix = builder.constraint_matrix().tocsr()
        constraints = []
        for row_index in range(builder.constraint_count):
            row = matrix.getrow(row_index)
            terms = {index_to_key[int(column)]: float(value) for column, value in zip(row.indices, row.data)}
            constraints.append((terms, builder.constraint_lower[row_index], builder.constraint_upper[row_index]))

        self.assertIn(({("startup", 1): 1.0, ("on", 1): -1.0, ("on", 0): 1.0}, 0.0, np.inf), constraints)
        self.assertIn(({("shutdown", 1): 1.0, ("on", 1): 1.0, ("on", 0): -1.0}, 0.0, np.inf), constraints)
        self.assertIn(({("on", 1): 1.0, ("on", 2): 1.0, ("startup", 1): -2.0}, 0.0, np.inf), constraints)
        self.assertIn(({("on", 2): 1.0, ("startup", 2): -2.0}, 0.0, np.inf), constraints)
        self.assertIn(({("on", 1): -1.0, ("on", 2): -1.0, ("quantity",): 2.0, ("shutdown", 1): -2.0}, 0.0, np.inf), constraints)
        self.assertIn(({("on", 2): -1.0, ("quantity",): 1.0, ("shutdown", 2): -2.0}, 0.0, np.inf), constraints)


if __name__ == "__main__":
    unittest.main()
