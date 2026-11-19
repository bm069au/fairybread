import base64
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from attachment_service import compose_question, extract_attachment
from bootstrap import build_palace
from context_service import ContextService
from dispatcher import ProviderDispatcher
from gemini_provider import GeminiProvider
from idle_service import _IDLE_PATCH_PATTERN, execute_live_autopatches_in_text
from openai_provider import OpenAIProvider
from orchestrator import PalaceOrchestrator, classify_drawing_request
from palace_config import (
    DEFAULT_AGENT_DEFAULTS,
    DEFAULT_GRAPHICS_SETTINGS,
    load_agent_defaults,
    load_graphics_settings,
    save_agent_defaults,
    save_graphics_settings,
)
from palace_theme import (
    _GENERATE_IMAGE_TAG_PATTERN,
    extract_reference_image_paths,
    format_markdown_and_drawings,
    generate_ai_image_to_png,
    get_image_engine_badge,
    prewarm_generated_images,
)
from provider_loader import load_configured_providers
from provider_registry import ProviderRegistry
from provider_result import ProviderResult
from providers import AIProvider, ProviderResponse
from search_service import detect_organic_turn_intents, is_terse_patch_confirmation, parse_turn_commands
from synthesizer import PalaceSynthesizer


def _make_sample_png_bytes(width: int = 32, height: int = 32, color: int = 0xFF3388FF) -> bytes:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(color)
    from PySide6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class _FakeMemory:
    def search(self, query: str):
        return SimpleNamespace(succeeded=False, context="", error=None)


class _StubProvider(AIProvider):
    def __init__(self, name: str, reply_fn):
        self.name = name
        self.reply_fn = reply_fn
        self.calls: list[str] = []

    def generate(self, prompt: str) -> ProviderResponse:
        self.calls.append(prompt)
        return ProviderResponse(text=self.reply_fn(prompt), model=f"{self.name}-test", provider=self.name)


class PipelineAndAutopatchTests(unittest.TestCase):
    def test_autopatch_command_and_typo_variations(self):
        cases = [
            ("deploy and /autopatch", True, "deploy"),
            ("deploy and /authpatch", True, "deploy"),
            ("/autopatch", True, "/autopatch"),
            ("/authpatch", True, "/authpatch"),
            ("/auto-patch", True, "/auto-patch"),
            ("fix the renderer /auto-patch now", True, "fix the renderer"),
            ("make the image renderer faster /autopatch", True, "make the image renderer faster"),
            ("make the image renderer faster /authpatch", True, "make the image renderer faster"),
            ("Please autopatch the experimental notice", True, "Please autopatch the experimental notice"),
            ("apply experimental mode patches", True, "apply experimental mode patches"),
            ("apply staged patch", True, "apply staged patch"),
            ("deploy the patch now", True, "deploy the patch now"),
            ("self-deploy this fix", True, "self-deploy this fix"),
            ("self patch the config", True, "self patch the config"),
            ("can you explain how python functions work?", False, "can you explain how python functions work?"),
        ]
        for raw, exp_ap, exp_clean in cases:
            parsed = parse_turn_commands(raw)
            self.assertEqual(parsed["autopatch"], exp_ap, f"Failed autopatch parse for {raw!r}")
            self.assertEqual(parsed["cleaned_question"], exp_clean, f"Failed clean for {raw!r}")
            if exp_ap:
                self.assertTrue(parsed["include_code"], f"Expected include_code=True for {raw!r}")

        for ok_word in ("Apply", "Proceed", "Go", "Go ahead", "Do it", "Deploy", "Yes", "OK", "Approved"):
            self.assertTrue(is_terse_patch_confirmation(ok_word), ok_word)
        self.assertFalse(is_terse_patch_confirmation("Why did that happen?"))

    def test_provider_loader_forwards_models_and_preserves_defaults(self):
        class FakeCreds:
            def __init__(self, keys):
                self.keys = keys
            def get_api_key(self, name):
                return self.keys.get(name)

        creds = FakeCreds({
            "gemini": "gk",
            "openai": "ok",
            "groq": "grk",
            "mistral": "mk",
            "cerebras": "ck",
            "cohere": "coh",
        })
        cfgs = {
            "gemini": {"enabled": True, "model": "gemini-4-neon"},
            "openai": {"enabled": True, "model": "gpt-5-mini"},
            "groq": {"enabled": True, "model": "llama-3.3-70b-versatile"},
            "mistral": {"enabled": True, "model": "codestral-latest"},
            "cerebras": {"enabled": True, "model": "gpt-oss-120b"},
            "cohere": {"enabled": True, "model": "command-a-03-2025"},
        }
        with patch("provider_loader.GeminiProvider") as mg, \
             patch("provider_loader.OpenAIProvider") as mo, \
             patch("provider_loader.GroqProvider") as mgr, \
             patch("provider_loader.MistralProvider") as mm, \
             patch("provider_loader.CerebrasProvider") as mc, \
             patch("provider_loader.CohereProvider") as mcoh:
            load_configured_providers(creds, provider_configs=cfgs)
            mg.assert_called_once_with(api_key="gk", model="gemini-4-neon")
            mo.assert_called_once_with(api_key="ok", model="gpt-5-mini")
            mgr.assert_called_once_with(api_key="grk", model="llama-3.3-70b-versatile")
            mm.assert_called_once_with(api_key="mk", model="codestral-latest")
            mc.assert_called_once_with(api_key="ck", model="gpt-oss-120b")
            mcoh.assert_called_once_with(api_key="coh", model="command-a-03-2025")

    def test_openai_provider_rejects_empty_thinking_output(self):
        p = OpenAIProvider("k", model="Qwen/Qwen3.8-27B", base_url="https://example.invalid/v1", provider_name="qwen", max_tokens=4096)
        fake_msg = SimpleNamespace(content="", reasoning_content="thinking..." * 50)
        fake_comp = SimpleNamespace(choices=[SimpleNamespace(message=fake_msg, finish_reason="length")])
        p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: fake_comp)))
        with self.assertRaises(RuntimeError) as ctx:
            p.generate("hi")
        self.assertIn("empty output", str(ctx.exception))
        self.assertIn("finish_reason=length", str(ctx.exception))

    def test_drawing_classifier_positive_and_negative_edges(self):
        self.assertEqual(
            classify_drawing_request("I want you to decide what to give me, and make 3 different banners and let me choose the best one. Surprise me."),
            "council_draw",
        )
        self.assertEqual(classify_drawing_request("Make 3 different banners for my Facebook group"), "direct_draw")
        self.assertEqual(classify_drawing_request("draw me a fairy with yellow hair"), "direct_draw")
        self.assertEqual(classify_drawing_request("work on the prompt to make a Facebook banner for Fairybread"), "council_draw")
        self.assertEqual(classify_drawing_request("option 2 in 1640x856"), "direct_draw")
        self.assertEqual(classify_drawing_request("create a fix for the image pipeline"), "none")
        self.assertEqual(classify_drawing_request("make the image renderer faster /autopatch"), "none")
        self.assertEqual(classify_drawing_request("make the image renderer faster /authpatch"), "none")
        self.assertEqual(classify_drawing_request("I need a clean image pipeline patch"), "none")
        self.assertEqual(classify_drawing_request("create a summary of the attached image"), "none")
        self.assertEqual(classify_drawing_request("review the banner layout code in python"), "none")
        self.assertEqual(
            classify_drawing_request(
                'summarize this\n\nATTACHED FILE EXCERPTS (user-provided reference material):\n'
                '[ATTACHED_FILE_META kind="image" name="draw_banner.png" stored="x.png"]'
            ),
            "none",
        )

    def test_two_provider_graphic_duo_and_empty_bubble_skip(self):
        reg = ProviderRegistry()
        calls_by_provider: dict[str, int] = {}
        for name in ("gemini", "openai", "deepseek", "mistral", "groq", "qwen", "cohere", "cerebras"):
            calls_by_provider[name] = 0
            def _mk(n=name):
                def _fn(_p):
                    calls_by_provider[n] += 1
                    if n == "qwen":
                        return "   "
                    return f'[GENERATE_IMAGE prompt="Warm fairy portrait by {n}" title="Draft 1" size="512x512" quality="low"]'
                return _fn
            reg.register(name, _StubProvider(name, _mk()))

        disp = ProviderDispatcher(reg)
        synth_prov = _StubProvider("palace_synth", lambda _p: '[GENERATE_IMAGE prompt="Final merged portrait" title="Draft 1" size="512x512" quality="low"]')
        synth = PalaceSynthesizer("palace_synth", synth_prov, fallback_providers={})
        orch = PalaceOrchestrator(_FakeMemory(), disp, synthesizer=synth)

        with patch("palace_theme.prewarm_generated_images") as mock_prewarm:
            res = orch.run("work on the prompt to make a fairy banner", include_context=False, max_rounds=2)

        dispatched_names = [k for k, v in calls_by_provider.items() if v > 0]
        self.assertEqual(len(dispatched_names), 2)
        self.assertEqual(set(dispatched_names), {"gemini", "openai"})
        self.assertEqual(len(res.peer_rounds), 0)
        mock_prewarm.assert_called_once()

        # Also verify direct draw uses ONLY the 2 specialists (gemini + openai)
        for k in calls_by_provider:
            calls_by_provider[k] = 0
        with patch("palace_theme.prewarm_generated_images"):
            orch.run("draw me a fairy", include_context=False, max_rounds=2)
        dispatched_direct = [k for k, v in calls_by_provider.items() if v > 0]
        self.assertEqual(set(dispatched_direct), {"gemini", "openai"})

        # Explicit "All agents" honors full active pool
        for k in calls_by_provider:
            calls_by_provider[k] = 0
        with patch("palace_theme.prewarm_generated_images"):
            orch.run("All agents work on the prompt to draw a fairy", include_context=False, max_rounds=2)
        dispatched_all = [k for k, v in calls_by_provider.items() if v > 0]
        self.assertEqual(len(dispatched_all), 8)

        # Verify blank outputs are filtered out by synthesizer
        blank_only_res = synth.synthesize(
            "test",
            {
                "qwen": ProviderResult("qwen", response=ProviderResponse(text="   ", provider="qwen")),
                "gemini": ProviderResult("gemini", response=ProviderResponse(text="Real answer", provider="gemini")),
            },
        )
        self.assertEqual(blank_only_res.text, "Real answer")
        self.assertEqual(blank_only_res.contributors, ("gemini",))

    def test_graphics_fallback_and_reference_threading_and_brackets(self):
        tag = '[GENERATE_IMAGE prompt="A sunlit fairy [soft bokeh, golden wings]" title="Fairy"]'
        m = _GENERATE_IMAGE_TAG_PATTERN.search(tag)
        self.assertIsNotNone(m)
        self.assertIn("golden wings]", m.group(1))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ref_path = tmp_dir / "ref_fairy_12345678.png"
            ref_bytes = _make_sample_png_bytes(48, 48, 0xFFFFAA00)
            ref_path.write_bytes(ref_bytes)

            sample_out_bytes = _make_sample_png_bytes(64, 64, 0xFF22CC88)
            seen_urls: list[str] = []
            seen_payloads: list[dict] = []

            class _FakeResp:
                def __init__(self, body_dict):
                    self._raw = json.dumps(body_dict).encode("utf-8")
                def read(self):
                    return self._raw
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False

            def fake_urlopen(req, timeout=60):
                url = req.full_url
                seen_urls.append(url)
                if "gemini-3-pro-image" in url:
                    raise RuntimeError("Simulated primary 503 overload")
                payload = json.loads(req.data.decode("utf-8"))
                seen_payloads.append(payload)
                return _FakeResp({
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(sample_out_bytes).decode("ascii"),
                                }
                            }]
                        }
                    }]
                })

            class FakeCreds:
                def get_api_key(self, name):
                    return "fake-key" if name == "gemini" else None

            gen_dir = tmp_dir / "generated_images"
            gen_dir.mkdir()

            with patch("palace_theme.get_generated_images_dir", return_value=gen_dir), \
                 patch("palace_theme.CredentialStore", return_value=FakeCreds()), \
                 patch("palace_theme.urllib_request.urlopen", side_effect=fake_urlopen):
                out_png = generate_ai_image_to_png(
                    "Warm fairy [golden rim light]",
                    title="RefTest",
                    size="256x256",
                    quality="high",
                    allow_network=True,
                    reference_image_paths=[ref_path],
                    primary_engine="gemini-3-pro-image",
                    fallback_engines=["gemini-3.1-flash-image"],
                )
                self.assertIsNotNone(out_png)
                self.assertTrue(out_png.exists())
                badge = get_image_engine_badge(out_png)
                self.assertIn("gemini-3.1-flash-image", badge)
                self.assertIn("(fallback)", badge)
                self.assertIn("+ref", badge)
                self.assertTrue(any("gemini-3-pro-image" in u for u in seen_urls))
                self.assertTrue(any("gemini-3.1-flash-image" in u for u in seen_urls))
                self.assertGreaterEqual(len(seen_payloads), 1)
                parts0 = seen_payloads[0]["contents"][0]["parts"]
                self.assertIn("inlineData", parts0[0])

                # Verify non-network HTML formatter hits _RECENT_RENDER_MAP for the ref-rendered tag
                html_out = format_markdown_and_drawings(
                    '[GENERATE_IMAGE prompt="Warm fairy [golden rim light]" title="RefTest" size="256x256" quality="high"]'
                )
                self.assertIn("gemini-3.1-flash-image (fallback) +ref", html_out)
                self.assertNotIn("[Image Request", html_out)

    def test_autopatch_diagnostics_and_fake_banner_stripped(self):
        bad_patch = (
            '[IDLE_PATCH file="services/image_pipeline.py" summary="Ghost path"]\n'
            '<<<TARGET\n'
            '===REPLACE\n'
            'print("hi")\n'
            '>>>\n'
            '[/IDLE_PATCH]'
        )
        m = _IDLE_PATCH_PATTERN.search(bad_patch)
        self.assertIsNotNone(m)
        cleaned, applied, _sum = execute_live_autopatches_in_text(bad_patch, author="test")
        self.assertEqual(applied, [])
        self.assertIn("Autopatch Rejected", cleaned)

        reg = ProviderRegistry()
        reg.register(
            "gemini",
            _StubProvider(
                "gemini",
                lambda _p: (
                    '[IDLE_PATCH file="services/image_pipeline.py" summary="Bad"]\n'
                    '<<<TARGET\nfoo\n===REPLACE\nbar\n>>>\n[/IDLE_PATCH]\n\n'
                    '⚡ [AUTOPATCH STAGED: REBOOTING TO CONTINUE NEXT STEP]'
                ),
            ),
        )
        disp = ProviderDispatcher(reg)
        orch = PalaceOrchestrator(_FakeMemory(), disp, synthesizer=PalaceSynthesizer("gemini", reg.get("gemini")))
        res = orch.run("deploy and /authpatch", include_context=False)
        self.assertEqual(res.applied_autopatch_files, [])
        self.assertNotIn("⚡ [AUTOPATCH STAGED", res.final_answer or "")
        self.assertIn("Autopatch", res.final_answer or "")

    def test_graphics_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            loaded = load_graphics_settings(cfg)
            self.assertEqual(loaded["prompt_duo"], DEFAULT_GRAPHICS_SETTINGS["prompt_duo"])
            saved = save_graphics_settings({"prompt_duo": ["openai", "deepseek"]}, cfg)
            self.assertEqual(saved["prompt_duo"], ["openai", "deepseek"])

    def test_extract_attachment_archives_image_on_windows_and_resolves_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            up_dir = tmp_dir / "uploaded_files"
            up_dir.mkdir()
            img_path = tmp_dir / "fairy_sample.png"
            img_path.write_bytes(_make_sample_png_bytes(40, 40, 0xFFFACC15))
            with patch("attachment_service.get_uploaded_files_dir", return_value=up_dir):
                att = extract_attachment(img_path)
                self.assertIsNotNone(att.stored_path)
                self.assertTrue(att.stored_path.exists())
                q = compose_question("portrait keeping palette", [att])
                refs = extract_reference_image_paths(q)
                self.assertEqual(len(refs), 1)
                self.assertTrue(refs[0].exists())

    def test_organic_approval_intent_and_auto_deploy_scoping(self):
        i1 = detect_organic_turn_intents("Run all three. No need to ask for approval.")
        self.assertTrue(i1["auto_approved"])
        self.assertFalse(i1["self_code_change_intent"])

        i2 = detect_organic_turn_intents("Fix the Fairybread settings panel, no need to ask for approval")
        self.assertTrue(i2["auto_approved"])
        self.assertTrue(i2["self_code_change_intent"])

        i3 = detect_organic_turn_intents("What port does HTTPS use? Keep it short.")
        self.assertEqual(i3["output_detail_override"], "concise")

        i4 = detect_organic_turn_intents("Explain the cache architecture in full detail.")
        self.assertEqual(i4["output_detail_override"], "high")

        # Verify orchestrator scoping: auto_deploy promotes Fairybread self-modifications, NOT external C# projects
        seen_prompts: list[str] = []
        reg = ProviderRegistry()
        reg.register("gemini", _StubProvider("gemini", lambda p: (seen_prompts.append(p), "OK")[1]))
        orch = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg), synthesizer=PalaceSynthesizer("gemini", reg.get("gemini")))

        with patch("palace_config.load_agent_defaults", return_value={**DEFAULT_AGENT_DEFAULTS, "approval_policy": "on_request"}):
            seen_prompts.clear()
            orch.run("Fix the Fairybread settings panel, no need to ask for approval", include_context=False)
            self.assertIn("[OPERATOR /AUTOPATCH DIRECTIVE ACTIVE]", seen_prompts[0])

        with patch("palace_config.load_agent_defaults", return_value={**DEFAULT_AGENT_DEFAULTS, "approval_policy": "auto_deploy"}):
            seen_prompts.clear()
            orch.run("Optimize Fairybread's image renderer", include_context=False)
            self.assertIn("[OPERATOR /AUTOPATCH DIRECTIVE ACTIVE]", seen_prompts[0])

            seen_prompts.clear()
            orch.run("Fix my C# WinUI 3 Project Kestrel database lock", include_context=False)
            self.assertNotIn("[OPERATOR /AUTOPATCH DIRECTIVE ACTIVE]", seen_prompts[0])

    def test_agent_defaults_roundtrip_and_control_panel_dialog(self):
        from palace_gui import ManageAIsDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            loaded = load_agent_defaults(cfg)
            self.assertEqual(loaded["approval_policy"], "on_request")
            saved = save_agent_defaults(
                {
                    "approval_policy": "auto_deploy",
                    "output_detail": "concise",
                    "reasoning_summary": "detailed",
                    "synthesizer_mode": "deepseek",
                    "smart_routing": False,
                    "provider_timeout_sec": 60,
                    "straggler_grace_sec": 10,
                },
                cfg,
            )
            self.assertEqual(saved["approval_policy"], "auto_deploy")
            self.assertEqual(saved["output_detail"], "concise")
            self.assertEqual(saved["straggler_grace_sec"], 10)

            dlg = ManageAIsDialog(config_path=cfg, initial_page="Agent Defaults")
            self.assertEqual(dlg.PAGES_COUNT if hasattr(dlg, "PAGES_COUNT") else dlg.nav_list.currentItem().text(), "Agent Defaults")
            self.assertEqual(dlg.ad_approval_combo.currentData(), "auto_deploy")
            self.assertEqual(dlg.ad_output_detail_combo.currentData(), "concise")
            idx_bal = dlg.ad_output_detail_combo.findData("balanced")
            dlg.ad_output_detail_combo.setCurrentIndex(idx_bal)
            dlg.ad_straggler_spin.setValue(18)
            dlg.save_settings()
            dlg.close()

            reloaded = load_agent_defaults(cfg)
            self.assertEqual(reloaded["output_detail"], "balanced")
            self.assertEqual(reloaded["straggler_grace_sec"], 18)
            app.processEvents()

    def test_parallel_prewarm_and_straggler_cutoff(self):
        tags = (
            '[GENERATE_IMAGE prompt="first test scene" title="D1" size="512x512" quality="low"]\n'
            '[GENERATE_IMAGE prompt="second test scene" title="D2" size="512x512" quality="low"]\n'
            '[GENERATE_IMAGE prompt="third test scene" title="D3" size="512x512" quality="low"]'
        )
        def fake_gen(prompt, **kwargs):
            time.sleep(0.32)
            return Path(f"{kwargs.get('title', 'x')}.png")

        t0 = time.monotonic()
        with patch("palace_theme.generate_ai_image_to_png", side_effect=fake_gen):
            out = prewarm_generated_images(tags)
        dt = time.monotonic() - t0
        self.assertEqual([p.name for p in out], ["D1.png", "D2.png", "D3.png"])
        self.assertLess(dt, 0.72)

        # Straggler quorum cutoff in dispatcher
        reg = ProviderRegistry()
        reg.register("fast1", _StubProvider("fast1", lambda p: (time.sleep(0.05), "r1")[1]))
        reg.register("fast2", _StubProvider("fast2", lambda p: (time.sleep(0.05), "r2")[1]))
        reg.register("slow", _StubProvider("slow", lambda p: (time.sleep(4.0), "r3")[1]))
        disp = ProviderDispatcher(reg)
        t0 = time.monotonic()
        res = disp.dispatch("hi", per_provider_timeout=10.0, straggler_grace_seconds=0.2)
        dt2 = time.monotonic() - t0
        self.assertLess(dt2, 0.8)
        self.assertTrue(res["fast1"].succeeded)
        self.assertTrue(res["fast2"].succeeded)
        self.assertFalse(res["slow"].succeeded)
        self.assertIn("straggler cutoff", res["slow"].error or "")

    def test_multimodal_vision_providers_and_graceful_text_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            img_p = Path(tmp) / "vision_sample.png"
            img_p.write_bytes(_make_sample_png_bytes(16, 16, 0xFFFF0000))

            gp = GeminiProvider("gk", model="gemini-4-neon")
            seen_gem: dict = {}
            gp.client = SimpleNamespace(
                models=SimpleNamespace(
                    generate_content=lambda model, contents: (seen_gem.update({"model": model, "contents": contents}), SimpleNamespace(text="Red"))[1]
                )
            )
            gres = gp.generate("What color?", images=[img_p])
            self.assertEqual(gres.text, "Red")
            self.assertEqual(len(seen_gem["contents"]), 2)

            op = OpenAIProvider("ok", model="gpt-5-mini")
            seen_oai: dict = {}
            op.client = SimpleNamespace(
                responses=SimpleNamespace(
                    create=lambda model, input: (seen_oai.update({"model": model, "input": input}), SimpleNamespace(output_text="Red"))[1]
                )
            )
            ores = op.generate("What color?", images=[img_p])
            self.assertEqual(ores.text, "Red")
            self.assertEqual(seen_oai["input"][0]["content"][1]["type"], "input_image")

            # Dispatcher degrades cleanly when a provider's generate(prompt) doesn't accept images=
            reg = ProviderRegistry()
            class TextOnlyProvider(AIProvider):
                def generate(self, prompt: str) -> ProviderResponse:
                    return ProviderResponse(text="text-only-ok", model="t", provider="textonly")
            reg.register("textonly", TextOnlyProvider())
            d_res = ProviderDispatcher(reg).dispatch("hi", images=[img_p])
            self.assertTrue(d_res["textonly"].succeeded)
            self.assertEqual(d_res["textonly"].response.text, "text-only-ok")

    def test_fast_synthesizer_and_smart_intent_routing(self):
        with patch("palace_config.load_agent_defaults", return_value={**DEFAULT_AGENT_DEFAULTS, "synthesizer_mode": "auto_fast"}):
            provs = {
                "gemini": _StubProvider("gemini", lambda _p: "g"),
                "openai": _StubProvider("openai", lambda _p: "o"),
                "deepseek": _StubProvider("deepseek", lambda _p: "d"),
                "cerebras": _StubProvider("cerebras", lambda _p: "c"),
                "cohere": _StubProvider("cohere", lambda _p: "coh"),
            }
            palace = build_palace(provs)
            self.assertEqual(palace.synthesizer.provider_name, "deepseek")

            # Quick factual -> 2 fast providers
            r_quick = palace.run("What port does HTTPS use?", include_context=False, max_rounds=2)
            self.assertEqual(len(r_quick.provider_results), 2)
            self.assertEqual(len(r_quick.peer_rounds), 0)

            # Code -> <= 4 coding specialists
            r_code = palace.run("Debug why this Python SQLite module fails under concurrency", include_context=False, max_rounds=1)
            self.assertLessEqual(len(r_code.provider_results), 4)
            self.assertNotIn("cohere", r_code.provider_results)

            # Explicit "All agents" -> full pool
            r_all = palace.run("All agents answer this: what is 2+2?", include_context=False, max_rounds=1)
            self.assertEqual(len(r_all.provider_results), 5)

    def test_context_service_tail_seek_matches_full_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            sess_path = Path(tmp) / "large_session.jsonl"
            ctx = ContextService(sess_path, session_id="large")
            # Write > 160 KB of history across many exchanges
            pad = "Detailed log padding text for context testing. " * 25
            for i in range(130):
                ctx.append_exchange(
                    f"Question #{i}: {pad[:200]}",
                    f"Final answer #{i}: {pad}",
                    speaker_messages=[
                        {"speaker_id": "gemini", "phase": "initial", "content": f"Draft #{i}: {pad}"},
                    ],
                )
            self.assertGreater(sess_path.stat().st_size, 131_072)
            tail_out = ctx.load_recent(max_chars=4000)
            self.assertIn("Question #129:", tail_out)
            self.assertIn("Final answer #129:", tail_out)
            self.assertNotIn("Draft #129:", tail_out)
            self.assertLessEqual(len(tail_out), 4000)

    def test_voice_settings_warm_american_defaults_and_dialog(self):
        from palace_gui import ManageAIsDialog
        from palace_ouroboros import audit_palace_window_geometry
        from voice_service import load_voice_settings, save_voice_settings

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            defaults = load_voice_settings(cfg)
            self.assertEqual(defaults["tts_engine"], "auto")
            self.assertEqual(defaults["voice_name"], "coral")
            self.assertEqual(defaults["gemini_voice_name"], "Kore")
            self.assertEqual(defaults["voice_style"], "warm_american")
            self.assertEqual(defaults["speech_speed"], 1.0)
            self.assertTrue(defaults["voice_companion_enabled"])
            self.assertTrue(defaults["spoken_summary_for_background"])

            saved = save_voice_settings(
                {
                    "tts_engine": "gemini",
                    "voice_name": "ash",
                    "gemini_voice_name": "Puck",
                    "voice_style": "warm_australian",
                    "custom_style_prompt": "Slightly slower",
                    "speech_speed": 1.15,
                    "voice_companion_enabled": False,
                },
                config_path=cfg,
            )
            self.assertEqual(saved["tts_engine"], "gemini")
            self.assertEqual(saved["gemini_voice_name"], "Puck")
            self.assertEqual(saved["voice_style"], "warm_australian")
            self.assertEqual(saved["speech_speed"], 1.15)
            self.assertFalse(saved["voice_companion_enabled"])

            dlg = ManageAIsDialog(config_path=cfg, initial_page="Voice & Audio")
            dlg.show()
            app.processEvents()
            audit = audit_palace_window_geometry(dlg)
            self.assertEqual(audit["clipped_widget_count"], 0, msg=str(audit.get("clipped_widgets")))
            self.assertEqual(dlg.tts_engine_combo.currentData(), "gemini")
            self.assertEqual(dlg.voice_name_combo.currentData(), "Puck")

            # Switching engine dynamically updates Primary Voice choices to OpenAI voices
            oai_idx = dlg.tts_engine_combo.findData("openai")
            dlg.tts_engine_combo.setCurrentIndex(oai_idx)
            app.processEvents()
            self.assertEqual(dlg.voice_name_combo.currentData(), "ash")

            dlg.voice_style_combo.setCurrentIndex(dlg.voice_style_combo.findData("warm_american"))
            dlg.voice_companion_check.setChecked(True)
            dlg.save_settings()
            dlg.close()

            reloaded = load_voice_settings(cfg)
            self.assertEqual(reloaded["tts_engine"], "openai")
            self.assertEqual(reloaded["voice_name"], "ash")
            self.assertEqual(reloaded["voice_style"], "warm_american")
            self.assertTrue(reloaded["voice_companion_enabled"])
            app.processEvents()

    def test_voice_tts_fallback_chunking_and_speech_cleanup(self):
        from voice_service import clean_text_for_speech, split_text_for_streaming_tts, synthesize_speech_pcm

        # Preserves legacy cleaning behavior while stripping UI banners, patches, and tools
        self.assertEqual(
            clean_text_for_speech('### Hello **Brett**! `[GENERATE_IMAGE prompt="x"]` Visit https://example.com'),
            "Hello Brett ! Visit",
        )
        noisy = (
            "Here is your update.\n"
            "[TOOL: read_source_file file=\"palace_gui.py\" start=1 end=50]\n"
            "[IDLE_PATCH file=\"dispatcher.py\" summary=\"x\"]<<<TARGET\na\n===REPLACE\nb\n>>>[/IDLE_PATCH]\n"
            "| ColA | ColB |\n| --- | --- |\n| 1 | 2 |\n"
            "✓ [ALL TASKS COMPLETED SUCCESSFULLY]"
        )
        cleaned = clean_text_for_speech(noisy)
        self.assertIn("Here is your update.", cleaned)
        self.assertNotIn("IDLE_PATCH", cleaned)
        self.assertNotIn("TOOL:", cleaned)
        self.assertNotIn("ALL TASKS COMPLETED", cleaned)
        self.assertNotIn("---", cleaned)

        # Streaming sentence chunker keeps chunk 1 concise and splits long paragraphs safely
        long_text = (
            "Sentence one is crisp and clear. "
            "Sentence two explains what the background crew started working on right now. "
            + ("Extra detail sentence with additional explanation about audio streaming. " * 6)
        )
        chunks = split_text_for_streaming_tts(long_text, first_chunk_max=120, max_chunk_chars=240)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertLessEqual(len(chunks[0]), 120)
        self.assertTrue(all(len(c) <= 240 for c in chunks[1:]))

        # Fallback test: OpenAI fails -> automatically falls back to Gemini neural PCM
        fake_store = SimpleNamespace(get_api_key=lambda p: {"openai": "sk-test", "gemini": "gk-test"}.get(p))
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            with patch("voice_service._stream_openai_pcm", side_effect=RuntimeError("429 simulated")), \
                 patch("voice_service._synthesize_gemini_pcm", return_value=(b"\x01\x00\x02\x00" * 100, 24000, "gemini-3.8-flash-lite-tts")) as gem_mock:
                pcm, sr, used = synthesize_speech_pcm("Testing fallback", config_path=cfg, credential_store=fake_store)
                self.assertEqual(sr, 24000)
                self.assertEqual(len(pcm), 400)
                self.assertTrue(used.startswith("gemini:"))
                instr_used = (gem_mock.call_args.kwargs.get("instructions") or "").lower()
                self.assertIn("warm, natural", instr_used)
                self.assertIn("american", instr_used)

    def test_voice_companion_chat_delegate_steer_and_status(self):
        from voice_companion import VoiceCompanion

        scripted: list[str] = []

        def fake_llm(prompt: str) -> str:
            return scripted.pop(0)

        vc = VoiceCompanion(llm_callable=fake_llm)

        scripted.append(json.dumps({
            "action": "chat",
            "spoken_reply": "Hey Brett! Doing great — what are we tackling next?",
            "delegated_task": "",
            "steer_note": "",
        }))
        d_chat = vc.respond("Hey there, how are you?", background_busy=False)
        self.assertEqual(d_chat.action, "chat")
        self.assertIn("Brett", d_chat.spoken_reply)

        scripted.append(json.dumps({
            "action": "delegate",
            "spoken_reply": "On it! I just handed those dark navy banner drafts to Gemini and OpenAI. Keep chatting while they build them.",
            "delegated_task": "Draw 3 variations of a minimalist dark navy geometric banner logo",
            "steer_note": "",
        }))
        d_del = vc.respond("Draw me three dark navy banner logo concepts", background_busy=False)
        self.assertEqual(d_del.action, "delegate")
        self.assertIn("navy", d_del.delegated_task.lower())

        scripted.append(json.dumps({
            "action": "steer",
            "spoken_reply": "Got it, telling them to add gold trim right now.",
            "delegated_task": "",
            "steer_note": "Add subtle gold trim accents to all banner variations",
        }))
        d_steer = vc.respond("Tell them to add subtle gold trim", background_busy=True, background_status="Round 1 running")
        self.assertEqual(d_steer.action, "steer")
        self.assertIn("gold trim", d_steer.steer_note.lower())

        scripted.append(json.dumps({
            "action": "status",
            "spoken_reply": "They are rendering the three banner images right now, almost ready.",
            "delegated_task": "",
            "steer_note": "",
        }))
        d_stat = vc.respond("How is it going?", background_busy=True, background_status="Rendering 3 drafts")
        self.assertEqual(d_stat.action, "status")

        scripted.append("Your three banner drafts are ready on screen now — option two has the cleanest navy and gold contrast.")
        summary = vc.summarize_completed_work("Draw banner", "Full markdown [GENERATE_IMAGE prompt=\"x\"] details...", contributors=["gemini", "openai"])
        self.assertIn("banner", summary.lower())
        self.assertNotIn("[GENERATE_IMAGE", summary)

    def test_live_audio_session_antichatter_echo_gate(self):
        from voice_service import LiveAudioSession
        import struct

        class FakeIODevice:
            def __init__(self, data: bytes):
                self._data = data

            def readAll(self) -> bytes:
                out = self._data
                self._data = b""
                return out

        loud_pcm = struct.pack("<800h", *([9000, -9000] * 400))
        seen_levels: list[int] = []
        sess = LiveAudioSession(live_mode=True, on_level=lambda lvl, bars, sp: seen_levels.append(lvl))
        sess.active = True
        sess._io_device = FakeIODevice(loud_pcm)

        # While TTS is speaking, LiveAudioSession drains device but discards echo PCM
        with patch("voice_service.is_speaking", return_value=True):
            sess._poll_audio()
        self.assertEqual(len(sess._pcm_buffer), 0)
        self.assertFalse(sess._speech_detected)
        self.assertEqual(seen_levels[-1], 0)

        # Once TTS finishes, incoming mic PCM records normally
        sess._io_device = FakeIODevice(loud_pcm)
        with patch("voice_service.is_speaking", return_value=False):
            sess._poll_audio()
        self.assertGreater(len(sess._pcm_buffer), 0)
        self.assertGreater(seen_levels[-1], 0)


if __name__ == "__main__":
    unittest.main()
