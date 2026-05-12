import sys
import unittest
from pathlib import Path


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
        payload["planning_parameters"][0]["planning_load_factor"] = 1
        payload["planning_parameters"][0]["diesel_price"] = 0
        payload["planning_parameters"][0]["green_power_ratio_lower"] = 0
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


if __name__ == "__main__":
    unittest.main()
