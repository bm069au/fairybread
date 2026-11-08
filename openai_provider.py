from openai import OpenAI

from providers import AIProvider, ProviderResponse


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-mini",
        base_url: str | None = None,
        provider_name: str = "openai"
    ):
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)
        self.model = model
        self.base_url = base_url
        self.provider_name = provider_name

    def generate(self, prompt: str) -> ProviderResponse:
        if self.base_url:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )
            text = (
                completion.choices[0].message.content or ""
                if getattr(completion, "choices", None)
                else ""
            )
            return ProviderResponse(
                text=text,
                model=self.model,
                provider=self.provider_name
            )

        response = self.client.responses.create(
            model=self.model,
            input=prompt
        )

        return ProviderResponse(
            text=response.output_text,
            model=self.model,
            provider=self.provider_name
        )
