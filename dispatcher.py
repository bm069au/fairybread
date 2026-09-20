from concurrent.futures import ThreadPoolExecutor

from provider_registry import ProviderRegistry
from provider_result import ProviderResult


class ProviderDispatcher:
    def __init__(self, registry: ProviderRegistry, max_workers: int = 4):
        self.registry = registry
        self.max_workers = max_workers

    def _dispatch_one(self, name: str, prompt: str) -> ProviderResult:
        try:
            provider = self.registry.get(name)
            response = provider.generate(prompt)

            return ProviderResult(
                provider_name=name,
                response=response
            )

        except Exception as exc:
            return ProviderResult(
                provider_name=name,
                error=str(exc)
            )

    def dispatch(
        self,
        prompt: str,
        provider_names: list[str] | None = None
    ) -> dict[str, ProviderResult]:

        if provider_names is None:
            provider_names = self.registry.names()

        if not provider_names:
            return {}

        worker_count = min(self.max_workers, len(provider_names))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                name: executor.submit(
                    self._dispatch_one,
                    name,
                    prompt
                )
                for name in provider_names
            }

            results = {
                name: futures[name].result()
                for name in provider_names
            }

        return results
