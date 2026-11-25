import base64
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from cost_service import extract_sdk_usage_tokens
from providers import AIProvider, ProviderResponse


def _guess_image_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    return "image/png"


_RETIRED_OPENAI_MODEL_MAP: dict[str, str] = {
    "gpt-5": "gpt-6.2-sol",
    "gpt-5-mini": "gpt-6-luna",
    "gpt-5-nano": "gpt-6-luna",
    "gpt-5-pro": "gpt-6.2-sol",
    "o3": "gpt-6.2-astra",
    "o3-pro": "gpt-6.2-astra",
}


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-mini",
        base_url: str | None = None,
        provider_name: str = "openai",
        max_tokens: int | None = None,
        timeout: float = 300.0,
        max_retries: int = 0,
    ):
        eff_timeout: Any = (
            httpx.Timeout(float(timeout), connect=min(15.0, float(timeout)))
            if isinstance(timeout, (int, float)) and float(timeout) > 15.0
            else timeout
        )
        if base_url:
            kw: dict[str, Any] = {
                "api_key": api_key,
                "base_url": base_url,
                "timeout": eff_timeout,
                "max_retries": max_retries,
            }
            if "openrouter.ai" in str(base_url).lower():
                kw["default_headers"] = {
                    "HTTP-Referer": "https://fairybread.me",
                    "X-Title": "Fairybread",
                }
            self.client = OpenAI(**kw)
        else:
            self.client = OpenAI(api_key=api_key, timeout=eff_timeout, max_retries=max_retries)
        self.model = model
        self.base_url = base_url
        self.provider_name = provider_name
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

    @staticmethod
    def _extract_explicit_cost(completion_obj: Any) -> float | None:
        if completion_obj is None:
            return None
        usage = (
            completion_obj.get("usage")
            if isinstance(completion_obj, dict)
            else getattr(completion_obj, "usage", None)
        )
        if usage is None:
            return None
        raw_cost = usage.get("cost") if isinstance(usage, dict) else getattr(usage, "cost", None)
        if raw_cost is None and not isinstance(usage, dict):
            extra = getattr(usage, "model_extra", None)
            if isinstance(extra, dict):
                raw_cost = extra.get("cost")
        if raw_cost is None:
            return None
        try:
            val = float(raw_cost)
            return val if val >= 0.0 else None
        except (TypeError, ValueError):
            return None

    def generate(
        self,
        prompt: str,
        *,
        images: list[Path | str] | None = None,
        system_prompt: str = "",
        history_messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> ProviderResponse:
        eff_model = (model_override or "").strip() or self.model
        sys_clean = (system_prompt or "").strip()
        clean_hist: list[dict[str, str]] = []
        if history_messages and isinstance(history_messages, list):
            for m in history_messages[-64:]:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "user").strip().lower()
                if role not in {"user", "assistant"}:
                    role = "user"
                content = str(m.get("content") or "").strip()
                if content:
                    clean_hist.append({"role": role, "content": content})

        if self.base_url:
            chat_image_items: list[dict[str, Any]] = []
            for raw_p in (images or []):
                try:
                    p = Path(raw_p)
                    if p.is_file() and 0 < p.stat().st_size <= 6 * 1024 * 1024:
                        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                        chat_image_items.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{_guess_image_mime(p)};base64,{b64}"},
                        })
                except OSError:
                    pass

            messages: list[dict[str, Any]] = []
            if sys_clean:
                messages.append({"role": "system", "content": sys_clean})
            messages.extend(clean_hist)
            if chat_image_items:
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}, *chat_image_items],
                })
            else:
                messages.append({"role": "user", "content": prompt})
            kwargs = {
                "model": eff_model,
                "messages": messages,
            }
            if self.max_tokens is not None:
                kwargs["max_tokens"] = self.max_tokens
            try:
                completion = self.client.chat.completions.create(**kwargs)
            except Exception:
                if not chat_image_items:
                    raise
                fallback_msgs = list(messages[:-1]) + [{"role": "user", "content": prompt}]
                kwargs["messages"] = fallback_msgs
                completion = self.client.chat.completions.create(**kwargs)
            choices = getattr(completion, "choices", None) or []
            choice0 = choices[0] if choices else None
            msg = getattr(choice0, "message", None)
            text = (getattr(msg, "content", None) or "").strip() if msg is not None else ""
            finish_reason = getattr(choice0, "finish_reason", None)
            reasoning = getattr(msg, "reasoning_content", None) if msg is not None else None
            if not reasoning and msg is not None:
                extra = getattr(msg, "model_extra", None)
                if isinstance(extra, dict):
                    reasoning = extra.get("reasoning_content")
            if not text:
                model_low = str(eff_model or "").lower()
                url_low = str(self.base_url or "").lower()
                if "qwen" in model_low or "deepinfra" in url_low or bool(reasoning):
                    try:
                        retry_kw = dict(kwargs)
                        retry_kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                        if finish_reason == "length":
                            retry_kw["max_tokens"] = max(int(self.max_tokens or 0), 4096)
                        completion2 = self.client.chat.completions.create(**retry_kw)
                        ch2 = (getattr(completion2, "choices", None) or [None])[0]
                        msg2 = getattr(ch2, "message", None)
                        txt2 = (getattr(msg2, "content", None) or "").strip() if msg2 is not None else ""
                        if txt2:
                            completion = completion2
                            text = txt2
                        elif not reasoning and msg2 is not None:
                            reasoning = getattr(msg2, "reasoning_content", None)
                    except Exception:
                        pass
            if not text:
                raise RuntimeError(
                    f"{self.provider_name} ({eff_model}) returned empty output "
                    f"(finish_reason={finish_reason}, reasoning_chars={len(str(reasoning or ''))}, max_tokens={self.max_tokens})"
                )
            in_tok, out_tok = extract_sdk_usage_tokens(completion, prompt_text=prompt, output_text=text)
            return ProviderResponse(
                text=text,
                model=eff_model,
                provider=self.provider_name,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=self._extract_explicit_cost(completion),
            )

        image_items: list[dict[str, str]] = []
        for raw_p in (images or []):
            try:
                p = Path(raw_p)
                if p.is_file() and 0 < p.stat().st_size <= 6 * 1024 * 1024:
                    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                    image_items.append({
                        "type": "input_image",
                        "image_url": f"data:{_guess_image_mime(p)};base64,{b64}",
                    })
            except OSError:
                pass

        resp_kw: dict[str, Any] = {"model": eff_model}
        if sys_clean:
            resp_kw["instructions"] = sys_clean
        if image_items or clean_hist:
            msg_list: list[Any] = []
            for h in clean_hist:
                msg_list.append({"role": h["role"], "content": h["content"]})
            msg_list.append({
                "role": "user",
                "content": (
                    [{"type": "input_text", "text": prompt}, *image_items]
                    if image_items
                    else prompt
                ),
            })
            resp_kw["input"] = msg_list
        else:
            resp_kw["input"] = prompt

        try:
            response = self.client.responses.create(**resp_kw)
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            fallback_model = _RETIRED_OPENAI_MODEL_MAP.get(str(eff_model or "").strip().lower())
            if not fallback_model:
                raise
            eff_model = fallback_model
            self.model = fallback_model
            resp_kw["model"] = eff_model
            response = self.client.responses.create(**resp_kw)
        out_text = getattr(response, "output_text", None) or ""
        if not out_text.strip():
            raise RuntimeError(f"{self.provider_name} ({eff_model}) returned empty output")

        in_tok, out_tok = extract_sdk_usage_tokens(response, prompt_text=prompt, output_text=out_text)
        return ProviderResponse(
            text=out_text,
            model=eff_model,
            provider=self.provider_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=self._extract_explicit_cost(response),
        )
