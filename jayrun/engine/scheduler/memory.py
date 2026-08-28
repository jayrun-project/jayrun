from __future__ import annotations

import os
import sys
from pathlib import Path

from ..resource.placement_request import capacity_bytes

try:
    import resource
except ImportError:
    resource = None


class MemoryPressureMonitor:
    def __init__(
        self,
        memory_limit_gb: int | float | None,
        high_watermark: float = 0.85,
        low_watermark: float = 0.75,
    ) -> None:
        self._configured_limit = (
            capacity_bytes(memory_limit_gb)
            if memory_limit_gb is not None
            else None
        )
        self._high_watermark = high_watermark
        self._low_watermark = low_watermark
        self._pressured = False

    def sample(self) -> bool:
        process_usage = self._process_usage()
        system_capacity, system_available = self._system_memory()
        process_limit = self._configured_limit or system_capacity

        if self._pressured:
            process_recovered = (
                process_usage is None
                or process_limit is None
                or process_usage <= process_limit * self._low_watermark
            )
            system_recovered = (
                system_capacity is None
                or system_available is None
                or system_available
                >= system_capacity * (1 - self._low_watermark)
            )
            if process_recovered and system_recovered:
                self._pressured = False
            return self._pressured

        process_pressured = (
            process_usage is not None
            and process_limit is not None
            and process_usage >= process_limit * self._high_watermark
        )
        system_pressured = (
            system_capacity is not None
            and system_available is not None
            and system_available
            <= system_capacity * (1 - self._high_watermark)
        )
        self._pressured = process_pressured or system_pressured
        return self._pressured

    @classmethod
    def _process_usage(cls) -> int | None:
        if sys.platform.startswith("linux"):
            try:
                values = Path("/proc/self/statm").read_text().split()
                return int(values[1]) * cls._page_size()
            except (IndexError, OSError, ValueError):
                pass
        if resource is None:
            return None
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except (OSError, ValueError):
            return None
        return int(usage if sys.platform == "darwin" else usage * 1024)

    @classmethod
    def _system_memory(cls) -> tuple[int | None, int | None]:
        capacity, available = cls._proc_memory()
        if capacity is None:
            capacity = cls._sysconf_memory("SC_PHYS_PAGES")
        if available is None:
            available = cls._sysconf_memory("SC_AVPHYS_PAGES")

        cgroup_capacity, cgroup_usage = cls._cgroup_memory()
        if cgroup_capacity is not None:
            cgroup_available = max(0, cgroup_capacity - cgroup_usage)
            capacity = (
                cgroup_capacity
                if capacity is None
                else min(capacity, cgroup_capacity)
            )
            available = (
                cgroup_available
                if available is None
                else min(available, cgroup_available)
            )
        return capacity, available

    @staticmethod
    def _proc_memory() -> tuple[int | None, int | None]:
        values: dict[str, int] = {}
        try:
            lines = Path("/proc/meminfo").read_text().splitlines()
        except OSError:
            return None, None
        for line in lines:
            name, separator, value = line.partition(":")
            if not separator:
                continue
            fields = value.split()
            if not fields:
                continue
            try:
                values[name] = int(fields[0]) * 1024
            except ValueError:
                continue
        return values.get("MemTotal"), values.get("MemAvailable")

    @staticmethod
    def _cgroup_memory() -> tuple[int | None, int]:
        for limit_path, usage_path in (
            (
                Path("/sys/fs/cgroup/memory.max"),
                Path("/sys/fs/cgroup/memory.current"),
            ),
            (
                Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
                Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
            ),
        ):
            try:
                limit_value = limit_path.read_text().strip()
                usage_value = usage_path.read_text().strip()
            except OSError:
                continue
            if limit_value == "max":
                continue
            try:
                limit = int(limit_value)
                usage = int(usage_value)
            except ValueError:
                continue
            if limit > 0:
                return limit, max(0, usage)
        return None, 0

    @classmethod
    def _sysconf_memory(cls, name: str) -> int | None:
        try:
            pages = os.sysconf(name)
        except (KeyError, OSError, ValueError):
            return None
        if not isinstance(pages, int) or pages <= 0:
            return None
        return pages * cls._page_size()

    @staticmethod
    def _page_size() -> int:
        try:
            value = os.sysconf("SC_PAGE_SIZE")
        except (KeyError, OSError, ValueError):
            return 4096
        return value if isinstance(value, int) and value > 0 else 4096
