"""Win32 physical-memory readings for scheduler admission, in bytes."""

import ctypes


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(_MemoryStatusEx),)
_kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
_kernel32.GetCurrentProcess.argtypes = ()
_kernel32.GetCurrentProcess.restype = ctypes.c_void_p
_kernel32.K32GetProcessMemoryInfo.argtypes = (
    ctypes.c_void_p, ctypes.POINTER(_ProcessMemoryCounters), ctypes.c_uint32,
)
_kernel32.K32GetProcessMemoryInfo.restype = ctypes.c_int
# GetCurrentProcess returns a pseudo-handle valid for this process's lifetime.
_current_process = _kernel32.GetCurrentProcess()


def process_usage() -> int | None:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if _kernel32.K32GetProcessMemoryInfo(_current_process, ctypes.byref(counters), counters.cb):
        return counters.WorkingSetSize
    return None


def system_memory() -> tuple[int | None, int | None]:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if _kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return status.ullTotalPhys, status.ullAvailPhys
    return None, None
