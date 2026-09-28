"""Closed, immutable configuration value contract (no application hooks)."""
from __future__ import annotations

import math

CONFIG_MAX_BYTES = 1024 * 1024
CONFIG_MAX_DEPTH = 64
CONFIG_MAX_NODES = 16_384
CONFIG_TYPES = (bool, int, float, str, tuple)


def validate_config_value(value: object, *, path: str = "config") -> None:
    size = nodes = 0

    def visit(item: object, location: str, depth: int) -> None:
        nonlocal size, nodes
        if depth > CONFIG_MAX_DEPTH:
            raise ValueError(f"{location}: config nesting exceeds {CONFIG_MAX_DEPTH}")
        nodes += 1
        size += 16
        kind = type(item)
        if kind is str:
            size += len(item.encode("utf-8"))
        elif kind is int:
            size += max(1, (item.bit_length() + 7) // 8)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError(f"{location}: config floats must be finite")
        elif item is not None and kind is not bool and kind is not tuple:
            raise TypeError(f"{location}: unsupported config value {kind.__name__}")
        if size > CONFIG_MAX_BYTES or nodes > CONFIG_MAX_NODES:
            raise ValueError(f"{location}: config value exceeds bounded size")
        if kind is tuple:
            for index, child in enumerate(item):
                visit(child, f"{location}[{index}]", depth + 1)

    visit(value, path, 0)


def yaml_config_value(value: object) -> object:
    """YAML arrays have tuple semantics only inside config values; aliases are bounded."""
    active: set[int] = set()
    nodes = 0

    def convert(item: object, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if depth > CONFIG_MAX_DEPTH or nodes > CONFIG_MAX_NODES:
            raise ValueError("YAML config exceeds structural bounds")
        if type(item) is not list:
            return item
        identity = id(item)
        if identity in active:
            raise ValueError("cyclic YAML config")
        active.add(identity)
        try:
            return tuple(convert(child, depth + 1) for child in item)
        finally:
            active.remove(identity)

    result = convert(value, 0)
    validate_config_value(result)
    return result
