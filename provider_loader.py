from typing import Any, Callable

from credential_store import CredentialStore
from gemini_provider import GeminiProvider
from groq_provider import GroqProvider
from openai_provider import OpenAIProvider
from providers import AIProvider
from cerebras_provider import CerebrasProvider
from cohere_provider import CohereProvider
from mistral_provider import MistralProvider


def load_configured_providers(
    credentials: CredentialStore,
    provider_configs: dict[str, dict[str, Any]] | None = None
) -> dict[str, AIProvider]:
    configs = provider_configs or {}

    def _build_openai(api_key: str) -> AIProvider:
        cfg = configs.get("openai", {})
        kwargs: dict[str, Any] = {"api_key": api_key}
        if cfg.get("model"):
            kwargs["model"] = cfg["model"]
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return OpenAIProvider(**kwargs)

    factories: dict[
        str,
        Callable[[str], AIProvider]
    ] = {
        "gemini": lambda api_key: GeminiProvider(
            api_key=api_key
        ),
        "openai": _build_openai,
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

    for custom_name, cfg in configs.items():
        if custom_name in factories:
            continue
        model = cfg.get("model") or "gpt-4o-mini"
        base_url = cfg.get("base_url")
        factories[custom_name] = (
            lambda api_key, m=model, b=base_url, n=custom_name: OpenAIProvider(
                api_key=api_key,
                model=m,
                base_url=b,
                provider_name=n
            )
        )

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
