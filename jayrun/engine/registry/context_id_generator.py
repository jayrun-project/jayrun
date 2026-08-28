from itertools import count


class ContextIdGenerator:
    def __init__(self) -> None:
        self._counter = count(100000)

    def generate(self) -> int:
        return next(self._counter)
