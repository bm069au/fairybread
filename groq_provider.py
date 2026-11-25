from groq import Groq

from cost_service import extract_sdk_usage_tokens
from providers import AIProvider, ProviderResponse


class GroqProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
        timeout: float = 120.0,
    ):
        self.client = Groq(
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )
        self.model = model
        self.timeout = timeout

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

        out_text = completion.choices[0].message.content or ""
        in_tok, out_tok = extract_sdk_usage_tokens(completion, prompt_text=prompt, output_text=out_text)
        return ProviderResponse(
            text=out_text,
            model=self.model,
            provider="groq",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
