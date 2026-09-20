from provider_registry import ProviderRegistry
from providers import ProviderResponse


class ProviderDispatcher:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def dispatch(
        self,
        prompt: str,
        provider_names: list[str] | None = None
    ) -> dict[str, ProviderResponse]:

        if provider_names is None:
            provider_names = self.registry.names()

        responses: dict[str, ProviderResponse] = {}

        for name in provider_names:
            provider = self.registry.get(name)
            responses[name] = provider.generate(prompt)

        return responses
