class _RuntimeCapability:
    __slots__ = ()

    def __reduce__(self):
        raise TypeError("runtime capabilities cannot be serialized")
