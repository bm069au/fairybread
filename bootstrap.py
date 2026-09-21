from dispatcher import ProviderDispatcher
from memory_service import MemoryService
from openai_provider import OpenAIProvider
from orchestrator import PalaceOrchestrator
from provider_registry import ProviderRegistry


def build_palace(
    api_key: str,
    model: str = "gpt-5-mini",
    wing: str = "gpt_palace",
    memory_limit: int = 4000,
    max_workers: int = 4
) -> PalaceOrchestrator:

    if not api_key.strip():
        raise ValueError("API key cannot be empty.")

    registry = ProviderRegistry()

    registry.register(
        "openai",
        OpenAIProvider(
            api_key=api_key,
            model=model
        )
    )

    dispatcher = ProviderDispatcher(
        registry,
        max_workers=max_workers
    )

    memory_service = MemoryService(
        wing=wing,
        memory_limit=memory_limit
    )

    return PalaceOrchestrator(
        memory_service,
        dispatcher
    )
