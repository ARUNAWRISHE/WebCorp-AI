from __future__ import annotations

import math
import sys

try:  # Unix only; Windows falls back to the Win32 process-memory API.
    import resource
except ImportError:  # pragma: no cover - platform dependent
    resource = None
from collections import Counter
from typing import Iterable


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def latency_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    measured = list(values)
    return {
        "n": len(measured),
        "p50_ms": round(percentile(measured, 0.50), 3) if measured else None,
        "p95_ms": round(percentile(measured, 0.95), 3) if measured else None,
        "max_ms": round(max(measured), 3) if measured else None,
    }


def domain_request_summary(counts: Counter[str]) -> dict[str, float | int | None]:
    values = list(counts.values())
    return {
        "domains": len(values),
        "p50_requests": percentile(values, 0.50),
        "p95_requests": percentile(values, 0.95),
        "max_requests": max(values) if values else None,
    }


def peak_rss_bytes() -> int | None:
    if resource is not None:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux and most BSD-derived CI images report KiB.
        return int(value if sys.platform == "darwin" else value * 1024)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            if kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize)
        except Exception:
            return None
    return None
