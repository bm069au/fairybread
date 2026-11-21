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


class GraphicsPromptOptimizationTests(unittest.TestCase):
    def test_visual_refinement_followups_route_to_prompt_duo_as_highres_master(self):
        prior_ctx = (
            "USER: Draw me a sunflower if it was grown on an alien world.\n\n"
            "ASSISTANT: # Alien Sunflower — Master Render (Draft 1)\n"
            '[GENERATE_IMAGE prompt="Ultra-detailed photorealistic environmental macro photograph of an alien sunflower at twilight" '
            'title="Alien Sunflower — Master" size="1024x1024" quality="high"]\n'
            "✓ [ALL TASKS COMPLETED SUCCESSFULLY]"
        )

        class _StaticCtx:
            session_id = "sunflower_refine_test"

            def load_recent(self, max_chars: int = 12000):
                return prior_ctx

            def append_exchange(self, *args, **kwargs):
                return ("q", "a")

        for q in (
            "its still hyper realistic. More photo realistic please",
            "The flower is nice but it's hyper realistic. How about making it photorealistic as if someone took a picture in this alien landscape",
            "Please finish the task. Tasks are supposed to be deligated to AIs for the prompt and then sent to the AI's in charge of creating the image.",
        ):
            reg = ProviderRegistry()
            calls: dict[str, list[str]] = {}
            for pname in ("gemini", "openai", "deepseek", "groq", "qwen", "cohere", "mistral", "cerebras"):
                def _make_fn(n=pname):
                    def _fn(prompt: str) -> str:
                        calls.setdefault(n, []).append(prompt)
                        if n in ("gemini", "openai"):
                            return (
                                '[GENERATE_IMAGE prompt="Unedited handheld 50mm photograph of an alien sunflower at overcast dusk" '
                                'title="Alien Sunflower Field Photo" size="1024x1024" quality="high"]'
                            )
                        return "Should not run on primary prompt duo turn"
                    return _fn
                reg.register(pname, _StubProvider(pname, _make_fn()))

            synth = PalaceSynthesizer(
                "palace_synth",
                _StubProvider(
                    "palace_synth",
                    lambda _p: '[GENERATE_IMAGE prompt="Unedited handheld 50mm photograph of an alien sunflower at overcast dusk" title="Alien Sunflower Field Photo" size="1024x1024" quality="high"]',
                ),
                fallback_providers={},
            )
            orch = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg), synthesizer=synth, context_service=_StaticCtx())
            with patch("palace_theme.prewarm_generated_images") as mock_prewarm:
                res = orch.run(
                    q,
                    provider_names=["gemini", "openai", "deepseek", "groq", "qwen", "cohere", "mistral", "cerebras"],
                    include_context=True,
                    save_to_context=False,
                    max_rounds=2,
                )
            self.assertEqual(set(res.provider_results.keys()), {"gemini", "openai"}, msg=f"Wrong duo routing for: {q}")
            self.assertEqual(len(calls["gemini"]), 1)
            self.assertEqual(len(calls["openai"]), 1)
            self.assertNotIn("deepseek", calls)
            self.assertEqual(res.peer_rounds, [])
            self.assertIn("YOUR ROLE IS PROMPT OPTIMIZATION", calls["gemini"][0])
            self.assertIn("[VISUAL REFINEMENT FOLLOW-UP", calls["gemini"][0])
            self.assertNotIn("NOT a drawing request", calls["gemini"][0])
            self.assertIn("[GENERATE_IMAGE", res.final_answer or "")
            mock_prewarm.assert_called_once()

    def test_verbose_pass_failover_and_rate_limit_skip_for_graphics_and_code_exclusion(self):
        from synthesizer import is_pass_or_defer_text

        self.assertTrue(is_pass_or_defer_text("[PASS]"))
        self.assertTrue(is_pass_or_defer_text("[PASS] — My strengths are software/architecture, not photoreal rendering."))
        self.assertTrue(is_pass_or_defer_text("[PASS] — Use the appropriate [GENERATE_IMAGE] command."))
        self.assertFalse(
            is_pass_or_defer_text(
                '[PASS] — Here is the tag anyway: [GENERATE_IMAGE prompt="A real dusk photograph of a sunflower" title="Sun"]'
            )
        )

        class _RateLimitThenFailProvider(AIProvider):
            def __init__(self, name: str, err_msg: str):
                self.name = name
                self.err_msg = err_msg
                self.calls: list[str] = []

            def generate(self, prompt: str) -> ProviderResponse:
                self.calls.append(prompt)
                raise RuntimeError(self.err_msg)

        prior_ctx = (
            "USER: Draw a sunflower.\n\n"
            "ASSISTANT: "
            '[GENERATE_IMAGE prompt="A sunlit sunflower on an exoplanet" title="Alien Sunflower Master" size="1024x1024" quality="high"]'
        )

        class _StaticCtx:
            session_id = "failover_429_test"

            def load_recent(self, max_chars: int = 12000):
                return prior_ctx

            def append_exchange(self, *args, **kwargs):
                return ("q", "a")

        reg = ProviderRegistry()
        gem = _RateLimitThenFailProvider("gemini", "429 RESOURCE_EXHAUSTED: Quota exceeded")
        oai_calls: list[str] = []
        ds_calls: list[str] = []

        def _oai_fn(p: str) -> str:
            oai_calls.append(p)
            return "[PASS] — Handing over to GEMINI for execution."

        def _ds_fn(p: str) -> str:
            ds_calls.append(p)
            return (
                '[GENERATE_IMAGE prompt="Raw unedited 10-year-old camera JPEG of an alien sunflower at dusk" '
                'title="Alien Sunflower — Actual Field Photograph" size="1024x1024" quality="high"]'
            )

        reg.register("gemini", gem)
        reg.register("openai", _StubProvider("openai", _oai_fn))
        reg.register("deepseek", _StubProvider("deepseek", _ds_fn))
        synth = PalaceSynthesizer("palace_synth", _StubProvider("palace_synth", lambda p: "UNEXPECTED"), fallback_providers={})
        orch = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg), synthesizer=synth, context_service=_StaticCtx())

        with patch("palace_theme.prewarm_generated_images") as mock_prewarm:
            res = orch.run(
                "its still hyper realistic. More photo realistic please",
                provider_names=["gemini", "openai", "deepseek"],
                include_context=True,
                save_to_context=False,
                max_rounds=2,
            )
        self.assertEqual(len(gem.calls), 1)  # 429 skips redundant retry and fails over immediately
        self.assertEqual(len(oai_calls), 1)
        self.assertEqual(len(ds_calls), 1)
        self.assertIn("[GRAPHICS FAILOVER — YOU ARE THE ACTIVE PROMPT OPTIMIZER]", ds_calls[0])
        self.assertIn("Actual Field Photograph", res.final_answer or "")
        self.assertNotIn("[PASS]", res.final_answer or "")
        mock_prewarm.assert_called_once()

        # Coding prompt mentioning renderer/pipeline must remain drawing_mode='none'
        code_calls: list[str] = []
        reg_code = ProviderRegistry()
        reg_code.register("deepseek", _StubProvider("deepseek", lambda p: (code_calls.append(p) or "Fixed the renderer pipeline bug.")))
        reg_code.register("openai", _StubProvider("openai", lambda _p: "[PASS] — My strengths are visual design, deferring."))
        synth_code = PalaceSynthesizer("palace_synth", _StubProvider("palace_synth", lambda _p: "UNEXPECTED"), fallback_providers={})
        orch_code = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg_code), synthesizer=synth_code, context_service=_StaticCtx())
        with patch("palace_theme.prewarm_generated_images") as mock_code_prewarm:
            res_code = orch_code.run(
                "Fix the photorealistic renderer pipeline bug in palace_theme.py",
                provider_names=["deepseek", "openai"],
                include_context=True,
                save_to_context=False,
                max_rounds=1,
            )
        self.assertIn("NOT a drawing request", code_calls[0])
        self.assertIn("Fixed the renderer pipeline bug.", res_code.final_answer or "")
        mock_code_prewarm.assert_not_called()

        # Synthesizer itself filters [PASS] — deferrals out when another peer returned real text
        s_res = synth.synthesize(
            "Explain X",
            {
                "gemini": ProviderResult(provider_name="gemini", response=ProviderResponse(text="[PASS] — Deferring to DeepSeek", model="m", provider="gemini")),
                "deepseek": ProviderResult(provider_name="deepseek", response=ProviderResponse(text="Direct explanation of X.", model="m", provider="deepseek")),
            },
        )
        self.assertEqual(s_res.text, "Direct explanation of X.")


class ExperimentalModeAutoResumeTests(unittest.TestCase):
    def test_watchdog_preserves_experimental_handoff_and_single_circuit_breaker_count(self):
        import palace_ouroboros
        import palace_watchdog

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sandbox = root / "sandbox"
            staging = sandbox / "staging"
            live = root / "live"
            repo = root / "repo"
            editions = sandbox / "editions"
            for d in (sandbox, staging, live, repo, editions):
                d.mkdir(parents=True, exist_ok=True)
            (staging / "memory_service.py").write_text("# test\n", encoding="utf-8")
            (live / "memory_service.py").write_text("# test\n", encoding="utf-8")
            (repo / "memory_service.py").write_text("# test\n", encoding="utf-8")

            handoff_path = sandbox / "reboot_handoff.json"
            hb_path = sandbox / "palace_ready_heartbeat.json"

            with patch.object(palace_ouroboros, "SANDBOX_ROOT", sandbox), \
                 patch.object(palace_ouroboros, "STAGING_DIR", staging), \
                 patch.object(palace_ouroboros, "LIVE_DIR", live), \
                 patch.object(palace_ouroboros, "SOURCE_REPO_DIR", repo), \
                 patch.object(palace_ouroboros, "EDITIONS_DIR", editions), \
                 patch.object(palace_ouroboros, "HANDOFF_PATH", handoff_path), \
                 patch.object(palace_ouroboros, "READY_HEARTBEAT_PATH", hb_path), \
                 patch.object(palace_watchdog, "SANDBOX_ROOT", sandbox), \
                 patch.object(palace_watchdog, "STAGING_DIR", staging), \
                 patch.object(palace_watchdog, "LIVE_DIR", live), \
                 patch.object(palace_watchdog, "SOURCE_REPO_DIR", repo), \
                 patch.object(palace_watchdog, "HANDOFF_PATH", handoff_path), \
                 patch.object(palace_watchdog, "READY_HEARTBEAT_PATH", hb_path), \
                 patch.object(palace_watchdog, "WATCHDOG_LOG_PATH", sandbox / "wd.log"), \
                 patch.object(palace_watchdog, "validate_staged_palace", return_value={"passed": True, "py_compile": "pass", "unittest_passed": True}), \
                 patch.object(palace_watchdog, "backup_live_to_last_known_good"), \
                 patch.object(palace_watchdog, "ensure_golden_baseline_edition"), \
                 patch.object(palace_watchdog, "create_code_edition_snapshot"), \
                 patch.object(palace_watchdog, "_stop_existing_palace_gui"):

                ok_w, msg_w, _payload = palace_ouroboros.write_reboot_handoff(
                    reason="experimental_agent_live_patch",
                    applied_diff_summary="GEMINI: Improve search",
                    test_results={"py_compile": "pass", "unittest_passed": True},
                    extra_continuity={
                        "auto_resume_idle": True,
                        "idle_transcript": [{"speaker": "gemini", "content": "Patched FTS query."}],
                        "idle_remaining_seconds": 4321,
                        "idle_tokens_used": 12345,
                        "idle_spend_usd": 0.42,
                        "idle_saved_notes": 2,
                        "idle_sent_emails": 1,
                    },
                )
                self.assertTrue(ok_w, msg_w)

                def _fake_launch():
                    hb_path.write_text(
                        json.dumps({"pid": 99999, "status": "READY", "timestamp": time.time() + 1.0}),
                        encoding="utf-8",
                    )

                with patch.object(palace_watchdog, "_launch_palace_on_interactive_desktop", side_effect=_fake_launch):
                    ok_r, msg_r = palace_watchdog.perform_hot_reboot(
                        reason="ouroboros_self_upgrade",
                        diff_summary="GEMINI: Improve search",
                        skip_tests=True,
                        preserve_existing_handoff=True,
                    )
                self.assertTrue(ok_r, msg_r)

                saved = json.loads(handoff_path.read_text(encoding="utf-8"))
                self.assertFalse(saved["consumed"])
                self.assertEqual(saved["reboot"]["reason"], "experimental_agent_live_patch")
                self.assertEqual(saved["reboot"]["reboot_count_in_window"], 1)
                self.assertTrue(saved["reboot"]["test_results"]["unittest_passed"])
                cont = saved["continuity"]
                self.assertTrue(cont["auto_resume_idle"])
                self.assertEqual(cont["idle_remaining_seconds"], 4321)
                self.assertEqual(cont["idle_tokens_used"], 12345)
                self.assertAlmostEqual(cont["idle_spend_usd"], 0.42, places=4)
                self.assertEqual(len(cont["idle_transcript"]), 1)

    def test_idle_session_manager_and_window_resume_without_wiping_state(self):
        from idle_service import IdleMailboxStore, IdleMemoryStore, IdleSessionManager
        from palace_gui import PalaceWindow
        from session_store import SessionStore

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg_p = root / "palace_config.json"
            mem = IdleMemoryStore(root / "idle_mem.md")
            mb = IdleMailboxStore(root / "mailbox.json")
            mgr = IdleSessionManager(idle_memory=mem, mailbox=mb, config_path=cfg_p)
            mgr.transcript = [{"speaker": "cohere", "content": "Previous turn before reboot."}]
            mgr.remaining_seconds = 1440
            mgr.tokens_used_this_session = 8800
            mgr.spend_usd_this_session = 0.19
            mgr.saved_notes_this_session = 3
            mgr.sent_emails_this_session = 1
            mgr.status = "Ready"
            mgr.resume_session()
            self.assertTrue(mgr.is_idle_mode)
            self.assertEqual(mgr.status, "Active")
            self.assertEqual(mgr.remaining_seconds, 1440)
            self.assertEqual(mgr.tokens_used_this_session, 8800)
            self.assertAlmostEqual(mgr.spend_usd_this_session, 0.19, places=4)
            self.assertEqual(mgr.saved_notes_this_session, 3)
            self.assertEqual(mgr.sent_emails_this_session, 1)
            self.assertEqual(len(mgr.transcript), 1)

            store = SessionStore(root / "sess_root")
            win = PalaceWindow(store=store, palace_factory=lambda ctx: build_palace({}, context_service=ctx))
            try:
                continuity = {
                    "auto_resume_idle": True,
                    "idle_transcript": [
                        {"speaker": "cohere", "content": "Applied live FTS patch."},
                    ],
                    "idle_remaining_seconds": 1440,
                    "idle_tokens_used": 8800,
                    "idle_spend_usd": 0.19,
                    "idle_saved_notes": 3,
                    "idle_sent_emails": 1,
                }
                win.resume_idle_session(continuity, "COHERE: FTS synonym patch", auto_step=False)
                self.assertEqual(win.workspace_tabs.currentIndex(), 1)
                self.assertTrue(win.idle_switch_btn.isChecked())
                self.assertEqual(win.current_profile, "Idle")
                self.assertEqual(win.idle_manager.status, "Active")
                self.assertEqual(win.idle_manager.remaining_seconds, 1440)
                self.assertEqual(win.idle_manager.tokens_used_this_session, 8800)
                self.assertAlmostEqual(win.idle_manager.spend_usd_this_session, 0.19, places=4)
                self.assertEqual(len(win.idle_manager.transcript), 2)
                self.assertIn("Ouroboros Hot-Reboot Complete", win.idle_manager.transcript[-1]["content"])
                self.assertFalse(win.composer.isEnabled())

                # Rollback banner check
                win.resume_idle_session(
                    continuity,
                    "BAD: Broken patch",
                    rolled_back=True,
                    rollback_reason="Timed out waiting for READY",
                    auto_step=False,
                )
                self.assertIn("Ouroboros Rollback", win.idle_manager.transcript[-1]["content"])
                self.assertIn("Timed out waiting for READY", win.idle_manager.transcript[-1]["content"])
            finally:
                win.idle_timer.stop()
                win.idle_auto_timer.stop()
                win.close()
                app.processEvents()

    def test_experimental_preflight_unittest_gate_rejects_broken_patch_and_reverts(self):
        from idle_service import IdleMailboxStore, IdleMemoryStore, IdleSessionManager
        import palace_config
        import palace_ouroboros
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg_p = root / "palace_config.json"
            palace_config.save_idle_settings(
                {"allow_live_self_modify": True, "share_source_code": True, "idle_submode": "self_improve"},
                config_path=cfg_p,
            )
            mem = IdleMemoryStore(root / "idle_mem.md")
            mb = IdleMailboxStore(root / "mailbox.json")
            mgr = IdleSessionManager(idle_memory=mem, mailbox=mb, config_path=cfg_p)
            mgr.is_idle_mode = True
            mgr.status = "Active"

            bad_reply = (
                '[IDLE_PATCH file="memory_service.py" summary="Expand synonyms"]\n'
                '<<<TARGET\n'
                'return " OR ".join(f\'"{t}"*\' for t in terms)\n'
                '===REPLACE\n'
                'return _SYNONYMS\n'
                '>>>\n'
                '[/IDLE_PATCH]'
            )
            with patch("palace_config.IS_DEVELOPER_EDITION", True), \
                 patch.object(palace_ouroboros, "sync_live_to_staging") as mock_sync, \
                 patch.object(palace_ouroboros, "stage_palace_replace", return_value=(True, "compiled cleanly")), \
                 patch.object(
                     palace_ouroboros,
                     "validate_staged_palace",
                     return_value={"passed": False, "unittest_output": "NameError: name '_SYNONYMS' is not defined"},
                 ) as mock_val, \
                 patch.object(subprocess, "Popen") as mock_popen:
                msgs = mgr.run_exchange_round({"cohere": lambda _p: bad_reply})

            self.assertEqual(mock_sync.call_count, 2)
            mock_val.assert_called_once_with(run_unit_tests=True)
            mock_popen.assert_not_called()
            self.assertEqual(mb.list_messages(), [])
            self.assertTrue(msgs)
            combined = "\n".join(m.get("content", "") for m in msgs)
            self.assertIn("Live Patch Rejected by Preflight Unit Tests", combined)
            self.assertIn("NameError: name '_SYNONYMS' is not defined", combined)


class VoiceStopLayoutAndMemoryTests(unittest.TestCase):
    def test_composer_two_row_and_live_bar_zero_clipping(self):
        from palace_gui import PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cfg = tmp_p / "palace_config.json"
            store = SessionStore(tmp_p)
            win = PalaceWindow(
                store=store,
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True, "deepseek": True},
                config_path=cfg,
            )
            win._memory_db_path = lambda: tmp_p / "mem.db"
            try:
                win.show()
                for w, h in ((1024, 700), (1120, 740)):
                    win.resize(w, h)
                    app.processEvents()

                    # Idle state: auto-hiding live bar stays hidden and zero clipping
                    self.assertTrue(win.composer_live_bar.isHidden())
                    audit_idle = audit_palace_window_geometry(win)
                    self.assertEqual(
                        audit_idle["clipped_widget_count"],
                        0,
                        msg=f"Idle {w}x{h} clipped: {audit_idle.get('clipped_widgets')}",
                    )

                    # Live Voice active state: meter, mute, and end-talk controls visible
                    win.voice_level_badge.setText("🎙 ▁▂▃▄▅▆  42% · Live Voice")
                    win.voice_level_badge.show()
                    win.voice_mute_btn.show()
                    win.end_talk_btn.show()
                    win._sync_composer_live_bar_visibility()
                    app.processEvents()
                    self.assertFalse(win.composer_live_bar.isHidden())
                    audit_voice = audit_palace_window_geometry(win)
                    self.assertEqual(
                        audit_voice["clipped_widget_count"],
                        0,
                        msg=f"LiveVoice {w}x{h} clipped: {audit_voice.get('clipped_widgets')}",
                    )

                    # Live Voice + Busy state: steer & stop buttons visible alongside live controls
                    win.set_busy(True)
                    app.processEvents()
                    self.assertFalse(win.steer_button.isHidden())
                    self.assertFalse(win.stop_button.isHidden())
                    audit_busy = audit_palace_window_geometry(win)
                    self.assertEqual(
                        audit_busy["clipped_widget_count"],
                        0,
                        msg=f"LiveVoice+Busy {w}x{h} clipped: {audit_busy.get('clipped_widgets')}",
                    )

                    # Restore idle state cleanly
                    win.set_busy(False)
                    win.stop_all_voice_modes()
                    app.processEvents()
                    self.assertTrue(win.composer_live_bar.isHidden())
            finally:
                win._force_quit = True
                win.close()
                app.processEvents()

    def test_voice_stop_mute_generation_and_close_cleanup(self):
        import threading
        from palace_gui import PalaceWindow
        from session_store import SessionStore
        from voice_companion import VoiceCompanion

        class _FakeSess:
            def __init__(self):
                self.muted = False
                self.stop_calls: list[tuple[str, bool]] = []

            def stop(self, filename: str = "x.wav", *, discard: bool = False):
                self.stop_calls.append((filename, discard))
                return None

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cfg = tmp_p / "palace_config.json"
            store = SessionStore(tmp_p)
            sid = store.selected
            win = PalaceWindow(
                store=store,
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True, "deepseek": True},
                config_path=cfg,
            )
            win._memory_db_path = lambda: tmp_p / "mem.db"
            win.show()
            app.processEvents()

            win._activate_talk_only_mode(auto_start_live_voice=False)
            app.processEvents()
            self.assertTrue(win._talk_only_mode)
            self.assertFalse(win.end_talk_btn.isHidden())
            self.assertFalse(win.composer_live_bar.isHidden())

            fake_sess = _FakeSess()
            win._active_voice_session = fake_sess
            win._toggle_voice_mute(True)
            self.assertTrue(fake_sess.muted)
            self.assertIn("Unmute", win.voice_mute_btn.text())

            gen_before = win._voice_session_gen
            with patch("voice_service.stop_speaking") as mock_stop_speaking, \
                 patch.object(win, "_on_live_voice_utterance") as mock_utt:
                win.stop_all_voice_modes()
                app.processEvents()

            self.assertEqual(win._voice_session_gen, gen_before + 1)
            self.assertEqual(len(fake_sess.stop_calls), 1)
            self.assertIs(fake_sess.stop_calls[0][1], True)
            mock_utt.assert_not_called()
            mock_stop_speaking.assert_called_once()
            self.assertFalse(win._talk_only_mode)
            self.assertTrue(win.end_talk_btn.isHidden())
            self.assertTrue(win.composer_live_bar.isHidden())
            self.assertFalse(win.live_voice_button.isChecked())

            # Normal mode switch exits Talk Mode Only as well
            win._activate_talk_only_mode(auto_start_live_voice=False)
            app.processEvents()
            self.assertTrue(win._talk_only_mode)
            win._activate_normal_mode_from_menu()
            app.processEvents()
            self.assertFalse(win._talk_only_mode)
            self.assertTrue(win.end_talk_btn.isHidden())

            # Stale generation cancellation drops delayed VoiceCompanionWorker output
            win._activate_talk_only_mode(auto_start_live_voice=False)
            app.processEvents()
            entered = threading.Event()
            release = threading.Event()

            def _slow_reply(_prompt: str) -> str:
                entered.set()
                release.wait(3.0)
                return "SHOULD_BE_DISCARDED"

            win._voice_companion = VoiceCompanion(llm_callable=_slow_reply)
            win.composer.setPlainText("Remember blue")
            win.send_message()
            self.assertTrue(entered.wait(3.0))
            win.stop_all_voice_modes()
            release.set()

            deadline = time.monotonic() + 5.0
            while win._voice_threads and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.02)
            app.processEvents()

            self.assertFalse(
                any("SHOULD_BE_DISCARDED" in (m.get("content") or "") for m in store.messages(sid)),
                msg="Stale voice response must not be stored after stop_all_voice_modes()",
            )

            # Force close cleanly stops active voice session
            fake_sess2 = _FakeSess()
            win._active_voice_session = fake_sess2
            win._force_quit = True
            win.close()
            app.processEvents()
            self.assertEqual(len(fake_sess2.stop_calls), 1)
            self.assertIs(fake_sess2.stop_calls[0][1], True)

    def test_shared_memory_read_write_voice_and_orchestrator(self):
        from memory_service import MemoryService, extract_and_save_memory_tags
        from session_store import SessionStore
        from voice_companion import VoiceCompanion

        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            db_p = tmp_p / "mem.db"
            mem_svc = MemoryService(db_path=db_p)

            # 1. Explicit [SAVE_MEMORY ...] extraction & retrieval
            cleaned, saved = extract_and_save_memory_tags(
                'Sure! [SAVE_MEMORY summary="Fav color" fact="Brett prefers cobalt blue"]',
                mem_svc,
                session_id="s1",
                replace_with_badge=True,
            )
            self.assertEqual(len(saved), 1)
            self.assertIn("Saved to Memory Palace", cleaned)
            search_res = mem_svc.search("cobalt blue")
            self.assertTrue(search_res.succeeded)
            self.assertIn("cobalt blue", search_res.context)

            # 2. backfill_from_sessions indexes phase='voice_chat'
            store_root = tmp_p / "store"
            st = SessionStore(store_root)
            sid = st.selected
            st.context(sid).append_exchange(
                "Where is the staging sandbox located?",
                "The staging sandbox lives at C:\\Palace_Idle_Sandbox\\staging.",
                contributors=["gemini"],
                answer_speaker_id="voice_companion",
                answer_phase="voice_chat",
            )
            added = mem_svc.backfill_from_sessions(store_root)
            self.assertGreaterEqual(added, 1)
            bf_res = mem_svc.search("Palace_Idle_Sandbox")
            self.assertTrue(bf_res.succeeded)
            self.assertIn("Palace_Idle_Sandbox", bf_res.context)

            # 3. VoiceCompanion Talk Mode read + write + No-History block
            prompts_seen: list[str] = []
            vc_talk = VoiceCompanion(
                llm_callable=lambda p: (
                    prompts_seen.append(p),
                    'I remember cobalt blue! [SAVE_MEMORY summary="Coffee" fact="Flat white with oat milk"]',
                )[1]
            )
            dec_talk = vc_talk.respond(
                "Save my coffee order",
                talk_only=True,
                memory_context="Fav color: cobalt blue",
                allow_memory_write=True,
            )
            self.assertIn("Fav color: cobalt blue", prompts_seen[-1])
            self.assertEqual(len(dec_talk.memory_saves), 1)
            self.assertEqual(dec_talk.memory_saves[0]["fact"], "Flat white with oat milk")
            self.assertNotIn("[SAVE_MEMORY", dec_talk.spoken_reply)

            dec_no_hist = vc_talk.respond(
                "Save tea order",
                talk_only=True,
                memory_context="",
                allow_memory_write=False,
            )
            self.assertEqual(dec_no_hist.memory_saves, [])

            # 4. VoiceCompanion Live JSON save_memory parsing
            vc_live = VoiceCompanion(
                llm_callable=lambda _p: json.dumps({
                    "action": "chat",
                    "spoken_reply": "Saved your audio interface setup.",
                    "delegated_task": "",
                    "steer_note": "",
                    "save_memory": {"summary": "Audio interface", "fact": "Focusrite Scarlett 2i2"},
                })
            )
            dec_live = vc_live.respond(
                "Remember my interface",
                talk_only=False,
                memory_context="Fav color: cobalt blue",
                allow_memory_write=True,
            )
            self.assertEqual(len(dec_live.memory_saves), 1)
            self.assertIn("Focusrite Scarlett 2i2", dec_live.memory_saves[0]["fact"])

            # 5. PalaceOrchestrator executes [SAVE_MEMORY ...] when include_memory=True and skips when False
            reg = ProviderRegistry()
            reg.register(
                "gemini",
                _StubProvider(
                    "gemini",
                    lambda _p: 'Noted! [SAVE_MEMORY summary="Orch Coffee" fact="Long black no sugar"]',
                ),
            )
            orch = PalaceOrchestrator(mem_svc, ProviderDispatcher(reg), synthesizer=None)
            res_on = orch.run("Please remember my coffee order", provider_names=["gemini"], include_memory=True)
            synth_txt = res_on.synthesis.text if res_on.synthesis else ""
            self.assertIn("Saved to Memory Palace", synth_txt)
            self.assertIn("Long black no sugar", mem_svc.search("Long black no sugar").context)

            reg2 = ProviderRegistry()
            reg2.register(
                "gemini",
                _StubProvider(
                    "gemini",
                    lambda _p: 'Ephemeral! [SAVE_MEMORY summary="NoHist Secret" fact="Must not persist offline"]',
                ),
            )
            orch2 = PalaceOrchestrator(mem_svc, ProviderDispatcher(reg2), synthesizer=None)
            orch2.run("Remember temporarily", provider_names=["gemini"], include_memory=False)
            self.assertNotIn("Must not persist offline", mem_svc.search("Must not persist offline").context or "")

    def test_tts_cost_per_char_and_per_minute(self):
        from cost_service import emit_tts_cost, estimate_tts_cost_usd, register_cost_listener, unregister_cost_listener

        self.assertEqual(estimate_tts_cost_usd("system:sapi5", 30.0, char_count=500), 0.0)
        self.assertAlmostEqual(estimate_tts_cost_usd("cartesia:sonic-2", 5.0, char_count=1000), 0.045, places=6)
        self.assertAlmostEqual(estimate_tts_cost_usd("elevenlabs:eleven_flash_v2_5", 5.0, char_count=1000), 0.18, places=6)
        self.assertAlmostEqual(estimate_tts_cost_usd("groq:canopylabs/orpheus-v1-english", 5.0, char_count=1000), 0.022, places=6)
        self.assertAlmostEqual(estimate_tts_cost_usd("deepgram:aura-2-thalia-en", 5.0, char_count=1000), 0.025, places=6)
        self.assertAlmostEqual(estimate_tts_cost_usd("openai:gpt-4o-mini-tts", 60.0), 0.015, places=6)
        self.assertAlmostEqual(estimate_tts_cost_usd("gemini:gemini-3.8-flash-lite-tts", 60.0), 0.012, places=6)

        events: list[dict] = []
        register_cost_listener(events.append)
        try:
            cost = emit_tts_cost("cartesia:sonic-2", 2.0, char_count=200)
        finally:
            unregister_cost_listener(events.append)
        self.assertAlmostEqual(cost, 0.009, places=6)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["provider"], "cartesia")
        self.assertEqual(events[0]["char_count"], 200)

    def test_live_volume_slider_and_waveout_error_fallback(self):
        import threading
        import voice_service
        from palace_gui import ManageAIsDialog
        from voice_service import get_live_volume, load_voice_settings, save_voice_settings, set_live_volume

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            save_voice_settings(
                {"tts_engine": "openai", "tts_fallback_engine": "auto", "voice_name": "ash", "volume_percent": 90},
                config_path=cfg,
            )
            self.assertEqual(get_live_volume(cfg), 90)
            set_live_volume(35, config_path=cfg)
            self.assertEqual(get_live_volume(cfg), 35)

            dlg = ManageAIsDialog(config_path=cfg, initial_page="Voice & Audio")
            dlg.show()
            app.processEvents()
            dlg.voice_vol_slider.setValue(42)
            dlg._flush_live_volume_save()
            app.processEvents()
            self.assertEqual(get_live_volume(cfg), 42)
            # Persists volume immediately without clicking Save or clobbering other fields
            reloaded = load_voice_settings(cfg)
            self.assertEqual(reloaded["volume_percent"], 42)
            self.assertEqual(reloaded["voice_name"], "ash")
            dlg.reject()
            dlg.close()

            # Simulate waveOutWrite failure on primary (OpenAI) -> fallback to Gemini + meta event
            class _FakeCredStore:
                def get_api_key(self, name: str) -> str:
                    return {"openai": "sk_fake", "gemini": "gk_fake"}.get(name, "")

            attempt_counter = {"n": 0}

            class _FakeWaveOut:
                def __init__(self, **_kw):
                    attempt_counter["n"] += 1
                    self._idx = attempt_counter["n"]

                def write(self, _pcm: bytes, _cancel, **_kw) -> bool:
                    return self._idx >= 2  # Fail first (OpenAI), succeed second (Gemini)

                def drain(self, _cancel) -> None:
                    return None

                def stop(self) -> None:
                    return None

            metas: list[dict] = []
            done = threading.Event()
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "windows"}), \
                 patch.object(voice_service, "_WaveOutStream", _FakeWaveOut), \
                 patch.object(voice_service, "_stream_openai_pcm", return_value=iter([b"\x01\x00" * 120])), \
                 patch.object(voice_service, "_synthesize_gemini_pcm", return_value=(b"\x02\x00" * 120, 24000, "gemini-3.8-flash-lite-tts")):
                ok = voice_service.speak_agent_response(
                    "Testing audio fallback.",
                    config_path=cfg,
                    credential_store=_FakeCredStore(),
                    on_speech_meta=metas.append,
                    on_finished=done.set,
                )
                self.assertTrue(ok)
                self.assertTrue(done.wait(3.0))
            self.assertEqual(len(metas), 1)
            self.assertTrue(metas[0]["fell_back"])
            self.assertEqual(metas[0]["engine_id"], "gemini")
            self.assertIn("openai", metas[0]["fallback_reason"])

            # With fallback='none' and failing primary write -> on_error fires loudly
            save_voice_settings({"tts_engine": "openai", "tts_fallback_engine": "none", "volume_percent": 80}, config_path=cfg)
            errs: list[str] = []
            done2 = threading.Event()

            class _AlwaysFailWaveOut:
                def __init__(self, **_kw):
                    pass

                def write(self, _pcm: bytes, _cancel, **_kw) -> bool:
                    return False

                def drain(self, _cancel) -> None:
                    return None

                def stop(self) -> None:
                    return None

            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "windows"}), \
                 patch.object(voice_service, "_WaveOutStream", _AlwaysFailWaveOut), \
                 patch.object(voice_service, "_stream_openai_pcm", return_value=iter([b"\x01\x00" * 120])):
                voice_service.speak_agent_response(
                    "Testing strict no-fallback error.",
                    config_path=cfg,
                    credential_store=_FakeCredStore(),
                    on_error=errs.append,
                    on_finished=done2.set,
                )
                self.assertTrue(done2.wait(3.0))
            self.assertEqual(len(errs), 1)
            self.assertIn("openai", errs[0].lower())

    def test_voice_companion_all_8_providers_primary_and_fallback(self):
        from voice_companion import VoiceCompanion

        all_8 = ("gemini", "openai", "deepseek", "groq", "cerebras", "qwen", "cohere", "mistral")

        class _AllCreds:
            def get_api_key(self, name: str) -> str:
                return f"key_{name}" if name in all_8 else ""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            vc = VoiceCompanion(config_path=cfg, credential_store=_AllCreds())
            cands = vc._build_provider_candidates(talk_only=True, preferred_provider="qwen", fallback_provider="mistral")
            names = [n for n, _fn in cands]
            for req_p in all_8:
                self.assertIn(req_p, names)
            self.assertEqual(names[0], "qwen")
            self.assertEqual(names[1], "mistral")

            no_fb = vc._build_provider_candidates(talk_only=True, preferred_provider="qwen", fallback_provider="none")
            self.assertEqual([n for n, _fn in no_fb], ["qwen"])

            # Simulate primary ('qwen') failing -> fallback ('mistral') answers with explicit fallback metadata
            def _fail_qwen(_p: str) -> str:
                raise RuntimeError("qwen 503 timeout")

            def _ok_mistral(_p: str) -> str:
                return "Mistral answering after Qwen timed out."

            with patch.object(
                vc,
                "_build_provider_candidates",
                side_effect=lambda **_kw: (
                    setattr(vc, "_last_models", {"qwen": "Qwen/Qwen3.8-27B", "mistral": "mistral-small-latest"}),
                    setattr(vc, "_last_requested_provider", "qwen"),
                    setattr(vc, "_candidate_skip_reasons", []),
                    [("qwen", _fail_qwen), ("mistral", _ok_mistral)],
                )[-1],
            ):
                dec = vc.respond("Say hello", talk_only=True)
            self.assertEqual(dec.provider_used, "mistral")
            self.assertEqual(dec.model_used, "mistral-small-latest")
            self.assertEqual(dec.requested_provider, "qwen")
            self.assertTrue(dec.fell_back)
            self.assertIn("qwen", dec.fallback_reason.lower())

    def test_voice_ui_brain_speaker_badges_handoff_memory_and_zero_clipping(self):
        from memory_service import MemoryService
        from palace_gui import ManageAIsDialog, PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore
        from voice_companion import VoiceCompanionDecision
        from voice_service import is_loopback_audio_device

        self.assertTrue(is_loopback_audio_device("Stereo Mix (Realtek(R) Audio)"))
        self.assertFalse(is_loopback_audio_device("Microphone (Realtek(R) Audio)"))

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cfg = tmp_p / "palace_config.json"
            mem_db = tmp_p / "mem.db"
            store = SessionStore(tmp_p)
            win = PalaceWindow(
                store=store,
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True, "deepseek": True, "groq": True},
                config_path=cfg,
            )
            win._memory_db_path = lambda: mem_db
            try:
                win.show()
                # 1. Verify MemoryService import works end-to-end in Voice Memory helpers
                saved = win._save_voice_memories(
                    [{"summary": "Fav editor", "fact": "Brett prefers Neovim with Lua"}],
                    author="deepseek",
                )
                self.assertEqual(len(saved), 1)
                win._persist_voice_exchange("🎙 Remember my tea order", "Noted, peppermint tea!", provider_used="deepseek")
                ms = MemoryService(db_path=mem_db)
                self.assertIn("Neovim", ms.search("Neovim").context)
                self.assertIn("peppermint tea", ms.search("peppermint tea").context)

                # 2. Verify 🧠 Thinking AI + 🔊 Speaking Voice attribution & switch/fallback dividers in chat HTML
                dec1 = VoiceCompanionDecision(
                    action="chat",
                    spoken_reply="Hi from DeepSeek.",
                    provider_used="deepseek",
                    model_used="deepseek-chat",
                    requested_provider="deepseek",
                )
                idx1 = win._deliver_voice_companion_reply(
                    user_disp="🎙 Hello",
                    raw_user_for_store="🎙 Hello",
                    disp_reply="Hi from DeepSeek.",
                    spoken_reply="Hi from DeepSeek.",
                    decision=dec1,
                    req_gen=win._voice_session_gen,
                    append_user_msg=True,
                    persist_exchange=False,
                    speak_aloud=False,
                )
                win.chat_items[idx1]["tts_label"] = "OpenAI (Sage)"

                dec2 = VoiceCompanionDecision(
                    action="chat",
                    spoken_reply="Now Gemini took over.",
                    provider_used="gemini",
                    model_used="gemini-2.5-flash",
                    requested_provider="openai",
                    fell_back=True,
                    fallback_reason="429 quota",
                )
                idx2 = win._deliver_voice_companion_reply(
                    user_disp="🎙 Switch",
                    raw_user_for_store="🎙 Switch",
                    disp_reply="Now Gemini took over.",
                    spoken_reply="Now Gemini took over.",
                    decision=dec2,
                    req_gen=win._voice_session_gen,
                    append_user_msg=True,
                    persist_exchange=False,
                    speak_aloud=False,
                )
                win.chat_items[idx2]["tts_label"] = "Windows Offline (David)"
                win.chat_items[idx2]["tts_fallback_note"] = "fallback from openai"
                win._render_chat_items()
                app.processEvents()

                html_out = win.chat.toHtml()
                self.assertIn("DeepSeek", html_out)
                self.assertIn("deepseek-chat", html_out)
                self.assertIn("OpenAI (Sage)", html_out)
                self.assertIn("Gemini", html_out)
                self.assertIn("took over", html_out)
                self.assertIn("Windows Offline (David)", html_out)

                # 3. Verify ManageAIsDialog inline external key prompt & loopback mic warning
                dlg = ManageAIsDialog(config_path=cfg, initial_page="Voice & Audio")
                dlg.show()
                app.processEvents()
                cart_idx = dlg.tts_engine_combo.findData("cartesia")
                self.assertGreaterEqual(cart_idx, 0)
                with patch.object(dlg.credential_store, "get_api_key", return_value=""):
                    dlg.tts_engine_combo.setCurrentIndex(cart_idx)
                    app.processEvents()
                    self.assertFalse(dlg.tts_inline_key_frame.isHidden())
                    sys_idx = dlg.tts_engine_combo.findData("system")
                    dlg.tts_engine_combo.setCurrentIndex(sys_idx)
                    app.processEvents()
                    self.assertTrue(dlg.tts_inline_key_frame.isHidden())
                dlg.mic_device_combo.addItem("Stereo Mix (Realtek(R) Audio)", "Stereo Mix (Realtek(R) Audio)")
                dlg.mic_device_combo.setCurrentText("Stereo Mix (Realtek(R) Audio)")
                app.processEvents()
                self.assertFalse(dlg.mic_loopback_warn_lbl.isHidden())
                dlg.reject()
                dlg.close()

                # 4. Verify zero clipping at 1024x700 and 1120x740 with 🧠 + 🔊 pills + Live Voice + Busy controls
                win._activate_talk_only_mode(auto_start_live_voice=False)
                win.voice_level_badge.setText("🎙 ▁▂▃▄▅▆ 42% · Listening")
                win.voice_level_badge.show()
                win.voice_mute_btn.show()
                win._sync_composer_live_bar_visibility()
                for w, h in ((1024, 700), (1120, 740)):
                    win.resize(w, h)
                    win.set_busy(False)
                    app.processEvents()
                    a1 = audit_palace_window_geometry(win)
                    self.assertEqual(a1["clipped_widget_count"], 0, msg=f"Voice {w}x{h} clipped: {a1.get('clipped_widgets')}")

                    win.set_busy(True)
                    win._on_voice_level_update(42, "▁▂▃▄▅▆", True)
                    app.processEvents()
                    a2 = audit_palace_window_geometry(win)
                    self.assertEqual(a2["clipped_widget_count"], 0, msg=f"Voice+Busy {w}x{h} clipped: {a2.get('clipped_widgets')}")
                win.set_busy(False)
                win.stop_all_voice_modes()
            finally:
                win._force_quit = True
                win.close()
                app.processEvents()


class AuditFixRegressionTests(unittest.TestCase):
    def test_dpapi_encrypt_fails_closed_when_cryptprotect_fails(self):
        import ctypes
        import credential_store

        if os.name != "nt":
            return
        with patch.object(ctypes.windll.crypt32, "CryptProtectData", return_value=0):
            with self.assertRaises(RuntimeError):
                credential_store.dpapi_encrypt("secret-api-key-123")

    def test_memory_upsert_distinct_bodies_with_same_summary_and_project_fallback(self):
        from memory_service import SQLiteMemoryIndex

        with tempfile.TemporaryDirectory() as tmp:
            idx = SQLiteMemoryIndex(Path(tmp) / "mem.db")
            id1 = idx.upsert("Repeated title", "First distinct body", wing="w", project="p1")
            id2 = idx.upsert("Repeated title", "Second distinct body", wing="w", project="p1")
            id1_dup = idx.upsert("Repeated title", "First distinct body", wing="w", project="p1")
            self.assertNotEqual(id1, id2)
            self.assertEqual(id1, id1_dup)
            self.assertEqual(idx.count(wing="w"), 2)

            idx.upsert("Other project note", "Other secret", wing="w", project="p2")
            no_kw_p1 = idx.search("!!!", wing="w", project="p1", limit=10)
            self.assertTrue(all(item.get("project") == "p1" for item in no_kw_p1))

    def test_access_policy_command_bypass_defenses_and_optional_read_block(self):
        from access_policy import evaluate_command_access, evaluate_path_access
        from workspace_tools import execute_readonly_workspace_tools_in_text

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "workspace"
            secret = parent / "Secret"
            secret.mkdir(parents=True)
            secret_file = secret / "notes.txt"
            secret_file.write_text("top secret line\n", encoding="utf-8")

            perms = {
                "permission_mode": "turbo",
                "write_exclusions": [{"path": str(secret), "include_subdirs": True}],
            }
            rel_dec = evaluate_command_access(r"del Secret\notes.txt", cwd=parent, permissions=perms)
            self.assertEqual((rel_dec.decision, rel_dec.excluded), ("ask", True))

            enc_dec = evaluate_command_access("powershell -EncodedCommand ZABlAGwA", cwd=parent, permissions=perms)
            self.assertEqual((enc_dec.decision, enc_dec.excluded), ("ask", True))

            with patch.dict(os.environ, {"PALACE_TEST_SECRET": str(secret)}):
                env_dec = evaluate_command_access(r"del %PALACE_TEST_SECRET%\notes.txt", cwd=root, permissions=perms)
                self.assertEqual((env_dec.decision, env_dec.excluded), ("ask", True))

            ok_dec = evaluate_command_access(
                "python -m unittest",
                cwd=r"E:\Visual_studio\Palace",
                permissions={
                    "permission_mode": "turbo",
                    "write_exclusions": [
                        {"path": "C:\\", "include_subdirs": False},
                        {"path": "E:\\", "include_subdirs": False},
                    ],
                },
            )
            self.assertEqual((ok_dec.decision, ok_dec.excluded), ("allow", False))

            # Optional block_reads blocks [FILE_LIST] and [FILE_READ] cleanly
            read_perms = {
                "permission_mode": "turbo",
                "write_exclusions": [{"path": str(secret), "include_subdirs": True, "block_reads": True}],
            }
            r_dec = evaluate_path_access(secret_file, "read", permissions=read_perms)
            self.assertEqual((r_dec.decision, r_dec.excluded), ("ask", True))
            tool_out = execute_readonly_workspace_tools_in_text(
                f'[FILE_LIST path="{secret}"]\n[FILE_READ path="{secret_file}"]',
                project_folder=str(parent),
                permissions=read_perms,
            )
            self.assertIn("FILE_LIST Blocked", tool_out)
            self.assertIn("FILE_READ Blocked", tool_out)
            self.assertNotIn("top secret line", tool_out)

    def test_gui_theme_persistence_stop_with_status_and_voice_reload_guard(self):
        from palace_config import load_ui_settings
        from palace_gui import PalaceWindow
        from session_store import SessionStore

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            cfg = tmp_p / "palace_config.json"
            store = SessionStore(tmp_p)
            win = PalaceWindow(
                store=store,
                palace_factory=lambda _ctx: PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(ProviderRegistry())),
                provider_states={"gemini": True},
                config_path=cfg,
            )
            try:
                win._switch_theme_and_persist("light")
                self.assertEqual(load_ui_settings(cfg).get("theme"), "light")

                # stop_active_turn removes aborted user bubble even when trailing system_status exists
                win.chat_items = [
                    {"role": "user", "content": "First question", "speaker": None, "phase": None, "contributors": [], "speaker_messages": [], "idx": 0},
                    {"role": "system_status", "content": "Status: Fallback engaged.", "severity": "info", "speaker": None, "phase": None, "contributors": [], "speaker_messages": [], "idx": 1},
                ]
                win.last_question = "First question"
                win.worker = SimpleNamespace(
                    succeeded=SimpleNamespace(disconnect=lambda: None),
                    failed=SimpleNamespace(disconnect=lambda: None),
                    finished=SimpleNamespace(disconnect=lambda: None),
                    requestInterruption=lambda: None,
                    quit=lambda: None,
                    wait=lambda _ms=0: True,
                )
                win.stop_active_turn()
                self.assertFalse(any(it.get("role") == "user" for it in win.chat_items))

                # _check_external_session_updates must skip when _voice_threads has active workers
                win.worker = None
                win._voice_threads = [object()]
                with patch.object(win, "load_history", side_effect=AssertionError("Must not reload during voice turn")):
                    win._check_external_session_updates()
            finally:
                win._voice_threads = []
                win._force_quit = True
                win.close()
                app.processEvents()

    def test_synthesizer_and_orchestrator_strip_autopatch_banner_in_non_autopatch_turn(self):
        fake_two = {
            "gemini": ProviderResult(provider_name="gemini", response=ProviderResponse(text="Analysis A", provider="gemini")),
            "groq": ProviderResult(provider_name="groq", response=ProviderResponse(text="Analysis B", provider="groq")),
        }
        spy = _StubProvider(
            "gemini",
            lambda _p: "Summary text.\n⚡ [AUTOPATCH STAGED: REBOOTING TO CONTINUE NEXT STEP]",
        )
        syn = PalaceSynthesizer("gemini", spy)
        syn.synthesize("Audit this code", fake_two, allow_autopatch_banner=False)
        self.assertNotIn("AUTOPATCH STAGED", spy.calls[-1])

        reg = ProviderRegistry()
        reg.register("gemini", _StubProvider("gemini", lambda _p: "Note.\n⚡ [AUTOPATCH STAGED: REBOOTING TO CONTINUE NEXT STEP]"))
        orch = PalaceOrchestrator(_FakeMemory(), ProviderDispatcher(reg), synthesizer=PalaceSynthesizer("gemini", reg.get("gemini")))
        res = orch.run("Please summarize module behavior", include_context=False)
        self.assertNotIn("AUTOPATCH STAGED", (res.final_answer or "").upper())

    def test_cost_idle_session_voice_and_local_cli_fixes(self):
        from cost_service import _usage_attr_optional_int, estimate_tts_cost_usd
        from idle_service import IdleSessionManager
        from local_cli_provider import LocalCLIProvider
        from session_store import SessionStore
        import voice_service

        self.assertEqual(_usage_attr_optional_int({"input_tokens": 0}, "input_tokens"), 0)
        self.assertIsNone(_usage_attr_optional_int({}, "input_tokens"))
        self.assertEqual(estimate_tts_cost_usd("unknown:bogus-engine", 60.0), 0.0)
        self.assertAlmostEqual(estimate_tts_cost_usd("openai:gpt-4o-mini-tts", 60.0), 0.015, places=6)

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "palace_config.json"
            from palace_config import save_idle_settings
            save_idle_settings({"duration_minutes": 30}, cfg)
            mgr = IdleSessionManager(config_path=cfg)
            mgr.status = "Active"
            mgr.remaining_seconds = 1000
            save_idle_settings({"duration_minutes": 45}, cfg)
            mgr.reload_settings()
            self.assertEqual(mgr.remaining_seconds, 1900)

            s1 = SessionStore(Path(tmp) / "sess")
            s2 = SessionStore(Path(tmp) / "sess")
            ext_id = s2.create()
            s1.rename_from_question(s1.selected, "Local GUI session")
            s1.save()
            s3 = SessionStore(Path(tmp) / "sess")
            self.assertIn(ext_id, {it["id"] for it in s3.sessions})

        # LiveAudioSession._poll_audio resets _restart_attempts after 36 healthy ticks
        sess = voice_service.LiveAudioSession(live_mode=False)
        sess.active = True
        sess._restart_attempts = 2
        sess._io_device = SimpleNamespace(readAll=lambda: b"\x01\x00" * 160)
        for _ in range(36):
            sess._poll_audio()
        self.assertEqual(sess._restart_attempts, 0)

        # _WaveOutStream.__init__ clamps channels/bits_per_sample before building WAVEFORMATEX
        if os.name == "nt":
            import ctypes
            captured_wfx = []

            class _FakeWinmm:
                def waveOutOpen(self, _hwo, _dev, wfx_ptr, *_rest):
                    captured_wfx.append(wfx_ptr._obj)
                    return 0

            with patch.dict(os.environ, {"QT_QPA_PLATFORM": ""}), \
                 patch.object(voice_service, "_configure_winmm_prototypes"), \
                 patch.object(ctypes.windll, "winmm", _FakeWinmm()):
                voice_service._WaveOutStream(sample_rate=0, channels=0, bits_per_sample=0)
                voice_service._WaveOutStream(sample_rate=0, channels=0, bits_per_sample=4)
            self.assertEqual(len(captured_wfx), 2)
            self.assertEqual((captured_wfx[0].nChannels, captured_wfx[0].wBitsPerSample, captured_wfx[0].nBlockAlign), (1, 16, 2))
            self.assertEqual((captured_wfx[1].nChannels, captured_wfx[1].wBitsPerSample, captured_wfx[1].nBlockAlign), (1, 8, 1))

        # LocalCLIProvider guards Windows >28KB argv prompts cleanly and wraps TimeoutExpired
        cli_codex = LocalCLIProvider("codex", cli_path="codex.exe")
        with patch("local_cli_provider.get_mcp_depth", return_value=0), \
             patch("local_cli_provider.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok-stdin", stderr="")) as mrun:
            big_prompt = "x" * 30000
            out = cli_codex.generate(big_prompt)
            self.assertEqual(out.text, "ok-stdin")
            if os.name == "nt":
                self.assertEqual(mrun.call_args.kwargs.get("input"), big_prompt)

        import subprocess as _sp
        with patch("local_cli_provider.get_mcp_depth", return_value=0), \
             patch("local_cli_provider.subprocess.run", side_effect=_sp.TimeoutExpired(cmd=["codex.exe"], timeout=10)):
            with self.assertRaises(RuntimeError) as ctx_err:
                cli_codex.generate("short prompt")
            self.assertIn("timed out", str(ctx_err.exception).lower())


class Round2AndSidebarUpgradeTests(unittest.TestCase):
    def test_batch_d_agent_mail_read_unread_and_backend_guards(self):
        from idle_service import IdleMailboxStore
        from orchestrator import PalaceRunResult, PalaceSynthesizer
        from palace_gui import PalaceWindow
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mb_path = root / "mailbox.json"
            mb = IdleMailboxStore(path=mb_path)
            ok1, m1 = mb.send_agent_email("gemini", "Audit Report", "Found two bugs.", link="audit.md")
            ok2, m2 = mb.send_agent_email("deepseek", "Perf Plan", "Batch SQLite hydration.")
            self.assertTrue(ok1 and ok2 and isinstance(m1, dict) and isinstance(m2, dict))
            self.assertEqual(mb.unread_count(), 2)

            self.assertTrue(mb.set_read(m1["id"], True))
            self.assertEqual(mb.unread_count(), 1)
            self.assertTrue(mb.mark_unread(m1["id"]))
            self.assertEqual(mb.unread_count(), 2)
            marked = mb.mark_all_read()
            self.assertEqual(marked, 2)
            self.assertEqual(mb.unread_count(), 0)
            mb.mark_unread(m2["id"])

            app = QApplication.instance() or QApplication([])
            cfg = root / "palace_config.json"
            store = SessionStore(root / "sessions")
            win = PalaceWindow(
                store=store,
                palace_factory=lambda ctx: PalaceOrchestrator(
                    SimpleNamespace(search=lambda _q: SimpleNamespace(memories=[], formatted="")),
                    ProviderDispatcher(ProviderRegistry()),
                    context_service=ctx,
                ),
                provider_states={"gemini": True},
                config_path=cfg,
            )
            win.idle_manager.mailbox = mb
            win.resize(1024, 700)
            win.show()
            win._toggle_agent_mail_view(True)
            win._refresh_agent_mail_tab(suppress_auto_read=True)
            app.processEvents()

            self.assertGreaterEqual(win.mail_list.count(), 2)
            row0_txt = win.mail_list.item(0).text()
            self.assertTrue("[UNREAD]" in row0_txt or "[READ]" in row0_txt, msg=row0_txt)

            # Selecting row updates it to READ, then toggling marks it back to UNREAD without auto-reading
            win.mail_list.setCurrentRow(0)
            app.processEvents()
            self.assertIn("READ", win.mail_header_label.text())
            win._toggle_selected_mail_read_state()
            app.processEvents()
            self.assertIn("[UNREAD]", win.mail_list.currentItem().text())
            self.assertIn("UNREAD", win.mail_header_label.text())

            win._mark_all_mail_read()
            app.processEvents()
            self.assertEqual(mb.unread_count(), 0)

            for w_sz, h_sz in ((1024, 700), (1120, 740)):
                win.resize(w_sz, h_sz)
                app.processEvents()
                aud = audit_palace_window_geometry(win)
                self.assertEqual(
                    aud["clipped_widget_count"],
                    0,
                    msg=f"Tab2 Agent Mail clipped at {w_sz}x{h_sz}: {aud.get('clipped_widgets')}",
                )
            win.close()

        # Read-only advisory prompt should NOT trigger autopatch even with fix words
        adv = detect_organic_turn_intents(
            "Run a read-only advisory audit on Fairybread and find bugs, do not edit any files."
        )
        self.assertFalse(adv["self_code_change_intent"])
        self.assertFalse(adv["auto_approved"])
        parsed_ro = parse_turn_commands("Run a read-only advisory audit on Fairybread and fix bugs, do not edit files.")
        self.assertFalse(parsed_ro["autopatch"])
        self.assertFalse(parsed_ro["self_code_change_intent"])
        self.assertTrue(parse_turn_commands("/restore v0.92 /restore v0.92a")["multiple_restores"])
        real_fix = detect_organic_turn_intents(
            "Fix the Fairybread settings panel crash on startup"
        )
        self.assertTrue(real_fix["self_code_change_intent"])

        # ContextService handles missing LOCALAPPDATA & concurrent appends safely
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LOCALAPPDATA", None)
                ctx_default = ContextService(Path(tmp) / "nested" / "ctx.jsonl")
                self.assertTrue(ctx_default.path.parent.exists())

            ctx_conc = ContextService(Path(tmp) / "conc" / "ctx.jsonl", session_id="s1")
            errs: list[Exception] = []

            def _writer(tid: int):
                try:
                    for k in range(5):
                        ctx_conc.append("user", f"msg-{tid}-{k}")
                except Exception as exc:
                    errs.append(exc)

            threads = [threading.Thread(target=_writer, args=(t,)) for t in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=5.0)
            self.assertEqual(errs, [])
            lines = ctx_conc.path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 20)
            for ln in lines:
                json.loads(ln)

        # PalaceRunResult uses peer_rounds fallback & internal TypeError propagates cleanly
        res_peer = PalaceRunResult(
            question="test",
            prompt="test",
            memory_context="",
            memory_error=None,
            provider_results={},
            peer_rounds=[
                {
                    "deepseek": ProviderResult(
                        provider_name="deepseek",
                        response=ProviderResponse(text="Peer answer", model="stub"),
                    ),
                }
            ],
        )
        self.assertEqual(res_peer.contributors, ["deepseek"])
        self.assertEqual(res_peer.final_answer, "Peer answer")

        class _BuggyTypeErrorDispatcher:
            def __init__(self):
                self.calls = 0

            def dispatch(self, prompt, provider_names=None, **_kwargs):
                self.calls += 1
                raise TypeError("internal dispatch type bug")

        bug_disp = _BuggyTypeErrorDispatcher()
        reg = ProviderRegistry()
        reg.register("gemini", _StubProvider("gemini", lambda _p: "ok"))
        orch = PalaceOrchestrator(
            SimpleNamespace(search=lambda _q: SimpleNamespace(memories=[], formatted="")),
            bug_disp,
            synthesizer=PalaceSynthesizer("gemini", reg.get("gemini")),
        )
        with self.assertRaises(TypeError):
            orch.run("hello", provider_names=["gemini"], include_context=False, include_memory=False)
        self.assertEqual(bug_disp.calls, 1)

    def test_batch_e_cancel_hydration_and_theme_caches(self):
        import threading
        import palace_theme
        from memory_service import SQLiteMemoryIndex

        class _SlowProvider(AIProvider):
            def generate(self, _prompt: str) -> ProviderResponse:
                time.sleep(2.5)
                return ProviderResponse(text="too late", model="slow")

        reg = ProviderRegistry()
        reg.register("gemini", _SlowProvider())
        disp = ProviderDispatcher(reg)
        cancel_ev = threading.Event()
        threading.Timer(0.1, cancel_ev.set).start()
        t0 = time.monotonic()
        out = disp.dispatch("hello", ["gemini"], per_provider_timeout=5.0, cancel_event=cancel_ev)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.7)
        self.assertIn("Cancelled", out["gemini"].error or "")

        with tempfile.TemporaryDirectory() as tmp:
            idx = SQLiteMemoryIndex(Path(tmp) / "mem.db")
            mid1 = idx.upsert("Alpha pref", "Body text one for batch hydration", wing="gpt_palace")
            mid2 = idx.upsert("Beta fact", "Body text two for batch hydration", wing="gpt_palace")
            recent = idx.list_memories(wing="gpt_palace", limit=10)
            by_id = {m["id"]: m["body"] for m in recent}
            self.assertEqual(by_id[mid1], "Body text one for batch hydration")
            self.assertEqual(by_id[mid2], "Body text two for batch hydration")
            hits = idx.search("hydration", wing="gpt_palace", limit=10)
            self.assertEqual(len(hits), 2)
            self.assertIn("batch hydration", hits[0]["body"])

            # Theme dict cache + Markdown SVG cache invalidation when PNG deleted
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                t1 = palace_theme.load_theme_dict("dark")
                t1["bg_main"] = "#123456"
                t2 = palace_theme.load_theme_dict("dark")
                self.assertNotEqual(t2["bg_main"], "#123456")

                md_svg = "```svg\n<svg viewBox='0 0 100 50'><rect width='100' height='50' fill='red'/></svg>\n```"
                html1 = format_markdown_and_drawings(md_svg)
                self.assertIn("<img src=", html1)
                gen_imgs = list(palace_theme.get_generated_images_dir().glob("*.png"))
                self.assertTrue(gen_imgs)
                for p_img in gen_imgs:
                    p_img.unlink()
                html2 = format_markdown_and_drawings(md_svg)
                self.assertIn("<img src=", html2)
                self.assertTrue(list(palace_theme.get_generated_images_dir().glob("*.png")))

    def test_batch_f_zipslip_version_voice_and_watchdog(self):
        import threading
        import zipfile
        from backup_service import restore_full_backup_zip
        from palace_config import bump_minor_letter_version
        import palace_watchdog
        import voice_service

        with tempfile.TemporaryDirectory() as tmp:
            evil_zip = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(evil_zip, "w") as zf:
                zf.writestr("../evil.txt", "pwned")
            with self.assertRaises(ValueError):
                restore_full_backup_zip(evil_zip, config_path=Path(tmp) / "cfg.json", appdata_root=Path(tmp) / "app")

        self.assertEqual(bump_minor_letter_version("0.9.1A"), "0.9.1B")
        self.assertEqual(bump_minor_letter_version("0.9.1Z"), "0.9.2A")

        with self.assertRaises(ValueError):
            list(voice_service._stream_cartesia_pcm("hello", api_key="   ", voice_id="v1"))

        ev = threading.Event()
        ev.set()
        pcm, _sr = voice_service._synthesize_groq_orpheus_pcm("hello world", api_key="gsk_fake", cancel_event=ev)
        self.assertEqual(pcm, b"")

        captured_ps: list[list[str]] = []
        with patch.object(
            palace_watchdog.subprocess,
            "run",
            side_effect=lambda cmd, **_kw: (captured_ps.append(cmd), SimpleNamespace(returncode=0))[1],
        ):
            palace_watchdog._stop_existing_palace_gui()
        self.assertTrue(captured_ps)
        ps_text = captured_ps[0][-1]
        self.assertIn("Name LIKE 'python%'", ps_text)
        self.assertIn(str(os.getpid()), ps_text)

    def test_batch_g_sidebar_actions_spinner_unread_and_archive(self):
        from PySide6.QtCore import QRect, Qt
        from palace_gui import SIDEBAR_META_ROLE, PalaceWindow, SidebarSessionList
        from palace_ouroboros import audit_palace_window_geometry
        from session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SessionStore(root / "sessions")
            p1 = store.create_project("AlphaProj")
            s1 = store.selected
            s2 = store.create(project_id=p1)
            store.rename_from_question(s2, "Second Discussion")

            self.assertEqual(store.rename_session(s2, "Renamed Discussion"), "Renamed Discussion")
            self.assertTrue(store.set_unread(s1, True))
            self.assertTrue(store.set_archived(s1, True))
            dup_id = store.duplicate_session(s2)
            self.assertNotEqual(dup_id, s2)
            store.delete_session(dup_id)
            store.save()
            self.assertNotIn(dup_id, {s["id"] for s in SessionStore(root / "sessions").sessions})

            self.assertEqual(store.rename_project(p1, "BetaProj"), "BetaProj")
            p2 = store.create_project("TempProj")
            store.delete_project(p2)
            store.save()
            self.assertNotIn(p2, {p["id"] for p in SessionStore(root / "sessions").projects})

            # GUI sidebar controls, working spinner, unread dot, and archived toggle
            app = QApplication.instance() or QApplication([])
            win = PalaceWindow(
                store=store,
                palace_factory=lambda ctx: PalaceOrchestrator(
                    SimpleNamespace(search=lambda _q: SimpleNamespace(memories=[], formatted="")),
                    ProviderDispatcher(ProviderRegistry()),
                    context_service=ctx,
                ),
                provider_states={"gemini": True},
                config_path=root / "palace_config.json",
            )
            win.show()
            app.processEvents()

            rects_sess = SidebarSessionList.action_rects_for_item(
                QRect(0, 0, 220, 26),
                {"kind": "session", "id": s2},
            )
            self.assertIn("pin_rect", rects_sess)
            self.assertIn("menu_rect", rects_sess)
            rects_proj = SidebarSessionList.action_rects_for_item(
                QRect(0, 0, 220, 26),
                {"kind": "project", "id": p1},
            )
            self.assertIn("menu_rect", rects_proj)
            self.assertIn("add_rect", rects_proj)

            # Collapsed archived section should exist with count 1
            roles = [win.session_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(win.session_list.count())]
            self.assertIn("archived_toggle", roles)
            self.assertNotIn(s1, roles)

            # Click archived_toggle expands archived section and reveals s1
            arch_idx = roles.index("archived_toggle")
            win._on_sidebar_item_clicked(win.session_list.item(arch_idx))
            app.processEvents()
            roles_after = [win.session_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(win.session_list.count())]
            self.assertIn(s1, roles_after)
            arch_meta = win.session_list.item(roles_after.index(s1)).data(SIDEBAR_META_ROLE)
            self.assertTrue(arch_meta["unread"])

            # Selecting unread session clears unread flag
            win.session_list.setCurrentRow(roles_after.index(s1))
            app.processEvents()
            self.assertFalse(any(s["id"] == s1 and s.get("unread") for s in store.sessions))

            # Working indicator updates sidebar list & clears cleanly on detach/finish
            win._active_working_session_id = s2
            win.pulse_step = 2
            win._sync_sidebar_working_indicator()
            self.assertEqual(win.session_list.working_session_id, s2)
            win._detach_active_worker()
            self.assertIsNone(win.session_list.working_session_id)

            for w_sz, h_sz in ((1024, 700), (1120, 740)):
                win.resize(w_sz, h_sz)
                app.processEvents()
                aud = audit_palace_window_geometry(win)
                self.assertEqual(
                    aud["clipped_widget_count"],
                    0,
                    msg=f"Main Chat clipped at {w_sz}x{h_sz}: {aud.get('clipped_widgets')}",
                )
            win.close()


if __name__ == "__main__":
    unittest.main()
