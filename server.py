#!/usr/bin/env python3
"""Static web server and JSON API for the power_plan dashboard."""

from __future__ import annotations

import argparse
import base64
import binascii
from http.cookies import SimpleCookie
import csv
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
from pathlib import Path
import sys
from contextlib import closing
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, unquote, urlparse
from urllib.request import urlopen

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import estimate
import plan_optimizer
import planning_store


WEB_ROOT = Path(__file__).resolve().parent
DATA_DIR = WEB_ROOT / "data"
VENDOR_DIR = WEB_ROOT / "vendor"
USER_DB_PATH = Path(os.environ.get("POWER_PLAN_USER_DB", WEB_ROOT / "power_plan_users.sqlite3"))
SESSION_COOKIE_NAME = "power_plan_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
NASA_POWER_HOURLY_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
AMAP_GEOCODING_URL = "https://restapi.amap.com/v3/geocode/geo"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OPTIMIZATION_RESULT_WORKBOOK_NAME = "optimization_results.xlsx"
RESULT_WORKBOOK_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+_results\.xlsx$")
PLANNING_RESULT_SHEET_NAME = "规划结果"
PLANNING_RESULT_HEADERS = ["设备类型", "设计台数", "单台容量", "总容量", "单位"]
TIME_SERIES_IMPORT_ROW_COUNT = 8760
TIME_SERIES_IMPORT_REQUIRED_COLUMNS = {
    "wind_speed": ("风速", ["wind_speed", "wind", "风速", "风速(m/s)", "风速ms", "ws10m"]),
    "solar_irradiance": ("太阳辐射", ["solar_irradiance", "solar", "irradiance", "太阳辐射", "太阳辐照", "太阳辐射(w/m2)", "太阳辐照(w/m2)", "allsky_sfc_sw_dwn"]),
    "temperature": ("室温", ["temperature", "temp", "室温", "温度", "环境温度", "气温", "t2m"]),
    "load": ("负荷", ["load", "负荷", "负荷功率", "负荷总功率", "负荷(kW)", "负荷kw"]),
}
TIME_SERIES_IMPORT_OPTIONAL_COLUMNS = {
    "datetime": ["datetime", "time", "时间", "日期时间", "时刻"],
}
AMAP_WEB_SERVICE_KEY = os.environ.get("POWER_PLAN_AMAP_KEY") or os.environ.get("AMAP_WEB_SERVICE_KEY") or os.environ.get("AMAP_KEY")
NASA_POWER_PARAMETERS = {
    "wind_speed": "WS10M",
    "solar_irradiance": "ALLSKY_SFC_SW_DWN",
    "temperature": "T2M",
}
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))
DB_CONFIG = {
    "host": os.environ.get("POWER_PLAN_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("POWER_PLAN_DB_PORT", "3306")),
    "user": os.environ.get("POWER_PLAN_DB_USER", "root"),
    "password": os.environ.get("POWER_PLAN_DB_PASSWORD", "scadaems"),
    "database": os.environ.get("POWER_PLAN_DB_NAME", "scadaems"),
    "charset": "utf8mb4",
}


def _coerce_value(value: str) -> float | int | str:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    value = value.strip()
    if value == "":
        return ""
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number


def _metric(label: str, value: float | int | str, unit: str, status: str = "normal") -> dict:
    return {"label": label, "value": value, "unit": unit, "status": status}


def _summary(label: str, value: str, status: str = "normal") -> dict:
    return {"label": label, "value": value, "status": status}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _time_to_hour(value: str) -> float:
    hour, minute = value.split(":", 1)
    return int(hour) + int(minute) / 60


def _hour_to_time(value: float) -> str:
    value = value % 24
    hour = int(value)
    minute = int(round((value - hour) * 60)) % 60
    return f"{hour:02d}:{minute:02d}"


class SimuRuntime:
    """In-memory runtime state for simulation controls."""

    def __init__(self, initial_time: str = "00:00", speed: float = 1.0, status: str = "STOPPED") -> None:
        self.cursor_hour = _time_to_hour(initial_time)
        self.speed = speed
        self.status = status
        self._last_tick = time.monotonic()
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            self._advance_locked()
            return {
                "sim_time": _hour_to_time(self.cursor_hour),
                "cursor_hour": round(self.cursor_hour, 3),
                "speed": self.speed,
                "status": self.status,
            }

    def apply(self, action: str) -> dict:
        with self._lock:
            self._advance_locked()
            if action == "start":
                self.status = "RUNNING"
            elif action == "faster":
                self.speed = min(16.0, self.speed * 2)
            elif action == "slower":
                self.speed = max(0.25, self.speed / 2)
            elif action == "stop":
                self.status = "STOPPED"
            elif action == "reset":
                self.cursor_hour = 0.0
                self.speed = 1.0
                self.status = "STOPPED"
            else:
                raise ValueError(f"unknown SIMU action: {action}")
            self._last_tick = time.monotonic()
            return {
                "sim_time": _hour_to_time(self.cursor_hour),
                "cursor_hour": round(self.cursor_hour, 3),
                "speed": self.speed,
                "status": self.status,
            }

    def _advance_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_tick
        if self.status == "RUNNING":
            # One real second advances one simulated minute at speed=1.
            self.cursor_hour = (self.cursor_hour + elapsed * self.speed / 60) % 24
            self._last_tick = now


class UserStore:
    """SQLite-backed user and session store."""

    def __init__(self, db_path: Path = USER_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            connection.commit()

    def user_count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username: str, password: str, role: str | None = None) -> dict:
        clean_username = self._clean_username(username)
        if len(password or "") < 6:
            raise ValueError("密码长度不能少于6位")
        with self._lock:
            user_role = role or ("admin" if self.user_count() == 0 else "user")
            if user_role not in {"admin", "user"}:
                raise ValueError("用户角色不合法")
            salt, password_hash = self._hash_password(password)
            try:
                with closing(self._connect()) as connection:
                    cursor = connection.execute(
                        """
                        INSERT INTO users (username, password_salt, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (clean_username, salt, password_hash, user_role, _now_iso()),
                    )
                    connection.commit()
                    user_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError as exc:
                raise ValueError("用户名已存在") from exc
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("用户创建失败")
        return user

    def authenticate(self, username: str, password: str) -> dict:
        clean_username = self._clean_username(username)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, username, password_salt, password_hash, role, created_at FROM users WHERE username = ?",
                (clean_username,),
            ).fetchone()
        if not row or not self._verify_password(password or "", row["password_salt"], row["password_hash"]):
            raise ValueError("用户名或密码错误")
        return self._public_user(row)

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, _now_iso(), now + SESSION_MAX_AGE_SECONDS),
            )
            connection.commit()
        return token

    def delete_session(self, token: str) -> None:
        if not token:
            return
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
            connection.commit()

    def user_for_session(self, token: str) -> dict | None:
        if not token:
            return None
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            row = connection.execute(
                """
                SELECT users.id, users.username, users.role, users.created_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (token, now),
            ).fetchone()
            connection.commit()
        return self._public_user(row) if row else None

    def list_users(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, username, role, created_at FROM users ORDER BY id"
            ).fetchall()
        return [self._public_user(row) for row in rows]

    def get_user_by_id(self, user_id: int) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, username, role, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._public_user(row) if row else None

    def update_role(self, user_id: int, role: str) -> dict:
        if role not in {"admin", "user"}:
            raise ValueError("用户角色不合法")
        with closing(self._connect()) as connection:
            connection.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            connection.commit()
        user = self.get_user_by_id(user_id)
        if not user:
            raise FileNotFoundError("用户不存在")
        return user

    def delete_user(self, user_id: int, current_user_id: int | None = None) -> None:
        if current_user_id is not None and int(user_id) == int(current_user_id):
            raise ValueError("不能删除当前登录用户")
        with closing(self._connect()) as connection:
            cursor = connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            connection.commit()
        if cursor.rowcount == 0:
            raise FileNotFoundError("用户不存在")

    @staticmethod
    def _clean_username(username: str) -> str:
        clean = str(username or "").strip()
        if len(clean) < 2 or len(clean) > 32:
            raise ValueError("用户名长度应为2-32位")
        if any(ord(char) < 32 or char.isspace() for char in clean):
            raise ValueError("用户名不能包含空格或不可见字符")
        return clean

    @staticmethod
    def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
        password_salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(password_salt), 120_000)
        return password_salt, digest.hex()

    @classmethod
    def _verify_password(cls, password: str, salt: str, expected_hash: str) -> bool:
        _, actual_hash = cls._hash_password(password, salt)
        return hmac.compare_digest(actual_hash, expected_hash)

    @staticmethod
    def _public_user(row) -> dict:
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "role": row["role"],
            "created_at": row["created_at"],
        }


class OptimizationRuntime:
    """In-memory runtime state for the planning optimization page."""

    def __init__(self, scheme: str = "") -> None:
        self.status = "待启动"
        self.scheme = str(scheme or "").strip()
        self.start_time = ""
        self.end_time = ""
        self.progress = 0
        self._started_monotonic = 0.0
        self._last_progress_log = -1
        self.result_file = ""
        self._metrics: list[dict] = []
        self._results: dict = {}
        self._results_exported = False
        self._logs: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._run_token = 0
        self._append_log_unlocked("info", "规划求解待启动")

    def snapshot(self) -> dict:
        with self._lock:
            return self._payload_unlocked()

    def apply(self, action: str, scheme: str = "") -> dict:
        target_scheme = str(scheme or self.scheme or "未选择方案").strip() or "未选择方案"
        if action == "clear_logs":
            with self._lock:
                self.scheme = target_scheme
                self._logs.clear()
                return self._payload_unlocked()

        if action == "start":
            with self._lock:
                if self.status == "运行中":
                    if self.scheme == target_scheme:
                        raise OptimizationStateError("running", f"方案“{target_scheme}”正在运行，无法再次启动")
                    raise OptimizationStateError("running", f"方案“{self.scheme}”正在运行，无法启动方案“{target_scheme}”")
                self.status = "运行中"
                self.scheme = target_scheme
                self.start_time = _now_text()
                self.end_time = ""
                self.progress = 0
                self._started_monotonic = time.monotonic()
                self._last_progress_log = -1
                self.result_file = ""
                self._metrics = []
                self._results = {}
                self._results_exported = False
                self._stop_requested = False
                self._run_token += 1
                token = self._run_token
                self._append_log_unlocked("ok", f"启动规划求解，方案：{self.scheme}")
                self._append_log_unlocked("info", "后台规划求解程序已启动")
                self._thread = threading.Thread(
                    target=self._run_optimization,
                    args=(token, target_scheme),
                    daemon=True,
                )
                self._thread.start()
                return self._payload_unlocked()

        if action == "stop":
            with self._lock:
                if self.status != "运行中" or self.scheme != target_scheme:
                    raise OptimizationStateError("not_running", f"方案“{target_scheme}”没有运行")
                self._stop_requested = True
                self.status = "已停止"
                self.end_time = _now_text()
                self._append_log_unlocked("warn", "停止规划求解")
                return self._payload_unlocked()

        raise ValueError(f"unknown optimization action: {action}")

    def _advance_locked(self) -> None:
        if self.status != "运行中":
            return
        elapsed = max(0.0, time.monotonic() - self._started_monotonic)
        self.progress = min(100, int(elapsed * 3))
        progress_bucket = min(100, (self.progress // 10) * 10)
        if progress_bucket >= 10 and progress_bucket != self._last_progress_log:
            self._last_progress_log = progress_bucket
            self._append_log_unlocked("info", f"优化迭代进度 {progress_bucket}%")
        if self.progress >= 100:
            self.status = "已完成"
            self.end_time = _now_text()
            self._append_log_unlocked("ok", "规划求解完成")
            self._export_results_once_unlocked()

    def _payload_unlocked(self) -> dict:
        return {
            "status": self.status,
            "scheme": self.scheme,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "progress": self.progress,
            "result_file": self.result_file,
            "metrics": self._metrics_unlocked(),
            "results": self._results if self._results else self._default_results_unlocked(),
            "logs": list(self._logs),
        }

    def _metrics_unlocked(self) -> list[dict]:
        base = [
            {"label": "当前状态", "value": self.status, "unit": ""},
            {"label": "启动时刻", "value": self.start_time or "-", "unit": ""},
            {"label": "结束时刻", "value": self.end_time or "-", "unit": ""},
        ]
        existing_labels = {item["label"] for item in base}
        for metric in self._metrics:
            if not isinstance(metric, dict):
                continue
            label = metric.get("label", "")
            if label in existing_labels:
                continue
            base.append(metric)
            existing_labels.add(label)
        if "度电成本" not in existing_labels:
            base.append({"label": "度电成本", "value": "-", "unit": "元/kWh"})
        if "绿电占比" not in existing_labels:
            base.append({"label": "绿电占比", "value": "-", "unit": "%"})
        return base

    @staticmethod
    def _default_results_unlocked() -> dict:
        return {
            "overview_tables": [
                {"title": "规划结果", "rows": []},
                {"title": "规划年指标", "rows": []},
            ],
            "overview_disks": [],
            "overview": [],
            "green": [],
            "green_table": [],
            "safety": [],
            "safety_table": [],
            "curves": {"green_daily": [], "green_monthly": [], "green_hourly": [], "safety_daily": []},
        }

    def _run_optimization(self, token: int, scheme: str) -> None:
        try:
            self._append_log("info", "读取方案参数和8760时序数据", None, token)
            scheme_payload = PLANNING_STORE.read_scheme(scheme)
            result = plan_optimizer.run_optimization(
                scheme_payload,
                log=lambda event: self._append_optimizer_event(event, token),
            )
            with self._lock:
                if token != self._run_token or self._stop_requested or self.status != "运行中":
                    return
                self.progress = 100
                self._metrics = result.get("metrics") if isinstance(result.get("metrics"), list) else []
                self._results = result.get("results") if isinstance(result.get("results"), dict) else {}
                self.status = "已完成"
                self.end_time = _now_text()
                result_path = export_optimization_results_workbook(self._payload_unlocked())
                self.result_file = str(result_path)
                self._results_exported = True
                self._append_log_unlocked("ok", f"优化结果已写入：{result_path.name}")
        except Exception as exc:
            with self._lock:
                if token != self._run_token:
                    return
                self.status = "失败"
                self.end_time = _now_text()
                self._append_log_unlocked("error", f"规划求解失败：{exc}")

    def _append_optimizer_event(self, event: dict, token: int) -> None:
        level = str(event.get("level") or "info")
        message = str(event.get("message") or "")
        progress = event.get("progress")
        self._append_log(level, message, progress if isinstance(progress, int) else None, token)

    def _append_log(self, level: str, message: str, progress: int | None, token: int) -> None:
        with self._lock:
            if token != self._run_token:
                return
            if progress is not None:
                self.progress = max(self.progress, min(100, max(0, int(progress))))
            if message:
                self._append_log_unlocked(level, message)

    def _results_unlocked(self) -> dict:
        cost = round(max(0.42, 0.78 - self.progress * 0.002), 3)
        green_ratio = round(min(92.0, 52.0 + self.progress * 0.34), 1)
        reserve_margin = round(max(12.0, 28.0 - self.progress * 0.05), 1)
        frequency_margin = round(1.08 + min(0.12, self.progress * 0.001), 3)
        curtailed_ratio = round(max(1.0, 9.0 - self.progress * 0.04), 1)
        diesel_energy = round(max(480, 1580 - self.progress * 7.2), 1)
        wind_energy = round(2260 + self.progress * 8.6, 1)
        pv_energy = round(1880 + self.progress * 7.4, 1)
        storage_energy = round(720 + self.progress * 3.5, 1)
        hydrogen_production = round(148 + self.progress * 1.1, 1)
        fuel_cell_energy = round(420 + self.progress * 2.6, 1)
        construction_cost = 2180.0
        operation_cost = round(980 - self.progress * 1.4, 1)
        renewable_energy = round(wind_energy + pv_energy + fuel_cell_energy, 1)
        load_energy_kwh = 6840.0 * 1000
        diesel_energy_kwh = diesel_energy * 1000
        wind_energy_kwh = wind_energy * 1000
        pv_energy_kwh = pv_energy * 1000
        storage_energy_kwh = storage_energy * 1000
        storage_charge_energy_kwh = round(storage_energy_kwh / 0.9, 1)
        fuel_cell_energy_kwh = fuel_cell_energy * 1000
        hydrogen_production_nm3 = hydrogen_production * 10000
        hydrogen_production_energy_kwh = hydrogen_production_nm3 / 0.2
        seed_green_daily = self._green_daily_curve_unlocked(
            load_energy_kwh,
            diesel_energy_kwh,
            wind_energy_kwh,
            pv_energy_kwh,
            fuel_cell_energy_kwh,
            hydrogen_production_energy_kwh,
            storage_energy_kwh,
            storage_charge_energy_kwh,
        )
        green_hourly = self._green_hourly_curve_unlocked(seed_green_daily)
        green_daily = estimate.aggregate_daily(green_hourly)
        green_monthly = estimate.aggregate_monthly(green_daily)
        energy_totals = self._energy_totals_from_daily_unlocked(green_daily)
        energy_totals["hydrogen_production"] = hydrogen_production_nm3
        energy_totals["diesel_consumption"] = round(diesel_energy * 0.24, 1)
        annual_energy_rows = estimate.annual_energy_rows(
            energy_totals,
            energy_totals["renewable_ratio"],
            energy_totals["renewable_curtailed_rate"],
        )
        safety_daily = self._safety_daily_frequency_curve_unlocked()
        highest_frequency = max(point["frequency_max"] for point in safety_daily)
        lowest_frequency = min(point["frequency_min"] for point in safety_daily)
        upward_disturbance = round(max(860.0, 1480.0 - self.progress * 5.8), 1)
        downward_disturbance = round(max(720.0, 1310.0 - self.progress * 5.1), 1)
        frequency_risk_hours = max(0, int(round(68 - self.progress * 0.55)))
        return {
            "overview_tables": [
                {
                    "title": "规划结果",
                    "rows": [
                        {"设备类型": "柴发", "设计台数": 2, "单台容量": 320, "总容量": 640, "单位": "kW"},
                        {"设备类型": "风机", "设计台数": 6, "单台容量": 120, "总容量": 720, "单位": "kW"},
                        {"设备类型": "光伏", "设计台数": 18, "单台容量": 55, "总容量": 990, "单位": "kW"},
                        {"设备类型": "储能", "设计台数": 4, "单台容量": 250, "总容量": 1000, "单位": "kWh"},
                        {"设备类型": "电制氢", "设计台数": 2, "单台容量": 180, "总容量": 360, "单位": "kW"},
                        {"设备类型": "储氢罐", "设计台数": 3, "单台容量": 420, "总容量": 1260, "单位": "Nm3"},
                        {"设备类型": "燃料电池", "设计台数": 2, "单台容量": 160, "总容量": 320, "单位": "kW"},
                    ],
                },
                {
                    "title": "规划年指标",
                    "rows": [
                        {"指标": "柴发总容量", "数值": 640, "单位": "kW"},
                        {"指标": "风电总容量", "数值": 720, "单位": "kW"},
                        {"指标": "光伏总容量", "数值": 990, "单位": "kW"},
                        {"指标": "氢能总容量", "数值": 320, "单位": "kW"},
                        {"指标": "储能总容量", "数值": 1000, "单位": "kWh"},
                        {"指标": "负荷总电量", "数值": 6840.0, "单位": "MWh"},
                        {"指标": "柴发总电量", "数值": diesel_energy, "单位": "MWh"},
                        {"指标": "风能总电量", "数值": wind_energy, "单位": "MWh"},
                        {"指标": "光伏总电量", "数值": pv_energy, "单位": "MWh"},
                        {"指标": "弃电量", "数值": round(420 - self.progress * 2.1, 1), "单位": "MWh"},
                        {"指标": "储能总电量", "数值": storage_energy, "单位": "MWh"},
                        {"指标": "制氢总量", "数值": hydrogen_production, "单位": "万Nm3"},
                        {"指标": "燃料电池发电量", "数值": fuel_cell_energy, "单位": "MWh"},
                        *annual_energy_rows,
                        {"指标": "总成本", "数值": round(3280 - self.progress * 3.2, 1), "单位": "万元"},
                        {"指标": "绿电占比", "数值": green_ratio, "单位": "%"},
                        {"指标": "频率风险点", "数值": max(0, 6 - self.progress // 18), "单位": "个"},
                    ],
                },
            ],
            "overview_disks": [
                {
                    "title": "成本构成",
                    "left_label": "运行成本",
                    "left_value": operation_cost,
                    "right_label": "建设成本",
                    "right_value": construction_cost,
                    "unit": "万元",
                },
                {
                    "title": "电量构成",
                    "left_label": "柴发电量",
                    "left_value": diesel_energy,
                    "right_label": "新能源电量",
                    "right_value": renewable_energy,
                    "unit": "MWh",
                },
            ],
            "overview": [
                {"指标": "度电成本", "数值": cost, "单位": "元/kWh", "说明": "基于当前候选方案的综合成本估计"},
                {"指标": "绿电占比", "数值": green_ratio, "单位": "%", "说明": "风光与氢储供电占比"},
                {"指标": "优化进度", "数值": self.progress, "单位": "%", "说明": self.status},
            ],
            "green": [
                {"指标": "风电消纳率", "数值": round(min(98.0, 82.0 + self.progress * 0.08), 1), "单位": "%", "说明": "风机出力消纳水平"},
                {"指标": "光伏消纳率", "数值": round(min(98.5, 84.0 + self.progress * 0.07), 1), "单位": "%", "说明": "光伏出力消纳水平"},
                {"指标": "弃电率", "数值": round(max(1.0, 9.0 - self.progress * 0.04), 1), "单位": "%", "说明": "新能源未利用电量占比"},
            ],
            "green_table": [
                *annual_energy_rows,
                {"指标": "负荷总电量", "数值": round(load_energy_kwh, 1), "单位": "kWh"},
                {"指标": "柴发总电量", "数值": round(diesel_energy_kwh, 1), "单位": "kWh"},
                {"指标": "风机总发电量", "数值": round(wind_energy_kwh, 1), "单位": "kWh"},
                {"指标": "光伏总发电量", "数值": round(pv_energy_kwh, 1), "单位": "kWh"},
                {"指标": "电储总发电量", "数值": round(storage_energy_kwh, 1), "单位": "kWh"},
                {"指标": "氢储总发电量", "数值": round(fuel_cell_energy_kwh, 1), "单位": "kWh"},
                {"指标": "新能源弃电率", "数值": energy_totals["renewable_curtailed_rate"], "单位": "%"},
                {"指标": "柴油消耗", "数值": round(diesel_energy * 0.24, 1), "单位": "吨"},
                {"指标": "制氢总量", "数值": round(hydrogen_production_nm3, 1), "单位": "Nm3"},
            ],
            "safety": [
                {"指标": "备用裕度", "数值": reserve_margin, "单位": "%", "说明": "负荷扰动后的可用备用"},
                {"指标": "频率安全裕度", "数值": frequency_margin, "单位": "p.u.", "说明": "频率约束裕度"},
                {"指标": "N-1校核", "数值": "通过" if self.progress >= 35 else "计算中", "单位": "", "说明": "新能源 N-1 约束校核"},
            ],
            "safety_table": [
                {"指标": "向上扰动最大量", "数值": upward_disturbance, "单位": "kW"},
                {"指标": "向下扰动最大量", "数值": downward_disturbance, "单位": "kW"},
                {"指标": "最高频率", "数值": highest_frequency, "单位": "Hz"},
                {"指标": "最低频率", "数值": lowest_frequency, "单位": "Hz"},
                {"指标": "频率安全风险小时数", "数值": frequency_risk_hours, "单位": "h"},
            ],
            "curves": {
                "overview": [
                    {"label": "20%", "value": round(cost + 0.08, 3)},
                    {"label": "40%", "value": round(cost + 0.05, 3)},
                    {"label": "60%", "value": round(cost + 0.03, 3)},
                    {"label": "80%", "value": round(cost + 0.01, 3)},
                    {"label": "当前", "value": cost},
                ],
                "green": [
                    {"label": "风电", "value": round(min(98.0, 82.0 + self.progress * 0.08), 1)},
                    {"label": "光伏", "value": round(min(98.5, 84.0 + self.progress * 0.07), 1)},
                    {"label": "氢储", "value": round(min(90.0, 66.0 + self.progress * 0.09), 1)},
                    {"label": "总体", "value": green_ratio},
                ],
                "green_daily": green_daily,
                "green_monthly": green_monthly,
                "green_hourly": green_hourly,
                "safety": [
                    {"label": "备用", "value": reserve_margin},
                    {"label": "频率", "value": round(frequency_margin * 10, 2)},
                    {"label": "N-1", "value": 100 if self.progress >= 35 else max(10, self.progress)},
                ],
                "safety_daily": safety_daily,
            },
        }

    @staticmethod
    def _energy_totals_from_daily_unlocked(daily_rows: list[dict[str, float | int]]) -> dict[str, float]:
        totals = {
            field: round(sum(float(row.get(field, 0.0) or 0.0) for row in daily_rows), 4)
            for field in estimate.ENERGY_AGGREGATE_FIELDS
        }
        estimate.add_energy_ratios(totals)
        return totals

    def _green_daily_curve_unlocked(
        self,
        load_total: float,
        diesel_total: float,
        wind_total: float,
        pv_total: float,
        hydrogen_total: float,
        hydrogen_production_total: float,
        storage_discharge_total: float,
        storage_charge_total: float,
    ) -> list[dict[str, float | int]]:
        days = list(range(1, 366))

        def seasonal(day: int, phase_shift: float, amplitude: float, second: float = 0.0) -> float:
            phase = 2 * math.pi * (day - 1) / 365
            return max(0.05, 1 + amplitude * math.sin(phase + phase_shift) + second * math.sin(phase * 2 + phase_shift / 2))

        raw = {
            "load_energy": [seasonal(day, -0.25, 0.12, 0.05) for day in days],
            "diesel_energy": [seasonal(day, 0.8, 0.18, 0.03) for day in days],
            "wind_energy": [seasonal(day, 1.25, 0.22, 0.05) for day in days],
            "pv_energy": [seasonal(day, -1.15, 0.34, 0.04) for day in days],
            "hydrogen_energy": [seasonal(day, 0.35, 0.16, 0.03) for day in days],
            "hydrogen_production_energy": [seasonal(day, -0.75, 0.2, 0.04) for day in days],
            "storage_discharge_energy": [seasonal(day, 0.1, 0.11, 0.06) for day in days],
            "storage_charge_energy": [seasonal(day, -0.9, 0.18, 0.05) for day in days],
        }
        totals = {
            "load_energy": load_total,
            "diesel_energy": diesel_total,
            "wind_energy": wind_total,
            "pv_energy": pv_total,
            "hydrogen_energy": hydrogen_total,
            "hydrogen_production_energy": hydrogen_production_total,
            "storage_discharge_energy": storage_discharge_total,
            "storage_charge_energy": storage_charge_total,
        }
        scaled: dict[str, list[float]] = {}
        for key, values in raw.items():
            raw_total = sum(values) or 1
            scaled[key] = [round(totals[key] * value / raw_total, 1) for value in values]

        return [
            {
                "day": day,
                "diesel_energy": scaled["diesel_energy"][index],
                "wind_energy": scaled["wind_energy"][index],
                "pv_energy": scaled["pv_energy"][index],
                "hydrogen_energy": scaled["hydrogen_energy"][index],
                "storage_discharge_energy": scaled["storage_discharge_energy"][index],
                "load_energy": scaled["load_energy"][index],
                "hydrogen_production_energy": scaled["hydrogen_production_energy"][index],
                "storage_charge_energy": scaled["storage_charge_energy"][index],
            }
            for index, day in enumerate(days)
        ]

    def _safety_daily_frequency_curve_unlocked(self) -> list[dict[str, float | int]]:
        days = list(range(1, 366))
        max_deviation_base = max(0.07, 0.22 - self.progress * 0.0012)
        min_deviation_base = max(0.06, 0.2 - self.progress * 0.001)
        points = []
        for day in days:
            phase = 2 * math.pi * (day - 1) / 365
            frequency_max = 50 + max_deviation_base + 0.035 * math.sin(phase + 0.7) + 0.012 * math.sin(phase * 2.4)
            frequency_min = 50 - min_deviation_base - 0.032 * math.cos(phase - 0.25) - 0.01 * math.sin(phase * 2.1)
            points.append(
                {
                    "day": day,
                    "frequency_max": round(frequency_max, 3),
                    "frequency_min": round(frequency_min, 3),
                }
            )
        return points

    def _green_hourly_curve_unlocked(self, daily_points: list[dict[str, float | int]]) -> list[dict[str, float | int | str]]:
        rows: list[dict[str, float | int | str]] = []
        hour_index = 1
        for day_point in daily_points:
            day = int(day_point.get("day") or 1)
            for hour in range(24):
                load_shape = 0.85 + 0.28 * math.sin((hour - 7) / 24 * 2 * math.pi) + 0.12 * math.sin((hour - 18) / 24 * 4 * math.pi)
                wind_shape = 0.9 + 0.18 * math.sin((hour + 3) / 24 * 2 * math.pi)
                daylight = max(0.0, math.sin((hour - 6) / 12 * math.pi))
                storage_discharge_shape = 1.0 + 0.35 * math.sin((hour - 17) / 24 * 2 * math.pi)
                storage_charge_shape = 0.35 + daylight

                load = max(0.0, float(day_point.get("load_energy", 0.0)) * load_shape / 24)
                wind_power = max(0.0, float(day_point.get("wind_energy", 0.0)) * wind_shape / 24)
                pv_power = max(0.0, float(day_point.get("pv_energy", 0.0)) * daylight / 7.6)
                storage_discharge = max(0.0, float(day_point.get("storage_discharge_energy", 0.0)) * storage_discharge_shape / 24)
                storage_charge = max(0.0, float(day_point.get("storage_charge_energy", 0.0)) * storage_charge_shape / 24)
                diesel_power = max(0.0, float(day_point.get("diesel_energy", 0.0)) * (1.0 + 0.16 * math.sin((hour + 9) / 24 * 2 * math.pi)) / 24)
                renewable_surplus = max(0.0, wind_power + pv_power + storage_discharge + diesel_power - load - storage_charge)
                curtailed_power = min(renewable_surplus, max(0.0, float(day_point.get("wind_energy", 0.0)) + float(day_point.get("pv_energy", 0.0))) / 24)
                unmet_load = max(0.0, load + storage_charge - wind_power - pv_power - storage_discharge - diesel_power)
                storage_soc = max(0.0, min(100.0, 52.0 + 30.0 * math.sin((day + hour / 24) / 365 * 2 * math.pi) + 12.0 * math.sin((hour - 5) / 24 * 2 * math.pi)))
                wind_speed = max(0.0, 7.5 + 2.2 * math.sin((day + hour / 24) / 365 * 2 * math.pi) + 1.1 * math.sin((hour + 2) / 24 * 2 * math.pi))
                solar_irradiance = max(0.0, daylight * (780.0 + 120.0 * math.sin((day - 80) / 365 * 2 * math.pi)))
                temperature = -5.0 + 18.0 * math.sin((day - 80) / 365 * 2 * math.pi) + 4.0 * math.sin((hour - 14) / 24 * 2 * math.pi)
                wind_available = wind_power + curtailed_power * 0.55
                pv_available = pv_power + curtailed_power * 0.45
                wind_curtailed_power = max(0.0, wind_available - wind_power)
                pv_curtailed_power = max(0.0, pv_available - pv_power)
                renewable_available = wind_available + pv_available
                renewable_power = wind_power + pv_power
                renewable_curtailed_power = wind_curtailed_power + pv_curtailed_power
                rows.append(
                    {
                        "hour_index": hour_index,
                        "datetime": f"D{day:03d} H{hour + 1:02d}",
                        "wind_speed": round(wind_speed, 4),
                        "solar_irradiance": round(solar_irradiance, 4),
                        "temperature": round(temperature, 4),
                        "load": round(load, 4),
                        "diesel_power": round(diesel_power, 4),
                        "wind_available": round(wind_available, 4),
                        "wind_power": round(wind_power, 4),
                        "pv_available": round(pv_available, 4),
                        "pv_power": round(pv_power, 4),
                        "renewable_available": round(renewable_available, 4),
                        "renewable_ratio": round(renewable_power / load * 100 if load else 0.0, 4),
                        "storage_power": round(storage_discharge - storage_charge, 4),
                        "storage_soc": round(storage_soc, 4),
                        "hydrogen_production_power": 0,
                        "hydrogen_storage": 0,
                        "fuel_cell_power": 0,
                        "wind_curtailed_power": round(wind_curtailed_power, 4),
                        "pv_curtailed_power": round(pv_curtailed_power, 4),
                        "curtailed_power": round(renewable_curtailed_power, 4),
                        "renewable_curtailed_rate": round(renewable_curtailed_power / renewable_available * 100 if renewable_available else 0.0, 4),
                        "unmet_load": round(unmet_load, 4),
                        "diesel_on": 1 if diesel_power > 0 else 0,
                        "electrolyzer_on": 0,
                        "storage_charge": round(storage_charge, 4),
                        "storage_discharge": round(storage_discharge, 4),
                    }
                )
                hour_index += 1
        return rows[:8760]

    def _append_log_unlocked(self, level: str, message: str) -> None:
        self._logs.append({"time": _now_text(), "level": level, "message": message})
        if len(self._logs) > 2000:
            del self._logs[:-2000]

    def _export_results_once_unlocked(self) -> None:
        if self._results_exported:
            return
        result_path = export_optimization_results_workbook(self._payload_unlocked())
        self.result_file = str(result_path)
        self._results_exported = True


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class OptimizationStateError(RuntimeError):
    """Raised when optimization start/stop violates the current runtime state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def export_optimization_results_workbook(payload: dict) -> Path:
    scheme = str(payload.get("scheme") or "未选择方案")
    result_path = PLANNING_STORE.scheme_dir(scheme) / OPTIMIZATION_RESULT_WORKBOOK_NAME
    result_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = build_optimization_results_workbook(payload)
    tmp_path = result_path.with_name(f".{result_path.name}.tmp")
    workbook.save(tmp_path)
    tmp_path.replace(result_path)
    return result_path


def export_evaluation_results_workbook(payload: dict, dispatch_rows: list[dict]) -> Path:
    scheme = str(payload.get("scheme") or "未选择方案")
    filename = str(payload.get("result_filename") or "").strip()
    result_path = evaluation_result_path(scheme, filename)
    if result_path.name == OPTIMIZATION_RESULT_WORKBOOK_NAME:
        raise ValueError("默认结果文件不允许修改")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = build_optimization_results_workbook(payload)
    tmp_path = result_path.with_name(f".{result_path.name}.tmp")
    workbook.save(tmp_path)
    tmp_path.replace(result_path)
    return result_path


def build_optimization_results_workbook(payload: dict) -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)
    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), list) else []
    logs = payload.get("logs") if isinstance(payload.get("logs"), list) else []
    curves = results.get("curves") if isinstance(results.get("curves"), dict) else {}

    append_rows_sheet(
        workbook,
        "总体指标",
        [
            {"指标": "方案", "数值": payload.get("scheme", ""), "单位": ""},
            {"指标": "状态", "数值": payload.get("status", ""), "单位": ""},
            {"指标": "进度", "数值": payload.get("progress", ""), "单位": "%"},
            *[
                {
                    "指标": metric.get("label", ""),
                    "数值": metric.get("value", ""),
                    "单位": metric.get("unit", ""),
                }
                for metric in metrics
            ],
        ],
        ["指标", "数值", "单位"],
    )

    for table in results.get("overview_tables", []):
        append_rows_sheet(workbook, str(table.get("title", "结果表")), table.get("rows", []))
    append_rows_sheet(workbook, "供能分析", results.get("green_table", []))
    append_rows_sheet(workbook, "供能日曲线", curves.get("green_daily", []))
    append_rows_sheet(workbook, "供能月曲线", curves.get("green_monthly", []))
    append_rows_sheet(workbook, "安全评估", results.get("safety_table", []))
    append_rows_sheet(workbook, "安全日曲线", curves.get("safety_daily", []))
    append_dispatch_rows_sheet(workbook, curves.get("green_hourly", []))
    append_rows_sheet(workbook, "运行日志", logs, ["time", "level", "message"], {"time": "时间", "level": "级别", "message": "消息"})
    return workbook


def append_dispatch_rows_sheet(workbook: Workbook, dispatch_rows: list[dict]) -> None:
    append_rows_sheet(
        workbook,
        "调度结果",
        dispatch_rows,
        [
            "hour_index",
            "datetime",
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
            "renewable_ratio",
            "renewable_curtailed_rate",
            "storage_power",
            "storage_soc",
            "hydrogen_production_power",
            "hydrogen_storage",
            "fuel_cell_power",
            "wind_curtailed_power",
            "pv_curtailed_power",
            "curtailed_power",
            "unmet_load",
            "diesel_on",
            "electrolyzer_on",
            "storage_charge",
            "storage_discharge",
        ],
        {
            "hour_index": "小时",
            "datetime": "时间",
            "wind_speed": "风速",
            "solar_irradiance": "太阳辐射",
            "temperature": "环境温度",
            "load": "负荷总功率",
            "diesel_power": "柴发总功率",
            "wind_available": "风力最大可发",
            "wind_power": "风机总功率",
            "pv_available": "光伏最大可发",
            "pv_power": "光伏总功率",
            "renewable_available": "新能源最大可发",
            "renewable_ratio": "新能源占比",
            "renewable_curtailed_rate": "新能源弃电率",
            "storage_power": "电储能总功率",
            "storage_soc": "电储电量",
            "hydrogen_production_power": "电制氢总功率",
            "hydrogen_storage": "储氢罐氢储量",
            "fuel_cell_power": "燃料电池总功率",
            "wind_curtailed_power": "弃风总功率",
            "pv_curtailed_power": "弃光总功率",
            "curtailed_power": "新能源弃电总功率",
            "unmet_load": "切负荷功率",
            "diesel_on": "柴发启停",
            "electrolyzer_on": "制氢启停",
            "storage_charge": "储能充电",
            "storage_discharge": "储能放电",
        },
    )


def append_rows_sheet(
    workbook: Workbook,
    title: str,
    rows: list[dict],
    headers: list[str] | None = None,
    labels: dict[str, str] | None = None,
) -> None:
    sheet = workbook.create_sheet(safe_sheet_title(title, workbook.sheetnames))
    normalized_rows = rows if isinstance(rows, list) else []
    header_keys = headers or keys_from_rows(normalized_rows)
    if not header_keys:
        header_keys = ["内容"]
    header_labels = labels or {}
    sheet.append([header_labels.get(key, key) for key in header_keys])
    for row in normalized_rows:
        if isinstance(row, dict):
            sheet.append([row.get(key, "") for key in header_keys])
    style_result_sheet(sheet)


def keys_from_rows(rows: list[dict]) -> list[str]:
    keys: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key not in keys:
                keys.append(key)
    return keys


def safe_sheet_title(title: str, existing: list[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", "_", str(title or "Sheet")).strip() or "Sheet"
    clean = clean[:31]
    if clean not in existing:
        return clean
    for index in range(2, 1000):
        suffix = f"_{index}"
        candidate = f"{clean[:31 - len(suffix)]}{suffix}"
        if candidate not in existing:
            return candidate
    raise ValueError("无法生成唯一工作表名称")


def style_result_sheet(sheet) -> None:
    header_fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    sheet.freeze_panes = "A2"
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(max_length + 2, 10), 28)


def list_evaluation_result_files(scheme: str) -> list[dict]:
    folder = PLANNING_STORE.scheme_dir(scheme)
    if not folder.exists():
        raise FileNotFoundError(f"方案不存在: {scheme}")
    files = []
    for path in sorted(folder.glob("*_results.xlsx"), key=lambda item: item.name):
        if path.is_file() and RESULT_WORKBOOK_RE.fullmatch(path.name):
            files.append({"name": path.name, "modified_at": path.stat().st_mtime})
    return files


def selected_evaluation_result_filename(scheme: str, filename: str = "") -> str:
    files = list_evaluation_result_files(scheme)
    names = [item["name"] for item in files]
    selected = str(filename or "").strip()
    if selected and selected in names:
        return selected
    return names[0] if names else ""


def evaluation_result_path(scheme: str, filename: str) -> Path:
    name = str(filename or "").strip()
    if not RESULT_WORKBOOK_RE.fullmatch(name):
        raise ValueError("结果文件名必须符合 xxxx_results.xlsx")
    folder = PLANNING_STORE.scheme_dir(scheme)
    path = (folder / name).resolve()
    if folder not in path.parents or path.parent != folder:
        raise ValueError("结果文件路径越界")
    return path


def read_evaluation_planning_result_rows(scheme: str, filename: str) -> list[dict]:
    if not filename:
        return []
    result_path = evaluation_result_path(scheme, filename)
    if not result_path.exists():
        return []
    workbook = load_workbook(result_path, read_only=True, data_only=True)
    try:
        if PLANNING_RESULT_SHEET_NAME not in workbook.sheetnames:
            return []
        sheet = workbook[PLANNING_RESULT_SHEET_NAME]
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(value or "").strip() for value in rows[0]]
        result_rows = []
        for row in rows[1:]:
            item = {}
            for index, header in enumerate(headers):
                if header:
                    item[header] = row[index] if index < len(row) else ""
            if any(value not in (None, "") for value in item.values()):
                result_rows.append(item)
        return result_rows
    finally:
        workbook.close()


def handle_comparison_data_api_path(path: str, query: str = "") -> tuple[int, dict[str, str], bytes]:
    if path != "/api/comparison/data":
        return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
    try:
        items_text = parse_qs(query).get("items", ["[]"])[0]
        items = json.loads(items_text or "[]")
        if not isinstance(items, list):
            raise ValueError("对比项必须为列表")
        return _json_response(build_comparison_payload(items[:4]))
    except FileNotFoundError as exc:
        return _json_response({"error": "not_found", "message": str(exc)}, HTTPStatus.NOT_FOUND)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)


def build_comparison_payload(items: list[dict]) -> dict:
    selected_items: list[dict] = []
    capacity_tables: list[list[dict]] = []
    energy_tables: list[list[dict]] = []
    safety_tables: list[list[dict]] = []
    curve_names: list[str] = []
    curve_series: dict[str, list[dict]] = {}

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        scheme = str(item.get("scheme", "")).strip()
        filename = str(item.get("filename", "")).strip()
        if not scheme or not filename:
            continue
        result_path = evaluation_result_path(scheme, filename)
        if not result_path.exists():
            raise FileNotFoundError(f"结果文件不存在: {result_path.name}")
        result_display_name = result_display_name_from_filename(filename)
        label = f"{scheme} / {result_display_name}"
        workbook_data = read_comparison_workbook(result_path)
        selected_items.append(
            {
                "id": f"item-{index + 1}",
                "scheme": scheme,
                "filename": filename,
                "result_display_name": result_display_name,
                "label": label,
            }
        )
        capacity_tables.append(workbook_data["capacity"])
        energy_tables.append(workbook_data["energy"])
        safety_tables.append(workbook_data["safety"])
        for name in workbook_data["curves"]:
            if name not in curve_names:
                curve_names.append(name)
            curve_series.setdefault(name, []).append(
                {
                    "label": label,
                    "scheme": scheme,
                    "filename": filename,
                    "points": workbook_data["curves"][name],
                }
            )

    return {
        "items": selected_items,
        "tables": {
            "capacity": merge_comparison_rows(capacity_tables, selected_items, "设备类型"),
            "energy": merge_comparison_rows(energy_tables, selected_items, "指标"),
            "safety": merge_comparison_rows(safety_tables, selected_items, "指标"),
        },
        "curves": curve_names,
        "series": curve_series,
    }


def read_comparison_workbook(path: Path) -> dict:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return {
            "capacity": read_named_sheet_rows(workbook, "规划结果"),
            "energy": read_named_sheet_rows(workbook, "供能分析"),
            "safety": read_named_sheet_rows(workbook, "安全评估"),
            "curves": read_dispatch_curves(workbook),
        }
    finally:
        workbook.close()


def read_named_sheet_rows(workbook, sheet_name: str) -> list[dict]:
    if sheet_name not in workbook.sheetnames:
        return []
    sheet = workbook[sheet_name]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(value or "").strip() for value in rows[0]]
    result_rows = []
    for row in rows[1:]:
        item = {}
        for index, header in enumerate(headers):
            if header:
                item[header] = row[index] if index < len(row) else ""
        if any(value not in (None, "") for value in item.values()):
            result_rows.append(item)
    return result_rows


def read_dispatch_curves(workbook) -> dict[str, list[dict]]:
    if "调度结果" not in workbook.sheetnames:
        return {}
    sheet = workbook["调度结果"]
    rows_iter = sheet.iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(rows_iter, [])]
    curves: dict[str, list[dict]] = {}
    for header in headers:
        if header and header not in {"小时", "hour_index", "时间", "datetime"}:
            curves[header] = []
    for row_index, row in enumerate(rows_iter, start=1):
        if row_index > 8760:
            break
        x_value = row[0] if len(row) > 0 and row[0] not in (None, "") else row_index
        for column_index, header in enumerate(headers):
            if header not in curves:
                continue
            value = row[column_index] if column_index < len(row) else None
            number = _numeric_or_none(value)
            if number is not None:
                curves[header].append({"x": x_value, "y": number})
    return curves


def merge_comparison_rows(tables: list[list[dict]], items: list[dict], key_field: str) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item, rows in zip(items, tables):
        value_field = "总容量" if key_field == "设备类型" else "数值"
        unit_field = "单位"
        label = item["label"]
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get(key_field, "")).strip()
            if not key:
                continue
            if key not in merged:
                merged[key] = {key_field: key, "单位": row.get(unit_field, "")}
                order.append(key)
            if not merged[key].get("单位") and row.get(unit_field, ""):
                merged[key]["单位"] = row.get(unit_field, "")
            merged[key][label] = row.get(value_field, "")
    return [merged[key] for key in order]


def result_display_name_from_filename(filename: str) -> str:
    return re.sub(r"_results\.xlsx$", "", str(filename or ""))


def _numeric_or_none(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def write_evaluation_planning_counts(scheme: str, filename: str, planning_rows: list[dict]) -> list[dict]:
    result_path = evaluation_result_path(scheme, filename)
    if not result_path.exists():
        raise FileNotFoundError(f"结果文件不存在: {result_path.name}")

    counts_by_device: dict[str, object] = {}
    for row in planning_rows if isinstance(planning_rows, list) else []:
        if not isinstance(row, dict):
            continue
        device_type = str(row.get("设备类型", "")).strip()
        if not device_type or "设计台数" not in row:
            continue
        counts_by_device[device_type] = row.get("设计台数")

    workbook = load_workbook(result_path)
    try:
        if PLANNING_RESULT_SHEET_NAME not in workbook.sheetnames:
            sheet = workbook.create_sheet(PLANNING_RESULT_SHEET_NAME)
            sheet.append(PLANNING_RESULT_HEADERS)
        else:
            sheet = workbook[PLANNING_RESULT_SHEET_NAME]
            if sheet.max_row < 1:
                sheet.append(PLANNING_RESULT_HEADERS)

        headers = [str(cell.value or "").strip() for cell in sheet[1]]
        if "设备类型" not in headers or "设计台数" not in headers:
            raise ValueError("规划结果工作表缺少设备类型或设计台数列")
        device_column = headers.index("设备类型") + 1
        count_column = headers.index("设计台数") + 1

        for row_index in range(2, sheet.max_row + 1):
            device_type = str(sheet.cell(row=row_index, column=device_column).value or "").strip()
            if device_type in counts_by_device:
                sheet.cell(row=row_index, column=count_column).value = normalize_planning_count(counts_by_device[device_type])

        tmp_path = result_path.with_name(f".{result_path.name}.tmp")
        workbook.save(tmp_path)
        tmp_path.replace(result_path)
    finally:
        workbook.close()
    return read_evaluation_planning_result_rows(scheme, filename)


def normalize_planning_count(value):
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError("设计台数必须为非负整数")
    return int(text)


def evaluation_result_filename_from_name(name: str) -> str:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("结果名称不能为空")
    if clean_name.endswith(".xlsx"):
        raise ValueError("结果名称只需输入 xxxx，不要输入扩展名")
    return f"{clean_name}_results.xlsx"


def save_evaluation_result_workbook(scheme: str, filename: str) -> Path:
    result_path = evaluation_result_path(scheme, filename or OPTIMIZATION_RESULT_WORKBOOK_NAME)
    if not result_path.exists():
        raise FileNotFoundError(f"结果文件不存在: {result_path.name}")
    return result_path


def handle_evaluation_results_api_path(
    path: str,
    method: str = "GET",
    body: bytes = b"",
    query: str = "",
) -> tuple[int, dict[str, str], bytes]:
    if path != "/api/evaluation/results":
        return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
    try:
        if method == "GET":
            scheme = parse_qs(query).get("scheme", [""])[0]
            filename = parse_qs(query).get("filename", [""])[0]
            selected = selected_evaluation_result_filename(scheme, filename)
            return _json_response(
                {
                    "selected": selected,
                    "results": list_evaluation_result_files(scheme),
                    "planning_result_rows": read_evaluation_planning_result_rows(scheme, selected),
                }
            )

        if method != "POST":
            return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)

        payload = _read_json_body(body)
        scheme = str(payload.get("scheme", ""))
        action = str(payload.get("action", ""))
        filename = str(payload.get("filename", ""))

        if action == "delete":
            result_path = evaluation_result_path(scheme, filename)
            if result_path.name == OPTIMIZATION_RESULT_WORKBOOK_NAME:
                raise ValueError("默认结果文件不允许删除")
            if result_path.exists():
                result_path.unlink()
            selected = selected_evaluation_result_filename(scheme)
            return _json_response(
                {
                    "selected": selected,
                    "results": list_evaluation_result_files(scheme),
                    "planning_result_rows": read_evaluation_planning_result_rows(scheme, selected),
                }
            )

        if action == "copy":
            source_path = evaluation_result_path(scheme, filename)
            if not source_path.exists():
                raise FileNotFoundError(f"结果文件不存在: {source_path.name}")
            target_filename = evaluation_result_filename_from_name(str(payload.get("target_name", "")))
            target_path = evaluation_result_path(scheme, target_filename)
            if target_path.exists():
                return _json_response(
                    {"error": "exists", "message": f"复制失败，结果文件已存在: {target_path.name}"},
                    HTTPStatus.CONFLICT,
                )
            shutil.copy2(source_path, target_path)
            return _json_response(
                {
                    "selected": target_path.name,
                    "results": list_evaluation_result_files(scheme),
                    "planning_result_rows": read_evaluation_planning_result_rows(scheme, target_path.name),
                }
            )

        if action == "save":
            if (filename or OPTIMIZATION_RESULT_WORKBOOK_NAME) == OPTIMIZATION_RESULT_WORKBOOK_NAME:
                raise ValueError("默认结果文件不允许修改")
            planning_rows = payload.get("planning_result_rows")
            if isinstance(planning_rows, list):
                planning_result_rows = write_evaluation_planning_counts(
                    scheme,
                    filename or OPTIMIZATION_RESULT_WORKBOOK_NAME,
                    planning_rows,
                )
                selected = filename or OPTIMIZATION_RESULT_WORKBOOK_NAME
            else:
                result_path = save_evaluation_result_workbook(scheme, filename or OPTIMIZATION_RESULT_WORKBOOK_NAME)
                selected = result_path.name
                planning_result_rows = read_evaluation_planning_result_rows(scheme, selected)
            return _json_response(
                {
                    "selected": selected,
                    "results": list_evaluation_result_files(scheme),
                    "planning_result_rows": planning_result_rows,
                }
            )

        raise ValueError("未知结果文件操作")
    except FileNotFoundError as exc:
        return _json_response({"error": "not_found", "message": str(exc)}, HTTPStatus.NOT_FOUND)
    except ValueError as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)


class OptimizationRuntimeManager:
    """Holds independent optimization runtimes for multiple schemes."""

    def __init__(self) -> None:
        self._runtimes: dict[str, OptimizationRuntime] = {}
        self._lock = threading.Lock()

    def snapshot(self, scheme: str = "") -> dict:
        runtime = self._runtime_for_scheme(scheme)
        payload = runtime.snapshot()
        payload["running_schemes"] = self.running_schemes()
        return payload

    def apply(self, action: str, scheme: str = "") -> dict:
        runtime = self._runtime_for_scheme(scheme)
        payload = runtime.apply(action, scheme=self._scheme_name(scheme))
        payload["running_schemes"] = self.running_schemes()
        return payload

    def running_schemes(self) -> list[str]:
        with self._lock:
            runtimes = list(self._runtimes.items())
        running = []
        for scheme, runtime in runtimes:
            if runtime.snapshot()["status"] == "运行中":
                running.append(scheme)
        return running

    def _runtime_for_scheme(self, scheme: str = "") -> OptimizationRuntime:
        name = self._scheme_name(scheme)
        with self._lock:
            if name not in self._runtimes:
                self._runtimes[name] = OptimizationRuntime(scheme=name)
            return self._runtimes[name]

    @staticmethod
    def _scheme_name(scheme: str = "") -> str:
        return str(scheme or "未选择方案").strip() or "未选择方案"


class EvaluationRuntime:
    """Independent runtime state for fixed-plan evaluation dispatch."""

    def __init__(self, scheme: str = "") -> None:
        self.status = "待启动"
        self.scheme = str(scheme or "").strip()
        self.start_time = ""
        self.end_time = ""
        self.progress = 0
        self.result_filename = ""
        self.result_file = ""
        self._metrics: list[dict] = []
        self._results: dict = {}
        self._logs: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._run_token = 0
        self._append_log_unlocked("info", "方案评估待启动")

    def snapshot(self) -> dict:
        with self._lock:
            return self._payload_unlocked()

    def apply(self, action: str, scheme: str = "", filename: str = "") -> dict:
        target_scheme = str(scheme or self.scheme or "未选择方案").strip() or "未选择方案"
        if action == "clear_logs":
            with self._lock:
                self.scheme = target_scheme
                if filename:
                    self.result_filename = str(filename or "").strip()
                self._logs.clear()
                return self._payload_unlocked()

        if action == "start":
            target_filename = selected_evaluation_result_filename(target_scheme, filename)
            if not target_filename:
                raise ValueError("请先选择结果文件")
            target_path = evaluation_result_path(target_scheme, target_filename)
            if not target_path.exists():
                raise FileNotFoundError(f"结果文件不存在: {target_path.name}")
            if target_path.name == OPTIMIZATION_RESULT_WORKBOOK_NAME:
                raise ValueError("默认结果文件不允许修改")

            with self._lock:
                if self.status == "运行中":
                    if self.scheme == target_scheme:
                        raise OptimizationStateError("running", f"方案“{target_scheme}”正在评估，无法再次启动")
                    raise OptimizationStateError("running", f"方案“{self.scheme}”正在评估，无法启动方案“{target_scheme}”")
                self.status = "运行中"
                self.scheme = target_scheme
                self.start_time = _now_text()
                self.end_time = ""
                self.progress = 0
                self.result_filename = target_filename
                self.result_file = str(target_path)
                self._metrics = []
                self._results = {}
                self._stop_requested = False
                self._run_token += 1
                token = self._run_token
                self._append_log_unlocked("ok", f"启动方案评估，方案：{self.scheme}，结果：{self.result_filename}")
                self._append_log_unlocked("info", "后台评估程序已启动")
                self._thread = threading.Thread(
                    target=self._run_estimation,
                    args=(token, target_scheme, target_filename),
                    daemon=True,
                )
                self._thread.start()
                return self._payload_unlocked()

        if action == "stop":
            with self._lock:
                if self.status != "运行中" or self.scheme != target_scheme:
                    raise OptimizationStateError("not_running", f"方案“{target_scheme}”没有运行")
                self._stop_requested = True
                self.status = "已停止"
                self.end_time = _now_text()
                self._append_log_unlocked("warn", "停止方案评估")
                return self._payload_unlocked()

        raise ValueError(f"unknown evaluation action: {action}")

    def _run_estimation(self, token: int, scheme: str, filename: str) -> None:
        dispatch_rows: list[dict] = []
        try:
            self._append_log("info", "读取方案参数和当前规划结果", None, token)
            scheme_payload = PLANNING_STORE.read_scheme(scheme)
            planning_rows = read_evaluation_planning_result_rows(scheme, filename)
            if not planning_rows:
                raise ValueError("当前结果文件缺少规划结果")
            result = estimate.run_estimation(
                scheme_payload,
                planning_rows,
                log=lambda event: self._append_estimate_event(event, token),
            )
            dispatch_rows = result.get("dispatch_rows") if isinstance(result.get("dispatch_rows"), list) else []
            with self._lock:
                if token != self._run_token or self._stop_requested or self.status != "运行中":
                    return
                self.progress = 100
                self._metrics = result.get("metrics") if isinstance(result.get("metrics"), list) else []
                self._results = result.get("results") if isinstance(result.get("results"), dict) else {}
                result_path = export_evaluation_results_workbook(self._payload_unlocked(), dispatch_rows)
                self.result_file = str(result_path)
                self._append_log_unlocked("ok", f"评估结果已写入：{result_path.name}")
                self.status = "已完成"
                self.end_time = _now_text()
        except Exception as exc:
            with self._lock:
                if token != self._run_token:
                    return
                self.status = "失败"
                self.end_time = _now_text()
                self._append_log_unlocked("error", f"方案评估失败：{exc}")

    def _append_estimate_event(self, event: dict, token: int) -> None:
        level = str(event.get("level") or "info")
        message = str(event.get("message") or "")
        progress = event.get("progress")
        self._append_log(level, message, progress if isinstance(progress, int) else None, token)

    def _append_log(self, level: str, message: str, progress: int | None, token: int) -> None:
        with self._lock:
            if token != self._run_token:
                return
            if progress is not None:
                self.progress = max(self.progress, min(100, max(0, int(progress))))
            if message:
                self._append_log_unlocked(level, message)

    def _payload_unlocked(self) -> dict:
        return {
            "status": self.status,
            "scheme": self.scheme,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "progress": self.progress,
            "result_filename": self.result_filename,
            "result_file": self.result_file,
            "metrics": self._metrics_unlocked(),
            "results": self._results if self._results else self._default_results_unlocked(),
            "logs": list(self._logs),
        }

    def _metrics_unlocked(self) -> list[dict]:
        base = [
            {"label": "当前状态", "value": self.status, "unit": ""},
            {"label": "启动时刻", "value": self.start_time or "-", "unit": ""},
            {"label": "结束时刻", "value": self.end_time or "-", "unit": ""},
        ]
        existing_labels = {item["label"] for item in base}
        for metric in self._metrics:
            if not isinstance(metric, dict):
                continue
            label = metric.get("label", "")
            if label in existing_labels:
                continue
            base.append(metric)
            existing_labels.add(label)
        return base

    @staticmethod
    def _default_results_unlocked() -> dict:
        return {
            "overview_tables": [
                {"title": "规划结果", "rows": []},
                {"title": "规划年指标", "rows": []},
            ],
            "overview_disks": [],
            "green_table": [],
            "safety_table": [],
            "curves": {"green_daily": [], "green_monthly": [], "green_hourly": [], "safety_daily": []},
        }

    def _append_log_unlocked(self, level: str, message: str) -> None:
        self._logs.append({"time": _now_text(), "level": level, "message": message})
        if len(self._logs) > 2000:
            del self._logs[:-2000]


class EvaluationRuntimeManager:
    """Holds independent evaluation runtimes for multiple schemes."""

    def __init__(self) -> None:
        self._runtimes: dict[str, EvaluationRuntime] = {}
        self._lock = threading.Lock()

    def snapshot(self, scheme: str = "", filename: str = "") -> dict:
        runtime = self._runtime_for_result(scheme, filename)
        payload = runtime.snapshot()
        payload["running_schemes"] = self.running_schemes()
        return payload

    def apply(self, action: str, scheme: str = "", filename: str = "") -> dict:
        runtime = self._runtime_for_result(scheme, filename)
        payload = runtime.apply(action, scheme=self._scheme_name(scheme), filename=filename)
        payload["running_schemes"] = self.running_schemes()
        return payload

    def running_schemes(self) -> list[str]:
        with self._lock:
            runtimes = list(self._runtimes.items())
        running = []
        for key, runtime in runtimes:
            if runtime.snapshot()["status"] == "运行中":
                running.append(key.split("\0", 1)[0])
        return sorted(set(running))

    def _runtime_for_result(self, scheme: str = "", filename: str = "") -> EvaluationRuntime:
        scheme_name = self._scheme_name(scheme)
        result_filename = self._result_filename(scheme_name, filename)
        key = f"{scheme_name}\0{result_filename}"
        with self._lock:
            if key not in self._runtimes:
                runtime = EvaluationRuntime(scheme=scheme_name)
                runtime.result_filename = result_filename
                if result_filename:
                    try:
                        runtime.result_file = str(evaluation_result_path(scheme_name, result_filename))
                    except ValueError:
                        runtime.result_file = ""
                self._runtimes[key] = runtime
            return self._runtimes[key]

    @staticmethod
    def _result_filename(scheme: str, filename: str = "") -> str:
        selected = str(filename or "").strip()
        if selected:
            return selected
        try:
            return selected_evaluation_result_filename(scheme)
        except (FileNotFoundError, ValueError):
            return ""

    def _runtime_for_scheme(self, scheme: str = "") -> EvaluationRuntime:
        runtime = self._runtime_for_result(scheme)
        return runtime

    @staticmethod
    def _scheme_name(scheme: str = "") -> str:
        return str(scheme or "未选择方案").strip() or "未选择方案"


class CsvDataSource:
    """Periodically reload dashboard data from CSV files."""

    def __init__(self, data_dir: Path = DATA_DIR, reload_interval: float = 1.0) -> None:
        self.data_dir = Path(data_dir)
        self.reload_interval = reload_interval
        self._snapshot: dict | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self, force_reload: bool = False) -> dict:
        now = time.monotonic()
        with self._lock:
            expired = now - self._loaded_at >= self.reload_interval
            if force_reload or self._snapshot is None or expired:
                self._snapshot = self._load_snapshot()
                self._loaded_at = now
            return self._snapshot

    def _rows(self, filename: str) -> list[dict[str, str]]:
        path = self.data_dir / filename
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]

    def _by_page(self, rows: list[dict[str, str]], page: str) -> list[dict[str, str]]:
        return [row for row in rows if row.get("page") == page]

    def _load_snapshot(self) -> dict:
        return {
            "system": "考察站风-光-氢-储-柴联合规划系统",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "summary": self._load_overview_summary(),
        }

    def _load_overview_summary(self) -> dict:
        return {
            row.get("key", ""): _coerce_value(row.get("value", ""))
            for row in self._rows("summary.csv")
            if row.get("key")
        }

    def _load_metrics(self, rows: list[dict[str, str]], page: str) -> list[dict]:
        return [
            _metric(
                row.get("label", ""),
                _coerce_value(row.get("value", "")),
                row.get("unit", ""),
                row.get("status", "normal"),
            )
            for row in self._by_page(rows, page)
        ]

    def _load_alarms(self, rows: list[dict[str, str]], page: str) -> list[dict]:
        return [
            {
                "time": row.get("time", ""),
                "object": row.get("object", ""),
                "message": row.get("message", ""),
                "status": row.get("status", ""),
            }
            for row in self._by_page(rows, page)
        ]

    def _load_page_summary(self, rows: list[dict[str, str]], page: str) -> list[dict]:
        return [
            _summary(row.get("label", ""), row.get("value", ""), row.get("status", "normal"))
            for row in self._by_page(rows, page)
        ]

    def _load_label_values(self, filename: str) -> list[dict]:
        return [
            {"label": row.get("label", ""), "value": _coerce_value(row.get("value", "")), "unit": row.get("unit", "")}
            for row in self._rows(filename)
        ]

    def _load_topology(self) -> list[dict]:
        return [
            {"id": row.get("id", ""), "status": row.get("status", "normal"), "value": row.get("value", "")}
            for row in self._rows("simu_topology.csv")
        ]

    def _load_simu_daily_curves(self) -> list[dict]:
        rows = self._rows("simu_daily_curves.csv")
        specs = [
            ("wind_speed", "风速", "m/s"),
            ("temperature", "温度", "℃"),
            ("solar_irradiance", "太阳辐射", "W/m²"),
            ("load", "负荷", "kW"),
        ]
        curves = []
        for key, name, unit in specs:
            points = [
                {"hour": _coerce_value(row.get("hour", "")), "value": _coerce_value(row.get(key, ""))}
                for row in rows
            ]
            curves.append({"key": key, "name": name, "unit": unit, "points": points})
        return curves

    def _load_stations(self) -> list[dict]:
        return [
            {"name": row.get("name", ""), "status": row.get("status", "normal"), "detail": row.get("detail", "")}
            for row in self._rows("scada_stations.csv")
        ]

    def _load_agc_reserve(self) -> dict:
        rows = self._rows("agc_reserve.csv")
        if not rows:
            return {"score": 0, "up": 0, "down": 0, "response": 0, "cycle": 0}
        row = rows[0]
        return {
            "score": _coerce_value(row.get("score", "")),
            "up": _coerce_value(row.get("up", "")),
            "down": _coerce_value(row.get("down", "")),
            "response": _coerce_value(row.get("response", "")),
            "cycle": _coerce_value(row.get("cycle", "")),
        }


def _mysql_connector(config: dict):
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("缺少 MySQL 驱动，请先安装: python -m pip install PyMySQL") from exc
    return pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset=config.get("charset", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


class MySqlDataSource:
    """Periodically reload dashboard data from MySQL."""

    def __init__(
        self,
        config: dict | None = None,
        reload_interval: float = 1.0,
        connector_factory=_mysql_connector,
    ) -> None:
        self.config = config or DB_CONFIG
        self.reload_interval = reload_interval
        self.connector_factory = connector_factory
        self._snapshot: dict | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self, force_reload: bool = False) -> dict:
        now = time.monotonic()
        with self._lock:
            expired = now - self._loaded_at >= self.reload_interval
            if force_reload or self._snapshot is None or expired:
                self._snapshot = self._load_snapshot()
                self._loaded_at = now
            return self._snapshot

    def save_simu_state(self, state: dict) -> None:
        sql = """
            UPDATE simu_state
            SET sim_time = %s, speed = %s, status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """
        self._execute(sql, (state["sim_time"], state["speed"], state["status"]), commit=True)

    def _connect(self):
        return self.connector_factory(self.config)

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                if rows is None:
                    return []
                if isinstance(rows, dict):
                    return [rows]
                return list(rows)
            finally:
                cursor.close()
        finally:
            connection.close()

    def _query_one(self, sql: str, params: tuple = ()) -> dict | None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                return cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()

    def _execute(self, sql: str, params: tuple = (), commit: bool = False) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                if commit:
                    connection.commit()
            finally:
                cursor.close()
        finally:
            connection.close()

    def _load_snapshot(self) -> dict:
        return {
            "system": "考察站风-光-氢-储-柴联合规划系统",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "summary": self._load_overview_summary(),
        }

    def _load_overview_summary(self) -> dict:
        return {
            row.get("key", ""): _coerce_value(str(row.get("value", "")))
            for row in self._query("SELECT `key`, value, unit FROM overview_summary ORDER BY display_order, id")
            if row.get("key")
        }

    def _by_page(self, rows: list[dict], page: str) -> list[dict]:
        return [row for row in rows if row.get("page") == page]

    def _load_metrics(self, rows: list[dict], page: str) -> list[dict]:
        return [
            _metric(
                row.get("label", ""),
                _coerce_value(str(row.get("value", ""))),
                row.get("unit", ""),
                row.get("status", "normal"),
            )
            for row in self._by_page(rows, page)
        ]

    def _load_alarms(self, rows: list[dict], page: str) -> list[dict]:
        return [
            {
                "time": row.get("time", ""),
                "object": row.get("object", ""),
                "message": row.get("message", ""),
                "status": row.get("status", ""),
            }
            for row in self._by_page(rows, page)
        ]

    def _load_page_summary(self, rows: list[dict], page: str) -> list[dict]:
        return [
            _summary(row.get("label", ""), row.get("value", ""), row.get("status", "normal"))
            for row in self._by_page(rows, page)
        ]

    def _load_label_values(self, sql: str) -> list[dict]:
        return [
            {
                "label": row.get("label", ""),
                "value": _coerce_value(str(row.get("value", ""))),
                "unit": row.get("unit", ""),
            }
            for row in self._query(sql)
        ]

    def _load_topology(self) -> list[dict]:
        return [
            {"id": row.get("id", ""), "status": row.get("status", "normal"), "value": row.get("value", "")}
            for row in self._query("SELECT id, status, value FROM simu_topology ORDER BY display_order, id")
        ]

    def _load_simu_daily_curves(self) -> list[dict]:
        rows = self._query(
            "SELECT hour, wind_speed, temperature, solar_irradiance, load_value FROM simu_daily_curves ORDER BY hour"
        )
        specs = [
            ("wind_speed", "风速", "m/s"),
            ("temperature", "温度", "℃"),
            ("solar_irradiance", "太阳辐射", "W/m²"),
            ("load_value", "负荷", "kW"),
        ]
        curves = []
        for key, name, unit in specs:
            points = [
                {"hour": _coerce_value(str(row.get("hour", ""))), "value": _coerce_value(str(row.get(key, "")))}
                for row in rows
            ]
            curves.append({"key": key, "name": name, "unit": unit, "points": points})
        return curves

    def _load_stations(self) -> list[dict]:
        return [
            {"name": row.get("name", ""), "status": row.get("status", "normal"), "detail": row.get("detail", "")}
            for row in self._query("SELECT name, status, detail FROM scada_stations ORDER BY display_order, id")
        ]

    def _load_agc_reserve(self) -> dict:
        row = self._query_one("SELECT score, up, down, response, cycle FROM agc_reserve ORDER BY id LIMIT 1")
        if not row:
            return {"score": 0, "up": 0, "down": 0, "response": 0, "cycle": 0}
        return {
            "score": _coerce_value(str(row.get("score", ""))),
            "up": _coerce_value(str(row.get("up", ""))),
            "down": _coerce_value(str(row.get("down", ""))),
            "response": _coerce_value(str(row.get("response", ""))),
            "cycle": _coerce_value(str(row.get("cycle", ""))),
        }


def _load_initial_simu_runtime() -> SimuRuntime:
    return SimuRuntime()


SIMU_RUNTIME = _load_initial_simu_runtime()
OPTIMIZATION_RUNTIME = OptimizationRuntimeManager()
EVALUATION_RUNTIME = EvaluationRuntimeManager()
DATA_SOURCE = CsvDataSource()
PLANNING_STORE = planning_store.PlanningStore()
USER_STORE = UserStore()


def build_snapshot(force_reload: bool = False) -> dict:
    """Build a snapshot from CSV files, reloading periodically."""
    return DATA_SOURCE.snapshot(force_reload=force_reload)


def _json_response(payload: dict, status: int = 200, extra_headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    }
    if extra_headers:
        headers.update(extra_headers)
    return status, headers, body


def _read_json_body(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("请求体不是合法 JSON") from exc


def _session_cookie(token: str, max_age: int = SESSION_MAX_AGE_SECONDS) -> str:
    return f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"


def _expired_session_cookie() -> str:
    return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def _session_token_from_cookie(cookie_header: str | None) -> str:
    if not cookie_header:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return ""
    morsel = cookie.get(SESSION_COOKIE_NAME)
    return morsel.value if morsel else ""


def handle_auth_api_path(path: str, method: str, body: bytes = b"", token: str = "") -> tuple[int, dict[str, str], bytes]:
    current_user = USER_STORE.user_for_session(token)
    try:
        if path == "/api/auth/me" and method == "GET":
            if not current_user:
                return _json_response({"error": "unauthorized", "message": "请先登录"}, HTTPStatus.UNAUTHORIZED)
            return _json_response({"user": current_user})
        if path == "/api/auth/register" and method == "POST":
            payload = _read_json_body(body)
            user = USER_STORE.create_user(str(payload.get("username", "")), str(payload.get("password", "")))
            session_token = USER_STORE.create_session(user["id"])
            return _json_response({"ok": True, "user": user}, extra_headers={"Set-Cookie": _session_cookie(session_token)})
        if path == "/api/auth/login" and method == "POST":
            payload = _read_json_body(body)
            user = USER_STORE.authenticate(str(payload.get("username", "")), str(payload.get("password", "")))
            session_token = USER_STORE.create_session(user["id"])
            return _json_response({"ok": True, "user": user}, extra_headers={"Set-Cookie": _session_cookie(session_token)})
        if path == "/api/auth/logout" and method == "POST":
            USER_STORE.delete_session(token)
            return _json_response({"ok": True}, extra_headers={"Set-Cookie": _expired_session_cookie()})
    except ValueError as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
    return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)


def handle_users_api_path(path: str, method: str, body: bytes, current_user: dict | None) -> tuple[int, dict[str, str], bytes]:
    if not current_user:
        return _json_response({"error": "unauthorized", "message": "请先登录"}, HTTPStatus.UNAUTHORIZED)
    if current_user.get("role") != "admin":
        return _json_response({"error": "forbidden", "message": "需要管理员权限"}, HTTPStatus.FORBIDDEN)
    try:
        if path == "/api/users" and method == "GET":
            return _json_response({"users": USER_STORE.list_users()})
        if path.startswith("/api/users/"):
            user_id = int(path.rsplit("/", 1)[1])
            if method == "PUT":
                payload = _read_json_body(body)
                return _json_response({"user": USER_STORE.update_role(user_id, str(payload.get("role", "")))})
            if method == "DELETE":
                USER_STORE.delete_user(user_id, current_user_id=current_user["id"])
                return _json_response({"ok": True})
    except FileNotFoundError as exc:
        return _json_response({"error": "not_found", "message": str(exc)}, HTTPStatus.NOT_FOUND)
    except (TypeError, ValueError) as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
    return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)


class WeatherHistoryError(RuntimeError):
    """Raised when historical weather data cannot be fetched or parsed."""


class GeocodingError(RuntimeError):
    """Raised when a place name cannot be resolved to coordinates."""


def geocode_place_name(place: str) -> dict:
    query_text = str(place or "").strip()
    if not query_text:
        raise ValueError("地名不能为空")
    errors: list[str] = []
    providers = []
    if AMAP_WEB_SERVICE_KEY:
        providers.append(geocode_with_amap)
    providers.extend([geocode_with_open_meteo, geocode_with_nominatim])
    for provider in providers:
        try:
            return provider(query_text)
        except GeocodingError as exc:
            errors.append(str(exc))
    raise GeocodingError("；".join(errors) or "未找到该地名对应的经纬度坐标")


def geocode_with_amap(place: str) -> dict:
    query = urlencode({"address": place, "output": "JSON", "key": AMAP_WEB_SERVICE_KEY})
    url = f"{AMAP_GEOCODING_URL}?{query}"
    try:
        with urlopen_with_user_agent(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise GeocodingError(f"高德地名解析接口返回错误: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise GeocodingError(f"高德地名解析接口连接失败: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GeocodingError("高德地名解析接口返回内容不是合法 JSON") from exc
    if str(data.get("status")) != "1":
        raise GeocodingError(f"高德地名解析失败: {data.get('info') or data.get('infocode') or '未知错误'}")
    geocodes = data.get("geocodes", [])
    if not geocodes:
        raise GeocodingError("高德未找到该地名对应的经纬度坐标")
    first = geocodes[0]
    location = str(first.get("location", ""))
    try:
        longitude_text, latitude_text = location.split(",", 1)
        longitude = float(longitude_text)
        latitude = float(latitude_text)
    except (ValueError, AttributeError) as exc:
        raise GeocodingError("高德地名解析结果缺少有效经纬度") from exc
    display_parts = [
        first.get("formatted_address"),
        first.get("province"),
        first.get("city"),
        first.get("district"),
    ]
    display_name = "，".join(str(part) for part in display_parts if part and part != [])
    return {
        "place": place,
        "display_name": display_name or place,
        "latitude": latitude,
        "longitude": longitude,
        "source": "高德地图 Web 服务地理编码 API",
    }


def geocode_with_open_meteo(place: str) -> dict:
    query = urlencode({"name": place, "count": 1, "language": "zh", "format": "json"})
    url = f"{OPEN_METEO_GEOCODING_URL}?{query}"
    try:
        with urlopen_with_user_agent(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise GeocodingError(f"Open-Meteo 地名解析接口返回错误: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise GeocodingError(f"Open-Meteo 地名解析接口连接失败: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GeocodingError("Open-Meteo 地名解析接口返回内容不是合法 JSON") from exc
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        raise GeocodingError("Open-Meteo 未找到该地名对应的经纬度坐标")
    first = results[0]
    try:
        latitude = float(first["latitude"])
        longitude = float(first["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("Open-Meteo 地名解析结果缺少有效经纬度") from exc
    display_parts = [
        first.get("name"),
        first.get("admin2"),
        first.get("admin1"),
        first.get("country"),
    ]
    display_name = "，".join(str(part) for part in display_parts if part)
    return {
        "place": place,
        "display_name": display_name or place,
        "latitude": latitude,
        "longitude": longitude,
        "source": "Open-Meteo Geocoding API",
    }


def geocode_with_nominatim(place: str) -> dict:
    query = urlencode({"q": place, "format": "json", "limit": 1, "accept-language": "zh-CN"})
    url = f"{NOMINATIM_SEARCH_URL}?{query}"
    try:
        with urlopen_with_user_agent(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise GeocodingError(f"Nominatim 地名解析接口返回错误: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise GeocodingError(f"Nominatim 地名解析接口连接失败: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GeocodingError("Nominatim 地名解析接口返回内容不是合法 JSON") from exc
    if not isinstance(data, list) or not data:
        raise GeocodingError("Nominatim 未找到该地名对应的经纬度坐标")
    first = data[0]
    try:
        latitude = float(first["lat"])
        longitude = float(first["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("Nominatim 地名解析结果缺少有效经纬度") from exc
    return {
        "place": place,
        "display_name": first.get("display_name", place),
        "latitude": latitude,
        "longitude": longitude,
        "source": "OpenStreetMap Nominatim",
    }


def urlopen_with_user_agent(url: str, timeout: int):
    from urllib.request import Request

    request = Request(url, headers={"User-Agent": "power-plan-local-web/1.0"})
    return urlopen(request, timeout=timeout)


def fetch_weather_history(latitude: float, longitude: float, year: int) -> dict:
    latitude, longitude, year = validate_weather_history_inputs(latitude, longitude, year)
    query = urlencode(
        {
            "parameters": ",".join(NASA_POWER_PARAMETERS.values()),
            "community": "RE",
            "longitude": longitude,
            "latitude": latitude,
            "start": f"{year}0101",
            "end": f"{year}1231",
            "format": "JSON",
            "time-standard": "LST",
        }
    )
    url = f"{NASA_POWER_HOURLY_URL}?{query}"
    try:
        with urlopen_with_user_agent(url, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise WeatherHistoryError(f"历史气象数据接口返回错误: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise WeatherHistoryError(f"历史气象数据接口连接失败: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise WeatherHistoryError("历史气象数据接口返回内容不是合法 JSON") from exc
    rows = parse_nasa_power_hourly_response(data, year)
    return {
        "source": "NASA POWER Hourly API",
        "source_url": url,
        "latitude": latitude,
        "longitude": longitude,
        "year": year,
        "rows": rows,
    }


def validate_weather_history_inputs(latitude: float, longitude: float, year: int) -> tuple[float, float, int]:
    try:
        latitude_number = float(latitude)
        longitude_number = float(longitude)
        year_number = int(year)
    except (TypeError, ValueError) as exc:
        raise ValueError("经纬度和历史数据年必须为数值") from exc
    current_year = datetime.now().year
    if not -90 <= latitude_number <= 90:
        raise ValueError("纬度范围应为 -90 到 90")
    if not -180 <= longitude_number <= 180:
        raise ValueError("经度范围应为 -180 到 180")
    if year_number < 2001:
        raise ValueError("NASA POWER 小时历史数据年份不能早于 2001")
    if year_number >= current_year:
        raise ValueError(f"历史数据年必须小于当前年 {current_year}")
    return latitude_number, longitude_number, year_number


def parse_nasa_power_hourly_response(data: dict, year: int) -> list[dict]:
    parameters = data.get("properties", {}).get("parameter", {})
    fill_value = data.get("header", {}).get("fill_value", -999)
    missing = [api_name for api_name in NASA_POWER_PARAMETERS.values() if api_name not in parameters]
    if missing:
        raise WeatherHistoryError(f"历史气象数据缺少字段: {', '.join(missing)}")
    wind_values = parameters[NASA_POWER_PARAMETERS["wind_speed"]]
    keys = sorted(key for key in wind_values if str(key).startswith(str(year)) and str(key)[4:8] != "0229")
    rows = []
    for hour_index, key in enumerate(keys, start=1):
        row = {"hour_index": hour_index, "datetime": power_hour_key_to_datetime(str(key))}
        for field, api_name in NASA_POWER_PARAMETERS.items():
            value = parameters.get(api_name, {}).get(key)
            if value in (None, "", fill_value):
                raise WeatherHistoryError(f"历史气象数据在 {key} 缺少 {api_name}")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise WeatherHistoryError(f"历史气象数据在 {key} 的 {api_name} 不是数值") from exc
            row[field] = round(number, 4)
        rows.append(row)
    if len(rows) != 8760:
        raise WeatherHistoryError(f"历史气象数据小时数应为8760，当前为{len(rows)}")
    return rows


def power_hour_key_to_datetime(key: str) -> str:
    return f"{key[0:4]}-{key[4:6]}-{key[6:8]} {key[8:10]}:00"


def import_time_series_file(filename: str, content: bytes) -> dict:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        headers, rows = read_time_series_csv(content)
    elif suffix == ".xlsx":
        headers, rows = read_time_series_xlsx(content)
    else:
        raise ValueError("导入文件仅支持 .csv 或 .xlsx 格式")
    return normalize_imported_time_series(headers, rows, filename)


def read_time_series_csv(content: bytes) -> tuple[list[str], list[dict[str, object]]]:
    text = decode_csv_text(content)
    reader = csv.DictReader(StringIO(text))
    headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
    rows = [row for row in reader if any(str(value or "").strip() for value in row.values())]
    return headers, rows


def read_time_series_xlsx(content: bytes) -> tuple[list[str], list[dict[str, object]]]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        row_iter = sheet.iter_rows(values_only=True)
        headers = [str(value or "").strip() for value in next(row_iter, ())]
        rows = []
        for values in row_iter:
            if not any(value not in ("", None) for value in values):
                continue
            rows.append({headers[index]: value if index < len(values) else "" for index, value in enumerate(values) if index < len(headers)})
        return headers, rows
    finally:
        workbook.close()


def decode_csv_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV文件编码无法识别，请使用 UTF-8 或 GBK 编码")


def normalize_imported_time_series(headers: list[str], raw_rows: list[dict[str, object]], filename: str) -> dict:
    column_map = match_time_series_import_columns(headers)
    if len(raw_rows) < TIME_SERIES_IMPORT_ROW_COUNT:
        raise ValueError(f"时序数据行数不足8760，当前为{len(raw_rows)}")
    imported_rows = []
    for index, raw_row in enumerate(raw_rows[:TIME_SERIES_IMPORT_ROW_COUNT], start=1):
        item = {
            "hour_index": index,
            "datetime": imported_datetime(raw_row, column_map.get("datetime"), index),
        }
        for key in TIME_SERIES_IMPORT_REQUIRED_COLUMNS:
            item[key] = imported_numeric_value(raw_row.get(column_map[key]), key, index)
        imported_rows.append(item)
    message = f"已从{filename}导入8760行时序数据"
    if len(raw_rows) > TIME_SERIES_IMPORT_ROW_COUNT:
        message += f"，文件共有{len(raw_rows)}行，已使用前8760行"
    return {"time_series": imported_rows, "time_series_count": len(imported_rows), "message": message}


def match_time_series_import_columns(headers: list[str]) -> dict[str, str]:
    normalized_headers = {normalize_import_header(header): header for header in headers if str(header or "").strip()}
    column_map: dict[str, str] = {}
    missing = []
    for key, (display_name, aliases) in TIME_SERIES_IMPORT_REQUIRED_COLUMNS.items():
        matched = next((normalized_headers[normalize_import_header(alias)] for alias in aliases if normalize_import_header(alias) in normalized_headers), "")
        if matched:
            column_map[key] = matched
        else:
            missing.append(display_name)
    for key, aliases in TIME_SERIES_IMPORT_OPTIONAL_COLUMNS.items():
        matched = next((normalized_headers[normalize_import_header(alias)] for alias in aliases if normalize_import_header(alias) in normalized_headers), "")
        if matched:
            column_map[key] = matched
    if missing:
        raise ValueError(f"导入失败，找不到对应的列：{', '.join(missing)}")
    return column_map


def normalize_import_header(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-（）()［\]\[\]/\\:：,，。.%％]+", "", text)


def imported_datetime(raw_row: dict[str, object], column: str | None, index: int) -> str:
    if column:
        value = raw_row.get(column)
        if value not in ("", None):
            if isinstance(value, datetime):
                return value.isoformat(sep=" ", timespec="minutes")
            return str(value)
    return f"H{index:04d}"


def imported_numeric_value(value: object, key: str, row_index: int) -> float | int:
    if value in ("", None):
        label = TIME_SERIES_IMPORT_REQUIRED_COLUMNS[key][0]
        raise ValueError(f"导入失败，第{row_index}行{label}为空")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        label = TIME_SERIES_IMPORT_REQUIRED_COLUMNS[key][0]
        raise ValueError(f"导入失败，第{row_index}行{label}不是数值") from exc
    if not math.isfinite(number):
        label = TIME_SERIES_IMPORT_REQUIRED_COLUMNS[key][0]
        raise ValueError(f"导入失败，第{row_index}行{label}不是有效数值")
    return int(number) if number.is_integer() else number


def generate_load_curve(mode: str, minimum: object, maximum: object, average: object) -> dict:
    mode_key = str(mode or "random").strip() or "random"
    if mode_key not in {"random", "pattern1", "pattern2", "pattern3"}:
        raise ValueError("负荷生成模式必须为随机曲线、模式1、模式2或模式3")
    min_value = load_curve_number(minimum, "负荷最小值")
    max_value = load_curve_number(maximum, "负荷最大值")
    avg_value = load_curve_number(average, "负荷平均值")
    if min_value < 0 or max_value < 0 or avg_value < 0:
        raise ValueError("负荷最大值、负荷最小值、负荷平均值必须为非负数")
    if max_value < min_value:
        raise ValueError("负荷最大值不能小于负荷最小值")
    if max_value == min_value:
        if avg_value != min_value:
            raise ValueError("最大值等于最小值时，平均值必须与其相等")
        values = [round_load_value(min_value) for _ in range(TIME_SERIES_IMPORT_ROW_COUNT)]
    else:
        low_mean = min_value + (max_value - min_value) / TIME_SERIES_IMPORT_ROW_COUNT
        high_mean = max_value - (max_value - min_value) / TIME_SERIES_IMPORT_ROW_COUNT
        if avg_value < low_mean or avg_value > high_mean:
            raise ValueError("平均值必须介于最小值和最大值之间，并能同时满足最大/最小约束")
        shape = normalized_load_shape(mode_key)
        adjusted_shape = adjust_shape_mean(shape, (avg_value - min_value) / (max_value - min_value))
        values = [round_load_value(min_value + (max_value - min_value) * value) for value in adjusted_shape]
    rows = [{"hour_index": index + 1, "load": value} for index, value in enumerate(values)]
    return {
        "mode": mode_key,
        "load_curve": rows,
        "load_curve_count": len(rows),
        "statistics": {
            "max": round_load_value(max(values)),
            "min": round_load_value(min(values)),
            "average": round_load_value(sum(values) / len(values)),
        },
    }


def load_curve_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须为数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}必须为有效数值")
    return number


def normalized_load_shape(mode: str) -> list[float]:
    if mode == "random":
        raw = deterministic_random_shape()
    else:
        raw = standard_load_shape(mode)
    minimum = min(raw)
    maximum = max(raw)
    span = maximum - minimum
    if span <= 0:
        return [0.5 for _ in raw]
    return [(value - minimum) / span for value in raw]


def deterministic_random_shape() -> list[float]:
    seed = 2463534242
    values = []
    previous = 0.5
    for hour in range(TIME_SERIES_IMPORT_ROW_COUNT):
        seed ^= (seed << 13) & 0xFFFFFFFF
        seed ^= seed >> 17
        seed ^= (seed << 5) & 0xFFFFFFFF
        random_value = (seed & 0xFFFFFFFF) / 0xFFFFFFFF
        previous = previous * 0.72 + random_value * 0.28
        daily = 0.5 + 0.28 * math.sin((hour % 24 - 7) / 24 * 2 * math.pi)
        values.append(previous * 0.65 + daily * 0.35 + hour * 1e-9)
    return values


def standard_load_shape(mode: str) -> list[float]:
    values = []
    for hour in range(TIME_SERIES_IMPORT_ROW_COUNT):
        day = hour // 24
        hour_of_day = hour % 24
        season = math.sin((day - 20) / 365 * 2 * math.pi)
        weekday_factor = 1.0 if day % 7 < 5 else 0.88
        morning_peak = math.exp(-((hour_of_day - 8) / 3.0) ** 2)
        evening_peak = math.exp(-((hour_of_day - 19) / 3.5) ** 2)
        noon_peak = math.exp(-((hour_of_day - 13) / 4.0) ** 2)
        night_valley = math.exp(-((hour_of_day - 3) / 4.0) ** 2)
        if mode == "pattern1":
            value = (0.56 + 0.20 * morning_peak + 0.34 * evening_peak - 0.10 * night_valley + 0.09 * season) * weekday_factor
        elif mode == "pattern2":
            value = (0.66 + 0.24 * noon_peak - 0.08 * night_valley + 0.05 * season) * (0.96 + 0.04 * weekday_factor)
        else:
            winter_summer = abs(season)
            value = 0.50 + 0.24 * morning_peak + 0.22 * noon_peak + 0.22 * evening_peak + 0.18 * winter_summer - 0.12 * night_valley
        values.append(value + hour * 1e-9)
    return values


def adjust_shape_mean(shape: list[float], target_mean: float) -> list[float]:
    current_mean = sum(shape) / len(shape)
    if abs(current_mean - target_mean) < 1e-10:
        return shape
    if target_mean < current_mean:
        low, high = 1.0, 2.0
        while mean_power(shape, high) > target_mean:
            high *= 2
        for _ in range(80):
            mid = (low + high) / 2
            if mean_power(shape, mid) > target_mean:
                low = mid
            else:
                high = mid
        power = high
        return [value**power for value in shape]
    low, high = 1.0, 2.0
    while mean_inverse_power(shape, high) < target_mean:
        high *= 2
    for _ in range(80):
        mid = (low + high) / 2
        if mean_inverse_power(shape, mid) < target_mean:
            low = mid
        else:
            high = mid
    power = high
    return [1 - (1 - value) ** power for value in shape]


def mean_power(shape: list[float], power: float) -> float:
    return sum(value**power for value in shape) / len(shape)


def mean_inverse_power(shape: list[float], power: float) -> float:
    return sum(1 - (1 - value) ** power for value in shape) / len(shape)


def round_load_value(value: float) -> float | int:
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded


def handle_planning_api_path(path: str, method: str = "GET", body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
    prefix = "/api/planning/schemes"
    try:
        if path == "/api/planning/time-series/import" and method == "POST":
            payload = _read_json_body(body)
            filename = str(payload.get("filename", ""))
            content_base64 = str(payload.get("content_base64", ""))
            try:
                content = base64.b64decode(content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("导入失败，文件内容无法解析") from exc
            return _json_response(import_time_series_file(filename, content))
        if path == "/api/planning/load-curve/generate" and method == "POST":
            payload = _read_json_body(body)
            return _json_response(
                generate_load_curve(
                    str(payload.get("mode", "random")),
                    payload.get("min"),
                    payload.get("max"),
                    payload.get("average"),
                )
            )
        if path == "/api/planning/map-config" and method == "GET":
            return _json_response({"amap_key": AMAP_WEB_SERVICE_KEY, "preferred_provider": "amap" if AMAP_WEB_SERVICE_KEY else "manual"})
        if path == "/api/planning/weather-history" and method == "POST":
            payload = _read_json_body(body)
            return _json_response(
                fetch_weather_history(payload.get("latitude"), payload.get("longitude"), payload.get("year"))
            )
        if path == "/api/planning/geocode" and method == "POST":
            payload = _read_json_body(body)
            return _json_response(geocode_place_name(str(payload.get("place", ""))))
        if path == prefix and method == "GET":
            return _json_response({"schemes": PLANNING_STORE.list_schemes()})
        if path == prefix and method == "POST":
            payload = _read_json_body(body)
            return _json_response(PLANNING_STORE.create_scheme(str(payload.get("name", ""))))
        if path == f"{prefix}/copy" and method == "POST":
            payload = _read_json_body(body)
            return _json_response(
                PLANNING_STORE.copy_scheme(str(payload.get("source", "")), str(payload.get("target", "")))
            )
        if path == f"{prefix}/rename" and method == "POST":
            payload = _read_json_body(body)
            return _json_response(
                PLANNING_STORE.rename_scheme(str(payload.get("source", "")), str(payload.get("target", "")))
            )
        if path.startswith(f"{prefix}/") and path.endswith("/overview") and method == "GET":
            name = unquote(path[len(prefix) + 1 : -len("/overview")])
            return _json_response(PLANNING_STORE.read_scheme_overview(name))
        if path.startswith(f"{prefix}/") and path.endswith("/time-series") and method == "GET":
            name = unquote(path[len(prefix) + 1 : -len("/time-series")])
            return _json_response(PLANNING_STORE.read_time_series(name))
        if path.startswith(f"{prefix}/"):
            name = unquote(path[len(prefix) + 1 :])
            if method == "GET":
                return _json_response(PLANNING_STORE.read_scheme(name))
            if method == "PUT":
                payload = _read_json_body(body)
                PLANNING_STORE.write_scheme(name, payload)
                return _json_response(PLANNING_STORE.read_scheme(name))
            if method == "DELETE":
                return _json_response(PLANNING_STORE.delete_scheme(name))
    except WeatherHistoryError as exc:
        return _json_response({"error": "weather_history_error", "message": str(exc)}, HTTPStatus.BAD_GATEWAY)
    except GeocodingError as exc:
        return _json_response({"error": "geocoding_error", "message": str(exc)}, HTTPStatus.BAD_GATEWAY)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
    return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)


def handle_api_path(path: str, query: str = "") -> tuple[int, dict[str, str], bytes]:
    parsed_api_path = urlparse(path)
    if parsed_api_path.query and not query:
        query = parsed_api_path.query
        path = parsed_api_path.path
    query_params = parse_qs(query)
    if path.startswith("/api/planning/"):
        return handle_planning_api_path(path, "GET", b"")
    if path.startswith("/api/comparison/"):
        return handle_comparison_data_api_path(path, query)
    if path == "/api/evaluation/status":
        scheme = query_params.get("scheme", [""])[0]
        filename = query_params.get("filename", [""])[0]
        return _json_response(EVALUATION_RUNTIME.snapshot(scheme=scheme, filename=filename))
    if path.startswith("/api/evaluation/"):
        return handle_evaluation_results_api_path(path, "GET", b"", query)
    if path == "/api/optimization/status":
        scheme = query_params.get("scheme", [""])[0]
        return _json_response(OPTIMIZATION_RUNTIME.snapshot(scheme=scheme))
    snapshot = build_snapshot()
    routes = {
        "/api/health": {"ok": True, "timestamp": snapshot["timestamp"]},
        "/api/overview": snapshot,
    }
    if path not in routes:
        return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
    return _json_response(routes[path])


def handle_control_path(path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
    if path == "/api/optimization/control":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            action = str(payload.get("action", ""))
            scheme = str(payload.get("scheme", ""))
            state = OPTIMIZATION_RUNTIME.apply(action, scheme=scheme)
        except OptimizationStateError as exc:
            return _json_response({"error": exc.code, "message": str(exc)}, HTTPStatus.CONFLICT)
        except (ValueError, json.JSONDecodeError) as exc:
            return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        return _json_response({"ok": True, "state": state})
    if path == "/api/evaluation/control":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            action = str(payload.get("action", ""))
            scheme = str(payload.get("scheme", ""))
            filename = str(payload.get("filename", ""))
            state = EVALUATION_RUNTIME.apply(action, scheme=scheme, filename=filename)
        except OptimizationStateError as exc:
            return _json_response({"error": exc.code, "message": str(exc)}, HTTPStatus.CONFLICT)
        except FileNotFoundError as exc:
            return _json_response({"error": "not_found", "message": str(exc)}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        return _json_response({"ok": True, "state": state})
    return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)


def _unauthorized_response() -> tuple[int, dict[str, str], bytes]:
    return _json_response({"error": "unauthorized", "message": "请先登录"}, HTTPStatus.UNAUTHORIZED)


def _redirect_response(location: str) -> tuple[int, dict[str, str], bytes]:
    return HTTPStatus.FOUND, {"Location": location, "Content-Type": "text/plain; charset=utf-8"}, b""


def resolve_static_path(request_path: str) -> Path:
    parsed_path = unquote(urlparse(request_path).path)
    if parsed_path == "/":
        parsed_path = "/index.html"

    relative = parsed_path.lstrip("/")
    candidate = (WEB_ROOT / relative).resolve()
    if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
        raise ValueError(f"path escapes web root: {request_path}")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate


class PowerPlanHandler(BaseHTTPRequestHandler):
    server_version = "PowerPlan/1.0"

    def _current_user(self) -> dict | None:
        token = _session_token_from_cookie(self.headers.get("Cookie"))
        return USER_STORE.user_for_session(token)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            token = _session_token_from_cookie(self.headers.get("Cookie"))
            current_user = USER_STORE.user_for_session(token)
            if parsed.path.startswith("/api/auth/"):
                status, headers, body = handle_auth_api_path(parsed.path, "GET", b"", token)
                self._send(status, headers, body)
                return
            if parsed.path.startswith("/api/users"):
                status, headers, body = handle_users_api_path(parsed.path, "GET", b"", current_user)
                self._send(status, headers, body)
                return
            if parsed.path != "/api/health" and not current_user:
                status, headers, body = _unauthorized_response()
                self._send(status, headers, body)
                return
            status, headers, body = handle_api_path(parsed.path, parsed.query)
            self._send(status, headers, body)
            return

        try:
            path = resolve_static_path(self.path)
        except ValueError:
            self._send_text(HTTPStatus.FORBIDDEN, "Forbidden")
            return

        if not path.exists() or not path.is_file():
            self._send_text(HTTPStatus.NOT_FOUND, "Not Found")
            return

        if path.suffix == ".html":
            current_user = self._current_user()
            public_pages = {"login.html", "register.html"}
            if path.name not in public_pages and not current_user:
                next_path = parsed.path or "/index.html"
                self._send(*_redirect_response(f"/login.html?next={urlencode({'next': next_path})[5:]}"))
                return
            if path.name == "users.html" and current_user and current_user.get("role") != "admin":
                self._send_text(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            if path.name in public_pages and current_user:
                self._send(*_redirect_response("/index.html"))
                return

        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        no_cache_suffixes = {".html", ".css", ".js", ".png"}
        headers = {
            "Content-Type": content_type,
            "Cache-Control": "no-cache" if path.suffix in no_cache_suffixes else "public, max-age=3600",
        }
        self._send(HTTPStatus.OK, headers, path.read_bytes())

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        if parsed.path.startswith("/api/"):
            token = _session_token_from_cookie(self.headers.get("Cookie"))
            current_user = USER_STORE.user_for_session(token)
            if parsed.path.startswith("/api/auth/"):
                status, headers, response_body = handle_auth_api_path(parsed.path, "POST", body, token)
                self._send(status, headers, response_body)
                return
            if parsed.path.startswith("/api/users"):
                status, headers, response_body = handle_users_api_path(parsed.path, "POST", body, current_user)
                self._send(status, headers, response_body)
                return
            if not current_user:
                status, headers, response_body = _unauthorized_response()
                self._send(status, headers, response_body)
                return
            if parsed.path.startswith("/api/planning/"):
                status, headers, response_body = handle_planning_api_path(parsed.path, "POST", body)
                self._send(status, headers, response_body)
                return
            if parsed.path == "/api/evaluation/control":
                status, headers, response_body = handle_control_path(parsed.path, body)
                self._send(status, headers, response_body)
                return
            if parsed.path.startswith("/api/evaluation/"):
                status, headers, response_body = handle_evaluation_results_api_path(parsed.path, "POST", body)
                self._send(status, headers, response_body)
                return
            status, headers, response_body = handle_control_path(parsed.path, body)
            self._send(status, headers, response_body)
            return
        self._send_text(HTTPStatus.NOT_FOUND, "Not Found")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        token = _session_token_from_cookie(self.headers.get("Cookie"))
        current_user = USER_STORE.user_for_session(token)
        if parsed.path.startswith("/api/users"):
            status, headers, response_body = handle_users_api_path(parsed.path, "PUT", body, current_user)
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/") and not current_user:
            status, headers, response_body = _unauthorized_response()
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/planning/"):
            status, headers, response_body = handle_planning_api_path(parsed.path, "PUT", body)
            self._send(status, headers, response_body)
            return
        self._send_text(HTTPStatus.NOT_FOUND, "Not Found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        token = _session_token_from_cookie(self.headers.get("Cookie"))
        current_user = USER_STORE.user_for_session(token)
        if parsed.path.startswith("/api/users"):
            status, headers, response_body = handle_users_api_path(parsed.path, "DELETE", b"", current_user)
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/") and not current_user:
            status, headers, response_body = _unauthorized_response()
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/planning/"):
            status, headers, response_body = handle_planning_api_path(parsed.path, "DELETE", b"")
            self._send(status, headers, response_body)
            return
        self._send_text(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_text(self, status: int, text: str) -> None:
        self._send(status, {"Content-Type": "text/plain; charset=utf-8"}, text.encode("utf-8"))

    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(int(status))
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8866) -> None:
    server = ThreadingHTTPServer((host, port), PowerPlanHandler)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the power plan server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8866, type=int)
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()


