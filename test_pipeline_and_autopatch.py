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

            dlg_perm = ManageAIsDialog(config_path=cfg, initial_page="AI Access Permissions")
            self.assertEqual(dlg_perm.nav_list.currentItem().text(), "AI Access Permissions")
            self.assertEqual(dlg_perm.perm_mode_combo.currentData(), "turbo")
            dlg_perm.close()

            dlg = ManageAIsDialog(config_path=cfg, initial_page="Agent Defaults")
            self.assertEqual(dlg.nav_list.currentItem().text(), "Agent Defaults")
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

    def test_cost_service_rates_ledger_formatting_and_persistence(self):
        from cost_service import (
            ConversationCostLedger,
            estimate_image_cost_usd,
            estimate_llm_cost_usd,
            estimate_stt_cost_usd,
            estimate_tts_cost_usd,
            format_usd_compact,
        )
        from session_store import SessionStore

        # Per-model pricing & sub-cent vs cent formatting
        c_gem = estimate_llm_cost_usd("gemini", "gemini-4-neon", 1_000_000, 1_000_000)
        self.assertAlmostEqual(c_gem, 3.50, places=4)
        c_mini = estimate_llm_cost_usd("openai", "gpt-5-mini-2026-01", 1000, 500)
        self.assertGreater(c_mini, 0.0)
        self.assertEqual(format_usd_compact(0.0), "~$0.000")
        self.assertEqual(format_usd_compact(0.00084), "~$0.0008")
        self.assertEqual(format_usd_compact(0.0184), "~$0.018")
        self.assertEqual(format_usd_compact(1.425), "~$1.43")

        self.assertAlmostEqual(estimate_tts_cost_usd("openai:gpt-4o-mini-tts", 60.0), 0.015, places=5)
        self.assertEqual(estimate_tts_cost_usd("system:sapi5", 30.0), 0.0)
        self.assertAlmostEqual(estimate_stt_cost_usd("openai:whisper-1", 60.0), 0.006, places=5)
        self.assertAlmostEqual(estimate_image_cost_usd("gemini-3-pro-image"), 0.06, places=5)

        ledger = ConversationCostLedger()
        ledger.record({"kind": "llm", "provider": "deepseek", "model": "deepseek-chat", "input_tokens": 1200, "output_tokens": 300, "cost_usd": 0.00065})
        ledger.record({"kind": "tts", "provider": "openai", "model": "openai:gpt-4o-mini-tts", "duration_sec": 12.0, "cost_usd": 0.003})
        ledger.record({"kind": "stt", "provider": "groq", "model": "groq:whisper-large-v3-turbo", "duration_sec": 10.0, "cost_usd": 0.00011})
        ledger.record({"kind": "image", "provider": "gemini", "model": "gemini-3-pro-image", "cost_usd": 0.06})

        bar = ledger.format_bottom_bar()
        self.assertIn("1.5k", bar)
        self.assertIn("~$0.064", bar)
        tip = ledger.format_tooltip()
        self.assertIn("Voice Audio:", tip)
        self.assertIn("1 render(s)", tip)
        self.assertIn("deepseek", tip)

        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp))
            sid = store.selected
            store.save_cost_ledger(sid, ledger.to_dict())
            reloaded_store = SessionStore(Path(tmp))
            restored = ConversationCostLedger.from_dict(reloaded_store.get_cost_ledger(sid))
            self.assertEqual(restored.total_tokens, 1500)
            self.assertEqual(restored.image_count, 1)
            self.assertAlmostEqual(restored.total_cost_usd, ledger.total_cost_usd, places=6)

    def test_provider_usage_extraction_and_live_bottom_bar_updates(self):
        from cost_service import emit_image_cost, emit_llm_cost, emit_stt_cost, emit_tts_cost
        from PySide6.QtCore import Qt
        from palace_gui import PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore

        # Verify OpenAI & Gemini usage extraction
        op = OpenAIProvider("ok", model="gpt-5-mini")
        op.client = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda model, input: SimpleNamespace(
                    output_text="Hi",
                    usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
                )
            )
        )
        ores = op.generate("Hello")
        self.assertEqual((ores.input_tokens, ores.output_tokens), (1200, 300))

        gp = GeminiProvider("gk", model="gemini-4-neon")
        gp.client = SimpleNamespace(
            interactions=SimpleNamespace(
                create=lambda model, input: SimpleNamespace(
                    output_text="Hi there",
                    usage=SimpleNamespace(input_tokens=900, output_tokens=150),
                )
            )
        )
        gres = gp.generate("Hello")
        self.assertEqual((gres.input_tokens, gres.output_tokens), (900, 150))

        # Verify live PalaceWindow bottom bar updates and per-session persistence
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cfg = tmp_p / "palace_config.json"
            store = SessionStore(tmp_p)
            sid1 = store.selected
            win = PalaceWindow(
                store=store,
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True},
                config_path=cfg,
            )
            win.show()
            app.processEvents()
            self.assertIn("Conv: ~$0.000", win.bottom_token_label.text())

            emit_llm_cost("gemini", "gemini-4-neon", 1200, 300)
            emit_tts_cost("openai:gpt-4o-mini-tts", 12.0)
            emit_stt_cost("groq:whisper-large-v3-turbo", 6.0)
            emit_image_cost("gemini-3-pro-image")
            app.processEvents()

            txt1 = win.bottom_token_label.text()
            self.assertIn("1.5k", txt1)
            self.assertNotIn("~$0.000", txt1)
            tip1 = win.bottom_token_label.toolTip()
            self.assertIn("1,200 in / 300 out", tip1)
            self.assertIn("1 render(s)", tip1)

            audit = audit_palace_window_geometry(win)
            self.assertEqual(audit["clipped_widget_count"], 0, msg=str(audit.get("clipped_widgets")))

            # Creating a new session switches to clean zero ledger; selecting sid1 restores previous ledger
            win.new_conversation()
            app.processEvents()
            self.assertIn("Conv: ~$0.000", win.bottom_token_label.text())

            target_item = next(
                win.session_list.item(i)
                for i in range(win.session_list.count())
                if win.session_list.item(i).data(Qt.ItemDataRole.UserRole) == sid1
            )
            win.change_session(target_item, None)
            app.processEvents()
            self.assertIn("1.5k", win.bottom_token_label.text())
            self.assertNotIn("~$0.000", win.bottom_token_label.text())

            win._force_quit = True
            win.close()
            app.processEvents()

    def test_talk_mode_only_no_delegation_persistence_and_menu_escaping(self):
        from PySide6.QtWidgets import QMenu
        from palace_config import save_provider_config
        from palace_gui import PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore
        from voice_companion import VoiceCompanion

        seen_prompts: list[str] = []

        def _fake_chat(prompt_text: str) -> str:
            seen_prompts.append(prompt_text)
            return "Sounds good, we can just talk through your ideas naturally."

        vc_talk = VoiceCompanion(llm_callable=_fake_chat)
        dec = vc_talk.respond("Please refactor and draw a banner for the code", talk_only=True)
        self.assertEqual(dec.action, "chat")
        self.assertEqual(dec.delegated_task, "")
        self.assertEqual(dec.steer_note, "")
        self.assertTrue(seen_prompts)
        self.assertNotIn("delegated_task", seen_prompts[-1])

        def _raising_llm(_prompt: str) -> str:
            raise RuntimeError("network down")

        vc_err = VoiceCompanion(llm_callable=_raising_llm)
        dec_err = vc_err.respond("Please refactor and draw a banner for the code", talk_only=True)
        self.assertEqual(dec_err.action, "chat")
        self.assertEqual(dec_err.delegated_task, "")

        # Verify Talk Mode Only candidate order prioritizes Groq over DeepSeek and avoids deepseek-reasoner
        with tempfile.TemporaryDirectory() as cfg_tmp:
            cfg_file = Path(cfg_tmp) / "palace_config.json"
            save_provider_config("groq", enabled=True, model="llama-3.3-70b-versatile", config_path=cfg_file)
            save_provider_config("deepseek", enabled=True, model="deepseek-reasoner", config_path=cfg_file)

            class _FakeCredStore:
                def get_api_key(self, name: str) -> str:
                    return {"groq": "gsk_fake", "deepseek": "sk_fake"}.get(name, "")

            vc_order = VoiceCompanion(config_path=cfg_file, credential_store=_FakeCredStore())
            talk_cands = vc_order._build_provider_candidates(talk_only=True)
            talk_names = [pname for pname, _fn in talk_cands]
            self.assertGreaterEqual(len(talk_names), 2)
            self.assertLess(talk_names.index("groq"), talk_names.index("deepseek"))

            used_models: list[str] = []

            class _FakeOpenAI:
                def __init__(self, **_kwargs):
                    self.chat = SimpleNamespace(
                        completions=SimpleNamespace(
                            create=lambda **kw: (
                                used_models.append(kw.get("model", "")),
                                SimpleNamespace(
                                    choices=[SimpleNamespace(message=SimpleNamespace(content="Hi back!"))],
                                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
                                ),
                            )[1]
                        )
                    )

            ds_fn = dict(talk_cands)["deepseek"]
            with patch("openai.OpenAI", _FakeOpenAI):
                out_ds = ds_fn("Hello there")
            self.assertEqual(out_ds, "Hi back!")
            self.assertEqual(used_models, ["deepseek-chat"])

        # Verify PalaceWindow Talk Mode Only UI, typed send, persistence, escalation & menu & escaping
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cfg = tmp_p / "palace_config.json"
            store = SessionStore(tmp_p)
            sid1 = store.selected
            factory_calls = 0

            def _counting_factory(_ctx):
                nonlocal factory_calls
                factory_calls += 1
                return PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry()))

            win = PalaceWindow(
                store=store,
                palace_factory=_counting_factory,
                provider_states={"gemini": True, "deepseek": True},
                config_path=cfg,
            )
            win.show()
            app.processEvents()

            menu = QMenu(win)
            win._populate_profiles_and_ais_menu(menu)
            top_actions = menu.actions()
            self.assertIn("Talk Mode Only", top_actions[0].text())
            self.assertTrue(top_actions[0].isCheckable())

            all_menu_texts: list[str] = []
            for act in top_actions:
                all_menu_texts.append(act.text())
                if act.menu() is not None:
                    for sub_act in act.menu().actions():
                        all_menu_texts.append(sub_act.text())
            joined_texts = "\n".join(all_menu_texts)
            self.assertIn("Graphics && Vision", joined_texts)
            self.assertIn("Custom Selection && How Many AIs", joined_texts)
            self.assertIn("Customize Profiles && Squads", joined_texts)
            self.assertIn("Manage AI Keys, Models && Tools", joined_texts)

            win._activate_talk_only_mode(auto_start_live_voice=False)
            app.processEvents()
            self.assertTrue(win._talk_only_mode)
            self.assertEqual(win.ai_pill_button.text(), "🎙️ Talk Only  ▾")
            self.assertIn("Talk Mode Only", win.ai_pill_button.toolTip())
            self.assertEqual(win.provider_states, {"gemini": True, "deepseek": True})

            audit = audit_palace_window_geometry(win)
            self.assertEqual(audit["clipped_widget_count"], 0, msg=str(audit.get("clipped_widgets")))

            win._voice_companion = VoiceCompanion(
                llm_callable=lambda _p: "Sure thing, let's keep chatting casually."
            )
            win.composer.setPlainText("Hey, let's just brainstorm for a minute.")
            win.send_message()

            deadline = time.monotonic() + 5.0
            while win._voice_threads and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.02)
            app.processEvents()

            self.assertEqual(factory_calls, 0)
            saved_msgs = store.messages(sid1)
            self.assertTrue(
                any(m.get("speaker_id") == "voice_companion" and "keep chatting casually" in m.get("content", "") for m in saved_msgs),
                msg=f"Expected voice_companion message in store: {saved_msgs}",
            )

            win.load_history()
            app.processEvents()
            self.assertIn("keep chatting casually", win.chat.toHtml())
            self.assertNotIn("voice_companion", win.conversation_contributors)

            # Switching mode via squad preset or toggling another AI exits Talk Mode Only while keeping context
            win._apply_squad_preset("🛠 Work Mode", ["deepseek", "gemini"], deliberate=True)
            app.processEvents()
            self.assertFalse(win._talk_only_mode)

            win._activate_talk_only_mode(auto_start_live_voice=False)
            self.assertTrue(win._talk_only_mode)
            win._toggle_provider_quick("openai", True)
            app.processEvents()
            self.assertFalse(win._talk_only_mode)

            ctx_txt = store.context(sid1).load_recent()
            self.assertIn("brainstorm for a minute", ctx_txt)
            self.assertIn("keep chatting casually", ctx_txt)

            for vw in list(win._voice_threads):
                vw.wait(1000)
            win._force_quit = True
            win.close()
            app.processEvents()

    def test_bare_draft_pick_verbose_pass_failover_and_deterministic_master_upgrade(self):
        prior_ctx = (
            "USER: Draw me an alien sunflower, 3 drafts.\n\n"
            "ASSISTANT: Here are three 512x512 drafts:\n"
            '[GENERATE_IMAGE prompt="A glowing macro alien sunflower with cyan veins" title="Draft 1 - Bioluminescent Macro" size="512x512" quality="low"]\n'
            '[GENERATE_IMAGE prompt="Whole tall alien sunflower in jungle clearing" title="Draft 2 - Whole Plant" size="512x512" quality="low"]\n'
            '[GENERATE_IMAGE prompt="Wide alien sunflower field panorama at sunrise" title="Draft 3 - Panorama" size="512x512" quality="low"]\n'
            "⏸ [PAUSED — WAITING FOR USER INPUT: which draft (1/2/3)]"
        )

        class _CountingFailThenSucceedProvider(AIProvider):
            def __init__(self, name: str, outcomes: list[str | Exception]):
                self.name = name
                self._outcomes = list(outcomes)
                self.calls: list[str] = []

            def generate(self, prompt: str) -> ProviderResponse:
                self.calls.append(prompt)
                idx = min(len(self.calls) - 1, len(self._outcomes) - 1)
                val = self._outcomes[idx]
                if isinstance(val, Exception):
                    raise val
                return ProviderResponse(text=val, model=f"{self.name}-test", provider=self.name)

        # Subtest A: Bare "1" classified as direct_draw -> Gemini fails once transiently, succeeds on 1 graphics retry
        reg_a = ProviderRegistry()
        gem_a = _CountingFailThenSucceedProvider(
            "gemini",
            [
                RuntimeError("503 Service Unavailable"),
                '[GENERATE_IMAGE prompt="Sunflower Draft 1 High-Res Master" title="Alien Sunflower Master" size="1024x1024" quality="high"]',
            ],
        )
        oai_a = _CountingFailThenSucceedProvider("openai", [RuntimeError("503 Service Unavailable")])
        ds_a = _StubProvider("deepseek", lambda _p: "[PASS] — Handing over for the 1024x1024 master.")
        reg_a.register("gemini", gem_a)
        reg_a.register("openai", oai_a)
        reg_a.register("deepseek", ds_a)
        synth_a = PalaceSynthesizer("palace_synth", _StubProvider("palace_synth", lambda p: p), fallback_providers={})

        class _StaticCtx:
            session_id = "sunflower_test"
            def load_recent(self, max_chars: int = 12000):
                return prior_ctx
            def append_exchange(self, *args, **kwargs):
                return ("q1", "a1")

        orch_a = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg_a), synthesizer=synth_a, context_service=_StaticCtx())
        with patch("palace_theme.prewarm_generated_images") as mock_prewarm_a:
            res_a = orch_a.run(
                "1",
                provider_names=["gemini", "openai", "deepseek"],
                include_context=True,
                save_to_context=False,
                max_rounds=2,
            )
        self.assertEqual(len(gem_a.calls), 2)
        self.assertIn("[GRAPHICS RETRY]", gem_a.calls[1])
        self.assertEqual(len(ds_a.calls), 0)
        self.assertIn("[GENERATE_IMAGE", res_a.final_answer or "")
        self.assertIn("Sunflower Draft 1 High-Res Master", res_a.final_answer or "")
        mock_prewarm_a.assert_called_once()

        # Subtest B: Both graphic specialists fail + DeepSeek returns verbose [PASS] -> deterministic Draft 1 high-res upgrade
        reg_b = ProviderRegistry()
        gem_b = _CountingFailThenSucceedProvider("gemini", [RuntimeError("503 retry fail"), RuntimeError("503 second fail")])
        oai_b = _CountingFailThenSucceedProvider("openai", [RuntimeError("503 oai fail")])
        ds_b = _StubProvider(
            "deepseek",
            lambda _p: "[PASS] — The user's '1' is a draft selection. Handing over for the 1024x1024 master.",
        )
        reg_b.register("gemini", gem_b)
        reg_b.register("openai", oai_b)
        reg_b.register("deepseek", ds_b)
        synth_b = PalaceSynthesizer(
            "palace_synth",
            _StubProvider("palace_synth", lambda _p: "UNEXPECTED_SYNTH_CALL"),
            fallback_providers={},
        )
        orch_b = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg_b), synthesizer=synth_b, context_service=_StaticCtx())
        with patch("palace_theme.prewarm_generated_images") as mock_prewarm_b:
            res_b = orch_b.run(
                "1",
                provider_names=["gemini", "openai", "deepseek"],
                include_context=True,
                save_to_context=False,
                max_rounds=2,
            )
        self.assertEqual(len(gem_b.calls), 2)
        self.assertEqual(len(ds_b.calls), 1)
        ans_b = res_b.final_answer or ""
        self.assertIn("A glowing macro alien sunflower with cyan veins", ans_b)
        self.assertIn('size="1024x1024"', ans_b)
        self.assertIn('quality="high"', ans_b)
        self.assertNotIn("[PASS]", ans_b)
        mock_prewarm_b.assert_called_once()

        # Non-drawing turns must NOT retry on errors, but DO fail over cleanly when peers only [PASS]
        reg_c = ProviderRegistry()
        ds_c = _CountingFailThenSucceedProvider("deepseek", ["[PASS] — Outside my specialty."])
        gem_c = _CountingFailThenSucceedProvider("gemini", [RuntimeError("503 temporary")])
        oai_c = _StubProvider("openai", lambda _p: "Direct real answer from OpenAI failover.")
        reg_c.register("deepseek", ds_c)
        reg_c.register("gemini", gem_c)
        reg_c.register("openai", oai_c)
        synth_c = PalaceSynthesizer("palace_synth", _StubProvider("palace_synth", lambda p: p), fallback_providers={})
        orch_c = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg_c), synthesizer=synth_c)
        res_c = orch_c.run("Briefly explain photosynthetic quantum efficiency", provider_names=["deepseek", "gemini", "openai"], include_context=False, max_rounds=1)
        self.assertEqual(len(ds_c.calls), 1)
        self.assertEqual(len(gem_c.calls), 1)
        self.assertEqual(len(oai_c.calls), 1)
        self.assertIn("Direct real answer from OpenAI failover.", res_c.final_answer or "")

    def test_primary_image_engine_retries_once_before_downgrading_to_fallback(self):
        sample_png = _make_sample_png_bytes(64, 64, 0xFF33AA55)

        class _FakeResp:
            def __init__(self, body_dict):
                self._raw = json.dumps(body_dict).encode("utf-8")
            def read(self):
                return self._raw
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        class _FakeCreds:
            def get_api_key(self, name):
                return "fake-key" if name == "gemini" else None

        def _ok_body():
            return {
                "candidates": [{
                    "content": {
                        "parts": [{
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(sample_png).decode("ascii"),
                            }
                        }]
                    }
                }]
            }

        with tempfile.TemporaryDirectory() as tmp:
            gen_dir = Path(tmp) / "generated_images"
            gen_dir.mkdir()

            # Case 1: Transient 503 on primary attempt 1 -> retries primary ONCE and succeeds without downgrading
            seen_case1: list[str] = []

            def fake_urlopen_retry_ok(req, timeout=75):
                url = req.full_url
                seen_case1.append(url)
                if "gemini-3-pro-image" in url and seen_case1.count(url) == 1:
                    raise RuntimeError("HTTP Error 503: Service Unavailable")
                return _FakeResp(_ok_body())

            with patch("palace_theme.get_generated_images_dir", return_value=gen_dir), \
                 patch("palace_theme.CredentialStore", return_value=_FakeCreds()), \
                 patch("palace_theme.urllib_request.urlopen", side_effect=fake_urlopen_retry_ok):
                out1 = generate_ai_image_to_png(
                    "Retry case 1 unique cosmic bloom prompt",
                    title="RetryPrimaryOK",
                    size="256x256",
                    quality="high",
                    allow_network=True,
                    primary_engine="gemini-3-pro-image",
                    fallback_engines=["gemini-3.1-flash-image"],
                    primary_retry_delay_sec=0.0,
                )
            self.assertIsNotNone(out1)
            self.assertEqual(sum(1 for u in seen_case1 if "gemini-3-pro-image" in u), 2)
            self.assertEqual(sum(1 for u in seen_case1 if "gemini-3.1-flash-image" in u), 0)
            badge1 = get_image_engine_badge(out1)
            self.assertEqual(badge1, "gemini-3-pro-image")

            # Case 2: Permanent 403 Forbidden -> skips retry and falls back immediately
            seen_case2: list[str] = []

            def fake_urlopen_perm_err(req, timeout=75):
                url = req.full_url
                seen_case2.append(url)
                if "gemini-3-pro-image" in url:
                    raise RuntimeError("HTTP Error 403: Forbidden")
                return _FakeResp(_ok_body())

            with patch("palace_theme.get_generated_images_dir", return_value=gen_dir), \
                 patch("palace_theme.CredentialStore", return_value=_FakeCreds()), \
                 patch("palace_theme.urllib_request.urlopen", side_effect=fake_urlopen_perm_err):
                out2 = generate_ai_image_to_png(
                    "Retry case 2 permanent error prompt",
                    title="PermNoRetry",
                    size="256x256",
                    quality="high",
                    allow_network=True,
                    primary_engine="gemini-3-pro-image",
                    fallback_engines=["gemini-3.1-flash-image"],
                    primary_retry_delay_sec=0.0,
                )
            self.assertIsNotNone(out2)
            self.assertEqual(sum(1 for u in seen_case2 if "gemini-3-pro-image" in u), 1)
            self.assertEqual(sum(1 for u in seen_case2 if "gemini-3.1-flash-image" in u), 1)
            badge2 = get_image_engine_badge(out2)
            self.assertIn("(fallback)", badge2)

    def test_access_policy_modes_and_exclusion_subdirs_override_turbo(self):
        from access_policy import (
            evaluate_command_access,
            evaluate_path_access,
            load_access_permissions,
            save_access_permissions,
        )

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            init_ap = load_access_permissions(cfg)
            self.assertEqual(init_ap["permission_mode"], "default")
            self.assertEqual(init_ap["write_exclusions"], [])

            # Set mode to Turbo with non-recursive C:\ & E:\ and recursive M:\
            save_access_permissions(
                {
                    "permission_mode": "turbo",
                    "write_exclusions": [
                        {"path": "C:\\", "include_subdirs": False},
                        {"path": "E:\\", "include_subdirs": False},
                        {"path": "M:\\", "include_subdirs": True},
                    ],
                },
                config_path=cfg,
            )

            # Root-only C:\ & E:\ protect root items even in Turbo, while allowing subdirs
            c_root = evaluate_path_access(r"C:\boot.txt", "write", config_path=cfg)
            self.assertEqual((c_root.decision, c_root.excluded), ("ask", True))
            c_sub = evaluate_path_access(r"C:\Palace_Live\palace_gui.py", "write", config_path=cfg)
            self.assertEqual((c_sub.decision, c_sub.excluded), ("allow", False))

            e_root = evaluate_path_access(r"E:\root.txt", "delete", config_path=cfg)
            self.assertEqual((e_root.decision, e_root.excluded), ("ask", True))
            e_sub = evaluate_path_access(r"E:\Visual_studio\Palace\foo.py", "write", config_path=cfg)
            self.assertEqual((e_sub.decision, e_sub.excluded), ("allow", False))

            # Recursive M:\ catches direct files, deeply nested trees, .. traversal & shell commands even in Turbo
            m_direct = evaluate_path_access(r"M:\file.txt", "write", config_path=cfg)
            self.assertEqual((m_direct.decision, m_direct.excluded), ("ask", True))
            m_nested = evaluate_path_access(r"M:\BACK_UP E DRIVE\nested\data.bin", "write", config_path=cfg)
            self.assertEqual((m_nested.decision, m_nested.excluded), ("ask", True))
            m_trav = evaluate_path_access(r"M:\sub\..\secret.txt", "patch", config_path=cfg)
            self.assertEqual((m_trav.decision, m_trav.excluded), ("ask", True))

            cmd_m = evaluate_command_access(r"Remove-Item M:\backup\file.txt", cwd=r"E:\Visual_studio", config_path=cfg)
            self.assertEqual((cmd_m.decision, cmd_m.excluded), ("ask", True))

            cmd_e_proj = evaluate_command_access("python -m unittest", cwd=r"E:\Visual_studio\Palace", config_path=cfg)
            self.assertEqual((cmd_e_proj.decision, cmd_e_proj.excluded), ("allow", False))

            # Verify mode behavior on unprotected paths across request_review, default, auto, turbo
            unprot = {"write_exclusions": []}
            self.assertEqual(evaluate_path_access(r"E:\proj\a.py", "write", permissions={**unprot, "permission_mode": "request_review"}).decision, "ask")
            self.assertEqual(evaluate_path_access(r"E:\proj\a.py", "write", permissions={**unprot, "permission_mode": "default"}).decision, "ask")
            self.assertEqual(evaluate_path_access(r"E:\proj\a.py", "write", permissions={**unprot, "permission_mode": "auto"}).decision, "allow")
            self.assertEqual(evaluate_path_access(r"E:\proj\a.py", "delete", permissions={**unprot, "permission_mode": "auto"}).decision, "ask")
            self.assertEqual(evaluate_command_access("git push origin main", permissions={**unprot, "permission_mode": "auto"}).decision, "ask")
            self.assertEqual(evaluate_command_access("python -m pytest", permissions={**unprot, "permission_mode": "auto"}).decision, "allow")
            self.assertEqual(evaluate_path_access(r"E:\proj\a.py", "delete", permissions={**unprot, "permission_mode": "turbo"}).decision, "allow")

    def test_workspace_tools_exclusion_approval_ui_and_zero_clipping(self):
        from PySide6.QtCore import Qt
        from access_policy import PERMISSION_MODES, load_access_permissions
        from palace_gui import ManageAIsDialog, PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore
        from workspace_tools import execute_approved_action, process_workspace_actions_in_text

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "palace_config.json"
            work_dir = root / "work_proj"
            work_dir.mkdir()
            prot_dir = root / "protected_vault"
            prot_dir.mkdir()

            perms = {
                "permission_mode": "turbo",
                "write_exclusions": [{"path": str(prot_dir), "include_subdirs": True}],
                "allow_workspace_writes": True,
                "allow_shell_commands": True,
            }

            agent_reply = (
                f'[FILE_WRITE path="{work_dir / "hello.py"}" summary="Create helper"]\n'
                "<<<CONTENT\nvalue = 1\n>>>\n[/FILE_WRITE]\n"
                f'[FILE_PATCH path="{work_dir / "hello.py"}" summary="Bump helper"]\n'
                "<<<TARGET\nvalue = 1\n===REPLACE\nvalue = 42\n>>>\n[/FILE_PATCH]\n"
                f'[FILE_WRITE path="{prot_dir / "secret.txt"}" summary="Write excluded file"]\n'
                "<<<CONTENT\nlocked-write\n>>>\n[/FILE_WRITE]"
            )

            executed, pending, _md = process_workspace_actions_in_text(
                agent_reply,
                project_folder=str(work_dir),
                config_path=cfg,
                permissions=perms,
            )
            self.assertEqual(len(executed), 2)
            self.assertEqual((work_dir / "hello.py").read_text(encoding="utf-8"), "value = 42")
            self.assertEqual(len(pending), 1)
            self.assertTrue(pending[0]["excluded"])
            self.assertFalse((prot_dir / "secret.txt").exists())

            ok_app, _msg_app = execute_approved_action(pending[0])
            self.assertTrue(ok_app)
            self.assertEqual((prot_dir / "secret.txt").read_text(encoding="utf-8"), "locked-write")

            # Verify AI Access Permissions UI has zero leaked internal strings & saves unlimited exclusions cleanly
            app = QApplication.instance() or QApplication([])
            dlg = ManageAIsDialog(config_path=cfg, initial_page="AI Access Permissions")
            self.assertEqual(dlg.nav_list.currentItem().text(), "AI Access Permissions")
            labels_text = "\n".join(
                getattr(lbl, "text", lambda: "")()
                for lbl in dlg.findChildren(type(dlg.perm_mode_desc_label))
            ) + "\n" + "\n".join(chk.text() for chk in dlg.tool_checks.values())
            for leaked in ("E: protected", "Tier 1 Sandbox", "M: blocked", r"C:\Palace_Idle_Sandbox"):
                self.assertNotIn(leaked, labels_text)

            dlg._add_exclusion_row("E:\\", include_subdirs=False)
            dlg._add_exclusion_row("M:\\", include_subdirs=True)
            dlg.save_settings()
            dlg.close()

            reloaded = load_access_permissions(cfg)
            self.assertEqual(
                reloaded["write_exclusions"],
                [
                    {"path": "E:\\", "include_subdirs": False},
                    {"path": "M:\\", "include_subdirs": True},
                ],
            )

            # Verify PalaceWindow permission pill geometry across all 4 modes + inline approval banner
            store = SessionStore(root / "sessions")
            win = PalaceWindow(
                store=store,
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True, "deepseek": True},
                config_path=cfg,
            )
            win.show()
            app.processEvents()

            for mk in PERMISSION_MODES:
                win._set_permission_mode_quick(mk)
                app.processEvents()
                audit = audit_palace_window_geometry(win)
                self.assertEqual(audit["clipped_widget_count"], 0, msg=f"Clipped on mode={mk}: {audit.get('clipped_widgets')}")

            # Pending action banner shows exclusion notice and Approve executes on click
            target_after_approve = prot_dir / "approved_banner.txt"
            self.assertFalse(target_after_approve.exists())
            win._show_pending_actions_banner([
                {
                    "id": "act-1",
                    "kind": "file_write",
                    "path": str(target_after_approve),
                    "cwd": str(prot_dir),
                    "summary": "Write after UI approve",
                    "preview": f"Write `{target_after_approve}`",
                    "excluded": True,
                    "reason": "Protected by Write Exclusion List",
                    "payload": {"content": "banner-ok"},
                }
            ])
            app.processEvents()
            self.assertTrue(win.approval_banner.isVisible())
            win.approve_actions_btn.click()
            app.processEvents()
            self.assertFalse(win.approval_banner.isVisible())
            self.assertEqual(target_after_approve.read_text(encoding="utf-8"), "banner-ok")

            win._force_quit = True
            win.close()
            app.processEvents()

    def test_external_bridge_mcp_stdio_python_fix_toml_json_and_recursion_guard(self):
        import tomllib
        from fairybread_mcp import (
            execute_bridge_tool,
            get_mcp_server_entry,
            get_platform_copy_snippet,
            install_antigravity_bridge,
            install_claude_desktop_bridge,
            install_codex_bridge,
            install_grok_bridge,
            is_mcp_server_registered,
            resolve_console_python_executable,
            save_bridge_settings,
            test_mcp_bridge_live,
            uninstall_antigravity_bridge,
            uninstall_claude_desktop_bridge,
            uninstall_codex_bridge,
            uninstall_grok_bridge,
        )
        from local_cli_provider import LocalCLIProvider

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            py_dir = root / "pybin"
            py_dir.mkdir()
            py_exe = py_dir / "python.exe"
            pyw_exe = py_dir / "pythonw.exe"
            py_exe.write_text("", encoding="utf-8")
            pyw_exe.write_text("", encoding="utf-8")
            self.assertEqual(Path(resolve_console_python_executable(str(pyw_exe))), py_exe)

            fake_entry = get_mcp_server_entry(
                python_exe=str(pyw_exe),
                script_path=Path(__file__).with_name("fairybread_mcp.py"),
            )
            self.assertEqual(Path(fake_entry["command"]), py_exe)
            self.assertIn("[mcp_servers.fairybread]", get_platform_copy_snippet("codex"))
            self.assertIn('"mcpServers"', get_platform_copy_snippet("antigravity"))

            temp_home = root / "home"
            temp_appdata = root / "appdata"

            # 1) Codex / ChatGPT Desktop TOML merge + preserve existing sections + .bak + clean unlink
            codex_toml = temp_home / ".codex" / "config.toml"
            codex_toml.parent.mkdir(parents=True)
            codex_toml.write_text(
                '[desktop]\ntheme = "dark"\n\n[mcp_servers.node_repl]\ncommand = \'node.exe\'\nargs = []\n',
                encoding="utf-8",
            )
            ok, _msg = install_codex_bridge(home_dir=temp_home, entry=fake_entry)
            self.assertTrue(ok)
            self.assertTrue((codex_toml.parent / "config.toml.fairybread.bak").exists())
            parsed_toml = tomllib.loads(codex_toml.read_text(encoding="utf-8"))
            self.assertIn("node_repl", parsed_toml["mcp_servers"])
            self.assertIn("fairybread", parsed_toml["mcp_servers"])
            self.assertEqual(parsed_toml["desktop"]["theme"], "dark")
            self.assertTrue(is_mcp_server_registered("codex", home_dir=temp_home, appdata_dir=temp_appdata))

            ok, _msg = uninstall_codex_bridge(home_dir=temp_home)
            self.assertTrue(ok)
            parsed_after = tomllib.loads(codex_toml.read_text(encoding="utf-8"))
            self.assertIn("node_repl", parsed_after["mcp_servers"])
            self.assertNotIn("fairybread", parsed_after["mcp_servers"])
            self.assertFalse(is_mcp_server_registered("codex", home_dir=temp_home, appdata_dir=temp_appdata))

            # 2) Antigravity JSON merge (preserving existing rea) + SKILL.md + clean unlink
            ag_json = temp_home / ".gemini" / "config" / "mcp_config.json"
            ag_json.parent.mkdir(parents=True)
            ag_json.write_text(json.dumps({"mcpServers": {"rea": {"command": "cmd.exe"}}}, indent=2), encoding="utf-8")
            ok, _msg = install_antigravity_bridge(home_dir=temp_home, entry=fake_entry)
            self.assertTrue(ok)
            skill_md = temp_home / ".gemini" / "config" / "skills" / "fairybread-council" / "SKILL.md"
            self.assertTrue(skill_md.exists())
            ag_data = json.loads(ag_json.read_text(encoding="utf-8"))
            self.assertIn("rea", ag_data["mcpServers"])
            self.assertIn("fairybread", ag_data["mcpServers"])

            ok, _msg = uninstall_antigravity_bridge(home_dir=temp_home)
            self.assertTrue(ok)
            ag_after = json.loads(ag_json.read_text(encoding="utf-8"))
            self.assertIn("rea", ag_after["mcpServers"])
            self.assertNotIn("fairybread", ag_after["mcpServers"])
            self.assertFalse(skill_md.exists())

            # 3) Grok & Claude Desktop merge + clean unlink
            ok, _ = install_grok_bridge(home_dir=temp_home, entry=fake_entry)
            self.assertTrue(ok)
            self.assertTrue(is_mcp_server_registered("grok", home_dir=temp_home, appdata_dir=temp_appdata))
            ok, _ = uninstall_grok_bridge(home_dir=temp_home)
            self.assertTrue(ok)
            self.assertFalse(is_mcp_server_registered("grok", home_dir=temp_home, appdata_dir=temp_appdata))

            ok, _ = install_claude_desktop_bridge(appdata_dir=temp_appdata, entry=fake_entry)
            self.assertTrue(ok)
            self.assertTrue(is_mcp_server_registered("claude", home_dir=temp_home, appdata_dir=temp_appdata))
            ok, _ = uninstall_claude_desktop_bridge(appdata_dir=temp_appdata)
            self.assertTrue(ok)
            self.assertFalse(is_mcp_server_registered("claude", home_dir=temp_home, appdata_dir=temp_appdata))

            # 4) Real stdio JSON-RPC handshake test
            live_ok, live_msg = test_mcp_bridge_live(script_path=Path(__file__).with_name("fairybread_mcp.py"))
            self.assertTrue(live_ok, msg=live_msg)

            # 5) Recursion guard blocks re-entrant MCP calls and LocalCLIProvider execution
            cfg = root / "cfg.json"
            save_bridge_settings({"enabled": True}, config_path=cfg)
            with patch.dict(os.environ, {"FAIRYBREAD_MCP_DEPTH": "1"}):
                blocked = execute_bridge_tool("fairybread_ask_council", {"question": "loop"}, config_path=cfg)
                self.assertIn("error", blocked)
                self.assertIn("FAIRYBREAD_MCP_DEPTH", blocked["error"])
                with self.assertRaises(RuntimeError):
                    LocalCLIProvider("codex", cli_path="codex").generate("hello")

            # 6) Output parsing for Grok JSON and plain text
            grok_cli = LocalCLIProvider("grok", cli_path="grok")
            self.assertEqual(grok_cli.parse_output('{"result": "Grok JSON answer"}'), "Grok JSON answer")
            self.assertEqual(grok_cli.parse_output('{"text": "part1"}\n{"text": "part2"}'), "part1\npart2")
            self.assertEqual(grok_cli.parse_output("Plain text reply"), "Plain text reply")

    def test_external_bridge_ui_interlock_guide_and_zero_clipping(self):
        import tomllib
        from access_policy import PERMISSION_MODES
        from bootstrap import build_palace
        from dispatcher import ProviderDispatcher
        from fairybread_mcp import load_bridge_settings, save_bridge_settings
        from orchestrator import PalaceOrchestrator
        from palace_gui import ManageAIsDialog, PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from provider_registry import ProviderRegistry
        from session_store import SessionStore

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config.json"
            temp_home = root / "home"
            temp_appdata = root / "appdata"
            (temp_home / ".codex").mkdir(parents=True)
            save_bridge_settings({"enabled": True}, config_path=cfg)

            # Pretend codex CLI is installed so both switches start unlocked for testing
            with patch("local_cli_provider.find_cli_binary", side_effect=lambda pk, **kw: ("codex.exe" if pk == "codex" else None)):
                dlg = ManageAIsDialog(
                    config_path=cfg,
                    initial_page="External Agent Bridge (MCP)",
                    bridge_home_dir=temp_home,
                    bridge_appdata_dir=temp_appdata,
                )
                app.processEvents()

                self.assertFalse(hasattr(dlg, "bridge_code_upgrade_check"))
                guide_txt = dlg.bridge_guide_label.text()
                self.assertIn("Foreman Mode", guide_txt)
                self.assertIn("Council Member Mode", guide_txt)

                ctrls = dlg.bridge_platform_controls["codex"]
                foreman_chk = ctrls["foreman"]
                council_chk = ctrls["council"]

                self.assertFalse(foreman_chk.isChecked())
                self.assertFalse(council_chk.isChecked())
                self.assertTrue(foreman_chk.isEnabled())
                self.assertTrue(council_chk.isEnabled())

                # Turn Foreman ON -> writes temp config.toml & disables Council Member
                foreman_chk.setChecked(True)
                app.processEvents()
                self.assertFalse(council_chk.isEnabled())
                self.assertFalse(council_chk.isChecked())
                codex_toml = temp_home / ".codex" / "config.toml"
                self.assertTrue(codex_toml.exists())
                self.assertIn("fairybread", tomllib.loads(codex_toml.read_text(encoding="utf-8"))["mcp_servers"])

                # Turn Foreman OFF -> cleanly unlinks config.toml & unlocks Council Member
                foreman_chk.setChecked(False)
                app.processEvents()
                self.assertTrue(council_chk.isEnabled())
                self.assertNotIn("fairybread", (tomllib.loads(codex_toml.read_text(encoding="utf-8")) if codex_toml.read_text(encoding="utf-8").strip() else {}).get("mcp_servers", {}))

                # Turn Council Member ON -> disables Foreman Mode and persists via save_settings()
                council_chk.setChecked(True)
                app.processEvents()
                self.assertFalse(foreman_chk.isEnabled())
                self.assertFalse(foreman_chk.isChecked())

                dlg.save_settings()
                saved = load_bridge_settings(cfg)
                self.assertEqual(saved["platforms"]["codex"], "council")

                # Turn Council Member OFF -> unlocks Foreman Mode again
                council_chk.setChecked(False)
                app.processEvents()
                self.assertTrue(foreman_chk.isEnabled())
                dlg.close()
                app.processEvents()

            class _FakeMemory:
                def build_prompt_context(self, _q):
                    return ""

            win = PalaceWindow(
                store=SessionStore(root / "sessions"),
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True, "deepseek": True},
                config_path=cfg,
            )
            win.show()
            app.processEvents()
            audit = audit_palace_window_geometry(win)
            self.assertEqual(audit["clipped_widget_count"], 0, msg=f"Clipped widgets: {audit.get('clipped_widgets')}")
            win._force_quit = True
            win.close()
            app.processEvents()

    def test_catalog_sync_rates_models_version_compare_and_sha256_verify(self):
        import hashlib
        import cost_service
        from catalog_sync import (
            compare_versions,
            download_and_verify_installer,
            sync_remote_catalog,
            validate_catalog_payload,
        )
        from palace_config import PROVIDER_CATALOG, save_ui_settings
        from palace_gui import PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore

        self.assertEqual(compare_versions("0.9.1", "0.9.1a"), -1)
        self.assertEqual(compare_versions("0.9.1g", "0.9.1h"), -1)
        self.assertEqual(compare_versions("0.9.1g", "0.92"), -1)
        self.assertEqual(compare_versions("0.92", "0.93"), -1)
        self.assertEqual(compare_versions("v0.9.1g", "0.9.1g"), 0)
        self.assertEqual(compare_versions("0.9.2", "0.9.1z"), 1)

        bad_payload = {
            "latest_app_version": "0.9.1h",
            "download_url": "http://insecure.example.com/setup.zip",
            "installer_sha256": "not-a-sha",
            "model_token_rates_per_1m": {"bad-neg": [-1.0, 2.0], "good-m": [0.42, 1.25]},
            "unknown_code_hook": "rm -rf /",
        }
        cleaned = validate_catalog_payload(bad_payload)
        self.assertEqual(cleaned["download_url"], "")
        self.assertEqual(cleaned["installer_sha256"], "")
        self.assertNotIn("unknown_code_hook", cleaned)
        self.assertNotIn("bad-neg", cleaned["model_token_rates_per_1m"])
        self.assertEqual(cleaned["model_token_rates_per_1m"]["good-m"], (0.42, 1.25))

        orig_rates = dict(cost_service.MODEL_TOKEN_RATES_PER_1M)
        orig_openai_meta = json.loads(json.dumps(PROVIDER_CATALOG["openai"]))
        app = QApplication.instance() or QApplication([])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cfg = root / "config.json"
                cache_p = root / "cache.json"
                save_ui_settings({"auto_refresh_catalog": True}, config_path=cfg)

                fake_bin = b"FAIRYBREAD-TEST-INSTALLER-BYTES"
                good_sha = hashlib.sha256(fake_bin).hexdigest()
                remote_doc = {
                    "schema_version": 1,
                    "latest_app_version": "0.9.1h",
                    "release_summary": "Live catalog + VLC fail-safe upgrade.",
                    "download_url": "https://github.com/bm069au/fairybread/releases/download/v0.9.1h/setup.zip",
                    "installer_sha256": good_sha,
                    "model_token_rates_per_1m": {"gpt-test-new": [0.11, 0.55]},
                    "provider_catalog_updates": {
                        "openai": {"suggested_models": ["gpt-4o-mini", "gpt-5-mini"]}
                    },
                }

                # 1) Fresh network fetch updates rate tables & PROVIDER_CATALOG in memory
                res1 = sync_remote_catalog(
                    config_path=cfg,
                    cache_path=cache_p,
                    current_version="0.9.1g",
                    fetcher=lambda _u, _e, _t: (200, remote_doc, '"etag-1"'),
                )
                self.assertEqual(res1["source"], "network")
                self.assertTrue(res1["update_available"])
                self.assertEqual(cost_service.MODEL_TOKEN_RATES_PER_1M["gpt-test-new"], (0.11, 0.55))
                self.assertIn("gpt-5-mini", PROVIDER_CATALOG["openai"]["suggested_models"])

                # 2) Warm 6h cache avoids network call
                def _fail_fetch(_u, _e, _t):
                    raise AssertionError("Network should not be called while cache is warm")

                res2 = sync_remote_catalog(
                    config_path=cfg,
                    cache_path=cache_p,
                    current_version="0.9.1g",
                    fetcher=_fail_fetch,
                )
                self.assertEqual(res2["source"], "cache")
                self.assertTrue(res2["update_available"])

                # 3) Force HTTP 304 preserves cache cleanly
                res3 = sync_remote_catalog(
                    config_path=cfg,
                    cache_path=cache_p,
                    current_version="0.9.1g",
                    force=True,
                    fetcher=lambda _u, et, _t: (304, None, et),
                )
                self.assertEqual(res3["source"], "not_modified")

                # 4) Offline network failure falls back gracefully
                res_off = sync_remote_catalog(
                    config_path=cfg,
                    cache_path=root / "missing_cache.json",
                    current_version="0.9.1g",
                    force=True,
                    fetcher=lambda _u, _e, _t: (_ for _ in ()).throw(ConnectionError("offline")),
                )
                self.assertEqual(res_off["source"], "offline_fallback")
                self.assertFalse(res_off["update_available"])

                # 5) Dismissed version stays hidden until newer version arrives
                save_ui_settings({"dismissed_update_version": "0.9.1h"}, config_path=cfg)
                res_dis = sync_remote_catalog(
                    config_path=cfg,
                    cache_path=cache_p,
                    current_version="0.9.1g",
                    force=False,
                    fetcher=_fail_fetch,
                )
                self.assertFalse(res_dis["update_available"])
                self.assertTrue(res_dis["has_newer_version"])

                # 6) SHA-256 download verifier deletes mismatched files & keeps verified ones
                dl_dir = root / "downloads"
                ok_http, _m, _p = download_and_verify_installer(
                    "http://bad.example.com/x.zip", dl_dir
                )
                self.assertFalse(ok_http)
                ok_bad_sha, msg_bad, path_bad = download_and_verify_installer(
                    remote_doc["download_url"],
                    dl_dir,
                    expected_sha256="0" * 64,
                    downloader=lambda _u, dst, _t: dst.write_bytes(fake_bin),
                )
                self.assertFalse(ok_bad_sha)
                self.assertIsNone(path_bad)
                self.assertIn("SHA-256 mismatch", msg_bad)
                self.assertEqual(list(dl_dir.glob("*")), [])

                ok_good, _m_ok, path_good = download_and_verify_installer(
                    remote_doc["download_url"],
                    dl_dir,
                    expected_sha256=good_sha,
                    downloader=lambda _u, dst, _t: dst.write_bytes(fake_bin),
                )
                self.assertTrue(ok_good)
                self.assertTrue(path_good.is_file())
                self.assertEqual(path_good.read_bytes(), fake_bin)

                # 7) PalaceWindow update pill renders without clipping when shown
                class _FakeMemory:
                    def build_prompt_context(self, _q):
                        return ""

                win = PalaceWindow(
                    store=SessionStore(root / "sessions"),
                    palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                    provider_states={"gemini": True, "deepseek": True},
                    config_path=cfg,
                )
                win.show()
                win._apply_catalog_sync_result(res1, manual=False)
                app.processEvents()
                self.assertTrue(win.update_available_btn.isVisible())
                audit = audit_palace_window_geometry(win)
                self.assertEqual(audit["clipped_widget_count"], 0, msg=f"Clipped with update pill: {audit.get('clipped_widgets')}")
                win._force_quit = True
                win.close()
                app.processEvents()
        finally:
            cost_service.MODEL_TOKEN_RATES_PER_1M.clear()
            cost_service.MODEL_TOKEN_RATES_PER_1M.update(orig_rates)
            PROVIDER_CATALOG["openai"].clear()
            PROVIDER_CATALOG["openai"].update(orig_openai_meta)

    def test_restore_default_settings_preserves_memory_keys_and_write_exclusions_by_default(self):
        import tomllib
        from access_policy import load_access_permissions, save_access_permissions
        from fairybread_mcp import install_codex_bridge, load_bridge_settings, save_bridge_settings
        from palace_config import (
            load_ui_settings,
            restore_default_settings,
            save_agent_defaults,
            save_provider_config,
            save_ui_settings,
        )
        from palace_gui import RestoreDefaultSettingsDialog
        from voice_service import load_voice_settings, save_voice_settings

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "palace_config.json"
            bak_dir = root / "bak"
            data_dir = root / "palace_data"
            data_dir.mkdir(parents=True)
            mem_db = data_dir / "memory.db"
            mem_db.write_text("KEEP-MEMORY-DB", encoding="utf-8")

            temp_home = root / "home"
            temp_appdata = root / "appdata"
            install_codex_bridge(home_dir=temp_home)

            save_provider_config("gemini", enabled=True, model="gemini-4-neon", config_path=cfg)
            save_ui_settings({"theme": "light", "enter_to_send": False, "custom_data_dir": str(data_dir)}, config_path=cfg)
            save_agent_defaults({"web_search_default": "deep"}, config_path=cfg)
            save_voice_settings({"gemini_voice_name": "Puck", "speech_speed": 1.25}, config_path=cfg)
            save_access_permissions(
                {"permission_mode": "turbo", "write_exclusions": [{"path": str(root / "KeepProt"), "include_subdirs": True}]},
                config_path=cfg,
            )
            save_bridge_settings({"enabled": True, "platforms": {"codex": "foreman"}}, config_path=cfg)

            # Default restore: resets UI/mode/voice, keeps Memory, providers, custom_data_dir, exclusions & MCP link
            res1 = restore_default_settings(
                cfg,
                clear_write_exclusions=False,
                unlink_external_bridges=False,
                backup_dir=bak_dir,
            )
            self.assertTrue(Path(res1["backup_path"]).is_file())
            self.assertEqual(res1["preserved_exclusions"], 1)
            self.assertEqual(mem_db.read_text(encoding="utf-8"), "KEEP-MEMORY-DB")
            self.assertEqual(load_ui_settings(cfg)["theme"], "dark")
            self.assertEqual(load_ui_settings(cfg)["custom_data_dir"], str(data_dir))
            self.assertEqual(load_agent_defaults(cfg)["web_search_default"], "default")
            self.assertEqual(load_voice_settings(cfg)["gemini_voice_name"], "Kore")
            ap1 = load_access_permissions(cfg)
            self.assertEqual(ap1["permission_mode"], "default")
            self.assertEqual(len(ap1["write_exclusions"]), 1)
            self.assertEqual(load_bridge_settings(cfg)["platforms"]["codex"], "foreman")
            self.assertIn("fairybread", tomllib.loads((temp_home / ".codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"])

            # Dialog opt-in clear exclusions + unlink external MCP bridges
            dlg = RestoreDefaultSettingsDialog(
                config_path=cfg,
                backup_dir=bak_dir,
                bridge_home_dir=temp_home,
                bridge_appdata_dir=temp_appdata,
            )
            self.assertFalse(dlg.clear_exclusions_check.isChecked())
            self.assertFalse(dlg.unlink_bridges_check.isChecked())
            dlg.clear_exclusions_check.setChecked(True)
            dlg.unlink_bridges_check.setChecked(True)
            dlg._execute_reset()
            app.processEvents()

            self.assertEqual(load_access_permissions(cfg)["write_exclusions"], [])
            self.assertEqual(load_bridge_settings(cfg)["platforms"]["codex"], "off")
            codex_txt = (temp_home / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertNotIn("fairybread", (tomllib.loads(codex_txt) if codex_txt.strip() else {}).get("mcp_servers", {}))
            self.assertEqual(mem_db.read_text(encoding="utf-8"), "KEEP-MEMORY-DB")

    def test_installer_vlc_upgrade_preserves_config_memory_and_creates_pre_upgrade_backup(self):
        import zipfile
        from install_fairybread_beta import perform_installation_detailed

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unrelated_dir = root / "unrelated"
            unrelated_dir.mkdir()
            (unrelated_dir / "notes.txt").write_text("user notes", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                perform_installation_detailed(
                    unrelated_dir,
                    register_system_shortcuts=False,
                    allow_upgrade_existing=True,
                    data_dir=root / "data_unused",
                )

            custom_install_dir = root / "MyCustomFairybread"
            custom_install_dir.mkdir()
            (custom_install_dir / "palace_gui.py").write_text("# old", encoding="utf-8")
            local_cfg = {"providers": {"gemini": {"enabled": True, "model": "gemini-4-neon"}}, "ui_settings": {"theme": "custom_user_theme"}}
            (custom_install_dir / "palace_config.json").write_text(json.dumps(local_cfg), encoding="utf-8")

            fake_data_dir = root / "palace_appdata"
            (fake_data_dir / "sessions").mkdir(parents=True)
            (fake_data_dir / "idle_notebooks").mkdir(parents=True)
            (fake_data_dir / "memory.db").write_text("MEMORY-DATA", encoding="utf-8")
            (fake_data_dir / "credentials.json").write_text('{"openai": "enc"}', encoding="utf-8")
            (fake_data_dir / "sessions" / "s1.json").write_text("[]", encoding="utf-8")
            (fake_data_dir / "idle_notebooks" / "n1.md").write_text("idle note", encoding="utf-8")
            (fake_data_dir / "palace_config.json").write_text(json.dumps(local_cfg), encoding="utf-8")

            # Must refuse if allow_upgrade_existing=False
            with self.assertRaises(FileExistsError):
                perform_installation_detailed(
                    custom_install_dir,
                    register_system_shortcuts=False,
                    allow_upgrade_existing=False,
                    data_dir=fake_data_dir,
                )

            # VLC default upgrade: creates backup ZIP, preserves non-Program-Files palace_config.json + Memory + keys
            up_res = perform_installation_detailed(
                custom_install_dir,
                register_system_shortcuts=False,
                allow_upgrade_existing=True,
                keep_existing_settings=True,
                wipe_memory_and_chats=False,
                data_dir=fake_data_dir,
            )
            self.assertTrue(up_res["upgraded_existing"])
            bak_zip = Path(up_res["backup_zip"])
            self.assertTrue(bak_zip.is_file())
            with zipfile.ZipFile(bak_zip, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("data/memory.db", names)
                self.assertIn("data/credentials.json", names)
                self.assertIn("install_dir/palace_config.json", names)
            self.assertEqual(json.loads((custom_install_dir / "palace_config.json").read_text(encoding="utf-8"))["ui_settings"]["theme"], "custom_user_theme")
            self.assertEqual((fake_data_dir / "memory.db").read_text(encoding="utf-8"), "MEMORY-DATA")

            # Opt-in Clean Install + Wipe Memory still keeps credentials.json & creates backup ZIP first
            clean_res = perform_installation_detailed(
                custom_install_dir,
                register_system_shortcuts=False,
                allow_upgrade_existing=True,
                keep_existing_settings=False,
                wipe_memory_and_chats=True,
                data_dir=fake_data_dir,
            )
            self.assertTrue(clean_res["wiped_memory"])
            self.assertEqual(json.loads((custom_install_dir / "palace_config.json").read_text(encoding="utf-8"))["ui_settings"]["theme"], "dark")
            self.assertTrue((fake_data_dir / "credentials.json").is_file())
            self.assertFalse((fake_data_dir / "memory.db").exists())


if __name__ == "__main__":
    unittest.main()
