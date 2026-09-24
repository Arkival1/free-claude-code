"""CPU, memory, and disk use for the HUD, with no extra packages.

CPU use is measured between two calls, so the first reading after start-up is
None; the HUD polls every few seconds and fills in from the second poll on.
"""

import ctypes
import os
import shutil
import sys
import threading
from pathlib import Path

from free_claude_code.core.json_types import JsonObject

_LOCK = threading.Lock()
_LAST_CPU: list[tuple[int, int]] = []


def _cpu_times() -> tuple[int, int] | None:
    """Return (idle, total) CPU time counters, or None when unavailable."""
    if sys.platform.startswith("linux"):
        try:
            fields = Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]
        except OSError:
            return None
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, sum(values)
    if sys.platform == "win32":
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        idle, kernel, user = (
            ctypes.c_ulonglong(),
            ctypes.c_ulonglong(),
            ctypes.c_ulonglong(),
        )
        if not windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        # Kernel time already includes idle time on Windows.
        return idle.value, kernel.value + user.value
    return None


def cpu_percent() -> float | None:
    """CPU use since the previous call, as a percentage."""
    sample = _cpu_times()
    if sample is None:
        load = getattr(os, "getloadavg", None)
        if load is None:
            return None
        return round(min(100.0, load()[0] / (os.cpu_count() or 1) * 100), 1)
    with _LOCK:
        previous = _LAST_CPU[-1] if _LAST_CPU else None
        _LAST_CPU[:] = [sample]
    if previous is None:
        return None
    idle = sample[0] - previous[0]
    total = sample[1] - previous[1]
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - idle / total) * 100)), 1)


def memory() -> tuple[float, float] | None:
    """Return (percent used, total GB)."""
    if sys.platform.startswith("linux"):
        try:
            info = {
                line.split(":")[0]: int(line.split()[1])
                for line in Path("/proc/meminfo").read_text().splitlines()
                if len(line.split()) >= 2
            }
        except OSError, ValueError:
            return None
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        if not total:
            return None
        return round((1 - available / total) * 100, 1), round(total / 1024**2, 1)
    if sys.platform == "win32":
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return float(status.dwMemoryLoad), round(status.ullTotalPhys / 1024**3, 1)
    return None


def sample(disk_path: Path | None = None) -> JsonObject:
    """One reading of CPU, memory, and disk use."""
    mem = memory()
    target = disk_path or Path.home()
    # The models folder may not exist yet; measure the drive it will live on.
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        disk = shutil.disk_usage(target)
        disk_percent: float | None = round(disk.used / disk.total * 100, 1)
        disk_total: float | None = round(disk.total / 1024**3)
    except OSError:
        disk_percent = disk_total = None
    return {
        "cpu": cpu_percent(),
        "cores": os.cpu_count() or 0,
        "memory": mem[0] if mem else None,
        "memory_gb": mem[1] if mem else None,
        "disk": disk_percent,
        "disk_gb": disk_total,
    }
