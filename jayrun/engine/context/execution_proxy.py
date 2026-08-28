from collections.abc import Awaitable, Callable
from typing import TypeAlias

ExecutionResult: TypeAlias = tuple[object, ...] | Exception


def _normalize_outputs(
    results: object,
    output_mask: tuple[bool, ...],
) -> tuple[object, ...]:
    normalized = results if isinstance(results, tuple) else (results,)
    if len(normalized) != len(output_mask):
        raise ValueError(
            f"execution returned {len(normalized)} outputs, "
            f"but {len(output_mask)} were expected"
        )
    return tuple(
        value if keep else None
        for value, keep in zip(normalized, output_mask, strict=True)
    )


class ExecutionProxy:
    _runtime_output_mask: tuple[bool, ...]


class SyncExecutionProxy(ExecutionProxy):
    _runtime_execute: Callable[[], object]

    def execute(self) -> ExecutionResult:
        self.execution._recorder.start_internal_timer("execution_runtime")
        try:
            return _normalize_outputs(
                self._runtime_execute(self),
                self._runtime_output_mask,
            )
        except Exception as error:
            return error
        finally:
            self.execution._recorder.stop_internal_timer("execution_runtime")


class AsyncExecutionProxy(ExecutionProxy):
    _runtime_execute: Callable[[], Awaitable[object]]

    async def execute(self) -> ExecutionResult:
        self.execution._recorder.start_internal_timer("execution_runtime")
        try:
            return _normalize_outputs(
                await self._runtime_execute(self),
                self._runtime_output_mask,
            )
        except Exception as error:
            return error
        finally:
            self.execution._recorder.stop_internal_timer("execution_runtime")


class ResourceTeardownProxy:
    teardown: Callable[..., object] | Callable[..., Awaitable[object]]
