"""Immutable, explicitly bounded storage and local-buffer policies."""
from __future__ import annotations
from dataclasses import dataclass, fields
import math

MiB = 1024 * 1024


def _positive_integer(name: str, value: object) -> None:
    if type(value) is not int or not 1 <= value <= 2**53 - 1:
        raise ValueError(f"{name} must be a positive integer at most 2**53 - 1")


def _positive_seconds(name: str, value: object, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 10**10:
        raise ValueError(f"{name} must be positive finite seconds")


@dataclass(frozen=True, slots=True, kw_only=True)
class RetentionPolicy:
    """One versioned policy per store. Bytes are logical data, except file_bytes.

    Referenced layouts count once toward total_context_bytes. Referenced/open sessions
    and unexpired producer watermarks are not evicted to conceal capacity failure.
    Main-file allocation has a separate page ceiling; journal size is not included.
    Legacy import ledgers/evidence have separate hard bounds and never expire
    automatically; capacity exhaustion cannot silently permit replay after pruning.
    """

    contexts: int = 10_000
    total_context_bytes: int = 128 * MiB
    context_age_seconds: float | None = 7 * 86400
    sessions: int = 10_000
    session_bytes: int = 16 * MiB
    session_age_seconds: float | None = 30 * 86400
    profiles: int = 4096
    profile_steps: int = 65_536
    profile_bytes: int = 32 * MiB
    profile_age_seconds: float | None = 30 * 86400
    producers: int = 4096
    retry_horizon_seconds: float = 7 * 86400
    file_bytes: int = 512 * MiB
    legacy_imports: int = 1024
    legacy_bytes: int = 16 * MiB

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("_seconds"):
                _positive_seconds(field.name, value, optional="age" in field.name)
                if value is not None:
                    object.__setattr__(self, field.name, float(value))
            else:
                _positive_integer(field.name, value)
        if self.file_bytes < 1024 * 1024:
            raise ValueError("file_bytes must be at least 1 MiB")


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseLimits:
    """Per-component limits. These do not replace live runtime retention."""

    pending_items: int = 256
    pending_bytes: int = 64 * MiB
    essential_bytes: int = 4096
    protected_essential_bytes: int = MiB
    max_context_bytes: int = 2 * MiB
    layout_bytes: int = 8 * MiB
    batch_items: int = 32
    batch_bytes: int = 16 * MiB
    reader_requests: int = 16
    page_items: int = 100
    page_bytes: int = MiB
    maintenance_interval_seconds: float = 30.0
    max_attempts: int = 3
    busy_timeout: float = 0.25
    operation_timeout: float = 5.0
    close_timeout: float = 10.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("timeout") or field.name == "maintenance_interval_seconds":
                _positive_seconds(field.name, value)
            else:
                _positive_integer(field.name, value)
        if not self.essential_bytes <= self.protected_essential_bytes <= self.pending_bytes:
            raise ValueError("essential_bytes <= protected_essential_bytes <= pending_bytes is required")
        if self.batch_bytes > self.pending_bytes:
            raise ValueError("batch_bytes cannot exceed pending_bytes")
        if self.page_items > 1000 or self.reader_requests > 1024:
            raise ValueError("page_items/reader_requests exceed their supported limits")
        if self.max_attempts > 10:
            raise ValueError("max_attempts cannot exceed 10")
