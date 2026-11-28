"""Graph-owned native fields for an attached use of an authored operator."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from ..artifact.base import Artifact
from ..artifact.field import ArtifactField
from ..config.field import ConfigField
from ..declaration.field import DeclarativeField
from ..resource.field import ResourceField
from .base import BaseOperator


class _BoundOperator(BaseOperator):
    # Keep implementation ownership separate from all author-named fields.
    __slots__ = ("__implementation",)

    @classmethod
    def translating(cls, operator: BaseOperator, translations: Mapping[int, Artifact]) -> BaseOperator:
        bound = object.__new__(cls)
        object.__setattr__(bound, "_BoundOperator__implementation", implementation(operator))

        def artifact_field(field: ArtifactField) -> ArtifactField:
            local = ArtifactField(name=field.name, description=field.description,
                                  required=field.required, properties=field.properties)
            local._bind(translations.get(id(field.artifact), field.artifact), enforce_required=False)
            return local

        for name, field in vars(operator).items():
            if not isinstance(field, DeclarativeField):
                continue
            if isinstance(field, ArtifactField):
                local = artifact_field(field)
            elif isinstance(field, ConfigField):
                local = ConfigField(name=field.name, description=field.description, required=field.required,
                                    value_type=field.value_type, default=field.default)
            elif isinstance(field, ResourceField):
                local = ResourceField(name=field.name, description=field.description, required=field.required,
                                      parallel_safe=field.parallel_safe)
            else:
                raise TypeError(f"Unsupported native field on attached operator: {name!r}")
            # Use the ordinary declaration namespace. No application constructor,
            # copy hook or execution method is invoked when translating bindings.
            vars(bound)[name] = local

        bound.outputs = tuple(artifact_field(field) for field in operator.outputs)
        bound._register_declarative_fields()
        bound._validate_artifact_group(bound.declared_artifact_fields, group_name="input",
                                       require_connected=bool(bound.declared_artifact_fields))
        bound._validate_artifact_group(bound.outputs, group_name="output", require_connected=False)
        object.__setattr__(bound, "_operator_initialized", True)
        return bound

    @property
    def name(self) -> str | None:
        return self.__implementation.name

    @property
    def description(self) -> str | None:
        return self.__implementation.description

    @property
    def display_name(self) -> str:
        return self.__implementation.display_name

    @property
    def requirements(self) -> tuple[str, ...]:
        return self.__implementation.requirements

    @property
    def execute(self) -> Callable[[], object]:
        # Compilation captures the authored function and invokes it on the
        # ordinary engine session proxy with this graph's field bindings.
        return self.__implementation.execute

    def __repr__(self) -> str:
        return repr(self.__implementation)


def implementation(operator: BaseOperator) -> BaseOperator:
    if isinstance(operator, _BoundOperator):
        return operator._BoundOperator__implementation
    return operator
