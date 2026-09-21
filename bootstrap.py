from dispatcher import ProviderDispatcher
from memory_service import MemoryService
from orchestrator import PalaceOrchestrator
from provider_registry import ProviderRegistry
from providers import AIProvider


def build_palace(
    providers: dict[str, AIProvider],
    wing: str = "gpt_palace",
    memory_limit: int = 4000,
    max_workers: int = 4
) -> PalaceOrchestrator:

    if not providers:
        raise ValueError(
            "At least one AI provider is required."
        )

    registry = ProviderRegistry()

    for name, provider in providers.items():
        registry.register(
            name,
            provider
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
