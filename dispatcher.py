from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from provider_registry import ProviderRegistry
from provider_result import ProviderResult


class ProviderDispatcher:
    def __init__(self, registry: ProviderRegistry, max_workers: int = 16):
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
        provider_names: list[str] | None = None,
        on_result: Callable[[ProviderResult], None] | None = None
    ) -> dict[str, ProviderResult]:

        if provider_names is None:
            provider_names = self.registry.names()

        if not provider_names:
            return {}

        worker_count = min(self.max_workers, len(provider_names))
        completed_map: dict[str, ProviderResult] = {}

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_name = {
                executor.submit(
                    self._dispatch_one,
                    name,
                    prompt.get(name, next(iter(prompt.values()), "")) if isinstance(prompt, dict) else prompt,
                ): name
                for name in provider_names
            }

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                res = future.result()
                completed_map[name] = res
                if on_result is not None:
                    on_result(res)

        return {
            name: completed_map[name]
            for name in provider_names
            if name in completed_map
        }
