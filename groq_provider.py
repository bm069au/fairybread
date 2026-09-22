from groq import Groq

from providers import AIProvider, ProviderResponse


class GroqProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b"
    ):
        self.client = Groq(
            api_key=api_key
        )
        self.model = model

    def generate(self, prompt: str) -> ProviderResponse:
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return ProviderResponse(
            text=completion.choices[0].message.content,
            model=self.model,
            provider="groq"
        )
