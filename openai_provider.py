from openai import OpenAI

from providers import AIProvider, ProviderResponse


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-5-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate(self, prompt: str) -> ProviderResponse:
        response = self.client.responses.create(
            model=self.model,
            input=prompt
        )

        return ProviderResponse(
            text=response.output_text,
            model=self.model,
            provider="openai"
        )


    

