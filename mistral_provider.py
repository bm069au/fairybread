from mistralai.client import Mistral

from providers import AIProvider, ProviderResponse


class MistralProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        timeout: float = 45.0,
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

        return ProviderResponse(
            text=response.choices[0].message.content,
            model=self.model,
            provider="mistral"
        )
