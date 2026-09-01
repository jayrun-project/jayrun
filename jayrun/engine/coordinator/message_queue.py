from __future__ import annotations

import asyncio
from collections import deque

from ..messages.runtime_message import RuntimeMessage, RuntimeMessagePriority


class RuntimeMessageQueue:
    _active_burst = 64

    def __init__(self) -> None:
        self._active: deque[RuntimeMessage] = deque()
        self._submissions: deque[RuntimeMessage] = deque()
        self._available = asyncio.Event()
        self._active_count = 0

    def put(self, message: RuntimeMessage) -> None:
        queue = (
            self._submissions
            if message.priority is RuntimeMessagePriority.SUBMISSION
            else self._active
        )
        queue.append(message)
        self._available.set()

    async def get(self) -> RuntimeMessage:
        while self.empty():
            self._available.clear()
            await self._available.wait()

        if self._active and (
            self._active_count < self._active_burst
            or not self._submissions
        ):
            self._active_count += 1
            return self._active.popleft()

        self._active_count = 0
        return self._submissions.popleft()

    def qsize(self) -> int:
        return len(self._active) + len(self._submissions)

    def empty(self) -> bool:
        return not self._active and not self._submissions
