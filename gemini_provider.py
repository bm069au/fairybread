from google import genai

from providers import AIProvider, ProviderResponse


class GeminiProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash-lite"
    ):
        self.client = genai.Client(
            api_key=api_key
        )
        self.model = model

    def generate(self, prompt: str) -> ProviderResponse:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt
        )

        return ProviderResponse(
            text=response.text,
            model=self.model,
            provider="gemini"
        )
