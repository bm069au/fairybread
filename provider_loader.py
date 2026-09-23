from typing import Callable

from credential_store import CredentialStore
from gemini_provider import GeminiProvider
from groq_provider import GroqProvider
from providers import AIProvider
from cerebras_provider import CerebrasProvider
from cohere_provider import CohereProvider
from mistral_provider import MistralProvider


def load_configured_providers(
    credentials: CredentialStore
) -> dict[str, AIProvider]:
    factories: dict[
        str,
        Callable[[str], AIProvider]
    ] = {
        "gemini": lambda api_key: GeminiProvider(
            api_key=api_key
        ),
        "groq": lambda api_key: GroqProvider(
            api_key=api_key
        ),
        "mistral": lambda api_key: MistralProvider(
            api_key=api_key
        ),
        "cerebras": lambda api_key: CerebrasProvider(
            api_key=api_key
        ),
        "cohere": lambda api_key: CohereProvider(
            api_key=api_key
        )
    }

    providers: dict[str, AIProvider] = {}

    for provider_name, factory in factories.items():
        api_key = credentials.get_api_key(
            provider_name
        )

        if api_key:
            providers[provider_name] = factory(
                api_key
            )

    return providers
