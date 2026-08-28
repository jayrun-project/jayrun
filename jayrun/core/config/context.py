from __future__ import annotations

from collections.abc import Mapping

from ..context.base import DataContext
from ..context.runtime_data import Data
from ..graph.definition.field import ConfigDefinition
from ..graph.graph_definition import GraphDefinition
from .field import ConfigField


class ConfigContext(DataContext[ConfigField, Data]):
    """Hold configuration values for one graph submission.

    Args:
        graph: Confirmed graph whose configuration fields the context accepts.
        name: Optional name for diagnostics.
        description: Optional description for diagnostics.

    Raises:
        TypeError: If ``graph`` is not a :class:`~jayrun.GraphDefinition`.
        RuntimeError: If the graph has not been confirmed.
    """

    def __init__(
        self,
        *,
        graph: GraphDefinition,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)

        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition instance")
        if not graph.confirmed:
            raise RuntimeError("The graph must be confirmed.")
        self._graph = graph
        self._registry = graph._specification.configs
        self._definitions_by_id = {
            definition.config_id: definition
            for definition in self._registry.definitions
        }

    def set(
        self,
        configs: Mapping[int | ConfigField | ConfigDefinition, object],
    ) -> None:
        """Set or replace configuration values.

        Args:
            configs: Mapping from config IDs, fields, or inspected definitions to
                values.

        Raises:
            KeyError: If a key does not belong to this graph.
            TypeError: If a value does not match its field type.
            ValueError: If a required value is ``None`` or keys are ambiguous.
        """
        if not isinstance(configs, Mapping):
            raise TypeError(
                "Expected a mapping of config IDs, ConfigField, or "
                "ConfigDefinition to values."
            )

        instances: dict[ConfigField, Data] = {}

        for key, value in configs.items():
            field = self._resolve_field(key)

            if field in instances:
                raise ValueError(
                    "Multiple config keys resolve to the same ConfigField."
                )

            self._validate_value(field, value)
            instances[field] = Data(value=value)

        self._update_instances(instances)

    def get(
        self,
        config: int | ConfigField | ConfigDefinition,
    ) -> Data | None:
        """Return a configured or default value wrapped in :class:`~jayrun.Data`."""
        field = self._resolve_field(config)

        if field in self._instances:
            return self._instances[field]

        if field.default is None:
            return None

        return Data(value=field.default)

    def validate(self) -> bool:
        """Return whether every required configuration field has a value."""
        return all(
            self.get(definition) is not None
            for definition in self._registry.definitions
            if definition.required
        )

    def _fork(self) -> ConfigContext:
        context = ConfigContext(
            graph=self.graph,
            name=self.name,
            description=self.description,
        )
        context._instances = dict(self._instances)
        return context

    def to_yaml(self) -> str:
        """Serialize graph configuration metadata and current values as YAML."""
        import yaml

        configs = {
            definition.config_id: self._yaml_entry(definition)
            for definition in sorted(
                self._registry.definitions,
                key=lambda definition: definition.config_id,
            )
        }

        return yaml.safe_dump(
            {"configs": configs},
            sort_keys=False,
            allow_unicode=True,
        )

    def load_yaml(self, content: str) -> None:
        """Load values from YAML produced by :meth:`to_yaml`.

        Existing values not present in ``content`` are preserved.

        Args:
            content: YAML document containing a top-level ``configs`` mapping.
        """
        import yaml

        if not isinstance(content, str):
            raise TypeError("content must be str")

        document = yaml.safe_load(content)

        if document is None:
            return

        if not isinstance(document, Mapping):
            raise TypeError("YAML root must be a mapping")

        configs = document.get("configs")

        if not isinstance(configs, Mapping):
            raise TypeError("'configs' must be a mapping")

        values: dict[int, object] = {}

        for config_id, config in configs.items():
            if type(config_id) is not int:
                raise TypeError("Config IDs in YAML must be integers")

            if not isinstance(config, Mapping):
                raise TypeError(f"Config {config_id!r} must be a mapping")

            if "value" not in config:
                raise ValueError(f"Config {config_id!r} is missing 'value'")

            values[config_id] = config["value"]

        self.set(values)

    def _yaml_entry(
        self,
        definition: ConfigDefinition,
    ) -> dict[str, object]:
        field = self._registry.source_for(definition)
        instance = self._instances.get(field)

        return {
            "name": definition.name,
            "description": definition.description,
            "owner": definition.owner,
            "required": definition.required,
            "layout_position": list(definition.layout_position),
            "attribute_name": definition.attribute_name,
            "value_type": self._type_name(definition.value_type),
            "default": definition.default,
            "value": instance.value if instance is not None else definition.default,
        }

    def _resolve_field(
        self,
        config: int | ConfigField | ConfigDefinition,
    ) -> ConfigField:
        if type(config) is int:
            try:
                definition = self._definitions_by_id[config]
            except KeyError:
                raise KeyError(f"Unknown config ID: {config!r}.") from None

            return self._registry.source_for(definition)

        if isinstance(config, ConfigDefinition):
            if config not in self._registry.definitions:
                raise KeyError("The ConfigDefinition does not belong to this graph.")

            return self._registry.source_for(config)

        if isinstance(config, ConfigField):
            if config not in self._registry.sources:
                raise KeyError("The ConfigField does not belong to this graph.")

            return config

        raise TypeError(
            "Expected int, ConfigField, or ConfigDefinition, "
            f"got {type(config).__name__!r}."
        )

    @staticmethod
    def _validate_value(
        field: ConfigField,
        value: object,
    ) -> None:
        if value is None:
            if field.required:
                raise ValueError("A required config cannot be None.")
            return

        if not isinstance(value, field.value_type):
            raise TypeError(
                f"Expected {field.value_type.__name__!r}, got {type(value).__name__!r}."
            )

        hash(value)

    @staticmethod
    def _type_name(value_type: type) -> str:
        if value_type.__module__ == "builtins":
            return value_type.__qualname__

        return f"{value_type.__module__}.{value_type.__qualname__}"

    @property
    def graph(self) -> GraphDefinition:
        """The confirmed graph associated with this context."""
        return self._graph
