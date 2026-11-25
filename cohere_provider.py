import cohere

from cost_service import extract_sdk_usage_tokens
from providers import AIProvider, ProviderResponse


class CohereProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "command-a-03-2025",
        timeout: float = 180.0,
    ):
        self.client = cohere.ClientV2(
            api_key=api_key,
            timeout=timeout,
        )
        self.model = model
        self.timeout = timeout

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
