from cerebras.cloud.sdk import Cerebras

from cost_service import extract_sdk_usage_tokens
from providers import AIProvider, ProviderResponse

_RETIRED_CEREBRAS_MODELS = {"llama3.1-8b", "llama-3.1-8b", "llama-3.3-70b", "llama3.3-70b"}
_FALLBACK_ORDER = ("gpt-oss-120b", "qwen-3.8-27b")


class CerebrasProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-oss-120b",
        timeout: float = 45.0,
    ):
        self.client = Cerebras(api_key=api_key, timeout=timeout)
        clean_model = (model or "gpt-oss-120b").strip()
        if clean_model.lower() in _RETIRED_CEREBRAS_MODELS:
            clean_model = "gpt-oss-120b"
        self.model = clean_model
        self.timeout = timeout

    def generate(self, prompt: str) -> ProviderResponse:
        candidates = [self.model]
        for fb in _FALLBACK_ORDER:
            if fb not in candidates:
                candidates.append(fb)

        last_exc: Exception | None = None
        for mod in candidates:
            try:
                response = self.client.chat.completions.create(
                    model=mod,
                    messages=[{"role": "user", "content": prompt}],
                )
                out_text = response.choices[0].message.content or ""
                in_tok, out_tok = extract_sdk_usage_tokens(response, prompt_text=prompt, output_text=out_text)
                return ProviderResponse(
                    text=out_text,
                    model=mod,
                    provider="cerebras",
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
            except Exception as exc:
                last_exc = exc
                continue
        raise last_exc if last_exc is not None else RuntimeError("Cerebras generation failed.")
