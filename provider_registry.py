from providers import AIProvider


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, AIProvider] = {}

    def register(self, name: str, provider: AIProvider) -> None:
        if not name.strip():
            raise ValueError("Provider name cannot be empty.")

        if name in self._providers:
            raise ValueError(f"Provider '{name}' is already registered.")

        self._providers[name] = provider

    def get(self, name: str) -> AIProvider:
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' is not registered.")

        return self._providers[name]

    def names(self) -> list[str]:
        return list(self._providers.keys())

    def all(self) -> dict[str, AIProvider]:
        return dict(self._providers)
