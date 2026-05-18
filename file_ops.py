"""Retry-aware filesystem helpers for the web backend.

Windows keeps an exclusive handle on files that are open in Excel, preview
panes, or some antivirus scans.  All backend write paths go through these
helpers so transient locks are retried and persistent locks produce a clear
message for the browser instead of a generic 500.
"""

from __future__ import annotations

import gc
import shutil
import time
from pathlib import Path
from typing import Callable, TypeVar

import file_cache


DEFAULT_ATTEMPTS = 20
DEFAULT_DELAY_SECONDS = 0.1
T = TypeVar("T")


class FileOperationLockedError(PermissionError):
    """Raised when a filesystem write operation cannot finish after retries."""


def invalidate_file_and_parent(path: Path) -> None:
    file_cache.invalidate_path(path)
    file_cache.invalidate_path(path.parent)


def retry_file_operation(
    operation: Callable[[], T],
    message: str,
    attempts: int = DEFAULT_ATTEMPTS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> T:
    """Run a file operation with short retries for Windows file locks."""

    last_error: PermissionError | OSError | None = None
    for _ in range(attempts):
        try:
            return operation()
        except (FileNotFoundError, FileExistsError):
            raise
        except OSError as exc:
            last_error = exc
            gc.collect()
            time.sleep(delay_seconds)
    raise FileOperationLockedError(message) from last_error


def replace_file_with_retry(source: Path, target: Path, label: str) -> None:
    retry_file_operation(
        lambda: source.replace(target),
        f"{label}被占用，无法保存：{target.name}。请关闭正在打开该文件的 Excel 或预览窗口后重试。",
    )
    file_cache.invalidate_path(source)
    invalidate_file_and_parent(target)


def save_workbook_with_retry(workbook, path: Path, label: str) -> None:
    retry_file_operation(
        lambda: workbook.save(path),
        f"{label}临时文件被占用，无法写入：{path.name}。请关闭正在打开的文件或预览窗口后重试。",
    )
    invalidate_file_and_parent(path)


def copy_file_with_retry(source: Path, target: Path, label: str) -> None:
    retry_file_operation(
        lambda: shutil.copy2(source, target),
        f"{label}被占用，无法复制到：{target.name}。请关闭正在打开的文件或预览窗口后重试。",
    )
    invalidate_file_and_parent(target)


def delete_file_if_exists_with_retry(path: Path, label: str) -> None:
    if path.exists():
        delete_file_with_retry(path, label)


def delete_file_with_retry(path: Path, label: str) -> None:
    retry_file_operation(
        lambda: path.unlink(),
        f"{label}被占用，无法删除：{path.name}。请关闭正在打开该文件的 Excel 或预览窗口后重试。",
    )
    invalidate_file_and_parent(path)


def replace_directory_with_retry(source: Path, target: Path, label: str) -> None:
    retry_file_operation(
        lambda: source.rename(target),
        f"{label}被占用，无法重命名：{source.name}。请关闭相关文件或资源管理器窗口后重试。",
    )
    file_cache.invalidate_under(source)
    file_cache.invalidate_under(target)


def copy_directory_with_retry(source: Path, target: Path, label: str) -> None:
    retry_file_operation(
        lambda: shutil.copytree(source, target),
        f"{label}被占用，无法复制到：{target.name}。请关闭相关文件或资源管理器窗口后重试。",
    )
    file_cache.invalidate_under(target)


def delete_directory_with_retry(path: Path, label: str) -> None:
    retry_file_operation(
        lambda: shutil.rmtree(path),
        f"{label}被占用，无法删除：{path.name}。请关闭相关文件或资源管理器窗口后重试。",
    )
    file_cache.invalidate_under(path)
