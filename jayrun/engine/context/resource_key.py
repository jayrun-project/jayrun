from dataclasses import dataclass
from typing import Hashable

from ...core.resource.base import BaseResource


@dataclass(frozen=True, slots=True)
class ResourceKey:
    resource_type: type[BaseResource]
    configuration: tuple[tuple[str, Hashable | None], ...]
    parallel_safe: bool
