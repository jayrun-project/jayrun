"""Closed, bounded history shapes; generic encoding remains the fallback.

Values/snapshots are built afresh and are never cached between captures.
The settings/configuration subset fits inside every default traversal bound:
at most 32 config rows or 64 retained IDs/retry names, strings <=256 code points,
integers <=63 bits, depth <=4, fewer than 1024 nodes, and <400 KiB even with
worst-case JSON escaping and per-node charges. Custom policies use the generic
encoder so its precise truncation, redaction and rejection order is preserved.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

from ..persistence.values import (DiagnosticCodec, VALUE_SCHEMA, ValueLimits,
                                 ValueMarker, ValuePath, ValueSnapshot, _json, encode_value)

_DEFAULT_LIMITS = ValueLimits()
_REQUESTED = tuple(sorted(('max_iterations', 'max_repeats', 'record_history_limit',
    'record_max_keys', 'record_max_value_bytes', 'record_max_total_bytes',
    'retry_policy', 'artifact_policy')))
_EFFECTIVE = tuple(sorted((*_REQUESTED, 'recording_mode', 'failure_mode')))
_ARTIFACT = ('release_entry_artifacts', 'retained_artifacts')
_RETRY = ('max_attempts', 'retry_on')
_CONFIG = ('layout_position', 'name', 'owner', 'value')
_KEYS = MappingProxyType({name: ('str', name)
                         for name in (*_EFFECTIVE, *_ARTIFACT, *_RETRY, *_CONFIG)})


def _matches(value: object, names: tuple[str, ...]) -> bool:
    # Never compare/hash application key objects during fast-path selection.
    return (type(value) is dict and len(value) == len(names)
            and all(type(key) is str for key in value)
            and all(name in value for name in names))


def _scalar(value: object) -> tuple | None:
    cls = type(value)
    if value is None:
        return ('null',)
    if cls is bool:
        return ('bool', value)
    if cls is int and value.bit_length() <= 63:
        return ('int', hex(value))
    if cls is float:
        return ('float', value.hex())
    if cls is str and len(value) <= 256:
        return ('str', value)
    if cls is bytes and len(value) <= 256:
        return ('bytes', value.hex())
    if cls is ValueMarker and type(value.kind) is str and value.kind == 'missing':
        return ('missing', value.reason)
    return None


def _sequence(value: object, item_type: type, maximum: int = 64) -> tuple | None:
    if type(value) is not tuple or len(value) > maximum:
        return None
    nodes = []
    for item in value:
        if type(item) is not item_type:
            return None
        node = _scalar(item)
        if node is None:
            return None
        nodes.append(node)
    return ('tuple', nodes)


def _settings(value: dict) -> tuple | None:
    names = _REQUESTED if len(value) == len(_REQUESTED) else _EFFECTIVE
    if not _matches(value, names):
        return None
    policy = value['artifact_policy']
    if not _matches(policy, _ARTIFACT):
        return None
    retained = ('null',) if policy['retained_artifacts'] is None else _sequence(policy['retained_artifacts'], int)
    release = _scalar(policy['release_entry_artifacts'])
    if retained is None or release is None:
        return None
    artifact = ('dict', [(_KEYS[name], node) for name, node in zip(_ARTIFACT, (release, retained))])
    policy = value['retry_policy']
    retry = ('null',)
    if policy is not None:
        if not _matches(policy, _RETRY):
            return None
        attempts, retry_on = _scalar(policy['max_attempts']), _sequence(policy['retry_on'], str)
        if attempts is None or retry_on is None:
            return None
        retry = ('dict', [(_KEYS['max_attempts'], attempts), (_KEYS['retry_on'], retry_on)])
    pairs = []
    for name in names:
        node = artifact if name == 'artifact_policy' else retry if name == 'retry_policy' else _scalar(value[name])
        if node is None:
            return None
        pairs.append((_KEYS[name], node))
    return ('dict', pairs)


def _configurations(value: dict) -> tuple | None:
    if len(value) > 32:
        return None
    pairs = []
    for identity, entry in value.items():
        if type(identity) is not int or identity.bit_length() > 63 or not _matches(entry, _CONFIG):
            return None
        position = _sequence(entry['layout_position'], int, 2)
        name, owner, data = _scalar(entry['name']), _scalar(entry['owner']), _scalar(entry['value'])
        if position is None or name is None or owner is None or data is None:
            return None
        pairs.append((('int', hex(identity)), ('dict', [(_KEYS[key], node)
                      for key, node in zip(_CONFIG, (position, name, owner, data))])))
    # Integer hex-token order, not numeric order, is the existing wire contract.
    # Hex text has no escaping; ordering it matches ordering the full JSON token.
    pairs.sort(key=lambda pair: pair[0][1])
    return ('dict', pairs)


def _encode_framework_value(value: object, *, limits: ValueLimits,
                            redact: tuple[ValuePath, ...],
                            codecs: tuple[DiagnosticCodec, ...]) -> ValueSnapshot:
    if (type(limits) is ValueLimits and limits == _DEFAULT_LIMITS
            and type(redact) is tuple and not redact
            and type(codecs) is tuple and not codecs):
        node = None
        if type(value) is ValueMarker:
            node = _scalar(value)
        elif type(value) is dict:
            settings_shape = all(type(key) is str for key in value) and 'artifact_policy' in value
            node = _settings(value) if settings_shape else _configurations(value)
        if node is not None:
            # Full final-envelope validation is deliberately retained.
            return ValueSnapshot(_json((VALUE_SCHEMA, node)), limits)
    return encode_value(value, limits=limits, redact=redact, codecs=codecs)


def _encode_detached_facts(value: object, *, limits: ValueLimits,
                           redact: tuple[ValuePath, ...] = ()) -> ValueSnapshot:
    """Encode a small exact-type subset of already detached terminal facts.

    At most 512 nodes, 64 items/container, depth 12, 128 code points/string
    (including keys/marker reasons), and 256 bytes/byte string
    fit all default traversal limits. Even worst-case JSON escaping plus the
    generic encoder's per-node charges is below 512 * 1600 bytes. Outside this
    subset, use the generic encoder with its original policy/error ordering.
    Tokens are shared only inside this call; no diagnostic values are cached.
    """
    if type(limits) is not ValueLimits or limits != _DEFAULT_LIMITS or type(redact) is not tuple or redact:
        return encode_value(value, limits=limits, redact=redact)
    remaining = 512
    keys: dict[str, tuple[tuple, bytes]] = {}

    def visit(item: object, depth: int) -> tuple | None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 12:
            return None
        cls = type(item)
        if cls in (dict, tuple):
            if len(item) > 64:
                return None
            if cls is tuple:
                children = []
                for child in item:
                    node = visit(child, depth + 1)
                    if node is None:
                        return None
                    children.append(node)
                return ('tuple', children)
            pairs = []
            for key, child in item.items():
                if type(key) is not str or len(key) > 128:
                    return None
                remaining -= 1
                if remaining < 0 or depth + 1 > 12:
                    return None
                token = keys.get(key)
                if token is None:
                    token = (('str', key), _json(['str', key]))
                    keys[key] = token
                node = visit(child, depth + 1)
                if node is None:
                    return None
                pairs.append((token, node))
            pairs.sort(key=lambda pair: pair[0][1])
            return ('dict', [(token[0], node) for token, node in pairs])
        if cls is datetime:
            if item.tzinfo is not None and type(item.tzinfo) is not timezone:
                return None
            return ('datetime', item.isoformat(), item.fold)
        if cls is str and len(item) > 128:
            return None
        if cls is ValueMarker and len(item.reason) > 128:
            return None
        return _scalar(item)

    node = visit(value, 0)
    if node is None:
        return encode_value(value, limits=limits, redact=redact)
    # This is still an untrusted envelope at every persistence boundary.
    return ValueSnapshot(_json((VALUE_SCHEMA, node)), limits)
