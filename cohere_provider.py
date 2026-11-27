import cohere

from cost_service import extract_sdk_usage_tokens
from providers import AIProvider, ProviderResponse


class CohereProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "command-a-03-2025",
        timeout: float | None = 0.0,
        handshake_timeout: float = 15.0,
    ):
        eff_timeout = 3600.0 if (timeout is None or float(timeout) <= 0.0) else float(timeout)
        self.client = cohere.ClientV2(
            api_key=api_key,
            timeout=eff_timeout,
        )
        self.model = model
        self.timeout = timeout
        self.handshake_timeout = max(5.0, float(handshake_timeout or 15.0))

    def generate(self, prompt: str) -> ProviderResponse:
        response = self.client.chat(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        text = response.message.content[0].text
        in_tok, out_tok = extract_sdk_usage_tokens(response, prompt_text=prompt, output_text=text or "")

        return ProviderResponse(
            text=text,
            model=self.model,
            provider="cohere",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
