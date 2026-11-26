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
    # -----------------------------------------------------
    # Memory included successfully
    # -----------------------------------------------------

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
        provider_names=["openai"],
        include_memory=True
    )

    assert memory_service.last_query == (
        "What should Palace do?"
    )

    assert result.question == (
        "What should Palace do?"
    )

    assert result.memory_context == (
        "Relevant stored memory"
    )

    assert result.memory_error is None

    assert (
        "Relevant stored memory"
        in result.prompt
    )

    assert (
        "What should Palace do?"
        in result.prompt
    )

    assert dispatcher.last_prompt == (
        result.prompt
    )

    assert dispatcher.last_provider_names == [
        "openai"
    ]

    assert "openai" in result.provider_results

    assert (
        result
        .provider_results["openai"]
        .succeeded
    )

    # -----------------------------------------------------
    # Memory requested but memory service fails
    # -----------------------------------------------------

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
        "Can Palace continue?",
        include_memory=True
    )

    assert failing_memory.last_query == (
        "Can Palace continue?"
    )

    assert result.memory_context == (
        "Memory unavailable."
    )

    assert result.memory_error == (
        "Simulated memory failure"
    )

    assert (
        "Memory unavailable."
        in result.prompt
    )

    assert (
        "Can Palace continue?"
        in result.prompt
    )

    assert "openai" in result.provider_results

    assert (
        result
        .provider_results["openai"]
        .succeeded
    )

    # -----------------------------------------------------
    # Privacy default:
    # memory must NOT be queried unless explicitly enabled
    # -----------------------------------------------------

    private_memory = FakeMemoryService(
        SimpleNamespace(
            succeeded=True,
            context="This should never be read",
            error=None
        )
    )

    private_dispatcher = FakeDispatcher()

    orchestrator = PalaceOrchestrator(
        private_memory,
        private_dispatcher
    )

    result = orchestrator.run(
        "Private test"
    )

    assert private_memory.last_query is None

    assert result.memory_context == (
        "Memory not included."
    )

    assert result.memory_error is None

    assert (
        "Memory not included."
        in result.prompt
    )

    assert (
        "Private test"
        in result.prompt
    )

    assert "openai" in result.provider_results

    assert (
        result
        .provider_results["openai"]
        .succeeded
    )


import unittest


class OrchestratorRegressionTests(unittest.TestCase):
    def test_basic_orchestrator_memory_flow(self):
        test_orchestrator()

    def test_plain_language_source_guard_and_silent_tools(self):
        from unittest.mock import patch
        from palace_config import build_palace_source_context
        from orchestrator import _execute_internal_agent_tools

        # 1. Ordinary question mentioning "this app" must NOT inject developer source tools
        self.assertEqual(build_palace_source_context("Is this app able to access gmail?"), "")

        # 2. Prompt includes plain non-technical rule on ordinary questions, and relaxes for explicit code asks
        mem = FakeMemoryService(SimpleNamespace(succeeded=True, context="None", error=None))
        orch_plain = PalaceOrchestrator(mem, FakeDispatcher())
        plain_prompt = orch_plain._build_prompt("How do I connect my Gmail?", "None")
        self.assertIn("Plain Non-Technical Language by Default", plain_prompt)
        code_prompt = orch_plain._build_prompt("Show me the python source code for this", "None")
        self.assertNotIn("Plain Non-Technical Language by Default", code_prompt)

        # 3. Silent [TOOL: ...] / [EMAIL_TEST] follow-up produces plain-English answer without leaking raw plumbing
        class ToolThenPlainDispatcher:
            def __init__(self):
                self.calls = []
            def dispatch(self, prompt: str, provider_names=None, **_kw):
                self.calls.append((prompt, provider_names))
                if len(self.calls) == 1:
                    txt = '[TOOL: search_source_code query="EMAIL_SEARCH"]\n[EMAIL_TEST]'
                else:
                    txt = "I checked your email connection and both receiving and sending are ready."
                return {
                    "openai": SimpleNamespace(
                        succeeded=True,
                        response=SimpleNamespace(text=txt, model="gpt-test"),
                        error=None,
                    )
                }

        disp = ToolThenPlainDispatcher()
        orch = PalaceOrchestrator(mem, disp)
        with patch("email_service.test_email_connection", return_value={
            "ok": True,
            "imap_ok": True,
            "imap_message": "Inbox connected.",
            "smtp_ok": True,
            "smtp_message": "Sending login verified.",
            "summary": "Both Inbox and Sending work for tester@gmail.com.",
        }):
            res = orch.run("I am asking you to try my email", provider_names=["openai"], include_memory=False, include_context=False)
        self.assertGreaterEqual(len(disp.calls), 2)
        ans = res.final_answer or ""
        self.assertIn("both receiving and sending are ready", ans)
        self.assertNotIn("[TOOL:", ans)
        self.assertNotIn("[EMAIL_TEST]", ans)
        self.assertNotIn("[ON-DEMAND SOURCE CODE TOOL RESULT]", ans)

        # 4. External [EMAIL_SEND ...] requires prior confirmation
        with patch("email_service.load_email_settings", return_value={"email_address": "me@gmail.com"}), \
             patch("email_service.send_email_message") as mock_send:
            out_txt, did_run = _execute_internal_agent_tools(
                '[EMAIL_SEND to="friend@example.com" subject="Hey" body="Test email"]',
                user_question="Send an email to friend@example.com saying Test email",
                session_context="",
            )
        self.assertTrue(did_run)
        self.assertIn("CONFIRMATION REQUIRED", out_txt)
        mock_send.assert_not_called()


if __name__ == "__main__":
    test_orchestrator()
    unittest.main()
