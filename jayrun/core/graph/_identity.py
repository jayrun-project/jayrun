"""Ordered declaration tokens, not executable identity or graph canonicalization.

Only trusted built-in artifact contracts expose values here. Opaque/custom
metadata contributes its qualified type, never repr, callbacks or instance state.
The application graph version is the revision boundary for omitted semantics.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeAlias

from ..artifact.properties import (
    BackendProperty,
    DeviceProperty,
    DTypeProperty,
    ShapeProperty,
    TypeProperty,
)

if TYPE_CHECKING:
    from ..artifact.base import Artifact
    from ..artifact.field import ArtifactField
    from .definition.artifact import ArtifactDefinition
    from .definition.requirement import RequirementDefinition
    from .operator_reference import OperatorReference

_Token: TypeAlias = str | int | bool | None | tuple['_Token', ...]
_VERSION = 'jrg1'
_MAX_ITEMS = 128
_MAX_VALUES = 256
_MAX_DEPTH = 4
_MAX_TEXT = 4096
_MAX_INTEGER_BITS = 4096
_VALUE_PROPERTIES = (TypeProperty, ShapeProperty, DeviceProperty, BackendProperty)


def _type_name(cls: type) -> tuple[str, str]:
    # Bypass an application's metaclass __getattribute__. Read names only, not
    # descriptors on instances or source/bytecode/closure/implementation state.
    module = type.__dict__['__module__'].__get__(cls)
    name = type.__dict__['__qualname__'].__get__(cls)
    return (module if type(module) is str else '<unknown-module>', name)


def _static(value: object, depth: int = 0) -> tuple[_Token, ...]:
    """Detach supported static values; bound total work as well as depth/width."""
    return _static_value(value, depth, [_MAX_VALUES])


def _static_value(value: object, depth: int, budget: list[int]) -> tuple[_Token, ...]:
    budget[0] -= 1
    if budget[0] < 0:
        return ('omitted', 'value-budget')
    kind = type(value)
    if value is None:
        return ('null',)
    if kind is bool:
        return ('bool', value)
    if kind is int:
        if value.bit_length() > _MAX_INTEGER_BITS:
            return ('omitted', 'integer-bits', value.bit_length())
        return ('int', hex(value))
    if kind is float:
        # hex distinguishes int/float and signed zero; all NaNs use one token.
        return ('float', value.hex())
    if kind is str or kind is bytes:
        if len(value) > _MAX_TEXT:
            return ('omitted', kind.__name__, len(value))
        return ('str', value) if kind is str else ('bytes', value.hex())
    if isinstance(value, type):
        return ('type', *_type_name(value))
    if kind is tuple:
        if len(value) > _MAX_ITEMS:
            return ('omitted', 'tuple-items', len(value))
        if depth >= _MAX_DEPTH:
            return ('omitted', 'tuple-depth')
        items = []
        for item in value:
            items.append(_static_value(item, depth + 1, budget))
            if budget[0] < 0:
                return ('omitted', 'value-budget')
        return ('tuple', tuple(items))
    return ('opaque', *_type_name(kind))


def _contracts(field: ArtifactField) -> tuple[_Token, ...]:
    properties = []
    for prop in field.properties:
        kind = type(prop)
        name = _type_name(kind)
        if kind in _VALUE_PROPERTIES:
            value = _static(prop.value)
        elif kind is DTypeProperty:
            choices = prop.value
            if type(choices) is tuple and len(choices) <= _MAX_ITEMS:
                # DTypeProperty.accepts treats alternatives as a set, including
                # when its constructor received a hash-seed-dependent iterable.
                encoded = _static(choices)
                value = (('alternatives', tuple(sorted(set(encoded[1]))))
                         if encoded[0] == 'tuple' else encoded)
            else:
                value = ('omitted', 'dtype-alternatives')
        else:
            # Even a subclass of a built-in property can implement value as
            # arbitrary code. Its qualified type is the only supported contract.
            value = ('opaque-property',)
        properties.append((name, value))
    # Validation matches properties by type; their tuple order is not a port or
    # operator declaration sequence and must not depend on accidental enumeration.
    return tuple(sorted(properties, key=lambda item: item[0]))


def declaration_tokens(
    operators: tuple[OperatorReference, ...],
    occurrences: tuple[int, ...],
    artifacts: Mapping[Artifact, ArtifactDefinition],
    requirements: tuple[RequirementDefinition, ...],
) -> tuple[_Token, ...]:
    """Freeze minimal metadata before resource-owned configuration discovery.

    Distinct declarations have first-encounter indices; occurrences preserve the
    existing column/row traversal. Connections use existing artifact indices and
    explicit disconnected ports, not labels or process addresses. Consumption and
    reproduction of the same artifact remain distinct occurrences in this order.
    """
    artifact_ids = {artifact: definition.artifact_id for artifact, definition in artifacts.items()}

    def port(field: ArtifactField) -> tuple[_Token, ...]:
        return (field.attribute_name, field.required, artifact_ids.get(field.artifact), _contracts(field))

    declarations = []
    for reference in operators:
        operator = reference.operator
        declarations.append((
            _type_name(type(operator)),
            'event_loop' if inspect.iscoroutinefunction(operator.execute) else 'thread',
            tuple(port(field) for field in operator.declared_artifact_fields),
            tuple(port(field) for field in operator.outputs),
            tuple((field.attribute_name, _type_name(field.value_type), field.required)
                  for field in reference.config_fields),
            tuple((field.attribute_name, field.required, field.parallel_safe)
                  for field in reference.resource_fields),
        ))
    return (
        tuple((definition.role.value, definition.is_exit) for definition in artifacts.values()),
        tuple(declarations),
        occurrences,
        tuple(sorted((item.name, item.extras, item.specifier, item.marker or '') for item in requirements)),
    )


def graph_id(version: str, tokens: tuple[_Token, ...]) -> str:
    """One pure, idempotent digest calculation; caller owns its per-graph cache."""
    encoded = json.dumps((_VERSION, version, tokens), ensure_ascii=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return _VERSION + ':' + hashlib.sha256(encoded).hexdigest()
