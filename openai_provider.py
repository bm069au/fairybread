import base64
from pathlib import Path

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


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-mini",
        base_url: str | None = None,
        provider_name: str = "openai",
        max_tokens: int | None = None,
        timeout: float = 45.0,
    ):
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        else:
            self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.base_url = base_url
        self.provider_name = provider_name
        self.max_tokens = max_tokens
        self.timeout = timeout

    def generate(
        self,
        prompt: str,
        *,
        images: list[Path | str] | None = None,
    ) -> ProviderResponse:
        if self.base_url:
            kwargs = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}]
            }
            if self.max_tokens is not None:
                kwargs["max_tokens"] = self.max_tokens
            completion = self.client.chat.completions.create(**kwargs)
            choices = getattr(completion, "choices", None) or []
            choice0 = choices[0] if choices else None
            msg = getattr(choice0, "message", None)
            text = (getattr(msg, "content", None) or "").strip() if msg is not None else ""
            if not text:
                finish_reason = getattr(choice0, "finish_reason", None)
                reasoning = getattr(msg, "reasoning_content", None) if msg is not None else None
                if not reasoning and msg is not None:
                    extra = getattr(msg, "model_extra", None)
                    if isinstance(extra, dict):
                        reasoning = extra.get("reasoning_content")
                raise RuntimeError(
                    f"{self.provider_name} ({self.model}) returned empty output "
                    f"(finish_reason={finish_reason}, reasoning_chars={len(str(reasoning or ''))}, max_tokens={self.max_tokens})"
                )
            in_tok, out_tok = extract_sdk_usage_tokens(completion, prompt_text=prompt, output_text=text)
            return ProviderResponse(
                text=text,
                model=self.model,
                provider=self.provider_name,
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        image_items: list[dict[str, str]] = []
        for raw_p in (images or [])[:3]:
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

        if image_items:
            response = self.client.responses.create(
                model=self.model,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        *image_items,
                    ],
                }],
            )
        else:
            response = self.client.responses.create(
                model=self.model,
                input=prompt
            )
        out_text = getattr(response, "output_text", None) or ""
        if not out_text.strip():
            raise RuntimeError(f"{self.provider_name} ({self.model}) returned empty output")

        in_tok, out_tok = extract_sdk_usage_tokens(response, prompt_text=prompt, output_text=out_text)
        return ProviderResponse(
            text=out_text,
            model=self.model,
            provider=self.provider_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
