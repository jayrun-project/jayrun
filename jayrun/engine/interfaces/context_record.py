"""Portable context records. No arbitrary-object serialization is performed."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
from types import MappingProxyType, NotImplementedType
from typing import TypeAlias

RecordValue: TypeAlias = None | bool | int | float | str | tuple['RecordValue', ...] | Mapping[str, 'RecordValue']


def _validate_key(key: str) -> None:
    if type(key) is not str:
        raise TypeError("record key must be a string")
    if len(key.encode("utf-8")) > 1024:
        raise ValueError("record key exceeds 1024 UTF-8 bytes")


def _freeze_value(value: object, *, max_bytes: int = 64 * 1024 * 1024) -> tuple[RecordValue, int]:
    active: set[int] = set()
    size = 0

    def freeze(item: object, path: str, depth: int) -> RecordValue:
        nonlocal size
        if depth > 64:
            raise ValueError(f"{path}: record nesting exceeds 64 levels")
        size += 16
        if type(item) is str:
            size += len(item.encode("utf-8"))
        elif type(item) is int:
            size += max(1, (item.bit_length() + 7) // 8)
        if size > max_bytes:
            raise ValueError(f"{path}: record value exceeds {max_bytes} accounted bytes")
        if item is None or type(item) in (bool, int, str):
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError(f"{path}: record floats must be finite")
            return item
        if not isinstance(item, (list, tuple, Mapping)):
            raise TypeError(f"{path}: unsupported record value {type(item).__name__}")
        identity = id(item)
        if identity in active:
            raise ValueError(f"{path}: cyclic record value")
        active.add(identity)
        try:
            if isinstance(item, Mapping):
                result: dict[str, RecordValue] = {}
                for key, child in item.items():
                    if type(key) is not str:
                        raise TypeError(f"{path}: mapping keys must be strings")
                    freeze(key, path, depth + 1)
                    result[key] = freeze(child, f"{path}[{key!r}]", depth + 1)
                return MappingProxyType(result)
            return tuple(freeze(child, f"{path}[{index}]", depth + 1)
                         for index, child in enumerate(item))
        finally:
            active.remove(identity)

    result = freeze(value, "value", 0)
    return result, size


def _portable_value(value: RecordValue) -> object:
    if isinstance(value, Mapping):
        return {key: _portable_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return tuple(_portable_value(child) for child in value)
    return value


def _values_equal(left: RecordValue, right: RecordValue) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return left.keys() == right.keys() and all(
            _values_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, tuple):
        return len(left) == len(right) and all(
            _values_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, float):
        return left.hex() == right.hex()
    return left == right


@dataclass(frozen=True, slots=True)
class ContextRecord:
    """Detached context value with stable context/sequence identity.

    Sequence zero denotes an internal, unpublished request. The context assigns
    positive sequences at commit. Reads expose only committed records. Mappings
    are read-only; codecs encode them as string-key maps and reconstruct this
    type to restore immutability. Integers retain their Python precision.
    """

    step_name: str
    execution: int
    iteration: int
    context_id: int
    key: str
    value: RecordValue
    recorded_at: datetime
    sequence: int = 0
    step_index: int = 0
    attempt: int = 1
    generation: int = 0

    def __post_init__(self) -> None:
        _validate_key(self.key)
        for name in ("context_id", "sequence", "step_index", "generation"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("execution", "iteration", "attempt"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.step_name) is not str:
            raise TypeError("step_name must be a string")
        if not isinstance(self.recorded_at, datetime) or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        frozen, _ = _freeze_value(self.value)
        object.__setattr__(self, "value", frozen)

    def __eq__(self, other: object) -> bool | NotImplementedType:
        if not isinstance(other, ContextRecord):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name)
            for name in self.__dataclass_fields__ if name != "value"
        ) and _values_equal(self.value, other.value)

    def __reduce__(self) -> tuple[type[ContextRecord], tuple[object, ...]]:
        # Pickle is application-owned; this only reconstructs supported values.
        return (type(self), (self.step_name, self.execution, self.iteration,
                self.context_id, self.key, _portable_value(self.value),
                self.recorded_at, self.sequence, self.step_index, self.attempt,
                self.generation))
