from cerebras.cloud.sdk import Cerebras

from providers import AIProvider, ProviderResponse


class CerebrasProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "qwen-3.8-27b"
    ):
        self.client = Cerebras(
            api_key=api_key
        )
        self.model = model

    def generate(self, prompt: str) -> ProviderResponse:
        response = self.client.chat.completions.create(
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
            provider="cerebras"
        )
