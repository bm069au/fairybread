from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

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


class GeminiProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
        timeout: float = 60.0,
    ):
        try:
            self.client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=max(5000, int(timeout * 1000))),
            )
        except Exception:
            self.client = genai.Client(api_key=api_key)
        self.model = model
        self.timeout = timeout

    def generate(
        self,
        prompt: str,
        *,
        images: list[Path | str] | None = None,
    ) -> ProviderResponse:
        valid_parts: list[Any] = []
        for raw_p in (images or [])[:3]:
            try:
                p = Path(raw_p)
                if p.is_file() and 0 < p.stat().st_size <= 6 * 1024 * 1024:
                    valid_parts.append(
                        types.Part.from_bytes(
                            data=p.read_bytes(),
                            mime_type=_guess_image_mime(p),
                        )
                    )
            except OSError:
                pass

        if valid_parts:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=[*valid_parts, prompt],
            )
            txt = getattr(resp, "text", None) or ""
            if not txt.strip():
                raise RuntimeError(f"gemini ({self.model}) returned empty multimodal response")
            in_tok, out_tok = extract_sdk_usage_tokens(resp, prompt_text=prompt, output_text=txt)
            return ProviderResponse(
                text=txt,
                model=self.model,
                provider="gemini",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        try:
            interaction = self.client.interactions.create(
                model=self.model,
                input=prompt
            )
            out_txt = getattr(interaction, "output_text", None) or ""
            usage_src = interaction
        except AttributeError:
            if not hasattr(self.client, "models"):
                raise
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            out_txt = getattr(resp, "text", None) or ""
            usage_src = resp
        if not out_txt.strip():
            raise RuntimeError(f"gemini ({self.model}) returned empty output")

        in_tok, out_tok = extract_sdk_usage_tokens(usage_src, prompt_text=prompt, output_text=out_txt)
        return ProviderResponse(
            text=out_txt,
            model=self.model,
            provider="gemini",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
