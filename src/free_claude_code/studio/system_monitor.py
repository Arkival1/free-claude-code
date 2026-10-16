"""CPU, memory, disk, and graphics card use for the HUD, with no extra packages.

CPU use is measured between two calls, so the first reading after start-up is
None; the HUD polls every few seconds and fills in from the second poll on.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from free_claude_code.core.json_types import JsonObject

_LOCK = threading.Lock()
_LAST_CPU: list[tuple[int, int]] = []
GPU_CACHE_SECONDS = 5.0
"""Starting nvidia-smi isn't free, so its reading is reused this long."""
_GPU_CACHE: list[tuple[float, list[JsonObject] | None]] = []


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
    return _busy(previous, sample)


def _busy(previous: tuple[int, int], sample: tuple[int, int]) -> float | None:
    idle = sample[0] - previous[0]
    total = sample[1] - previous[1]
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - idle / total) * 100)), 1)


class CpuWindow:
    """CPU use over this caller's own window, so it never shortens the HUD's.

    Readings closer together than ``min_seconds`` reuse the last one: many
    jobs starting at once would otherwise measure a window too short to mean
    anything.
    """

    def __init__(
        self,
        *,
        min_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        times: Callable[[], tuple[int, int] | None] = _cpu_times,
    ) -> None:
        self._min_seconds = min_seconds
        self._clock = clock
        self._times = times
        self._last: tuple[int, int] | None = None
        self._last_at = 0.0
        self._value: float | None = None

    def percent(self) -> float | None:
        now = self._clock()
        if self._last is not None and now - self._last_at < self._min_seconds:
            return self._value
        sample = self._times()
        if sample is None:
            return None
        previous, self._last, self._last_at = self._last, sample, now
        if previous is None:
            return None
        busy = _busy(previous, sample)
        if busy is not None:
            self._value = busy
        return self._value


def gpus(
    *, run: Callable[[list[str]], str | None] | None = None
) -> list[JsonObject] | None:
    """Each NVIDIA card's load, memory, and temperature, or None without one.

    Read with nvidia-smi, which comes with NVIDIA's driver; other cards, and
    PCs without the tool, report None.
    """
    now = time.monotonic()
    with _LOCK:
        cached = _GPU_CACHE[-1] if _GPU_CACHE else None
    if run is None and cached is not None and now - cached[0] < GPU_CACHE_SECONDS:
        return cached[1]
    output = (run or _nvidia_smi)(
        [
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    found = parse_gpus(output) if output else None
    if run is None:
        with _LOCK:
            _GPU_CACHE[:] = [(now, found)]
    return found


def parse_gpus(text: str) -> list[JsonObject] | None:
    """Read nvidia-smi's CSV lines: name, load %, memory used and total MB, °C."""
    found: list[JsonObject] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue
        name = ", ".join(parts[:-4])
        numbers: list[float | None] = []
        for part in parts[-4:]:
            try:
                numbers.append(float(part))
            except ValueError:
                numbers.append(None)
        load, used, total, temperature = numbers
        found.append(
            {
                "name": name,
                "load": load,
                "memory_used_gb": round(used / 1024, 1) if used is not None else None,
                "memory_gb": round(total / 1024, 1) if total is not None else None,
                "memory": (
                    round(used / total * 100, 1) if used is not None and total else None
                ),
                "temperature": temperature,
            }
        )
    return found or None


def _nvidia_smi(arguments: list[str]) -> str | None:
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return None
    try:
        finished = subprocess.run(
            [binary, *arguments],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
            # The hidden Windows server must not flash a console window.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return finished.stdout if finished.returncode == 0 else None


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
