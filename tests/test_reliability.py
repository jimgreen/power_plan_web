import json
import sys
import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))

import reliability


class ReliabilityTest(unittest.TestCase):
    def _payload(self, time_series=None):
        return {
            "scheme": "可靠性测试",
            "time_series": time_series
            or [
                {
                    "hour_index": 1,
                    "datetime": "H1",
                    "wind_speed": 0,
                    "solar_irradiance": 0,
                    "load": 0,
                    "temperature": 0,
                }
            ],
            "diesel_generators": [],
            "wind_turbines": [],
            "photovoltaics": [],
            "storage_pcs": [],
            "storage_battery_packs": [],
            "planning_parameters": [{"initial_storage_soc_ratio": 0.5}],
        }

    def _fixed_row(self, **values):
        row = {"quantity_lower": 1, "quantity_upper": 1, "cost": 0}
        row.update(values)
        return row

    def test_two_state_sampler_is_reproducible_and_tracks_for(self):
        first = reliability.sample_two_state_availability(
            4, 0.10, 8, 40000, seed=1234, initial_state="stationary"
        )
        second = reliability.sample_two_state_availability(
            4, 0.10, 8, 40000, seed=1234, initial_state="stationary"
        )

        self.assertEqual(first, second)
        observed_for = 1.0 - sum(first) / (4 * len(first))
        self.assertAlmostEqual(observed_for, 0.10, delta=0.015)

        transition = reliability.two_state_transition_probabilities(0.10, 8)
        stationary_down = transition["up_to_down"] / (
            transition["up_to_down"] + transition["down_to_up"]
        )
        self.assertAlmostEqual(stationary_down, 0.10, places=12)

    def test_nonzero_for_requires_mttr_and_percent_for_is_supported(self):
        payload = self._payload()
        payload["diesel_generators"] = [
            self._fixed_row(name="柴发", capacity=10, power_upper=10, forced_outage_rate=5)
        ]

        with self.assertRaisesRegex(ValueError, "MTTR"):
            reliability.build_reliability_case(payload)

        payload["diesel_generators"][0]["mttr_hours"] = 12
        case = reliability.build_reliability_case(payload)
        self.assertEqual(case["groups"][0]["forced_outage_rate"], 0.05)

    def test_storage_dispatch_respects_pcs_power_and_soc_lower_bound(self):
        payload = self._payload(
            [
                {"load": 0, "wind_speed": 0, "solar_irradiance": 1000},
                {"load": 10, "wind_speed": 0, "solar_irradiance": 0},
                {"load": 10, "wind_speed": 0, "solar_irradiance": 0},
            ]
        )
        payload["planning_parameters"][0]["initial_storage_soc_ratio"] = 0.2
        payload["photovoltaics"] = [self._fixed_row(name="光伏", capacity=10)]
        payload["storage_pcs"] = [
            self._fixed_row(
                name="PCS",
                power_capacity=5,
                storage_charge_efficiency=1,
                storage_discharge_efficiency=1,
            )
        ]
        payload["storage_battery_packs"] = [
            self._fixed_row(
                name="电池",
                battery_capacity=10,
                soc_lower=0.2,
                soc_upper=0.8,
                self_discharge_rate=0,
            )
        ]
        case = reliability.build_reliability_case(payload)

        result = reliability.dispatch_hourly(case, include_hourly=True)

        self.assertEqual(result["summary"]["ens_kwh"], 15.0)
        self.assertEqual(result["summary"]["lole_hours"], 2.0)
        self.assertEqual(result["summary"]["lolf_events"], 1)
        self.assertEqual(result["summary"]["max_deficit_kw"], 10.0)
        self.assertEqual(result["summary"]["longest_consecutive_outage_hours"], 2.0)
        self.assertAlmostEqual(result["summary"]["end_storage"]["soc_ratio"], 0.2)
        self.assertEqual(result["hourly"][0]["storage_charge_kw"], 5.0)
        self.assertEqual(result["hourly"][1]["storage_discharge_kw"], 5.0)

    def test_pcs_outage_makes_battery_energy_inaccessible(self):
        payload = self._payload(
            [
                {"load": 0, "wind_speed": 0, "solar_irradiance": 1000},
                {"load": 10, "wind_speed": 0, "solar_irradiance": 0},
            ]
        )
        payload["planning_parameters"][0]["initial_storage_soc_ratio"] = 0.2
        payload["photovoltaics"] = [self._fixed_row(name="光伏", capacity=10)]
        payload["storage_pcs"] = [
            self._fixed_row(
                name="PCS",
                power_capacity=10,
                storage_charge_efficiency=1,
                storage_discharge_efficiency=1,
            )
        ]
        payload["storage_battery_packs"] = [
            self._fixed_row(
                name="电池",
                battery_capacity=10,
                soc_lower=0.2,
                soc_upper=0.9,
                self_discharge_rate=0,
            )
        ]
        case = reliability.build_reliability_case(payload)
        pcs = next(group for group in case["groups"] if group["device_type"] == "pcs")

        result = reliability.dispatch_hourly(case, {pcs["id"]: [0, 0]})

        self.assertEqual(result["summary"]["storage_charge_energy_kwh"], 0.0)
        self.assertEqual(result["summary"]["storage_discharge_energy_kwh"], 0.0)
        self.assertEqual(result["summary"]["ens_kwh"], 10.0)

    def test_dispatch_counts_lolf_and_longest_consecutive_shortage(self):
        payload = self._payload([{"load": 5}] * 4)
        payload["diesel_generators"] = [
            self._fixed_row(name="柴发", capacity=10, power_upper=10)
        ]
        case = reliability.build_reliability_case(payload)
        diesel = case["groups"][0]

        result = reliability.dispatch_hourly(case, {diesel["id"]: [0, 1, 0, 0]})

        self.assertEqual(result["summary"]["ens_kwh"], 15.0)
        self.assertEqual(result["summary"]["lole_hours"], 3.0)
        self.assertEqual(result["summary"]["lolf_events"], 2)
        self.assertEqual(result["summary"]["longest_consecutive_outage_hours"], 2.0)

    def test_n_minus_one_removes_one_physical_unit(self):
        payload = self._payload([{"load": 8}, {"load": 8}])
        payload["diesel_generators"] = [
            {
                "name": "柴发",
                "capacity": 5,
                "power_upper": 5,
                "quantity_lower": 2,
                "quantity_upper": 2,
                "forced_outage_rate": 0,
                "mttr_hours": 0,
            }
        ]
        case = reliability.build_reliability_case(payload)

        result = reliability.run_n_minus_one(case, device_types=["diesel"])

        self.assertEqual(result["base_case"]["ens_kwh"], 0.0)
        self.assertEqual(result["scenario_count"], 1)
        scenario = result["scenarios"][0]
        self.assertEqual(scenario["removed_capacity_kw"], 5.0)
        self.assertEqual(scenario["ens_kwh"], 6.0)
        self.assertEqual(scenario["lole_hours"], 2.0)
        self.assertEqual(scenario["max_deficit_kw"], 3.0)
        self.assertFalse(scenario["passed"])

    def test_all_five_equipment_families_have_independent_unit_states(self):
        payload = self._payload([{"load": 0, "wind_speed": 12, "solar_irradiance": 1000}] * 2)
        common = {"forced_outage_rate": 1, "mttr_hours": 0}
        payload["diesel_generators"] = [
            self._fixed_row(name="柴发", capacity=10, power_upper=10, **common)
        ]
        payload["wind_turbines"] = [
            self._fixed_row(
                name="风机",
                capacity=10,
                cut_in_wind_speed=3,
                rated_wind_speed=12,
                cut_out_wind_speed=25,
                **common,
            )
        ]
        payload["photovoltaics"] = [self._fixed_row(name="光伏", capacity=10, **common)]
        payload["storage_pcs"] = [
            self._fixed_row(
                name="PCS",
                power_capacity=10,
                storage_charge_efficiency=1,
                storage_discharge_efficiency=1,
                **common,
            )
        ]
        payload["storage_battery_packs"] = [
            self._fixed_row(
                name="电池",
                battery_capacity=10,
                soc_lower=0.1,
                soc_upper=0.9,
                self_discharge_rate=0,
                **common,
            )
        ]
        case = reliability.build_reliability_case(payload)

        availability = reliability.sample_fleet_availability(case, 2, seed=8)
        n_minus_one = reliability.run_n_minus_one(case)

        self.assertEqual(len(availability), 5)
        self.assertTrue(all(states == [[False, False]] for states in availability.values()))
        self.assertEqual(
            {scenario["device_type"] for scenario in n_minus_one["scenarios"]},
            {"diesel", "wind", "pv", "pcs", "battery"},
        )
        battery_scenario = next(
            scenario for scenario in n_minus_one["scenarios"] if scenario["device_type"] == "battery"
        )
        self.assertEqual(battery_scenario["removed_capacity_kwh"], 10.0)

    def test_all_down_monte_carlo_outputs_expected_metrics_and_contribution(self):
        payload = self._payload([{"load": 4}] * 4)
        payload["diesel_generators"] = [
            self._fixed_row(
                name="柴发",
                capacity=10,
                power_upper=10,
                forced_outage_rate=1,
                mttr_hours=0,
            )
        ]
        case = reliability.build_reliability_case(
            payload,
            config={"simulation_years": 3, "hours_per_year": 4, "seed": 9},
        )

        result = reliability.run_sequential_monte_carlo(case)

        self.assertEqual(result["summary"]["eens_kwh_per_year"], 35040.0)
        self.assertEqual(result["summary"]["lole_hours_per_year"], 8760.0)
        self.assertEqual(result["summary"]["lolp"], 1.0)
        self.assertEqual(result["summary"]["lpsp"], 1.0)
        self.assertEqual(result["summary"]["p95_ens_kwh_per_year"], 35040.0)
        self.assertEqual(result["summary"]["p99_ens_kwh_per_year"], 35040.0)
        self.assertEqual(result["confidence_intervals"]["eens_kwh_per_year"]["half_width"], 0.0)
        self.assertEqual(
            result["device_contributions"][0]["marginal_eens_reduction_kwh_per_year"],
            35040.0,
        )
        self.assertEqual(result["device_contributions"][0]["normalized_contribution_share"], 1.0)

    def test_zero_load_has_no_division_errors(self):
        case = reliability.build_reliability_case(self._payload([{"load": 0}] * 3))

        result = reliability.dispatch_hourly(case)

        self.assertEqual(result["summary"]["ens_kwh"], 0.0)
        self.assertEqual(result["summary"]["lpsp"], 0.0)
        self.assertEqual(result["summary"]["energy_supply_reliability"], 1.0)
        self.assertEqual(result["summary"]["time_supply_availability"], 1.0)

    def test_planning_result_rows_fix_installed_quantity(self):
        payload = self._payload([{"load": 0}])
        payload["diesel_generators"] = [
            {
                "name": "目标柴发",
                "capacity": 10,
                "power_upper": 10,
                "quantity_lower": 0,
                "quantity_upper": 9,
                "forced_outage_rate": 0,
                "mttr_hours": 0,
            }
        ]
        planning_rows = [
            {
                "设备类型": "柴发",
                "名称": "目标柴发",
                "设计台数": 2,
                "单台容量": 10,
                "总容量": 20,
                "单位": "kW",
            }
        ]

        case = reliability.build_reliability_case(payload, planning_rows)

        self.assertEqual(case["groups"][0]["unit_count"], 2)
        self.assertEqual(case["groups"][0]["quantity_source"], "fixed_bounds")

    def test_full_payload_is_strict_json_serializable_and_has_all_sections(self):
        payload = self._payload([{"load": 3}, {"load": 3}])
        payload["diesel_generators"] = [
            self._fixed_row(
                name="柴发",
                capacity=5,
                power_upper=5,
                forced_outage_rate=0,
                mttr_hours=0,
            )
        ]

        result = reliability.run_reliability_assessment(
            payload,
            config={
                "simulation_years": 2,
                "hours_per_year": 2,
                "seed": 42,
                "include_device_contributions": True,
            },
        )

        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.assertTrue(encoded)
        self.assertEqual(result["status"], "completed")
        self.assertIn("eens_kwh_per_year", result["summary"])
        self.assertIn("p95_ens_kwh_per_year", result["summary"])
        self.assertIn("confidence_intervals", result)
        self.assertIn("n_minus_one", result)
        self.assertIn("device_contributions", result)
        self.assertIn("annual_samples", result)
        self.assertTrue(any("独立校核" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
