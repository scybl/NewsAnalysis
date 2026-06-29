from __future__ import annotations


class ProviderRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, name: str, factory) -> None:
        if name in self._factories:
            raise ValueError(f"provider already registered: {name}")
        self._factories[name] = factory

    def create(self, name: str):
        try:
            return self._factories[name]()
        except KeyError as exc:
            raise ValueError(f"unknown provider: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._factories)
