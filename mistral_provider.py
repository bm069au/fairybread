import base64
from pathlib import Path
from typing import Any

from mistralai.client import Mistral

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


def _extract_mistral_content_text(raw_content: Any) -> str:
    """Extract clean user-facing text from Mistral/Magistral string or chunked content."""
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, (list, tuple)):
        parts: list[str] = []
        for chunk in raw_content:
            if isinstance(chunk, dict):
                ctype = str(chunk.get("type") or "").strip().lower()
                if ctype == "thinking":
                    continue
                txt = chunk.get("text")
                if isinstance(txt, str) and txt:
                    parts.append(txt)
            else:
                ctype = str(getattr(chunk, "type", "") or "").strip().lower()
                if ctype == "thinking":
                    continue
                txt = getattr(chunk, "text", None)
                if isinstance(txt, str) and txt:
                    parts.append(txt)
        return "\n".join(parts).strip()
    return str(raw_content or "")


class MistralProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        timeout: float | None = 0.0,
        handshake_timeout: float = 15.0,
    ):
        eff_ms = (
            3_600_000
            if (timeout is None or float(timeout) <= 0.0)
            else max(5000, int(float(timeout) * 1000))
        )
        self.client = Mistral(
            api_key=api_key,
            timeout_ms=eff_ms,
        )
        self.model = model
        self.timeout = timeout
        self.handshake_timeout = max(5.0, float(handshake_timeout or 15.0))

    def _build_messages(
        self,
        prompt: str,
        *,
        images: list[Any] | None = None,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        allow_vision: bool = True,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_prompt and str(system_prompt).strip():
            messages.append({"role": "system", "content": str(system_prompt).strip()})
        for hm in history_messages or []:
            role = str((hm or {}).get("role") or "").strip().lower()
            content = str((hm or {}).get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})

        valid_imgs: list[Path] = []
        if allow_vision and images:
            for item in images:
                try:
                    p = Path(item)
                    if not str(p).upper().startswith("M:") and p.is_file():
                        valid_imgs.append(p)
                        if len(valid_imgs) >= 4:
                            break
                except OSError:
                    continue

        if valid_imgs:
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for p in valid_imgs:
                try:
                    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                    mime = _guess_image_mime(p)
                    parts.append({
                        "type": "image_url",
                        "image_url": f"data:{mime};base64,{b64}",
                    })
                except OSError:
                    continue
            messages.append({"role": "user", "content": parts if len(parts) > 1 else prompt})
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    def generate(
        self,
        prompt: str,
        *,
        images: list[Any] | None = None,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> ProviderResponse:
        target_model = str(model_override or self.model or "mistral-medium-latest").strip()
        candidates: list[str] = [target_model]
        for fb in ("mistral-medium-latest", "mistral-small-latest"):
            if fb not in candidates:
                candidates.append(fb)

        last_exc: Exception | None = None
        for idx, cand in enumerate(candidates):
            is_code_only = cand.lower().startswith("codestral")
            messages = self._build_messages(
                prompt,
                images=images,
                system_prompt=system_prompt,
                history_messages=history_messages,
                allow_vision=not is_code_only,
            )
            try:
                response = self.client.chat.complete(
                    model=cand,
                    messages=messages,
                )
                out_text = _extract_mistral_content_text(response.choices[0].message.content)
                in_tok, out_tok = extract_sdk_usage_tokens(response, prompt_text=prompt, output_text=out_text)
                return ProviderResponse(
                    text=out_text,
                    model=cand,
                    provider="mistral",
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
            except Exception as exc:
                last_exc = exc
                low = str(exc).lower()
                # Fail fast on billing/plan or auth errors rather than burning extra requests
                if any(tok in low for tok in ("402", "billing", "budget", "subscription", "401", "unauthorized", "invalid_api_key")):
                    raise
                can_fallback = idx + 1 < len(candidates) and any(
                    tok in low for tok in ("403", "404", "tier_not_allowed", "model_not_found", "not found", "does not exist")
                )
                if can_fallback:
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Mistral chat completion failed.")
