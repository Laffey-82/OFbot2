from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Capability:
    name: str
    version: str = "1.0.0"
    description: str = ""
    methods: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> Capability:
        self._capabilities[capability.name] = capability
        return capability

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def has(self, name: str) -> bool:
        return name in self._capabilities

    def list(self) -> list[Capability]:
        return list(self._capabilities.values())

    def require(self, names: list[str]) -> list[str]:
        return [name for name in names if not self.has(name)]


capability_registry = CapabilityRegistry()

