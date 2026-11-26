"""Restore immutable settings and snapshot values from pickle state."""
from dataclasses import MISSING, fields


def restore_fields(instance: object, values: list[object]) -> None:
    for index, field in enumerate(fields(instance)):
        value = values[index] if index < len(values) else field.default
        if value is MISSING:
            raise ValueError(f"missing required snapshot field {field.name}")
        object.__setattr__(instance, field.name, value)


def restore_settings(instance: object, values: list[object]) -> None:
    """Reconstruct through the constructor and reject incompatible slot layouts."""
    names = [field.name for field in fields(instance)]
    if len(names) != len(values):
        raise ValueError(f"incompatible {type(instance).__name__} snapshot layout")
    type(instance).__init__(instance, **dict(zip(names, values, strict=True)))
