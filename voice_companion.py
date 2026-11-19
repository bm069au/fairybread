"""Conversational Front-Desk Voice Companion for Fairybread.

Stays responsive in natural spoken conversation while complex multi-AI tasks,
image renders, and code patches execute asynchronously in the background.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable

from cost_service import emit_llm_cost, extract_sdk_usage_tokens
from credential_store import CredentialStore
from palace_config import CONFIG_PATH, load_enabled_provider_names, load_provider_configs
from voice_service import clean_text_for_speech


@dataclass
class VoiceCompanionDecision:
    action: str  # "chat" | "delegate" | "steer" | "status"
    spoken_reply: str
    delegated_task: str = ""
    steer_note: str = ""
    provider_used: str = ""


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

    def reset(self) -> None:
        self._history.clear()

    def _build_provider_candidates(self) -> list[tuple[str, Callable[[str], str]]]:
        if self._injected_llm is not None:
            return [("injected", self._injected_llm)]

        store = self.credential_store or CredentialStore()
        try:
            p_cfgs = load_provider_configs(self.config_path)
            enabled = set(load_enabled_provider_names(self.config_path))
        except Exception:
            p_cfgs = {}
            enabled = {"deepseek", "gemini", "openai", "groq", "cerebras"}

        candidates: list[tuple[str, Callable[[str], str]]] = []

        # 1. DeepSeek (fast, natural, zero-bloat conversational routing)
        ds_key = store.get_api_key("deepseek")
        if ds_key and ("deepseek" in enabled or not enabled):
            ds_model = str((p_cfgs.get("deepseek") or {}).get("model") or "deepseek-chat").strip() or "deepseek-chat"

            def _call_deepseek(prompt_text: str, _k=ds_key, _m=ds_model) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url="https://api.deepseek.com", timeout=15.0)
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

            candidates.append(("deepseek", _call_deepseek))

        # 2. Gemini (gemini-4-hydrogen -> configured gemini-4-neon / 2.5-flash)
        gem_key = store.get_api_key("gemini")
        if gem_key and ("gemini" in enabled or not enabled):
            gem_cfg_model = str((p_cfgs.get("gemini") or {}).get("model") or "").strip()

            def _call_gemini(prompt_text: str, _k=gem_key, _cfg_m=gem_cfg_model) -> str:
                from google import genai
                from google.genai import types

                cli = genai.Client(api_key=_k, http_options=types.HttpOptions(timeout=18000))
                models_to_try = ["gemini-4-hydrogen"]
                if _cfg_m and _cfg_m not in models_to_try:
                    models_to_try.append(_cfg_m)
                if "gemini-2.5-flash" not in models_to_try:
                    models_to_try.append("gemini-2.5-flash")
                last_err: Exception | None = None
                for gm in models_to_try:
                    try:
                        r = cli.models.generate_content(model=gm, contents=prompt_text)
                        txt = (getattr(r, "text", "") or "").strip()
                        if txt:
                            in_t, out_t = extract_sdk_usage_tokens(r, prompt_text=prompt_text, output_text=txt)
                            emit_llm_cost("gemini", gm, in_t, out_t, source="voice_companion")
                            return txt
                    except Exception as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"Gemini voice companion call failed: {last_err}")

            candidates.append(("gemini", _call_gemini))

        # 3. OpenAI (gpt-5-mini)
        oai_key = store.get_api_key("openai")
        if oai_key and ("openai" in enabled or not enabled):
            oai_model = str((p_cfgs.get("openai") or {}).get("model") or "gpt-5-mini").strip() or "gpt-5-mini"

            def _call_openai(prompt_text: str, _k=oai_key, _m=oai_model) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, timeout=18.0)
                r = cli.responses.create(model=_m, input=prompt_text)
                txt = (getattr(r, "output_text", "") or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(r, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("openai", _m, in_t, out_t, source="voice_companion")
                return txt

            candidates.append(("openai", _call_openai))

        # 4. Groq / Cerebras fast fallbacks
        groq_key = store.get_api_key("groq")
        if groq_key and ("groq" in enabled or not enabled):
            groq_model = str((p_cfgs.get("groq") or {}).get("model") or "llama-3.3-70b-versatile").strip()

            def _call_groq(prompt_text: str, _k=groq_key, _m=groq_model) -> str:
                from openai import OpenAI

                cli = OpenAI(api_key=_k, base_url="https://api.groq.com/openai/v1", timeout=15.0)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=[{"role": "user", "content": prompt_text}],
                    temperature=0.4,
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("groq", _m, in_t, out_t, source="voice_companion")
                return txt

            candidates.append(("groq", _call_groq))

        cer_key = store.get_api_key("cerebras")
        if cer_key and ("cerebras" in enabled or not enabled):
            cer_model = str((p_cfgs.get("cerebras") or {}).get("model") or "gpt-oss-120b").strip()

            def _call_cerebras(prompt_text: str, _k=cer_key, _m=cer_model) -> str:
                from cerebras.cloud.sdk import Cerebras

                cli = Cerebras(api_key=_k, timeout=15.0)
                resp = cli.chat.completions.create(
                    model=_m,
                    messages=[{"role": "user", "content": prompt_text}],
                    max_tokens=450,
                )
                txt = (resp.choices[0].message.content or "").strip()
                in_t, out_t = extract_sdk_usage_tokens(resp, prompt_text=prompt_text, output_text=txt)
                emit_llm_cost("cerebras", _m, in_t, out_t, source="voice_companion")
                return txt

            candidates.append(("cerebras", _call_cerebras))

        return candidates

    def _get_fast_callable(self) -> tuple[str, Callable[[str], str]]:
        cands = self._build_provider_candidates()
        if not cands:
            raise RuntimeError("No fast conversational provider available for Voice Companion.")
        return cands[0]

    def _invoke_fast_llm(self, prompt_text: str) -> tuple[str, str]:
        last_err: Exception | None = None
        for pname, fn in self._build_provider_candidates():
            try:
                out = (fn(prompt_text) or "").strip()
                if out:
                    return out, pname
            except Exception as exc:
                last_err = exc
                continue
        raise RuntimeError(f"Voice companion LLM call failed: {last_err}")

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

        bg_block = (
            f"ACTIVE BACKGROUND CREW STATUS: BUSY\n"
            f"- Running task: {background_question[:240] or '(unspecified)'}\n"
            f"- Live phase: {background_status or 'Working in background'}"
            if background_busy
            else "ACTIVE BACKGROUND CREW STATUS: IDLE (no background task currently running)"
        )

        prompt = (
            "You are Fairybread's live conversational Voice Companion — warm, friendly, natural, relaxed, and intuitive.\n"
            "You talk directly with the user out loud while Fairybread's multi-AI crew can work asynchronously in the background.\n\n"
            f"{bg_block}\n"
            f"RECENT VOICE HISTORY:\n{hist_block}\n"
            f"RECENT WORKSPACE CONTEXT:\n{(recent_chat_snippet or '(none)')[:500]}\n\n"
            f"USER JUST SAID: {utterance}\n\n"
            "Respond ONLY with a single valid JSON object matching this exact schema:\n"
            '{"action": "chat|delegate|steer|status", "spoken_reply": "...", "delegated_task": "...", "steer_note": "..."}\n\n'
            "ROUTING RULES:\n"
            "1. 'chat': Casual talk, follow-up banter, quick questions, brainstorming, or simple explanations you can answer directly right now (even if the background crew is BUSY).\n"
            "2. 'delegate': Complex or heavy work suited to Fairybread's multi-AI team — generating/drawing images, editing/debugging/patching code, deep research, multi-AI comparisons, reading files/emails. "
            "Put a clean self-contained prompt in 'delegated_task', and in 'spoken_reply' give a warm 1-2 sentence handoff letting them know the team started in the background (or queued it if already busy) and they can keep talking with you.\n"
            "3. 'steer': ONLY when BACKGROUND CREW STATUS is BUSY and the user is adjusting, redirecting, or adding constraints to the currently running background task. Put the instruction in 'steer_note' and confirm warmly in 'spoken_reply'.\n"
            "4. 'status': ONLY when BACKGROUND CREW STATUS is BUSY and the user asks how the background work is going. Summarize the live phase naturally in 'spoken_reply'.\n"
            "SPOKEN STYLE RULES:\n"
            "- Keep 'spoken_reply' to 1-3 natural conversational sentences (warm everyday phrasing, contractions okay).\n"
            "- ZERO markdown, ZERO asterisks, ZERO bullet lists, ZERO URLs, ZERO code blocks, and ZERO [bracket tags] in 'spoken_reply'."
        )

        try:
            raw_out, pname = self._invoke_fast_llm(prompt)
        except Exception:
            dec = self._fallback_decision(
                utterance,
                background_busy=background_busy,
                background_status=background_status,
                background_question=background_question,
            )
            self._remember(utterance, dec.spoken_reply)
            return dec

        obj = _extract_json_obj(raw_out)
        if not obj:
            spoken = clean_text_for_speech(raw_out)
            if not spoken:
                dec = self._fallback_decision(
                    utterance,
                    background_busy=background_busy,
                    background_status=background_status,
                    background_question=background_question,
                )
            else:
                dec = VoiceCompanionDecision(action="chat", spoken_reply=spoken, provider_used=pname)
            self._remember(utterance, dec.spoken_reply)
            return dec

        action = str(obj.get("action") or "chat").strip().lower()
        if action not in {"chat", "delegate", "steer", "status"}:
            action = "chat"
        spoken = clean_text_for_speech(str(obj.get("spoken_reply") or ""))
        delegated_task = str(obj.get("delegated_task") or "").strip()
        steer_note = str(obj.get("steer_note") or "").strip()

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
            else:
                spoken = "Gotcha."

        dec = VoiceCompanionDecision(
            action=action,
            spoken_reply=spoken,
            delegated_task=delegated_task if action == "delegate" else "",
            steer_note=steer_note if action == "steer" else "",
            provider_used=pname,
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
