import cohere

from providers import AIProvider, ProviderResponse


class CohereProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "command-a-03-2025",
        timeout: float = 45.0,
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

        return ProviderResponse(
            text=text,
            model=self.model,
            provider="cohere"
        )
