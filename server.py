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
import multiprocessing
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
import traceback
import zlib
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
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

import estimate
import file_ops
import plan_optimizer
import planning_store


WEB_ROOT = Path(__file__).resolve().parent
DATA_DIR = WEB_ROOT / "data"
VENDOR_DIR = WEB_ROOT / "vendor"
LOAD_CURVE_TEMPLATE_PATH = DATA_DIR / "load_curve_templates.csv"
USER_DB_PATH = Path(os.environ.get("POWER_PLAN_USER_DB", WEB_ROOT / "power_plan_users.sqlite3"))
SESSION_COOKIE_NAME = "power_plan_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
NASA_POWER_HOURLY_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
AMAP_GEOCODING_URL = "https://restapi.amap.com/v3/geocode/geo"
DEFAULT_AMAP_WEB_SERVICE_KEY = "21db26646aac8fed4620eaa36f210018"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_GEOCODING_URL = "https://photon.komoot.io/api/"
CHINESE_PLACE_ALIASES = {
    "上海": "shanghai",
    "上海市": "shanghai",
    "北京": "beijing",
    "北京市": "beijing",
    "广州": "guangzhou",
    "广州市": "guangzhou",
    "深圳": "shenzhen",
    "深圳市": "shenzhen",
    "天津": "tianjin",
    "天津市": "tianjin",
    "重庆": "chongqing",
    "重庆市": "chongqing",
    "香港": "hong kong",
    "澳门": "macau",
    "台北": "taipei",
}
OPTIMIZATION_RESULT_WORKBOOK_NAME = "opt_results.xlsx"
RESULT_WORKBOOK_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+_results\.xlsx$")
PLANNING_RESULT_SHEET_NAME = "规划结果"
PLANNING_RESULT_HEADERS = ["设备类型", "设计台数", "单台容量", "总容量", "单位"]
COMPARISON_CURVE_GROUPS = {
    "hourly": {"title": "小时级曲线", "sheet": "调度结果", "limit": 8760},
    "daily": {"title": "日级统计", "sheet": "供能日曲线", "limit": None},
    "monthly": {"title": "月度统计", "sheet": "供能月曲线", "limit": None},
}
COMPARISON_CURVE_X_HEADERS = {"小时", "hour_index", "时间", "datetime", "day", "month", "日期", "月份"}
RESULT_CURVE_FIELD_LABELS = {
    "load_energy": "负荷总电量",
    "diesel_energy": "柴发总发电量",
    "wind_energy": "风机总发电量",
    "pv_energy": "光伏总发电量",
    "storage_charge_energy": "电储能总储电量",
    "storage_discharge_energy": "电储能总放电量",
    "hydrogen_production_energy": "电制氢总用电量",
    "hydrogen_storage_increase": "氢储总增加量",
    "hydrogen_storage_decrease": "氢储总消耗量",
    "fuel_cell_energy": "燃料电池总发电量",
    "wind_available_energy": "风力最大可发电量",
    "pv_available_energy": "光伏最大可发电量",
    "renewable_available_energy": "新能源最大可发电量",
    "renewable_energy": "新能源实发电量",
    "wind_curtailed_energy": "弃风总电量",
    "pv_curtailed_energy": "弃光总电量",
    "curtailed_energy": "新能源总弃电量",
    "unmet_load_energy": "切负荷总电量",
    "renewable_ratio": "新能源占比",
    "renewable_curtailed_rate": "新能源弃电率",
}
RESULT_WORKBOOK_HEADER_TO_FIELD = {label: key for key, label in RESULT_CURVE_FIELD_LABELS.items()}
RESULT_WORKBOOK_HEADER_TO_FIELD.update(
    {
        "小时": "hour_index",
        "时间": "datetime",
        "风速": "wind_speed",
        "太阳辐射": "solar_irradiance",
        "环境温度": "temperature",
        "负荷总功率": "load",
        "柴发总功率": "diesel_power",
        "风力最大可发": "wind_available",
        "风机总功率": "wind_power",
        "光伏最大可发": "pv_available",
        "光伏总功率": "pv_power",
        "新能源最大可发": "renewable_available",
        "电储能总功率": "storage_power",
        "电储电量": "storage_soc",
        "电制氢总功率": "hydrogen_production_power",
        "储氢罐氢储量": "hydrogen_storage",
        "燃料电池总功率": "fuel_cell_power",
        "弃风总功率": "wind_curtailed_power",
        "弃光总功率": "pv_curtailed_power",
        "新能源弃电总功率": "curtailed_power",
        "切负荷功率": "unmet_load",
        "柴发启停": "diesel_on",
        "制氢启停": "electrolyzer_on",
        "储能充电": "storage_charge",
        "储能放电": "storage_discharge",
        "日期": "day",
        "月份": "month",
    }
)
STATIC_NO_STORE_SUFFIXES = {".html", ".css", ".js", ".png", ".svg", ".ico", ".map"}
NO_STORE_CACHE_CONTROL = "no-store, no-cache, max-age=0, must-revalidate"
RESULT_WORKBOOK_READ_ERRORS = (BadZipFile, zlib.error, OSError, EOFError, KeyError, InvalidFileException)
TIME_SERIES_IMPORT_ROW_COUNT = 8760
TIME_SERIES_IMPORT_REQUIRED_COLUMNS = {
    "wind_speed": ("风速", ["wind_speed", "wind", "风速", "风速(m/s)", "风速ms", "风速米秒", "ws10m"]),
    "solar_irradiance": (
        "太阳辐射",
        [
            "solar_irradiance",
            "solar",
            "irradiance",
            "solar radiation",
            "太阳辐射",
            "太阳辐照",
            "太阳辐照度",
            "单位面积太阳辐射",
            "单位面积太阳辐照",
            "太阳辐射(w/m2)",
            "太阳辐照(w/m2)",
            "太阳辐射(W/m^2)",
            "太阳辐照(W/m^2)",
            "allsky_sfc_sw_dwn",
        ],
    ),
    "temperature": ("室温", ["temperature", "temp", "室温", "温度", "环境温度", "气温", "温度(摄氏度)", "环境温度(摄氏度)", "t2m"]),
    "load": ("负荷", ["load", "负荷", "负荷功率", "负荷总功率", "用电负荷", "用电功率", "用电功率(kW)", "负荷(kW)", "负荷kw"]),
}
TIME_SERIES_IMPORT_OPTIONAL_COLUMNS = {
    "datetime": ["datetime", "time", "时间", "日期时间", "时刻", "小时", "小时序号", "hour", "hour_index"],
}
AMAP_WEB_SERVICE_KEY = (
    os.environ.get("POWER_PLAN_AMAP_KEY")
    or os.environ.get("AMAP_WEB_SERVICE_KEY")
    or os.environ.get("AMAP_KEY")
    or DEFAULT_AMAP_WEB_SERVICE_KEY
)
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
        self._process: multiprocessing.Process | None = None
        self._event_queue: multiprocessing.Queue | None = None
        self.process_id: int | None = None
        self._stop_requested = False
        self._run_token = 0
        self._append_log_unlocked("info", "规划求解待启动")

    def snapshot(self, include_hourly_curves: bool = True) -> dict:
        with self._lock:
            self._drain_events_unlocked()
            self._reap_process_unlocked()
            return self._payload_unlocked(include_hourly_curves=include_hourly_curves)

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
                self._terminate_process_unlocked()
                self._run_token += 1
                token = self._run_token
                self._append_log_unlocked("ok", f"启动规划求解，方案：{self.scheme}")
                self._append_log_unlocked("info", "后台规划求解程序已启动")
                self._event_queue = multiprocessing.Queue()
                self._process = multiprocessing.Process(
                    target=optimization_process_worker,
                    args=(self._event_queue, target_scheme, str(PLANNING_STORE.root)),
                    daemon=True,
                )
                self._process.start()
                self.process_id = self._process.pid
                return self._payload_unlocked()

        if action == "stop":
            with self._lock:
                if self.status != "运行中" or self.scheme != target_scheme:
                    raise OptimizationStateError("not_running", f"方案“{target_scheme}”没有运行")
                self._stop_requested = True
                self._terminate_process_unlocked()
                self.status = "已停止"
                self.end_time = _now_text()
                self._append_log_unlocked("warn", "停止规划求解")
                return self._payload_unlocked()

        raise ValueError(f"unknown optimization action: {action}")

    def _drain_events_unlocked(self) -> None:
        if not self._event_queue:
            return
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if not isinstance(event, dict):
                continue
            self._handle_process_event_unlocked(event)
            if not self._event_queue:
                break
        if self.status == "运行中" and self._process and not self._process.is_alive():
            self._process.join(timeout=0)
            if self.status == "运行中":
                exit_code = self._process.exitcode
                self.status = "失败"
                self.end_time = _now_text()
                self._append_log_unlocked("error", f"规划求解进程异常退出，退出码：{exit_code}")
            self._close_event_queue_unlocked()

    def _handle_process_event_unlocked(self, event: dict) -> None:
        event_type = str(event.get("type") or "log")
        if event_type == "log":
            self._append_optimizer_event_unlocked(event)
            return
        if event_type == "done":
            if self.status != "运行中" or self._stop_requested:
                return
            self.progress = 100
            self._metrics = event.get("metrics") if isinstance(event.get("metrics"), list) else []
            self._results = event.get("results") if isinstance(event.get("results"), dict) else {}
            self.status = "已完成"
            self.end_time = _now_text()
            result_path = export_optimization_results_workbook(self._payload_unlocked())
            self.result_file = str(result_path)
            self._results_exported = True
            self._append_log_unlocked("ok", f"优化结果已写入：{result_path.name}")
            self._join_finished_process_unlocked()
            self._close_event_queue_unlocked()
            return
        if event_type == "error":
            if self.status != "运行中":
                return
            self.status = "失败"
            self.end_time = _now_text()
            self._append_log_unlocked("error", str(event.get("message") or "规划求解失败"))
            self._join_finished_process_unlocked()
            self._close_event_queue_unlocked()

    def _payload_unlocked(self, include_hourly_curves: bool = True) -> dict:
        result_path = optimization_result_workbook_path(self.scheme)
        workbook_payload = (
            read_result_workbook_display_payload_for_response(result_path, include_hourly_curves=include_hourly_curves)
            if self.status != "运行中"
            else None
        )
        if workbook_payload:
            self.result_file = str(result_path)
        return {
            "status": self.status,
            "scheme": self.scheme,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "progress": self.progress,
            "result_file": self.result_file,
            "process_id": self.process_id or "",
            "elapsed_seconds": elapsed_seconds_from_times(self.start_time, self.end_time),
            "metrics": merge_runtime_metrics(self._metrics_unlocked(), workbook_payload.get("metrics", []) if workbook_payload else []),
            "results": workbook_payload.get("results", {}) if workbook_payload else (self._results if self._results else self._default_results_unlocked()),
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

    def _append_optimizer_event_unlocked(self, event: dict) -> None:
        level = str(event.get("level") or "info")
        message = str(event.get("message") or "")
        progress = event.get("progress")
        if progress is not None:
            try:
                self.progress = max(self.progress, min(100, max(0, int(progress))))
            except (TypeError, ValueError):
                pass
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

    def _terminate_process_unlocked(self) -> None:
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=2)
        if self._process and not self._process.is_alive():
            self._process.join(timeout=0)
        self._close_event_queue_unlocked()

    def _join_finished_process_unlocked(self) -> None:
        if self._process and not self._process.is_alive():
            self._process.join(timeout=0)

    def _reap_process_unlocked(self) -> None:
        if self._process and self.status != "运行中" and not self._process.is_alive():
            self._process.join(timeout=0)

    def _close_event_queue_unlocked(self) -> None:
        if not self._event_queue:
            return
        try:
            self._event_queue.close()
            self._event_queue.join_thread()
        except Exception:
            pass
        self._event_queue = None

    def _export_results_once_unlocked(self) -> None:
        if self._results_exported:
            return
        result_path = export_optimization_results_workbook(self._payload_unlocked())
        self.result_file = str(result_path)
        self._results_exported = True


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def elapsed_seconds_from_times(start_time: str, end_time: str = "") -> int:
    if not start_time:
        return 0
    try:
        start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") if end_time else datetime.now()
    except ValueError:
        return 0
    return max(0, int((end - start).total_seconds()))


class OptimizationStateError(RuntimeError):
    """Raised when optimization start/stop violates the current runtime state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def optimization_process_worker(event_queue, scheme: str, planning_root: str = "") -> None:
    """Run planning optimization in a child process and report serializable events."""
    try:
        event_queue.put({"type": "log", "level": "info", "message": "读取方案参数和8760时序数据"})
        store = planning_store.PlanningStore(root=Path(planning_root)) if planning_root else PLANNING_STORE
        scheme_payload = store.read_scheme(scheme)
        result = plan_optimizer.run_optimization(
            scheme_payload,
            log=lambda event: event_queue.put({"type": "log", **dict(event or {})}),
        )
        event_queue.put(
            {
                "type": "done",
                "metrics": result.get("metrics") if isinstance(result.get("metrics"), list) else [],
                "results": result.get("results") if isinstance(result.get("results"), dict) else {},
            }
        )
    except Exception as exc:
        event_queue.put({"type": "error", "message": f"规划求解失败：{exc}", "traceback": traceback.format_exc()})


def evaluation_process_worker(event_queue, scheme: str, filename: str, planning_root: str = "") -> None:
    """Run fixed-plan evaluation in a child process and report serializable events."""
    try:
        event_queue.put({"type": "log", "level": "info", "message": "读取方案参数和当前规划结果"})
        store = planning_store.PlanningStore(root=Path(planning_root)) if planning_root else PLANNING_STORE
        scheme_payload = store.read_scheme(scheme)
        planning_rows = read_evaluation_planning_result_rows_with_store(store, scheme, filename)
        if not planning_rows:
            raise ValueError("当前结果文件缺少规划结果")
        result = estimate.run_estimation(
            scheme_payload,
            planning_rows,
            log=lambda event: event_queue.put({"type": "log", **dict(event or {})}),
        )
        event_queue.put(
            {
                "type": "done",
                "metrics": result.get("metrics") if isinstance(result.get("metrics"), list) else [],
                "results": result.get("results") if isinstance(result.get("results"), dict) else {},
                "dispatch_rows": result.get("dispatch_rows") if isinstance(result.get("dispatch_rows"), list) else [],
            }
        )
    except Exception as exc:
        event_queue.put({"type": "error", "message": f"方案评估失败：{exc}", "traceback": traceback.format_exc()})


def export_optimization_results_workbook(payload: dict) -> Path:
    scheme = str(payload.get("scheme") or "未选择方案")
    result_path = optimization_result_workbook_path(scheme)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = build_optimization_results_workbook(payload)
    tmp_path = result_path.with_name(f".{result_path.name}.tmp")
    try:
        file_ops.save_workbook_with_retry(workbook, tmp_path, "结果文件")
    finally:
        workbook.close()
    replace_result_workbook_with_retry(tmp_path, result_path)
    return result_path


def optimization_result_workbook_path(scheme: str) -> Path:
    return PLANNING_STORE.scheme_dir(str(scheme or "未选择方案")) / OPTIMIZATION_RESULT_WORKBOOK_NAME


def export_evaluation_results_workbook(payload: dict, dispatch_rows: list[dict]) -> Path:
    scheme = str(payload.get("scheme") or "未选择方案")
    filename = str(payload.get("result_filename") or "").strip()
    result_path = evaluation_result_path(scheme, filename)
    if result_path.name == OPTIMIZATION_RESULT_WORKBOOK_NAME:
        raise ValueError("默认结果文件不允许修改")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = build_optimization_results_workbook(payload)
    tmp_path = result_path.with_name(f".{result_path.name}.tmp")
    try:
        file_ops.save_workbook_with_retry(workbook, tmp_path, "结果文件")
    finally:
        workbook.close()
    replace_result_workbook_with_retry(tmp_path, result_path)
    return result_path


def replace_result_workbook_with_retry(source: Path, target: Path, attempts: int = 20, delay_seconds: float = 0.1) -> None:
    file_ops.retry_file_operation(
        lambda: source.replace(target),
        f"结果文件被占用，无法保存：{target.name}。请关闭正在打开该文件的 Excel 或预览窗口后重试。",
        attempts=attempts,
        delay_seconds=delay_seconds,
    )


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
            item = {"name": path.name, "modified_at": path.stat().st_mtime, "readable": True, "message": ""}
            error_message = result_workbook_error_message(path)
            if error_message:
                item["readable"] = False
                item["message"] = error_message
            files.append(item)
    return files


def selected_evaluation_result_filename(scheme: str, filename: str = "") -> str:
    files = list_evaluation_result_files(scheme)
    names = [item["name"] for item in files]
    readable_names = [item["name"] for item in files if item.get("readable", True)]
    selected = str(filename or "").strip()
    if selected and selected in names:
        return selected
    return readable_names[0] if readable_names else ""


def result_workbook_error_message(path: Path) -> str:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        workbook.close()
        return ""
    except RESULT_WORKBOOK_READ_ERRORS:
        return "结果文件无法读取，可能已损坏或格式不正确"


def evaluation_result_path(scheme: str, filename: str) -> Path:
    return evaluation_result_path_with_store(PLANNING_STORE, scheme, filename)


def evaluation_result_path_with_store(store: planning_store.PlanningStore, scheme: str, filename: str) -> Path:
    name = str(filename or "").strip()
    if not RESULT_WORKBOOK_RE.fullmatch(name):
        raise ValueError("结果文件名必须符合 xxxx_results.xlsx")
    folder = store.scheme_dir(scheme)
    path = (folder / name).resolve()
    if folder not in path.parents or path.parent != folder:
        raise ValueError("结果文件路径越界")
    return path


def read_evaluation_planning_result_rows(scheme: str, filename: str) -> list[dict]:
    return read_evaluation_planning_result_rows_with_store(PLANNING_STORE, scheme, filename)


def read_evaluation_planning_result_rows_with_store(
    store: planning_store.PlanningStore,
    scheme: str,
    filename: str,
) -> list[dict]:
    if not filename:
        return []
    result_path = evaluation_result_path_with_store(store, scheme, filename)
    if not result_path.exists():
        return []
    try:
        workbook = load_workbook(result_path, read_only=True, data_only=True)
    except RESULT_WORKBOOK_READ_ERRORS as exc:
        raise ValueError(f"结果文件无法读取: {result_path.name}") from exc
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
                normalize_planning_result_total_capacity(item)
                result_rows.append(item)
        return result_rows
    finally:
        workbook.close()


def normalize_planning_result_total_capacity(row: dict) -> dict:
    if "设计台数" in row and "单台容量" in row:
        row["总容量"] = round(
            estimate.numeric(row.get("设计台数"), 0.0) * estimate.numeric(row.get("单台容量"), 0.0),
            4,
        )
    return row


def read_evaluation_planning_result_rows_for_response(scheme: str, filename: str) -> list[dict]:
    try:
        return read_evaluation_planning_result_rows(scheme, filename)
    except ValueError:
        return []


def handle_comparison_data_api_path(path: str, query: str = "") -> tuple[int, dict[str, str], bytes]:
    if path != "/api/comparison/data":
        return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
    try:
        query_params = parse_qs(query)
        items_text = query_params.get("items", ["[]"])[0]
        mode = str(query_params.get("mode", ["full"])[0] or "full").strip().lower()
        include_hourly_curves = mode not in {"summary", "tables", "light"}
        items = json.loads(items_text or "[]")
        if not isinstance(items, list):
            raise ValueError("对比项必须为列表")
        return _json_response(build_comparison_payload(items[:4], include_hourly_curves=include_hourly_curves))
    except FileNotFoundError as exc:
        return _json_response({"error": "not_found", "message": str(exc)}, HTTPStatus.NOT_FOUND)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)


def build_comparison_payload(items: list[dict], include_hourly_curves: bool = True) -> dict:
    selected_items: list[dict] = []
    capacity_tables: list[list[dict]] = []
    energy_tables: list[list[dict]] = []
    safety_tables: list[list[dict]] = []
    annual_tables: list[list[dict]] = []
    curve_groups = empty_comparison_curve_groups()

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
        workbook_data = read_comparison_workbook(result_path, include_hourly_curves=include_hourly_curves)
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
        annual_tables.append(workbook_data["annual"])
        append_comparison_curve_groups(curve_groups, workbook_data["curve_groups"], label, scheme, filename)

    hourly_group = curve_groups["hourly"]

    return {
        "items": selected_items,
        "tables": {
            "capacity": merge_comparison_rows(capacity_tables, selected_items, "设备类型"),
            "energy": merge_comparison_rows(energy_tables, selected_items, "指标"),
            "safety": merge_comparison_rows(safety_tables, selected_items, "指标"),
        },
        "curve_groups": curve_groups,
        "annual_table": merge_comparison_rows(annual_tables, selected_items, "指标"),
        "curves": hourly_group["curves"],
        "series": hourly_group["series"],
    }


def read_comparison_workbook(path: Path, include_hourly_curves: bool = True) -> dict:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except RESULT_WORKBOOK_READ_ERRORS as exc:
        raise ValueError(f"结果文件无法读取: {path.name}") from exc
    try:
        curve_groups = {}
        for key, config in COMPARISON_CURVE_GROUPS.items():
            if key == "hourly" and not include_hourly_curves:
                curve_groups[key] = {}
            else:
                curve_groups[key] = read_curve_sheet(workbook, config["sheet"], config["limit"])
        return {
            "capacity": read_named_sheet_rows(workbook, "规划结果"),
            "energy": read_named_sheet_rows(workbook, "供能分析"),
            "safety": read_named_sheet_rows(workbook, "安全评估"),
            "annual": read_annual_comparison_rows(workbook),
            "curve_groups": curve_groups,
            "curves": curve_groups["hourly"],
        }
    finally:
        workbook.close()


def read_result_workbook_display_payload_for_response(path: Path, include_hourly_curves: bool = True) -> dict | None:
    try:
        if not path.exists():
            return None
        return read_result_workbook_display_payload(path, include_hourly_curves=include_hourly_curves)
    except (ValueError, FileNotFoundError):
        return None


def read_result_workbook_display_payload(path: Path, include_hourly_curves: bool = True) -> dict:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except RESULT_WORKBOOK_READ_ERRORS as exc:
        raise ValueError(f"结果文件无法读取: {path.name}") from exc
    try:
        planning_rows = read_named_sheet_rows(workbook, "规划结果")
        for row in planning_rows:
            normalize_planning_result_total_capacity(row)
        annual_rows = read_named_sheet_rows(workbook, "规划年指标")
        green_daily = read_workbook_rows_with_field_map(workbook, "供能日曲线", limit=365)
        green_monthly = read_workbook_rows_with_field_map(workbook, "供能月曲线", limit=12)
        green_hourly = (
            read_workbook_rows_with_field_map(workbook, "调度结果", limit=8760)
            if include_hourly_curves
            else []
        )
        safety_daily = read_workbook_rows_with_field_map(workbook, "安全日曲线", limit=365)
        return {
            "metrics": read_result_workbook_metrics(workbook),
            "results": {
                "overview_tables": [
                    {"title": "规划结果", "rows": planning_rows},
                    {"title": "规划年指标", "rows": annual_rows},
                ],
                "overview_disks": build_overview_composition_from_workbook(workbook),
                "overview": [],
                "green": [],
                "green_table": read_named_sheet_rows(workbook, "供能分析"),
                "safety": [],
                "safety_table": read_named_sheet_rows(workbook, "安全评估"),
                "curves": {
                    "green_daily": green_daily,
                    "green_monthly": green_monthly,
                    "green_hourly": green_hourly,
                    "safety_daily": safety_daily,
                },
            },
        }
    finally:
        workbook.close()


def read_result_workbook_metrics(workbook) -> list[dict]:
    rows = read_named_sheet_rows(workbook, "总体指标")
    metrics = []
    for row in rows:
        label = str(row.get("指标", "")).strip()
        if not label or label in {"方案", "状态", "进度"}:
            continue
        metrics.append({"label": label, "value": row.get("数值", ""), "unit": row.get("单位", "")})
    return metrics


def merge_runtime_metrics(runtime_metrics: list[dict], workbook_metrics: list[dict]) -> list[dict]:
    if not workbook_metrics:
        return runtime_metrics
    primary_labels = {"当前状态", "启动时刻", "结束时刻"}
    primary = [item for item in runtime_metrics if isinstance(item, dict) and str(item.get("label", "")) in primary_labels]
    secondary = [item for item in runtime_metrics if isinstance(item, dict) and str(item.get("label", "")) not in primary_labels]
    merged = list(primary)
    existing = {str(item.get("label", "")) for item in merged if isinstance(item, dict)}
    for metric in workbook_metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label", "")).strip()
        if not label or label in existing:
            continue
        merged.append(metric)
        existing.add(label)
    for metric in secondary:
        label = str(metric.get("label", "")).strip()
        if label and label not in existing:
            merged.append(metric)
            existing.add(label)
    return merged


def read_workbook_rows_with_field_map(workbook, sheet_name: str, limit: int | None = None) -> list[dict]:
    if sheet_name not in workbook.sheetnames:
        return []
    sheet = workbook[sheet_name]
    rows_iter = sheet.iter_rows(values_only=True)
    raw_headers = [str(value or "").strip() for value in next(rows_iter, [])]
    headers = [result_workbook_header_to_field(header) for header in raw_headers]
    rows = []
    for row_index, row in enumerate(rows_iter, start=1):
        if limit is not None and row_index > limit:
            break
        item = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            value = row[index] if index < len(row) else ""
            if value not in (None, ""):
                item[header] = value
        if item:
            rows.append(item)
    return rows


def result_workbook_header_to_field(header: str) -> str:
    clean = str(header or "").strip()
    return RESULT_WORKBOOK_HEADER_TO_FIELD.get(clean, clean)


def build_overview_composition_from_workbook(workbook) -> list[dict]:
    annual_rows = read_annual_comparison_rows(workbook)
    energy_rows = read_named_sheet_rows(workbook, "供能分析")
    metrics = rows_by_metric([*annual_rows, *energy_rows])
    construction_cost = metric_value(metrics, "年均建设成本")
    diesel_cost = metric_value(metrics, "年柴油成本")
    if construction_cost == 0 and diesel_cost == 0:
        total_cost = metric_value(metrics, "年总成本") or metric_value(metrics, "总成本")
        if total_cost:
            construction_cost = total_cost
    diesel_energy = metric_value(metrics, "柴发总发电量") or metric_value(metrics, "柴发总电量")
    green_energy = metric_value(metrics, "绿电年发电量") or metric_value(metrics, "新能源实发电量")
    if green_energy == 0:
        green_energy = (
            metric_value(metrics, "风机总发电量")
            + metric_value(metrics, "光伏总发电量")
            + metric_value(metrics, "电储能总放电量")
            + metric_value(metrics, "燃料电池总发电量")
        )
    return [
        {
            "title": "成本构成",
            "left_label": "年柴油成本",
            "left_value": diesel_cost,
            "right_label": "年均建设成本",
            "right_value": construction_cost,
            "unit": "万元",
        },
        {
            "title": "电量构成",
            "left_label": "柴发电量",
            "left_value": diesel_energy,
            "right_label": "绿电电量",
            "right_value": green_energy,
            "unit": energy_unit(metrics, ["柴发总发电量", "柴发总电量", "绿电年发电量", "新能源实发电量"]) or "kWh",
        },
    ]


def rows_by_metric(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("指标", "")).strip()
        if name and name not in result:
            result[name] = row
    return result


def metric_value(metrics: dict[str, dict], name: str) -> float:
    row = metrics.get(name) or {}
    value = _numeric_or_none(row.get("数值"))
    return float(value) if value is not None else 0.0


def energy_unit(metrics: dict[str, dict], names: list[str]) -> str:
    for name in names:
        unit = str((metrics.get(name) or {}).get("单位", "")).strip()
        if unit:
            return unit
    return ""


def empty_comparison_curve_groups() -> dict:
    return {
        key: {"title": config["title"], "curves": [], "series": {}}
        for key, config in COMPARISON_CURVE_GROUPS.items()
    }


def append_comparison_curve_groups(target_groups: dict, source_groups: dict, label: str, scheme: str, filename: str) -> None:
    for key, config in COMPARISON_CURVE_GROUPS.items():
        target_group = target_groups.setdefault(key, {"title": config["title"], "curves": [], "series": {}})
        source_group = source_groups.get(key, {}) if isinstance(source_groups, dict) else {}
        for name, points in source_group.items():
            if name not in target_group["curves"]:
                target_group["curves"].append(name)
            target_group["series"].setdefault(name, []).append(
                {
                    "label": label,
                    "scheme": scheme,
                    "filename": filename,
                    "points": points,
                }
            )


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


def read_annual_comparison_rows(workbook) -> list[dict]:
    rows = read_named_sheet_rows(workbook, "规划年指标")
    if rows:
        return rows
    return read_named_sheet_rows(workbook, "供能分析")


def read_dispatch_curves(workbook) -> dict[str, list[dict]]:
    return read_curve_sheet(workbook, "调度结果", 8760)


def read_curve_sheet(workbook, sheet_name: str, limit: int | None = None) -> dict[str, list[dict]]:
    if sheet_name not in workbook.sheetnames:
        return {}
    sheet = workbook[sheet_name]
    rows_iter = sheet.iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(rows_iter, [])]
    curves: dict[str, list[dict]] = {}
    for header in headers:
        if header and header not in COMPARISON_CURVE_X_HEADERS:
            curves[result_curve_display_name(header)] = []
    for row_index, row in enumerate(rows_iter, start=1):
        if limit is not None and row_index > limit:
            break
        x_value = row[0] if len(row) > 0 and row[0] not in (None, "") else row_index
        for column_index, header in enumerate(headers):
            display_name = result_curve_display_name(header)
            if display_name not in curves:
                continue
            value = row[column_index] if column_index < len(row) else None
            number = _numeric_or_none(value)
            if number is not None:
                curves[display_name].append({"x": x_value, "y": number})
    return curves


def result_curve_display_name(header: str) -> str:
    return RESULT_CURVE_FIELD_LABELS.get(str(header or "").strip(), str(header or "").strip())


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
        unit_capacity_column = headers.index("单台容量") + 1 if "单台容量" in headers else None
        total_capacity_column = headers.index("总容量") + 1 if "总容量" in headers else None

        for row_index in range(2, sheet.max_row + 1):
            device_type = str(sheet.cell(row=row_index, column=device_column).value or "").strip()
            if device_type in counts_by_device:
                count = normalize_planning_count(counts_by_device[device_type])
                sheet.cell(row=row_index, column=count_column).value = count
                if total_capacity_column and unit_capacity_column and count != "":
                    unit_capacity = estimate.numeric(sheet.cell(row=row_index, column=unit_capacity_column).value, 0.0)
                    sheet.cell(row=row_index, column=total_capacity_column).value = round(count * unit_capacity, 4)

        tmp_path = result_path.with_name(f".{result_path.name}.tmp")
        file_ops.save_workbook_with_retry(workbook, tmp_path, "结果文件")
    finally:
        workbook.close()
    replace_result_workbook_with_retry(tmp_path, result_path)
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
                    "planning_result_rows": read_evaluation_planning_result_rows_for_response(scheme, selected),
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
                file_ops.delete_file_with_retry(result_path, "结果文件")
            selected = selected_evaluation_result_filename(scheme)
            return _json_response(
                {
                    "selected": selected,
                    "results": list_evaluation_result_files(scheme),
                    "planning_result_rows": read_evaluation_planning_result_rows_for_response(scheme, selected),
                }
            )

        if action == "copy":
            source_path = evaluation_result_path(scheme, filename)
            if not source_path.exists():
                raise FileNotFoundError(f"结果文件不存在: {source_path.name}")
            source_error = result_workbook_error_message(source_path)
            if source_error:
                raise ValueError(f"复制失败，当前结果文件无法读取: {source_path.name}")
            target_filename = evaluation_result_filename_from_name(str(payload.get("target_name", "")))
            target_path = evaluation_result_path(scheme, target_filename)
            if target_path.exists():
                if not result_workbook_error_message(target_path):
                    return _json_response(
                        {"error": "exists", "message": f"复制失败，结果文件已存在: {target_path.name}"},
                        HTTPStatus.CONFLICT,
                    )
                if target_path.name == OPTIMIZATION_RESULT_WORKBOOK_NAME:
                    raise ValueError("默认结果文件不允许覆盖")
            file_ops.copy_file_with_retry(source_path, target_path, "结果文件")
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
    except PermissionError as exc:
        return _json_response({"error": "file_locked", "message": str(exc)}, HTTPStatus.CONFLICT)
    except ValueError as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)


class OptimizationRuntimeManager:
    """Holds independent optimization runtimes for multiple schemes."""

    def __init__(self) -> None:
        self._runtimes: dict[str, OptimizationRuntime] = {}
        self._lock = threading.Lock()

    def snapshot(self, scheme: str = "", include_hourly_curves: bool = True) -> dict:
        runtime = self._runtime_for_scheme(scheme)
        payload = runtime.snapshot(include_hourly_curves=include_hourly_curves)
        payload["running_schemes"] = self.running_schemes()
        append_task_control_state(payload, "optimization", self._scheme_name(scheme), OPTIMIZATION_RESULT_WORKBOOK_NAME)
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
            if runtime.status == "运行中":
                running.append(scheme)
        return running

    def runtimes(self) -> dict[str, OptimizationRuntime]:
        with self._lock:
            return dict(self._runtimes)

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
        self._process: multiprocessing.Process | None = None
        self._event_queue: multiprocessing.Queue | None = None
        self.process_id: int | None = None
        self._stop_requested = False
        self._run_token = 0
        self._append_log_unlocked("info", "方案评估待启动")

    def snapshot(self, include_hourly_curves: bool = True) -> dict:
        with self._lock:
            self._drain_events_unlocked()
            self._reap_process_unlocked()
            return self._payload_unlocked(include_hourly_curves=include_hourly_curves)

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
                self._terminate_process_unlocked()
                self._run_token += 1
                token = self._run_token
                self._append_log_unlocked("ok", f"启动方案评估，方案：{self.scheme}，结果：{self.result_filename}")
                self._append_log_unlocked("info", "后台评估程序已启动")
                self._event_queue = multiprocessing.Queue()
                self._process = multiprocessing.Process(
                    target=evaluation_process_worker,
                    args=(self._event_queue, target_scheme, target_filename, str(PLANNING_STORE.root)),
                    daemon=True,
                )
                self._process.start()
                self.process_id = self._process.pid
                return self._payload_unlocked()

        if action == "stop":
            with self._lock:
                if self.status != "运行中" or self.scheme != target_scheme:
                    raise OptimizationStateError("not_running", f"方案“{target_scheme}”没有运行")
                self._stop_requested = True
                self._terminate_process_unlocked()
                self.status = "已停止"
                self.end_time = _now_text()
                self._append_log_unlocked("warn", "停止方案评估")
                return self._payload_unlocked()

        raise ValueError(f"unknown evaluation action: {action}")

    def _drain_events_unlocked(self) -> None:
        if not self._event_queue:
            return
        while True:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if not isinstance(event, dict):
                continue
            self._handle_process_event_unlocked(event)
            if not self._event_queue:
                break
        if self.status == "运行中" and self._process and not self._process.is_alive():
            self._process.join(timeout=0)
            if self.status == "运行中":
                exit_code = self._process.exitcode
                self.status = "失败"
                self.end_time = _now_text()
                self._append_log_unlocked("error", f"方案评估进程异常退出，退出码：{exit_code}")
            self._close_event_queue_unlocked()

    def _handle_process_event_unlocked(self, event: dict) -> None:
        event_type = str(event.get("type") or "log")
        if event_type == "log":
            self._append_estimate_event_unlocked(event)
            return
        if event_type == "done":
            if self.status != "运行中" or self._stop_requested:
                return
            self.progress = 100
            self._metrics = event.get("metrics") if isinstance(event.get("metrics"), list) else []
            self._results = event.get("results") if isinstance(event.get("results"), dict) else {}
            dispatch_rows = event.get("dispatch_rows") if isinstance(event.get("dispatch_rows"), list) else []
            result_path = export_evaluation_results_workbook(self._payload_unlocked(), dispatch_rows)
            self.result_file = str(result_path)
            self._append_log_unlocked("ok", f"评估结果已写入：{result_path.name}")
            self.status = "已完成"
            self.end_time = _now_text()
            self._join_finished_process_unlocked()
            self._close_event_queue_unlocked()
            return
        if event_type == "error":
            if self.status != "运行中":
                return
            self.status = "失败"
            self.end_time = _now_text()
            self._append_log_unlocked("error", str(event.get("message") or "方案评估失败"))
            self._join_finished_process_unlocked()
            self._close_event_queue_unlocked()

    def _append_estimate_event_unlocked(self, event: dict) -> None:
        level = str(event.get("level") or "info")
        message = str(event.get("message") or "")
        progress = event.get("progress")
        if progress is not None:
            try:
                self.progress = max(self.progress, min(100, max(0, int(progress))))
            except (TypeError, ValueError):
                pass
        if message:
            self._append_log_unlocked(level, message)

    def _payload_unlocked(self, include_hourly_curves: bool = True) -> dict:
        workbook_payload = None
        if self.status != "运行中" and self.result_filename:
            try:
                workbook_payload = read_result_workbook_display_payload_for_response(
                    evaluation_result_path(self.scheme, self.result_filename),
                    include_hourly_curves=include_hourly_curves,
                )
            except ValueError:
                workbook_payload = None
        return {
            "status": self.status,
            "scheme": self.scheme,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "progress": self.progress,
            "result_filename": self.result_filename,
            "result_file": self.result_file,
            "process_id": self.process_id or "",
            "elapsed_seconds": elapsed_seconds_from_times(self.start_time, self.end_time),
            "metrics": merge_runtime_metrics(self._metrics_unlocked(), workbook_payload.get("metrics", []) if workbook_payload else []),
            "results": workbook_payload.get("results", {}) if workbook_payload else (self._results if self._results else self._default_results_unlocked()),
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

    def _terminate_process_unlocked(self) -> None:
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=2)
        if self._process and not self._process.is_alive():
            self._process.join(timeout=0)
        self._close_event_queue_unlocked()

    def _join_finished_process_unlocked(self) -> None:
        if self._process and not self._process.is_alive():
            self._process.join(timeout=0)

    def _reap_process_unlocked(self) -> None:
        if self._process and self.status != "运行中" and not self._process.is_alive():
            self._process.join(timeout=0)

    def _close_event_queue_unlocked(self) -> None:
        if not self._event_queue:
            return
        try:
            self._event_queue.close()
            self._event_queue.join_thread()
        except Exception:
            pass
        self._event_queue = None


class EvaluationRuntimeManager:
    """Holds independent evaluation runtimes for multiple schemes."""

    def __init__(self) -> None:
        self._runtimes: dict[str, EvaluationRuntime] = {}
        self._lock = threading.Lock()

    def snapshot(self, scheme: str = "", filename: str = "", include_hourly_curves: bool = True) -> dict:
        runtime = self._runtime_for_result(scheme, filename)
        payload = runtime.snapshot(include_hourly_curves=include_hourly_curves)
        payload["running_schemes"] = self.running_schemes()
        append_task_control_state(
            payload,
            "evaluation",
            self._scheme_name(scheme),
            payload.get("result_filename") or self._result_filename(self._scheme_name(scheme), filename),
        )
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
            if runtime.status == "运行中":
                running.append(key.split("\0", 1)[0])
        return sorted(set(running))

    def runtimes(self) -> dict[str, EvaluationRuntime]:
        with self._lock:
            return dict(self._runtimes)

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


class TaskScheduler:
    """Serial queue for calculation tasks that should wait for existing jobs."""

    def __init__(self) -> None:
        self._queue: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def enqueue(self, task_type_key: str, scheme: str, result: str = "") -> dict:
        item = normalized_task_item(task_type_key, scheme, result)
        with self._lock:
            if not any(same_task_item(item, existing) for existing in self._queue):
                self._queue.append(item)
            return dict(item)

    def remove(self, task_type_key: str, scheme: str, result: str = "") -> None:
        item = normalized_task_item(task_type_key, scheme, result)
        with self._lock:
            self._queue = [existing for existing in self._queue if not same_task_item(item, existing)]

    def remove_running_or_finished(self) -> None:
        with self._lock:
            self._queue = [item for item in self._queue if not is_task_running_or_finished(item)]

    def queued_items(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(item) for item in self._queue]

    def is_queued(self, task_type_key: str, scheme: str, result: str = "") -> bool:
        item = normalized_task_item(task_type_key, scheme, result)
        with self._lock:
            return any(same_task_item(item, existing) for existing in self._queue)

    def queue_position(self, task_type_key: str, scheme: str, result: str = "") -> int:
        item = normalized_task_item(task_type_key, scheme, result)
        with self._lock:
            for index, existing in enumerate(self._queue, start=1):
                if same_task_item(item, existing):
                    return index
        return 0

    def schedule_next_if_idle(self) -> None:
        with self._lock:
            if any_calculation_running_unlocked():
                return
            while self._queue:
                item = self._queue.pop(0)
                try:
                    start_task_item_unlocked(item)
                    return
                except Exception:
                    continue


def normalized_task_item(task_type_key: str, scheme: str, result: str = "") -> dict[str, str]:
    normalized_type = normalize_task_type_key(task_type_key)
    normalized_result = str(result or "").strip()
    if normalized_type == "optimization":
        normalized_result = OPTIMIZATION_RESULT_WORKBOOK_NAME
    return {
        "task_type_key": normalized_type,
        "scheme": str(scheme or "未选择方案").strip() or "未选择方案",
        "result": normalized_result,
    }


def same_task_item(left: dict, right: dict) -> bool:
    return (
        left.get("task_type_key") == right.get("task_type_key")
        and left.get("scheme") == right.get("scheme")
        and (left.get("result") or "") == (right.get("result") or "")
    )


def is_task_running_or_finished(item: dict) -> bool:
    runtime = runtime_for_task_item(item)
    return bool(runtime and runtime.status in {"运行中", "已完成"})


def runtime_for_task_item(item: dict):
    task_type_key = item.get("task_type_key")
    scheme = item.get("scheme", "")
    result = item.get("result", "")
    if task_type_key == "optimization":
        return OPTIMIZATION_RUNTIME.runtimes().get(scheme)
    if task_type_key == "evaluation":
        return EVALUATION_RUNTIME.runtimes().get(f"{scheme}\0{result}")
    return None


def any_calculation_running_unlocked() -> bool:
    return any(runtime.status == "运行中" for runtime in OPTIMIZATION_RUNTIME.runtimes().values()) or any(
        runtime.status == "运行中" for runtime in EVALUATION_RUNTIME.runtimes().values()
    )


def start_task_item_unlocked(item: dict) -> dict:
    task_type_key = item.get("task_type_key")
    if task_type_key == "optimization":
        return OPTIMIZATION_RUNTIME.apply("start", scheme=item.get("scheme", ""))
    if task_type_key == "evaluation":
        return EVALUATION_RUNTIME.apply("start", scheme=item.get("scheme", ""), filename=item.get("result", ""))
    raise ValueError("任务类型必须为规划计算或方案评估")


def build_task_list() -> list[dict]:
    TASK_SCHEDULER.remove_running_or_finished()
    TASK_SCHEDULER.schedule_next_if_idle()
    tasks: dict[str, dict] = {}
    for scheme_item in safe_list_schemes_for_tasks():
        scheme = str(scheme_item.get("name") or "").strip()
        if not scheme:
            continue
        runtime = OPTIMIZATION_RUNTIME.runtimes().get(scheme)
        state = runtime.snapshot(include_hourly_curves=False) if runtime else default_task_runtime_state(scheme)
        task = task_from_runtime_state(
            "optimization",
            state,
            scheme=scheme,
            result=OPTIMIZATION_RESULT_WORKBOOK_NAME,
            queued=TASK_SCHEDULER.is_queued("optimization", scheme, OPTIMIZATION_RESULT_WORKBOOK_NAME),
            queue_position=TASK_SCHEDULER.queue_position("optimization", scheme, OPTIMIZATION_RESULT_WORKBOOK_NAME),
        )
        tasks[task["id"]] = task
        for result_item in safe_list_results_for_tasks(scheme):
            result_name = str(result_item.get("name") or "").strip()
            if not result_name:
                continue
            if not task_list_evaluation_result_is_eligible(result_item):
                continue
            key = f"{scheme}\0{result_name}"
            eval_runtime = EVALUATION_RUNTIME.runtimes().get(key)
            eval_state = (
                eval_runtime.snapshot(include_hourly_curves=False)
                if eval_runtime
                else default_task_runtime_state(scheme, result_filename=result_name)
            )
            eval_task = task_from_runtime_state(
                "evaluation",
                eval_state,
                scheme=scheme,
                result=result_name,
                queued=TASK_SCHEDULER.is_queued("evaluation", scheme, result_name),
                queue_position=TASK_SCHEDULER.queue_position("evaluation", scheme, result_name),
            )
            tasks[eval_task["id"]] = eval_task

    for scheme, runtime in OPTIMIZATION_RUNTIME.runtimes().items():
        state = runtime.snapshot(include_hourly_curves=False)
        task = task_from_runtime_state(
            "optimization",
            state,
            scheme=scheme,
            result=OPTIMIZATION_RESULT_WORKBOOK_NAME,
            queued=TASK_SCHEDULER.is_queued("optimization", scheme, OPTIMIZATION_RESULT_WORKBOOK_NAME),
            queue_position=TASK_SCHEDULER.queue_position("optimization", scheme, OPTIMIZATION_RESULT_WORKBOOK_NAME),
        )
        tasks[task["id"]] = task

    for key, runtime in EVALUATION_RUNTIME.runtimes().items():
        scheme, result = split_evaluation_runtime_key(key)
        queued = TASK_SCHEDULER.is_queued("evaluation", scheme, result)
        if result == OPTIMIZATION_RESULT_WORKBOOK_NAME and runtime.status != "运行中" and not queued:
            continue
        state = runtime.snapshot(include_hourly_curves=False)
        task = task_from_runtime_state(
            "evaluation",
            state,
            scheme=scheme,
            result=result,
            queued=queued,
            queue_position=TASK_SCHEDULER.queue_position("evaluation", scheme, result),
        )
        tasks[task["id"]] = task

    return sorted(tasks.values(), key=task_sort_key)


def task_list_evaluation_result_is_eligible(result_item: dict) -> bool:
    result_name = str(result_item.get("name") or "").strip()
    return bool(result_name) and result_name != OPTIMIZATION_RESULT_WORKBOOK_NAME and bool(result_item.get("readable", True))


def task_sort_key(item: dict) -> tuple[int, str, str]:
    type_rank = 0 if item.get("task_type_key") == "optimization" else 1
    return type_rank, str(item.get("scheme") or ""), str(item.get("result") or "")


def safe_list_schemes_for_tasks() -> list[dict]:
    try:
        return PLANNING_STORE.list_schemes()
    except Exception:
        return []


def safe_list_results_for_tasks(scheme: str) -> list[dict]:
    try:
        return list_evaluation_result_files(scheme)
    except Exception:
        return []


def split_evaluation_runtime_key(key: str) -> tuple[str, str]:
    if "\0" in key:
        scheme, result = key.split("\0", 1)
        return scheme, result
    return key, ""


def default_task_runtime_state(scheme: str, result_filename: str = "") -> dict:
    return {
        "status": "待启动",
        "scheme": scheme,
        "result_filename": result_filename,
        "start_time": "",
        "end_time": "",
        "process_id": "",
        "elapsed_seconds": 0,
        "logs": [],
    }


def task_from_runtime_state(
    task_type_key: str,
    state: dict,
    scheme: str,
    result: str = "",
    queued: bool = False,
    queue_position: int = 0,
) -> dict:
    runtime_status = str(state.get("status") or "待启动")
    normalized_result = result or str(state.get("result_filename") or "") or OPTIMIZATION_RESULT_WORKBOOK_NAME
    latest_log = latest_log_message(state.get("logs"))
    display_status = task_display_status(runtime_status, queued)
    process_id = state.get("process_id") or ""
    if isinstance(process_id, str) and process_id.isdigit():
        process_id = int(process_id)
    task_type = "规划计算" if task_type_key == "optimization" else "方案评估"
    task_id = f"{task_type_key}::{scheme}::{normalized_result}"
    return {
        "id": task_id,
        "task_key": task_id,
        "task_type": task_type,
        "task_type_key": task_type_key,
        "scheme": scheme,
        "result": normalized_result,
        "status": display_status,
        "runtime_status": runtime_status,
        "queued": bool(queued),
        "queue_position": int(queue_position or 0),
        "process_id": process_id,
        "start_time": state.get("start_time") or "",
        "end_time": state.get("end_time") or "",
        "elapsed_seconds": int(state.get("elapsed_seconds") or elapsed_seconds_from_times(state.get("start_time", ""), state.get("end_time", ""))),
        "latest_log": latest_log,
        "can_start": runtime_status != "运行中",
        "can_queue": runtime_status != "运行中" and not queued,
        "can_stop": runtime_status == "运行中",
    }


def task_display_status(runtime_status: str, queued: bool = False) -> str:
    if runtime_status == "运行中":
        return "计算中"
    if queued:
        return "排队中"
    if runtime_status == "已完成":
        return "完成计算"
    return "未计算"


def latest_log_message(logs: object) -> str:
    if not isinstance(logs, list) or not logs:
        return ""
    for item in reversed(logs):
        if isinstance(item, dict) and item.get("message"):
            return str(item.get("message"))
    return ""


def build_task_control_response(action: str, task_type: str, scheme: str, result: str = "") -> dict:
    task_type_key = normalize_task_type_key(task_type)
    normalized_action = normalize_task_action(action)
    if normalized_action == "cancel_queue":
        item = normalized_task_item(task_type_key, scheme, result)
        TASK_SCHEDULER.remove(task_type_key, scheme, result)
        tasks = build_task_list()
        task = find_task_in_list(tasks, item, queued=False)
        return {"ok": True, "task": task, "tasks": tasks}
    if normalized_action == "queue":
        item = TASK_SCHEDULER.enqueue(task_type_key, scheme, result)
        tasks = build_task_list()
        task = find_task_in_list(tasks, item)
        return {"ok": True, "task": task, "tasks": tasks}
    if task_type_key == "optimization":
        TASK_SCHEDULER.remove(task_type_key, scheme, result)
        state = OPTIMIZATION_RUNTIME.apply(normalized_action, scheme=scheme)
        task = task_from_runtime_state("optimization", state, scheme=state.get("scheme") or scheme, result=OPTIMIZATION_RESULT_WORKBOOK_NAME)
        tasks = build_task_list()
        return {"ok": True, "task": task_from_list_or_default(tasks, task), "tasks": tasks}
    if task_type_key == "evaluation":
        TASK_SCHEDULER.remove(task_type_key, scheme, result)
        state = EVALUATION_RUNTIME.apply(normalized_action, scheme=scheme, filename=result)
        task = task_from_runtime_state(
            "evaluation",
            state,
            scheme=state.get("scheme") or scheme,
            result=state.get("result_filename") or result,
        )
        tasks = build_task_list()
        return {"ok": True, "task": task_from_list_or_default(tasks, task), "tasks": tasks}
    raise ValueError("任务类型必须为规划计算或方案评估")


def normalize_task_action(action: str) -> str:
    text = str(action or "").strip().lower()
    if text in {"start", "start_now", "immediate", "run", "立刻启动"}:
        return "start"
    if text in {"queue", "enqueue", "排队", "加入排队"}:
        return "queue"
    if text in {"cancel_queue", "dequeue", "remove_queue", "取消排队", "移出队列", "退出队列"}:
        return "cancel_queue"
    if text in {"stop", "停止", "停止计算"}:
        return "stop"
    return text


def find_task_in_list(tasks: list[dict], item: dict, queued: bool = True) -> dict:
    for task in tasks:
        if (
            task.get("task_type_key") == item.get("task_type_key")
            and task.get("scheme") == item.get("scheme")
            and (task.get("result") or "") == (item.get("result") or "")
        ):
            return task
    return task_from_runtime_state(
        item.get("task_type_key", ""),
        default_task_runtime_state(item.get("scheme", ""), item.get("result", "")),
        scheme=item.get("scheme", ""),
        result=item.get("result", ""),
        queued=queued,
        queue_position=TASK_SCHEDULER.queue_position(item.get("task_type_key", ""), item.get("scheme", ""), item.get("result", "")),
    )


def task_from_list_or_default(tasks: list[dict], fallback: dict) -> dict:
    item = {"task_type_key": fallback.get("task_type_key"), "scheme": fallback.get("scheme"), "result": fallback.get("result")}
    for task in tasks:
        if same_task_item(item, task):
            return task
    return fallback


def task_control_state_for_item(task_type_key: str, scheme: str, result: str = "", state: dict | None = None) -> dict:
    """Return the task scheduler view used by business pages and the task page."""
    item = normalized_task_item(task_type_key, scheme, result)
    queued = TASK_SCHEDULER.is_queued(item["task_type_key"], item["scheme"], item["result"])
    queue_position = TASK_SCHEDULER.queue_position(item["task_type_key"], item["scheme"], item["result"])
    task = task_from_runtime_state(
        item["task_type_key"],
        state or default_task_runtime_state(item["scheme"], item["result"]),
        scheme=item["scheme"],
        result=item["result"],
        queued=queued,
        queue_position=queue_position,
    )
    if queued:
        task["can_queue"] = False
    if item["task_type_key"] == "evaluation":
        task["can_start"] = task["can_start"] and bool(item["result"]) and item["result"] != OPTIMIZATION_RESULT_WORKBOOK_NAME
        task["can_queue"] = task["can_queue"] and bool(item["result"]) and item["result"] != OPTIMIZATION_RESULT_WORKBOOK_NAME
    return task


def append_task_control_state(payload: dict, task_type_key: str, scheme: str, result: str = "") -> dict:
    task = task_control_state_for_item(task_type_key, scheme, result, payload)
    payload.update(
        {
            "task_status": task["status"],
            "task_runtime_status": task["runtime_status"],
            "task_type_key": task["task_type_key"],
            "task_key": task["task_key"],
            "task_result": task["result"],
            "queued": task["queued"],
            "queue_position": task["queue_position"],
            "can_start_task": task["can_start"],
            "can_queue_task": task["can_queue"],
            "can_stop_task": task["can_stop"],
            "can_cancel_queue_task": bool(task["queued"]),
        }
    )
    replace_metric_value(payload, "当前状态", task["status"])
    return payload


def replace_metric_value(payload: dict, label: str, value: object, unit: str = "") -> None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return
    for metric in metrics:
        if isinstance(metric, dict) and metric.get("label") == label:
            metric["value"] = value
            metric["unit"] = unit
            return
    metrics.insert(0, {"label": label, "value": value, "unit": unit})


def normalize_task_type_key(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"optimization", "opt", "规划计算", "规划求解"}:
        return "optimization"
    if text in {"evaluation", "eval", "方案评估"}:
        return "evaluation"
    return ""


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
TASK_SCHEDULER = TaskScheduler()
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


def _no_store_headers(*, vary_cookie: bool = False) -> dict[str, str]:
    headers = {
        "Cache-Control": NO_STORE_CACHE_CONTROL,
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if vary_cookie:
        headers["Vary"] = "Cookie"
    return headers


def _static_headers(path: Path, *, authenticated_html: bool = False) -> dict[str, str]:
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if path.suffix.lower() in STATIC_NO_STORE_SUFFIXES:
        headers = {"Content-Type": content_type}
        headers.update(_no_store_headers(vary_cookie=authenticated_html or path.suffix.lower() == ".html"))
        return headers
    return {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=3600",
    }


def _read_json_body(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("请求体不是合法 JSON") from exc


def truthy_json_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


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


class LoadCurveTemplateExistsError(FileExistsError):
    """Raised when saving a load-curve template would overwrite an existing template."""


def geocode_place_name(place: str) -> dict:
    query_text = str(place or "").strip()
    if not query_text:
        raise ValueError("地名不能为空")
    errors: list[str] = []
    for candidate in geocode_query_candidates(query_text):
        providers = geocode_provider_order(candidate)
        for provider in providers:
            try:
                result = provider(candidate)
                if candidate != query_text:
                    result["place"] = query_text
                    result["display_name"] = f"{query_text} / {result.get('display_name') or candidate}"
                return result
            except GeocodingError as exc:
                errors.append(str(exc))
    raise GeocodingError("；".join(errors) or "未找到该地名对应的经纬度坐标")


def geocode_query_candidates(place: str) -> list[str]:
    """Return the original query plus an English alias for common Chinese place names."""
    query_text = str(place or "").strip()
    normalized = re.sub(r"\s+", "", query_text.lower())
    alias = CHINESE_PLACE_ALIASES.get(normalized)
    candidates = [query_text]
    if alias and alias not in candidates:
        candidates.append(alias)
    return candidates


def geocode_provider_order(place: str):
    """Prefer Amap for Chinese place names, and global providers for foreign names."""
    global_providers = [geocode_with_open_meteo, geocode_with_photon, geocode_with_nominatim]
    if not AMAP_WEB_SERVICE_KEY:
        return global_providers
    if should_prefer_global_geocoder(place):
        return [*global_providers, geocode_with_amap]
    return [geocode_with_amap, *global_providers]


def should_prefer_global_geocoder(place: str) -> bool:
    """Amap geocoding can match English names to domestic POIs, so route them globally first."""
    text = str(place or "").strip()
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", text))
    has_non_cjk_letter = any(character.isalpha() and not ("\u3400" <= character <= "\u9fff") for character in text)
    return has_non_cjk_letter and not has_cjk


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


def geocode_with_photon(place: str) -> dict:
    query = urlencode({"q": place, "limit": 1, "lang": "en"})
    url = f"{PHOTON_GEOCODING_URL}?{query}"
    try:
        with urlopen_with_user_agent(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise GeocodingError(f"Photon 地名解析接口返回错误: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise GeocodingError(f"Photon 地名解析接口连接失败: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GeocodingError("Photon 地名解析接口返回内容不是合法 JSON") from exc
    features = data.get("features", []) if isinstance(data, dict) else []
    if not features:
        raise GeocodingError("Photon 未找到该地名对应的经纬度坐标")
    first = features[0]
    coordinates = first.get("geometry", {}).get("coordinates", [])
    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (IndexError, TypeError, ValueError) as exc:
        raise GeocodingError("Photon 地名解析结果缺少有效经纬度") from exc
    properties = first.get("properties", {})
    display_parts = [
        properties.get("name"),
        properties.get("city"),
        properties.get("state"),
        properties.get("country"),
    ]
    display_name = "，".join(str(part) for part in display_parts if part)
    return {
        "place": place,
        "display_name": display_name or place,
        "latitude": latitude,
        "longitude": longitude,
        "source": "OpenStreetMap Photon API",
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
    if not raw_rows:
        raise ValueError("导入失败，文件没有可用数据行")
    parsed_by_hour: dict[int, dict] = {}
    source_hour_count = min(len(raw_rows), TIME_SERIES_IMPORT_ROW_COUNT)
    for row_index, raw_row in enumerate(raw_rows[:TIME_SERIES_IMPORT_ROW_COUNT], start=1):
        target_hour = imported_hour_index(raw_row, column_map.get("datetime"), row_index)
        if target_hour < 1 or target_hour > TIME_SERIES_IMPORT_ROW_COUNT or target_hour in parsed_by_hour:
            target_hour = next_available_time_series_hour(parsed_by_hour, row_index)
        item = {"hour_index": target_hour, "datetime": imported_datetime(raw_row, column_map.get("datetime"), target_hour)}
        for key in TIME_SERIES_IMPORT_REQUIRED_COLUMNS:
            item[key] = imported_numeric_value_or_none(raw_row.get(column_map[key]))
        parsed_by_hour[target_hour] = item
    repaired_numeric_count = repair_imported_numeric_values(parsed_by_hour)
    imported_rows = fill_imported_time_series_hours(parsed_by_hour)
    missing_count = sum(1 for item in imported_rows if item.get("_filled"))
    for item in imported_rows:
        item.pop("_filled", None)
    message = f"已从{filename}导入8760行时序数据"
    if len(raw_rows) > TIME_SERIES_IMPORT_ROW_COUNT:
        message += f"，文件共有{len(raw_rows)}行，已使用前8760行"
    elif source_hour_count < TIME_SERIES_IMPORT_ROW_COUNT:
        message += f"，文件共有{source_hour_count}行，已按最后一行自动补齐{TIME_SERIES_IMPORT_ROW_COUNT - source_hour_count}行"
    if missing_count:
        message += f"，已补齐{missing_count}个缺失时点"
    if repaired_numeric_count:
        message += f"，已修复{repaired_numeric_count}个无效数值"
    return {"time_series": imported_rows, "time_series_count": len(imported_rows), "message": message}


def import_load_curve_file(filename: str, content: bytes, minimum: object, maximum: object, average: object, raw: object = False) -> dict:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        headers, rows = read_time_series_csv(content)
    elif suffix == ".xlsx":
        headers, rows = read_time_series_xlsx(content)
    else:
        raise ValueError("导入文件仅支持 .csv 或 .xlsx 格式")
    return normalize_imported_load_curve(headers, rows, filename, minimum, maximum, average, raw)


def normalize_imported_load_curve(
    headers: list[str],
    raw_rows: list[dict[str, object]],
    filename: str,
    minimum: object,
    maximum: object,
    average: object,
    raw: object = False,
) -> dict:
    if not raw_rows:
        raise ValueError("导入失败，文件没有可用数据行")
    column_map = match_load_curve_import_columns(headers)
    values, repaired_numeric_count, missing_count, duplicate_count = normalized_imported_load_values(raw_rows, column_map)
    if truthy_json_value(raw):
        scaled_values = [round_load_value(float(value)) for value in values]
    else:
        min_value, max_value, avg_value = validate_load_curve_targets(minimum, maximum, average)
        scaled_values = scale_load_values_to_targets(values, min_value, max_value, avg_value)
    rows = [{"hour_index": index + 1, "load": value} for index, value in enumerate(scaled_values)]
    message = f"已从{filename}导入8760点负荷{'原始' if truthy_json_value(raw) else ''}曲线"
    if len(raw_rows) != TIME_SERIES_IMPORT_ROW_COUNT:
        message += f"，文件共有{len(raw_rows)}行，已自适应扩展到8760点"
    if missing_count:
        message += f"，已按相邻点自动补齐{missing_count}个缺失时点"
    if duplicate_count:
        message += f"，已合并{duplicate_count}个重复小时数据"
    if repaired_numeric_count:
        message += f"，已修复{repaired_numeric_count}个无效数值"
    return {
        "source": "file",
        "load_curve": rows,
        "load_curve_count": len(rows),
        "statistics": {
            "max": round_load_value(max(scaled_values)),
            "min": round_load_value(min(scaled_values)),
            "average": round_load_value(sum(scaled_values) / len(scaled_values)),
        },
        "message": message,
    }


def match_load_curve_import_columns(headers: list[str]) -> dict[str, str]:
    normalized_headers = [(normalize_import_header(header), header) for header in headers if str(header or "").strip()]
    load_aliases = TIME_SERIES_IMPORT_REQUIRED_COLUMNS["load"][1]
    load_column = match_time_series_header(normalized_headers, load_aliases)
    if not load_column:
        raise ValueError("导入失败，找不到对应的列：负荷")
    column_map = {"load": load_column}
    matched_time = match_time_series_header(normalized_headers, TIME_SERIES_IMPORT_OPTIONAL_COLUMNS["datetime"])
    if matched_time:
        column_map["datetime"] = matched_time
    return column_map


def normalized_imported_load_values(raw_rows: list[dict[str, object]], column_map: dict[str, str]) -> tuple[list[float | int], int, int, int]:
    load_column = column_map["load"]
    time_column = column_map.get("datetime")
    raw_values = [imported_numeric_value_or_none(row.get(load_column)) for row in raw_rows]
    grouped_by_hour: dict[int, list[float | int | None]] = {}
    if time_column:
        for raw_row, value in zip(raw_rows, raw_values):
            target_hour = imported_load_curve_hour_index(raw_row, time_column)
            if target_hour is None or target_hour < 1 or target_hour > TIME_SERIES_IMPORT_ROW_COUNT:
                continue
            grouped_by_hour.setdefault(target_hour, []).append(value)
    if grouped_by_hour:
        parsed_by_hour = {}
        duplicate_count = 0
        for hour, hour_values in grouped_by_hour.items():
            duplicate_count += max(0, len(hour_values) - 1)
            valid_values = [float(value) for value in hour_values if value is not None]
            parsed_by_hour[hour] = {
                "hour_index": hour,
                "datetime": f"H{hour:04d}",
                "load": sum(valid_values) / len(valid_values) if valid_values else None,
            }
        repaired_numeric_count = repair_imported_load_values(parsed_by_hour)
        imported_rows = fill_imported_load_curve_hours(parsed_by_hour)
        missing_count = sum(1 for item in imported_rows if item.get("_filled"))
        source_values = [row["load"] for row in imported_rows[: max(grouped_by_hour)]]
        return resample_load_values(source_values, TIME_SERIES_IMPORT_ROW_COUNT), repaired_numeric_count, missing_count, duplicate_count
    repaired_values, repaired_numeric_count = repair_load_value_sequence(raw_values)
    return resample_load_values(repaired_values, TIME_SERIES_IMPORT_ROW_COUNT), repaired_numeric_count, 0, 0


def imported_load_curve_hour_index(raw_row: dict[str, object], column: str) -> int | None:
    value = raw_row.get(column)
    if value in ("", None):
        return None
    if isinstance(value, datetime):
        return (value.timetuple().tm_yday - 1) * 24 + value.hour + 1
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    hour_match = re.fullmatch(r"[hH]\s*0*(\d{1,4})", text)
    if hour_match:
        return int(hour_match.group(1))
    numeric_match = re.fullmatch(r"0*(\d{1,4})(?:\.0+)?", text)
    if numeric_match:
        return int(numeric_match.group(1))
    datetime_match = re.search(r"\b(\d{1,2})[:：](\d{1,2})(?::\d{1,2})?\b", text)
    date_match = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if datetime_match and date_match:
        try:
            parsed = datetime(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
                int(datetime_match.group(1)),
            )
            return (parsed.timetuple().tm_yday - 1) * 24 + parsed.hour + 1
        except ValueError:
            return None
    return None


def repair_imported_load_values(parsed_by_hour: dict[int, dict]) -> int:
    hours = sorted(parsed_by_hour)
    valid_hours = [hour for hour in hours if parsed_by_hour[hour].get("load") is not None]
    if not valid_hours:
        raise ValueError("导入失败，负荷没有任何有效数值，无法用相邻点修复")
    repaired_count = 0
    previous_valid_hour = None
    next_valid_index = 0
    for hour in hours:
        if parsed_by_hour[hour].get("load") is not None:
            previous_valid_hour = hour
            if next_valid_index < len(valid_hours) and valid_hours[next_valid_index] == hour:
                next_valid_index += 1
            continue
        if previous_valid_hour is not None:
            source_hour = previous_valid_hour
        else:
            while next_valid_index < len(valid_hours) and valid_hours[next_valid_index] < hour:
                next_valid_index += 1
            source_hour = valid_hours[next_valid_index]
        parsed_by_hour[hour]["load"] = parsed_by_hour[source_hour]["load"]
        repaired_count += 1
    return repaired_count


def fill_imported_load_curve_hours(parsed_by_hour: dict[int, dict]) -> list[dict]:
    first_row = parsed_by_hour[min(parsed_by_hour)]
    previous = None
    imported_rows = []
    for hour in range(1, TIME_SERIES_IMPORT_ROW_COUNT + 1):
        if hour in parsed_by_hour:
            current = dict(parsed_by_hour[hour])
            current["hour_index"] = hour
            previous = current
            imported_rows.append(current)
            continue
        base = previous or first_row
        filled = {"hour_index": hour, "datetime": f"H{hour:04d}", "load": base["load"], "_filled": True}
        previous = filled
        imported_rows.append(filled)
    return imported_rows


def repair_load_value_sequence(values: list[float | int | None]) -> tuple[list[float | int], int]:
    valid_indexes = [index for index, value in enumerate(values) if value is not None]
    if not valid_indexes:
        raise ValueError("导入失败，负荷没有任何有效数值，无法用相邻点修复")
    repaired = list(values)
    repaired_count = 0
    previous_valid_index = None
    next_valid_index = 0
    for index, value in enumerate(repaired):
        if value is not None:
            previous_valid_index = index
            if next_valid_index < len(valid_indexes) and valid_indexes[next_valid_index] == index:
                next_valid_index += 1
            continue
        if previous_valid_index is not None:
            source_index = previous_valid_index
        else:
            source_index = valid_indexes[next_valid_index]
        repaired[index] = repaired[source_index]
        repaired_count += 1
    return [value for value in repaired if value is not None], repaired_count


def resample_load_values(values: list[float | int], target_count: int) -> list[float]:
    if len(values) == target_count:
        return [float(value) for value in values]
    if len(values) == 1:
        return [float(values[0]) for _ in range(target_count)]
    source_last = len(values) - 1
    target_last = target_count - 1
    resampled = []
    for index in range(target_count):
        source_position = (index / target_last) * source_last
        left_index = int(math.floor(source_position))
        right_index = min(source_last, left_index + 1)
        ratio = source_position - left_index
        left_value = float(values[left_index])
        right_value = float(values[right_index])
        resampled.append(left_value + (right_value - left_value) * ratio)
    return resampled


def scale_load_values_to_targets(values: list[float | int], min_value: float, max_value: float, avg_value: float) -> list[float | int]:
    if max_value == min_value:
        return [round_load_value(min_value) for _ in range(TIME_SERIES_IMPORT_ROW_COUNT)]
    raw_min = min(float(value) for value in values)
    raw_max = max(float(value) for value in values)
    raw_span = raw_max - raw_min
    if raw_span <= 0:
        raise ValueError("导入负荷曲线没有变化，无法按指定最大值和最小值缩放")
    target_mean = (avg_value - min_value) / (max_value - min_value)
    shape = [(float(value) - raw_min) / raw_span for value in values]
    adjusted_shape = adjust_shape_mean(shape, target_mean)
    return [round_load_value(min_value + (max_value - min_value) * value) for value in adjusted_shape]


def match_time_series_import_columns(headers: list[str]) -> dict[str, str]:
    normalized_headers = [(normalize_import_header(header), header) for header in headers if str(header or "").strip()]
    column_map: dict[str, str] = {}
    missing = []
    for key, (display_name, aliases) in TIME_SERIES_IMPORT_REQUIRED_COLUMNS.items():
        matched = match_time_series_header(normalized_headers, aliases)
        if matched:
            column_map[key] = matched
        else:
            missing.append(display_name)
    for key, aliases in TIME_SERIES_IMPORT_OPTIONAL_COLUMNS.items():
        matched = match_time_series_header(normalized_headers, aliases)
        if matched:
            column_map[key] = matched
    if missing:
        raise ValueError(f"导入失败，找不到对应的列：{', '.join(missing)}")
    return column_map


def match_time_series_header(normalized_headers: list[tuple[str, str]], aliases: list[str]) -> str:
    normalized_aliases = [normalize_import_header(alias) for alias in aliases]
    for alias in normalized_aliases:
        for header_norm, header in normalized_headers:
            if header_norm == alias:
                return header
    for alias in normalized_aliases:
        if len(alias) < 2:
            continue
        for header_norm, header in normalized_headers:
            if alias in header_norm or header_norm in alias:
                return header
    return ""


def normalize_import_header(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-^（）()［\]\[\]/\\:：,，。.%％]+", "", text)


def imported_hour_index(raw_row: dict[str, object], column: str | None, fallback_index: int) -> int:
    if not column:
        return fallback_index
    value = raw_row.get(column)
    if value in ("", None):
        return fallback_index
    if isinstance(value, datetime):
        day_of_year = value.timetuple().tm_yday
        return (day_of_year - 1) * 24 + value.hour + 1
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return int(value)
    text = str(value).strip()
    if not text:
        return fallback_index
    hour_match = re.fullmatch(r"[hH]\s*0*(\d{1,4})", text)
    if hour_match:
        return int(hour_match.group(1))
    numeric_match = re.fullmatch(r"0*(\d{1,4})(?:\.0+)?", text)
    if numeric_match:
        return int(numeric_match.group(1))
    datetime_match = re.search(r"\b(\d{1,2})[:：](\d{1,2})(?::\d{1,2})?\b", text)
    date_match = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if datetime_match and date_match:
        try:
            parsed = datetime(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
                int(datetime_match.group(1)),
            )
            return (parsed.timetuple().tm_yday - 1) * 24 + parsed.hour + 1
        except ValueError:
            return fallback_index
    return fallback_index


def next_available_time_series_hour(parsed_by_hour: dict[int, dict], fallback_index: int) -> int:
    hour = max(1, min(TIME_SERIES_IMPORT_ROW_COUNT, fallback_index))
    while hour in parsed_by_hour and hour <= TIME_SERIES_IMPORT_ROW_COUNT:
        hour += 1
    if hour <= TIME_SERIES_IMPORT_ROW_COUNT:
        return hour
    for candidate in range(1, TIME_SERIES_IMPORT_ROW_COUNT + 1):
        if candidate not in parsed_by_hour:
            return candidate
    return TIME_SERIES_IMPORT_ROW_COUNT


def fill_imported_time_series_hours(parsed_by_hour: dict[int, dict]) -> list[dict]:
    first_row = parsed_by_hour[min(parsed_by_hour)]
    previous = None
    imported_rows = []
    for hour in range(1, TIME_SERIES_IMPORT_ROW_COUNT + 1):
        if hour in parsed_by_hour:
            current = dict(parsed_by_hour[hour])
            current["hour_index"] = hour
            current["datetime"] = imported_datetime_for_output(current.get("datetime"), hour)
            previous = current
            imported_rows.append(current)
            continue
        base = previous or first_row
        filled = {key: base[key] for key in TIME_SERIES_IMPORT_REQUIRED_COLUMNS}
        filled.update({"hour_index": hour, "datetime": f"H{hour:04d}", "_filled": True})
        previous = filled
        imported_rows.append(filled)
    return imported_rows


def imported_datetime_for_output(value: object, index: int) -> str:
    text = str(value or "").strip()
    return text or f"H{index:04d}"


def imported_datetime(raw_row: dict[str, object], column: str | None, index: int) -> str:
    if column:
        value = raw_row.get(column)
        if value not in ("", None):
            if isinstance(value, datetime):
                return value.isoformat(sep=" ", timespec="minutes")
            return str(value)
    return f"H{index:04d}"


def imported_numeric_value_or_none(value: object) -> float | int | None:
    if value in ("", None) or not str(value).strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def repair_imported_numeric_values(parsed_by_hour: dict[int, dict]) -> int:
    hours = sorted(parsed_by_hour)
    repaired_count = 0
    for key, (label, _) in TIME_SERIES_IMPORT_REQUIRED_COLUMNS.items():
        valid_hours = [hour for hour in hours if parsed_by_hour[hour].get(key) is not None]
        if not valid_hours:
            raise ValueError(f"导入失败，{label}没有任何有效数值，无法用相邻点修复")
        previous_valid_hour = None
        next_valid_index = 0
        for hour in hours:
            if parsed_by_hour[hour].get(key) is not None:
                previous_valid_hour = hour
                if next_valid_index < len(valid_hours) and valid_hours[next_valid_index] == hour:
                    next_valid_index += 1
                continue
            if previous_valid_hour is not None:
                source_hour = previous_valid_hour
            else:
                while next_valid_index < len(valid_hours) and valid_hours[next_valid_index] < hour:
                    next_valid_index += 1
                source_hour = valid_hours[next_valid_index]
            parsed_by_hour[hour][key] = parsed_by_hour[source_hour][key]
            repaired_count += 1
    return repaired_count


def generate_load_curve(mode: str, minimum: object, maximum: object, average: object, source_load_curve: object = None) -> dict:
    mode_key = str(mode or "random").strip() or "random"
    min_value, max_value, avg_value = validate_load_curve_targets(minimum, maximum, average)
    if max_value == min_value:
        values = [round_load_value(min_value) for _ in range(TIME_SERIES_IMPORT_ROW_COUNT)]
    else:
        shape = normalized_source_load_shape(source_load_curve) if mode_key == "file" else normalized_load_shape(mode_key)
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


def list_load_curve_templates() -> dict:
    templates = read_load_curve_templates()
    return {"templates": load_curve_template_summaries(templates)}


def save_load_curve_template(name: str, rows: object, overwrite: object = False) -> dict:
    clean_name = planning_store.sanitize_scheme_name(str(name or ""))
    if clean_name in {"", ".", ".."} or planning_store.INVALID_NAME_RE.search(clean_name) or ".." in clean_name:
        raise ValueError("模板名称不能为空，且不能包含路径或非法字符")
    values = normalize_load_curve_template_values(rows)
    templates = read_load_curve_templates()
    exists = any(template.get("name") == clean_name for template in templates)
    if exists and not truthy_json_value(overwrite):
        raise LoadCurveTemplateExistsError(f"模板名称已存在：{clean_name}")
    next_template = {
        "name": clean_name,
        "load_curve": values,
        "load_curve_count": len(values),
        "updated_at": _now_iso(),
    }
    next_templates = [template for template in templates if template.get("name") != clean_name]
    next_templates.append(next_template)
    next_templates.sort(key=lambda item: item["name"])
    write_load_curve_templates(next_templates)
    return {
        "template": load_curve_template_summary(next_template),
        "templates": load_curve_template_summaries(next_templates),
        "message": f"{'已覆盖' if exists else '已保存'}负荷模板：{clean_name}",
    }


def read_load_curve_templates() -> list[dict]:
    if not LOAD_CURVE_TEMPLATE_PATH.exists():
        return []
    try:
        with LOAD_CURVE_TEMPLATE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = [header for header in (reader.fieldnames or []) if str(header or "").strip()]
            template_names = [header for header in headers if header != "hour_index"]
            columns = {name: [] for name in template_names}
            for row in reader:
                for name in template_names:
                    columns[name].append(row.get(name, ""))
    except OSError as exc:
        raise ValueError(f"负荷模板文件读取失败：{exc}") from exc
    normalized = []
    for name, values in columns.items():
        clean_name = planning_store.sanitize_scheme_name(str(name))
        try:
            normalized_values = normalize_load_curve_template_values(values)
        except ValueError:
            continue
        if clean_name:
            normalized.append(
                {
                    "name": clean_name,
                    "load_curve": normalized_values,
                    "load_curve_count": len(normalized_values),
                    "updated_at": "",
                }
            )
    normalized.sort(key=lambda item: item["name"])
    return normalized


def write_load_curve_templates(templates: list[dict]) -> None:
    LOAD_CURVE_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = LOAD_CURVE_TEMPLATE_PATH.with_name(f".{LOAD_CURVE_TEMPLATE_PATH.name}.tmp")
    headers = ["hour_index", *[template["name"] for template in templates]]
    try:
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for index in range(TIME_SERIES_IMPORT_ROW_COUNT):
                row = {"hour_index": index + 1}
                for template in templates:
                    row[template["name"]] = template["load_curve"][index]
                writer.writerow(row)
        file_ops.replace_file_with_retry(tmp_path, LOAD_CURVE_TEMPLATE_PATH, "负荷模板文件")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def normalize_load_curve_template_values(rows: object) -> list[float | int]:
    if not isinstance(rows, list) or len(rows) != TIME_SERIES_IMPORT_ROW_COUNT:
        raise ValueError(f"负荷模板必须包含{TIME_SERIES_IMPORT_ROW_COUNT}点曲线")
    values = []
    for index, row in enumerate(rows, start=1):
        raw_value = row.get("load") if isinstance(row, dict) else row
        value = imported_numeric_value_or_none(raw_value)
        if value is None:
            raise ValueError(f"负荷模板第{index}点不是有效数值")
        values.append(round_load_value(value))
    return values


def load_curve_template_summaries(templates: list[dict]) -> list[dict]:
    return [load_curve_template_summary(template) for template in templates]


def load_curve_template_summary(template: dict) -> dict:
    values = template.get("load_curve") or []
    return {
        "name": template.get("name", ""),
        "load_curve_count": int(template.get("load_curve_count") or TIME_SERIES_IMPORT_ROW_COUNT),
        "load_curve": [{"hour_index": index + 1, "load": round_load_value(value)} for index, value in enumerate(values)],
        "updated_at": template.get("updated_at", ""),
    }


def load_curve_template_shape(mode: str) -> list[float]:
    template_name = mode.split(":", 1)[1].strip() if ":" in mode else ""
    if not template_name:
        raise ValueError("负荷模板名称不能为空")
    clean_name = planning_store.sanitize_scheme_name(template_name)
    for template in read_load_curve_templates():
        if template.get("name") == clean_name:
            values = template["load_curve"]
            minimum = min(float(value) for value in values)
            maximum = max(float(value) for value in values)
            span = maximum - minimum
            if span <= 0:
                return [0.5 for _ in values]
            return [(float(value) - minimum) / span for value in values]
    raise ValueError(f"负荷模板不存在：{clean_name}")


def validate_load_curve_targets(minimum: object, maximum: object, average: object) -> tuple[float, float, float]:
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
        return min_value, max_value, avg_value
    low_mean = min_value + (max_value - min_value) / TIME_SERIES_IMPORT_ROW_COUNT
    high_mean = max_value - (max_value - min_value) / TIME_SERIES_IMPORT_ROW_COUNT
    if avg_value < low_mean or avg_value > high_mean:
        raise ValueError("平均值必须介于最小值和最大值之间，并能同时满足最大/最小约束")
    return min_value, max_value, avg_value


def load_curve_number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须为数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}必须为有效数值")
    return number


def normalized_load_shape(mode: str) -> list[float]:
    if mode.startswith("template:"):
        return load_curve_template_shape(mode)
    if mode == "random":
        raw = deterministic_random_shape()
    elif mode in {"pattern1", "pattern2", "pattern3"}:
        raw = standard_load_shape(mode)
    else:
        raise ValueError("负荷生成模式必须为随机曲线、文件导入、模式1、模式2、模式3或已保存模板")
    minimum = min(raw)
    maximum = max(raw)
    span = maximum - minimum
    if span <= 0:
        return [0.5 for _ in raw]
    return [(value - minimum) / span for value in raw]


def normalized_source_load_shape(source_load_curve: object) -> list[float]:
    values = normalize_load_curve_template_values(source_load_curve)
    minimum = min(float(value) for value in values)
    maximum = max(float(value) for value in values)
    span = maximum - minimum
    if span <= 0:
        raise ValueError("文件导入原始曲线没有变化，无法按指定最大值和最小值缩放")
    return [(float(value) - minimum) / span for value in values]


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
                    payload.get("source_load_curve"),
                )
            )
        if path == "/api/planning/load-curve/import" and method == "POST":
            payload = _read_json_body(body)
            filename = str(payload.get("filename", ""))
            content_base64 = str(payload.get("content_base64", ""))
            try:
                content = base64.b64decode(content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("导入失败，文件内容无法解析") from exc
            return _json_response(
                import_load_curve_file(
                    filename,
                    content,
                    payload.get("min"),
                    payload.get("max"),
                    payload.get("average"),
                    payload.get("raw"),
                )
            )
        if path == "/api/planning/load-curve/templates" and method == "GET":
            return _json_response(list_load_curve_templates())
        if path == "/api/planning/load-curve/templates" and method == "POST":
            payload = _read_json_body(body)
            return _json_response(
                save_load_curve_template(
                    str(payload.get("name", "")),
                    payload.get("load_curve"),
                    payload.get("overwrite"),
                )
            )
        if path == "/api/planning/map-config" and method == "GET":
            providers = [
                {"key": "amap", "label": "高德地图", "enabled": bool(AMAP_WEB_SERVICE_KEY)},
                {"key": "osm", "label": "OpenStreetMap", "enabled": True},
            ]
            preferred = next((provider["key"] for provider in providers if provider["enabled"]), "manual")
            return _json_response(
                {
                    "amap_key": AMAP_WEB_SERVICE_KEY,
                    "osm_key": "",
                    "providers": providers,
                    "preferred_provider": preferred,
                }
            )
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
                PLANNING_STORE.copy_scheme(
                    str(payload.get("source", "")),
                    str(payload.get("target", "")),
                    overwrite=truthy_json_value(payload.get("overwrite")),
                )
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
    except PermissionError as exc:
        return _json_response({"error": "file_locked", "message": str(exc)}, HTTPStatus.CONFLICT)
    except LoadCurveTemplateExistsError as exc:
        return _json_response({"error": "exists", "message": str(exc)}, HTTPStatus.CONFLICT)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
    return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)


def handle_api_path(path: str, query: str = "") -> tuple[int, dict[str, str], bytes]:
    parsed_api_path = urlparse(path)
    if parsed_api_path.query and not query:
        query = parsed_api_path.query
        path = parsed_api_path.path
    query_params = parse_qs(query)
    if path == "/api/tasks":
        return _json_response({"tasks": build_task_list()})
    if path.startswith("/api/planning/"):
        return handle_planning_api_path(path, "GET", b"")
    if path.startswith("/api/comparison/"):
        return handle_comparison_data_api_path(path, query)
    if path == "/api/evaluation/status":
        scheme = query_params.get("scheme", [""])[0]
        filename = query_params.get("filename", [""])[0]
        light = truthy_json_value(query_params.get("light", ["0"])[0])
        include_hourly_curves = not light
        return _json_response(EVALUATION_RUNTIME.snapshot(scheme=scheme, filename=filename, include_hourly_curves=include_hourly_curves))
    if path.startswith("/api/evaluation/"):
        return handle_evaluation_results_api_path(path, "GET", b"", query)
    if path == "/api/optimization/status":
        scheme = query_params.get("scheme", [""])[0]
        light = truthy_json_value(query_params.get("light", ["0"])[0])
        include_hourly_curves = not light
        return _json_response(OPTIMIZATION_RUNTIME.snapshot(scheme=scheme, include_hourly_curves=include_hourly_curves))
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
    if path == "/api/tasks/control":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            action = str(payload.get("action", ""))
            task_type = str(payload.get("task_type") or payload.get("task_type_key") or "")
            scheme = str(payload.get("scheme", ""))
            result = str(payload.get("result") or payload.get("filename") or "")
            response = build_task_control_response(action, task_type, scheme, result)
        except OptimizationStateError as exc:
            return _json_response({"error": exc.code, "message": str(exc)}, HTTPStatus.CONFLICT)
        except FileNotFoundError as exc:
            return _json_response({"error": "not_found", "message": str(exc)}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            return _json_response({"error": "bad_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        return _json_response(response)
    return _json_response({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)


def _unauthorized_response() -> tuple[int, dict[str, str], bytes]:
    return _json_response({"error": "unauthorized", "message": "请先登录"}, HTTPStatus.UNAUTHORIZED)


def _redirect_response(location: str) -> tuple[int, dict[str, str], bytes]:
    headers = {
        "Location": location,
        "Content-Type": "text/plain; charset=utf-8",
    }
    headers.update(_no_store_headers(vary_cookie=True))
    return HTTPStatus.FOUND, headers, b""


def safe_api_call(handler) -> tuple[int, dict[str, str], bytes]:
    try:
        return handler()
    except Exception as exc:
        traceback.print_exc()
        return _json_response(
            {"error": "internal_error", "message": f"后台处理失败: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


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
                status, headers, body = safe_api_call(lambda: handle_auth_api_path(parsed.path, "GET", b"", token))
                self._send(status, headers, body)
                return
            if parsed.path.startswith("/api/users"):
                status, headers, body = safe_api_call(lambda: handle_users_api_path(parsed.path, "GET", b"", current_user))
                self._send(status, headers, body)
                return
            if parsed.path != "/api/health" and not current_user:
                status, headers, body = _unauthorized_response()
                self._send(status, headers, body)
                return
            status, headers, body = safe_api_call(lambda: handle_api_path(parsed.path, parsed.query))
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

        headers = _static_headers(path, authenticated_html=path.suffix == ".html")
        self._send(HTTPStatus.OK, headers, path.read_bytes())

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        if parsed.path.startswith("/api/"):
            token = _session_token_from_cookie(self.headers.get("Cookie"))
            current_user = USER_STORE.user_for_session(token)
            if parsed.path.startswith("/api/auth/"):
                status, headers, response_body = safe_api_call(lambda: handle_auth_api_path(parsed.path, "POST", body, token))
                self._send(status, headers, response_body)
                return
            if parsed.path.startswith("/api/users"):
                status, headers, response_body = safe_api_call(lambda: handle_users_api_path(parsed.path, "POST", body, current_user))
                self._send(status, headers, response_body)
                return
            if not current_user:
                status, headers, response_body = _unauthorized_response()
                self._send(status, headers, response_body)
                return
            if parsed.path.startswith("/api/planning/"):
                status, headers, response_body = safe_api_call(lambda: handle_planning_api_path(parsed.path, "POST", body))
                self._send(status, headers, response_body)
                return
            if parsed.path == "/api/evaluation/control":
                status, headers, response_body = safe_api_call(lambda: handle_control_path(parsed.path, body))
                self._send(status, headers, response_body)
                return
            if parsed.path.startswith("/api/evaluation/"):
                status, headers, response_body = safe_api_call(lambda: handle_evaluation_results_api_path(parsed.path, "POST", body))
                self._send(status, headers, response_body)
                return
            status, headers, response_body = safe_api_call(lambda: handle_control_path(parsed.path, body))
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
            status, headers, response_body = safe_api_call(lambda: handle_users_api_path(parsed.path, "PUT", body, current_user))
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/") and not current_user:
            status, headers, response_body = _unauthorized_response()
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/planning/"):
            status, headers, response_body = safe_api_call(lambda: handle_planning_api_path(parsed.path, "PUT", body))
            self._send(status, headers, response_body)
            return
        self._send_text(HTTPStatus.NOT_FOUND, "Not Found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        token = _session_token_from_cookie(self.headers.get("Cookie"))
        current_user = USER_STORE.user_for_session(token)
        if parsed.path.startswith("/api/users"):
            status, headers, response_body = safe_api_call(lambda: handle_users_api_path(parsed.path, "DELETE", b"", current_user))
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/") and not current_user:
            status, headers, response_body = _unauthorized_response()
            self._send(status, headers, response_body)
            return
        if parsed.path.startswith("/api/planning/"):
            status, headers, response_body = safe_api_call(lambda: handle_planning_api_path(parsed.path, "DELETE", b""))
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


