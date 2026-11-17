from mistralai.client import Mistral

from providers import AIProvider, ProviderResponse


class MistralProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest"
    ):
        self.client = Mistral(
            api_key=api_key
        )
        self.model = model

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
