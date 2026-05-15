import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))

import plan_optimizer
import planning_store


class PlanOptimizerTest(unittest.TestCase):
    def _payload(self):
        payload = planning_store.default_payload("优化测试")
        for index, row in enumerate(payload["time_series"]):
            row["hour_index"] = index + 1
            row["datetime"] = f"H{index + 1:04d}"
            row["wind_speed"] = 12
            row["solar_irradiance"] = 0
            row["temperature"] = 20
            row["load"] = 10
        for key in planning_store.DEFAULT_DEVICE_ROWS:
            for row in payload[key]:
                row["quantity_lower"] = 0
                row["quantity_upper"] = 0
                row["cost"] = 0
                row["design_life_years"] = 20
        payload["planning_parameters"][0]["diesel_price"] = 0
        payload["planning_parameters"][0]["green_power_ratio_lower"] = 0
        payload["planning_parameters"][0]["optimization_time_limit_minutes"] = 60
        return payload

    def test_planning_optimization_optimizes_equipment_counts_and_cost_terms(self):
        payload = self._payload()
        payload["diesel_generators"][0].update(
            {
                "capacity": 10,
                "power_upper": 10,
                "power_lower": 0,
                "fuel_rate": 0.5,
                "quantity_lower": 1,
                "quantity_upper": 1,
                "cost": 0,
                "design_life_years": 20,
            }
        )
        payload["wind_turbines"][0].update(
            {
                "capacity": 10,
                "cost": 20,
                "quantity_lower": 0,
                "quantity_upper": 2,
                "design_life_years": 10,
            }
        )
        payload["planning_parameters"][0]["green_power_ratio_lower"] = 0.5

        result = plan_optimizer.run_optimization(payload, horizon_hours=24)

        planning_rows = result["planning_result_rows"]
        by_type = {row["设备类型"]: row for row in planning_rows}
        self.assertEqual(by_type["柴发"]["设计台数"], 1)
        self.assertEqual(by_type["风机"]["设计台数"], 1)
        self.assertEqual(by_type["风机"]["单台容量"], 10)
        self.assertEqual(by_type["风机"]["总容量"], 10)
        annual_rows = {
            row["指标"]: row
            for row in result["results"]["overview_tables"][1]["rows"]
        }
        self.assertAlmostEqual(annual_rows["年均建设成本"]["数值"], 2.0, places=4)
        self.assertGreaterEqual(annual_rows["绿电占比"]["数值"], 50.0)
        self.assertEqual(result["totals"]["unmet_load_energy"], 0)

    def test_planning_optimization_uses_diesel_price_from_planning_parameters(self):
        payload = self._payload()
        for row in payload["time_series"]:
            row["wind_speed"] = 0
        payload["diesel_generators"][0].update(
            {
                "capacity": 10,
                "power_upper": 10,
                "power_lower": 0,
                "fuel_rate": 0.5,
                "quantity_lower": 1,
                "quantity_upper": 1,
                "cost": 100,
                "design_life_years": 10,
            }
        )
        payload["planning_parameters"][0]["diesel_price"] = 2

        result = plan_optimizer.run_optimization(payload, horizon_hours=24)

        annual_rows = {
            row["指标"]: row
            for row in result["results"]["overview_tables"][1]["rows"]
        }
        self.assertAlmostEqual(annual_rows["年均建设成本"]["数值"], 10.0, places=4)
        self.assertAlmostEqual(annual_rows["年柴油成本"]["数值"], 0.24, places=4)
        self.assertAlmostEqual(annual_rows["年总成本"]["数值"], 10.24, places=4)
        self.assertAlmostEqual(result["totals"]["diesel_consumption"], 0.12, places=4)

    def test_planning_optimization_emits_detailed_progress_logs(self):
        payload = self._payload()
        payload["diesel_generators"][0].update(
            {
                "capacity": 10,
                "power_upper": 10,
                "power_lower": 0,
                "fuel_rate": 0.5,
                "quantity_lower": 1,
                "quantity_upper": 1,
            }
        )
        events = []

        plan_optimizer.run_optimization(payload, horizon_hours=24, log=events.append)

        messages = "\n".join(event["message"] for event in events)
        for expected in (
            "模型输入",
            "候选设备",
            "模型规模",
            "求解参数",
            "求解器返回",
            "成本汇总",
            "容量结果",
        ):
            self.assertIn(expected, messages)

    def test_planning_optimization_uses_time_limit_from_planning_parameters(self):
        payload = self._payload()
        payload["planning_parameters"][0]["optimization_time_limit_minutes"] = 90
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])
        seen_options = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            seen_options.update(options)
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        self.assertEqual(seen_options["time_limit"], 5400)

    def test_planning_optimization_uses_unit_commitment_binaries(self):
        payload = self._payload()
        payload["diesel_generators"][0].update(
            {
                "capacity": 10,
                "power_upper": 10,
                "power_lower": 2,
                "quantity_lower": 0,
                "quantity_upper": 2,
            }
        )
        payload["storage_pcs"][0].update({"power_capacity": 10, "quantity_lower": 0, "quantity_upper": 1})
        payload["storage_battery_packs"][0].update({"battery_capacity": 20, "quantity_lower": 0, "quantity_upper": 1})
        payload["hydrogen_electrolyzers"][0].update(
            {
                "power_capacity": 5,
                "power_lower": 1,
                "quantity_lower": 0,
                "quantity_upper": 2,
            }
        )
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        variables = model["variables"]
        for unit in range(2):
            self.assertIn(("diesel_on_unit", 0, 0, unit), variables)
            self.assertIn(("electrolyzer_on_unit", 0, 0, unit), variables)
            self.assertNotIn(("diesel_on_count", 0, 0), variables)
            self.assertNotIn(("electrolyzer_on_count", 0, 0), variables)
        self.assertIn(("storage_charge_on", 0), variables)
        self.assertIn(("storage_discharge_on", 0), variables)

    def test_planning_optimization_models_each_renewable_unit_for_exact_curtailment_rate(self):
        payload = self._payload()
        payload["wind_turbines"][0].update(
            {"capacity": 10, "quantity_lower": 0, "quantity_upper": 2}
        )
        payload["photovoltaics"][0].update(
            {"capacity": 8, "quantity_lower": 0, "quantity_upper": 1}
        )
        payload["time_series"][0]["solar_irradiance"] = 1000
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])

        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["integrality"] = integrality
            captured["constraints"] = constraints.tocsr()
            captured["constraint_lower"] = constraint_lower
            captured["constraint_upper"] = constraint_upper
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        variables = model["variables"]
        self.assertIn(("renewable_curtailment_rate", 0), variables)
        self.assertIn(("renewable_unit_built", "wind_turbines", 0, 0), variables)
        self.assertIn(("renewable_unit_built", "wind_turbines", 0, 1), variables)
        self.assertIn(("renewable_unit_built", "photovoltaics", 0, 0), variables)
        self.assertIn(("renewable_curtailment_product", 0, "wind_turbines", 0, 0), variables)
        self.assertIn(("renewable_curtailment_product", 0, "wind_turbines", 0, 1), variables)
        self.assertIn(("renewable_curtailment_product", 0, "photovoltaics", 0, 0), variables)
        self.assertEqual(captured["integrality"][variables[("renewable_unit_built", "wind_turbines", 0, 0)]], 1)
        self.assertEqual(captured["integrality"][variables[("renewable_unit_built", "photovoltaics", 0, 0)]], 1)
        self.assertEqual(captured["integrality"][variables[("renewable_curtailment_rate", 0)]], 0)

        def has_constraint(expected_terms, expected_lower, expected_upper):
            matrix = captured["constraints"]
            expected = {variables[key]: coefficient for key, coefficient in expected_terms.items()}
            for row in range(matrix.shape[0]):
                vector = matrix.getrow(row)
                terms = {
                    int(column): float(value)
                    for column, value in zip(vector.indices, vector.data)
                    if abs(value) > 1e-9
                }
                if set(terms) != set(expected):
                    continue
                if not all(abs(terms[column] - expected[column]) < 1e-9 for column in expected):
                    continue
                lower = captured["constraint_lower"][row]
                upper = captured["constraint_upper"][row]
                lower_matches = np.isneginf(expected_lower) and np.isneginf(lower) or abs(lower - expected_lower) < 1e-9
                upper_matches = np.isposinf(expected_upper) and np.isposinf(upper) or abs(upper - expected_upper) < 1e-9
                if lower_matches and upper_matches:
                    return True
            return False

        self.assertTrue(has_constraint(
            {
                ("qty", "wind_turbines", 0): 1.0,
                ("renewable_unit_built", "wind_turbines", 0, 0): -1.0,
                ("renewable_unit_built", "wind_turbines", 0, 1): -1.0,
            },
            0.0,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 0): 1.0,
                ("renewable_curtailment_rate", 0): -1.0,
            },
            -np.inf,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 0): 1.0,
                ("renewable_unit_built", "wind_turbines", 0, 0): -1.0,
            },
            -np.inf,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 0): 1.0,
                ("renewable_curtailment_rate", 0): -1.0,
                ("renewable_unit_built", "wind_turbines", 0, 0): -1.0,
            },
            -1.0,
            np.inf,
        ))
        self.assertTrue(has_constraint(
            {
                ("wind_curtailed", 0): 1.0,
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 0): -10.0,
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 1): -10.0,
            },
            0.0,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("wind_power", 0): 1.0,
                ("renewable_unit_built", "wind_turbines", 0, 0): -10.0,
                ("renewable_unit_built", "wind_turbines", 0, 1): -10.0,
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 0): 10.0,
                ("renewable_curtailment_product", 0, "wind_turbines", 0, 1): 10.0,
            },
            0.0,
            0.0,
        ))

    def test_planning_model_tracks_grid_forming_storage_and_soc_limits(self):
        payload = self._payload()
        payload["planning_parameters"][0]["post_disturbance_power_balance_enabled"] = 1
        payload["diesel_generators"][0].update(
            {"capacity": 10, "power_upper": 10, "power_lower": 0, "quantity_lower": 0, "quantity_upper": 1}
        )
        payload["storage_pcs"][0].update(
            {"power_capacity": 10, "quantity_lower": 0, "quantity_upper": 2, "is_grid_forming": 1}
        )
        payload["storage_battery_packs"][0].update(
            {"battery_capacity": 100, "quantity_lower": 1, "quantity_upper": 1, "soc_upper": 0.8, "soc_lower": 0.2}
        )
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        variables = model["variables"]
        self.assertTrue(model["post_disturbance_power_balance_enabled"])
        self.assertEqual(model["storage_soc_upper_ratio"], 0.8)
        self.assertEqual(model["storage_soc_lower_ratio"], 0.2)
        self.assertIn(("grid_storage_on", 0, 0, 0), variables)
        self.assertIn(("grid_storage_on", 0, 0, 1), variables)

    def test_planning_optimization_uses_initial_storage_ratios_from_planning_parameters(self):
        payload = self._payload()
        for row in payload["time_series"]:
            row["load"] = 0
            row["wind_speed"] = 0
        payload["storage_battery_packs"][0].update(
            {"battery_capacity": 100, "quantity_lower": 1, "quantity_upper": 1}
        )
        payload["hydrogen_tanks"][0].update(
            {"hydrogen_tank_capacity": 80, "quantity_lower": 1, "quantity_upper": 1}
        )
        payload["planning_parameters"][0]["initial_storage_soc_ratio"] = 0.25
        payload["planning_parameters"][0]["initial_hydrogen_storage_ratio"] = 0.75
        payload["planning_parameters"][0]["storage_charge_efficiency"] = 1
        payload["planning_parameters"][0]["storage_discharge_efficiency"] = 1

        result = plan_optimizer.run_optimization(payload, horizon_hours=1)
        row = result["dispatch_rows"][0]

        self.assertAlmostEqual(row["storage_soc"], 25.0, places=4)
        self.assertAlmostEqual(row["hydrogen_storage"], 60.0, places=4)


if __name__ == "__main__":
    unittest.main()
