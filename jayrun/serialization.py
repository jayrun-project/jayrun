"""Exact, versioned config/record value encoding for application-owned transports.

These codecs do not encode whole ContextSnapshots, arbitrary reports/exceptions,
artifact payloads, or authority. Artifact payloads use graph-bound serializers.
The JSON envelope uses tagged hex integers/floats, preserving Python precision.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import math

from .core.config.values import validate_config_value
from .core.context.runtime_data import Data
from .engine.interfaces.context_record import ContextRecord

__all__ = ("encode_configs", "decode_configs", "encode_record", "decode_record")
_MAX_BYTES = 64 * 1024 * 1024
_MAX_NODES = 1_000_000


def _tree(value: object, depth: int = 0, *, budget: list[int] | None = None) -> list:
    if budget is None:
        budget = [_MAX_NODES, _MAX_BYTES]
    budget[0] -= 1
    charge = 16
    if type(value) is str:
        charge += 6 * len(value)
    elif type(value) is int:
        charge += (value.bit_length() + 3) // 4
    budget[1] -= charge
    if budget[0] < 0 or budget[1] < 0:
        raise ValueError("portable value exceeds structural or size bounds")
    if depth > 64:
        raise ValueError("portable value nesting exceeds 64")
    kind = type(value)
    if value is None: return ["null"]
    if kind is bool: return ["bool", value]
    if kind is int: return ["int", hex(value)]
    if kind is float:
        if not math.isfinite(value): raise ValueError("portable floats must be finite")
        return ["float", value.hex()]
    if kind is str: return ["str", value]
    if kind is tuple: return ["tuple", [_tree(v, depth + 1, budget=budget) for v in value]]
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value): raise TypeError("map keys must be strings")
        for key in value:
            budget[1] -= 6 * len(key) + 16
        if budget[1] < 0: raise ValueError("portable map exceeds size bounds")
        return ["map", [[k, _tree(v, depth + 1, budget=budget)] for k, v in value.items()]]
    raise TypeError("unsupported portable value")


def _value(tree: object, *, depth: int = 0, budget: list[int] | None = None) -> object:
    if budget is None: budget = [_MAX_NODES]
    budget[0] -= 1
    if depth > 64 or budget[0] < 0: raise ValueError("portable value exceeds structural bounds")
    if type(tree) is not list or not tree or type(tree[0]) is not str: raise ValueError("invalid value tag")
    tag = tree[0]
    if tag == "null" and len(tree) == 1: return None
    if len(tree) != 2: raise ValueError("invalid value shape")
    raw = tree[1]
    if tag == "bool" and type(raw) is bool: return raw
    if tag == "str" and type(raw) is str: return raw
    if tag == "int" and type(raw) is str:
        value = int(raw, 16)
        if hex(value) != raw: raise ValueError("noncanonical integer")
        return value
    if tag == "float" and type(raw) is str:
        value = float.fromhex(raw)
        if not math.isfinite(value) or value.hex() != raw: raise ValueError("noncanonical float")
        return value
    if tag == "tuple" and type(raw) is list:
        return tuple(_value(v, depth=depth+1, budget=budget) for v in raw)
    if tag == "map" and type(raw) is list:
        result = {}
        for pair in raw:
            if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str or pair[0] in result:
                raise ValueError("invalid or duplicate map key")
            result[pair[0]] = _value(pair[1], depth=depth+1, budget=budget)
        return result
    raise ValueError("invalid portable value")


def _pack(schema: str, value: object) -> bytes:
    body = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=True, separators=(",", ":"))
    for chunk in encoder.iterencode([schema, value]):
        if len(body) + len(chunk) > _MAX_BYTES:
            raise ValueError("portable envelope exceeds 64 MiB")
        body.extend(chunk.encode("ascii"))
    return bytes(body)


def _unpack(data: bytes, schema: str) -> object:
    if type(data) is not bytes: raise TypeError("encoded data must be bytes")
    if len(data) > _MAX_BYTES: raise ValueError("portable envelope exceeds 64 MiB")
    try:
        document = json.loads(data)
    except (ValueError, RecursionError) as error:
        raise ValueError("invalid portable envelope") from error
    if type(document) is not list or len(document) != 2 or document[0] != schema:
        raise ValueError("unsupported portable schema")
    return document[1]


def encode_configs(configs: tuple[tuple[int, Data[object]], ...]) -> bytes:
    """Encode a snapshot's config_context, preserving omission and explicit None."""
    if type(configs) is not tuple: raise TypeError("configs must be a tuple")
    result = []; seen = set(); budget = [_MAX_NODES, _MAX_BYTES]
    for key, data in configs:
        if type(key) is not int or key < 0 or key in seen: raise ValueError("invalid config ID")
        if type(data) is not Data: raise TypeError("config values must be Data")
        from .engine.resource.placement import Placement, Device
        if type(data.placement) is not Placement or data.placement.device is not Device.CPU: raise ValueError("configs must use CPU placement")
        validate_config_value(data.value)
        budget[1] -= (key.bit_length() + 3) // 4 + 16
        seen.add(key); result.append([hex(key), _tree(data.value, budget=budget)])
    return _pack("jayrun.configs/1", result)


def decode_configs(data: bytes) -> tuple[tuple[int, Data[object]], ...]:
    """Decode values; receiving graph validation still checks IDs and field types."""
    raw = _unpack(data, "jayrun.configs/1")
    if type(raw) is not list: raise ValueError("invalid config list")
    result = []; seen = set(); budget = [_MAX_NODES]
    for pair in raw:
        if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str: raise ValueError("invalid config entry")
        key = int(pair[0], 16)
        if key < 0 or hex(key) != pair[0] or key in seen: raise ValueError("invalid config ID")
        value = _value(pair[1], budget=budget); validate_config_value(value)
        seen.add(key); result.append((key, Data(value=value)))
    return tuple(result)


def encode_record(record: ContextRecord) -> bytes:
    """Encode one immutable record including its timezone-aware timestamp."""
    if type(record) is not ContextRecord: raise TypeError("record must be ContextRecord")
    fields = {name: getattr(record, name) for name in record.__dataclass_fields__}
    fields["recorded_at"] = record.recorded_at.isoformat()
    # Metadata is encoded separately so it does not consume value nesting depth.
    value = fields.pop("value")
    budget = [_MAX_NODES, _MAX_BYTES]
    return _pack("jayrun.record/1", [_tree(fields, budget=budget), _tree(value, budget=budget)])


def decode_record(data: bytes) -> ContextRecord:
    """Restore a record, validating metadata and freezing its value containers."""
    raw = _unpack(data, "jayrun.record/1")
    if type(raw) is not list or len(raw) != 2: raise ValueError("invalid record envelope")
    fields = _value(raw[0]); value = _value(raw[1])
    expected = set(ContextRecord.__dataclass_fields__) - {"value"}
    if type(fields) is not dict or fields.keys() != expected: raise ValueError("invalid record fields")
    if type(fields["recorded_at"]) is not str: raise ValueError("invalid record timestamp")
    fields["recorded_at"] = datetime.fromisoformat(fields["recorded_at"])
    return ContextRecord(**fields, value=value)
