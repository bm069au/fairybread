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
        timeout: float = 300.0,
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
        system_prompt: str = "",
        history_messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> ProviderResponse:
        eff_model = (model_override or "").strip() or self.model
        valid_parts: list[Any] = []
        for raw_p in (images or []):
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

        sys_clean = (system_prompt or "").strip()
        hist_prefix = ""
        if history_messages and isinstance(history_messages, list):
            hist_lines = []
            for m in history_messages[-64:]:
                r = str(m.get("role") or "user").strip().capitalize()
                c = str(m.get("content") or "").strip()
                if c:
                    hist_lines.append(f"{r}: {c}")
            if hist_lines:
                hist_prefix = "\n\n".join(hist_lines) + "\n\nUser: "
        effective_prompt = f"{hist_prefix}{prompt}" if hist_prefix else prompt

        cfg_kw: dict[str, Any] = {}
        if sys_clean and hasattr(types, "GenerateContentConfig"):
            try:
                cfg_kw["config"] = types.GenerateContentConfig(system_instruction=sys_clean)
            except Exception:
                pass

        if valid_parts:
            full_contents = (
                [f"SYSTEM INSTRUCTIONS:\n{sys_clean}\n", *valid_parts, effective_prompt]
                if sys_clean and "config" not in cfg_kw
                else [*valid_parts, effective_prompt]
            )
            try:
                resp = self.client.models.generate_content(
                    model=eff_model,
                    contents=full_contents,
                    **cfg_kw,
                )
            except TypeError:
                resp = self.client.models.generate_content(
                    model=eff_model,
                    contents=[*valid_parts, prompt],
                )
            txt = getattr(resp, "text", None) or ""
            if not txt.strip():
                raise RuntimeError(f"gemini ({eff_model}) returned empty multimodal response")
            in_tok, out_tok = extract_sdk_usage_tokens(resp, prompt_text=prompt, output_text=txt)
            return ProviderResponse(
                text=txt,
                model=eff_model,
                provider="gemini",
                input_tokens=in_tok,
                output_tokens=out_tok,
            )

        if not sys_clean and not hist_prefix:
            try:
                interaction = self.client.interactions.create(
                    model=eff_model,
                    input=prompt
                )
                out_txt = getattr(interaction, "output_text", None) or ""
                usage_src = interaction
            except AttributeError:
                if not hasattr(self.client, "models"):
                    raise
                resp = self.client.models.generate_content(
                    model=eff_model,
                    contents=prompt,
                )
                out_txt = getattr(resp, "text", None) or ""
                usage_src = resp
        else:
            if hasattr(self.client, "models"):
                try:
                    resp = self.client.models.generate_content(
                        model=eff_model,
                        contents=effective_prompt if "config" in cfg_kw else f"SYSTEM INSTRUCTIONS:\n{sys_clean}\n\n{effective_prompt}",
                        **cfg_kw,
                    )
                except TypeError:
                    resp = self.client.models.generate_content(
                        model=eff_model,
                        contents=f"{sys_clean}\n\n{effective_prompt}".strip(),
                    )
                out_txt = getattr(resp, "text", None) or ""
                usage_src = resp
            else:
                interaction = self.client.interactions.create(
                    model=eff_model,
                    input=f"{sys_clean}\n\n{effective_prompt}".strip() if sys_clean else effective_prompt,
                )
                out_txt = getattr(interaction, "output_text", None) or ""
                usage_src = interaction
        if not out_txt.strip():
            raise RuntimeError(f"gemini ({eff_model}) returned empty output")

        in_tok, out_tok = extract_sdk_usage_tokens(usage_src, prompt_text=prompt, output_text=out_txt)
        return ProviderResponse(
            text=out_txt,
            model=eff_model,
            provider="gemini",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
