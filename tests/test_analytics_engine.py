"""测试 analytics_engine：陈旧检测、工程洞察与NPZ缓存、诊断结论、龙卷风排行与SSE总线。"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

import analytics_engine


class AnalyticsEngineTests(unittest.TestCase):
    def test_stale_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheme_dir = Path(tmp)
            cfg = scheme_dir / "planning_parameters.csv"
            res = scheme_dir / "opt_results.xlsx"
            cfg.write_text("k,v\na,1\n", encoding="utf-8")
            res.write_text("dummy", encoding="utf-8")
            now = time.time()
            # 结果晚于配置 -> 不陈旧
            os.utime(cfg, (now - 10, now - 10))
            os.utime(res, (now, now))
            info = analytics_engine.build_stale_info(scheme_dir, res)
            self.assertFalse(info["is_stale"])
            # 配置晚于结果 > 1.5s -> 陈旧
            os.utime(cfg, (now + 5, now + 5))
            info2 = analytics_engine.build_stale_info(scheme_dir, res)
            self.assertTrue(info2["is_stale"])
            self.assertIn("更新", info2["reason"])

    def test_engineering_insights_and_npz_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            res_path = Path(tmp) / "opt_results.xlsx"
            res_path.write_bytes(b"mock-workbook-v1")
            hourly = []
            for h in range(48):
                hourly.append(
                    {
                        "hour_index": h + 1,
                        "datetime": f"2026-01-{1 + h // 24:02d} {h % 24:02d}:00",
                        "load": 100.0 + (h % 24) * 2.0,
                        "wind_power": 50.0,
                        "pv_power": 30.0 if 8 <= (h % 24) <= 16 else 0.0,
                        "diesel_power": 20.0 if h >= 24 else 5.0,
                        "curtailed_power": 10.0 if h < 24 else 0.0,
                        "storage_soc": 0.55,
                        "storage_charge": 8.0,
                        "storage_discharge": 6.0,
                        "hydrogen_production_power": 4.0,
                        "fuel_cell_power": 2.0,
                        "unmet_load": 0.0,
                        "wind_speed": 12.5 + (h % 6),
                        "solar_irradiance": 280.0 if 8 <= (h % 24) <= 16 else 0.0,
                        "temperature": -28.0 + (h % 12) * 0.5,
                    }
                )
            green_table = [
                {"指标": "综合度电成本", "数值": 1.82, "单位": "元/kWh"},
                {"指标": "年均总成本", "数值": 120.5, "单位": "万元"},
                {"指标": "年均建设成本", "数值": 78.2, "单位": "万元"},
                {"指标": "年运行成本", "数值": 42.3, "单位": "万元"},
                {"指标": "绿电占比", "数值": 78.5, "单位": "%"},
                {"指标": "新能源弃电率", "数值": 9.2, "单位": "%"},
            ]
            analytics_engine.INSIGHTS_MEMORY_CACHE.clear()
            first = analytics_engine.build_engineering_insights(res_path, lambda: hourly, green_table, [])
            self.assertTrue(first["ok"])
            self.assertEqual(first["cache_source"], "computed")
            self.assertIn("net_load", first["heatmaps"])
            self.assertEqual(len(first["heatmaps"]["net_load"]["matrix"]), 2)
            self.assertGreaterEqual(len(first["typical_days"]), 2)
            first_day_series = first["typical_days"][0]["series"]
            self.assertEqual(len(first_day_series.get("wind_speed", [])), 24)
            self.assertEqual(len(first_day_series.get("solar_irradiance", [])), 24)
            self.assertEqual(len(first_day_series.get("temperature", [])), 24)
            self.assertTrue(first["sankey"]["links"])
            self.assertTrue(first["lcoe_waterfall"]["items"])
            self.assertTrue(analytics_engine.insights_npz_path(res_path).exists())

            # 清空内存缓存，确认二次读取命中 .npz 旁路而无需重新调用 loader
            analytics_engine.INSIGHTS_MEMORY_CACHE.clear()
            called = {"n": 0}

            def fail_loader():
                called["n"] += 1
                return []

            second = analytics_engine.build_engineering_insights(res_path, fail_loader, green_table, [])
            self.assertEqual(second["cache_source"], "npz")
            self.assertEqual(called["n"], 0)

    def test_diagnostic_conclusions_and_tornado(self) -> None:
        conclusions = analytics_engine.build_diagnostic_conclusions(
            green_table=[
                {"指标": "度电成本", "数值": 1.65, "单位": "元/kWh"},
                {"指标": "绿电占比", "数值": 82.0, "单位": "%"},
                {"指标": "弃电率", "数值": 11.0, "单位": "%"},
            ],
            safety_table=[
                {"指标": "最低频率", "数值": 49.72, "单位": "Hz"},
                {"指标": "最高频率", "数值": 50.25, "单位": "Hz"},
            ],
            reliability_rows=[{"指标": "供电可靠率", "数值": 99.96, "单位": "%"}],
            site_summary={"annual_load_mwh": 300.0},
            stale_info={"is_stale": True, "reason": "参数已更新"},
        )
        categories = {c["category"] for c in conclusions}
        self.assertIn("数据一致性", categories)
        self.assertIn("绿电替代", categories)
        self.assertIn("频率安全", categories)
        self.assertIn("供电可靠", categories)

        tornado = analytics_engine.build_tornado_summary(
            [
                {"scheme": "a_load_0p8", "has_result": True, "lcoe": 1.5, "parameter_value": 0.8},
                {"scheme": "a_load_1p0", "has_result": True, "lcoe": 1.8, "parameter_value": 1.0},
                {"scheme": "a_load_1p2", "has_result": True, "lcoe": 2.3, "parameter_value": 1.2},
                {"scheme": "a_wind_0p8", "has_result": True, "lcoe": 2.0, "parameter_value": 0.8},
                {"scheme": "a_wind_1p2", "has_result": True, "lcoe": 1.7, "parameter_value": 1.2},
            ],
            "lcoe",
        )
        self.assertEqual(len(tornado), 2)
        self.assertEqual(tornado[0]["label"], "负荷缩放系数")
        self.assertAlmostEqual(tornado[0]["span"], 0.8, places=3)

    def test_event_broker_publish_subscribe(self) -> None:
        broker = analytics_engine.EventBroker(max_subscribers=8)
        sub = broker.subscribe()
        try:
            self.assertEqual(broker.subscriber_count(), 1)
            broker.publish("tasks", {"scheme": "demo"})
            ev, data = sub.get(timeout=1.0)
            self.assertEqual(ev, "tasks")
            self.assertEqual(data["scheme"], "demo")
        finally:
            broker.unsubscribe(sub)
        self.assertEqual(broker.subscriber_count(), 0)

    def test_server_new_v14_endpoints_and_caching(self) -> None:
        import json
        import server

        admin = {"id": 0, "username": "local", "role": "admin"}
        # 1. 验证 solver_capabilities 缓存与系统诊断含 sse_subscribers & analytics_insights 缓存
        st, _, body = server.handle_admin_system_status(current_user=admin)
        self.assertEqual(st, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertIn("sse_subscribers", payload["environment"])
        cache_keys = {c["key"] for c in payload["caches"]}
        self.assertIn("analytics_insights", cache_keys)

        # 2. 验证 /api/analysis/insights 参数校验
        st_bad, _, _ = server.handle_api_path("/api/analysis/insights", "", current_user=admin)
        self.assertEqual(st_bad, 400)

        # 3. 验证 /api/sensitivity/retry-failed 参数校验
        st_rf, _, _ = server.handle_control_path("/api/sensitivity/retry-failed", b"{}", current_user=admin)
        self.assertEqual(st_rf, 400)

        # 4. 验证 /api/planning/apply-weather-scenario 参数校验
        st_wx, _, _ = server.handle_control_path("/api/planning/apply-weather-scenario", b"{}", current_user=admin)
        self.assertEqual(st_wx, 400)

        # 5. 验证 /api/report/summary 的 site_summary 包含南极气象扩展字段
        st_ls, _, ls_body = server.handle_api_path("/api/planning/schemes", "", current_user=admin)
        self.assertEqual(st_ls, 200)
        schemes = (json.loads(ls_body.decode("utf-8")) or {}).get("schemes") or []
        if schemes:
            sample = schemes[0]["name"]
            st_rep, _, rep_body = server.handle_api_path(
                "/api/report/summary",
                f"scheme={sample}",
                current_user=admin,
            )
            self.assertEqual(st_rep, 200)
            rep_data = json.loads(rep_body.decode("utf-8"))
            site = rep_data.get("site_summary") or {}
            for key in ("min_temp_c", "avg_temp_c", "max_wind_ms", "polar_night_days", "gale_hours", "extreme_cold_hours"):
                self.assertIn(key, site)


if __name__ == "__main__":
    unittest.main()
