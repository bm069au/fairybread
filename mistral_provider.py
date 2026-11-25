from mistralai.client import Mistral

from cost_service import extract_sdk_usage_tokens
from providers import AIProvider, ProviderResponse


class MistralProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        timeout: float = 180.0,
    ):
        self.client = Mistral(
            api_key=api_key,
            timeout_ms=max(5000, int(timeout * 1000)),
        )
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str) -> ProviderResponse:
        response = self.client.chat.complete(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        out_text = response.choices[0].message.content or ""
        in_tok, out_tok = extract_sdk_usage_tokens(response, prompt_text=prompt, output_text=out_text)
        return ProviderResponse(
            text=out_text,
            model=self.model,
            provider="mistral",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
