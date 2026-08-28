class GraphComponent:
    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)

        if not isinstance(name, (str, type(None))):
            raise TypeError(f"{type(self).__name__} 'name' must be string or None")

        if not isinstance(description, (str, type(None))):
            raise TypeError(
                f"{type(self).__name__}' 'description' must be string or None"
            )

        self._name = name
        self._description = description

    @property
    def name(self) -> str | None:
        """Optional component name."""
        return self._name

    @property
    def description(self) -> str | None:
        """Optional component description."""
        return self._description
