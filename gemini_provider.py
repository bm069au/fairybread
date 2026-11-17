from google import genai

from providers import AIProvider, ProviderResponse


class GeminiProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite"
    ):
        self.client = genai.Client(
            api_key=api_key
        )
        self.model = model

    def generate(self, prompt: str) -> ProviderResponse:
        interaction = self.client.interactions.create(
            model=self.model,
            input=prompt
        )

        return ProviderResponse(
            text=interaction.output_text,
            model=self.model,
            provider="gemini"
        )
