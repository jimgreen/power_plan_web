import json
import shutil
import sys
import time
import unittest
import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from unittest.mock import patch

from openpyxl import Workbook, load_workbook


WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))

import server
import estimate


class FakeCursor:
    def __init__(self, rows_by_sql):
        self.rows_by_sql = rows_by_sql
        self.last_sql = ""
        self.last_params = ()
        self.executed = []

    def execute(self, sql, params=()):
        self.last_sql = " ".join(sql.split())
        self.last_params = params
        self.executed.append((self.last_sql, params))

    def fetchall(self):
        return self.rows_by_sql.get(self.last_sql, [])

    def fetchone(self):
        rows = self.fetchall()
        if isinstance(rows, dict):
            return rows
        return rows[0] if rows else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, rows_by_sql):
        self.cursor_obj = FakeCursor(rows_by_sql)
        self.committed = False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        pass


class PowerPlanServerTest(unittest.TestCase):
    def setUp(self):
        self._original_data_source = server.DATA_SOURCE
        self._original_simu_runtime = server.SIMU_RUNTIME
        server.DATA_SOURCE = server.CsvDataSource()
        server.SIMU_RUNTIME = server.SimuRuntime()

    def tearDown(self):
        server.DATA_SOURCE = self._original_data_source
        server.SIMU_RUNTIME = self._original_simu_runtime

    def wait_optimization_runtime(self, runtime, timeout=30):
        deadline = time.time() + timeout
        payload = runtime.snapshot()
        while payload["status"] == "运行中" and time.time() < deadline:
            time.sleep(0.05)
            payload = runtime.snapshot()
        return payload

    def test_api_payload_excludes_removed_monitor_sections(self):
        payload = server.build_snapshot()

        self.assertEqual(payload["system"], "考察站风-光-氢-储-柴联合规划系统")
        self.assertIn("timestamp", payload)
        self.assertIn("summary", payload)
        self.assertNotIn("simu", payload)
        self.assertNotIn("scada", payload)
        self.assertNotIn("agc", payload)

    def test_index_page_has_visual_planning_entry_buttons(self):
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("assets/i18n.js", html)
        self.assertIn(".language-switch", html)
        self.assertIn('background-image: url("assets/main-dashboard-bg.png?v=20260513-bg-refresh")', html)
        self.assertIn("background-size: contain", html)
        self.assertIn('<link rel="icon" href="data:,">', html)
        self.assertIn(".screen::before", html)
        self.assertIn("filter: saturate(1.08) brightness(0.74) contrast(1.08)", html)
        self.assertIn('class="home-title"', html)
        self.assertIn("考察站风-光-氢-储-柴联合规划系统</h1>", html)
        home_title_css = html.split(".home-title {", 1)[1].split("}", 1)[0]
        self.assertIn("z-index: 6", home_title_css)
        self.assertIn("text-shadow: none", home_title_css)
        self.assertIn("color: #ffffff", home_title_css)
        home_user_status_css = html.split(".home-user-status {", 1)[1].split("}", 1)[0]
        self.assertIn("border: 0", home_user_status_css)
        self.assertIn("background:", home_user_status_css)
        self.assertIn(".energy-side", html)
        self.assertIn(".energy-left", html)
        self.assertIn(".energy-right", html)
        energy_side_css = html.split(".energy-side {", 1)[1].split("}", 1)[0]
        self.assertIn("top: 50%", energy_side_css)
        self.assertIn("min-height: clamp(320px, 41vh, 400px)", energy_side_css)
        self.assertIn("align-content: space-around", energy_side_css)
        self.assertIn("transform: translateY(-29%)", energy_side_css)
        self.assertIn("clip-path: polygon", html)
        self.assertIn("box-shadow:", html)
        self.assertIn("color: #21d5ff", html)
        self.assertIn('class="feature-entry-grid"', html)
        self.assertIn('aria-label="规划功能快捷入口"', html)
        self.assertEqual(html.count('class="feature-entry"'), 4)
        self.assertEqual(html.count('class="feature-icon"'), 4)
        self.assertIn('class="energy-side energy-left"', html)
        self.assertIn('class="energy-side energy-right"', html)
        self.assertIn('<strong>参数维护</strong>', html)
        self.assertIn('<strong>规划求解</strong>', html)
        self.assertIn('<strong>方案评估</strong>', html)
        self.assertIn('<strong>结果对比</strong>', html)
        self.assertNotIn("规划参数维护", html)
        self.assertNotIn("规划算法", html)
        self.assertNotIn("规划方案评估", html)
        self.assertIn('href="planning.html"', html)
        self.assertIn('href="optimize.html"', html)
        self.assertIn('href="evaluation.html"', html)
        self.assertIn('href="comparison.html"', html)
        self.assertIn(".feature-entry-grid", html)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", html)
        self.assertIn("top: 50%", html)
        self.assertIn("transform: translate(-50%, -29%)", html)
        feature_text_css = html.split(".feature-entry strong {", 1)[1].split("}", 1)[0]
        self.assertIn("white-space: nowrap", feature_text_css)
        self.assertIn("font-size: clamp(16px, min(1.55vw, 4.2vh), 30px)", feature_text_css)
        self.assertIn("max-width: 100%", feature_text_css)
        self.assertNotIn("text-overflow: ellipsis", feature_text_css)
        self.assertNotIn("overflow: hidden", feature_text_css)
        self.assertIn(".feature-icon svg", html)
        self.assertNotIn("hot-nav", html)
        self.assertNotIn("quick-links", html)
        self.assertNotIn("系统主导航", html)
        self.assertNotIn("在线监视快捷入口", html)
        self.assertNotIn("SIMU在线监视", html)

    def test_power_plan_pages_share_dark_hud_visual_theme(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")
        planning_html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        optimize_html = (WEB_ROOT / "optimize.html").read_text(encoding="utf-8")

        self.assertIn("assets/planning.css?v=", planning_html)
        self.assertIn("assets/planning.css?v=", optimize_html)
        self.assertIn('url("main-dashboard-bg.png?v=20260513-bg-refresh")', css)
        self.assertIn("--hud-cyan: #21d5ff", css)
        self.assertIn("--hud-panel:", css)
        self.assertIn("rgba(20, 190, 255, 0.64)", css)
        self.assertIn(".scheme-rail,", css)
        self.assertIn(".optimization-command-card,", css)
        self.assertIn("background: var(--hud-panel)", css)
        self.assertIn("color: var(--hud-text)", css)

    def test_monitor_static_pages_are_removed(self):
        for filename in ("simu.html", "scada.html", "agc.html"):
            self.assertFalse((WEB_ROOT / filename).exists())

    def test_auth_pages_and_topbars_include_user_controls(self):
        login_html = (WEB_ROOT / "login.html").read_text(encoding="utf-8")
        register_html = (WEB_ROOT / "register.html").read_text(encoding="utf-8")
        users_html = (WEB_ROOT / "users.html").read_text(encoding="utf-8")
        planning_html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        optimize_html = (WEB_ROOT / "optimize.html").read_text(encoding="utf-8")
        index_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")
        i18n_script = (WEB_ROOT / "assets" / "i18n.js").read_text(encoding="utf-8")

        self.assertIn('id="loginForm"', login_html)
        self.assertIn('id="registerForm"', register_html)
        self.assertIn('body data-admin-page="true"', users_html)
        self.assertIn('id="usersTable"', users_html)
        for html in (planning_html, optimize_html, index_html, users_html):
            self.assertIn("data-auth-user", html)
            self.assertIn("data-auth-username", html)
            self.assertIn("data-logout", html)
            self.assertIn("assets/auth.js", html)
            self.assertIn("assets/i18n.js", html)
        self.assertIn("assets/i18n.js", login_html)
        self.assertIn("assets/i18n.js", register_html)
        self.assertIn("powerPlanLanguage", i18n_script)
        self.assertIn("languageSelect", i18n_script)
        self.assertIn("PowerPlanI18n", i18n_script)
        self.assertIn("Station Wind-Solar-Hydrogen-Storage-Diesel Planning System", i18n_script)
        self.assertIn("Scenario Evaluation", i18n_script)
        self.assertIn("Result Comparison", i18n_script)
        self.assertIn("Load Up Disturbance Factor", i18n_script)
        self.assertIn("Load Down Disturbance Factor", i18n_script)
        self.assertIn("Renewable Down Disturbance Factor", i18n_script)
        self.assertIn("MutationObserver", i18n_script)
        self.assertIn("patchDialogs", i18n_script)
        self.assertIn("target.parentNode.insertBefore(wrap, target)", i18n_script)
        self.assertNotIn("target.insertBefore(wrap, target.firstElementChild)", i18n_script)
        self.assertIn("const translated = translateText(node.nodeValue, language);", i18n_script)
        self.assertIn("if (translated !== node.nodeValue) node.nodeValue = translated;", i18n_script)
        self.assertIn("data-admin-only", planning_html)
        self.assertIn("data-admin-only", optimize_html)
        self.assertIn("data-admin-only", index_html)
        self.assertIn(".user-status", css)
        self.assertIn(".language-switch", css)
        self.assertIn(".auth-shell > .language-switch", css)
        user_status_css = css.split(".user-status {", 1)[1].split("}", 1)[0]
        self.assertIn("border: 0", user_status_css)
        self.assertIn(".auth-card", css)
        self.assertIn("font-size: 17px", css)

    def test_sqlite_user_store_registers_first_user_as_admin_and_authenticates(self):
        db_path = WEB_ROOT / "tests" / "tmp_users.sqlite3"
        db_path.unlink(missing_ok=True)
        try:
            store = server.UserStore(db_path)
            admin = store.create_user("adminA", "secret1")
            normal = store.create_user("userA", "secret2")

            self.assertEqual(admin["role"], "admin")
            self.assertEqual(normal["role"], "user")
            self.assertEqual(store.authenticate("adminA", "secret1")["id"], admin["id"])
            with self.assertRaises(ValueError):
                store.authenticate("adminA", "bad-password")
            token = store.create_session(admin["id"])
            self.assertEqual(store.user_for_session(token)["username"], "adminA")
            store.delete_session(token)
            self.assertIsNone(store.user_for_session(token))
        finally:
            db_path.unlink(missing_ok=True)

    def test_auth_and_user_management_api_use_sqlite_sessions(self):
        original_store = server.USER_STORE
        db_path = WEB_ROOT / "tests" / "tmp_auth_api.sqlite3"
        db_path.unlink(missing_ok=True)
        server.USER_STORE = server.UserStore(db_path)
        try:
            status, headers, body = server.handle_auth_api_path(
                "/api/auth/register",
                "POST",
                json.dumps({"username": "adminA", "password": "secret1"}).encode("utf-8"),
            )
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(data["user"]["role"], "admin")
            self.assertIn("Set-Cookie", headers)
            token = headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]

            status, headers, body = server.handle_auth_api_path("/api/auth/me", "GET", token=token)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body.decode("utf-8"))["user"]["username"], "adminA")

            status, headers, body = server.handle_users_api_path("/api/users", "GET", b"", {"id": 1, "username": "adminA", "role": "admin"})
            self.assertEqual(status, 200)
            self.assertEqual(len(json.loads(body.decode("utf-8"))["users"]), 1)

            status, headers, body = server.handle_users_api_path("/api/users", "GET", b"", {"id": 2, "username": "userA", "role": "user"})
            self.assertEqual(status, 403)
        finally:
            server.USER_STORE = original_store
            db_path.unlink(missing_ok=True)

    def test_optimization_runtime_can_clear_logs(self):
        runtime = server.OptimizationRuntime("测试方案")
        runtime._append_log_unlocked("info", "待清空日志")

        payload = runtime.apply("clear_logs", scheme="测试方案")

        self.assertEqual(payload["logs"], [])
        self.assertEqual(runtime.snapshot()["logs"], [])

    def test_evaluation_runtime_can_clear_logs(self):
        runtime = server.EvaluationRuntime("测试方案")
        runtime.result_filename = "case_results.xlsx"
        runtime._append_log_unlocked("info", "待清空日志")

        payload = runtime.apply("clear_logs", scheme="测试方案", filename="case_results.xlsx")

        self.assertEqual(payload["logs"], [])
        self.assertEqual(runtime.snapshot()["logs"], [])

    def test_api_response_is_json_for_known_endpoint(self):
        status, headers, body = server.handle_api_path("/api/overview")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["system"], "考察站风-光-氢-储-柴联合规划系统")
        self.assertIn("summary", data)
        self.assertNotIn("simu", data)
        self.assertNotIn("scada", data)
        self.assertNotIn("agc", data)

    def test_removed_monitor_api_endpoints_return_not_found(self):
        for path in ("/api/simu", "/api/scada", "/api/agc"):
            status, headers, body = server.handle_api_path(path)
            data = json.loads(body.decode("utf-8"))

            self.assertEqual(status, 404)
            self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
            self.assertEqual(data["error"], "not_found")
            self.assertEqual(data["path"], path)

        status, headers, body = server.handle_control_path(
            "/api/simu/control",
            json.dumps({"action": "start"}).encode("utf-8"),
        )
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 404)
        self.assertEqual(data["error"], "not_found")

    def test_optimization_api_start_stop_and_logs(self):
        original_runtime = server.OPTIMIZATION_RUNTIME
        original_run_optimization = server.OptimizationRuntime._run_optimization
        server.OPTIMIZATION_RUNTIME = server.OptimizationRuntimeManager()
        try:
            server.OptimizationRuntime._run_optimization = lambda self, token, scheme: None
            status, headers, body = server.handle_api_path("/api/optimization/status?scheme=方案A")
            initial = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
            self.assertEqual(initial["status"], "待启动")
            self.assertEqual(initial["scheme"], "方案A")
            self.assertIn("metrics", initial)
            self.assertIn("results", initial)
            self.assertIn("logs", initial)

            status, headers, body = server.handle_control_path(
                "/api/optimization/control",
                json.dumps({"action": "start", "scheme": "方案A"}, ensure_ascii=False).encode("utf-8"),
            )
            started = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(started["state"]["status"], "运行中")
            self.assertEqual(started["state"]["scheme"], "方案A")
            self.assertTrue(started["state"]["start_time"])
            self.assertFalse(started["state"]["end_time"])
            self.assertTrue(any("启动规划求解" in item["message"] for item in started["state"]["logs"]))

            status, headers, body = server.handle_control_path(
                "/api/optimization/control",
                json.dumps({"action": "start", "scheme": "方案A"}, ensure_ascii=False).encode("utf-8"),
            )
            duplicate = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 409)
            self.assertEqual(duplicate["error"], "running")
            self.assertIn("正在运行，无法再次启动", duplicate["message"])

            status, headers, body = server.handle_control_path(
                "/api/optimization/control",
                json.dumps({"action": "start", "scheme": "方案B"}, ensure_ascii=False).encode("utf-8"),
            )
            second_started = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(second_started["state"]["status"], "运行中")
            self.assertEqual(second_started["state"]["scheme"], "方案B")

            status, headers, body = server.handle_api_path("/api/optimization/status?scheme=方案A")
            scheme_a = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(scheme_a["status"], "运行中")
            self.assertEqual(scheme_a["scheme"], "方案A")
            self.assertIn("方案A", scheme_a["running_schemes"])
            self.assertIn("方案B", scheme_a["running_schemes"])

            status, headers, body = server.handle_api_path("/api/optimization/status?scheme=方案B")
            scheme_b = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(scheme_b["status"], "运行中")
            self.assertEqual(scheme_b["scheme"], "方案B")
            self.assertTrue(any("方案：方案A" in item["message"] for item in scheme_a["logs"]))
            self.assertFalse(any("方案：方案B" in item["message"] for item in scheme_a["logs"]))
            self.assertTrue(any("方案：方案B" in item["message"] for item in scheme_b["logs"]))

            status, headers, body = server.handle_control_path(
                "/api/optimization/control",
                json.dumps({"action": "stop", "scheme": "方案A"}, ensure_ascii=False).encode("utf-8"),
            )
            stopped = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(stopped["state"]["status"], "已停止")
            self.assertTrue(stopped["state"]["end_time"])
            self.assertTrue(any("停止规划求解" in item["message"] for item in stopped["state"]["logs"]))

            status, headers, body = server.handle_control_path(
                "/api/optimization/control",
                json.dumps({"action": "stop", "scheme": "方案A"}, ensure_ascii=False).encode("utf-8"),
            )
            not_running = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 409)
            self.assertEqual(not_running["error"], "not_running")
            self.assertIn("没有运行", not_running["message"])

            status, headers, body = server.handle_api_path("/api/optimization/status?scheme=方案B")
            scheme_b_after_a_stop = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(scheme_b_after_a_stop["status"], "运行中")
            self.assertEqual(scheme_b_after_a_stop["scheme"], "方案B")

            status, headers, body = server.handle_control_path(
                "/api/optimization/control",
                json.dumps({"action": "bad"}).encode("utf-8"),
            )
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body.decode("utf-8"))["error"], "bad_request")
        finally:
            server.OPTIMIZATION_RUNTIME = original_runtime
            server.OptimizationRuntime._run_optimization = original_run_optimization

    def test_estimate_dispatch_minimizes_diesel_for_8760_hours(self):
        payload = server.planning_store.default_payload("方案A")
        for index, row in enumerate(payload["time_series"]):
            row["wind_speed"] = 8 if index % 2 == 0 else 0
            row["solar_irradiance"] = 800 if 8 <= index % 24 <= 16 else 0
            row["load"] = 100
            row["temperature"] = 20
        result_rows = [
            {"设备类型": "柴发", "设计台数": 2, "单台容量": 100, "总容量": 200, "单位": "kW"},
            {"设备类型": "风机", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "光伏", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "储能", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kWh"},
        ]
        events = []

        result = estimate.run_estimation(payload, result_rows, log=events.append)

        self.assertEqual(result["status"], "已完成")
        self.assertEqual(result["progress"], 100)
        self.assertEqual(len(result["dispatch_rows"]), 8760)
        self.assertEqual(result["dispatch_rows"][0]["hour_index"], 1)
        self.assertEqual(result["dispatch_rows"][-1]["hour_index"], 8760)
        self.assertLess(result["totals"]["diesel_energy"], result["totals"]["load_energy"])
        self.assertTrue(any("8760点优化调度" in item["message"] for item in events))
        self.assertTrue(any(item.get("progress") == 100 for item in events))

    def test_estimate_dispatch_uses_joint_milp_with_curtailment_and_hydrogen(self):
        payload = server.planning_store.default_payload("方案A")
        for row in payload["time_series"]:
            row["wind_speed"] = 12
            row["solar_irradiance"] = 1000
            row["load"] = 40
            row["temperature"] = 20
        payload["diesel_generators"][0]["capacity"] = 100
        payload["diesel_generators"][0]["power_lower"] = 20
        payload["diesel_generators"][0]["power_upper"] = 100
        result_rows = [
            {"设备类型": "柴发", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "风机", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "光伏", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 50, "总容量": 50, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kWh"},
            {"设备类型": "电制氢", "设计台数": 1, "单台容量": 30, "总容量": 30, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 20, "总容量": 20, "单位": "kW"},
        ]
        events = []

        result = estimate.run_estimation(payload, result_rows, log=events.append)
        first_row = result["dispatch_rows"][0]

        self.assertEqual(result["status"], "已完成")
        self.assertEqual(len(result["dispatch_rows"]), 8760)
        self.assertIn("diesel_on", first_row)
        self.assertIn("hydrogen_production_power", first_row)
        self.assertIn("fuel_cell_power", first_row)
        self.assertIn("hydrogen_storage", first_row)
        self.assertGreater(result["totals"]["curtailed_energy"], 0)
        self.assertEqual(result["totals"]["unmet_load_energy"], 0)
        self.assertTrue(any("混合整数线性优化" in item["message"] for item in events))

    def test_estimate_dispatch_uses_surplus_renewable_hydrogen_to_reduce_later_diesel(self):
        payload = server.planning_store.default_payload("方案A")
        payload["time_series"] = payload["time_series"][:2]
        payload["time_series"][0].update({"wind_speed": 12, "solar_irradiance": 0, "load": 0, "temperature": 20})
        payload["time_series"][1].update({"wind_speed": 0, "solar_irradiance": 0, "load": 40, "temperature": 20})
        payload["diesel_generators"][0].update({"capacity": 100, "power_lower": 0, "power_upper": 100})
        payload["hydrogen_electrolyzers"][0].update(
            {"power_capacity": 100, "power_lower": 0, "electric_to_hydrogen_efficiency": 1}
        )
        payload["fuel_cells"][0].update({"power_capacity": 100, "hydrogen_to_electric_efficiency": 1})
        payload["hydrogen_tanks"][0].update({"hydrogen_tank_capacity": 200, "self_discharge_rate": 0})
        result_rows = [
            {"设备类型": "柴发", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "风机", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "电制氢", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 200, "总容量": 200, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
        ]

        dispatch_rows = estimate.solve_dispatch_model(estimate.build_dispatch_model(payload, result_rows))

        self.assertGreater(dispatch_rows[0]["hydrogen_production_power"], 0)
        self.assertGreater(dispatch_rows[0]["hydrogen_storage"], 100)
        self.assertGreater(dispatch_rows[1]["fuel_cell_power"], 0)
        self.assertLess(dispatch_rows[1]["diesel_power"], 40)

    def test_estimate_dispatch_uses_time_limit_from_planning_parameters(self):
        payload = server.planning_store.default_payload("方案A")
        payload["time_series"] = payload["time_series"][:1]
        payload["planning_parameters"][0]["optimization_time_limit_minutes"] = 45
        result_rows = [
            {"设备类型": "柴发", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "电制氢", "设计台数": 1, "单台容量": 10, "总容量": 10, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 20, "总容量": 20, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 10, "总容量": 10, "单位": "kW"},
        ]
        model = estimate.build_dispatch_model(payload, result_rows)
        seen_options = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            seen_options.update(options)
            return SimpleNamespace(success=True, x=lower_bounds.copy(), fun=0.0, message="ok")

        with patch.object(estimate, "solve_milp", side_effect=fake_solve_milp):
            estimate.solve_dispatch_model(model)

        self.assertEqual(seen_options["time_limit"], 2700)

    def test_estimate_dispatch_enforces_storage_daily_and_hydrogen_annual_cycle(self):
        payload = server.planning_store.default_payload("方案A")
        for row in payload["time_series"]:
            row["wind_speed"] = 12
            row["solar_irradiance"] = 1000
            row["load"] = 40
            row["temperature"] = 20
        payload["diesel_generators"][0]["capacity"] = 100
        payload["diesel_generators"][0]["power_lower"] = 20
        payload["diesel_generators"][0]["power_upper"] = 100
        result_rows = [
            {"设备类型": "柴发", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "风机", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "光伏", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 50, "总容量": 50, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kWh"},
            {"设备类型": "电制氢", "设计台数": 1, "单台容量": 30, "总容量": 30, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 20, "总容量": 20, "单位": "kW"},
        ]

        result = estimate.run_estimation(payload, result_rows)
        dispatch_rows = result["dispatch_rows"]
        model = estimate.build_dispatch_model(payload, result_rows)
        expected_storage_start = model["storage_energy_capacity"] * 0.5
        expected_hydrogen_start = model["hydrogen_tank_capacity"] * 0.5

        for day_end_hour in range(23, 8760, 24):
            self.assertAlmostEqual(dispatch_rows[day_end_hour]["storage_soc"], expected_storage_start, places=3)
        self.assertAlmostEqual(dispatch_rows[-1]["hydrogen_storage"], expected_hydrogen_start, places=3)

    def test_estimate_capacity_mapping_keeps_fuel_cells_out_of_storage_energy(self):
        result_rows = [
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 50, "总容量": 50, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kWh"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 20, "总容量": 20, "单位": "kW"},
        ]

        capacities = estimate.capacities_from_planning_rows(result_rows)

        self.assertEqual(capacities["storage_power_capacity"], 50)
        self.assertEqual(capacities["storage_energy_capacity"], 100)
        self.assertEqual(capacities["fuel_cell_power_capacity"], 20)

    def test_estimate_capacity_mapping_recomputes_total_capacity_from_count_and_unit_capacity(self):
        result_rows = [
            {"设备类型": "电制氢", "设计台数": 1, "单台容量": 80, "总容量": 0, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 1000, "总容量": 0, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 50, "总容量": 0, "单位": "kW"},
            {"设备类型": "柴发", "设计台数": 0, "单台容量": 300, "总容量": 300, "单位": "kW"},
        ]

        capacities = estimate.capacities_from_planning_rows(result_rows)

        self.assertEqual(capacities["electrolyzer_power_capacity"], 80)
        self.assertEqual(capacities["hydrogen_tank_capacity"], 1000)
        self.assertEqual(capacities["fuel_cell_power_capacity"], 50)
        self.assertEqual(capacities["diesel_capacity"], 0)

    def test_estimate_dispatch_uses_unit_binaries_and_initial_storage_ratios(self):
        payload = server.planning_store.default_payload("方案A")
        payload["time_series"] = payload["time_series"][:1]
        payload["time_series"][0]["load"] = 0
        payload["time_series"][0]["wind_speed"] = 0
        payload["time_series"][0]["solar_irradiance"] = 0
        payload["planning_parameters"][0]["initial_storage_soc_ratio"] = 0.2
        payload["planning_parameters"][0]["initial_hydrogen_storage_ratio"] = 0.8
        payload["storage_pcs"][0]["storage_charge_efficiency"] = 0.91
        payload["storage_pcs"][0]["storage_discharge_efficiency"] = 0.89
        payload["planning_parameters"][0]["post_disturbance_power_balance_enabled"] = 1
        payload["diesel_generators"][0]["capacity"] = 100
        payload["diesel_generators"][0]["power_lower"] = 20
        payload["diesel_generators"][0]["power_upper"] = 100
        payload["storage_pcs"][0]["is_grid_forming"] = 1
        payload["storage_battery_packs"][0]["soc_upper"] = 0.8
        payload["storage_battery_packs"][0]["soc_lower"] = 0.2
        payload["hydrogen_electrolyzers"][0]["power_capacity"] = 30
        payload["hydrogen_electrolyzers"][0]["power_lower"] = 5
        result_rows = [
            {"设备类型": "柴发", "设计台数": 2, "单台容量": 100, "总容量": 200, "单位": "kW"},
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 50, "总容量": 50, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kWh"},
            {"设备类型": "电制氢", "设计台数": 2, "单台容量": 30, "总容量": 60, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 20, "总容量": 20, "单位": "kW"},
        ]
        model = estimate.build_dispatch_model(payload, result_rows)
        captured = {}

        def fake_solve_milp(c, integrality, lower_bounds, upper_bounds, constraints, constraint_lower, constraint_upper, options, log, problem_name):
            captured["objective"] = c.copy()
            return SimpleNamespace(success=True, x=lower_bounds.copy(), fun=0.0, message="ok")

        with patch.object(estimate, "solve_milp", side_effect=fake_solve_milp):
            estimate.solve_dispatch_model(model)

        variables = model["variables"]
        objective = captured["objective"]

        def objective_cost(key):
            return objective[variables[key]]

        self.assertEqual(objective_cost(("diesel_power", 0)), 1.0)
        self.assertEqual(objective_cost(("unmet_load", 0)), estimate.LOAD_SHED_PENALTY)
        self.assertEqual(objective_cost(("diesel_on_unit", 0, 0)), estimate.DIESEL_ON_PENALTY)
        self.assertEqual(objective_cost(("electrolyzer_on_unit", 0, 0)), estimate.ELECTROLYZER_ON_PENALTY)
        for key in (
            ("storage_charge", 0),
            ("storage_discharge", 0),
            ("electrolyzer_power", 0),
            ("fuel_cell_power", 0),
            ("curtailed_power", 0),
            ("grid_storage_on_unit", 0, 0),
        ):
            self.assertEqual(objective_cost(key), 0.0)
        for unit in range(2):
            self.assertIn(("diesel_on_unit", 0, unit), variables)
            self.assertIn(("electrolyzer_on_unit", 0, unit), variables)
        self.assertNotIn(("diesel_on", 0), variables)
        self.assertNotIn(("electrolyzer_on", 0), variables)
        self.assertIn(("storage_charge_on", 0), variables)
        self.assertIn(("storage_discharge_on", 0), variables)
        self.assertIn(("grid_storage_on_unit", 0, 0), variables)
        self.assertEqual(model["initial_storage_soc_ratio"], 0.2)
        self.assertEqual(model["initial_hydrogen_storage_ratio"], 0.8)
        self.assertEqual(model["storage_charge_efficiency"], 0.91)
        self.assertEqual(model["storage_discharge_efficiency"], 0.89)
        self.assertTrue(model["post_disturbance_power_balance_enabled"])
        self.assertEqual(model["storage_soc_upper_ratio"], 0.8)
        self.assertEqual(model["storage_soc_lower_ratio"], 0.2)

    def test_pv_generation_uses_capacity_times_irradiance_without_efficiency_parameter(self):
        self.assertAlmostEqual(estimate.pv_generation(500, 100, {"generation_efficiency": 0.1}), 50.0)
        self.assertAlmostEqual(estimate.pv_generation(1200, 100, {}), 100.0)

    def test_wind_generation_uses_configured_rated_wind_speed(self):
        params = {"cut_in_wind_speed": 3, "rated_wind_speed": 9, "cut_out_wind_speed": 25}

        self.assertAlmostEqual(estimate.wind_generation(9, 100, params), 100.0)
        self.assertAlmostEqual(estimate.wind_generation(6, 100, params), 12.5)
        self.assertAlmostEqual(estimate.wind_generation(25, 100, params), 0.0)

    def test_estimate_dispatch_outputs_requested_8760_curve_columns(self):
        payload = server.planning_store.default_payload("方案A")
        for row in payload["time_series"]:
            row["wind_speed"] = 12
            row["solar_irradiance"] = 900
            row["temperature"] = -5
            row["load"] = 60
        result_rows = [
            {"设备类型": "柴发", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "风机", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "光伏", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kW"},
            {"设备类型": "储能PCS", "设计台数": 1, "单台容量": 50, "总容量": 50, "单位": "kW"},
            {"设备类型": "储能电池组", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "kWh"},
            {"设备类型": "电制氢", "设计台数": 1, "单台容量": 30, "总容量": 30, "单位": "kW"},
            {"设备类型": "储氢罐", "设计台数": 1, "单台容量": 100, "总容量": 100, "单位": "Nm3"},
            {"设备类型": "燃料电池", "设计台数": 1, "单台容量": 20, "总容量": 20, "单位": "kW"},
        ]

        result = estimate.run_estimation(payload, result_rows)
        row = result["dispatch_rows"][0]

        for field in (
            "wind_speed",
            "solar_irradiance",
            "temperature",
            "load",
            "diesel_power",
            "wind_available",
            "wind_power",
            "pv_available",
            "pv_power",
            "renewable_available",
            "storage_power",
            "storage_soc",
            "hydrogen_production_power",
            "hydrogen_storage",
            "fuel_cell_power",
            "wind_curtailed_power",
            "pv_curtailed_power",
            "curtailed_power",
            "unmet_load",
            "renewable_ratio",
            "renewable_curtailed_rate",
        ):
            self.assertIn(field, row)
            self.assertIsInstance(row[field], (int, float))
        self.assertAlmostEqual(row["curtailed_power"], row["wind_curtailed_power"] + row["pv_curtailed_power"], places=3)

        requested_energy_fields = (
            "load_energy",
            "diesel_energy",
            "wind_energy",
            "pv_energy",
            "storage_charge_energy",
            "storage_discharge_energy",
            "hydrogen_production_energy",
            "hydrogen_storage_increase",
            "hydrogen_storage_decrease",
            "fuel_cell_energy",
            "wind_available_energy",
            "pv_available_energy",
            "renewable_available_energy",
            "renewable_energy",
            "wind_curtailed_energy",
            "pv_curtailed_energy",
            "curtailed_energy",
            "unmet_load_energy",
            "renewable_ratio",
            "renewable_curtailed_rate",
        )
        daily = result["results"]["curves"]["green_daily"]
        monthly = result["results"]["curves"]["green_monthly"]
        self.assertEqual(len(daily), 365)
        self.assertEqual(len(monthly), 12)
        for field in requested_energy_fields:
            self.assertIn(field, daily[0])
            self.assertIsInstance(daily[0][field], (int, float))
            self.assertIn(field, monthly[0])
            self.assertIsInstance(monthly[0][field], (int, float))

        annual_metric_names = {
            row["指标"]
            for table in result["results"]["overview_tables"]
            if table["title"] == "规划年指标"
            for row in table["rows"]
        }
        green_metric_names = {row["指标"] for row in result["results"]["green_table"]}
        for name in (
            "负荷总电量",
            "柴发总发电量",
            "风机总发电量",
            "光伏总发电量",
            "电储能总储电量",
            "电储能总放电量",
            "电制氢总用电量",
            "氢储总增加量",
            "氢储总消耗量",
            "燃料电池总发电量",
            "风力最大可发电量",
            "光伏最大可发电量",
            "新能源最大可发电量",
            "新能源实发电量",
            "弃风总电量",
            "弃光总电量",
            "新能源总弃电量",
            "切负荷总电量",
            "新能源占比",
            "新能源弃电率",
        ):
            self.assertIn(name, annual_metric_names)
            self.assertIn(name, green_metric_names)

    def test_evaluation_api_uses_independent_runtime_and_estimate_script(self):
        planning_root = WEB_ROOT / "tests" / "tmp_evaluation_runtime"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        original_runtime = server.EVALUATION_RUNTIME
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        server.EVALUATION_RUNTIME = server.EvaluationRuntimeManager()
        try:
            payload = server.planning_store.default_payload("方案A")
            for row in payload["time_series"]:
                row["wind_speed"] = 7
                row["solar_irradiance"] = 500
                row["load"] = 80
            server.PLANNING_STORE.write_scheme("方案A", payload)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "规划结果"
            sheet.append(["设备类型", "设计台数", "单台容量", "总容量", "单位"])
            sheet.append(["柴发", 2, 100, 200, "kW"])
            sheet.append(["风机", 1, 100, 100, "kW"])
            sheet.append(["光伏", 1, 100, 100, "kW"])
            workbook.save(planning_root / "方案A" / "case_results.xlsx")

            status, headers, body = server.handle_api_path("/api/evaluation/status?scheme=方案A")
            initial = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(initial["status"], "待启动")

            status, headers, body = server.handle_control_path(
                "/api/evaluation/control",
                json.dumps(
                    {"action": "start", "scheme": "方案A", "filename": "case_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            started = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(started["state"]["status"], "运行中")
            self.assertEqual(started["state"]["result_filename"], "case_results.xlsx")
            self.assertTrue(any("启动方案评估" in item["message"] for item in started["state"]["logs"]))

            for _ in range(120):
                status, headers, body = server.handle_api_path("/api/evaluation/status?scheme=方案A")
                state = json.loads(body.decode("utf-8"))
                if state["status"] == "已完成":
                    break
                time.sleep(0.05)

            self.assertEqual(state["status"], "已完成")
            self.assertEqual(state["progress"], 100)
            self.assertTrue(any("8760点优化调度完成" in item["message"] for item in state["logs"]))
            self.assertEqual(len(state["results"]["curves"]["green_hourly"]), 8760)
            workbook = load_workbook(planning_root / "方案A" / "case_results.xlsx", read_only=True, data_only=True)
            try:
                self.assertIn("调度结果", workbook.sheetnames)
                self.assertEqual(workbook["调度结果"].max_row, 8761)
                headers = [cell.value for cell in workbook["调度结果"][1]]
                for header in (
                    "风速",
                    "太阳辐射",
                    "环境温度",
                    "负荷总功率",
                    "柴发总功率",
                    "风力最大可发",
                    "风机总功率",
                    "光伏最大可发",
                    "光伏总功率",
                    "新能源最大可发",
                    "电储能总功率",
                    "电储电量",
                    "电制氢总功率",
                    "储氢罐氢储量",
                    "燃料电池总功率",
                    "弃风总功率",
                    "弃光总功率",
                    "新能源弃电总功率",
                    "切负荷功率",
                ):
                    self.assertIn(header, headers)
            finally:
                workbook.close()
        finally:
            server.PLANNING_STORE = original_store
            server.EVALUATION_RUNTIME = original_runtime
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_evaluation_status_is_scoped_by_result_file(self):
        planning_root = WEB_ROOT / "tests" / "tmp_evaluation_result_switch"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        original_runtime = server.EVALUATION_RUNTIME
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        server.EVALUATION_RUNTIME = server.EvaluationRuntimeManager()
        try:
            payload = server.planning_store.default_payload("方案A")
            for row in payload["time_series"]:
                row["wind_speed"] = 7
                row["solar_irradiance"] = 500
                row["load"] = 80
            server.PLANNING_STORE.write_scheme("方案A", payload)

            for filename, diesel_count in (("case_a_results.xlsx", 2), ("case_b_results.xlsx", 3)):
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = "规划结果"
                sheet.append(["设备类型", "设计台数", "单台容量", "总容量", "单位"])
                sheet.append(["柴发", diesel_count, 100, diesel_count * 100, "kW"])
                sheet.append(["风机", 1, 100, 100, "kW"])
                sheet.append(["光伏", 1, 100, 100, "kW"])
                workbook.save(planning_root / "方案A" / filename)

            status, headers, body = server.handle_control_path(
                "/api/evaluation/control",
                json.dumps(
                    {"action": "start", "scheme": "方案A", "filename": "case_a_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            self.assertEqual(status, 200)

            case_a = {}
            for _ in range(200):
                status, headers, body = server.handle_api_path(
                    "/api/evaluation/status?scheme=方案A&filename=case_a_results.xlsx"
                )
                case_a = json.loads(body.decode("utf-8"))
                if case_a["status"] == "已完成":
                    break
                time.sleep(0.05)

            status, headers, body = server.handle_api_path(
                "/api/evaluation/status?scheme=方案A&filename=case_b_results.xlsx"
            )
            case_b = json.loads(body.decode("utf-8"))

            self.assertEqual(case_a["status"], "已完成")
            self.assertEqual(case_a["result_filename"], "case_a_results.xlsx")
            self.assertTrue(any("8760点优化调度完成" in item["message"] for item in case_a["logs"]))
            self.assertEqual(len(case_a["results"]["curves"]["green_hourly"]), 8760)
            self.assertEqual(case_b["status"], "待启动")
            self.assertEqual(case_b["result_filename"], "case_b_results.xlsx")
            self.assertFalse(any("8760点优化调度完成" in item["message"] for item in case_b["logs"]))
            self.assertEqual(case_b["results"]["curves"]["green_hourly"], [])
        finally:
            server.PLANNING_STORE = original_store
            server.EVALUATION_RUNTIME = original_runtime
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_optimization_overview_results_are_two_tables_with_composition_bars(self):
        planning_root = WEB_ROOT / "tests" / "tmp_optimization_overview"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            server.PLANNING_STORE.create_scheme("caseA")
            runtime = server.OptimizationRuntime()
            runtime.apply("start", scheme="caseA")
            payload = self.wait_optimization_runtime(runtime)

            self.assertEqual(payload["status"], "已完成")
            tables = payload["results"]["overview_tables"]
            self.assertEqual([table["title"] for table in tables], ["规划结果", "规划年指标"])
            self.assertEqual(len(tables), 2)
            self.assertTrue(any(row["设备类型"] == "柴发" and "设计台数" in row for row in tables[0]["rows"]))
            self.assertTrue(any(row["设备类型"] == "储能电池组" and "设计台数" in row for row in tables[0]["rows"]))
            annual_metric_names = {row["指标"] for row in tables[1]["rows"]}
            for name in (
                "柴发总容量",
                "风电总容量",
                "光伏总容量",
                "氢能总容量",
                "储能总容量",
                "负荷总电量",
                "柴发总发电量",
                "风机总发电量",
                "光伏总发电量",
                "风力最大可发电量",
                "光伏最大可发电量",
                "新能源最大可发电量",
                "新能源实发电量",
                "弃风总电量",
                "弃光总电量",
                "新能源总弃电量",
                "切负荷总电量",
                "新能源占比",
                "新能源弃电率",
                "年均建设成本",
                "年柴油成本",
                "年总成本",
                "总成本",
                "绿电占比",
                "频率风险点",
            ):
                self.assertIn(name, annual_metric_names)
            self.assertNotIn("规划年效益", [table["title"] for table in tables])

            disks = payload["results"]["overview_disks"]
            self.assertEqual([disk["title"] for disk in disks], ["成本构成", "电量构成"])
            self.assertEqual(disks[0]["left_label"], "年柴油成本")
            self.assertEqual(disks[0]["right_label"], "年均建设成本")
            self.assertEqual(disks[1]["left_label"], "柴发电量")
            self.assertEqual(disks[1]["right_label"], "绿电电量")
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_optimization_green_result_has_summary_table_and_daily_curve(self):
        planning_root = WEB_ROOT / "tests" / "tmp_optimization_green"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            server.PLANNING_STORE.create_scheme("caseA")
            runtime = server.OptimizationRuntime()
            runtime.apply("start", scheme="caseA")
            payload = self.wait_optimization_runtime(runtime)

            self.assertEqual(payload["status"], "已完成")
            green_rows = payload["results"]["green_table"]
            metric_names = {row["指标"] for row in green_rows}
            for name in (
                "负荷总电量",
                "柴发总电量",
                "风机总发电量",
                "光伏总发电量",
                "电储总发电量",
                "氢储总发电量",
                "新能源总弃电量",
                "柴油消耗",
                "制氢总量",
                "电储能总储电量",
                "电储能总放电量",
                "电制氢总用电量",
                "氢储总增加量",
                "氢储总消耗量",
                "燃料电池总发电量",
                "风力最大可发电量",
                "光伏最大可发电量",
                "新能源最大可发电量",
                "新能源实发电量",
                "弃风总电量",
                "弃光总电量",
                "新能源总弃电量",
                "切负荷总电量",
                "新能源占比",
                "新能源弃电率",
            ):
                self.assertIn(name, metric_names)
            self.assertTrue(all(set(row) == {"指标", "数值", "单位"} for row in green_rows))
            units = {row["指标"]: row["单位"] for row in green_rows}
            self.assertEqual(units["负荷总电量"], "kWh")
            self.assertEqual(units["柴发总电量"], "kWh")
            self.assertEqual(units["风机总发电量"], "kWh")
            self.assertEqual(units["光伏总发电量"], "kWh")
            self.assertEqual(units["电储总发电量"], "kWh")
            self.assertEqual(units["氢储总发电量"], "kWh")
            self.assertEqual(units["新能源总弃电量"], "kWh")
            self.assertEqual(units["新能源占比"], "%")
            self.assertEqual(units["新能源弃电率"], "%")
            self.assertEqual(units["风力最大可发电量"], "kWh")
            self.assertEqual(units["光伏最大可发电量"], "kWh")
            self.assertEqual(units["新能源最大可发电量"], "kWh")
            self.assertEqual(units["新能源实发电量"], "kWh")
            self.assertEqual(units["弃风总电量"], "kWh")
            self.assertEqual(units["弃光总电量"], "kWh")
            self.assertEqual(units["切负荷总电量"], "kWh")
            self.assertEqual(units["柴油消耗"], "吨")
            self.assertEqual(units["制氢总量"], "Nm3")

            daily = payload["results"]["curves"]["green_daily"]
            self.assertEqual(len(daily), 365)
            self.assertEqual(daily[0]["day"], 1)
            self.assertEqual(daily[-1]["day"], 365)
            for field in (
                "load_energy",
                "diesel_energy",
                "wind_energy",
                "pv_energy",
                "storage_charge_energy",
                "storage_discharge_energy",
                "hydrogen_production_energy",
                "hydrogen_storage_increase",
                "hydrogen_storage_decrease",
                "fuel_cell_energy",
                "wind_available_energy",
                "pv_available_energy",
                "renewable_available_energy",
                "renewable_energy",
                "wind_curtailed_energy",
                "pv_curtailed_energy",
                "curtailed_energy",
                "unmet_load_energy",
                "renewable_ratio",
                "renewable_curtailed_rate",
            ):
                self.assertIn(field, daily[0])
                self.assertIsInstance(daily[0][field], (int, float))

            monthly = payload["results"]["curves"]["green_monthly"]
            self.assertEqual(len(monthly), 12)
            self.assertEqual(monthly[0]["month"], 1)
            self.assertEqual(monthly[-1]["month"], 12)
            for field in (
                "load_energy",
                "diesel_energy",
                "wind_energy",
                "pv_energy",
                "storage_charge_energy",
                "storage_discharge_energy",
                "hydrogen_production_energy",
                "hydrogen_storage_increase",
                "hydrogen_storage_decrease",
                "fuel_cell_energy",
                "wind_available_energy",
                "pv_available_energy",
                "renewable_available_energy",
                "renewable_energy",
                "wind_curtailed_energy",
                "pv_curtailed_energy",
                "curtailed_energy",
                "unmet_load_energy",
                "renewable_ratio",
                "renewable_curtailed_rate",
            ):
                self.assertIn(field, monthly[0])
                self.assertIsInstance(monthly[0][field], (int, float))

            hourly = payload["results"]["curves"]["green_hourly"]
            self.assertEqual(len(hourly), 8760)
            self.assertEqual(hourly[0]["hour_index"], 1)
            self.assertEqual(hourly[-1]["hour_index"], 8760)
            for field in (
                "load",
                "wind_power",
                "pv_power",
                "storage_charge",
                "storage_discharge",
                "diesel_power",
                "curtailed_power",
                "unmet_load",
                "storage_soc",
            ):
                self.assertIn(field, hourly[0])
                self.assertIsInstance(hourly[0][field], (int, float))
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_optimization_safety_result_has_summary_table_and_daily_frequency_curve(self):
        planning_root = WEB_ROOT / "tests" / "tmp_optimization_safety"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            server.PLANNING_STORE.create_scheme("caseA")
            runtime = server.OptimizationRuntime()
            runtime.apply("start", scheme="caseA")
            payload = self.wait_optimization_runtime(runtime)

            self.assertEqual(payload["status"], "已完成")
            safety_rows = payload["results"]["safety_table"]
            metric_names = {row["指标"] for row in safety_rows}
            for name in (
                "向上扰动最大量",
                "向下扰动最大量",
                "最高频率",
                "最低频率",
                "频率安全风险小时数",
            ):
                self.assertIn(name, metric_names)
            units = {row["指标"]: row["单位"] for row in safety_rows}
            self.assertEqual(units["向上扰动最大量"], "kW")
            self.assertEqual(units["向下扰动最大量"], "kW")
            self.assertEqual(units["最高频率"], "Hz")
            self.assertEqual(units["最低频率"], "Hz")
            self.assertEqual(units["频率安全风险小时数"], "h")

            daily = payload["results"]["curves"]["safety_daily"]
            self.assertEqual(len(daily), 365)
            self.assertEqual(daily[0]["day"], 1)
            self.assertEqual(daily[-1]["day"], 365)
            self.assertGreaterEqual(daily[0]["frequency_max"], 50)
            self.assertLessEqual(daily[0]["frequency_min"], 50)
            for field in ("frequency_max", "frequency_min"):
                self.assertIn(field, daily[0])
                self.assertIsInstance(daily[0][field], (int, float))
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_completed_optimization_writes_result_workbook_and_overwrites_existing_file(self):
        planning_root = WEB_ROOT / "tests" / "tmp_optimization_results"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            server.PLANNING_STORE.create_scheme("方案A")
            result_path = planning_root / "方案A" / "optimization_results.xlsx"
            result_path.write_text("old result", encoding="utf-8")

            runtime = server.OptimizationRuntime()
            runtime.apply("start", scheme="方案A")
            payload = self.wait_optimization_runtime(runtime)

            self.assertEqual(payload["status"], "已完成")
            self.assertEqual(payload["result_file"], str(result_path))
            self.assertTrue(result_path.exists())
            workbook = load_workbook(result_path, data_only=True, read_only=True)
            try:
                self.assertEqual(
                    workbook.sheetnames,
                    ["总体指标", "规划结果", "规划年指标", "供能分析", "供能日曲线", "供能月曲线", "安全评估", "安全日曲线", "调度结果", "运行日志"],
                )
                self.assertEqual(workbook["总体指标"]["A1"].value, "指标")
                self.assertEqual(workbook["总体指标"]["B1"].value, "数值")
                self.assertEqual(workbook["规划结果"]["A1"].value, "设备类型")
                self.assertEqual(workbook["规划结果"]["A2"].value, "柴发")
                self.assertEqual(workbook["供能日曲线"].max_row, 366)
                self.assertIn("供能月曲线", workbook.sheetnames)
                self.assertEqual(workbook["供能月曲线"].max_row, 13)
                self.assertEqual(workbook["安全日曲线"].max_row, 366)
                self.assertEqual(workbook["调度结果"].max_row, 8761)
                self.assertEqual(workbook["调度结果"]["A1"].value, "小时")
                self.assertEqual(workbook["调度结果"]["C1"].value, "风速")
                self.assertEqual(workbook["调度结果"]["F1"].value, "负荷总功率")
                self.assertEqual(workbook["调度结果"]["L1"].value, "新能源最大可发")
                hourly_headers = [cell.value for cell in workbook["调度结果"][1]]
                self.assertIn("新能源占比", hourly_headers)
                self.assertIn("新能源弃电率", hourly_headers)
                self.assertEqual(workbook["运行日志"]["A1"].value, "时间")
                log_messages = [row[2] for row in workbook["运行日志"].iter_rows(min_row=2, values_only=True)]
                self.assertIn("规划求解完成", log_messages)
            finally:
                workbook.close()
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_optimization_status_reads_display_results_from_result_workbook(self):
        planning_root = WEB_ROOT / "tests" / "tmp_optimization_status_workbook"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        original_runtime = server.OPTIMIZATION_RUNTIME
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        server.OPTIMIZATION_RUNTIME = server.OptimizationRuntimeManager()
        try:
            server.PLANNING_STORE.create_scheme("方案A")
            result_path = planning_root / "方案A" / "optimization_results.xlsx"
            workbook = Workbook()
            workbook.active.title = "总体指标"
            workbook.active.append(["指标", "数值", "单位"])
            workbook.active.append(["度电成本", 9.99, "元/kWh"])
            planning_sheet = workbook.create_sheet("规划结果")
            planning_sheet.append(["设备类型", "设计台数", "单台容量", "总容量", "单位"])
            planning_sheet.append(["工作簿柴发", 3, 111, 333, "kW"])
            annual_sheet = workbook.create_sheet("规划年指标")
            annual_sheet.append(["指标", "数值", "单位"])
            annual_sheet.append(["工作簿年指标", 1234, "kWh"])
            green_sheet = workbook.create_sheet("供能分析")
            green_sheet.append(["指标", "数值", "单位"])
            green_sheet.append(["工作簿供能指标", 5678, "kWh"])
            daily_sheet = workbook.create_sheet("供能日曲线")
            daily_sheet.append(["day", "load_energy", "diesel_energy"])
            daily_sheet.append([1, 10, 2])
            monthly_sheet = workbook.create_sheet("供能月曲线")
            monthly_sheet.append(["month", "load_energy", "diesel_energy"])
            monthly_sheet.append([1, 310, 62])
            safety_sheet = workbook.create_sheet("安全评估")
            safety_sheet.append(["指标", "数值", "单位"])
            safety_sheet.append(["工作簿安全指标", 50.1, "Hz"])
            safety_daily_sheet = workbook.create_sheet("安全日曲线")
            safety_daily_sheet.append(["day", "frequency_max", "frequency_min"])
            safety_daily_sheet.append([1, 50.2, 49.8])
            dispatch_sheet = workbook.create_sheet("调度结果")
            dispatch_sheet.append(["小时", "负荷总功率", "柴发总功率"])
            dispatch_sheet.append([1, 100, 30])
            workbook.save(result_path)
            workbook.close()

            status, headers, body = server.handle_api_path("/api/optimization/status?scheme=方案A")
            payload = json.loads(body.decode("utf-8"))

            self.assertEqual(status, 200)
            self.assertEqual(payload["result_file"], str(result_path))
            self.assertEqual(payload["metrics"][3], {"label": "度电成本", "value": 9.99, "unit": "元/kWh"})
            self.assertEqual(payload["results"]["overview_tables"][0]["rows"][0]["设备类型"], "工作簿柴发")
            self.assertEqual(payload["results"]["overview_tables"][1]["rows"][0]["指标"], "工作簿年指标")
            self.assertEqual(payload["results"]["green_table"][0]["指标"], "工作簿供能指标")
            self.assertEqual(payload["results"]["safety_table"][0]["指标"], "工作簿安全指标")
            self.assertEqual(payload["results"]["curves"]["green_daily"][0]["load_energy"], 10)
            self.assertEqual(payload["results"]["curves"]["green_monthly"][0]["load_energy"], 310)
            self.assertEqual(payload["results"]["curves"]["safety_daily"][0]["frequency_max"], 50.2)
            self.assertEqual(payload["results"]["curves"]["green_hourly"][0]["load"], 100)
        finally:
            server.PLANNING_STORE = original_store
            server.OPTIMIZATION_RUNTIME = original_runtime
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_evaluation_status_reads_display_results_from_selected_workbook(self):
        planning_root = WEB_ROOT / "tests" / "tmp_evaluation_status_workbook"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        original_runtime = server.EVALUATION_RUNTIME
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        server.EVALUATION_RUNTIME = server.EvaluationRuntimeManager()
        try:
            server.PLANNING_STORE.create_scheme("方案A")
            result_path = planning_root / "方案A" / "case_results.xlsx"
            workbook = Workbook()
            workbook.active.title = "总体指标"
            workbook.active.append(["指标", "数值", "单位"])
            workbook.active.append(["柴油消耗", 8.8, "吨"])
            planning_sheet = workbook.create_sheet("规划结果")
            planning_sheet.append(["设备类型", "设计台数", "单台容量", "总容量", "单位"])
            planning_sheet.append(["评估柴发", 1, 200, 200, "kW"])
            annual_sheet = workbook.create_sheet("规划年指标")
            annual_sheet.append(["指标", "数值", "单位"])
            annual_sheet.append(["评估年指标", 12, "kWh"])
            green_sheet = workbook.create_sheet("供能分析")
            green_sheet.append(["指标", "数值", "单位"])
            green_sheet.append(["评估供能指标", 34, "kWh"])
            daily_sheet = workbook.create_sheet("供能日曲线")
            daily_sheet.append(["day", "load_energy", "diesel_energy"])
            daily_sheet.append([1, 56, 7])
            safety_sheet = workbook.create_sheet("安全评估")
            safety_sheet.append(["指标", "数值", "单位"])
            safety_sheet.append(["评估安全指标", 49.9, "Hz"])
            safety_daily_sheet = workbook.create_sheet("安全日曲线")
            safety_daily_sheet.append(["day", "frequency_max", "frequency_min"])
            safety_daily_sheet.append([1, 50.1, 49.9])
            workbook.save(result_path)
            workbook.close()

            status, headers, body = server.handle_api_path("/api/evaluation/status?scheme=方案A&filename=case_results.xlsx")
            payload = json.loads(body.decode("utf-8"))

            self.assertEqual(status, 200)
            self.assertEqual(payload["result_filename"], "case_results.xlsx")
            self.assertEqual(payload["result_file"], str(result_path))
            self.assertEqual(payload["metrics"][3], {"label": "柴油消耗", "value": 8.8, "unit": "吨"})
            self.assertEqual(payload["results"]["overview_tables"][0]["rows"][0]["设备类型"], "评估柴发")
            self.assertEqual(payload["results"]["overview_tables"][1]["rows"][0]["指标"], "评估年指标")
            self.assertEqual(payload["results"]["green_table"][0]["指标"], "评估供能指标")
            self.assertEqual(payload["results"]["safety_table"][0]["指标"], "评估安全指标")
            self.assertEqual(payload["results"]["curves"]["green_daily"][0]["load_energy"], 56)
            self.assertEqual(payload["results"]["curves"]["safety_daily"][0]["frequency_min"], 49.9)
        finally:
            server.PLANNING_STORE = original_store
            server.EVALUATION_RUNTIME = original_runtime
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_evaluation_results_api_manages_scheme_result_workbooks(self):
        planning_root = WEB_ROOT / "tests" / "tmp_evaluation_results"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        original_runtime = server.OPTIMIZATION_RUNTIME
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        server.OPTIMIZATION_RUNTIME = server.OptimizationRuntimeManager()
        try:
            server.PLANNING_STORE.create_scheme("方案A")

            status, headers, body = server.handle_api_path("/api/evaluation/results?scheme=方案A")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body.decode("utf-8"))["results"], [])

            source_path = planning_root / "方案A" / "optimization_results.xlsx"
            create_workbook = Workbook()
            create_workbook.active.title = "总体指标"
            create_workbook.active.append(["指标", "数值"])
            planning_sheet = create_workbook.create_sheet("规划结果")
            planning_sheet.append(["设备类型", "设计台数", "单台容量", "总容量", "单位"])
            planning_sheet.append(["柴发", 2, 320, 640, "kW"])
            planning_sheet.append(["储能", 4, 250, 1000, "kWh"])
            planning_sheet.append(["电制氢", 1, 80, 0, "kW"])
            planning_sheet.append(["燃料电池", 0, 50, 50, "kW"])
            create_workbook.save(source_path)

            broken_path = planning_root / "方案A" / "aaa_results.xlsx"
            broken_path.write_bytes(b"not a valid workbook")
            dead_path = planning_root / "方案A" / "dead_results.xlsx"
            dead_path.write_bytes(b"dead workbook")

            status, headers, body = server.handle_api_path(
                "/api/evaluation/results?scheme=方案A"
            )
            listed = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(listed["selected"], "optimization_results.xlsx")
            broken_item = next(item for item in listed["results"] if item["name"] == "aaa_results.xlsx")
            self.assertFalse(broken_item["readable"])
            self.assertIn("结果文件无法读取", broken_item["message"])
            self.assertEqual(
                listed["planning_result_rows"],
                [
                    {"设备类型": "柴发", "设计台数": 2, "单台容量": 320, "总容量": 640, "单位": "kW"},
                    {"设备类型": "储能", "设计台数": 4, "单台容量": 250, "总容量": 1000, "单位": "kWh"},
                    {"设备类型": "电制氢", "设计台数": 1, "单台容量": 80, "总容量": 80, "单位": "kW"},
                    {"设备类型": "燃料电池", "设计台数": 0, "单台容量": 50, "总容量": 0, "单位": "kW"},
                ],
            )

            status, headers, body = server.handle_api_path(
                "/api/evaluation/results?scheme=方案A&filename=aaa_results.xlsx"
            )
            selected_broken = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(selected_broken["selected"], "aaa_results.xlsx")
            self.assertEqual(selected_broken["planning_result_rows"], [])

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {
                        "scheme": "方案A",
                        "action": "copy",
                        "filename": "optimization_results.xlsx",
                        "target_name": "custom",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            copied = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(copied["selected"], "custom_results.xlsx")
            self.assertTrue((planning_root / "方案A" / "custom_results.xlsx").exists())

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {
                        "scheme": "方案A",
                        "action": "copy",
                        "filename": "optimization_results.xlsx",
                        "target_name": "custom",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            duplicate = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 409)
            self.assertEqual(duplicate["error"], "exists")
            self.assertIn("复制失败", duplicate["message"])

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {
                        "scheme": "方案A",
                        "action": "copy",
                        "filename": "optimization_results.xlsx",
                        "target_name": "aaa",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            overwritten = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(overwritten["selected"], "aaa_results.xlsx")
            overwritten_item = next(item for item in overwritten["results"] if item["name"] == "aaa_results.xlsx")
            self.assertTrue(overwritten_item["readable"])
            workbook = load_workbook(planning_root / "方案A" / "aaa_results.xlsx", read_only=True)
            try:
                self.assertIn("规划结果", workbook.sheetnames)
            finally:
                workbook.close()

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {"scheme": "方案A", "action": "delete", "filename": "dead_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            deleted_broken = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertFalse(dead_path.exists())
            self.assertNotIn("dead_results.xlsx", [item["name"] for item in deleted_broken["results"]])

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {"scheme": "方案A", "action": "delete", "filename": "optimization_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            protected_delete = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 400)
            self.assertEqual(protected_delete["error"], "bad_request")
            self.assertIn("默认结果文件不允许删除", protected_delete["message"])
            self.assertTrue((planning_root / "方案A" / "optimization_results.xlsx").exists())

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {"scheme": "方案A", "action": "save", "filename": "optimization_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            protected_save = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 400)
            self.assertEqual(protected_save["error"], "bad_request")
            self.assertIn("默认结果文件不允许修改", protected_save["message"])

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {"scheme": "方案A", "action": "save", "filename": "custom_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            saved = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(saved["selected"], "custom_results.xlsx")
            workbook = load_workbook(planning_root / "方案A" / "custom_results.xlsx", read_only=True)
            try:
                self.assertIn("总体指标", workbook.sheetnames)
                self.assertIn("规划结果", workbook.sheetnames)
            finally:
                workbook.close()

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {
                        "scheme": "方案A",
                        "action": "save",
                        "filename": "custom_results.xlsx",
                        "planning_result_rows": [
                            {"设备类型": "柴发", "设计台数": 5},
                            {"设备类型": "储能", "设计台数": 7},
                        ],
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            saved_with_counts = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(saved_with_counts["selected"], "custom_results.xlsx")
            saved_counts = {row["设备类型"]: row["设计台数"] for row in saved_with_counts["planning_result_rows"]}
            saved_totals = {row["设备类型"]: row["总容量"] for row in saved_with_counts["planning_result_rows"]}
            self.assertEqual(saved_counts["柴发"], 5)
            self.assertEqual(saved_counts["储能"], 7)
            self.assertEqual(saved_totals["柴发"], 1600)
            self.assertEqual(saved_totals["储能"], 1750)
            workbook = load_workbook(planning_root / "方案A" / "custom_results.xlsx", read_only=True)
            try:
                workbook_counts = {
                    row[0]: row[1]
                    for row in workbook["规划结果"].iter_rows(min_row=2, values_only=True)
                    if row and row[0]
                }
                workbook_totals = {
                    row[0]: row[3]
                    for row in workbook["规划结果"].iter_rows(min_row=2, values_only=True)
                    if row and row[0]
                }
                self.assertEqual(workbook_counts["柴发"], 5)
                self.assertEqual(workbook_counts["储能"], 7)
                self.assertEqual(workbook_totals["柴发"], 1600)
                self.assertEqual(workbook_totals["储能"], 1750)
            finally:
                workbook.close()

            result_path_for_retry = planning_root / "方案A" / "custom_results.xlsx"
            replace_calls = {"count": 0}
            original_replace = Path.replace

            def flaky_replace(self, target):
                if Path(self).name == f".{result_path_for_retry.name}.tmp":
                    replace_calls["count"] += 1
                    if replace_calls["count"] == 1:
                        raise PermissionError("simulated workbook lock")
                return original_replace(self, target)

            with patch.object(Path, "replace", new=flaky_replace):
                status, headers, body = server.handle_evaluation_results_api_path(
                    "/api/evaluation/results",
                    "POST",
                    json.dumps(
                        {
                            "scheme": "方案A",
                            "action": "save",
                            "filename": "custom_results.xlsx",
                            "planning_result_rows": [{"设备类型": "柴发", "设计台数": 6}],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            retried_save = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(retried_save["selected"], "custom_results.xlsx")
            self.assertGreaterEqual(replace_calls["count"], 2)
            retried_counts = {row["设备类型"]: row["设计台数"] for row in retried_save["planning_result_rows"]}
            self.assertEqual(retried_counts["柴发"], 6)

            def always_locked_replace(self, target):
                if Path(self).name == f".{result_path_for_retry.name}.tmp":
                    raise PermissionError("still locked")
                return original_replace(self, target)

            with patch.object(Path, "replace", new=always_locked_replace), patch.object(server.file_ops.time, "sleep", return_value=None):
                status, headers, body = server.handle_evaluation_results_api_path(
                    "/api/evaluation/results",
                    "POST",
                    json.dumps(
                        {
                            "scheme": "方案A",
                            "action": "save",
                            "filename": "custom_results.xlsx",
                            "planning_result_rows": [{"设备类型": "柴发", "设计台数": 6}],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            locked = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 409)
            self.assertEqual(locked["error"], "file_locked")
            self.assertIn("结果文件被占用", locked["message"])
            self.assertIn("请关闭", locked["message"])

            original_copy2 = server.file_ops.shutil.copy2
            copy_calls = {"count": 0}

            def flaky_copy2(source, target):
                if Path(target).name == "copyretry_results.xlsx":
                    copy_calls["count"] += 1
                    if copy_calls["count"] == 1:
                        raise PermissionError("simulated copy lock")
                return original_copy2(source, target)

            with patch.object(server.file_ops.shutil, "copy2", side_effect=flaky_copy2):
                status, headers, body = server.handle_evaluation_results_api_path(
                    "/api/evaluation/results",
                    "POST",
                    json.dumps(
                        {
                            "scheme": "方案A",
                            "action": "copy",
                            "filename": "custom_results.xlsx",
                            "target_name": "copyretry",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            retried_copy = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(retried_copy["selected"], "copyretry_results.xlsx")
            self.assertGreaterEqual(copy_calls["count"], 2)

            def always_locked_copy2(source, target):
                if Path(target).name == "copylocked_results.xlsx":
                    raise PermissionError("copy target locked")
                return original_copy2(source, target)

            with patch.object(server.file_ops.shutil, "copy2", side_effect=always_locked_copy2), patch.object(server.file_ops.time, "sleep", return_value=None):
                status, headers, body = server.handle_evaluation_results_api_path(
                    "/api/evaluation/results",
                    "POST",
                    json.dumps(
                        {
                            "scheme": "方案A",
                            "action": "copy",
                            "filename": "custom_results.xlsx",
                            "target_name": "copylocked",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            locked_copy = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 409)
            self.assertEqual(locked_copy["error"], "file_locked")
            self.assertIn("结果文件被占用", locked_copy["message"])
            self.assertIn("无法复制", locked_copy["message"])

            original_unlink = Path.unlink
            unlink_calls = {"count": 0}

            def flaky_unlink(self, *args, **kwargs):
                if Path(self).name == "copyretry_results.xlsx":
                    unlink_calls["count"] += 1
                    if unlink_calls["count"] == 1:
                        raise PermissionError("simulated delete lock")
                return original_unlink(self, *args, **kwargs)

            with patch.object(Path, "unlink", new=flaky_unlink):
                status, headers, body = server.handle_evaluation_results_api_path(
                    "/api/evaluation/results",
                    "POST",
                    json.dumps(
                        {"scheme": "方案A", "action": "delete", "filename": "copyretry_results.xlsx"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            retried_delete = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertGreaterEqual(unlink_calls["count"], 2)
            self.assertNotIn("copyretry_results.xlsx", [item["name"] for item in retried_delete["results"]])

            for invalid_count in (-1, 1.5, "2.2"):
                status, headers, body = server.handle_evaluation_results_api_path(
                    "/api/evaluation/results",
                    "POST",
                    json.dumps(
                        {
                            "scheme": "方案A",
                            "action": "save",
                            "filename": "custom_results.xlsx",
                            "planning_result_rows": [{"设备类型": "柴发", "设计台数": invalid_count}],
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
                invalid = json.loads(body.decode("utf-8"))
                self.assertEqual(status, 400)
                self.assertEqual(invalid["error"], "bad_request")
                self.assertIn("设计台数必须为非负整数", invalid["message"])

            status, headers, body = server.handle_evaluation_results_api_path(
                "/api/evaluation/results",
                "POST",
                json.dumps(
                    {"scheme": "方案A", "action": "delete", "filename": "custom_results.xlsx"},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            deleted = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertFalse((planning_root / "方案A" / "custom_results.xlsx").exists())
            self.assertEqual([item["name"] for item in deleted["results"]], ["aaa_results.xlsx", "optimization_results.xlsx"])
            self.assertEqual(deleted["selected"], "aaa_results.xlsx")
        finally:
            server.PLANNING_STORE = original_store
            server.OPTIMIZATION_RUNTIME = original_runtime
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_comparison_data_api_reads_selected_result_workbooks(self):
        planning_root = WEB_ROOT / "tests" / "tmp_comparison_data"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            server.PLANNING_STORE.create_scheme("方案A")
            result_path = planning_root / "方案A" / "case_results.xlsx"
            workbook = Workbook()
            planning_sheet = workbook.active
            planning_sheet.title = "规划结果"
            planning_sheet.append(["设备类型", "设计台数", "单台容量", "总容量", "单位"])
            planning_sheet.append(["柴发", 2, 100, 200, "kW"])
            planning_sheet.append(["风机", 1, 50, 50, "kW"])
            green_sheet = workbook.create_sheet("供能分析")
            green_sheet.append(["指标", "数值", "单位"])
            green_sheet.append(["柴油消耗", 12.5, "吨"])
            green_sheet.append(["绿电占比", 85, "%"])
            annual_sheet = workbook.create_sheet("规划年指标")
            annual_sheet.append(["指标", "数值", "单位"])
            annual_sheet.append(["年总成本", 123.4, "万元"])
            annual_sheet.append(["新能源弃电率", 1.2, "%"])
            safety_sheet = workbook.create_sheet("安全评估")
            safety_sheet.append(["指标", "数值", "单位"])
            safety_sheet.append(["最大未供负荷", 0, "kW"])
            daily_sheet = workbook.create_sheet("供能日曲线")
            daily_sheet.append(["day", "load_energy", "wind_energy"])
            daily_sheet.append([1, 1000, 220])
            daily_sheet.append([2, 1100, 240])
            monthly_sheet = workbook.create_sheet("供能月曲线")
            monthly_sheet.append(["month", "load_energy", "renewable_curtailed_rate"])
            monthly_sheet.append([1, 30000, 1.1])
            monthly_sheet.append([2, 28000, 1.4])
            dispatch_sheet = workbook.create_sheet("调度结果")
            dispatch_sheet.append(["小时", "时间", "负荷", "风电出力", "光伏出力"])
            for hour in range(1, 8761):
                dispatch_sheet.append([hour, f"H{hour:04d}", 80 + hour % 3, 20 + hour % 5, 30 + hour % 7])
            workbook.save(result_path)

            status, headers, body = server.handle_api_path(
                "/api/comparison/data?items="
                + quote(json.dumps([{"scheme": "方案A", "filename": "case_results.xlsx"}], ensure_ascii=False))
            )
            payload = json.loads(body.decode("utf-8"))

            self.assertEqual(status, 200)
            self.assertEqual(payload["items"][0]["scheme"], "方案A")
            self.assertEqual(payload["items"][0]["result_display_name"], "case")
            self.assertEqual(payload["tables"]["capacity"][0]["设备类型"], "柴发")
            self.assertEqual(payload["tables"]["energy"][0]["指标"], "柴油消耗")
            self.assertEqual(payload["tables"]["safety"][0]["指标"], "最大未供负荷")
            self.assertIn("负荷", payload["curves"])
            self.assertIn("风电出力", payload["curves"])
            self.assertEqual(len(payload["series"]["负荷"][0]["points"]), 8760)
            self.assertEqual(payload["series"]["负荷"][0]["label"], "方案A / case")
            self.assertEqual(payload["curve_groups"]["hourly"]["title"], "小时级曲线")
            self.assertEqual(payload["curve_groups"]["daily"]["title"], "日级统计")
            self.assertEqual(payload["curve_groups"]["monthly"]["title"], "月度统计")
            self.assertIn("负荷", payload["curve_groups"]["hourly"]["curves"])
            self.assertIn("负荷总电量", payload["curve_groups"]["daily"]["curves"])
            self.assertIn("风机总发电量", payload["curve_groups"]["daily"]["curves"])
            self.assertIn("新能源弃电率", payload["curve_groups"]["monthly"]["curves"])
            self.assertNotIn("load_energy", payload["curve_groups"]["daily"]["curves"])
            self.assertNotIn("renewable_curtailed_rate", payload["curve_groups"]["monthly"]["curves"])
            self.assertEqual(len(payload["curve_groups"]["daily"]["series"]["负荷总电量"][0]["points"]), 2)
            self.assertEqual(len(payload["curve_groups"]["monthly"]["series"]["负荷总电量"][0]["points"]), 2)
            self.assertEqual(payload["annual_table"][0]["指标"], "年总成本")
            self.assertEqual(payload["annual_table"][0]["方案A / case"], 123.4)
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_snapshot_reads_summary_from_csv_files(self):
        payload = server.build_snapshot(force_reload=True)

        self.assertEqual(payload["system"], "考察站风-光-氢-储-柴联合规划系统")
        self.assertIn("summary", payload)
        self.assertNotIn("simu", payload)
        self.assertNotIn("scada", payload)
        self.assertNotIn("agc", payload)

    def test_snapshot_reloads_after_configured_interval(self):
        data_dir = WEB_ROOT / "tests" / "tmp_data_source"
        if data_dir.exists():
            shutil.rmtree(data_dir)
        data_dir.mkdir(parents=True)
        try:
            (data_dir / "summary.csv").write_text("key,value,unit\nrunning_days,1,天\n", encoding="utf-8")

            reader = server.CsvDataSource(data_dir=data_dir, reload_interval=0)
            first = reader.snapshot()
            (data_dir / "summary.csv").write_text("key,value,unit\nrunning_days,2,天\n", encoding="utf-8")
            second = reader.snapshot()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

        self.assertEqual(first["summary"]["running_days"], 1)
        self.assertEqual(second["summary"]["running_days"], 2)

    def test_mysql_data_source_builds_snapshot_from_database_rows(self):
        rows = {
            "SELECT `key`, value, unit FROM overview_summary ORDER BY display_order, id": [
                {"key": "running_days", "value": "449", "unit": "天"},
            ],
        }
        fake_connection = FakeConnection(rows)
        source = server.MySqlDataSource(connector_factory=lambda config: fake_connection, reload_interval=0)

        payload = source.snapshot()

        self.assertEqual(payload["summary"]["running_days"], 449)
        self.assertNotIn("simu", payload)
        self.assertNotIn("scada", payload)
        self.assertNotIn("agc", payload)
        self.assertEqual(
            fake_connection.cursor_obj.executed,
            [("SELECT `key`, value, unit FROM overview_summary ORDER BY display_order, id", ())],
        )

    def test_unknown_api_path_returns_404_json(self):
        status, headers, body = server.handle_api_path("/api/not-found")

        self.assertEqual(status, 404)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body.decode("utf-8"))["error"], "not_found")

    def test_planning_api_create_read_save_copy_rename(self):
        planning_root = WEB_ROOT / "tests" / "tmp_planning_api"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            status, headers, body = server.handle_planning_api_path(
                "/api/planning/schemes",
                "POST",
                json.dumps({"name": "方案A"}).encode("utf-8"),
            )
            self.assertEqual(status, 200)
            created = json.loads(body.decode("utf-8"))
            self.assertEqual(created["scheme"], "方案A")
            self.assertEqual(len(created["time_series"]), 8760)
            self.assertIn("planning_parameters", created)
            self.assertNotIn("design_life_years", created["planning_parameters"][0])
            self.assertEqual(created["storage_battery_packs"][0]["self_discharge_rate"], 0.01)
            self.assertEqual(created["hydrogen_tanks"][0]["self_discharge_rate"], 0.001)
            self.assertEqual(created["storage_pcs"][0]["storage_charge_efficiency"], 0.95)
            self.assertEqual(created["storage_pcs"][0]["storage_discharge_efficiency"], 0.95)

            created["time_series"][0]["load"] = 123.4
            created["planning_parameters"][0]["storage_frequency_regulation_enabled"] = 1
            status, headers, body = server.handle_planning_api_path(
                "/api/planning/schemes/方案A",
                "PUT",
                json.dumps(created, ensure_ascii=False).encode("utf-8"),
            )
            self.assertEqual(status, 200)

            status, headers, body = server.handle_planning_api_path("/api/planning/schemes/方案A", "GET", b"")
            loaded = json.loads(body.decode("utf-8"))
            self.assertEqual(loaded["time_series"][0]["load"], 123.4)
            self.assertNotIn("design_life_years", loaded["planning_parameters"][0])
            self.assertEqual(loaded["planning_parameters"][0]["storage_frequency_regulation_enabled"], 1)
            self.assertEqual(loaded["storage_battery_packs"][0]["self_discharge_rate"], 0.01)
            self.assertEqual(loaded["hydrogen_tanks"][0]["self_discharge_rate"], 0.001)
            self.assertEqual(loaded["storage_pcs"][0]["storage_charge_efficiency"], 0.95)
            self.assertEqual(loaded["storage_pcs"][0]["storage_discharge_efficiency"], 0.95)

            status, headers, body = server.handle_planning_api_path("/api/planning/schemes/方案A/overview", "GET", b"")
            overview = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertNotIn("time_series", overview)
            self.assertFalse(overview["time_series_loaded"])
            self.assertEqual(overview["time_series_count"], 8760)
            self.assertIn("diesel_generators", overview)
            self.assertIn("planning_parameters", overview)
            self.assertNotIn("design_life_years", overview["planning_parameters"][0])

            status, headers, body = server.handle_planning_api_path("/api/planning/schemes/方案A/time-series", "GET", b"")
            time_payload = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(time_payload["time_series"][0]["load"], 123.4)
            self.assertNotIn("diesel_generators", time_payload)

            status, headers, body = server.handle_planning_api_path(
                "/api/planning/schemes/copy",
                "POST",
                json.dumps({"source": "方案A", "target": "方案B"}, ensure_ascii=False).encode("utf-8"),
            )
            self.assertEqual(status, 200)

            status, headers, body = server.handle_planning_api_path(
                "/api/planning/schemes/copy",
                "POST",
                json.dumps({"source": "方案A", "target": "方案B"}, ensure_ascii=False).encode("utf-8"),
            )
            duplicate_copy = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("目标方案已存在", duplicate_copy["message"])

            status, headers, body = server.handle_planning_api_path(
                "/api/planning/schemes/copy",
                "POST",
                json.dumps({"source": "方案A", "target": "方案B", "overwrite": True}, ensure_ascii=False).encode("utf-8"),
            )
            overwritten_copy = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(overwritten_copy["scheme"], "方案B")

            status, headers, body = server.handle_planning_api_path(
                "/api/planning/schemes/rename",
                "POST",
                json.dumps({"source": "方案B", "target": "方案C"}, ensure_ascii=False).encode("utf-8"),
            )
            self.assertEqual(status, 200)

            status, headers, body = server.handle_planning_api_path("/api/planning/schemes", "GET", b"")
            names = [item["name"] for item in json.loads(body.decode("utf-8"))["schemes"]]
            self.assertEqual(names, ["方案A", "方案C"])
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_planning_api_reports_locked_parameter_file_as_conflict(self):
        planning_root = WEB_ROOT / "tests" / "tmp_planning_api_locked"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            payload = server.PLANNING_STORE.create_scheme("方案A")
            payload["time_series"][0]["load"] = 789

            def always_locked_replace(self, target):
                if Path(self).name == f".{server.planning_store.WORKBOOK_NAME}.tmp":
                    raise PermissionError("still locked")
                return Path.replace(self, target)

            with patch.object(Path, "replace", new=always_locked_replace), patch.object(server.file_ops.time, "sleep", return_value=None):
                status, headers, body = server.handle_planning_api_path(
                    "/api/planning/schemes/方案A",
                    "PUT",
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                )

            locked = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 409)
            self.assertEqual(locked["error"], "file_locked")
            self.assertIn("参数文件被占用", locked["message"])
            self.assertIn("请关闭", locked["message"])
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_planning_store_backfills_key_specific_self_discharge_defaults_for_legacy_workbook(self):
        planning_root = WEB_ROOT / "tests" / "tmp_planning_legacy_defaults"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        path = planning_root / "parameters.xlsx"
        payload = server.planning_store.default_payload("方案A")
        workbook = server.planning_store.build_workbook(payload)
        try:
            for sheet_name in ("储能电池组参数", "储氢罐参数"):
                sheet = workbook[sheet_name]
                for cell in sheet[1]:
                    if cell.value == "self_discharge_rate":
                        sheet.delete_cols(cell.column)
                        break
            workbook.save(path)
        finally:
            workbook.close()

        try:
            loaded = server.planning_store.read_workbook(
                path,
                "方案A",
                include_keys=["storage_battery_packs", "hydrogen_tanks"],
            )

            self.assertEqual(loaded["storage_battery_packs"][0]["self_discharge_rate"], 0.01)
            self.assertEqual(loaded["hydrogen_tanks"][0]["self_discharge_rate"], 0.001)
        finally:
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_planning_time_series_import_parses_csv_and_validates_required_columns(self):
        rows = ["风速,太阳辐射,室温,负荷"]
        rows.extend(f"{i % 20},{500 + i % 300},{-10 + i % 30},{100 + i % 50}" for i in range(8760))
        content = "\n".join(rows).encode("utf-8")

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/time-series/import",
            "POST",
            json.dumps({"filename": "timeseries.csv", "content_base64": base64.b64encode(content).decode("ascii")}).encode("utf-8"),
        )

        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["time_series_count"], 8760)
        self.assertEqual(payload["time_series"][0]["hour_index"], 1)
        self.assertEqual(payload["time_series"][0]["wind_speed"], 0)
        self.assertEqual(payload["time_series"][0]["solar_irradiance"], 500)
        self.assertEqual(payload["time_series"][0]["temperature"], -10)
        self.assertEqual(payload["time_series"][0]["load"], 100)

        bad_rows = ["风速,室温,负荷", "1,2,3"]
        status, headers, body = server.handle_planning_api_path(
            "/api/planning/time-series/import",
            "POST",
            json.dumps({"filename": "bad.csv", "content_base64": base64.b64encode("\n".join(bad_rows).encode("utf-8")).decode("ascii")}).encode("utf-8"),
        )

        self.assertEqual(status, 400)
        error_payload = json.loads(body.decode("utf-8"))
        self.assertIn("找不到对应的列", error_payload["message"])
        self.assertIn("太阳辐射", error_payload["message"])

    def test_planning_time_series_import_matches_fuzzy_headers_and_pads_short_files(self):
        rows = [
            "风速(m/s),单位面积太阳辐射(W/m^2),温度(摄氏度),用电功率(kW)",
            "3.5,600,18,120",
            "4.0,610,19,125",
            "4.5,620,20,130",
        ]
        content = "\n".join(rows).encode("utf-8")

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/time-series/import",
            "POST",
            json.dumps({"filename": "short_timeseries.csv", "content_base64": base64.b64encode(content).decode("ascii")}).encode("utf-8"),
        )

        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["time_series_count"], 8760)
        self.assertEqual(payload["time_series"][0]["solar_irradiance"], 600)
        self.assertEqual(payload["time_series"][0]["temperature"], 18)
        self.assertEqual(payload["time_series"][0]["load"], 120)
        self.assertEqual(payload["time_series"][8759]["hour_index"], 8760)
        self.assertEqual(payload["time_series"][8759]["datetime"], "H8760")
        self.assertEqual(payload["time_series"][8759]["wind_speed"], 4.5)
        self.assertEqual(payload["time_series"][8759]["solar_irradiance"], 620)
        self.assertIn("已按最后一行自动补齐8757行", payload["message"])

    def test_planning_time_series_import_fills_missing_middle_hours(self):
        rows = [
            "时间,风速,太阳辐照,环境温度,负荷功率",
            "H0001,3,500,10,100",
            "H0003,5,700,12,120",
        ]
        content = "\n".join(rows).encode("utf-8")

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/time-series/import",
            "POST",
            json.dumps({"filename": "gap_timeseries.csv", "content_base64": base64.b64encode(content).decode("ascii")}).encode("utf-8"),
        )

        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["time_series_count"], 8760)
        self.assertEqual(payload["time_series"][0]["datetime"], "H0001")
        self.assertEqual(payload["time_series"][0]["wind_speed"], 3)
        self.assertEqual(payload["time_series"][1]["datetime"], "H0002")
        self.assertEqual(payload["time_series"][1]["wind_speed"], 3)
        self.assertEqual(payload["time_series"][1]["solar_irradiance"], 500)
        self.assertEqual(payload["time_series"][2]["datetime"], "H0003")
        self.assertEqual(payload["time_series"][2]["wind_speed"], 5)
        self.assertEqual(payload["time_series"][8759]["datetime"], "H8760")
        self.assertEqual(payload["time_series"][8759]["load"], 120)
        self.assertIn("已补齐8758个缺失时点", payload["message"])

    def test_planning_time_series_import_parses_xlsx(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["时间", "风速", "太阳辐照", "温度", "负荷"])
        for i in range(8760):
            sheet.append([f"H{i + 1:04d}", 3.5, 720, 15, 88])
        stream = BytesIO()
        workbook.save(stream)

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/time-series/import",
            "POST",
            json.dumps({"filename": "timeseries.xlsx", "content_base64": base64.b64encode(stream.getvalue()).decode("ascii")}).encode("utf-8"),
        )

        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["time_series_count"], 8760)
        self.assertEqual(payload["time_series"][8759]["datetime"], "H8760")
        self.assertEqual(payload["time_series"][8759]["wind_speed"], 3.5)

    def test_planning_load_curve_generation_matches_requested_statistics(self):
        for mode in ("random", "pattern1", "pattern2", "pattern3"):
            status, headers, body = server.handle_planning_api_path(
                "/api/planning/load-curve/generate",
                "POST",
                json.dumps({"mode": mode, "max": 180, "min": 40, "average": 95}).encode("utf-8"),
            )

            self.assertEqual(status, 200)
            payload = json.loads(body.decode("utf-8"))
            values = [row["load"] for row in payload["load_curve"]]
            self.assertEqual(payload["load_curve_count"], 8760)
            self.assertEqual(payload["mode"], mode)
            self.assertAlmostEqual(min(values), 40, places=3)
            self.assertAlmostEqual(max(values), 180, places=3)
            self.assertAlmostEqual(sum(values) / len(values), 95, places=3)

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/load-curve/generate",
            "POST",
            json.dumps({"mode": "pattern1", "max": 180, "min": 40, "average": 200}).encode("utf-8"),
        )

        self.assertEqual(status, 400)
        self.assertIn("平均值必须介于最小值和最大值之间", json.loads(body.decode("utf-8"))["message"])

    def test_planning_api_delete_scheme(self):
        planning_root = WEB_ROOT / "tests" / "tmp_planning_delete_api"
        shutil.rmtree(planning_root, ignore_errors=True)
        planning_root.mkdir(parents=True)
        original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=planning_root)
        try:
            server.PLANNING_STORE.create_scheme("方案A")
            server.PLANNING_STORE.create_scheme("方案B")

            status, headers, body = server.handle_planning_api_path("/api/planning/schemes/方案A", "DELETE", b"")

            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body.decode("utf-8"))["deleted"], "方案A")
            self.assertFalse((planning_root / "方案A").exists())
            names = [item["name"] for item in server.PLANNING_STORE.list_schemes()]
            self.assertEqual(names, ["方案B"])
        finally:
            server.PLANNING_STORE = original_store
            shutil.rmtree(planning_root, ignore_errors=True)

    def test_planning_api_rejects_bad_scheme_name(self):
        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes",
            "POST",
            json.dumps({"name": "../bad"}).encode("utf-8"),
        )

        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body.decode("utf-8"))["error"], "bad_request")

    def test_planning_weather_history_endpoint_validates_year_before_current_year(self):
        status, headers, body = server.handle_planning_api_path(
            "/api/planning/weather-history",
            "POST",
            json.dumps({"latitude": 10, "longitude": 20, "year": 9999}).encode("utf-8"),
        )

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "bad_request")
        self.assertIn("历史数据年必须小于当前年", data["message"])

    def test_parse_nasa_power_hourly_response_requires_8760_rows(self):
        payload = {
            "header": {"fill_value": -999},
            "properties": {
                "parameter": {
                    "WS10M": {"2025010100": 7.1},
                    "ALLSKY_SFC_SW_DWN": {"2025010100": 0},
                    "T2M": {"2025010100": -12.5},
                }
            },
        }

        with self.assertRaises(server.WeatherHistoryError):
            server.parse_nasa_power_hourly_response(payload, 2025)

    def test_planning_geocode_endpoint_fills_coordinates_from_place_name(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(url, timeout):
            self.assertIn("geocoding-api.open-meteo.com", url)
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "北京",
                            "latitude": 39.9075,
                            "longitude": 116.39723,
                            "country": "中国",
                            "admin1": "北京市",
                        }
                    ]
                }
            )

        original_key = server.AMAP_WEB_SERVICE_KEY
        server.AMAP_WEB_SERVICE_KEY = ""
        try:
            with patch.object(server, "urlopen_with_user_agent", side_effect=fake_urlopen):
                status, headers, body = server.handle_planning_api_path(
                    "/api/planning/geocode",
                    "POST",
                    json.dumps({"place": "北京"}, ensure_ascii=False).encode("utf-8"),
                )
        finally:
            server.AMAP_WEB_SERVICE_KEY = original_key

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["latitude"], 39.9075)
        self.assertEqual(data["longitude"], 116.39723)
        self.assertEqual(data["source"], "Open-Meteo Geocoding API")

    def test_planning_geocode_prefers_amap_when_key_is_configured(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "status": "1",
                        "geocodes": [
                            {
                                "formatted_address": "北京市",
                                "province": "北京市",
                                "city": "北京市",
                                "district": [],
                                "location": "116.407526,39.904030",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        original_key = server.AMAP_WEB_SERVICE_KEY
        server.AMAP_WEB_SERVICE_KEY = "test-key"
        try:
            def fake_urlopen(url, timeout):
                self.assertIn("restapi.amap.com", url)
                self.assertIn("key=test-key", url)
                return FakeResponse()

            with patch.object(server, "urlopen_with_user_agent", side_effect=fake_urlopen):
                status, headers, body = server.handle_planning_api_path(
                    "/api/planning/geocode",
                    "POST",
                    json.dumps({"place": "北京"}, ensure_ascii=False).encode("utf-8"),
                )
        finally:
            server.AMAP_WEB_SERVICE_KEY = original_key

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["latitude"], 39.90403)
        self.assertEqual(data["longitude"], 116.407526)
        self.assertEqual(data["source"], "高德地图 Web 服务地理编码 API")

    def test_planning_geocode_uses_global_provider_first_for_english_places(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        requested_urls = []

        def fake_urlopen(url, timeout):
            requested_urls.append(url)
            if "geocoding-api.open-meteo.com" in url:
                return FakeResponse(
                    {
                        "results": [
                            {
                                "name": "New York",
                                "latitude": 40.71427,
                                "longitude": -74.00597,
                                "country": "美国",
                                "admin1": "纽约州",
                            }
                        ]
                    }
                )
            if "restapi.amap.com" in url:
                return FakeResponse(
                    {
                        "status": "1",
                        "geocodes": [
                            {
                                "formatted_address": "广东省惠州市惠东县New YorK(解放中路店)",
                                "province": "广东省",
                                "city": "惠州市",
                                "district": "惠东县",
                                "location": "114.721208,22.978660",
                            }
                        ],
                    }
                )
            raise AssertionError(f"unexpected url: {url}")

        original_key = server.AMAP_WEB_SERVICE_KEY
        server.AMAP_WEB_SERVICE_KEY = "test-key"
        try:
            with patch.object(server, "urlopen_with_user_agent", side_effect=fake_urlopen):
                status, headers, body = server.handle_planning_api_path(
                    "/api/planning/geocode",
                    "POST",
                    json.dumps({"place": "New York"}, ensure_ascii=False).encode("utf-8"),
                )
        finally:
            server.AMAP_WEB_SERVICE_KEY = original_key

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["latitude"], 40.71427)
        self.assertEqual(data["longitude"], -74.00597)
        self.assertEqual(data["source"], "Open-Meteo Geocoding API")
        self.assertIn("geocoding-api.open-meteo.com", requested_urls[0])
        self.assertTrue(all("restapi.amap.com" not in url for url in requested_urls))

    def test_planning_map_config_exposes_amap_key_when_configured(self):
        original_key = server.AMAP_WEB_SERVICE_KEY
        server.AMAP_WEB_SERVICE_KEY = "test-key"
        try:
            status, headers, body = server.handle_planning_api_path("/api/planning/map-config", "GET", b"")
        finally:
            server.AMAP_WEB_SERVICE_KEY = original_key

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["amap_key"], "test-key")
        self.assertEqual(data["preferred_provider"], "amap")

    def test_planning_map_config_has_default_amap_key(self):
        self.assertEqual(server.DEFAULT_AMAP_WEB_SERVICE_KEY, "21db26646aac8fed4620eaa36f210018")
        self.assertEqual(server.DEFAULT_BAIDU_MAP_BROWSER_KEY, "ebp62kY5I2KTRF6WVn3byZ9VZCc3uuE8")

    def test_planning_map_config_exposes_baidu_and_google_keys_when_configured(self):
        original_baidu_key = server.BAIDU_MAP_BROWSER_KEY
        original_google_key = server.GOOGLE_MAPS_BROWSER_KEY
        server.BAIDU_MAP_BROWSER_KEY = "baidu-test-key"
        server.GOOGLE_MAPS_BROWSER_KEY = "google-test-key"
        try:
            status, headers, body = server.handle_planning_api_path("/api/planning/map-config", "GET", b"")
        finally:
            server.BAIDU_MAP_BROWSER_KEY = original_baidu_key
            server.GOOGLE_MAPS_BROWSER_KEY = original_google_key

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["baidu_key"], "baidu-test-key")
        self.assertEqual(data["google_key"], "google-test-key")
        self.assertIn({"key": "baidu", "label": "百度地图", "enabled": True}, data["providers"])
        self.assertIn({"key": "google", "label": "谷歌地图", "enabled": True}, data["providers"])

    def test_planning_geocode_endpoint_falls_back_to_nominatim(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(url, timeout):
            if "geocoding-api.open-meteo.com" in url:
                return FakeResponse({"results": []})
            self.assertIn("nominatim.openstreetmap.org", url)
            return FakeResponse([{"lat": "39.9042", "lon": "116.4074", "display_name": "北京"}])

        original_key = server.AMAP_WEB_SERVICE_KEY
        server.AMAP_WEB_SERVICE_KEY = ""
        try:
            with patch.object(server, "urlopen_with_user_agent", side_effect=fake_urlopen):
                status, headers, body = server.handle_planning_api_path(
                    "/api/planning/geocode",
                    "POST",
                    json.dumps({"place": "北京"}, ensure_ascii=False).encode("utf-8"),
                )
        finally:
            server.AMAP_WEB_SERVICE_KEY = original_key

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["latitude"], 39.9042)
        self.assertEqual(data["longitude"], 116.4074)
        self.assertEqual(data["source"], "OpenStreetMap Nominatim")

    def test_planning_page_has_current_scheme_display(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn('id="currentSchemeName"', html)
        self.assertIn("当前方案:", html)
        self.assertIn(".current-scheme", css)
        self.assertIn("display: flex", css)
        self.assertIn("justify-content: flex-start", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn("text-overflow: ellipsis", css)
        self.assertLess(html.index('id="currentSchemeName"'), html.index(">时序数据<"))

    def test_planning_page_uses_requested_product_and_time_series_labels(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")

        self.assertIn(">考察站风-光-氢-储-柴联合规划系统<", html)
        self.assertIn(">时序数据<", html)
        self.assertNotIn(">电网规划系统<", html)
        self.assertNotIn(">微电网风光氢储联合规划系统<", html)
        self.assertNotIn(">电网规划列表<", html)
        self.assertNotIn(">8760时序数据<", html)

    def test_scheme_lists_use_list_items_with_hover_response(self):
        planning_script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        optimize_script = (WEB_ROOT / "assets" / "optimize.js").read_text(encoding="utf-8")
        evaluation_script = (WEB_ROOT / "assets" / "evaluation.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        for script in (planning_script, optimize_script, evaluation_script):
            self.assertIn('<ul class="scheme-list-items" role="listbox">', script)
            self.assertIn('<li class="scheme-item', script)
            self.assertIn('role="option"', script)
            self.assertIn('tabindex="0"', script)
            self.assertIn('aria-selected="${scheme.name === state.currentScheme ? "true" : "false"}"', script)
            self.assertIn("bindSchemeListItem", script)
            self.assertIn("event.key === \"Enter\" || event.key === \" \"", script)
            self.assertNotIn("<button class=\"scheme-item", script)

        self.assertIn(".scheme-list-items", css)
        self.assertIn(".scheme-item:hover", css)
        self.assertIn(".scheme-item:focus-visible", css)
        scheme_item_css = css.split(".scheme-item {", 1)[1].split("}", 1)[0]
        self.assertIn("cursor: pointer", scheme_item_css)
        self.assertIn("user-select: none", scheme_item_css)

    def test_optimization_page_has_requested_three_area_layout(self):
        html = (WEB_ROOT / "optimize.html").read_text(encoding="utf-8")
        planning_html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn(">考察站风-光-氢-储-柴联合规划系统<", html)
        self.assertIn('<a class="active" href="optimize.html">规划求解</a>', html)
        self.assertIn('<aside class="scheme-rail">', html)
        self.assertIn('<div class="scheme-list-title">方案列表</div>', html)
        self.assertIn('id="schemeList"', html)
        self.assertIn('class="optimization-panel"', html)
        self.assertIn('class="optimization-command-card"', html)
        self.assertIn('id="startOptimization"', html)
        self.assertIn('id="stopOptimization"', html)
        for label in ("当前状态", "启动时刻", "结束时刻", "度电成本", "绿电占比"):
            self.assertIn(label, html)
        for tab in ("结果概览", "供能分析", "安全评估"):
            self.assertIn(tab, html)
        self.assertNotIn("绿电结果", html)
        self.assertNotIn("安全结果", html)
        self.assertIn('id="overviewResult"', html)
        self.assertIn('id="greenResult"', html)
        self.assertIn('id="safetyResult"', html)
        self.assertIn('id="optimizationLogViewToggle"', html)
        self.assertIn('id="optimizationCurveViewToggle"', html)
        self.assertIn('id="optimizationLogPanel"', html)
        self.assertIn('id="optimizationCurvePanel"', html)
        self.assertIn('id="optimizationLogs"', html)
        self.assertIn('id="optimizationCurveNameList"', html)
        self.assertIn('id="optimizationCurveChart"', html)
        self.assertIn(">运行日志<", html)
        self.assertIn(">曲线展示<", html)
        self.assertIn("assets/result_curves.js", html)
        self.assertIn('assets/optimize.js', html)
        self.assertIn('href="optimize.html">规划求解</a>', planning_html)
        self.assertIn(".optimization-panel", css)
        self.assertIn("grid-template-rows: max-content minmax(220px, 1fr)", css)
        self.assertIn(".log-view-tabs", css)
        self.assertIn(".log-view-tab", css)
        self.assertIn(".log-view-panel", css)
        self.assertIn(".optimization-curve-panel", css)
        self.assertIn(".optimization-curve-name-list", css)
        self.assertIn(".optimization-curve-chart", css)

    def test_optimization_frontend_polls_status_and_binds_controls(self):
        script = (WEB_ROOT / "assets" / "optimize.js").read_text(encoding="utf-8")

        self.assertIn("/api/planning/schemes", script)
        self.assertIn("/api/optimization/status", script)
        self.assertIn("/api/optimization/control", script)
        self.assertNotIn("/api/evaluation/status", script)
        self.assertNotIn("/api/evaluation/control", script)
        self.assertIn("startOptimization", script)
        self.assertIn("stopOptimization", script)
        self.assertIn("updateOptimizationActions", script)
        self.assertIn("startButton.disabled = !hasScheme || isRunning", script)
        self.assertIn("stopButton.disabled = !hasScheme || !isRunning", script)
        self.assertIn("classList.toggle(\"is-disabled\"", script)
        self.assertIn("classList.toggle(\"is-active\"", script)
        self.assertIn("正在运行，无法再次启动", script)
        self.assertIn("没有运行", script)
        self.assertIn("alert(data.message", script)
        self.assertIn("setInterval", script)
        self.assertIn("scheduleOptimizationPolling", script)
        self.assertIn("state.pollDelay = data.status === \"运行中\" ? 1000 : 4000", script)
        self.assertIn("renderOptimizationLogs", script)
        self.assertIn("bindLogContextMenu", script)
        self.assertIn("clearOptimizationLogs", script)
        self.assertIn("saveOptimizationLogs", script)
        self.assertIn("optimizationCurveViewer", script)
        self.assertIn("loadOptimizationCurveData", script)
        self.assertIn("/api/comparison/data", script)
        self.assertIn("ResultCurveViewer.create", script)
        self.assertIn("暂无小时级曲线", script)
        self.assertIn("请选择小时级曲线", script)
        self.assertIn("正在加载小时级曲线", script)
        self.assertIn("setData", script)
        self.assertIn("scrollTop", script)
        self.assertIn("data-result-tab", script)
        self.assertIn("结果概览", script)
        self.assertIn("供能分析", script)
        self.assertIn("安全评估", script)
        self.assertNotIn("绿电结果", script)
        self.assertNotIn("安全结果", script)
        self.assertIn("optimizationStatusPath", script)
        self.assertIn("defaultOptimizationState", script)
        self.assertIn("scheme=", script)
        self.assertIn("encodeURIComponent(scheme)", script)
        self.assertIn("refreshOptimizationStatus().catch(showError)", script)
        self.assertIn(".optimization-actions button.is-disabled", css := (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8"))
        self.assertIn(".optimization-actions button.is-active", css)

    def test_evaluation_page_uses_optimization_layout_as_editable_base(self):
        html = (WEB_ROOT / "evaluation.html").read_text(encoding="utf-8")
        planning_html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        optimize_html = (WEB_ROOT / "optimize.html").read_text(encoding="utf-8")
        index_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "evaluation.js").read_text(encoding="utf-8")

        self.assertIn("assets/planning.css?v=20260514-i18n", html)
        self.assertIn('<a class="active" href="evaluation.html">方案评估</a>', html)
        self.assertIn('href="evaluation.html">方案评估</a>', planning_html)
        self.assertIn('href="evaluation.html">方案评估</a>', optimize_html)
        self.assertIn('href="evaluation.html"', index_html)
        self.assertIn("<strong>方案评估</strong>", index_html)
        self.assertIn('<aside class="scheme-rail">', html)
        self.assertIn('id="schemeList"', html)
        self.assertIn('class="optimization-panel"', html)
        self.assertIn('id="startEvaluation"', html)
        self.assertIn('id="stopEvaluation"', html)
        self.assertIn('id="evaluationResultSelect"', html)
        self.assertIn('id="evaluationResultWarnings"', html)
        self.assertIn("result-file-warnings", html)
        self.assertIn('class="evaluation-result-rail"', html)
        self.assertIn('id="evaluationCurrentScheme"', html)
        self.assertIn('id="evaluationPlanningResultTable"', html)
        self.assertIn('id="evaluationMainResizeHandle"', html)
        self.assertIn("当前方案: 未选择方案", html)
        self.assertNotIn("当前方案: 未选择方案，结果显示", html)
        self.assertIn("当前规划结果", html)
        self.assertNotIn(">结果文件<", html)
        self.assertNotIn('id="addEvaluationResult"', html)
        for control in ("deleteEvaluationResult", "copyEvaluationResult", "saveEvaluationResult"):
            self.assertIn(f'id="{control}"', html)
        self.assertNotIn("增加结果", html)
        for label in ("删除结果", "复制结果", "保存结果"):
            self.assertIn(label, html)
        for label in ("当前状态", "启动时刻", "结束时刻", "综合评分", "风险等级"):
            self.assertIn(label, html)
        for tab in ("评估概览", "经济性评估", "安全性评估"):
            self.assertIn(tab, html)
        self.assertIn('id="evaluationLogViewToggle"', html)
        self.assertIn('id="evaluationCurveViewToggle"', html)
        self.assertIn('id="evaluationLogPanel"', html)
        self.assertIn('id="evaluationCurvePanel"', html)
        self.assertIn('id="evaluationLogs"', html)
        self.assertIn('id="evaluationCurveNameList"', html)
        self.assertIn('id="evaluationCurveChart"', html)
        self.assertIn('class="evaluation-log-region optimization-log-card"', html)
        self.assertIn(">评估日志<", html)
        self.assertIn(">曲线展示<", html)
        self.assertIn("assets/result_curves.js", html)
        self.assertIn("assets/evaluation.js", html)
        self.assertIn("/api/evaluation/status", script)
        self.assertIn("/api/evaluation/control", script)
        self.assertNotIn("/api/optimization/status", script)
        self.assertNotIn("/api/optimization/control", script)
        self.assertIn("/api/evaluation/results", script)
        self.assertIn("loadEvaluationResults", script)
        self.assertIn("refreshOptimizationStatus(state.currentScheme, state.selectedResultFile).catch(showError)", script)
        self.assertIn("manageEvaluationResult", script)
        self.assertIn("resultDisplayName", script)
        self.assertIn("renderEvaluationResultOption", script)
        self.assertIn("renderEvaluationResultWarnings", script)
        self.assertIn("selectedResultIsReadable", script)
        self.assertNotIn('unreadable ? " disabled" : ""', script)
        self.assertIn("暂无可读取结果文件", script)
        self.assertIn("无法读取", script)
        self.assertIn("请求后台失败，请检查 WEB 服务是否正常运行，或查看服务器错误日志。", script)
        self.assertIn("target_name", script)
        self.assertIn("filename=${encodeURIComponent(filename)}", script)
        self.assertIn("planning_result_rows", script)
        self.assertIn("renderEvaluationPlanningResultTable", script)
        self.assertIn("renderEvaluationCurrentScheme", script)
        self.assertIn("bindLogViewTabs", script)
        self.assertIn("evaluationCurveViewer", script)
        self.assertIn("loadEvaluationCurveData", script)
        self.assertIn("/api/comparison/data", script)
        self.assertIn("ResultCurveViewer.create", script)
        self.assertIn("暂无小时级曲线", script)
        self.assertIn("请选择小时级曲线", script)
        self.assertIn("正在加载小时级曲线", script)
        self.assertIn("bindEvaluationMainResizeHandle", script)
        self.assertIn("--evaluation-result-rail-width", script)
        self.assertIn("ArrowLeft", script)
        self.assertIn("ArrowRight", script)
        self.assertIn('document.getElementById("evaluationCurrentScheme")', script)
        self.assertIn('`当前方案: ${state.currentScheme || "未选择方案"}`', script)
        self.assertNotIn('`当前方案: ${state.currentScheme || "未选择方案"}，结果显示`', script)
        self.assertIn('data-planning-count-index="${index}"', script)
        self.assertIn('pattern="[0-9]*"', script)
        self.assertIn('inputmode="numeric"', script)
        self.assertIn("validatePlanningCountInput", script)
        self.assertIn("collectPlanningResultRows", script)
        self.assertIn("设计台数", script)
        self.assertIn("prompt(", script)
        self.assertIn("复制失败", script)
        self.assertIn("selectedResultIsDefault", script)
        self.assertIn("deleteButton.disabled = selectedResultIsDefault() || !hasScheme || !hasSelection", script)
        self.assertIn("saveButton.disabled = !canEditWorkbook || !hasScheme || !hasSelection", script)
        self.assertIn("copyButton.disabled = !selectedResultIsReadable() || !hasScheme || !hasSelection", script)
        self.assertIn("启动评估", html)
        self.assertIn("停止评估", html)

        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")
        self.assertIn(".evaluation-main-resize-handle", css)
        self.assertIn("grid-template-columns: 260px minmax(280px, var(--evaluation-result-rail-width, 340px)) 10px minmax(0, 1fr)", css)
        self.assertIn("grid-template-rows: minmax(0, var(--evaluation-upper-height, 1fr)) 14px minmax(180px, var(--optimization-log-height, 28vh))", css)
        self.assertIn("grid-column: 2 / 5", css)
        self.assertIn("grid-row: 3", css)
        self.assertIn("grid-template-rows: max-content minmax(220px, 1fr)", css)
        self.assertIn(".optimization-curve-panel", css)
        self.assertIn(".optimization-curve-name-list", css)
        self.assertIn(".optimization-curve-chart", css)

    def test_comparison_page_has_tabs_tables_curves_and_result_selectors(self):
        html = (WEB_ROOT / "comparison.html").read_text(encoding="utf-8")
        planning_html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        optimize_html = (WEB_ROOT / "optimize.html").read_text(encoding="utf-8")
        evaluation_html = (WEB_ROOT / "evaluation.html").read_text(encoding="utf-8")
        index_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "comparison.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("assets/planning.css?v=20260514-i18n", html)
        self.assertIn('<a class="active" href="comparison.html">结果对比</a>', html)
        self.assertIn('href="comparison.html">结果对比</a>', planning_html)
        self.assertIn('href="comparison.html">结果对比</a>', optimize_html)
        self.assertIn('href="comparison.html">结果对比</a>', evaluation_html)
        self.assertIn('href="comparison.html"', index_html)
        self.assertIn("comparison-tab-bar", html)
        self.assertIn("comparisonTabs", html)
        self.assertIn("comparisonResultWarnings", html)
        self.assertIn("result-file-warnings", html)
        self.assertIn("comparison-table-grid", html)
        for table_id in ("capacityComparisonTable", "energyComparisonTable", "safetyComparisonTable"):
            self.assertIn(table_id, html)
        for title in ("规划容量对比", "供能指标对比", "安全指标对比"):
            self.assertIn(title, html)
        self.assertIn("capacityEnergyResizeHandle", html)
        self.assertIn("energySafetyResizeHandle", html)
        self.assertIn('data-comparison-table-column-resize="capacity-energy"', html)
        self.assertIn('data-comparison-table-column-resize="energy-safety"', html)
        self.assertIn("comparisonTableCurveResizeHandle", html)
        self.assertIn("curveNameList", html)
        self.assertIn("comparisonCurveChart", html)
        self.assertIn("小时级曲线", html)
        self.assertIn("日级统计", html)
        self.assertIn("月度统计", html)
        self.assertIn("年度统计", html)
        self.assertNotIn("8760曲线", html)
        self.assertIn("assets/result_curves.js", html)
        self.assertIn("assets/comparison.js", html)

        self.assertIn("/api/planning/schemes", script)
        self.assertIn("/api/evaluation/results", script)
        self.assertIn("/api/comparison/data", script)
        self.assertIn("MAX_TABS = 4", script)
        self.assertIn("addComparisonTab", script)
        self.assertIn("renderAddComparisonTab", script)
        self.assertIn(".join(\"\") + renderAddComparisonTab()", script)
        self.assertIn('closest("#addComparisonTab")', script)
        self.assertIn("draggable=\"true\"", script)
        self.assertIn("data-close-comparison-tab", script)
        self.assertIn("bindComparisonTableCurveResizeHandle", script)
        self.assertIn("bindComparisonTableColumnResizeHandles", script)
        self.assertIn("data-comparison-table-column-resize", script)
        self.assertIn("--comparison-capacity-table-width", script)
        self.assertIn("--comparison-energy-table-width", script)
        self.assertIn("--comparison-safety-table-width", script)
        self.assertIn("curveNameList", script)
        self.assertIn("comparisonCurveViewer", script)
        self.assertIn("ResultCurveViewer.create", script)
        self.assertIn("curve_groups", script)
        self.assertIn("annual_table", script)
        self.assertIn("setData", script)
        self.assertIn("renderComparisonCurveChart", script)
        self.assertIn("selectedCurves", script)
        self.assertIn("selectedCurveNames", script)
        self.assertIn("selectedCurveSeries", script)
        self.assertIn("toggleSelectedCurve", script)
        self.assertIn("flatMap", script)
        self.assertIn('preserveAspectRatio="none"', script)
        self.assertIn("comparison-chart-hover-capture", script)
        self.assertIn("comparisonChartTooltip", script)
        self.assertIn("bindComparisonChartHover", script)
        self.assertIn("renderComparisonChartHover", script)
        self.assertIn("renderComparisonAxisLabels", script)
        self.assertIn("renderComparisonCurveStats", script)
        self.assertIn("comparison-chart-x-axis", script)
        self.assertIn("comparison-chart-y-axis", script)
        self.assertIn("comparison-curve-stats", script)
        self.assertIn("平均", script)
        self.assertIn("合计", script)
        self.assertIn("mouseleave", script)
        self.assertIn("loadResultFilesForTab", script)
        self.assertIn("schemeSelect", script)
        self.assertIn("resultSelect", script)
        self.assertIn("renderComparisonResultWarnings", script)
        self.assertIn("readable !== false", script)
        self.assertIn("无法读取", script)
        self.assertIn("请求后台失败，请检查 WEB 服务是否正常运行，或查看服务器错误日志。", script)
        self.assertIn('event.target.closest("select")', script)
        self.assertIn("event.stopPropagation()", script)
        self.assertIn('<ul aria-multiselectable="true">', script)
        self.assertIn("comparison-curve-name-item", script)
        self.assertIn('role="option"', script)
        self.assertIn('aria-multiselectable="true"', script)
        self.assertNotIn("<button type=\"button\" class=\"${name === state.selectedCurve", script)
        self.assertIn("comparison-table-curve-resize-handle", css)
        self.assertIn(".comparison-table-column-resize-handle", css)
        self.assertIn("grid-template-columns: minmax(0, var(--comparison-capacity-table-width, 1fr)) 10px minmax(0, var(--comparison-energy-table-width, 1fr)) 10px minmax(0, var(--comparison-safety-table-width, 1fr))", css)
        comparison_table_css = css.split(".comparison-table table {", 1)[1].split("}", 1)[0]
        self.assertIn("table-layout: fixed", comparison_table_css)
        self.assertIn("min-width: 0", comparison_table_css)
        self.assertIn(".comparison-curve-board", css)
        comparison_curve_chart_css = css.split(".comparison-curve-chart {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%", comparison_curve_chart_css)
        comparison_curve_svg_css = css.split(".comparison-curve-chart svg {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%", comparison_curve_svg_css)
        self.assertIn("height: 100%", comparison_curve_svg_css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", comparison_curve_chart_css)
        self.assertIn(".comparison-chart-hover-line", css)
        self.assertIn(".comparison-chart-hover-capture", css)
        self.assertIn(".comparison-chart-tooltip", css)
        self.assertIn(".comparison-chart-x-axis", css)
        self.assertIn(".comparison-chart-y-axis", css)
        self.assertIn(".comparison-curve-stats", css)
        comparison_curve_stats_css = css.split(".comparison-curve-stats {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", comparison_curve_stats_css)
        self.assertIn("right:", comparison_curve_stats_css)
        self.assertIn("top:", comparison_curve_stats_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", comparison_curve_stats_css)
        self.assertNotIn("<text class=\"comparison-chart-label\"", script)
        comparison_curve_stats_section_css = css.split(".comparison-curve-stats section {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: minmax(120px, 1fr) repeat(4, auto)", comparison_curve_stats_section_css)
        self.assertIn("min-width: 0", comparison_curve_stats_section_css)
        self.assertIn("white-space: nowrap", comparison_curve_stats_section_css)
        self.assertIn(".comparison-curve-name-item", css)
        self.assertIn(".curve-group-tabs", css)
        self.assertIn(".curve-group-tab", css)
        self.assertIn(".annual-stat-table", css)
        curve_group_tabs_css = css.split(".curve-group-tabs {", 1)[1].split("}", 1)[0]
        self.assertIn("position: sticky", curve_group_tabs_css)
        self.assertIn("top: 0", curve_group_tabs_css)
        self.assertIn("z-index:", curve_group_tabs_css)
        self.assertNotIn(".comparison-curve-name-list button", css)
        comparison_curve_name_item_css = css.split(".comparison-curve-name-item {", 1)[1].split("}", 1)[0]
        self.assertIn("cursor: pointer", comparison_curve_name_item_css)
        self.assertIn("user-select: none", comparison_curve_name_item_css)
        comparison_curve_name_hover_css = css.split(".comparison-curve-name-item:hover,", 1)[1].split("}", 1)[0]
        self.assertIn("border-left-color: #0d5c59", comparison_curve_name_hover_css)
        self.assertIn("background: rgba(13, 92, 89, 0.12)", comparison_curve_name_hover_css)

        result_curve_script = (WEB_ROOT / "assets" / "result_curves.js").read_text(encoding="utf-8")
        self.assertIn("curve_groups", result_curve_script)
        self.assertIn("annual_table", result_curve_script)
        self.assertIn("小时级曲线", result_curve_script)
        self.assertIn("日级统计", result_curve_script)
        self.assertIn("月度统计", result_curve_script)
        self.assertIn("年度统计", result_curve_script)
        self.assertIn("data-curve-group", result_curve_script)
        self.assertIn("renderAnnualTable", result_curve_script)

    def test_optimization_page_removes_command_to_result_resize_handle(self):
        html = (WEB_ROOT / "optimize.html").read_text(encoding="utf-8")
        evaluation_html = (WEB_ROOT / "evaluation.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "optimize.js").read_text(encoding="utf-8")
        evaluation_script = (WEB_ROOT / "assets" / "evaluation.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertNotIn('id="optimizationResultResizeHandle"', html)
        self.assertNotIn('id="optimizationResultResizeHandle"', evaluation_html)
        self.assertNotIn('id="optimizationLogResizeHandle"', html)
        self.assertNotIn('aria-label="调整规划结果高度"', html)
        self.assertNotIn('aria-label="调整评估结果高度"', evaluation_html)
        self.assertNotIn("bindOptimizationResultResizeHandle", script)
        self.assertNotIn("bindOptimizationResultResizeHandle", evaluation_script)
        self.assertNotIn("bindOptimizationLogResizeHandle", script)
        self.assertNotIn("optimizationResultHeight", script)
        self.assertNotIn("--optimization-result-height", script)
        self.assertNotIn(".optimization-result-resize-handle", css)
        self.assertIn(".optimization-log-resize-handle", css)
        result_tabs_css = css.split(".result-tabs {", 1)[1].split("}", 1)[0]
        self.assertIn("flex: 0 0 auto", result_tabs_css)
        self.assertIn("min-height: 38px", result_tabs_css)
        result_tab_css = css.split(".result-tab {", 1)[1].split("}", 1)[0]
        self.assertIn("height: 36px", result_tab_css)
        self.assertIn("display: inline-flex", result_tab_css)
        self.assertIn("cursor: row-resize", css)
        self.assertIn("--optimization-log-height", css)

    def test_optimization_overview_frontend_renders_two_tables_and_composition_bars(self):
        script = (WEB_ROOT / "assets" / "optimize.js").read_text(encoding="utf-8")
        evaluation_script = (WEB_ROOT / "assets" / "evaluation.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("renderOverviewTables", script)
        self.assertIn("overview_tables", script)
        self.assertIn("renderOverviewCompositionBars", script)
        self.assertIn("renderOverviewCompositionBar", script)
        self.assertIn("bindOverviewColumnResizeHandles", script)
        self.assertIn('data-overview-column-resize="left-middle"', script)
        self.assertIn('data-overview-column-resize="middle-right"', script)
        self.assertIn("--overview-left-column-width", script)
        self.assertIn("--overview-middle-column-width", script)
        self.assertIn("bindOverviewColumnResizeHandles", evaluation_script)
        self.assertIn('data-overview-column-resize="left-middle"', evaluation_script)
        self.assertIn("composition-bar-track", script)
        self.assertIn("composition-bar-segment", script)
        self.assertIn("overview_disks", script)
        self.assertIn("overview-composition-stack", script)
        self.assertIn("renderOverviewCompositionBars", evaluation_script)
        self.assertIn("composition-bar-track", evaluation_script)
        self.assertIn("optimization-overview-grid", script)
        for title in ("规划结果", "规划年指标"):
            self.assertIn(title, script)
        self.assertNotIn("规划年效益", script)
        for label in ("运行成本", "建设成本", "柴发电量", "新能源电量"):
            self.assertIn(label, script)
        for field in ("设备类型", "设计台数", "指标", "数值", "单位"):
            self.assertIn(field, script)
        self.assertIn(".optimization-overview-grid", css)
        self.assertIn("grid-template-columns: minmax(240px, var(--overview-left-column-width, 1fr)) 10px minmax(280px, var(--overview-middle-column-width, 0.95fr)) 10px minmax(240px, 1fr)", css)
        self.assertIn(".overview-column-resize-handle", css)
        self.assertIn("cursor: col-resize", css)
        self.assertIn(".overview-table-card", css)
        self.assertIn(".overview-composition-stack", css)
        composition_stack_css = css.split(".overview-composition-stack {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", composition_stack_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", composition_stack_css)
        self.assertIn("overflow: auto", composition_stack_css)
        composition_card_css = css.split(".composition-bar-card {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-rows: auto auto auto", composition_card_css)
        self.assertIn("min-height: 150px", composition_card_css)
        self.assertIn("border: 1px solid #d7e4e0", composition_card_css)
        self.assertIn(".composition-bar-track", css)
        composition_track_css = css.split(".composition-bar-track {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex", composition_track_css)
        self.assertIn("height: 24px", composition_track_css)
        self.assertIn(".composition-bar-segment.primary", css)
        self.assertIn(".composition-bar-segment.secondary", css)
        self.assertNotIn(".ratio-disk", css)
        self.assertNotIn("conic-gradient", css)

    def test_optimization_green_frontend_renders_daily_stacked_chart_and_table(self):
        script = (WEB_ROOT / "assets" / "optimize.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("renderGreenResult", script)
        self.assertIn("green_table", script)
        self.assertIn("green_daily", script)
        self.assertIn("renderGreenDailyChart", script)
        self.assertIn("bindResultColumnResizeHandles", script)
        self.assertIn("bindAdaptiveResultCharts", script)
        self.assertIn("bindChartHoverCursors", script)
        self.assertIn("updateChartHoverCursor", script)
        self.assertIn("renderGreenHoverTooltip", script)
        self.assertIn("ResizeObserver", script)
        self.assertIn("resultChartMargins", script)
        self.assertIn("chartTickIndexes", script)
        self.assertIn("height >= 200", script)
        self.assertIn("width < 620", script)
        self.assertNotIn("right: 22", script)
        self.assertIn('data-result-column-resize="green"', script)
        self.assertIn('data-result-chart-viewport="green"', script)
        self.assertIn("--green-result-table-width", script)
        self.assertIn("green-daily-chart", script)
        self.assertIn("green-zero-line", script)
        self.assertIn("green-zero-label", script)
        self.assertIn('data-chart-hover="green"', script)
        self.assertIn('data-chart-hover-line="green"', script)
        self.assertIn('data-chart-hover-tooltip="green"', script)
        self.assertIn('data-series-toggle', script)
        self.assertIn('aria-pressed', script)
        self.assertIn("greenSeriesVisibility", script)
        self.assertIn("toggleGreenSeriesVisibility", script)
        self.assertIn("isSeriesVisible", script)
        self.assertNotIn("green-axis-label", script)
        self.assertNotIn("green-y-axis-title", script)
        self.assertNotIn("green-x-axis-title", script)
        self.assertNotIn(">kWh<", script)
        self.assertNotIn("日序号", script)
        self.assertNotIn("renderGreenDailyDataTable", script)
        self.assertNotIn("green-daily-data-table", script)
        self.assertNotIn("日曲线测试数据", script)
        self.assertNotIn("第${day}日", script)
        green_render_script = script.split("function renderGreenResult", 1)[1].split("function renderGreenDailyChart", 1)[0]
        self.assertIn('"单位": row["单位"] || ""', green_render_script)
        self.assertLess(green_render_script.index("green-result-table"), green_render_script.index("green-chart-card"))
        for label in ("柴发日电量", "风电日电量", "光伏日电量", "氢能日电量", "储能放电量", "负荷电量", "制氢电量", "储能充电量"):
            self.assertIn(label, script)
        for metric in (
            '"指标": "负荷总电量", "数值": "-", "单位": "kWh"',
            '"指标": "柴发总电量", "数值": "-", "单位": "kWh"',
            '"指标": "风机总发电量", "数值": "-", "单位": "kWh"',
            '"指标": "光伏总发电量", "数值": "-", "单位": "kWh"',
            '"指标": "电储总发电量", "数值": "-", "单位": "kWh"',
            '"指标": "氢储总发电量", "数值": "-", "单位": "kWh"',
            '"指标": "新能源总弃电量", "数值": "-", "单位": "kWh"',
            '"指标": "新能源占比", "数值": "-", "单位": "%"',
            '"指标": "新能源弃电率", "数值": "-", "单位": "%"',
            '"指标": "柴油消耗", "数值": "-", "单位": "吨"',
            '"指标": "制氢总量", "数值": "-", "单位": "Nm3"',
        ):
            self.assertIn(metric, script)
        self.assertNotIn("负荷总电量(kWh)", script)

        self.assertIn(".green-result-layout", css)
        green_layout_css = css.split(".green-result-layout {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", green_layout_css)
        self.assertIn("grid-template-columns: minmax(260px, var(--green-result-table-width, 34%)) 10px minmax(0, 1fr)", green_layout_css)
        self.assertIn(".result-column-resize-handle", css)
        result_column_resize_css = css.split(".result-column-resize-handle {", 1)[1].split("}", 1)[0]
        self.assertIn("cursor: col-resize", result_column_resize_css)
        self.assertIn(".green-daily-chart", css)
        green_chart_card_css = css.split(".green-chart-card {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", green_chart_card_css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", green_chart_card_css)
        self.assertIn(".green-chart-viewport", css)
        green_chart_viewport_css = css.split(".green-chart-viewport,", 1)[1].split("{", 1)[1].split("}", 1)[0]
        self.assertIn("height: 100%", green_chart_viewport_css)
        self.assertIn("min-height: 0", green_chart_viewport_css)
        self.assertIn(".green-chart-svg", css)
        self.assertIn(".chart-hover-line", css)
        self.assertIn(".chart-hover-tooltip", css)
        chart_tooltip_css = css.split(".chart-hover-tooltip {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", chart_tooltip_css)
        self.assertIn("pointer-events: none", chart_tooltip_css)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', script)
        self.assertNotIn('preserveAspectRatio="none"', script)
        self.assertIn('resultChartSize("green"', script)
        green_chart_svg_css = css.split(".green-chart-svg {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%", green_chart_svg_css)
        self.assertIn("height: 100%", green_chart_svg_css)
        self.assertIn("min-height: 0", green_chart_svg_css)
        self.assertIn(".green-chart-legend", css)
        self.assertIn(".green-chart-legend button", css)
        self.assertIn(".green-chart-legend button.is-hidden", css)
        self.assertIn(".green-result-table", css)
        self.assertNotIn(".green-daily-data-table", css)
        self.assertNotIn(".green-daily-data-section", css)

    def test_optimization_safety_frontend_renders_frequency_chart_and_table(self):
        script = (WEB_ROOT / "assets" / "optimize.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("renderSafetyResult", script)
        self.assertIn("safety_table", script)
        self.assertIn("safety_daily", script)
        self.assertIn("renderSafetyDailyChart", script)
        self.assertIn("bindResultColumnResizeHandles", script)
        self.assertIn("bindAdaptiveResultCharts", script)
        self.assertIn("bindChartHoverCursors", script)
        self.assertIn("updateChartHoverCursor", script)
        self.assertIn("renderSafetyHoverTooltip", script)
        self.assertIn("ResizeObserver", script)
        self.assertIn("resultChartMargins", script)
        self.assertIn("chartTickIndexes", script)
        self.assertIn("height >= 200", script)
        self.assertIn("width < 620", script)
        self.assertNotIn("right: 22", script)
        self.assertIn('data-result-column-resize="safety"', script)
        self.assertIn('data-result-chart-viewport="safety"', script)
        self.assertIn("--safety-result-table-width", script)
        self.assertIn("safety-frequency-chart", script)
        self.assertIn("safety-center-line", script)
        self.assertIn("safety-zero-label", script)
        self.assertIn('data-chart-hover="safety"', script)
        self.assertIn('data-chart-hover-line="safety"', script)
        self.assertIn('data-chart-hover-tooltip="safety"', script)
        self.assertIn('data-series-toggle', script)
        self.assertIn('aria-pressed', script)
        self.assertIn("safetySeriesVisibility", script)
        self.assertIn("toggleSafetySeriesVisibility", script)
        self.assertIn("isSeriesVisible", script)
        self.assertIn("formatFrequencyDeviation", script)
        self.assertNotIn("safety-axis-label", script)
        self.assertNotIn("safety-y-axis-title", script)
        self.assertNotIn("safety-x-axis-title", script)
        self.assertNotIn(">Hz<", script)
        self.assertNotIn("日序号", script)
        self.assertNotIn(">50Hz<", script)
        self.assertIn("向上频率最大值", script)
        self.assertIn("向下频率最小值", script)
        self.assertNotIn("第${day}日", script)
        safety_render_script = script.split("function renderSafetyResult", 1)[1].split("function renderSafetyDailyChart", 1)[0]
        self.assertLess(safety_render_script.index("safety-result-table"), safety_render_script.index("safety-chart-card"))
        for metric in (
            "向上扰动最大量",
            "向下扰动最大量",
            "最高频率",
            "最低频率",
            "频率安全风险小时数",
        ):
            self.assertIn(metric, script)

        self.assertIn(".safety-result-layout", css)
        safety_layout_css = css.split(".safety-result-layout {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", safety_layout_css)
        self.assertIn("grid-template-columns: minmax(260px, var(--safety-result-table-width, 34%)) 10px minmax(0, 1fr)", safety_layout_css)
        self.assertIn(".result-column-resize-handle", css)
        result_column_resize_css = css.split(".result-column-resize-handle {", 1)[1].split("}", 1)[0]
        self.assertIn("cursor: col-resize", result_column_resize_css)
        self.assertIn(".safety-chart-card", css)
        safety_chart_card_css = css.split(".safety-chart-card {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", safety_chart_card_css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", safety_chart_card_css)
        self.assertIn(".safety-chart-viewport", css)
        safety_chart_viewport_css = css.split(".green-chart-viewport,", 1)[1].split("{", 1)[1].split("}", 1)[0]
        self.assertIn("height: 100%", safety_chart_viewport_css)
        self.assertIn("min-height: 0", safety_chart_viewport_css)
        self.assertIn(".safety-chart-svg", css)
        self.assertIn(".chart-hover-line", css)
        self.assertIn(".chart-hover-tooltip", css)
        chart_tooltip_css = css.split(".chart-hover-tooltip {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", chart_tooltip_css)
        self.assertIn("pointer-events: none", chart_tooltip_css)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', script)
        self.assertNotIn('preserveAspectRatio="none"', script)
        self.assertIn('resultChartSize("safety"', script)
        safety_chart_svg_css = css.split(".safety-chart-svg {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%", safety_chart_svg_css)
        self.assertIn("height: 100%", safety_chart_svg_css)
        self.assertIn("min-height: 0", safety_chart_svg_css)
        self.assertIn(".safety-chart-legend", css)
        self.assertIn(".safety-chart-legend button", css)
        self.assertIn(".safety-chart-legend button.is-hidden", css)
        self.assertIn(".safety-center-line", css)
        self.assertIn(".safety-result-table", css)

    def test_planning_scheme_rail_only_shows_scheme_list_title(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")
        rail = html.split('<aside class="scheme-rail">', 1)[1].split("</aside>", 1)[0]

        self.assertNotIn("方案管理", rail)
        self.assertIn("方案列表", rail)
        self.assertIn('id="schemeList"', rail)
        self.assertIn(".scheme-list-title", css)
        self.assertIn("color: #102b2a", css)
        self.assertIn("font-size: 18px", css)
        self.assertIn("font-weight: 900", css)

    def test_planning_page_save_button_is_in_scheme_actions(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        current_scheme_panel = html.split('<div class="current-scheme-panel">', 1)[1].split('<div class="tabs"', 1)[0]
        editor_header = html.split('<div class="editor-header">', 1)[1].split("</div>\n\n        <section", 1)[0]
        topbar = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        rail = html.split('<aside class="scheme-rail">', 1)[1].split("</aside>", 1)[0]

        self.assertNotIn('id="saveScheme"', current_scheme_panel)
        self.assertIn('class="scheme-actions"', editor_header)
        self.assertIn("margin-left: auto", (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8"))
        self.assertIn('id="saveScheme"', editor_header)
        self.assertIn('id="renameScheme"', editor_header)
        self.assertIn('id="copyScheme"', editor_header)
        self.assertIn('id="deleteScheme"', editor_header)
        self.assertIn(">修改名称<", editor_header)
        self.assertNotIn("修改方案名称", editor_header)
        self.assertNotIn("修改方案名", editor_header)
        self.assertNotIn('id="saveScheme"', topbar)
        self.assertNotIn('id="saveScheme"', rail)
        self.assertLess(html.index('id="currentSchemeName"'), html.index(">时序数据<"))
        self.assertLess(html.index(">时序数据<"), html.index('id="saveScheme"'))

    def test_planning_scheme_actions_are_horizontal(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("white-space: nowrap", css)

    def test_planning_page_has_device_filter_tags(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn('id="deviceFilters"', html)
        self.assertIn("renderDeviceFilters", script)
        self.assertIn("visibleDevices", script)
        self.assertIn("deviceGroups", script)
        self.assertIn("data-device-group", script)
        self.assertNotIn("<h2>设备类型显示</h2>", html)
        self.assertNotIn("默认全部显示，取消勾选则隐藏对应表格。", html)
        self.assertIn('class="device-filter-row"', html)
        device_filter_card = html.split('<div class="device-filter-card">', 1)[1].split('<div id="deviceTables"', 1)[0]
        self.assertIn('id="deviceFilters"', device_filter_card)
        self.assertIn('id="deviceJump"', device_filter_card)
        self.assertLess(device_filter_card.index('id="deviceFilters"'), device_filter_card.index('id="deviceJump"'))
        self.assertIn(".device-filter-row", css)
        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("justify-content: flex-end", css)
        self.assertIn("margin-left: auto", css)
        self.assertIn("min-width: 0", css)
        for group_name in ("风光柴", "氢储能", "电储能"):
            self.assertIn(group_name, script)
        self.assertLess(script.index('"电储能"'), script.index('"氢储能"'))
        self.assertLess(script.index('"储能PCS"'), script.index('"电制氢"'))
        for name in ("柴发", "风机", "光伏", "储能PCS", "储能电池组", "电制氢", "储氢罐", "燃料电池"):
            self.assertIn(name, script)

    def test_planning_page_has_planning_parameters_tab_and_summary_panel(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn('data-tab="planning"', html)
        self.assertIn('id="planningTab"', html)
        self.assertIn('id="planningParametersTable"', html)
        self.assertNotIn("参数随当前方案保存到 XLSX 文件。", html)
        self.assertLess(html.index('data-tab="devices"'), html.index('data-tab="planning"'))
        self.assertLess(html.index('data-tab="planning"'), html.index('data-tab="limits"'))
        self.assertIn('data-summary-tab="planning"', html)
        self.assertIn('data-summary-panel="planning"', html)
        self.assertIn('id="planningSummary"', html)
        self.assertIn("planningParameterSpecs", script)
        self.assertIn("planningParameterGroups", script)
        self.assertIn("planningGroupToggle", script)
        self.assertIn("isPlanningGroupEnabled", script)
        self.assertIn("bindPlanningParameterResizeHandles", script)
        self.assertIn("planning-parameter-resize-handle", script)
        self.assertIn("renderPlanningParameterGroupTable", script)
        self.assertIn("renderPlanningParameters", script)
        self.assertIn("renderPlanningParameterSummaryTable", script)
        self.assertIn('grid-template-columns: minmax(0, 1fr)', css)
        self.assertNotIn('grid-template-columns: repeat(3, minmax(220px, 1fr))', css)
        self.assertIn("collectPlanningParameterWarnings", script)
        self.assertIn("planning_parameters", script)
        self.assertIn(".planning-parameters-card", css)
        self.assertIn("#planningTab #planningParametersTable", css)
        self.assertIn(".planning-parameter-grid", css)
        self.assertIn(".planning-parameter-group", css)
        self.assertIn(".planning-parameter-switch", css)
        self.assertIn(".planning-parameter-group.disabled", css)
        self.assertIn(".planning-parameter-resize-handle", css)
        for label in (
            "柴油价格(万元/吨)",
            "绿色电量占比下限(0.0-1.0)",
            "规划求解时间上限(分钟)",
            "初始电储SOC(0.0-1.0)",
            "初始氢储SOC(0.0-1.0)",
            "储能是否参与调频",
            "是否考虑扰动后平衡约束",
            "负荷向上扰动系数(0.0-0.5)",
            "负荷向下扰动系数(0.0-0.5)",
            "新能源向下扰动系数(0.0-0.5)",
            "是否考虑频率安全约束",
            "频率安全上限(1.0-1.5)",
            "频率安全下限(0.5-1.0)",
            "频率最低点下限(Hz)",
            "频率最高点上限(Hz)",
            "频率下限安全裕度(Hz)",
            "频率上限安全裕度(Hz)",
            "负荷频率系数D",
            "RoCoF上限(Hz/s)",
            "稳态频率下限(Hz)",
            "稳态频率上限(Hz)",
            "频率Nadir评估时长(s)",
            "Nadir线性化每轴采样点数",
            "Nadir线性化区间比例",
            "网络同步系数基值",
            "网络同步系数斜率",
            "网络同步系数基准负荷(kW)",
            "是否考虑新能源N-1",
            "是否考虑新能源扰动",
            "是否考虑负荷扰动",
        ):
            self.assertIn(label, script)
        self.assertLess(script.index('"frequency_security_constraint_enabled"'), script.index('"frequency_nadir_lower_hz"'))
        self.assertLess(script.index('"network_synchronization_reference_load_kw"'), script.index('"storage_frequency_regulation_enabled"'))
        self.assertIn("Nadir线性化每轴采样点数必须为正整数", script)
        self.assertIn("稳态频率上限(Hz)不能小于稳态频率下限(Hz)", script)
        self.assertNotIn('["storage_charge_efficiency", "充电效率(0.0-1.0)", "number"', script)
        self.assertNotIn('["storage_discharge_efficiency", "放电效率(0.0-1.0)", "number"', script)
        self.assertNotIn("设计使用年限(年)", script)

    def test_planning_boolean_parameters_use_yes_no_selects(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("planning-bool-select", script)
        self.assertIn('<option value="1"', script)
        self.assertIn('<option value="0"', script)
        self.assertNotIn('<option value="true"', script)
        self.assertNotIn('<option value="false"', script)
        self.assertIn(">是</option>", script)
        self.assertIn(">否</option>", script)
        self.assertIn("numericBooleanPlanningValue", script)
        self.assertIn('input.type === "checkbox"', script)
        self.assertIn('input.tagName === "SELECT"', script)
        self.assertNotIn('type="checkbox" data-planning-key', script)
        self.assertIn(".planning-bool-select", css)

    def test_planning_save_has_parameter_alarm_validation(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertIn("collectSaveWarnings", script)
        self.assertIn("参数校验未通过", script)
        self.assertIn("数量下限(台)", script)
        self.assertIn("数量上限(台)", script)
        self.assertIn("数量上限不能小于数量下限", script)
        self.assertIn("频率安全上限不能小于频率安全下限", script)
        self.assertIn("规划求解时间上限(分钟)", script)
        self.assertIn("defaultValue: 60", script)
        self.assertIn("max: 120", script)
        self.assertIn('spec[0] === "hydrogen_tanks" ? 0.001 : 0.01', script)
        self.assertNotIn("规划负荷系数(0.1-10.0)", script)
        self.assertNotIn("设计容量上限不能小于下限", script)

    def test_planning_device_fields_have_numeric_validation_rules(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertIn("deviceFieldRules", script)
        self.assertIn("integer: true", script)
        self.assertIn("positive: true", script)
        self.assertIn("nonNegative: true", script)
        self.assertIn("deviceInputAttributes", script)
        self.assertIn('type="number"', script)
        self.assertIn('min="0"', script)
        self.assertIn('min="1"', script)
        self.assertIn('step="1"', script)
        self.assertIn('step="any"', script)
        self.assertIn('inputmode="numeric"', script)
        self.assertIn('inputmode="decimal"', script)
        self.assertIn('pattern="[0-9]*"', script)
        for field in (
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
            "cost",
            "capacity",
            "power_capacity",
            "storage_charge_efficiency",
            "storage_discharge_efficiency",
            "storage_equivalent_inertia_constant_h",
            "storage_equivalent_primary_frequency_coefficient_k",
            "storage_equivalent_damping_coefficient_d",
            "battery_capacity",
            "hydrogen_tank_capacity",
            "electric_to_hydrogen_efficiency",
            "hydrogen_to_electric_efficiency",
            "fuel_rate",
            "inertia_constant_h",
            "primary_frequency_coefficient_k",
            "damping_coefficient_d",
            "governor_time_constant_t",
            "power_lower",
            "cut_in_wind_speed",
            "rated_wind_speed",
            "cut_out_wind_speed",
            "is_grid_forming",
            "soc_upper",
            "soc_lower",
            "self_discharge_rate",
        ):
            self.assertIn(field, script)
        for message in (
            "数量上下限必须为非负整数",
            "设计年限(年）必须为正整数",
            "成本(万元/台)必须为非负浮点数",
            "容量(kW)必须为正实数",
            "容量(kWh)必须为正实数",
            "容量(Nm3)必须为正实数",
            "电-氢效率(Nm3/kWh)必须为正实数",
            "氢-电效率(kWh/Nm3)必须为正实数",
            "油耗率(kg/kWh)必须为正实数",
            "惯量常数H(s)必须在1.0到10.0之间",
            "一次调频系数K必须在0.1到1.0之间",
            "阻尼系数D必须在0.001到1.0之间",
            "调速时间常数T(s)必须在0.1到2.0之间",
            "等效惯量常数H(s)必须在0.5到10.0之间",
            "等效一次调频系数K必须在0.1到5.0之间",
            "等效阻尼系数D必须在0.001到1.0之间",
            "功率下限(kW)必须为非负实数",
            "切入风速(m/s)必须为非负实数",
            "额定风速(m/s)必须为正实数",
            "切出风速(m/s)必须为非负实数",
            "是否构网必须为0或1",
            "充电效率(0.0-1.0)必须在0到1之间，且必须大于0",
            "放电效率(0.0-1.0)必须在0到1之间，且必须大于0",
            "SOC上限(0.0-1.0)必须在0到1之间",
            "SOC下限(0.0-1.0)必须在0到1之间",
            "自损耗率(0-1%/天)必须在0到0.01之间",
        ):
            self.assertIn(message, script)
        self.assertIn("自损耗率(0-1%/天)", script)
        self.assertIn("充电效率(0.0-1.0)", script)
        self.assertIn("放电效率(0.0-1.0)", script)

    def test_planning_scheme_actions_validate_duplicates_and_delete_current_scheme(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertIn("schemeNameExists", script)
        self.assertIn("normalizeSchemeName", script)
        self.assertIn("\\s\\u0000-\\u001f", script)
        self.assertIn("方案名称已存在", script)
        self.assertIn("是否覆盖", script)
        self.assertIn("payload.overwrite = true", script)
        self.assertIn("deleteScheme", script)
        self.assertIn("DELETE", script)
        self.assertIn("确认删除方案", script)
        self.assertIn("selectNextSchemeAfterDelete", script)

    def test_planning_overview_page_has_statistics_histograms_and_candidate_device_list(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertIn("方案概览", html)
        self.assertNotIn("方案汇总", html)
        self.assertNotIn('id="schemeOverview"', html)
        self.assertNotIn("overviewHost", script)
        self.assertNotIn('id="summaryStats"', html)
        self.assertNotIn("时序统计量", html)
        self.assertIn('id="summaryCharts"', html)
        self.assertIn('id="quantitySummary"', html)
        self.assertIn("待选设备列表", html)
        self.assertIn('class="summary-tabs"', html)
        self.assertIn('data-summary-tab="charts"', html)
        self.assertIn('data-summary-tab="devices"', html)
        self.assertIn('data-summary-tab="planning"', html)
        self.assertIn('data-summary-panel="charts"', html)
        self.assertIn('data-summary-panel="devices"', html)
        self.assertIn('data-summary-panel="planning"', html)
        self.assertNotIn("设计容量约束", html)
        self.assertIn("bindSummaryTabs", script)
        self.assertIn("data-summary-panel", script)
        self.assertIn("renderSchemeSummary", script)
        self.assertNotIn("renderStatsTable", script)
        self.assertIn("renderCandidateDeviceTable", script)
        self.assertIn("capacityValue", script)
        self.assertIn("calculateSeriesStats", script)
        self.assertIn("buildHistogram", script)
        for name in ("风速", "太阳辐照", "温度", "负荷", "最大值", "最小值", "平均值", "数量下限(台)", "数量上限(台)"):
            self.assertIn(name, script)
        self.assertNotIn("formatFixed2", script)
        self.assertIn("formatInteger", script)
        self.assertNotIn(">频数</text>", script)
        self.assertIn("yAxis", script)
        self.assertIn("formatInteger(count)", script)
        self.assertIn("formatInteger(bin.count)", script)
        self.assertIn("histogram-bar", script)
        self.assertIn("data-bin-range", script)
        self.assertIn("data-bin-count", script)
        self.assertIn("onHistogramMouseMove", script)
        self.assertIn("横坐标", script)
        self.assertIn("纵坐标", script)

    def test_planning_overview_page_scrolls_when_content_overflows(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn(".summary-page", css)
        self.assertIn(".summary-switcher", css)
        self.assertIn(".summary-tab-panel.active", css)
        self.assertIn("flex: 1 1 auto", css)
        self.assertIn("overflow: auto", css)

    def test_planning_overview_charts_and_tables_adapt_to_available_height(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        summary_layout_script = script.split("function applyAdaptiveSummaryLayout()", 1)[1].split("function bindTimeResizeHandle()", 1)[0]

        self.assertIn("--summary-panel-height", css)
        self.assertIn("--summary-table-height", css)
        self.assertIn("--summary-histogram-grid-height", css)
        self.assertIn("--summary-histogram-svg-height", css)
        self.assertIn("height: var(--summary-table-height", css)
        self.assertIn("max-height: none", css)
        self.assertNotIn("min(50vh, 560px)", css)
        self.assertIn("height: var(--summary-histogram-grid-height", css)
        self.assertNotIn("min(52vh, 620px)", css)
        self.assertIn("grid-template-rows: repeat(2, minmax(0, 1fr))", css)
        self.assertIn("flex-direction: column", css)
        self.assertIn("applyAdaptiveSummaryLayout", script)
        self.assertIn("summaryTabs", script)
        self.assertIn("summary-histogram-grid-height", script)
        self.assertIn("summary-table-height", script)
        self.assertNotIn("Math.min(560", summary_layout_script)
        self.assertNotIn("Math.min(620", summary_layout_script)

    def test_planning_overview_table_rows_wrap_and_use_adaptive_height(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("#quantitySummary table,", css)
        self.assertIn("#planningSummary table", css)
        self.assertIn("table-layout: fixed", css)
        self.assertIn("#quantitySummary th,", css)
        self.assertIn("#quantitySummary td,", css)
        self.assertIn("#planningSummary th,", css)
        self.assertIn("#planningSummary td", css)
        self.assertNotIn("#limitsTab .data-table table", css)
        self.assertIn("white-space: normal", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("line-height: 1.45", css)
        self.assertIn("min-height: 48px", css)
        self.assertIn("vertical-align: top", css)

    def test_planning_layout_constrains_page_height_to_viewport(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("height: 100vh", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", css)
        self.assertIn("#timeTab #timeTable", css)
        self.assertIn("height: var(--time-chart-height, clamp(180px, 28vh, 300px))", css)

    def test_planning_layout_adapts_chart_and_table_heights_to_viewport(self):
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertIn("--panel-table-max-height", css)
        self.assertIn("--time-table-height", css)
        self.assertIn("height: var(--time-table-height", css)
        self.assertIn("max-height: var(--panel-table-max-height", css)
        self.assertIn("#timeTab.tab-panel.active", css)
        self.assertIn("syncAdaptiveLayout", script)
        self.assertIn("applyAdaptiveTimeSeriesLayout", script)
        self.assertIn("ResizeObserver", script)
        self.assertIn("timeChartManualHeight", script)
        self.assertIn("Math.round(tableHeight)", script)

    def test_planning_frontend_defers_time_series_loading(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertIn("/overview", script)
        self.assertIn("/time-series", script)
        self.assertIn("ensureTimeSeriesLoaded", script)
        self.assertIn("ensureTimeSeriesForActiveTab", script)
        self.assertIn("shouldAutoLoadTimeSeries", script)
        self.assertIn("timeSeriesLoaded", script)
        self.assertIn("时序数据尚未加载", script)
        self.assertIn("进入时序数据或方案概览", script)
        self.assertIn("自动加载", script)
        self.assertNotIn("8760时序数据", script)
        self.assertNotIn("data-load-time-series", script)
        self.assertNotIn("点击加载", script)

    def test_planning_time_series_page_includes_temperature(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertNotIn("8760点曲线板", html)
        for curve_key, label in (
            ("wind_speed", "风速"),
            ("solar_irradiance", "太阳辐照"),
            ("temperature", "温度"),
            ("load", "负荷"),
        ):
            self.assertIn(f'<button type="button" data-curve="{curve_key}"', html)
            self.assertIn(f">{label}</button>", html)
        self.assertNotIn('type="radio"', html)
        self.assertNotIn('name="timeCurve"', html)
        self.assertNotIn('type="checkbox" data-curve', html)
        self.assertIn('class="curve-switch-row"', html)
        self.assertIn('class="curve-button active"', html)
        self.assertIn('aria-pressed="true"', html)
        self.assertLess(html.index('class="weather-import-bar"'), html.index('class="curve-switch-row"'))
        self.assertIn("temperature", script)
        self.assertIn("温度", script)

    def test_planning_time_series_page_can_fetch_geocoded_weather_history(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        for element_id in (
            "importTimeSeriesFile",
            "timeSeriesImportFile",
            "timeSeriesImportModal",
            "timeSeriesImportTitle",
            "openTimeSeriesImportFile",
            "timeSeriesImportHint",
            "timeSeriesImportPreview",
            "timeSeriesImportSummary",
            "confirmTimeSeriesImport",
            "cancelTimeSeriesImport",
            "closeTimeSeriesImport",
            "openLoadGenerator",
            "loadGeneratorModal",
            "loadGeneratorMode",
            "loadGeneratorMax",
            "loadGeneratorMin",
            "loadGeneratorAverage",
            "generateLoadCurve",
            "loadGeneratorPreview",
            "confirmLoadGenerator",
            "cancelLoadGenerator",
            "closeLoadGenerator",
            "weatherPlace",
            "geocodePlace",
            "openCoordinatePicker",
            "weatherLatitude",
            "weatherLongitude",
            "weatherYear",
            "fetchWeatherHistory",
            "weatherImportStatus",
            "mapPickerModal",
            "mapPickerCanvas",
            "closeMapPicker",
            "confirmMapPoint",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('id="weatherYear" type="number" min="2001" step="1" value="2024"', html)
        self.assertIn('accept=".csv,.xlsx"', html)
        weather_bar = html.split('<div class="weather-import-bar"', 1)[1].split("</div>", 1)[0]
        modal = html.split('<div id="mapPickerModal"', 1)[1].split('<div id="timeResizeHandle"', 1)[0]
        import_modal = html.split('<div id="timeSeriesImportModal"', 1)[1].split('<div id="loadGeneratorModal"', 1)[0]
        self.assertIn(">导入曲线<", weather_bar)
        self.assertIn(">负荷生成<", weather_bar)
        self.assertIn(">坐标选择<", weather_bar)
        self.assertLess(weather_bar.index(">导入曲线<"), weather_bar.index(">负荷生成<"))
        self.assertLess(weather_bar.index(">负荷生成<"), weather_bar.index(">坐标选择<"))
        for label in ("打开文件", "风速", "太阳辐射", "室温", "负荷", "确定", "取消"):
            self.assertIn(label, import_modal)
        for label in ("随机曲线", "模式1", "模式2", "模式3", "负荷最大值", "负荷最小值", "负荷平均值", "确定", "取消"):
            self.assertIn(label, html)
        for label in ("高德地图", "百度地图", "谷歌地图"):
            self.assertIn(label, modal)
        for provider in ('data-map-provider="amap"', 'data-map-provider="baidu"', 'data-map-provider="google"'):
            self.assertIn(provider, modal)
        self.assertNotIn('id="weatherPlace"', weather_bar)
        self.assertNotIn('id="geocodePlace"', weather_bar)
        self.assertNotIn(">地图选点</button>", weather_bar)
        self.assertIn('id="weatherPlace"', modal)
        self.assertIn('id="geocodePlace"', modal)
        self.assertIn("根据地名查找坐标", modal)
        self.assertIn("/api/planning/map-config", script)
        self.assertIn("/api/planning/geocode", script)
        self.assertIn("/api/planning/weather-history", script)
        self.assertIn("/api/planning/time-series/import", script)
        self.assertIn("/api/planning/load-curve/generate", script)
        self.assertIn("selectMapProvider", script)
        self.assertIn("loadBaiduMapScript", script)
        self.assertIn("initBaiduMapPicker", script)
        self.assertIn("api.map.baidu.com/api?v=3.0", script)
        self.assertIn("window.BMap", script)
        self.assertIn("loadGoogleMapScript", script)
        self.assertIn("initGoogleMapPicker", script)
        self.assertIn("importTimeSeriesFile", script)
        self.assertIn("openTimeSeriesImportModal", script)
        self.assertIn("openTimeSeriesImportFile", script)
        self.assertIn("onTimeSeriesImportFileChange", script)
        self.assertIn("renderTimeSeriesImportPreview", script)
        self.assertIn("confirmImportedTimeSeries", script)
        self.assertIn("cancelTimeSeriesImport", script)
        self.assertIn("pendingTimeSeriesImport", script)
        self.assertIn("导入曲线已保存到后台", script)
        self.assertIn("isTimeSeriesImportWarning", script)
        self.assertIn('setTimeSeriesImportHint(result.message || "导入文件解析成功，请确认后保存。", level)', script)
        self.assertIn('hint.classList.toggle("warning", level === "warning")', script)
        self.assertIn("#timeSeriesImportHint.warning", css)
        self.assertIn("openLoadGenerator", script)
        self.assertIn("generateLoadCurve", script)
        self.assertIn("renderLoadGeneratorPreview", script)
        self.assertIn("confirmGeneratedLoadCurve", script)
        self.assertIn("cancelLoadGenerator", script)
        self.assertIn("pendingLoadCurve", script)
        self.assertIn("originalLoadCurve", script)
        self.assertIn("修改前", script)
        self.assertIn("修改后", script)
        self.assertIn("applyGeneratedLoadCurve", script)
        self.assertIn("content_base64", script)
        self.assertIn("arrayBufferToBase64", script)
        self.assertIn("导入失败", script)
        self.assertIn("load: curve.load", script)
        self.assertIn("负荷曲线已生成", script)
        self.assertIn("openCoordinatePicker", script)
        self.assertIn("initAmapTilePicker", script)
        self.assertIn("renderAmapTileLayer", script)
        self.assertIn("webrd0${server}.is.autonavi.com", script)
        self.assertIn("osmTileUrl", script)
        self.assertIn("switchAmapTileToGlobalFallback", script)
        self.assertIn("OpenStreetMap 全球底图", script)
        self.assertIn("lngLatToWebMercatorPixel", script)
        self.assertIn("webMercatorPixelToLngLat", script)
        self.assertIn("setMapPoint", script)
        self.assertIn('setMapPoint(result.latitude, result.longitude, "geocode", result)', script)
        self.assertIn("geocodeHintLabel", script)
        self.assertIn("高德定位", script)
        self.assertIn('state.mapInstance.setZoom(11)', script)
        self.assertIn("未配置${mapProviderLabel(state.mapProvider)} Key", script)
        self.assertIn("geocodePlace", script)
        self.assertIn("fetchWeatherHistory", script)
        self.assertIn("validateWeatherInputs", script)
        self.assertIn("历史数据年必须", script)
        self.assertIn("rows.length !== 8760", script)
        self.assertIn("未更新数据", script)
        self.assertIn("wind_speed: weather.wind_speed", script)
        self.assertIn("solar_irradiance: weather.solar_irradiance", script)
        self.assertIn("temperature: weather.temperature", script)
        self.assertNotIn("load: weather.load", script)
        self.assertIn("气象已更新", script)
        self.assertIn("纬度：", script)
        self.assertIn("经度：", script)
        self.assertIn("latitude.toFixed(3)", script)
        self.assertIn("longitude.toFixed(3)", script)
        self.assertNotIn("风速、太阳辐照和温度数据", script)
        self.assertIn(".weather-import-bar", css)
        self.assertIn(".time-series-import-dialog", css)
        self.assertIn(".time-series-import-toolbar", css)
        self.assertIn(".time-series-import-preview", css)
        self.assertIn(".map-provider-tabs", css)
        self.assertIn(".map-provider-tab", css)
        self.assertIn("body.modal-open", css)
        self.assertIn(".load-generator-dialog", css)
        self.assertIn(".load-generator-preview", css)
        self.assertIn("background: var(--hud-panel-strong)", css)
        self.assertIn("border-color: var(--hud-cyan-border)", css)
        self.assertIn("linear-gradient(rgba(33, 213, 255, 0.07)", css)
        self.assertIn(".coordinate-search-row", css)
        self.assertIn(".weather-import-status.error", css)
        self.assertIn(".map-picker-modal", css)
        self.assertIn(".map-picker-canvas", css)

    def test_planning_time_series_table_uses_month_tabs(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn('id="monthTabs"', html)
        self.assertIn('class="time-table-toolbar"', html)
        self.assertNotIn('id="prevPage"', html)
        self.assertNotIn('id="nextPage"', html)
        self.assertNotIn("<h2>小时级数据</h2>", html)
        toolbar = html.split('<div class="time-table-toolbar">', 1)[1].split('<div id="timeTable"', 1)[0]
        self.assertLess(toolbar.index('id="monthTabs"'), toolbar.index('id="pageInfo"'))
        self.assertIn(".time-table-toolbar", css)
        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn("justify-content: flex-start", css)
        self.assertIn("margin-left: auto", css)
        self.assertIn("text-align: right", css)
        self.assertIn("monthRanges", script)
        self.assertIn("renderMonthTabs", script)
        self.assertIn("1月", script)
        self.assertIn("12月", script)

    def test_planning_time_series_chart_height_has_resizable_splitter(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn('id="timeResizeHandle"', html)
        self.assertIn('role="separator"', html)
        self.assertIn("调整时序图高度", html)
        self.assertLess(html.index('id="timeChart"'), html.index('id="timeResizeHandle"'))
        self.assertLess(html.index('id="timeResizeHandle"'), html.index('id="timeTable"'))
        self.assertIn("bindTimeResizeHandle", script)
        self.assertIn("pointerdown", script)
        self.assertIn("--time-chart-height", script)
        self.assertIn("svg.clientHeight", script)
        self.assertIn(".time-resize-handle", css)
        self.assertIn("cursor: row-resize", css)
        self.assertIn("height: var(--time-chart-height", css)

    def test_planning_time_series_input_refreshes_visible_chart(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")
        css = (WEB_ROOT / "assets" / "planning.css").read_text(encoding="utf-8")

        self.assertIn("function onTimeInput", script)
        self.assertIn("renderChart();", script)
        self.assertIn("selectedCurveSpec", script)
        self.assertIn('[data-curve][aria-pressed="true"]', script)
        self.assertIn("selectCurve", script)
        self.assertNotIn("时间（月）", script)
        self.assertIn("monthRanges", script)
        self.assertIn("yTicks", script)
        self.assertIn('stroke="${color}"', script)
        self.assertIn("onChartMouseMove", script)
        self.assertIn("hideChartCursor", script)
        self.assertIn('id="chartCursor"', script)
        self.assertIn('id="chartCursorLine"', script)
        self.assertIn('id="chartCursorPoint"', script)
        self.assertIn("mousemove", script)
        self.assertIn("mouseleave", script)
        self.assertIn(".chart-cursor", css)
        self.assertIn("positionFloatingTipInRect", script)
        self.assertIn("bounds.right - tipWidth - margin", script)
        self.assertIn("bounds.bottom - tipHeight - margin", script)
        self.assertIn("tip.offsetWidth", script)
        self.assertIn("parentRect.left", script)
        self.assertIn(".chart-tip", css)
        self.assertIn("position: absolute", css)
        self.assertIn("z-index: 40", css)
        self.assertIn("white-space: nowrap", css)

    def test_planning_device_fields_follow_latest_parameter_names(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        self.assertNotIn("design_capacity_lower", script)
        self.assertNotIn("design_capacity_upper", script)
        self.assertNotIn("generation_efficiency", script)
        self.assertNotIn("发电效率(0-1.0)", script)
        self.assertIn("氢-电效率(kWh/Nm3)", script)
        self.assertIn("电-氢效率(Nm3/kWh)", script)
        self.assertIn("切入风速(m/s)", script)
        self.assertIn("额定风速(m/s)", script)
        self.assertIn("切出风速(m/s)", script)
        self.assertIn("成本(万元/台)", script)
        self.assertIn("油耗率(kg/kWh)", script)
        self.assertIn("惯量常数H(s)", script)
        self.assertIn("一次调频系数K", script)
        self.assertIn("阻尼系数D", script)
        self.assertIn("调速时间常数T(s)", script)
        self.assertIn("等效惯量常数H(s)", script)
        self.assertIn("等效一次调频系数K", script)
        self.assertIn("等效阻尼系数D", script)
        self.assertIn("功率上限(kW)", script)
        self.assertIn("功率下限(kW)", script)
        self.assertIn('capacity: "容量(kW)"', script)
        self.assertIn('power_capacity: "容量(kW)"', script)
        self.assertIn('battery_capacity: "容量(kWh)"', script)
        self.assertIn('hydrogen_tank_capacity: "容量(Nm3)"', script)
        self.assertNotIn('capacity: "功率容量(kW)"', script)
        self.assertNotIn('power_capacity: "功率容量"', script)
        self.assertNotIn('battery_capacity: "电池容量"', script)
        self.assertNotIn('hydrogen_tank_capacity: "氢储容量(Nm3)"', script)
        self.assertNotIn('hydrogen_tank_capacity: "储氢罐容量"', script)

    def test_planning_device_cost_columns_follow_name(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        for line in script.splitlines():
            if line.strip().startswith("[") and "quantity_upper" in line and "planningParameterSpecs" not in line:
                fields = [item.strip().strip('"') for item in line.split("[", 2)[2].split("]", 1)[0].split(",")]
                self.assertEqual(fields[0], "name")
                self.assertEqual(fields[1], "cost")

    def test_planning_device_tables_include_design_life_column(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        device_spec_lines = [
            line
            for line in script.splitlines()
            if line.strip().startswith("[") and "quantity_upper" in line and "planningParameterSpecs" not in line
        ]
        self.assertEqual(len(device_spec_lines), 8)
        for line in device_spec_lines:
            self.assertIn("design_life_years", line)
            fields = line.split("[", 2)[2].split("]", 1)[0]
            self.assertEqual(fields.rsplit('"', 2)[1], "design_life_years")
        self.assertIn("design_life_years: \"设计年限(年）\"", script)
        self.assertIn("design_life_years: 20", script)

    def test_planning_hydrogen_electrolyzer_table_has_power_lower(self):
        script = (WEB_ROOT / "assets" / "planning.js").read_text(encoding="utf-8")

        electrolyzer_line = next(
            line for line in script.splitlines() if line.strip().startswith('["hydrogen_electrolyzers"')
        )
        self.assertIn("power_lower", electrolyzer_line)
        self.assertLess(electrolyzer_line.index("cost"), electrolyzer_line.index("power_capacity"))
        self.assertLess(electrolyzer_line.index("power_capacity"), electrolyzer_line.index("power_lower"))
        self.assertIn('power_lower: "功率下限(kW)"', script)

    def test_static_path_resolves_index(self):
        resolved = server.resolve_static_path("/")

        self.assertEqual(resolved.name, "index.html")
        self.assertTrue(resolved.exists())

    def test_planning_assets_are_cache_busted_and_static_js_css_png_are_no_cache(self):
        html = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")

        self.assertIn("assets/planning.css?v=", html)
        self.assertIn("assets/planning.js?v=", html)
        self.assertEqual(server.resolve_static_path("/assets/planning.js?v=test").name, "planning.js")
        server_text = (WEB_ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('".css", ".js"', server_text)
        self.assertIn('".png"', server_text)

    def test_static_path_rejects_directory_traversal(self):
        with self.assertRaises(ValueError):
            server.resolve_static_path("/../README.md")


if __name__ == "__main__":
    unittest.main()
