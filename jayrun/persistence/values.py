"""Versioned diagnostic values; no arbitrary repr, pickle, discovery or imports.

Normal decoding never instantiates application types. A codec is an explicit
application opt-in, used only when supplied to the particular encode/decode call.
The application is responsible for a codec's execution time and side effects.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta, timezone
import json
from typing import TypeAlias
from uuid import UUID

from .errors import StorageContractError
from .policy import _positive_integer

VALUE_SCHEMA = "jayrun.values/1"
PathPart: TypeAlias = str | int
ValuePath: TypeAlias = tuple[PathPart, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ValueLimits:
    max_bytes: int = 1024 * 1024
    max_depth: int = 16
    max_items: int = 4096
    max_nodes: int = 16_384
    max_string_bytes: int = 65_536
    max_integer_bits: int = 4096

    def __post_init__(self) -> None:
        for field in fields(self):
            _positive_integer(field.name, getattr(self, field.name))
        if self.max_depth > 64:
            raise ValueError("max_depth cannot exceed 64")


@dataclass(frozen=True, slots=True)
class ValueMarker:
    """Explicit absent/omitted/unresolved data, distinct from a recorded None."""

    kind: str
    reason: str = ""
    codec: str | None = None
    version: int | None = None
    payload: ValueSnapshot | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"missing", "redacted", "unsupported", "truncated", "cycle", "codec"}:
            raise ValueError("unknown diagnostic marker")
        if type(self.reason) is not str or len(self.reason) > 256:
            raise ValueError("marker reason must be bounded text")
        if self.kind == "codec":
            _codec_name(self.codec, self.version)
            if not isinstance(self.payload, ValueSnapshot):
                raise ValueError("unresolved codec requires a detached payload")
        elif self.codec is not None or self.version is not None or self.payload is not None:
            raise ValueError("only codec markers have a payload")


def _codec_name(name: object, version: object) -> None:
    if type(name) is not str or not name or len(name) > 128 or not name.isascii():
        raise ValueError("codec name must be nonempty ASCII text of at most 128 characters")
    _positive_integer("codec version", version)


@dataclass(frozen=True, slots=True)
class DiagnosticCodec:
    """Exact-type, explicit versioned encoding. No automatic decoder is installed."""

    name: str
    version: int
    value_type: type
    encode: Callable[[object], object]
    decode: Callable[[object], object] | None = None

    def __post_init__(self) -> None:
        _codec_name(self.name, self.version)
        if not isinstance(self.value_type, type) or not callable(self.encode):
            raise ValueError("a codec requires an exact value type and encoder")
        if self.decode is not None and not callable(self.decode):
            raise ValueError("codec decoder must be callable or None")


def _codecs(codecs: tuple[DiagnosticCodec, ...]) -> dict[type, DiagnosticCodec]:
    if type(codecs) is not tuple or len(codecs) > 64:
        raise ValueError("codecs must be a tuple of at most 64 DiagnosticCodec values")
    by_type: dict[type, DiagnosticCodec] = {}
    names: set[tuple[str, int]] = set()
    for codec in codecs:
        if not isinstance(codec, DiagnosticCodec):
            raise ValueError("invalid DiagnosticCodec")
        key = (codec.name, codec.version)
        if codec.value_type in by_type or key in names:
            raise ValueError("duplicate codec type or name/version")
        names.add(key)
        by_type[codec.value_type] = codec
    return by_type


def _json(value: object) -> bytes:
    # Most scalar tokens (including setting names and integer hex values) are
    # two exact strings. Escape with the same JSON primitive, without building
    # a general-purpose container encoder for every tiny token.
    if (type(value) is list and len(value) == 2
            and type(value[0]) is str and type(value[1]) is str):
        return ("[" + json.encoder.encode_basestring_ascii(value[0]) + ","
                + json.encoder.encode_basestring_ascii(value[1]) + "]").encode("ascii")
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _typename(cls: type) -> str:
    # Built-in descriptors avoid application repr/metaclass hooks.
    module = type.__getattribute__(cls, "__module__")
    name = type.__getattribute__(cls, "__qualname__")
    return ((module if type(module) is str else "<unknown>") + "." + name)[:256]


def _forbidden(cls: type) -> bool:
    # Do not let a registered codec make automatic artifact/device/authority capture
    # possible. Explicit application references (strings, IDs) remain supported.
    for parent in type.__getattribute__(cls, "__mro__"):
        name = _typename(parent)
        if name.startswith(("torch.", "numpy.ndarray", "jayrun.core.artifact.",
                            "jayrun.core.resource.", "jayrun.authority.", "jayrun.engine.",
                            "_io.", "_thread.")) or issubclass(parent, BaseException):
            return True
    return False


@dataclass(frozen=True, slots=True)
class ValueSnapshot:
    """Immutable bytes; decode returns a fresh value, never a live historical handle."""

    data: bytes
    limits: ValueLimits = ValueLimits()

    def __post_init__(self) -> None:
        if type(self.data) is not bytes or not isinstance(self.limits, ValueLimits):
            raise StorageContractError("snapshot requires bytes and ValueLimits")
        _read(self.data, self.limits)

    def decode(self, *, codecs: tuple[DiagnosticCodec, ...] = ()) -> object:
        """Decode supported types; custom types remain ValueMarker unless explicitly supplied."""
        by_name = {(c.name, c.version): c for c in _codecs(codecs).values()}
        node = _read(self.data, self.limits)
        return _decode(node, self.limits, by_name)

    @property
    def complete(self) -> bool:
        """Whether the encoded tree has no omission/unresolved codec markers."""
        def clean(node: list) -> bool:
            tag = node[0]
            if tag in {"missing", "redacted", "unsupported", "truncated", "cycle", "codec"}:
                return False
            if tag == "dict":
                return all(clean(k) and clean(v) for k, v in node[1])
            if tag in {"list", "tuple", "set", "frozenset"}:
                return all(clean(v) for v in node[1])
            return True
        return clean(_read(self.data, self.limits))


def _redactions(redact: tuple[ValuePath, ...], limits: ValueLimits) -> frozenset[ValuePath]:
    if type(redact) is not tuple or len(redact) > limits.max_nodes:
        raise ValueError("redact must be a bounded tuple of field paths")
    for path in redact:
        if type(path) is not tuple or len(path) > limits.max_depth or any(type(p) not in (str, int) for p in path):
            raise ValueError("invalid redaction path")
        for part in path:
            if type(part) is str and len(part.encode("utf-8", "surrogatepass")) > limits.max_string_bytes:
                raise ValueError("redaction path exceeds string bound")
            if type(part) is int and part.bit_length() > limits.max_integer_bits:
                raise ValueError("redaction index exceeds integer bound")
    return frozenset(redact)


def _key_node(node: list) -> bool:
    """Only losslessly representable hashable elements may identify map/set entries."""
    tag = node[0]
    if tag in {"tuple", "frozenset"}:
        return all(_key_node(child) for child in node[1])
    if tag == "float" and node[1] == "nan":
        return False
    return tag in {"null", "bool", "int", "float", "str", "bytes", "date", "datetime", "timedelta", "uuid"}


def encode_value(
    value: object, *, limits: ValueLimits = ValueLimits(),
    redact: tuple[ValuePath, ...] = (), codecs: tuple[DiagnosticCodec, ...] = (),
) -> ValueSnapshot:
    """Detach exact supported types within bounds, before any runtime lock is acquired.

    Redaction paths select exact string/integer mapping keys or sequence positions.
    Redaction is explicit, not secret detection. Oversized containers/values become
    visible markers; an oversized final envelope raises StorageContractError.
    """
    if not isinstance(limits, ValueLimits):
        raise ValueError("limits must be ValueLimits")
    redactions = _redactions(redact, limits)
    selected = _codecs(codecs)
    ancestors: set[int] = set()
    remaining = limits.max_nodes
    # Charge escaped JSON bytes while traversing, rather than building an
    # enormous intermediate tree that is rejected only by the final dump.
    byte_budget = limits.max_bytes
    scalar_bytes: dict[tuple, bytes] = {}

    def canonical(node: list) -> bytes:
        # Only detached scalar tokens are shared, within this capture. Composite
        # keys still serialize normally; every visit keeps its own limit charges.
        if type(node[0]) is not str or node[0] in ("tuple", "frozenset"):
            return _json(node)
        key = tuple(node)
        encoded = scalar_bytes.get(key)
        if encoded is None:
            encoded = _json(node)
            scalar_bytes[key] = encoded
        return encoded

    def visit(item: object, path: ValuePath | None, depth: int, *, allow_codec: bool = True) -> list:
        nonlocal remaining, byte_budget
        remaining -= 1
        byte_budget -= 8
        if byte_budget < 0:
            raise StorageContractError("diagnostic envelope exceeds max_bytes")
        if path is not None and path in redactions:
            return ["redacted", "field policy"]
        if remaining < 0:
            # Reject the whole capture so exhaustion cannot choose different
            # surviving values from an unordered mapping/set traversal.
            raise StorageContractError("diagnostic value count exceeds max_nodes")
        if depth > limits.max_depth:
            return ["truncated", "depth"]
        cls = type(item)
        if item is None:
            return ["null"]
        if cls is bool:
            return ["bool", item]
        if cls is int:
            if item.bit_length() > limits.max_integer_bits:
                return ["truncated", "integer bits"]
            token = ["int", hex(item)]
        elif cls is float:
            token = ["float", item.hex()]
        elif cls in (str, bytes):
            if len(item) > limits.max_string_bytes:
                return ["truncated", "string/bytes length"]
            if cls is str and len(item.encode("utf-8", "surrogatepass")) > limits.max_string_bytes:
                return ["truncated", "string bytes"]
            token = ["str", item] if cls is str else ["bytes", item.hex()]
        elif cls is datetime:
            if item.tzinfo is not None and type(item.tzinfo) is not timezone:
                return ["unsupported", "custom timezone"]
            token = ["datetime", item.isoformat(), item.fold]
        elif cls is date:
            token = ["date", item.isoformat()]
        elif cls is timedelta:
            token = ["timedelta", item.days, item.seconds, item.microseconds]
        elif cls is UUID:
            token = ["uuid", item.hex]
        elif cls is ValueMarker:
            if item.kind == "codec":
                return ["codec", item.codec, item.version, _read(item.payload.data, limits)]
            token = [item.kind, item.reason]
        elif cls in (list, tuple, dict, set, frozenset):
            if id(item) in ancestors:
                return ["cycle", "ancestor reference"]
            if len(item) > limits.max_items or remaining < len(item) * (2 if cls is dict else 1):
                return ["truncated", "collection/value count"]
            ancestors.add(id(item))
            try:
                if cls is dict:
                    pairs = []
                    for key, child in item.items():
                        child_path = path + (key,) if path is not None and type(key) in (str, int) else None
                        encoded_key = visit(key, None, depth + 1, allow_codec=False)
                        if not _key_node(encoded_key):
                            return ["unsupported", "mapping contains an unsupported key"]
                        pairs.append([encoded_key, visit(child, child_path, depth + 1)])
                    pairs.sort(key=lambda p: canonical(p[0]))
                    return ["dict", pairs]
                values = [visit(child, path + (index,) if path is not None and cls in (list, tuple) else None, depth + 1) for index, child in enumerate(item)]
                if cls in (set, frozenset):
                    if not all(_key_node(child) for child in values):
                        return ["unsupported", "set contains an unsupported element"]
                    values.sort(key=canonical)
                return [cls.__name__, values]
            except RuntimeError as error:
                raise StorageContractError("diagnostic container mutated during capture") from error
            finally:
                ancestors.remove(id(item))
        elif _forbidden(cls):
            token = ["unsupported", "forbidden payload/handle"]
        elif allow_codec and cls in selected:
            if id(item) in ancestors:
                return ["cycle", "codec ancestor reference"]
            codec = selected[cls]
            ancestors.add(id(item))
            try:
                try:
                    result = codec.encode(item)
                except Exception as error:
                    raise StorageContractError(f"diagnostic codec {codec.name}/{codec.version} failed") from error
                return ["codec", codec.name, codec.version, visit(result, path, depth + 1, allow_codec=False)]
            finally:
                ancestors.remove(id(item))
        else:
            token = ["unsupported", _typename(cls)]
        byte_budget -= len(canonical(token))
        if byte_budget < 0:
            raise StorageContractError("diagnostic envelope exceeds max_bytes")
        return token

    # No policy can match when the validated redaction set is empty. Avoid
    # constructing unused path tuples throughout that traversal.
    node = visit(value, () if redactions else None, 0)
    data = _json([VALUE_SCHEMA, node])
    if len(data) > limits.max_bytes:
        raise StorageContractError("diagnostic envelope exceeds max_bytes")
    return ValueSnapshot(data, limits)


def _read(data: bytes, limits: ValueLimits) -> list:
    if len(data) > limits.max_bytes:
        raise StorageContractError("diagnostic envelope exceeds max_bytes")
    try:
        value = json.loads(data.decode("ascii"))
        if type(value) is not list or len(value) != 2 or value[0] != VALUE_SCHEMA:
            raise ValueError("unsupported value envelope")
        nodes = 0
        scalar_limit = max(limits.max_string_bytes * 2, limits.max_integer_bits // 4 + 4)

        def validate(node: object, depth: int) -> None:
            nonlocal nodes
            nodes += 1
            if depth > limits.max_depth + 1 or nodes > limits.max_nodes:
                raise ValueError("value structure exceeds limits")
            if type(node) is not list or not node or type(node[0]) is not str:
                raise ValueError("invalid typed value")
            tag = node[0]
            # Writer evidence is dominated by these exact text-backed scalars.
            # Keep the same checks/error order, without the collection/date
            # dispatch chain or recomputing the invariant scalar bound per node.
            if tag in {"str", "int", "float"}:
                if len(node) != 2:
                    raise ValueError("invalid scalar/marker")
                item = node[1]
                if type(item) is not str:
                    raise ValueError("invalid text token")
                if len(item) > scalar_limit:
                    raise ValueError("scalar length exceeds limits")
                if tag == "str":
                    if len(item.encode("utf-8", "surrogatepass")) > limits.max_string_bytes:
                        raise ValueError("string exceeds limits")
                elif tag == "int":
                    if int(item, 16).bit_length() > limits.max_integer_bits:
                        raise ValueError("integer exceeds limits")
                else:
                    float.fromhex(item)
            elif tag == "null":
                if len(node) != 1:
                    raise ValueError("invalid null")
            elif tag == "codec":
                if len(node) != 4:
                    raise ValueError("invalid codec")
                _codec_name(node[1], node[2]); validate(node[3], depth + 1)
            elif tag in {"list", "tuple", "set", "frozenset", "dict"}:
                if len(node) != 2 or type(node[1]) is not list or len(node[1]) > limits.max_items:
                    raise ValueError("invalid collection")
                for item in node[1]:
                    if tag == "dict":
                        if type(item) is not list or len(item) != 2:
                            raise ValueError("invalid mapping pair")
                        validate(item[0], depth + 1); validate(item[1], depth + 1)
                    else:
                        validate(item, depth + 1)
                if tag in {"dict", "set", "frozenset"}:
                    keys = [pair[0] for pair in node[1]] if tag == "dict" else node[1]
                    # Decode only the checked built-in hashable subset. A
                    # malformed stored envelope must not collapse entries or
                    # defer executable/custom key interpretation to inspection.
                    if not keys or (keys[0][0] == "str" and all(key[0] == "str" for key in keys)):
                        # Recursive validation above already checked each exact
                        # string token and its bounds. Settings/metadata maps
                        # need no generic hashability walk or decoding here.
                        decoded = [key[1] for key in keys]
                    else:
                        if not all(_key_node(key) for key in keys):
                            raise ValueError("unsupported collection key/element")
                        decoded = [_decode(key, limits, {}) for key in keys]
                    if len(set(decoded)) != len(decoded):
                        raise ValueError("indistinguishable collection keys/elements")
            elif tag == "datetime":
                if len(node) != 3 or type(node[1]) is not str or type(node[2]) is not int or node[2] not in (0, 1):
                    raise ValueError("invalid datetime")
                datetime.fromisoformat(node[1])
            elif tag == "timedelta":
                if len(node) != 4 or any(type(v) is not int for v in node[1:]):
                    raise ValueError("invalid timedelta")
                timedelta(days=node[1], seconds=node[2], microseconds=node[3])
            else:
                if len(node) != 2:
                    raise ValueError("invalid scalar/marker")
                item = node[1]
                if tag == "bool":
                    if type(item) is not bool:
                        raise ValueError("invalid bool")
                elif tag in {"bytes", "date", "uuid", "missing", "redacted", "unsupported", "truncated", "cycle"}:
                    if type(item) is not str:
                        raise ValueError("invalid text token")
                    if len(item) > scalar_limit:
                        raise ValueError("scalar length exceeds limits")
                    if tag == "bytes":
                        if len(bytes.fromhex(item)) > limits.max_string_bytes:
                            raise ValueError("bytes exceed limits")
                    if tag == "date": date.fromisoformat(item)
                    if tag == "uuid": UUID(hex=item)
                    if tag in {"missing", "redacted", "unsupported", "truncated", "cycle"} and len(item) > 256:
                        raise ValueError("marker exceeds limits")
                else:
                    raise ValueError("unknown value tag")
        validate(value[1], 0)
        return value[1]
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise StorageContractError("invalid/unsupported bounded diagnostic envelope") from error


def _decode(node: list, limits: ValueLimits, codecs: dict[tuple[str, int], DiagnosticCodec]) -> object:
    tag = node[0]
    if tag == "null": return None
    if tag in {"bool", "str"}: return node[1]
    if tag == "int": return int(node[1], 16)
    if tag == "float": return float.fromhex(node[1])
    if tag == "bytes": return bytes.fromhex(node[1])
    if tag == "date": return date.fromisoformat(node[1])
    if tag == "datetime": return datetime.fromisoformat(node[1]).replace(fold=node[2])
    if tag == "timedelta": return timedelta(days=node[1], seconds=node[2], microseconds=node[3])
    if tag == "uuid": return UUID(hex=node[1])
    if tag == "codec":
        codec = codecs.get((node[1], node[2]))
        if codec is not None and codec.decode is not None:
            try:
                return codec.decode(_decode(node[3], limits, codecs))
            except Exception as error:
                raise StorageContractError(f"diagnostic codec {codec.name}/{codec.version} decode failed") from error
        return ValueMarker("codec", codec=node[1], version=node[2], payload=ValueSnapshot(_json([VALUE_SCHEMA, node[3]]), limits))
    if tag in {"missing", "redacted", "unsupported", "truncated", "cycle"}:
        return ValueMarker(tag, node[1])
    if tag == "dict":
        pairs = [(_decode(k, limits, codecs), _decode(v, limits, codecs)) for k, v in node[1]]
        try:
            result = dict(pairs)
        except TypeError as error:
            raise StorageContractError("decoded dictionary has an unhashable key") from error
        if len(result) != len(pairs):
            raise StorageContractError("decoded dictionary has indistinguishable keys")
        return result
    values = [_decode(v, limits, codecs) for v in node[1]]
    try:
        return {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}[tag](values)
    except TypeError as error:
        raise StorageContractError("decoded set has an unhashable value") from error
