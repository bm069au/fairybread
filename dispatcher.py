from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
from typing import Any, Callable

from provider_registry import ProviderRegistry
from provider_result import ProviderResult


class ProviderDispatcher:
    def __init__(self, registry: ProviderRegistry, max_workers: int = 16):
        self.registry = registry
        self.max_workers = max_workers

    def _dispatch_one(
        self,
        name: str,
        prompt: str,
        images: list[Any] | None = None,
    ) -> ProviderResult:
        try:
            provider = self.registry.get(name)
            if images:
                try:
                    response = provider.generate(prompt, images=images)
                except TypeError:
                    response = provider.generate(prompt)
            else:
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
        prompt: str | dict[str, str],
        provider_names: list[str] | None = None,
        on_result: Callable[[ProviderResult], None] | None = None,
        *,
        images: list[Any] | None = None,
        per_provider_timeout: float | None = None,
        straggler_grace_seconds: float | None = None,
    ) -> dict[str, ProviderResult]:

        if provider_names is None:
            provider_names = self.registry.names()

        if not provider_names:
            return {}

        worker_count = min(self.max_workers, len(provider_names))
        completed_map: dict[str, ProviderResult] = {}
        start_ts = time.monotonic()
        quorum_met_at: float | None = None
        quorum_target = max(2, (len(provider_names) + 1) // 2)
        timed_out_any = False

        executor = ThreadPoolExecutor(max_workers=worker_count)
        try:
            future_to_name = {
                executor.submit(
                    self._dispatch_one,
                    name,
                    prompt.get(name, next(iter(prompt.values()), "")) if isinstance(prompt, dict) else prompt,
                    images,
                ): name
                for name in provider_names
            }
            pending = set(future_to_name.keys())

            while pending:
                done, pending = wait(pending, timeout=0.15, return_when=FIRST_COMPLETED)
                for future in done:
                    name = future_to_name[future]
                    res = future.result()
                    completed_map[name] = res
                    if on_result is not None:
                        on_result(res)

                now = time.monotonic()
                if (
                    straggler_grace_seconds is not None
                    and straggler_grace_seconds > 0
                    and len(provider_names) >= 3
                    and quorum_met_at is None
                ):
                    succ_cnt = sum(1 for r in completed_map.values() if r.succeeded)
                    if succ_cnt >= 2 and len(completed_map) >= quorum_target:
                        quorum_met_at = now

                exceeded_hard = per_provider_timeout is not None and (now - start_ts) >= per_provider_timeout
                exceeded_grace = quorum_met_at is not None and (now - quorum_met_at) >= float(straggler_grace_seconds or 0)
                if pending and (exceeded_hard or exceeded_grace):
                    timed_out_any = True
                    elapsed = now - start_ts
                    reason_tag = "straggler cutoff" if exceeded_grace and not exceeded_hard else "timeout"
                    for fut in list(pending):
                        fut.cancel()
                        name = future_to_name[fut]
                        res = ProviderResult(
                            provider_name=name,
                            error=f"Timed out after {elapsed:.1f}s ({reason_tag})",
                        )
                        completed_map[name] = res
                        if on_result is not None:
                            on_result(res)
                    pending.clear()
                    break
        finally:
            executor.shutdown(wait=not timed_out_any, cancel_futures=timed_out_any)

        return {
            name: completed_map[name]
            for name in provider_names
            if name in completed_map
        }
