"""Conversational Front-Desk Voice Companion for Fairybread.

Stays responsive in natural spoken conversation while complex multi-AI tasks,
image renders, and code patches execute asynchronously in the background.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Callable

from cost_service import emit_llm_cost, extract_sdk_usage_tokens
from credential_store import CredentialStore
from memory_service import parse_save_memory_tags
from palace_config import (
    CONFIG_PATH,
    format_personalization_prompt_block,
    load_enabled_provider_names,
    load_provider_configs,
)
from voice_service import clean_text_for_speech, load_voice_settings


_RETIRED_GROQ_MODELS = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant"}
_GROQ_VOICE_FALLBACK_CHAIN = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b")


@dataclass
class VoiceCompanionDecision:
    action: str  # "chat" | "delegate" | "steer" | "status"
    spoken_reply: str
    delegated_task: str = ""
    steer_note: str = ""
    provider_used: str = ""
    model_used: str = ""
    requested_provider: str = ""
    fell_back: bool = False
    fallback_reason: str = ""
    memory_saves: list[dict[str, str]] = field(default_factory=list)


_DELEGATE_HINT_RE = re.compile(
    r"\b(draw|paint|sketch|render|illustrat\w*|generate\s+(?:an?\s+)?image|create\s+(?:a\s+)?(?:banner|logo|icon|picture)|"
    r"patch|autopatch|refactor|debug|fix\s+(?:the|a|this)|write\s+(?:a\s+|the\s+)?(?:code|script|function|test|class)|"
    r"research|search\s+(?:my\s+email|inbox|files|folder|the\s+web)|compare\s+all|ask\s+(?:the\s+)?(?:team|council|everyone|all\s+ais))\b",
    re.IGNORECASE,
)
_STATUS_HINT_RE = re.compile(
    r"\b(how(?:'s|\s+is)\s+it\s+going|are\s+they\s+done|progress|status\s+update|still\s+working|what\s+stage)\b",
    re.IGNORECASE,
)
_STEER_HINT_RE = re.compile(
    r"\b(tell\s+them|have\s+them|make\s+sure\s+they|steer|adjust\s+it|change\s+(?:the\s+)?(?:background|color|plan)|instead\s+of)\b",
    re.IGNORECASE,
)


def _extract_json_obj(raw_text: str) -> dict | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


class VoiceCompanion:
    """Fast conversational voice layer that chats naturally and delegates/steers heavy work."""

    def __init__(
        self,
        *,
        config_path: Path = CONFIG_PATH,
        credential_store: CredentialStore | None = None,
        llm_callable: Callable[[str], str] | None = None,
    ):
        self.config_path = config_path
        self.credential_store = credential_store
        self._injected_llm = llm_callable
        self._history: list[tuple[str, str]] = []
        self._lock_history_limit = 8
        self._last_models: dict[str, str] = {}
        self._last_requested_provider: str = ""
        self._candidate_skip_reasons: list[str] = []

    def reset(self) -> None:
        self._history.clear()

    def _build_provider_candidates(
        self,
        *,
        talk_only: bool = False,
        preferred_provider: str = "",
        fallback_provider: str = "",
    ) -> list[tuple[str, Callable[[str], str]]]:
        self._last_models = {}
        self._candidate_skip_reasons = []
        if self._injected_llm is not None:
            self._last_models["injected"] = "custom"
            self._last_requested_provider = "injected"
            return [("injected", self._injected_llm)]

        store = self.credential_store or CredentialStore()
        try:
            p_cfgs = load_provider_configs(self.config_path)
            enabled = set(load_enabled_provider_names(self.config_path))
        except Exception:
            p_cfgs = {}
            enabled = {"deepseek", "gemini", "openai", "groq", "cerebras", "qwen", "cohere", "mistral"}

        try:
            v_cfg = load_voice_settings(self.config_path)
        except Exception:
            v_cfg = {}
        pref = (preferred_provider or str(v_cfg.get("voice_llm_provider") or "auto")).strip().lower() or "auto"
        fb = (fallback_provider or str(v_cfg.get("voice_llm_fallback") or "auto")).strip().lower() or "auto"
        explicit_set = {x for x in (pref, fb) if x not in {"", "auto", "none"}}

        def _is_usable(pname: str) -> bool:
            return (pname in enabled) or (not enabled) or (pname in explicit_set)

        by_name: dict[str, Callable[[str], str]] = {}

        # DeepSeek (fast, natural, zero-bloat conversational routing; skip reasoner in talk_only)
        ds_key = store.get_api_key("deepseek")
        if ds_key and _is_usable("deepseek"):
            ds_model = str((p_cfgs.get("deepseek") or {}).get("model") or "deepseek-chat").strip() or "deepseek-chat"
            if talk_only and "reasoner" in ds_model.lower():
                ds_model = "deepseek-chat"
            self._last_models["deepseek"] = ds_model

            def _call_deepseek(prompt_text: str, _k=ds_key, _m=ds_model) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url="https://api.deepseek.com", timeout=15.0, max_retries=0)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.4,
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("deepseek", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["deepseek"] = _call_deepseek

        # Gemini (in talk_only, prefer hydrogen & 2.5-flash ahead of configured model to avoid thinking lag)
        gem_key = store.get_api_key("gemini")
        if gem_key and _is_usable("gemini"):
            gem_cfg_model = str((p_cfgs.get("gemini") or {}).get("model") or "").strip()
            if talk_only:
                gem_models = ["gemini-4-hydrogen", "gemini-2.5-flash"]
                if gem_cfg_model and gem_cfg_model not in gem_models:
                    gem_models.append(gem_cfg_model)
            else:
                gem_models = ["gemini-4-hydrogen"]
                if gem_cfg_model and gem_cfg_model not in gem_models:
                    gem_models.append(gem_cfg_model)
                if "gemini-2.5-flash" not in gem_models:
                    gem_models.append("gemini-2.5-flash")
            self._last_models["gemini"] = gem_models[0]

            def _call_gemini(prompt_text: str, _k=gem_key, _models=tuple(gem_models)) -> str:
                from google import genai
                from google.genai import types

                cli = genai.Client(api_key=_k, http_options=types.HttpOptions(timeout=18000))
                last_err: Exception | None = None
                for gm in _models:
                    try:
                        r = cli.models.generate_content(model=gm, contents=prompt_text)
                        txt = (getattr(r, "text", "") or "").strip()
                        if txt:
                            self._last_models["gemini"] = gm
                            in_t, out_t = extract_sdk_usage_tokens(r, prompt_text=prompt_text, output_text=txt)
                            emit_llm_cost("gemini", gm, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"Gemini voice companion call failed: {last_err}")

            by_name["gemini"] = _call_gemini

        # OpenAI (skip slow reasoning models in interactive talk_only mode)
        oai_key = store.get_api_key("openai")
        if oai_key and _is_usable("openai"):
            oai_model = str((p_cfgs.get("openai") or {}).get("model") or "gpt-5-mini").strip() or "gpt-5-mini"
            if talk_only and oai_model.lower().startswith(("gpt-5", "o1", "o3", "o4")):
                oai_model = "gpt-4o-mini"
            self._last_models["openai"] = oai_model

            def _call_openai(prompt_text: str, _k=oai_key, _m=oai_model) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, timeout=18.0, max_retries=0)
                r = cli.responses.create(model=_m, input=prompt_text)
                txt = (getattr(r, "output_text", "") or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(r, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("openai", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["openai"] = _call_openai

        # Groq / Cerebras ultra-low-latency conversational endpoints
        groq_key = store.get_api_key("groq")
        if groq_key and _is_usable("groq"):
            cfg_m = str((p_cfgs.get("groq") or {}).get("model") or "").strip()
            primary_gm = cfg_m if (cfg_m and cfg_m.lower() not in _RETIRED_GROQ_MODELS) else _GROQ_VOICE_FALLBACK_CHAIN[0]
            groq_models = tuple(dict.fromkeys([primary_gm, *_GROQ_VOICE_FALLBACK_CHAIN]))
            self._last_models["groq"] = groq_models[0]

            def _call_groq(prompt_text: str, _k=groq_key, _models=groq_models) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url="https://api.groq.com/openai/v1", timeout=15.0, max_retries=0)
                last_err: Exception | None = None
                for gm in _models:
                    try:
                        resp = cli.chat.completions.create(
                            model=gm,
                            messages=[{"role": "user", "content": prompt_text}],
                            temperature=0.4,
                            max_tokens=800,
                        )
                        txt = (resp.choices[0].message.content or "").strip()
                        if txt:
                            self._last_models["groq"] = gm
                            in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                            emit_llm_cost("groq", gm, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"Groq voice companion call failed: {last_err}")

            by_name["groq"] = _call_groq

        cer_key = store.get_api_key("cerebras")
        if cer_key and _is_usable("cerebras"):
            cer_model = str((p_cfgs.get("cerebras") or {}).get("model") or "gpt-oss-120b").strip() or "gpt-oss-120b"
            self._last_models["cerebras"] = cer_model

            def _call_cerebras(prompt_text: str, _k=cer_key, _m=cer_model) -> str:
                from cerebras.cloud.sdk import Cerebras

                cli = Cerebras(api_key=_k, timeout=15.0, max_retries=0)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=[{"role": "user", "content": prompt_text}],
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("cerebras", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["cerebras"] = _call_cerebras

        # Qwen (DeepInfra / DashScope OpenAI-compatible)
        qwen_key = store.get_api_key("qwen")
        if qwen_key and _is_usable("qwen"):
            qwen_cfg = p_cfgs.get("qwen") or {}
            qwen_model = str(qwen_cfg.get("model") or "Qwen/Qwen3.8-27B").strip() or "Qwen/Qwen3.8-27B"
            qwen_base = str(qwen_cfg.get("base_url") or "https://api.deepinfra.com/v1/openai").strip()
            self._last_models["qwen"] = qwen_model

            def _call_qwen(prompt_text: str, _k=qwen_key, _m=qwen_model, _b=qwen_base) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url=_b, timeout=18.0, max_retries=0)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.4,
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("qwen", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["qwen"] = _call_qwen

        # Cohere (command-a / command-r)
        coh_key = store.get_api_key("cohere")
        if coh_key and _is_usable("cohere"):
            coh_model = str((p_cfgs.get("cohere") or {}).get("model") or "command-a-03-2025").strip() or "command-a-03-2025"
            self._last_models["cohere"] = coh_model

            def _call_cohere(prompt_text: str, _k=coh_key, _m=coh_model) -> str:
                import cohere

                cli = cohere.ClientV2(api_key=_k, timeout=18.0)
                resp = cli.chat(model=_m, messages=[{"role": "user", "content": prompt_text}])
                txt = (resp.message.content[0].text or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("cohere", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["cohere"] = _call_cohere

        # Mistral
        mis_key = store.get_api_key("mistral")
        if mis_key and _is_usable("mistral"):
            mis_model = str((p_cfgs.get("mistral") or {}).get("model") or "mistral-small-latest").strip() or "mistral-small-latest"
            self._last_models["mistral"] = mis_model

            def _call_mistral(prompt_text: str, _k=mis_key, _m=mis_model) -> str:
                from mistralai.client import Mistral

                cli = Mistral(api_key=_k, timeout_ms=18000)
                resp = cli.chat.complete(model=_m, messages=[{"role": "user", "content": prompt_text}])
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("mistral", _m, in_t, out_t, source="voice_companion")
                return txt

            by_name["mistral"] = _call_mistral

        base_order = (
            ("groq", "deepseek", "gemini", "openai", "cerebras", "qwen", "cohere", "mistral")
            if talk_only
            else ("deepseek", "gemini", "openai", "groq", "cerebras", "qwen", "cohere", "mistral")
        )

        ordered_names: list[str] = []
        if pref not in {"", "auto"}:
            self._last_requested_provider = pref
            if pref in by_name:
                ordered_names.append(pref)
            else:
                self._candidate_skip_reasons.append(f"{pref}: missing API key")
        else:
            auto_first = next((n for n in base_order if n in by_name), "")
            self._last_requested_provider = auto_first

        if fb == "none":
            if pref not in {"", "auto"}:
                if not ordered_names:
                    return []
                return [(ordered_names[0], by_name[ordered_names[0]])]
            first_auto = next((n for n in base_order if n in by_name), "")
            return [(first_auto, by_name[first_auto])] if first_auto else []

        if fb not in {"", "auto"} and fb in by_name and fb not in ordered_names:
            ordered_names.append(fb)
        elif fb not in {"", "auto"} and fb not in by_name and fb not in ordered_names:
            self._candidate_skip_reasons.append(f"{fb}: fallback missing API key")

        for name in base_order:
            if name in by_name and name not in ordered_names:
                ordered_names.append(name)

        return [(name, by_name[name]) for name in ordered_names]

    def _get_fast_callable(self, *, talk_only: bool = False) -> tuple[str, Callable[[str], str]]:
        cands = self._build_provider_candidates(talk_only=talk_only)
        if not cands:
            raise RuntimeError("No fast conversational provider available for Voice Companion.")
        return cands[0]

    def _invoke_fast_llm_detailed(
        self,
        prompt_text: str,
        *,
        talk_only: bool = False,
        preferred_provider: str = "",
        fallback_provider: str = "",
    ) -> tuple[str, str, str, str, bool, str]:
        cands = self._build_provider_candidates(
            talk_only=talk_only,
            preferred_provider=preferred_provider,
            fallback_provider=fallback_provider,
        )
        req_p = self._last_requested_provider or (cands[0][0] if cands else "")
        errors: list[str] = list(getattr(self, "_candidate_skip_reasons", []) or [])
        if not cands:
            raise RuntimeError(f"Voice companion LLM unavailable: {'; '.join(errors) or 'no configured provider'}")
        for pname, fn in cands:
            try:
                out = (fn(prompt_text) or "").strip()
                if out:
                    model_used = self._last_models.get(pname, "")
                    fell_back = bool(errors) or (bool(req_p) and req_p not in {"auto", "injected", pname})
                    fb_reason = errors[0] if (fell_back and errors) else ""
                    return out, pname, model_used, req_p or pname, fell_back, fb_reason
                errors.append(f"{pname}: empty reply")
            except Exception as exc:
                errors.append(f"{pname}: {exc}")
                continue
        raise RuntimeError(f"Voice companion LLM call failed: {'; '.join(errors)}")

    def _invoke_fast_llm(self, prompt_text: str, *, talk_only: bool = False) -> tuple[str, str]:
        out, pname, _, _, _, _ = self._invoke_fast_llm_detailed(prompt_text, talk_only=talk_only)
        return out, pname

    def _remember(self, user_text: str, spoken_reply: str) -> None:
        self._history.append((user_text, spoken_reply))
        if len(self._history) > self._lock_history_limit:
            self._history = self._history[-self._lock_history_limit :]

    def _fallback_decision(
        self,
        utterance: str,
        *,
        background_busy: bool,
        background_status: str,
        background_question: str,
    ) -> VoiceCompanionDecision:
        u = (utterance or "").strip()
        if background_busy and _STATUS_HINT_RE.search(u):
            msg = background_status or "The AI team is still working through it right now."
            return VoiceCompanionDecision(
                action="status",
                spoken_reply=f"{msg} Feel free to keep talking while they finish up.",
                provider_used="fallback",
            )
        if background_busy and _STEER_HINT_RE.search(u):
            return VoiceCompanionDecision(
                action="steer",
                spoken_reply="Got it, I just passed that note to the AIs working in the background.",
                steer_note=u,
                provider_used="fallback",
            )
        if _DELEGATE_HINT_RE.search(u):
            if background_busy:
                return VoiceCompanionDecision(
                    action="delegate",
                    spoken_reply="Got it, I lined that up right behind the current task so we can keep chatting.",
                    delegated_task=u,
                    provider_used="fallback",
                )
            return VoiceCompanionDecision(
                action="delegate",
                spoken_reply="On it, I've handed that over to the AI team in the background. Keep talking with me while they work.",
                delegated_task=u,
                provider_used="fallback",
            )
        reply = (
            "I heard you, though I couldn't reach a quick chat model just now. "
            "Want me to send that straight to the full AI team?"
        )
        return VoiceCompanionDecision(action="chat", spoken_reply=reply, provider_used="fallback")

    def respond(
        self,
        user_utterance: str,
        *,
        background_busy: bool = False,
        background_status: str = "",
        background_question: str = "",
        recent_chat_snippet: str = "",
        talk_only: bool = False,
        memory_context: str = "",
        allow_memory_write: bool = True,
        preferred_provider: str = "",
        fallback_provider: str = "",
    ) -> VoiceCompanionDecision:
        utterance = (user_utterance or "").strip()
        if not utterance:
            return VoiceCompanionDecision(
                action="chat",
                spoken_reply="Sorry, I didn't quite catch that. Could you say that again?",
                provider_used="local",
            )

        hist_lines = []
        for u_prev, a_prev in self._history[-6:]:
            hist_lines.append(f"User: {u_prev}")
            hist_lines.append(f"You: {a_prev}")
        hist_block = "\n".join(hist_lines) if hist_lines else "(new voice conversation)"

        if allow_memory_write:
            mem_block = (
                f"SHARED MEMORY PALACE CONTEXT:\n{(memory_context or '(none saved yet)')[:1400]}\n"
            )
            mem_rule_talk = (
                "MEMORY PALACE ACCESS (ACTIVE): You DO have direct read & write access to Fairybread's local Shared Memory Palace (do NOT say you cannot access memory). "
                "Use SHARED MEMORY PALACE CONTEXT above to answer personal/project questions. "
                "Whenever the user asks you to remember, store, or save something in the Memory Palace, emit "
                "`[SAVE_MEMORY summary=\"Short title\" fact=\"Exact durable fact\"]` at the very end of your response "
                "(Fairybread saves it silently to memory.db and strips the tag before speaking) and confirm naturally out loud.\n"
            )
        else:
            mem_block = "SHARED MEMORY PALACE CONTEXT: (Disabled — No-History ephemeral mode is ON)\n"
            mem_rule_talk = (
                "MEMORY NOTICE: No-History (ephemeral) mode is currently ON, so tell the user if they ask to store permanent memory that No-History is active.\n"
            )

        pers_block = ""
        try:
            raw_pers = format_personalization_prompt_block(self.config_path, conversational_scale="casual")
            if raw_pers:
                pers_block = raw_pers[:700] + "\n"
        except Exception:
            pers_block = ""

        if talk_only:
            prompt = (
                "You are Fairybread in Talk Mode Only — a warm, relaxed, fast conversational companion.\n"
                "There is NO background council, NO code execution, NO image generation, and NO web tools active right now.\n"
                f"{pers_block}"
                f"{mem_rule_talk}"
                "Have a natural conversation directly with the user. If they ask for deep coding, image generation, or multi-AI analysis, "
                "give a brief friendly answer and mention they can switch back to Work Mode, Code AIs, or Graphics anytime.\n\n"
                f"{mem_block}"
                f"RECENT VOICE HISTORY:\n{hist_block}\n"
                f"RECENT WORKSPACE CONTEXT:\n{(recent_chat_snippet or '(none)')[:500]}\n\n"
                f"USER JUST SAID: {utterance}\n\n"
                "SPOKEN STYLE RULES:\n"
                "- Reply in plain natural conversational sentences only (1-3 short everyday sentences, contractions okay).\n"
                "- Follow natural topic shifts, jokes, and side tangents effortlessly without dragging the user back to older topics.\n"
                "- ZERO JSON, ZERO markdown, ZERO asterisks, ZERO bullet lists, ZERO URLs, ZERO code blocks, and ZERO [bracket tags] OTHER than an optional trailing `[SAVE_MEMORY summary=\"...\" fact=\"...\"]` when explicitly storing memory."
            )
            try:
                raw_out, pname, m_used, req_p, fell_back, fb_reason = self._invoke_fast_llm_detailed(
                    prompt,
                    talk_only=True,
                    preferred_provider=preferred_provider,
                    fallback_provider=fallback_provider,
                )
            except Exception as exc:
                dec = VoiceCompanionDecision(
                    action="chat",
                    spoken_reply=(
                        "I heard you, though I couldn't reach your selected chat model just now. "
                        "Try again or pick another Thinking AI."
                    ),
                    provider_used="fallback",
                    requested_provider=preferred_provider or self._last_requested_provider,
                    fell_back=True,
                    fallback_reason=str(exc),
                )
                self._remember(utterance, dec.spoken_reply)
                return dec

            obj = _extract_json_obj(raw_out)
            candidate_txt = str(obj.get("spoken_reply") or raw_out) if (isinstance(obj, dict) and obj.get("spoken_reply")) else raw_out
            stripped_txt, parsed_saves = parse_save_memory_tags(candidate_txt, replace_with_badge=False)
            if not allow_memory_write:
                parsed_saves = []
            spoken = clean_text_for_speech(stripped_txt) or ("Saved that to your Memory Palace." if parsed_saves else "Gotcha.")
            dec = VoiceCompanionDecision(
                action="chat",
                spoken_reply=spoken,
                delegated_task="",
                steer_note="",
                provider_used=pname,
                model_used=m_used,
                requested_provider=req_p,
                fell_back=fell_back,
                fallback_reason=fb_reason,
                memory_saves=parsed_saves,
            )
            self._remember(utterance, dec.spoken_reply)
            return dec

        bg_block = (
            f"ACTIVE BACKGROUND CREW STATUS: BUSY\n"
            f"- Running task: {background_question[:240] or '(unspecified)'}\n"
            f"- Live phase: {background_status or 'Working in background'}"
            if background_busy
            else "ACTIVE BACKGROUND CREW STATUS: IDLE (no background task currently running)"
        )
        mem_json_rule = (
            "- Direct Memory Access: You DO have direct read & write access to Fairybread's local Shared Memory Palace (do NOT say you lack memory access). "
            "Use SHARED MEMORY PALACE CONTEXT to answer recall questions, and if the user asks to store/save/remember something, "
            "set optional `\"save_memory\": {\"summary\": \"Short title\", \"fact\": \"Exact durable fact\"}` in the JSON (keeping `action=\"chat\"`) and confirm naturally in `spoken_reply`.\n"
            if allow_memory_write
            else "- No-History (ephemeral) mode is ON: omit `save_memory` and let the user know if they ask to save memory.\n"
        )

        prompt = (
            "You are Fairybread's live conversational Voice Companion — warm, friendly, natural, relaxed, and intuitive.\n"
            "You talk directly with the user out loud while Fairybread's multi-AI crew can work asynchronously in the background.\n\n"
            f"{pers_block}"
            f"{bg_block}\n"
            f"{mem_block}"
            f"RECENT VOICE HISTORY:\n{hist_block}\n"
            f"RECENT WORKSPACE CONTEXT:\n{(recent_chat_snippet or '(none)')[:500]}\n\n"
            f"USER JUST SAID: {utterance}\n\n"
            "Respond ONLY with a single valid JSON object matching this exact schema:\n"
            '{"action": "chat|delegate|steer|status", "spoken_reply": "...", "delegated_task": "...", "steer_note": "...", "save_memory": null}\n\n'
            "ROUTING RULES:\n"
            f"{mem_json_rule}"
            "1. 'chat': Casual talk, follow-up banter, quick questions, memory recalls/saves, brainstorming, or simple explanations you can answer directly right now (even if the background crew is BUSY).\n"
            "2. 'delegate': Complex or heavy work suited to Fairybread's multi-AI team — generating/drawing images, editing/debugging/patching code, deep research, multi-AI comparisons, reading files/emails. "
            "Put a clean self-contained prompt in 'delegated_task', and in 'spoken_reply' give a warm 1-2 sentence handoff letting them know the team started in the background (or queued it if already busy) and they can keep talking with you.\n"
            "3. 'steer': ONLY when BACKGROUND CREW STATUS is BUSY and the user is adjusting, redirecting, or adding constraints to the currently running background task. Put the instruction in 'steer_note' and confirm warmly in 'spoken_reply'.\n"
            "4. 'status': ONLY when BACKGROUND CREW STATUS is BUSY and the user asks how the background work is going. Summarize the live phase naturally in 'spoken_reply'.\n"
            "SPOKEN STYLE RULES:\n"
            "- Keep 'spoken_reply' to 1-3 natural conversational sentences (warm everyday phrasing, contractions okay).\n"
            "- Follow natural topic shifts, jokes, and side tangents effortlessly without dragging the user back to older topics.\n"
            "- ZERO markdown, ZERO asterisks, ZERO bullet lists, ZERO URLs, ZERO code blocks, and ZERO [bracket tags] in 'spoken_reply'."
        )

        try:
            raw_out, pname, m_used, req_p, fell_back, fb_reason = self._invoke_fast_llm_detailed(
                prompt,
                talk_only=False,
                preferred_provider=preferred_provider,
                fallback_provider=fallback_provider,
            )
        except Exception as exc:
            dec = self._fallback_decision(
                utterance,
                background_busy=background_busy,
                background_status=background_status,
                background_question=background_question,
            )
            dec.requested_provider = preferred_provider or self._last_requested_provider
            dec.fell_back = True
            dec.fallback_reason = str(exc)
            self._remember(utterance, dec.spoken_reply)
            return dec

        obj = _extract_json_obj(raw_out)
        if not obj:
            stripped_raw, parsed_raw_saves = parse_save_memory_tags(raw_out, replace_with_badge=False)
            spoken = clean_text_for_speech(stripped_raw)
            if not spoken:
                dec = self._fallback_decision(
                    utterance,
                    background_busy=background_busy,
                    background_status=background_status,
                    background_question=background_question,
                )
                dec.requested_provider = req_p
                dec.fell_back = True
                dec.fallback_reason = fb_reason or "Empty non-JSON reply"
            else:
                dec = VoiceCompanionDecision(
                    action="chat",
                    spoken_reply=spoken,
                    provider_used=pname,
                    model_used=m_used,
                    requested_provider=req_p,
                    fell_back=fell_back,
                    fallback_reason=fb_reason,
                    memory_saves=parsed_raw_saves if allow_memory_write else [],
                )
            self._remember(utterance, dec.spoken_reply)
            return dec

        action = str(obj.get("action") or "chat").strip().lower()
        if action not in {"chat", "delegate", "steer", "status"}:
            action = "chat"
        raw_reply_field = str(obj.get("spoken_reply") or "")
        stripped_reply, tag_saves = parse_save_memory_tags(raw_reply_field, replace_with_badge=False)
        spoken = clean_text_for_speech(stripped_reply)
        delegated_task = str(obj.get("delegated_task") or "").strip()
        steer_note = str(obj.get("steer_note") or "").strip()

        collected_saves: list[dict[str, str]] = []
        if allow_memory_write:
            raw_sm = obj.get("save_memory")
            sm_items = raw_sm if isinstance(raw_sm, list) else ([raw_sm] if isinstance(raw_sm, dict) else [])
            for sm in sm_items:
                if not isinstance(sm, dict):
                    continue
                fact_v = str(sm.get("fact") or sm.get("body") or sm.get("content") or sm.get("summary") or "").strip()
                sum_v = str(sm.get("summary") or "").strip() or (fact_v[:97] + "..." if len(fact_v) > 100 else fact_v)
                if sum_v and fact_v:
                    collected_saves.append({
                        "summary": sum_v[:140],
                        "fact": fact_v,
                        "project": str(sm.get("project") or "").strip(),
                        "memory_type": str(sm.get("memory_type") or "standing").strip().lower() or "standing",
                    })
            collected_saves.extend(tag_saves)

        if action == "steer" and not background_busy:
            action = "delegate"
            delegated_task = steer_note or delegated_task or utterance
            steer_note = ""
        elif action == "status" and not background_busy:
            action = "chat"

        if action == "delegate" and not delegated_task:
            delegated_task = utterance
        if action == "steer" and not steer_note:
            steer_note = utterance

        if not spoken:
            if action == "delegate":
                spoken = "On it — I've passed that to the AI team in the background. Keep talking with me while they handle it."
            elif action == "steer":
                spoken = "Got it, I sent that update over to the AIs working in the background."
            elif action == "status":
                spoken = background_status or "The team is still working through that task right now."
            elif collected_saves:
                spoken = "Saved that to your Memory Palace."
            else:
                spoken = "Gotcha."

        dec = VoiceCompanionDecision(
            action=action,
            spoken_reply=spoken,
            delegated_task=delegated_task if action == "delegate" else "",
            steer_note=steer_note if action == "steer" else "",
            provider_used=pname,
            model_used=m_used,
            requested_provider=req_p,
            fell_back=fell_back,
            fallback_reason=fb_reason,
            memory_saves=collected_saves,
        )
        self._remember(utterance, dec.spoken_reply)
        return dec

    def summarize_completed_work(
        self,
        original_question: str,
        final_answer: str,
        *,
        contributors: list[str] | None = None,
    ) -> str:
        raw_ans = final_answer or ""
        has_images = "[GENERATE_IMAGE" in raw_ans.upper()
        has_autopatch = ("AUTOPATCH" in raw_ans.upper()) or ("[IDLE_PATCH" in raw_ans.upper())
        cleaned_ans = clean_text_for_speech(raw_ans)
        if not cleaned_ans:
            if has_images:
                return "Your generated images are up on screen now. Want me to tweak anything?"
            return "The AI team finished up and posted the result on screen."

        prompt = (
            "You are Fairybread's Voice Companion giving a quick spoken update because a background AI task just finished.\n"
            f"Original request: {(original_question or '')[:260]}\n"
            f"Contributors: {', '.join(contributors or []) or 'AI team'}\n"
            f"Generated images included: {'yes' if has_images else 'no'}\n"
            f"Code patch applied: {'yes' if has_autopatch else 'no'}\n"
            f"Completed output excerpt:\n{cleaned_ans[:1800]}\n\n"
            "Write a natural, warm spoken summary in 2-3 short conversational sentences (under 360 characters).\n"
            "Tell the user what finished and the key takeaway. If images were rendered, mention they're up on screen. "
            "Do NOT read code, tables, URLs, file paths, or markdown symbols aloud."
        )
        try:
            summary_raw, _ = self._invoke_fast_llm(prompt)
            spoken = clean_text_for_speech(summary_raw)
            if spoken:
                return spoken[:420]
        except Exception:
            pass

        # Fast local fallback: take first 1-2 clean sentences <= 300 chars
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned_ans) if s.strip()]
        out = ""
        for s in sents:
            cand = f"{out} {s}".strip()
            if len(cand) > 300 and out:
                break
            out = cand
            if len(out) >= 180:
                break
        if not out:
            out = cleaned_ans[:280].rsplit(" ", 1)[0].strip() + "."
        if has_images and "image" not in out.lower() and "screen" not in out.lower():
            out = f"Your images are up on screen now. {out}"[:360]
        self._remember(f"[Background completed: {original_question[:80]}]", out)
        return out
