from __future__ import annotations

from collections.abc import Mapping

from ..context.base import DataContext
from ..context.runtime_data import Data
from ..graph.definition.field import ConfigDefinition
from ..graph.graph_definition import GraphDefinition
from ..graph.registry.config import ConfigRegistry
from .field import ConfigField
from .values import validate_config_value, yaml_config_value


_ConfigReference = int | ConfigField | ConfigDefinition


class ConfigContext(DataContext[_ConfigReference, Data[object]]):
    """Build the configuration values for one graph submission.

    Builder contexts are graph-independent. References are resolved against the
    explicit graph during submission; before then, only exact
    :class:`~jayrun.ConfigField` declarations support lookup. Submission creates a
    separate, sealed context that additionally supports graph-local definitions and
    IDs.

    Args:
        configs: Optional initial values, using the same rules as :meth:`set`.
        name: Optional name for diagnostics.
        description: Optional description for diagnostics.
    """

    def __init__(
        self,
        configs: Mapping[_ConfigReference, object] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self._registry: ConfigRegistry | None = None
        if configs is not None:
            self.set(configs)

    def set(
        self,
        configs: Mapping[_ConfigReference, object],
    ) -> None:
        """Set or replace configuration values.

        Builder keys may be exact declarations or graph-relative references. All values are checked against the portable value contract immediately.
        Exact declaration types are checked immediately; graph-relative field
        types are checked when the submission graph resolves them. Assignments
        retain call order, and the last reference resolving to a field supplies its
        submitted value.

        Args:
            configs: Mapping from configuration references to values.

        Raises:
            RuntimeError: If the context is sealed.
            TypeError: If the mapping, reference, or value type is invalid.
            ValueError: If a required exact-declaration value is ``None``.
        """
        self._require_mutable()
        if not isinstance(configs, Mapping):
            raise TypeError(
                "Expected a mapping of config IDs, ConfigField, or "
                "ConfigDefinition to values."
            )

        instances: dict[_ConfigReference, Data[object]] = {}

        for key, value in configs.items():
            self._validate_reference(key)
            if isinstance(key, ConfigField):
                self._validate_value(key, value)
            else:
                validate_config_value(value, path="config value")
            instances[key] = Data(value=value)

        self._update_ordered_instances(instances)

    def get(
        self,
        config: _ConfigReference,
    ) -> Data[object] | None:
        """Return a configured or default value wrapped in :class:`~jayrun.Data`.

        Before submission, ``config`` must be the exact declaration object used
        with :meth:`set`. Definitions and integer IDs become available only on the
        normalized submission context.
        """
        if self._registry is None:
            if isinstance(config, ConfigField):
                field = config
            else:
                self._validate_reference(config)
                self._require_registry()
        else:
            field = self._resolve_field(config)

        if field in self._instances:
            return self._instances[field]

        if field.default is None:
            return None

        return Data(value=field.default)

    def clear(self) -> None:
        """Remove every configured value from this mutable builder context."""
        self._require_mutable()
        self._instances.clear()

    def _validate(self) -> bool:
        """Return whether required values exist in a normalized context.

        This is available on a submitted run's context, not on a mutable builder.
        Submission validates builder values against its explicit graph.

        Raises:
            RuntimeError: If called before submission normalization.
        """
        registry = self._require_registry()
        return all(
            self.get(definition) is not None
            for definition in registry.definitions
            if definition.required
        )

    def to_yaml(self, graph: GraphDefinition) -> str:
        """Serialize graph configuration metadata and current values as YAML.

        Args:
            graph: Confirmed graph used to resolve configuration IDs and metadata.

        Raises:
            TypeError: If ``graph`` is not a :class:`~jayrun.GraphDefinition`.
            RuntimeError: If the graph is unconfirmed.
            KeyError: If this context contains a field outside ``graph``.
        """
        import yaml

        registry = self._registry_for_graph(graph)
        instances: dict[ConfigField, Data[object]] = {}
        for reference, data in self._instances.items():
            field = self._resolve_with_registry(reference, registry)
            instances[field] = data

        for field, data in instances.items():
            self._validate_value(field, data.value)

        configs = {
            definition.config_id: self._yaml_entry(
                definition,
                registry,
                instances,
            )
            for definition in sorted(
                registry.definitions,
                key=lambda definition: definition.config_id,
            )
        }

        return yaml.safe_dump(
            {"configs": configs},
            sort_keys=False,
            allow_unicode=True,
        )

    def load_yaml(self, content: str, graph: GraphDefinition) -> None:
        """Load graph-resolved values from YAML produced by :meth:`to_yaml`.

        Existing values not present in ``content`` are preserved. Loaded values
        participate in normal assignment order, so later :meth:`set` calls override
        them during submission normalization.

        Args:
            content: YAML document containing a top-level ``configs`` mapping.
            graph: Confirmed graph used to resolve graph-local configuration IDs.

        Raises:
            TypeError: If the content, graph, or YAML structure is invalid.
            RuntimeError: If the context is sealed or the graph is unconfirmed.
            KeyError: If the YAML contains an unknown configuration ID.
            ValueError: If a configuration entry has no value.
        """
        import yaml

        self._require_mutable()
        registry = self._registry_for_graph(graph)

        if not isinstance(content, str):
            raise TypeError("content must be str")

        if len(content.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("config YAML exceeds 8 MiB")
        try:
            document = yaml.safe_load(content)
        except RecursionError as error:
            raise ValueError("config YAML nesting exceeds supported depth") from error

        if document is None:
            return

        if not isinstance(document, Mapping):
            raise TypeError("YAML root must be a mapping")

        configs = document.get("configs")

        if not isinstance(configs, Mapping):
            raise TypeError("'configs' must be a mapping")

        definitions_by_id = {
            definition.config_id: definition for definition in registry.definitions
        }
        values: dict[ConfigField, object] = {}

        for config_id, config in configs.items():
            if type(config_id) is not int:
                raise TypeError("Config IDs in YAML must be integers")

            try:
                definition = definitions_by_id[config_id]
            except KeyError:
                raise KeyError(f"Unknown config ID: {config_id!r}.") from None

            if not isinstance(config, Mapping):
                raise TypeError(f"Config {config_id!r} must be a mapping")

            if "value" not in config:
                raise ValueError(f"Config {config_id!r} is missing 'value'")

            values[registry.source_for(definition)] = yaml_config_value(config["value"])

        self.set(values)

    @classmethod
    def _from_normalized(
        cls,
        source: ConfigContext,
        registry: ConfigRegistry,
        instances: Mapping[ConfigField, Data[object]],
    ) -> ConfigContext:
        context = cls(name=source.name, description=source.description)
        context._registry = registry
        context._instances = dict(instances)
        context._seal()
        return context

    def _is_normalized_for(self, registry: ConfigRegistry) -> bool:
        return self._is_sealed and self._registry is registry

    def _yaml_entry(
        self,
        definition: ConfigDefinition,
        registry: ConfigRegistry,
        instances: Mapping[ConfigField, Data[object]],
    ) -> dict[str, object]:
        field = registry.source_for(definition)
        instance = instances.get(field)

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

    def _require_registry(self) -> ConfigRegistry:
        if self._registry is None:
            raise RuntimeError(
                "graph-relative config access is unavailable before submission "
                "normalization"
            )
        return self._registry

    def _resolve_field(
        self,
        config: _ConfigReference,
    ) -> ConfigField:
        return self._resolve_with_registry(config, self._require_registry())

    @staticmethod
    def _resolve_with_registry(
        config: _ConfigReference,
        registry: ConfigRegistry,
    ) -> ConfigField:
        if isinstance(config, ConfigField):
            if not registry._contains_source(config):
                raise KeyError("The ConfigField does not belong to this graph.")
            return config

        if type(config) is int:
            for definition in registry.definitions:
                if definition.config_id == config:
                    return registry.source_for(definition)
            raise KeyError(f"Unknown config ID: {config!r}.")

        if isinstance(config, ConfigDefinition):
            for definition in registry.definitions:
                if config is definition:
                    return registry.source_for(definition)
            raise KeyError("The ConfigDefinition does not belong to this graph.")

        raise TypeError(
            "Expected int, ConfigField, or ConfigDefinition, "
            f"got {type(config).__name__!r}."
        )

    @staticmethod
    def _validate_reference(config: object) -> None:
        if (
            type(config) is int
            or isinstance(config, (ConfigField, ConfigDefinition))
        ):
            return
        raise TypeError(
            "Expected int, ConfigField, or ConfigDefinition, "
            f"got {type(config).__name__!r}."
        )

    @staticmethod
    def _registry_for_graph(graph: GraphDefinition) -> ConfigRegistry:
        if not isinstance(graph, GraphDefinition):
            raise TypeError("graph must be a GraphDefinition instance")
        if not graph.confirmed:
            raise RuntimeError("The graph must be confirmed.")
        return graph._specification.configs

    @staticmethod
    def _validate_value(
        field: ConfigField,
        value: object,
    ) -> None:
        if value is None:
            if field.required:
                raise ValueError("A required config cannot be None.")
            return

        if type(value) is not field.value_type:
            raise TypeError(
                f"Expected {field.value_type.__name__!r}, got {type(value).__name__!r}."
            )

        validate_config_value(value, path=field.attribute_name or field.name or "config")

    @staticmethod
    def _type_name(value_type: type) -> str:
        if value_type.__module__ == "builtins":
            return value_type.__qualname__

        return f"{value_type.__module__}.{value_type.__qualname__}"
