"""XLSX-backed scheme storage for grid-planning parameter maintenance."""

from __future__ import annotations

import re
import shutil
import time
import unicodedata
import zipfile
import gc
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook


WEB_ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEME_ROOT = WEB_ROOT / "planning_schemes"
WORKBOOK_NAME = "parameters.xlsx"
WORKBOOK_XML = "xl/workbook.xml"
WORKBOOK_RELS_XML = "xl/_rels/workbook.xml.rels"
MAIN_XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_XML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_XML_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

SHEET_SPECS: dict[str, tuple[str, list[str]]] = {
    "time_series": ("8760时序数据", ["hour_index", "datetime", "wind_speed", "solar_irradiance", "load", "temperature"]),
    "diesel_generators": (
        "柴发参数",
        [
            "name",
            "capacity",
            "cost",
            "power_upper",
            "power_lower",
            "fuel_rate",
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
        ],
    ),
    "wind_turbines": (
        "风机参数",
        [
            "name",
            "capacity",
            "cost",
            "cut_in_wind_speed",
            "cut_out_wind_speed",
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
        ],
    ),
    "photovoltaics": (
        "光伏参数",
        [
            "name",
            "capacity",
            "cost",
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
        ],
    ),
    "storage_pcs": (
        "储能PCS参数",
        ["name", "power_capacity", "cost", "quantity_lower", "quantity_upper", "design_life_years"],
    ),
    "storage_battery_packs": (
        "储能电池组参数",
        ["name", "battery_capacity", "cost", "quantity_lower", "quantity_upper", "design_life_years"],
    ),
    "hydrogen_electrolyzers": (
        "电制氢参数",
        [
            "name",
            "power_capacity",
            "power_lower",
            "cost",
            "electric_to_hydrogen_efficiency",
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
        ],
    ),
    "hydrogen_tanks": (
        "储氢罐参数",
        [
            "name",
            "hydrogen_tank_capacity",
            "cost",
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
        ],
    ),
    "fuel_cells": (
        "燃料电池参数",
        [
            "name",
            "power_capacity",
            "cost",
            "hydrogen_to_electric_efficiency",
            "quantity_lower",
            "quantity_upper",
            "design_life_years",
        ],
    ),
    "planning_parameters": (
        "规划参数",
        [
            "diesel_price",
            "green_power_ratio_lower",
            "optimization_time_limit_minutes",
            "initial_storage_soc_ratio",
            "initial_hydrogen_storage_ratio",
            "storage_charge_efficiency",
            "storage_discharge_efficiency",
            "storage_frequency_regulation_enabled",
            "load_disturbance_factor",
            "frequency_security_constraint_enabled",
            "frequency_security_upper",
            "frequency_security_lower",
            "post_disturbance_power_balance_enabled",
            "renewable_n_1_enabled",
            "load_disturbance_enabled",
        ],
    ),
}

DEFAULT_DEVICE_ROWS: dict[str, list[dict[str, Any]]] = {
    "diesel_generators": [
        {
            "name": "柴发1",
            "capacity": 100,
            "cost": 0,
            "power_upper": 100,
            "power_lower": 20,
            "fuel_rate": 0.26,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "wind_turbines": [
        {
            "name": "风机1",
            "capacity": 50,
            "cost": 0,
            "cut_in_wind_speed": 3,
            "cut_out_wind_speed": 25,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "photovoltaics": [
        {
            "name": "光伏1",
            "capacity": 50,
            "cost": 0,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "storage_pcs": [
        {
            "name": "储能PCS1",
            "power_capacity": 50,
            "cost": 0,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "storage_battery_packs": [
        {
            "name": "储能电池组1",
            "battery_capacity": 200,
            "cost": 0,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "hydrogen_electrolyzers": [
        {
            "name": "电制氢1",
            "power_capacity": 50,
            "power_lower": 0,
            "cost": 0,
            "electric_to_hydrogen_efficiency": 0.7,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "hydrogen_tanks": [
        {
            "name": "储氢罐1",
            "hydrogen_tank_capacity": 100,
            "cost": 0,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
    "fuel_cells": [
        {
            "name": "燃料电池1",
            "power_capacity": 50,
            "cost": 0,
            "hydrogen_to_electric_efficiency": 0.55,
            "quantity_lower": 0,
            "quantity_upper": 0,
        }
    ],
}

DEFAULT_PLANNING_PARAMETERS: dict[str, Any] = {
    "diesel_price": 0,
    "green_power_ratio_lower": 0,
    "optimization_time_limit_minutes": 60,
    "initial_storage_soc_ratio": 0.5,
    "initial_hydrogen_storage_ratio": 0.5,
    "storage_charge_efficiency": 0.95,
    "storage_discharge_efficiency": 0.95,
    "storage_frequency_regulation_enabled": False,
    "load_disturbance_factor": 0,
    "frequency_security_constraint_enabled": False,
    "frequency_security_upper": 1.5,
    "frequency_security_lower": 1.0,
    "post_disturbance_power_balance_enabled": False,
    "renewable_n_1_enabled": False,
    "load_disturbance_enabled": False,
}

FIELD_DEFAULTS: dict[str, Any] = {
    **DEFAULT_PLANNING_PARAMETERS,
    "design_life_years": 20,
}

DEVICE_FIELD_RULES: dict[str, dict[str, Any]] = {
    "quantity_lower": {"integer": True, "non_negative": True, "message": "数据上下限必须为非负整数"},
    "quantity_upper": {"integer": True, "non_negative": True, "message": "数据上下限必须为非负整数"},
    "design_life_years": {"integer": True, "positive": True, "message": "设计年限(年）必须为正整数"},
    "cost": {"non_negative": True, "message": "成本(万元/台)必须为非负浮点数"},
    "capacity": {"positive": True, "message": "功率容量(kW)必须为正实数"},
    "power_capacity": {"positive": True, "message": "功率容量(kW)必须为正实数"},
    "battery_capacity": {"positive": True, "message": "电池容量(kWh)必须为正实数"},
    "hydrogen_tank_capacity": {"positive": True, "message": "氢储容量(Nm3)必须为正实数"},
    "electric_to_hydrogen_efficiency": {"positive": True, "message": "电-氢效率(Nm3/kWh)必须为正实数"},
    "hydrogen_to_electric_efficiency": {"positive": True, "message": "氢-电效率(kWh/Nm3)必须为正实数"},
    "fuel_rate": {"positive": True, "message": "油耗率(kg/kWh)必须为正实数"},
    "power_lower": {"non_negative": True, "message": "功率下限(kW)必须为非负实数"},
    "cut_in_wind_speed": {"non_negative": True, "message": "切入风速(m/s)必须为非负实数"},
    "cut_out_wind_speed": {"non_negative": True, "message": "切出风速(m/s)必须为非负实数"},
}

INVALID_NAME_RE = re.compile(r'[<>:"/\\|?*]')


def sanitize_scheme_name(name: str) -> str:
    return "".join(
        char
        for char in str(name or "")
        if not char.isspace() and unicodedata.category(char) not in {"Cc", "Cf"}
    )


def validate_scheme_name(name: str) -> str:
    clean = sanitize_scheme_name(name)
    if clean in {"", ".", ".."} or INVALID_NAME_RE.search(clean) or ".." in clean:
        raise ValueError("方案名称不能为空，且不能包含路径或非法字符")
    return clean


def default_time_series() -> list[dict[str, Any]]:
    return [
        {
            "hour_index": hour,
            "datetime": f"H{hour:04d}",
            "wind_speed": 0,
            "solar_irradiance": 0,
            "load": 0,
            "temperature": 0,
        }
        for hour in range(1, 8761)
    ]


def default_payload(scheme: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"scheme": scheme, "time_series": default_time_series(), "validation": []}
    for key in DEFAULT_DEVICE_ROWS:
        payload[key] = [with_field_defaults(row, SHEET_SPECS[key][1]) for row in DEFAULT_DEVICE_ROWS[key]]
    payload["planning_parameters"] = [deepcopy(DEFAULT_PLANNING_PARAMETERS)]
    payload["capacity_limits"] = []
    return payload


def default_rows_for_key(key: str) -> list[dict[str, Any]]:
    if key == "time_series":
        return default_time_series()
    if key == "planning_parameters":
        return [deepcopy(DEFAULT_PLANNING_PARAMETERS)]
    return [with_field_defaults(row, SHEET_SPECS[key][1]) for row in DEFAULT_DEVICE_ROWS.get(key, [])]


def field_default(header: str, fallback: Any = "") -> Any:
    return deepcopy(FIELD_DEFAULTS.get(header, fallback))


def with_field_defaults(row: dict[str, Any], headers: list[str]) -> dict[str, Any]:
    normalized = deepcopy(row)
    for header in headers:
        if header not in normalized:
            normalized[header] = field_default(header, "")
    return normalized


def sanitize_payload_names(payload: dict[str, Any]) -> dict[str, Any]:
    for key in DEFAULT_DEVICE_ROWS:
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and "name" in row:
                row["name"] = sanitize_scheme_name(row.get("name", ""))
    return payload


@dataclass
class PlanningStore:
    root: Path = DEFAULT_SCHEME_ROOT

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def scheme_dir(self, name: str) -> Path:
        clean = validate_scheme_name(name)
        path = (self.root / clean).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("方案路径越界")
        return path

    def workbook_path(self, name: str) -> Path:
        return self.scheme_dir(name) / WORKBOOK_NAME

    def list_schemes(self) -> list[dict[str, Any]]:
        schemes: list[dict[str, Any]] = []
        for folder in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not folder.is_dir():
                continue
            workbook = folder / WORKBOOK_NAME
            schemes.append(
                {
                    "name": folder.name,
                    "has_workbook": workbook.exists(),
                    "modified_at": workbook.stat().st_mtime if workbook.exists() else None,
                }
            )
        return schemes

    def create_scheme(self, name: str) -> dict[str, Any]:
        clean = validate_scheme_name(name)
        folder = self.scheme_dir(clean)
        if folder.exists():
            raise FileExistsError(f"方案已存在: {clean}")
        folder.mkdir(parents=True)
        self.write_scheme(clean, default_payload(clean))
        return self.read_scheme(clean)

    def copy_scheme(self, source: str, target: str) -> dict[str, Any]:
        source_dir = self.scheme_dir(source)
        target_dir = self.scheme_dir(target)
        if not source_dir.exists():
            raise FileNotFoundError(f"源方案不存在: {source}")
        if target_dir.exists():
            raise FileExistsError(f"目标方案已存在: {target}")
        shutil.copytree(source_dir, target_dir)
        return self.read_scheme(target)

    def rename_scheme(self, source: str, target: str) -> dict[str, Any]:
        source_dir = self.scheme_dir(source)
        target_dir = self.scheme_dir(target)
        if not source_dir.exists():
            raise FileNotFoundError(f"源方案不存在: {source}")
        if target_dir.exists():
            raise FileExistsError(f"目标方案已存在: {target}")
        source_dir.rename(target_dir)
        return self.read_scheme(target)

    def delete_scheme(self, name: str) -> dict[str, str]:
        clean = validate_scheme_name(name)
        folder = self.scheme_dir(clean)
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"方案不存在: {clean}")
        shutil.rmtree(folder)
        return {"deleted": clean}

    def write_scheme(self, name: str, payload: dict[str, Any]) -> None:
        clean = validate_scheme_name(name)
        folder = self.scheme_dir(clean)
        folder.mkdir(parents=True, exist_ok=True)
        payload = sanitize_payload_names(deepcopy(payload))
        workbook = build_workbook(payload | {"scheme": clean})
        tmp_path = folder / f".{WORKBOOK_NAME}.tmp"
        final_path = folder / WORKBOOK_NAME
        try:
            workbook.save(tmp_path)
        finally:
            workbook.close()
        tmp_path.replace(final_path)

    def read_scheme(self, name: str) -> dict[str, Any]:
        clean = validate_scheme_name(name)
        path = self.workbook_path(clean)
        if not path.exists():
            raise FileNotFoundError(f"方案参数文件不存在: {path}")
        payload = read_workbook(path, clean)
        payload["validation"] = payload.get("validation", []) + validate_payload(payload)
        payload["time_series_loaded"] = True
        payload["time_series_count"] = len(payload.get("time_series", []))
        return payload

    def read_scheme_overview(self, name: str) -> dict[str, Any]:
        clean = validate_scheme_name(name)
        path = self.workbook_path(clean)
        if not path.exists():
            raise FileNotFoundError(f"方案参数文件不存在: {path}")
        payload = read_workbook(path, clean, include_keys=[key for key in SHEET_SPECS if key != "time_series"])
        payload["time_series_loaded"] = False
        payload["time_series_count"] = count_sheet_rows(path, SHEET_SPECS["time_series"][0])
        payload["validation"] = payload.get("validation", []) + validate_payload(payload, require_time_series=False)
        return payload

    def read_time_series(self, name: str) -> dict[str, Any]:
        clean = validate_scheme_name(name)
        path = self.workbook_path(clean)
        if not path.exists():
            raise FileNotFoundError(f"方案参数文件不存在: {path}")
        payload = read_workbook(path, clean, include_keys=["time_series"])
        payload["time_series_loaded"] = True
        payload["time_series_count"] = len(payload.get("time_series", []))
        payload["validation"] = payload.get("validation", []) + validate_payload(payload)
        return payload


def build_workbook(payload: dict[str, Any]) -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for key, (sheet_name, headers) in SHEET_SPECS.items():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(headers)
        rows = payload.get(key, default_rows_for_key(key))
        if key == "planning_parameters" and isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            sheet.append([row.get(header, field_default(header, "")) for header in headers])
    return workbook


class TimeSeriesSheetReadError(Exception):
    """Raised when only the 8760 time-series worksheet cannot be read."""


def read_workbook(path: Path, scheme: str, include_keys: list[str] | None = None) -> dict[str, Any]:
    selected_keys = set(include_keys) if include_keys is not None else set(SHEET_SPECS)
    repair_messages: list[dict[str, str]] = []
    if is_time_series_zip_member_corrupted(path):
        repair_messages.append(repair_time_series_sheet(path, "8760时序数据工作表压缩内容损坏"))
    for attempt in range(2):
        try:
            payload = read_workbook_once(path, scheme, selected_keys)
            payload["validation"] = repair_messages + payload.get("validation", [])
            return payload
        except TimeSeriesSheetReadError as exc:
            if attempt > 0:
                raise ValueError(f"参数文件损坏，8760时序数据工作表无法修复：{path}") from exc
            reason = str(exc)
            del exc
            gc.collect()
            repair_messages.append(repair_time_series_sheet(path, reason))
        except Exception as exc:
            if attempt == 0 and is_time_series_zip_member_corrupted(path):
                reason = str(exc)
                del exc
                gc.collect()
                repair_messages.append(repair_time_series_sheet(path, reason))
                continue
            raise ValueError(f"参数文件损坏或无法读取：{path}。请恢复备份或重新导入8760时序数据。原始错误：{exc}") from exc
    raise ValueError(f"参数文件损坏或无法读取：{path}")


def read_workbook_once(path: Path, scheme: str, selected_keys: set[str]) -> dict[str, Any]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    payload: dict[str, Any] = {"scheme": scheme, "validation": [], "capacity_limits": []}
    try:
        for key, (sheet_name, headers) in SHEET_SPECS.items():
            if key not in selected_keys:
                continue
            if sheet_name not in workbook.sheetnames:
                payload[key] = default_rows_for_key(key)
                if key != "planning_parameters":
                    payload["validation"].append({"level": "error", "message": f"缺少工作表: {sheet_name}"})
                continue
            sheet = workbook[sheet_name]
            try:
                header_values = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1), [])]
            except Exception as exc:
                if key == "time_series":
                    raise TimeSeriesSheetReadError(str(exc)) from exc
                raise
            has_named_header = any(value is not None for value in header_values)
            header_index = {
                str(value): index
                for index, value in enumerate(header_values)
                if value is not None and str(value) in headers
            }
            rows = []
            try:
                for values in sheet.iter_rows(min_row=2, values_only=True):
                    if values is None or all(value is None for value in values):
                        continue
                    row = {}
                    for index, header in enumerate(headers):
                        if header in header_index:
                            source_index = header_index[header]
                        elif has_named_header:
                            row[header] = field_default(header, "")
                            continue
                        else:
                            source_index = index
                        row[header] = (
                            values[source_index]
                            if source_index < len(values) and values[source_index] is not None
                            else field_default(header, "")
                        )
                    if key == "planning_parameters" and "optimization_time_limit_minutes" not in header_index:
                        legacy_index = next(
                            (
                                index
                                for index, value in enumerate(header_values)
                                if value is not None and str(value) == "optimization_time_limit_seconds"
                            ),
                            None,
                        )
                        if legacy_index is not None and legacy_index < len(values) and values[legacy_index] not in (None, ""):
                            row["optimization_time_limit_minutes"] = numeric(values[legacy_index], 3600) / 60
                    rows.append(row)
            except Exception as exc:
                if key == "time_series":
                    raise TimeSeriesSheetReadError(str(exc)) from exc
                raise
            payload[key] = (rows or default_rows_for_key(key)) if key == "planning_parameters" else rows
    finally:
        workbook.close()
    return payload


def is_time_series_zip_member_corrupted(path: Path) -> bool:
    try:
        sheet_member = time_series_sheet_member(path)
        return corrupted_zip_member(path) == sheet_member
    except Exception:
        return False


def corrupted_zip_member(path: Path) -> str | None:
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            try:
                archive.read(name)
            except Exception:
                return name
    return None


def repair_time_series_sheet(path: Path, reason: str) -> dict[str, str]:
    sheet_member = time_series_sheet_member(path)
    backup_path = backup_corrupted_workbook(path)
    replacement_xml = build_time_series_sheet_xml().encode("utf-8")
    tmp_path = path.with_name(f".{path.name}.repairing")
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            replaced = False
            for info in source.infolist():
                if info.filename == sheet_member:
                    target.writestr(info, replacement_xml)
                    replaced = True
                    continue
                target.writestr(info, source.read(info.filename))
            if not replaced:
                raise ValueError(f"未找到8760时序数据工作表: {sheet_member}")
        replace_workbook_with_retry(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return {
        "level": "warn",
        "message": (
            "检测到参数文件中的8760时序数据工作表损坏，"
            "已保留其它参数，已重建默认8760时序数据；"
            f"原文件已备份为 {backup_path.name}。原始错误：{reason}"
        ),
    }


def replace_workbook_with_retry(source: Path, target: Path, attempts: int = 20, delay_seconds: float = 0.1) -> None:
    last_error: PermissionError | None = None
    for _ in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            time.sleep(delay_seconds)
    raise PermissionError(f"参数文件被占用，无法写回修复后的工作簿：{target}") from last_error


def backup_corrupted_workbook(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}.bak")
    counter = 1
    while backup_path.exists():
        backup_path = path.with_name(f"{path.stem}.corrupt-{timestamp}-{counter}{path.suffix}.bak")
        counter += 1
    shutil.copy2(path, backup_path)
    return backup_path


def time_series_sheet_member(path: Path) -> str:
    sheet_name = SHEET_SPECS["time_series"][0]
    with zipfile.ZipFile(path) as archive:
        workbook_root = ElementTree.fromstring(archive.read(WORKBOOK_XML))
        relation_id = ""
        for sheet in workbook_root.findall(f".//{{{MAIN_XML_NS}}}sheet"):
            if sheet.attrib.get("name") == sheet_name:
                relation_id = sheet.attrib.get(f"{{{REL_XML_NS}}}id", "")
                break
        if not relation_id:
            raise ValueError(f"未找到工作表: {sheet_name}")
        rels_root = ElementTree.fromstring(archive.read(WORKBOOK_RELS_XML))
        for relationship in rels_root.findall(f".//{{{PACKAGE_REL_XML_NS}}}Relationship"):
            if relationship.attrib.get("Id") == relation_id:
                target = relationship.attrib.get("Target", "")
                if not target:
                    break
                normalized = target.lstrip("/")
                if not normalized.startswith("xl/"):
                    normalized = f"xl/{normalized}"
                return normalized.replace("\\", "/")
    raise ValueError(f"未找到工作表关系: {sheet_name}")


def build_time_series_sheet_xml() -> str:
    headers = SHEET_SPECS["time_series"][1]
    rows = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{MAIN_XML_NS}">',
        '<dimension ref="A1:F8761"/>',
        '<sheetData>',
        f'<row r="1">{"".join(inline_cell(column_name(index), 1, header) for index, header in enumerate(headers, start=1))}</row>',
    ]
    for row_index, row in enumerate(default_time_series(), start=2):
        rows.append(
            f'<row r="{row_index}">'
            f'<c r="A{row_index}" t="n"><v>{row["hour_index"]}</v></c>'
            f'{inline_cell("B", row_index, row["datetime"])}'
            f'<c r="C{row_index}" t="n"><v>{row["wind_speed"]}</v></c>'
            f'<c r="D{row_index}" t="n"><v>{row["solar_irradiance"]}</v></c>'
            f'<c r="E{row_index}" t="n"><v>{row["load"]}</v></c>'
            f'<c r="F{row_index}" t="n"><v>{row["temperature"]}</v></c>'
            "</row>"
        )
    rows.extend(["</sheetData>", "</worksheet>"])
    return "".join(rows)


def inline_cell(column: str, row: int, value: Any) -> str:
    text = (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<c r="{column}{row}" t="inlineStr"><is><t>{text}</t></is></c>'


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def count_sheet_rows(path: Path, sheet_name: str) -> int:
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            return 0
        sheet = workbook[sheet_name]
        if sheet.max_row and sheet.max_row > 1:
            return sheet.max_row - 1
        return sum(1 for _ in sheet.iter_rows(min_row=2, values_only=True))
    finally:
        workbook.close()


def is_non_negative_integer_value(value: Any) -> bool:
    if isinstance(value, bool) or value in ("", None):
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return value >= 0 and value.is_integer()
    text = str(value).strip()
    return bool(re.fullmatch(r"\d+", text))


def numeric(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and number not in (float("inf"), float("-inf")) else default


def validate_device_field_value(value: Any, rule: dict[str, Any]) -> bool:
    if rule.get("integer"):
        if not is_non_negative_integer_value(value):
            return False
        number = float(value)
    else:
        if isinstance(value, bool) or value in ("", None):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if not number == number or number in (float("inf"), float("-inf")):
            return False
    if rule.get("positive") and number <= 0:
        return False
    if rule.get("non_negative") and number < 0:
        return False
    return True


def validate_payload(payload: dict[str, Any], require_time_series: bool = True) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if require_time_series:
        time_series = payload.get("time_series", [])
        if len(time_series) != 8760:
            messages.append({"level": "error", "message": f"时序数据行数应为8760，当前为{len(time_series)}"})
        else:
            messages.append({"level": "ok", "message": "时序数据行数正确"})
    elif "time_series_count" in payload:
        messages.append({"level": "ok", "message": f"时序数据延迟加载，当前行数为{payload['time_series_count']}"})

    for key in DEFAULT_DEVICE_ROWS:
        for index, row in enumerate(payload.get(key, []), start=1):
            row_label = f"{SHEET_SPECS[key][0]}第{index}行"
            for field in SHEET_SPECS[key][1]:
                rule = DEVICE_FIELD_RULES.get(field)
                if rule and not validate_device_field_value(row.get(field, ""), rule):
                    messages.append({"level": "error", "message": f"{row_label}{rule['message']}"})
            if (
                validate_device_field_value(row.get("quantity_lower", ""), DEVICE_FIELD_RULES["quantity_lower"])
                and validate_device_field_value(row.get("quantity_upper", ""), DEVICE_FIELD_RULES["quantity_upper"])
                and float(row.get("quantity_lower")) > float(row.get("quantity_upper"))
            ):
                messages.append({"level": "error", "message": f"{SHEET_SPECS[key][0]}第{index}行数据上限不能小于数据下限"})
    messages.extend(validate_planning_parameters(payload))
    return messages


def first_planning_parameter_row(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("planning_parameters")
    if isinstance(rows, dict):
        return rows
    if isinstance(rows, list) and rows:
        return rows[0]
    return deepcopy(DEFAULT_PLANNING_PARAMETERS)


def validate_planning_parameters(payload: dict[str, Any]) -> list[dict[str, str]]:
    row = first_planning_parameter_row(payload)
    messages: list[dict[str, str]] = []

    def number_in_range(key: str, label: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
        value = row.get(key, "")
        try:
            number = float(value)
        except (TypeError, ValueError):
            messages.append({"level": "error", "message": f"{label}必须为数值"})
            return None
        if minimum is not None and number < minimum:
            messages.append({"level": "error", "message": f"{label}不能小于{minimum:g}"})
        if maximum is not None and number > maximum:
            messages.append({"level": "error", "message": f"{label}不能大于{maximum:g}"})
        return number

    number_in_range("diesel_price", "柴油价格(万元/吨)", 0)
    number_in_range("green_power_ratio_lower", "绿色电量占比下限(0.0-1.0)", 0, 1)
    time_limit = number_in_range("optimization_time_limit_minutes", "规划求解时间上限(分钟)", 10, 120)
    if time_limit is not None and not float(time_limit).is_integer():
        messages.append({"level": "error", "message": "规划求解时间上限(分钟)必须为正整数"})
    number_in_range("initial_storage_soc_ratio", "初始电储SOC(0.0-1.0)", 0, 1)
    number_in_range("initial_hydrogen_storage_ratio", "初始氢储SOC(0.0-1.0)", 0, 1)
    for key, label in (
        ("storage_charge_efficiency", "电储能充电效率(0.0-1.0)"),
        ("storage_discharge_efficiency", "电储能放电效率(0.0-1.0)"),
    ):
        efficiency = number_in_range(key, label, 0, 1)
        if efficiency is not None and efficiency <= 0:
            messages.append({"level": "error", "message": f"{label}必须大于0"})
    number_in_range("load_disturbance_factor", "负荷扰动系数(0.0-0.5)", 0, 0.5)
    frequency_upper = number_in_range("frequency_security_upper", "频率安全上限(1.0-1.5)", 1, 1.5)
    frequency_lower = number_in_range("frequency_security_lower", "频率安全下限(0.9-1.0)", 0.9, 1)
    if frequency_upper is not None and frequency_lower is not None and frequency_upper < frequency_lower:
        messages.append({"level": "error", "message": "频率安全上限不能小于频率安全下限"})
    return messages
