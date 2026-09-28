from secrets import randbits


class ContextIdGenerator:
    """Generate compact identifiers compatible with signed 64-bit systems."""

    _BITS = 62

    def generate(self) -> int:
        return randbits(self._BITS)
