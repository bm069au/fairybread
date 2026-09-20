from provider_registry import ProviderRegistry
from provider_result import ProviderResult


class ProviderDispatcher:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def dispatch(
        self,
        prompt: str,
        provider_names: list[str] | None = None
    ) -> dict[str, ProviderResult]:

        if provider_names is None:
            provider_names = self.registry.names()

        results: dict[str, ProviderResult] = {}

        for name in provider_names:
            try:
                provider = self.registry.get(name)
                response = provider.generate(prompt)

                results[name] = ProviderResult(
                    provider_name=name,
                    response=response
                )

            except Exception as exc:
                results[name] = ProviderResult(
                    provider_name=name,
                    error=str(exc)
                )

        return results
