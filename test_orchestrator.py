from types import SimpleNamespace

from orchestrator import PalaceOrchestrator


class FakeMemoryService:
    def __init__(self, result):
        self.result = result
        self.last_query = None

    def search(self, query: str):
        self.last_query = query
        return self.result


class FakeDispatcher:
    def __init__(self):
        self.last_prompt = None
        self.last_provider_names = None

    def dispatch(self, prompt: str, provider_names=None):
        self.last_prompt = prompt
        self.last_provider_names = provider_names

        return {
            "openai": SimpleNamespace(
                succeeded=True,
                response=SimpleNamespace(
                    text="Fake OpenAI answer"
                ),
                error=None
            )
        }


def test_orchestrator():
    # Normal memory path
    memory_service = FakeMemoryService(
        SimpleNamespace(
            succeeded=True,
            context="Relevant stored memory",
            error=None
        )
    )

    dispatcher = FakeDispatcher()

    orchestrator = PalaceOrchestrator(
        memory_service,
        dispatcher
    )

    result = orchestrator.run(
        "What should Palace do?",
        provider_names=["openai"]
    )

    assert memory_service.last_query == "What should Palace do?"

    assert result.question == "What should Palace do?"
    assert result.memory_context == "Relevant stored memory"
    assert result.memory_error is None

    assert "Relevant stored memory" in result.prompt
    assert "What should Palace do?" in result.prompt

    assert dispatcher.last_prompt == result.prompt
    assert dispatcher.last_provider_names == ["openai"]

    assert "openai" in result.provider_results
    assert result.provider_results["openai"].succeeded

    # Memory failure path
    failing_memory = FakeMemoryService(
        SimpleNamespace(
            succeeded=False,
            context="",
            error="Simulated memory failure"
        )
    )

    failing_dispatcher = FakeDispatcher()

    orchestrator = PalaceOrchestrator(
        failing_memory,
        failing_dispatcher
    )

    result = orchestrator.run(
        "Can Palace continue?"
    )

    assert result.memory_context == "Memory unavailable."
    assert result.memory_error == "Simulated memory failure"

    assert "Memory unavailable." in result.prompt
    assert "Can Palace continue?" in result.prompt

    assert "openai" in result.provider_results
    assert result.provider_results["openai"].succeeded


if __name__ == "__main__":
    test_orchestrator()
    print("Orchestrator tests passed.")
