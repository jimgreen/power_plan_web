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
import estimate


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

    def test_planning_optimization_uses_count_commitment_variables_without_unit_binaries(self):
        payload = self._payload()
        payload["photovoltaics"][0].update(
            {
                "capacity": 8,
                "quantity_lower": 0,
                "quantity_upper": 1,
            }
        )
        payload["diesel_generators"][0].update(
            {
                "capacity": 10,
                "power_upper": 10,
                "power_lower": 2,
                "fuel_rate": 0.5,
                "quantity_lower": 0,
                "quantity_upper": 2,
            }
        )
        payload["storage_pcs"][0].update({"power_capacity": 10, "quantity_lower": 0, "quantity_upper": 1, "is_grid_forming": 1})
        payload["storage_battery_packs"][0].update({"battery_capacity": 20, "quantity_lower": 0, "quantity_upper": 1})
        payload["hydrogen_electrolyzers"][0].update(
            {
                "power_capacity": 5,
                "power_lower": 1,
                "quantity_lower": 0,
                "quantity_upper": 2,
            }
        )
        payload["fuel_cells"][0].update({"power_capacity": 4, "quantity_lower": 0, "quantity_upper": 1})
        payload["planning_parameters"][0]["diesel_price"] = 2
        payload["time_series"][0]["solar_irradiance"] = 1000
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])
        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["objective"] = c.copy()
            captured["integrality"] = integrality.copy()
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        variables = model["variables"]
        objective = captured["objective"]

        def objective_cost(key):
            return objective[variables[key]]

        self.assertEqual(objective_cost(("diesel_power", 0, 0)), 0.001)
        self.assertEqual(objective_cost(("unmet_load", 0)), plan_optimizer.LOAD_SHED_PENALTY_COST)
        self.assertEqual(objective_cost(("diesel_on_count", 0, 0)), plan_optimizer.DIESEL_ON_COUNT_PENALTY)
        self.assertEqual(objective_cost(("electrolyzer_on_count", 0, 0)), plan_optimizer.ELECTROLYZER_ON_COUNT_PENALTY)
        for key in (
            ("wind_curtailed", 0),
            ("pv_curtailed", 0),
            ("storage_charge", 0),
            ("storage_discharge", 0),
            ("grid_storage_on_count", 0, 0),
            ("electrolyzer_power", 0, 0),
            ("fuel_cell_power", 0, 0),
        ):
            self.assertEqual(objective_cost(key), 0.0)
        self.assertIn(("diesel_on_count", 0, 0), variables)
        self.assertIn(("electrolyzer_on_count", 0, 0), variables)
        self.assertIn(("grid_storage_on_count", 0, 0), variables)
        self.assertIn(("grid_storage_up_available_count", 0, 0), variables)
        self.assertIn(("grid_storage_down_available_count", 0, 0), variables)
        self.assertEqual(captured["integrality"][variables[("diesel_on_count", 0, 0)]], 1)
        self.assertEqual(captured["integrality"][variables[("electrolyzer_on_count", 0, 0)]], 1)
        self.assertEqual(captured["integrality"][variables[("grid_storage_on_count", 0, 0)]], 1)
        for unit in range(2):
            self.assertNotIn(("diesel_on_unit", 0, 0, unit), variables)
            self.assertNotIn(("electrolyzer_on_unit", 0, 0, unit), variables)
            self.assertNotIn(("grid_storage_on", 0, 0, unit), variables)
        self.assertIn(("storage_charge_on", 0), variables)
        self.assertIn(("storage_discharge_on", 0), variables)

    def test_planning_model_avoids_unit_level_variables_for_all_equipment_families(self):
        payload = self._payload()
        payload["diesel_generators"][0].update(
            {"capacity": 10, "power_upper": 10, "power_lower": 2, "quantity_lower": 0, "quantity_upper": 3}
        )
        payload["wind_turbines"][0].update({"capacity": 10, "quantity_lower": 0, "quantity_upper": 3})
        payload["photovoltaics"][0].update({"capacity": 8, "quantity_lower": 0, "quantity_upper": 3})
        payload["storage_pcs"][0].update(
            {"power_capacity": 10, "quantity_lower": 0, "quantity_upper": 3, "is_grid_forming": 1}
        )
        payload["storage_battery_packs"][0].update({"battery_capacity": 20, "quantity_lower": 0, "quantity_upper": 3})
        payload["hydrogen_electrolyzers"][0].update(
            {"power_capacity": 5, "power_lower": 1, "quantity_lower": 0, "quantity_upper": 3}
        )
        payload["hydrogen_tanks"][0].update({"hydrogen_tank_capacity": 100, "quantity_lower": 0, "quantity_upper": 3})
        payload["fuel_cells"][0].update({"power_capacity": 4, "quantity_lower": 0, "quantity_upper": 3})
        payload["time_series"][0]["solar_irradiance"] = 1000
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])
        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["integrality"] = integrality.copy()
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        variables = model["variables"]
        forbidden_unit_variables = {
            "diesel_on_unit",
            "electrolyzer_on_unit",
            "grid_storage_on",
            "grid_storage_up_available",
            "grid_storage_down_available",
            "grid_storage_on_unit",
            "grid_storage_up_available_unit",
            "grid_storage_down_available_unit",
            "renewable_unit_built",
            "fuel_cell_on_unit",
            "hydrogen_tank_unit",
            "storage_battery_unit",
            "storage_pcs_unit",
        }
        self.assertFalse(any(key[0] in forbidden_unit_variables for key in variables))
        for key in (
            ("diesel_on_count", 0, 0),
            ("electrolyzer_on_count", 0, 0),
            ("grid_storage_on_count", 0, 0),
            ("grid_storage_up_available_count", 0, 0),
            ("grid_storage_down_available_count", 0, 0),
            ("renewable_curtailment_product", 0, "wind_turbines", 0),
            ("renewable_curtailment_product", 0, "photovoltaics", 0),
            ("fuel_cell_power", 0, 0),
            ("hydrogen_storage", 0),
            ("storage_soc", 0),
        ):
            self.assertIn(key, variables)
        for key in (
            ("fuel_cell_power", 0, 0),
            ("hydrogen_storage", 0),
            ("storage_soc", 0),
            ("storage_charge", 0),
            ("storage_discharge", 0),
        ):
            self.assertEqual(captured["integrality"][variables[key]], 0)

    def test_planning_optimization_applies_storage_and_hydrogen_self_discharge(self):
        payload = self._payload()
        payload["storage_pcs"][0].update({"power_capacity": 10, "quantity_lower": 1, "quantity_upper": 1})
        payload["storage_battery_packs"][0].update(
            {"battery_capacity": 24, "quantity_lower": 1, "quantity_upper": 1, "self_discharge_rate": 0.012}
        )
        payload["hydrogen_tanks"][0].update(
            {"hydrogen_tank_capacity": 24, "quantity_lower": 1, "quantity_upper": 1, "self_discharge_rate": 0.006}
        )
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:2])
        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["constraints"] = constraints.tocsr()
            captured["constraint_lower"] = constraint_lower
            captured["constraint_upper"] = constraint_upper
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(plan_optimizer, "solve_milp", side_effect=fake_solve_milp):
            plan_optimizer.solve_planning_model(model)

        variables = model["variables"]

        def has_equality(expected_terms):
            matrix = captured["constraints"]
            expected = {variables[key]: coefficient for key, coefficient in expected_terms.items()}
            for row in range(matrix.shape[0]):
                if abs(captured["constraint_lower"][row]) > 1e-9 or abs(captured["constraint_upper"][row]) > 1e-9:
                    continue
                vector = matrix.getrow(row)
                terms = {
                    int(column): float(value)
                    for column, value in zip(vector.indices, vector.data)
                    if abs(value) > 1e-9
                }
                if set(terms) != set(expected):
                    continue
                if all(abs(terms[column] - expected[column]) < 1e-9 for column in expected):
                    return True
            return False

        self.assertAlmostEqual(model["storage_self_discharge_rate"], 0.01)
        self.assertAlmostEqual(model["hydrogen_self_discharge_rate"], 0.006)
        self.assertTrue(has_equality(
            {
                ("storage_soc", 1): 1.0,
                ("storage_charge", 1): -0.95,
                ("storage_discharge", 1): 1.0 / 0.95,
                ("storage_soc", 0): -(1.0 - 0.01 / 24.0),
            }
        ))
        self.assertTrue(has_equality(
            {
                ("hydrogen_storage", 1): 1.0,
                ("hydrogen_storage", 0): -(1.0 - 0.006 / 24.0),
            }
        ))

    def test_planning_optimization_reads_storage_efficiencies_from_storage_pcs(self):
        payload = self._payload()
        payload["planning_parameters"][0]["storage_charge_efficiency"] = 0.31
        payload["planning_parameters"][0]["storage_discharge_efficiency"] = 0.32
        payload["storage_pcs"][0].update(
            {
                "power_capacity": 10,
                "quantity_lower": 1,
                "quantity_upper": 1,
                "storage_charge_efficiency": 0.91,
                "storage_discharge_efficiency": 0.89,
            }
        )
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])

        self.assertEqual(model["storage_charge_efficiency"], 0.91)
        self.assertEqual(model["storage_discharge_efficiency"], 0.89)

    def test_planning_optimization_keeps_legacy_planning_parameter_efficiency_fallback(self):
        payload = self._payload()
        payload["planning_parameters"][0]["storage_charge_efficiency"] = 0.91
        payload["planning_parameters"][0]["storage_discharge_efficiency"] = 0.89
        payload["storage_pcs"][0].pop("storage_charge_efficiency", None)
        payload["storage_pcs"][0].pop("storage_discharge_efficiency", None)
        model = plan_optimizer.build_planning_model(payload, payload["time_series"][:1])

        self.assertEqual(model["storage_charge_efficiency"], 0.91)
        self.assertEqual(model["storage_discharge_efficiency"], 0.89)

    def test_dispatch_evaluation_reads_storage_efficiencies_from_storage_pcs(self):
        payload = self._payload()
        payload["time_series"] = payload["time_series"][:1]
        payload["planning_parameters"][0]["storage_charge_efficiency"] = 0.31
        payload["planning_parameters"][0]["storage_discharge_efficiency"] = 0.32
        payload["storage_pcs"][0]["storage_charge_efficiency"] = 0.91
        payload["storage_pcs"][0]["storage_discharge_efficiency"] = 0.89
        result_rows = [
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 10, "总容量": 10, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 24, "总容量": 24, "单位": "kWh"},
        ]
        model = estimate.build_dispatch_model(payload, result_rows)

        self.assertEqual(model["storage_charge_efficiency"], 0.91)
        self.assertEqual(model["storage_discharge_efficiency"], 0.89)

    def test_evaluation_run_reuses_planning_optimizer_with_fixed_quantities(self):
        payload = self._payload()
        payload["diesel_generators"][0].update({"name": "评估柴发", "quantity_lower": 0, "quantity_upper": 9})
        payload["wind_turbines"][0].update({"name": "评估风机", "quantity_lower": 0, "quantity_upper": 9})
        payload["planning_parameters"][0]["diesel_price"] = 0
        result_rows = [
            {"设备类型": "柴发", "名称": "评估柴发", "设计台数": 2, "单台容量": 10, "总容量": 20, "单位": "kW"},
            {"设备类型": "风机", "名称": "评估风机", "设计台数": 3, "单台容量": 10, "总容量": 30, "单位": "kW"},
        ]
        captured = {}

        def fake_run_optimization(fixed_payload, log=None, horizon_hours=None, allow_direct_result=True):
            captured["diesel"] = fixed_payload["diesel_generators"][0]["quantity_lower"], fixed_payload["diesel_generators"][0]["quantity_upper"]
            captured["wind"] = fixed_payload["wind_turbines"][0]["quantity_lower"], fixed_payload["wind_turbines"][0]["quantity_upper"]
            captured["horizon_hours"] = horizon_hours
            captured["allow_direct_result"] = allow_direct_result
            captured["problem_name"] = fixed_payload.get("_optimization_problem_name")
            captured["diesel_objective_price"] = fixed_payload.get("_diesel_objective_price")
            return {
                "status": "已完成",
                "progress": 100,
                "metrics": [{"label": "度电成本", "value": 0.0, "unit": "元"}],
                "results": {"overview_tables": [], "overview_disks": [], "green_table": [], "safety_table": [], "curves": {}},
                "planning_result_rows": result_rows,
                "dispatch_rows": [],
                "totals": {"diesel_consumption": 0.0},
            }

        with patch.object(plan_optimizer, "run_optimization", side_effect=fake_run_optimization):
            result = estimate.run_estimation(payload, result_rows)

        self.assertEqual(captured["diesel"], (2, 2))
        self.assertEqual(captured["wind"], (3, 3))
        self.assertIsNone(captured["horizon_hours"])
        self.assertFalse(captured["allow_direct_result"])
        self.assertEqual(captured["problem_name"], "方案评估")
        self.assertEqual(captured["diesel_objective_price"], 1.0)
        self.assertEqual(result["status"], "已完成")

    def test_evaluation_module_does_not_keep_legacy_simple_dispatch_path(self):
        source = (WEB_ROOT / "estimate.py").read_text(encoding="utf-8")

        for forbidden in (
            "build_legacy_dispatch_model",
            "solve_legacy_dispatch_model",
            "direct_dispatch_rows",
            "direct_hour_dispatch",
            "allocate_renewable_power",
            "LOAD_SHED_PENALTY",
            "DIESEL_ON_PENALTY",
            "ELECTROLYZER_ON_PENALTY",
        ):
            self.assertNotIn(forbidden, source)

    def test_evaluation_dispatch_model_is_fixed_quantity_planning_model(self):
        payload = self._payload()
        payload["time_series"] = payload["time_series"][:1]
        payload["diesel_generators"][0].update(
            {"name": "评估柴发", "capacity": 10, "power_upper": 10, "quantity_lower": 0, "quantity_upper": 9}
        )
        result_rows = [
            {"设备类型": "柴发", "名称": "评估柴发", "设计台数": 2, "单台容量": 10, "总容量": 20, "单位": "kW"},
        ]
        model = estimate.build_dispatch_model(payload, result_rows)
        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["lower_bounds"] = lower_bounds.copy()
            captured["upper_bounds"] = upper_bounds.copy()
            captured["integrality"] = integrality.copy()
            captured["problem_name"] = problem_name
            return SimpleNamespace(success=True, x=lower_bounds.copy(), fun=0.0, message="ok")

        with patch.object(estimate, "solve_milp", side_effect=fake_solve_milp):
            estimate.solve_dispatch_model(model)

        variables = model["variables"]
        qty_index = variables[("qty", "diesel_generators", 0)]
        self.assertEqual(captured["lower_bounds"][qty_index], 2)
        self.assertEqual(captured["upper_bounds"][qty_index], 2)
        self.assertEqual(captured["integrality"][qty_index], 1)
        self.assertEqual(captured["problem_name"], "方案评估")
        self.assertIn(("diesel_power", 0, 0), variables)
        self.assertNotIn(("diesel_power", 0), variables)

    def test_evaluation_fixed_payload_treats_legacy_storage_row_as_pcs_and_battery(self):
        payload = self._payload()
        payload["storage_pcs"][0].update({"quantity_lower": 0, "quantity_upper": 9})
        payload["storage_battery_packs"][0].update({"quantity_lower": 0, "quantity_upper": 9})
        result_rows = [
            {"设备类型": "储能", "设计台数": 2, "单台容量": 100, "总容量": 200, "单位": "kWh"},
        ]

        fixed_payload = estimate.fixed_quantity_payload(payload, result_rows)

        self.assertEqual(fixed_payload["storage_pcs"][0]["quantity_lower"], 2)
        self.assertEqual(fixed_payload["storage_pcs"][0]["quantity_upper"], 2)
        self.assertEqual(fixed_payload["storage_battery_packs"][0]["quantity_lower"], 2)
        self.assertEqual(fixed_payload["storage_battery_packs"][0]["quantity_upper"], 2)

    def test_dispatch_evaluation_applies_storage_and_hydrogen_self_discharge(self):
        payload = self._payload()
        payload["time_series"] = payload["time_series"][:2]
        for row in payload["time_series"]:
            row["load"] = 0
            row["wind_speed"] = 0
            row["solar_irradiance"] = 0
        payload["storage_battery_packs"][0]["self_discharge_rate"] = 0.01
        payload["hydrogen_tanks"][0]["self_discharge_rate"] = 0.006
        result_rows = [
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 10, "总容量": 10, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 24, "总容量": 24, "单位": "kWh"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 24, "总容量": 24, "单位": "Nm3"},
        ]
        model = estimate.build_dispatch_model(payload, result_rows)
        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["constraints"] = constraints.tocsr()
            captured["constraint_lower"] = constraint_lower
            captured["constraint_upper"] = constraint_upper
            return SimpleNamespace(success=True, x=np.array(lower_bounds, dtype=float), fun=0.0, message="ok")

        with patch.object(estimate, "solve_milp", side_effect=fake_solve_milp):
            estimate.solve_dispatch_model(model)

        variables = model["variables"]

        def has_equality(expected_terms):
            matrix = captured["constraints"]
            expected = {variables[key]: coefficient for key, coefficient in expected_terms.items()}
            for row in range(matrix.shape[0]):
                if abs(captured["constraint_lower"][row]) > 1e-9 or abs(captured["constraint_upper"][row]) > 1e-9:
                    continue
                vector = matrix.getrow(row)
                terms = {
                    int(column): float(value)
                    for column, value in zip(vector.indices, vector.data)
                    if abs(value) > 1e-9
                }
                if set(terms) != set(expected):
                    continue
                if all(abs(terms[column] - expected[column]) < 1e-9 for column in expected):
                    return True
            return False

        self.assertAlmostEqual(model["storage_self_discharge_rate"], 0.01)
        self.assertAlmostEqual(model["hydrogen_self_discharge_rate"], 0.006)
        self.assertTrue(has_equality(
            {
                ("storage_soc", 1): 1.0,
                ("storage_charge", 1): -0.95,
                ("storage_discharge", 1): 1.0 / 0.95,
                ("storage_soc", 0): -(1.0 - 0.01 / 24.0),
            }
        ))
        self.assertTrue(has_equality(
            {
                ("hydrogen_storage", 1): 1.0,
                ("hydrogen_storage", 0): -(1.0 - 0.006 / 24.0),
            }
        ))

    def test_planning_optimization_uses_quantity_level_renewable_curtailment(self):
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
        self.assertIn(("renewable_curtailment_product", 0, "wind_turbines", 0), variables)
        self.assertIn(("renewable_curtailment_product", 0, "photovoltaics", 0), variables)
        self.assertNotIn(("renewable_unit_built", "wind_turbines", 0, 0), variables)
        self.assertNotIn(("renewable_unit_built", "wind_turbines", 0, 1), variables)
        self.assertNotIn(("renewable_unit_built", "photovoltaics", 0, 0), variables)
        self.assertNotIn(("renewable_curtailment_product", 0, "wind_turbines", 0, 0), variables)
        self.assertNotIn(("renewable_curtailment_product", 0, "wind_turbines", 0, 1), variables)
        self.assertEqual(captured["integrality"][variables[("qty", "wind_turbines", 0)]], 1)
        self.assertEqual(captured["integrality"][variables[("qty", "photovoltaics", 0)]], 1)
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
                ("renewable_curtailment_product", 0, "wind_turbines", 0): 1.0,
                ("renewable_curtailment_rate", 0): -2.0,
            },
            -np.inf,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("renewable_curtailment_product", 0, "wind_turbines", 0): 1.0,
                ("qty", "wind_turbines", 0): -1.0,
            },
            -np.inf,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("renewable_curtailment_product", 0, "wind_turbines", 0): 1.0,
                ("renewable_curtailment_rate", 0): -2.0,
                ("qty", "wind_turbines", 0): -1.0,
            },
            -2.0,
            np.inf,
        ))
        self.assertTrue(has_constraint(
            {
                ("wind_curtailed", 0): 1.0,
                ("renewable_curtailment_product", 0, "wind_turbines", 0): -10.0,
            },
            0.0,
            0.0,
        ))
        self.assertTrue(has_constraint(
            {
                ("wind_power", 0): 1.0,
                ("qty", "wind_turbines", 0): -10.0,
                ("renewable_curtailment_product", 0, "wind_turbines", 0): 10.0,
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
        self.assertIn(("grid_storage_on_count", 0, 0), variables)
        self.assertIn(("grid_storage_up_available_count", 0, 0), variables)
        self.assertIn(("grid_storage_down_available_count", 0, 0), variables)
        self.assertNotIn(("grid_storage_on", 0, 0, 0), variables)
        self.assertNotIn(("grid_storage_on", 0, 0, 1), variables)

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
        payload["storage_pcs"][0]["storage_charge_efficiency"] = 1
        payload["storage_pcs"][0]["storage_discharge_efficiency"] = 1

        result = plan_optimizer.run_optimization(payload, horizon_hours=1)
        row = result["dispatch_rows"][0]

        self.assertAlmostEqual(row["storage_soc"], 25.0, places=4)
        self.assertAlmostEqual(row["hydrogen_storage"], 60.0, places=4)


if __name__ == "__main__":
    unittest.main()
