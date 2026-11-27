from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import inspect
import re
import threading
import time
from typing import Any, Callable

from provider_registry import ProviderRegistry
from provider_result import ProviderResult


_INLINE_SESSION_HISTORY_RE = re.compile(
    r"(?:={2,}\s*RECENT SESSION HISTORY[^\n]*\n.*?\n={2,}\s*END SESSION HISTORY[^\n]*(?:\n+)?|"
    r"RECENT SESSION HISTORY(?:\s*\([^)]*\))?:\n.*?(?=\n+(?:MEMORY CONTEXT:|SHARED MEMORY CONTEXT:|WORKSPACE / SOURCE CODE TOOL CONTEXT:|ORIGINAL USER QUESTION:|CURRENT USER QUESTION:|USER QUESTION:)))",
    re.DOTALL,
)


def _strip_duplicate_inline_history(prompt: str) -> str:
    """Remove duplicate inline history text when structured `history_messages` are passed natively."""
    if not prompt or "RECENT SESSION HISTORY" not in prompt:
        return prompt
    return _INLINE_SESSION_HISTORY_RE.sub(
        "CONVERSATION HISTORY: (Provided directly in structured conversation turns above.)\n",
        prompt,
        count=1,
    )


class ProviderDispatcher:
    def __init__(self, registry: ProviderRegistry, max_workers: int = 16):
        self.registry = registry
        self.max_workers = max_workers

    def _dispatch_one(
        self,
        name: str,
        prompt: str,
        images: list[Any] | None = None,
        *,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
        on_activity: Callable[[], None] | None = None,
        heartbeat_enabled: bool = True,
        heartbeat_interval_sec: float = 15.0,
    ) -> ProviderResult:
        hb_stop = threading.Event()
        hb_thread: threading.Thread | None = None
        try:
            if on_activity is not None:
                on_activity()
            provider = self.registry.get(name)
            if heartbeat_enabled and on_activity is not None and heartbeat_interval_sec > 0:
                interval = max(1.0, min(60.0, float(heartbeat_interval_sec)))

                def _heartbeat_pulse() -> None:
                    while not hb_stop.wait(timeout=interval):
                        try:
                            on_activity()
                        except Exception:
                            break

                hb_thread = threading.Thread(
                    target=_heartbeat_pulse,
                    daemon=True,
                    name=f"FairybreadHeartbeat-{name}",
                )
                hb_thread.start()

            call_kw: dict[str, Any] = {}
            if images or system_prompt or history_messages or model_override or on_activity:
                try:
                    sig = inspect.signature(provider.generate)
                    params = sig.parameters
                    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                except (TypeError, ValueError):
                    params = {}
                    has_varkw = False

                if images and (has_varkw or "images" in params):
                    call_kw["images"] = images
                if system_prompt and (has_varkw or "system_prompt" in params):
                    call_kw["system_prompt"] = system_prompt
                if history_messages and (has_varkw or "history_messages" in params):
                    call_kw["history_messages"] = history_messages
                if on_activity is not None and "on_activity" in params:
                    call_kw["on_activity"] = on_activity
                if model_override and (has_varkw or "model_override" in params):
                    try:
                        from palace_config import resolve_profile_model_override
                        is_or = "openrouter.ai" in str(getattr(provider, "base_url", "") or "").lower()
                        resolved_ov = resolve_profile_model_override(name, str(model_override), is_openrouter=is_or)
                    except Exception:
                        resolved_ov = str(model_override).strip()
                    if resolved_ov:
                        call_kw["model_override"] = resolved_ov

            eff_prompt = _strip_duplicate_inline_history(prompt) if "history_messages" in call_kw else prompt
            response = provider.generate(eff_prompt, **call_kw) if call_kw else provider.generate(eff_prompt)
            if on_activity is not None:
                on_activity()

            return ProviderResult(
                provider_name=name,
                response=response
            )

        except Exception as exc:
            return ProviderResult(
                provider_name=name,
                error=str(exc)
            )
        finally:
            hb_stop.set()

    def dispatch(
        self,
        prompt: str | dict[str, str],
        provider_names: list[str] | None = None,
        on_result: Callable[[ProviderResult], None] | None = None,
        *,
        images: list[Any] | None = None,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        model_overrides: dict[str, str] | None = None,
        per_provider_timeout: float | None = None,
        provider_ceilings: dict[str, float] | None = None,
        straggler_grace_seconds: float | None = None,
        heartbeat_enabled: bool = True,
        heartbeat_interval_sec: float = 15.0,
        cancel_event: Any = None,
    ) -> dict[str, ProviderResult]:

        if provider_names is None:
            provider_names = self.registry.names()

        if not provider_names:
            return {}
        if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
            return {}

        eff_global_timeout = (
            float(per_provider_timeout)
            if (per_provider_timeout is not None and float(per_provider_timeout) > 0.0)
            else None
        )
        worker_count = min(self.max_workers, len(provider_names))
        completed_map: dict[str, ProviderResult] = {}
        start_ts = time.monotonic()
        activity_ts: dict[str, float] = {name: start_ts for name in provider_names}
        heartbeat_seen: dict[str, bool] = {name: False for name in provider_names}
        quorum_met_at: float | None = None
        quorum_target = max(2, (len(provider_names) + 1) // 2)
        timed_out_any = False

        def _make_activity_cb(p_name: str) -> Callable[[], None]:
            def _touch() -> None:
                now_t = time.monotonic()
                if now_t - start_ts > 0.05:
                    heartbeat_seen[p_name] = True
                activity_ts[p_name] = now_t
            return _touch

        executor = ThreadPoolExecutor(max_workers=worker_count)
        try:
            future_to_name = {
                executor.submit(
                    self._dispatch_one,
                    name,
                    prompt.get(name, next(iter(prompt.values()), "")) if isinstance(prompt, dict) else prompt,
                    images,
                    system_prompt=system_prompt,
                    history_messages=history_messages,
                    model_override=(model_overrides or {}).get(name),
                    on_activity=_make_activity_cb(name),
                    heartbeat_enabled=heartbeat_enabled,
                    heartbeat_interval_sec=heartbeat_interval_sec,
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
                cancelled_now = (
                    cancel_event is not None
                    and hasattr(cancel_event, "is_set")
                    and cancel_event.is_set()
                )
                if cancelled_now and pending:
                    timed_out_any = True
                    for fut in list(pending):
                        fut.cancel()
                        name = future_to_name[fut]
                        res = ProviderResult(
                            provider_name=name,
                            error="Cancelled by operator.",
                        )
                        completed_map[name] = res
                        if on_result is not None:
                            on_result(res)
                    pending.clear()
                    break

                if (
                    straggler_grace_seconds is not None
                    and straggler_grace_seconds > 0
                    and len(provider_names) >= 3
                    and quorum_met_at is None
                ):
                    succ_cnt = sum(1 for r in completed_map.values() if r.succeeded)
                    if succ_cnt >= 2 and len(completed_map) >= quorum_target:
                        quorum_met_at = now

                exceeded_grace = quorum_met_at is not None and (now - quorum_met_at) >= float(straggler_grace_seconds or 0)
                if pending:
                    expired_futs = []
                    for fut in list(pending):
                        name = future_to_name[fut]
                        last_act = activity_ts.get(name, start_ts)
                        idle_secs = (now - last_act) if heartbeat_seen.get(name) else (now - start_ts)
                        prov_cap = (provider_ceilings or {}).get(name)
                        eff_prov_timeout = (
                            float(prov_cap)
                            if (prov_cap is not None and float(prov_cap) > 0.0)
                            else eff_global_timeout
                        )
                        total_elapsed = now - start_ts
                        is_hard_expired = (
                            eff_prov_timeout is not None
                            and (idle_secs >= eff_prov_timeout or total_elapsed >= eff_prov_timeout)
                        )
                        is_grace_expired = exceeded_grace and (not heartbeat_seen.get(name) or idle_secs >= float(straggler_grace_seconds or 0))
                        if is_hard_expired or is_grace_expired:
                            expired_futs.append((fut, name, is_grace_expired and not is_hard_expired))
                    if expired_futs:
                        timed_out_any = True
                        elapsed = now - start_ts
                        for fut, name, was_grace in expired_futs:
                            pending.discard(fut)
                            fut.cancel()
                            reason_tag = "straggler cutoff" if was_grace else "timeout"
                            res = ProviderResult(
                                provider_name=name,
                                error=f"Timed out after {elapsed:.1f}s ({reason_tag})",
                            )
                            completed_map[name] = res
                            if on_result is not None:
                                on_result(res)
                        if not pending:
                            break
        finally:
            executor.shutdown(wait=not timed_out_any, cancel_futures=timed_out_any)

        return dict(completed_map)
