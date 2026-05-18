"""Small file-content cache for backend read paths.

The web server repeatedly parses a few relatively large files, especially
scheme workbooks and result workbooks.  This cache keys entries by absolute
path, a caller-provided variant, file size, and mtime_ns, so unchanged files
reuse parsed data while external edits are picked up automatically.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Hashable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class FileSignature:
    mtime_ns: int
    size: int


@dataclass
class CacheEntry:
    signature: FileSignature
    value: Any


_REGISTRY_LOCK = RLock()
_REGISTRY: list["FileCache"] = []


def resolved_path(path: Path | str) -> Path:
    """Resolve a path without requiring it to exist."""

    return Path(path).resolve()


def file_signature(path: Path) -> FileSignature:
    stat = path.stat()
    return FileSignature(mtime_ns=stat.st_mtime_ns, size=stat.st_size)


class FileCache:
    """Thread-safe LRU cache invalidated by filesystem metadata."""

    def __init__(self, name: str, max_entries: int = 128, copy_values: bool = True) -> None:
        self.name = name
        self.max_entries = max(1, int(max_entries))
        self.copy_values = copy_values
        self._lock = RLock()
        self._entries: OrderedDict[tuple[Path, Hashable], CacheEntry] = OrderedDict()
        with _REGISTRY_LOCK:
            _REGISTRY.append(self)

    def get(self, path: Path | str, loader: Callable[[Path], T], variant: Hashable = "default") -> T:
        resolved = resolved_path(path)
        signature = file_signature(resolved)
        key = (resolved, variant)
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry.signature == signature:
                self._entries.move_to_end(key)
                return self._copy(entry.value)

        value = loader(resolved)
        stored = self._copy(value)
        with self._lock:
            self._entries[key] = CacheEntry(signature=signature, value=stored)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return self._copy(stored)

    def invalidate_path(self, path: Path | str) -> None:
        resolved = resolved_path(path)
        with self._lock:
            for key in list(self._entries):
                if key[0] == resolved:
                    self._entries.pop(key, None)

    def invalidate_under(self, path: Path | str) -> None:
        resolved = resolved_path(path)
        with self._lock:
            for key in list(self._entries):
                cached_path = key[0]
                if cached_path == resolved or resolved in cached_path.parents:
                    self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _copy(self, value: T) -> T:
        if not self.copy_values:
            return value
        return deepcopy(value)


def invalidate_path(path: Path | str) -> None:
    with _REGISTRY_LOCK:
        caches = list(_REGISTRY)
    for cache in caches:
        cache.invalidate_path(path)


def invalidate_under(path: Path | str) -> None:
    with _REGISTRY_LOCK:
        caches = list(_REGISTRY)
    for cache in caches:
        cache.invalidate_under(path)


def clear_all() -> None:
    with _REGISTRY_LOCK:
        caches = list(_REGISTRY)
    for cache in caches:
        cache.clear()
