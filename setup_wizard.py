"""First-Run & Re-Runnable Guided Setup Wizard, Selective Backup Restore, and 3-Layer Spend Dashboard."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cost_service import (
    ConversationCostLedger,
    GlobalBillingLedger,
    format_usd_compact,
    get_global_billing_ledger,
)
from credential_store import CredentialStore
from palace_config import (
    CONFIG_PATH,
    OPENROUTER_PRESET_TIERS,
    PROVIDER_CATALOG,
    load_openrouter_hub_settings,
    load_provider_configs,
    save_openrouter_hub_settings,
    save_personalization_settings,
    save_provider_config,
    save_ui_settings,
)


def _style_wizard_card(card: QFrame, obj_name: str, lay=None, pad_h: int = 14, pad_v: int = 12) -> QFrame:
    """Apply scoped QFrame styling so child QLabels never inherit card borders."""
    card.setObjectName(obj_name)
    card.setStyleSheet(
        f"QFrame#{obj_name} {{ background:#131720; border:1px solid #262c3a; border-radius:10px; }}"
    )
    if lay is not None:
        lay.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
    return card


def _make_scrolled_page() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(12)
    scroll.setWidget(inner)
    return scroll, inner, lay


def recommend_setup_plan(
    needs: set[str] | list[str],
    voice_pref: str = "best_deepgram",
    tone_pref: str = "warm",
    billing_pref: str = "openrouter_one_bill",
    budget_pref: str = "balanced",
) -> dict[str, Any]:
    """Compute a concrete, plain-English Fairybread key checklist & config patches from questionnaire answers."""
    norm_needs = {str(n).strip().lower() for n in (needs or set()) if str(n).strip()}
    if not norm_needs:
        norm_needs = {"chat"}
    if "everything" in norm_needs:
        norm_needs.update({"chat", "writing", "learning", "simple_code", "complex_code", "images", "everything"})

    v_pref = (voice_pref or "best_deepgram").strip().lower()
    if v_pref not in {"best_deepgram", "builtin_openrouter", "free_windows"}:
        v_pref = "best_deepgram"

    t_pref = (tone_pref or "warm").strip().lower()
    if t_pref not in {"warm", "balanced", "direct"}:
        t_pref = "warm"

    b_pref = (billing_pref or "openrouter_one_bill").strip().lower()
    if b_pref not in {"openrouter_one_bill", "direct_keys"}:
        b_pref = "openrouter_one_bill"

    bud_pref = (budget_pref or "balanced").strip().lower()
    if bud_pref not in OPENROUTER_PRESET_TIERS:
        bud_pref = "balanced"

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _add_provider_item(prov_id: str, *, subtitle: str, optional: bool = False, supports_balance: bool = False) -> None:
        pid = prov_id.strip().lower()
        if pid in seen_ids:
            return
        seen_ids.add(pid)
        cat = PROVIDER_CATALOG.get(pid, {})
        items.append({
            "id": pid,
            "title": str(cat.get("display_name") or pid.title()),
            "subtitle": subtitle,
            "url": str(cat.get("key_url") or "https://openrouter.ai/settings/keys"),
            "kind": "provider",
            "credential_key": pid,
            "optional": bool(optional),
            "supports_balance": bool(supports_balance),
            "default_model": str(cat.get("default_model") or ""),
            "default_base_url": str(cat.get("default_base_url") or ""),
        })

    def _add_voice_item(eng_id: str, *, title: str, subtitle: str, url: str, optional: bool = False, supports_balance: bool = False) -> None:
        eid = eng_id.strip().lower()
        if eid in seen_ids:
            return
        seen_ids.add(eid)
        items.append({
            "id": eid,
            "title": title,
            "subtitle": subtitle,
            "url": url,
            "kind": "voice",
            "credential_key": eid,
            "optional": bool(optional),
            "supports_balance": bool(supports_balance),
            "default_model": "",
            "default_base_url": "",
        })

    if b_pref == "openrouter_one_bill":
        _add_provider_item(
            "openrouter",
            subtitle=(
                f"One prepaid wallet powers Claude, Gemini, GPT, DeepSeek, Qwen, Mistral & Image Fallback "
                f"({bud_pref.title()} tier preset · strict top-up balance, zero auto-overage)."
            ),
            optional=False,
            supports_balance=True,
        )
        if v_pref == "best_deepgram":
            _add_voice_item(
                "deepgram",
                title="Deepgram Voice (Flux + Aura-2 — Best Spoken Experience)",
                subtitle="Powers natural real-time speech-to-text & 89 expressive voices (~$0.025–$0.03/1k chars; $200 free starter credit).",
                url="https://console.deepgram.com/",
                optional=False,
                supports_balance=True,
            )
        if "images" in norm_needs or "everything" in norm_needs:
            _add_provider_item(
                "gemini",
                subtitle="Optional native Google Imagen 3/4 renderer (Free tier via Google AI Studio; OpenRouter image fallback works even without it).",
                optional=True,
                supports_balance=False,
            )
    else:
        # Direct BYOK keys tailored to selected needs
        _add_provider_item(
            "gemini",
            subtitle="Fast multimodal reasoning, search grounding & native Imagen picture creation (Free tier or pay-as-you-go).",
            optional=False,
        )
        _add_provider_item(
            "openai",
            subtitle="Conversational clarity, writing, and visual composition + optional GPT-4o-mini neural TTS.",
            optional=False,
        )
        if any(k in norm_needs for k in ("writing", "learning", "chat", "complex_code", "everything")):
            _add_provider_item(
                "anthropic",
                subtitle="Claude Sonnet — warm natural prose, university writing & high-EQ dialogue.",
                optional=("everything" not in norm_needs and "writing" not in norm_needs),
            )
        if any(k in norm_needs for k in ("simple_code", "complex_code", "everything")):
            _add_provider_item(
                "deepseek",
                subtitle="High-value coding, debugging & architecture specialist (prepaid top-up wallet).",
                optional=False,
            )
            _add_provider_item(
                "mistral",
                subtitle="Codestral specialist for crisp refactors and syntax review (Free Experiment tier available).",
                optional=("complex_code" not in norm_needs and "everything" not in norm_needs),
            )
        if "everything" in norm_needs:
            _add_provider_item(
                "qwen",
                subtitle="Qwen via DeepInfra — analytical decomposition & code critique.",
                optional=True,
            )
            _add_provider_item(
                "cohere",
                subtitle="Cohere Command — Free Trial tier key great for zero-cost local memory fast-recall.",
                optional=True,
            )
            _add_provider_item(
                "openrouter",
                subtitle="Optional OpenRouter hub key for 300+ extra roleplay, coding & fallback models on 1 prepaid wallet.",
                optional=True,
                supports_balance=True,
            )
        if v_pref == "best_deepgram":
            _add_voice_item(
                "deepgram",
                title="Deepgram Voice (Flux + Aura-2 — Best Spoken Experience)",
                subtitle="Powers natural real-time speech-to-text & 89 expressive voices (~$0.025–$0.03/1k chars; $200 free starter credit).",
                url="https://console.deepgram.com/",
                optional=False,
                supports_balance=True,
            )
        elif v_pref == "builtin_openrouter":
            _add_provider_item(
                "openrouter",
                subtitle="OpenRouter Audio (gpt-audio-mini) — good built-in voice TTS/STT on 1 wallet.",
                optional=False,
                supports_balance=True,
            )

    if v_pref == "best_deepgram":
        voice_patch: dict[str, Any] = {
            "tts_engine": "deepgram",
            "tts_fallback_engine": "openrouter" if b_pref == "openrouter_one_bill" else "auto",
            "deepgram_voice_name": "flux-sienna-en",
        }
    elif v_pref == "builtin_openrouter":
        voice_patch = {
            "tts_engine": "openrouter",
            "tts_fallback_engine": "system",
        }
    else:
        voice_patch = {
            "tts_engine": "system",
            "tts_fallback_engine": "none",
        }

    if t_pref == "warm":
        pers_patch = {
            "base_style": "Friendly",
            "warmth": "More",
            "enthusiasm": "Default",
        }
    elif t_pref == "direct":
        pers_patch = {
            "base_style": "Candid & Direct (No Flattery)",
            "warmth": "Less",
            "enthusiasm": "Less",
        }
    else:
        pers_patch = {
            "base_style": "Friendly",
            "warmth": "Default",
            "enthusiasm": "Less",
        }

    hub_patch = {
        "auto_fill_seats": (b_pref == "openrouter_one_bill"),
        "tier": bud_pref,
        "enable_image_fallback": True,
        "enable_audio_fallback": True,
    }

    return {
        "needs": sorted(norm_needs),
        "voice_pref": v_pref,
        "tone_pref": t_pref,
        "billing_pref": b_pref,
        "openrouter_tier": bud_pref,
        "auto_fill_seats": (b_pref == "openrouter_one_bill"),
        "required_items": items,
        "voice_settings_patch": voice_patch,
        "personalization_patch": pers_patch,
        "hub_settings_patch": hub_patch,
    }


class GuidedSetupWizardDialog(QDialog):
    """Non-destructive 4-page Guided Setup & Selective Backup Restore Wizard."""

    def __init__(
        self,
        parent=None,
        *,
        config_path: Path = CONFIG_PATH,
        credential_store: CredentialStore | None = None,
        initial_page: int = 0,
    ):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self.credential_store = credential_store or CredentialStore()
        self.open_manual_requested = False
        self.restored_anything = False
        self._restored_keys_any = False
        self._current_plan: dict[str, Any] = {}
        self._checklist_widgets: list[dict[str, Any]] = []
        self._selected_zip_path: Path | None = None
        self._zip_info: dict[str, Any] = {}

        self.setWindowTitle("Fairybread — Guided Setup & Restore Wizard")
        self.setWindowFlags(
            (
                self.windowFlags()
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(900, 680)
        self.setMinimumSize(780, 560)
        self.setStyleSheet(
            "QDialog { background:#0d1117; color:#e6edf3; } "
            "QLabel { color:#e6edf3; } "
            "QLineEdit { background:#0b0f17; color:#f0f6fc; border:1px solid #2b313e; border-radius:6px; padding:6px 10px; } "
            "QPushButton { background:#161b22; color:#e6edf3; border:1px solid #30363d; border-radius:6px; padding:6px 12px; font-weight:600; } "
            "QPushButton:hover { border-color:#58a6ff; background:#1f2735; } "
            "QCheckBox, QRadioButton { color:#e6edf3; spacing:8px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.pages_stack = QStackedWidget()
        root.addWidget(self.pages_stack, 1)

        self._build_page0_welcome()
        self._build_page1_questionnaire()
        self._build_page2_checklist()
        self._build_page3_restore()

        eff_page = max(0, min(3, int(initial_page or 0)))
        self.pages_stack.setCurrentIndex(eff_page)

    # ------------------------------------------------------------------ Page 0: Welcome
    def _build_page0_welcome(self):
        scroll, _, lay = _make_scrolled_page()

        title = QLabel("Welcome to Fairybread")
        title.setStyleSheet("font-size:20px; font-weight:700; color:#f0f6fc;")
        lay.addWidget(title)

        sub = QLabel(
            "Everything runs locally on your PC with zero subscriptions and zero vendor lock-in. "
            "Choose how you'd like to get started or reconfigure your workspace:"
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size:13px; color:#8b949e;")
        lay.addWidget(sub)

        existing_provs = []
        try:
            existing_provs = self.credential_store.list_providers()
        except Exception:
            existing_provs = []
        if existing_provs:
            notice_card = QFrame()
            n_lay = QVBoxLayout(notice_card)
            notice_card.setObjectName("wizardExistingKeyNotice")
            notice_card.setStyleSheet(
                "QFrame#wizardExistingKeyNotice { background:#11281b; border:1px solid #22c55e; border-radius:8px; }"
            )
            n_lay.setContentsMargins(12, 8, 12, 8)
            n_lbl = QLabel(
                f"🔒 Detected {len(existing_provs)} existing encrypted key(s) in Windows DPAPI "
                f"({', '.join(existing_provs[:6])}). Re-running Guided Setup is non-destructive and keeps your existing keys safe."
            )
            n_lbl.setWordWrap(True)
            n_lbl.setStyleSheet("color:#86efac; font-size:12px;")
            n_lay.addWidget(n_lbl)
            lay.addWidget(notice_card)

        self.welcome_cards: list[QPushButton] = []

        def _make_choice_card(btn_text: str, desc_text: str, tip: str, accent: str, slot) -> QFrame:
            card = QFrame()
            c_lay = QVBoxLayout(card)
            _style_wizard_card(card, f"welcomeCard_{len(self.welcome_cards)}", c_lay, pad_h=16, pad_v=14)
            c_lay.setSpacing(6)
            btn = QPushButton(btn_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                f"QPushButton {{ background:{accent}; color:#ffffff; border:none; padding:9px 14px; "
                f"border-radius:7px; font-size:13.5px; font-weight:700; text-align:left; }} "
                f"QPushButton:hover {{ opacity:0.92; }}"
            )
            btn.clicked.connect(slot)
            desc = QLabel(desc_text)
            desc.setWordWrap(True)
            desc.setStyleSheet("color:#9da7b3; font-size:12.5px;")
            c_lay.addWidget(btn)
            c_lay.addWidget(desc)
            self.welcome_cards.append(btn)
            return card

        lay.addWidget(_make_choice_card(
            "🧭  1. Guided Setup (Recommended — Easy Step-by-Step)",
            "Answer 5 quick plain-English questions about what you want to do (chat, coding, pictures, best voice), "
            "and Fairybread prepares a tailored key checklist with direct links and live tick-off verification.",
            "Walk through needs questionnaire and generate your customized API key checklist",
            "#1f6feb",
            lambda: self.pages_stack.setCurrentIndex(1),
        ))
        lay.addWidget(_make_choice_card(
            "♻️  2. Restore From Backup (.zip)",
            "Selectively restore your Memory Palace & conversations, your Settings & profiles, and/or your AES-256 encrypted API keys "
            "from one backup or two separate files (Data + Keys).",
            "Open the selective Backup Restore tool",
            "#238636",
            lambda: self.pages_stack.setCurrentIndex(3),
        ))
        lay.addWidget(_make_choice_card(
            "⚙  3. Advanced Manual Setup (Open AI Providers Page)",
            "Skip the walkthrough and jump straight into manual per-provider API key configuration and OpenRouter hub controls.",
            "Close wizard and open Settings -> AI Providers directly",
            "#30363d",
            self._choose_manual_setup,
        ))

        lay.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        later_btn = QPushButton("Close / Skip for Now")
        later_btn.setToolTip("Close the wizard (you can re-open it anytime from Fairybread -> Guided Setup Wizard)")
        later_btn.clicked.connect(self.reject)
        foot.addWidget(later_btn)
        lay.addLayout(foot)

        self.pages_stack.addWidget(scroll)

    def _mark_wizard_completed(self) -> None:
        try:
            save_ui_settings({"setup_wizard_completed": True}, config_path=self.config_path)
        except Exception:
            pass

    def reject(self):
        self._mark_wizard_completed()
        super().reject()

    def _choose_manual_setup(self):
        self.open_manual_requested = True
        self._mark_wizard_completed()
        self.accept()

    # ------------------------------------------------------------------ Page 1: Questionnaire
    def _build_page1_questionnaire(self):
        scroll, _, lay = _make_scrolled_page()

        hdr = QLabel("Step 1 of 2 — What Will You Use Fairybread For?")
        hdr.setStyleSheet("font-size:17px; font-weight:700; color:#f0f6fc;")
        lay.addWidget(hdr)

        # Card A: Use Cases (Multi-select)
        use_card = QFrame()
        u_lay = QVBoxLayout(use_card)
        _style_wizard_card(use_card, "wizardUseCasesCard", u_lay)
        u_lay.setSpacing(6)
        u_hdr = QLabel("<b>1. Pick everything you want to do (select one or more):</b>")
        u_hdr.setTextFormat(Qt.TextFormat.RichText)
        u_lay.addWidget(u_hdr)

        self.need_checks: dict[str, QCheckBox] = {}
        need_specs = [
            ("chat", "💬  Light social chat, daily questions & deep research (replacing generic search)"),
            ("writing", "🎓  University assignments, essays, reports & structured writing"),
            ("learning", "🌍  Learning a language, tutoring & step-by-step explanations"),
            ("simple_code", "🧩  Simple coding, scripts & troubleshooting"),
            ("complex_code", "🛠  Complex coding, software architecture & multi-file engineering"),
            ("images", "🎨  Drawing & creating pictures, banners & visual concepts"),
            ("everything", "🚀  Give me EVERYTHING — most options, full council & best overall experience"),
        ]
        for key, text in need_specs:
            cb = QCheckBox(text)
            cb.setToolTip(f"Include recommendations tailored for: {text}")
            if key == "chat":
                cb.setChecked(True)
            self.need_checks[key] = cb
            u_lay.addWidget(cb)

        def _on_everything_toggled(checked: bool):
            if checked:
                for k, box in self.need_checks.items():
                    if k != "everything":
                        box.setChecked(True)

        self.need_checks["everything"].toggled.connect(_on_everything_toggled)
        lay.addWidget(use_card)

        # Card B: Voice Quality
        voice_card = QFrame()
        v_lay = QVBoxLayout(voice_card)
        _style_wizard_card(voice_card, "wizardVoiceCard", v_lay)
        v_lay.setSpacing(6)
        v_hdr = QLabel("<b>2. Choose your Spoken Voice quality:</b>")
        v_hdr.setTextFormat(Qt.TextFormat.RichText)
        v_lay.addWidget(v_hdr)
        self._voice_group = QButtonGroup(self)
        self.voice_radios: dict[str, QRadioButton] = {}
        voice_specs = [
            ("best_deepgram", "🎙  Best Voice — Deepgram Flux + Aura-2 (ultra-natural real-time speech · $200 free starter credit)"),
            ("builtin_openrouter", "🔊  Good Built-In Voice via OpenRouter Audio (uses same OpenRouter wallet · zero extra account)"),
            ("free_windows", "💻  Free Windows Voice (offline robotic Windows SAPI 5 · $0 forever)"),
        ]
        for key, text in voice_specs:
            rb = QRadioButton(text)
            rb.setToolTip(text)
            if key == "best_deepgram":
                rb.setChecked(True)
            self._voice_group.addButton(rb)
            self.voice_radios[key] = rb
            v_lay.addWidget(rb)
        lay.addWidget(voice_card)

        # Card C: Personality & Warmth
        tone_card = QFrame()
        t_lay = QVBoxLayout(tone_card)
        _style_wizard_card(tone_card, "wizardToneCard", t_lay)
        t_lay.setSpacing(6)
        t_hdr = QLabel("<b>3. How should Fairybread sound when chatting with you?</b>")
        t_hdr.setTextFormat(Qt.TextFormat.RichText)
        t_lay.addWidget(t_hdr)
        self._tone_group = QButtonGroup(self)
        self.tone_radios: dict[str, QRadioButton] = {}
        tone_specs = [
            ("warm", "☀️  Warm & witty (friendly rapport, remembers humor/banter mid-work, zero flattery)"),
            ("balanced", "💬  Balanced & natural (clear, personable collaborator)"),
            ("direct", "⚡  Concise & direct (straight to facts and code)"),
        ]
        for key, text in tone_specs:
            rb = QRadioButton(text)
            rb.setToolTip(text)
            if key == "warm":
                rb.setChecked(True)
            self._tone_group.addButton(rb)
            self.tone_radios[key] = rb
            t_lay.addWidget(rb)
        lay.addWidget(tone_card)

        # Card D: Billing Style
        bill_card = QFrame()
        b_lay = QVBoxLayout(bill_card)
        _style_wizard_card(bill_card, "wizardBillingCard", b_lay)
        b_lay.setSpacing(6)
        b_hdr = QLabel("<b>4. How do you want to manage API billing?</b>")
        b_hdr.setTextFormat(Qt.TextFormat.RichText)
        b_lay.addWidget(b_hdr)
        self._billing_group = QButtonGroup(self)
        self.billing_radios: dict[str, QRadioButton] = {}
        bill_specs = [
            ("openrouter_one_bill", "⊕  Simplified 1-Bill Hub via OpenRouter (Recommended — 1 prepaid wallet covers all AIs, no juggling keys)"),
            ("direct_keys", "🔑  Separate Direct API Keys (bring your own keys directly to Google, OpenAI, Anthropic, DeepSeek, etc.)"),
        ]
        for key, text in bill_specs:
            rb = QRadioButton(text)
            rb.setToolTip(text)
            if key == "openrouter_one_bill":
                rb.setChecked(True)
            self._billing_group.addButton(rb)
            self.billing_radios[key] = rb
            b_lay.addWidget(rb)
        lay.addWidget(bill_card)

        # Card E: Budget Tier
        bud_card = QFrame()
        bud_lay = QVBoxLayout(bud_card)
        _style_wizard_card(bud_card, "wizardBudgetCard", bud_lay)
        bud_lay.setSpacing(6)
        bud_hdr = QLabel("<b>5. Monthly spend / model tier preference:</b>")
        bud_hdr.setTextFormat(Qt.TextFormat.RichText)
        bud_lay.addWidget(bud_hdr)
        self._budget_group = QButtonGroup(self)
        self.budget_radios: dict[str, QRadioButton] = {}
        bud_specs = [
            ("free", "🆓  Free / Starter ($0 free models & trial keys where available)"),
            ("balanced", "⚖️  Balanced Best Value (fast, warm & inexpensive — typically pennies per session)"),
            ("flagship", "🏆  Flagship Top-End (Claude Sonnet 5.5, Gemini 4 Neon, GPT-6.2, Grok 4)"),
        ]
        for key, text in bud_specs:
            rb = QRadioButton(text)
            rb.setToolTip(text)
            if key == "balanced":
                rb.setChecked(True)
            self._budget_group.addButton(rb)
            self.budget_radios[key] = rb
            bud_lay.addWidget(rb)
        lay.addWidget(bud_card)

        nav = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.setToolTip("Return to Welcome choices")
        back_btn.clicked.connect(lambda: self.pages_stack.setCurrentIndex(0))
        nav.addWidget(back_btn)
        nav.addStretch(1)
        next_btn = QPushButton("Next: Build My Key Checklist →")
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setToolTip("Generate your customized API key list with site buttons and live tick-off checks")
        next_btn.setStyleSheet("QPushButton { background:#1f6feb; color:#ffffff; border:none; padding:8px 16px; border-radius:6px; font-weight:700; }")
        next_btn.clicked.connect(self._advance_to_checklist)
        nav.addWidget(next_btn)
        lay.addLayout(nav)

        self.pages_stack.addWidget(scroll)

    def _gather_questionnaire_plan(self) -> dict[str, Any]:
        selected_needs = {k for k, cb in self.need_checks.items() if cb.isChecked()}
        voice_pref = next((k for k, rb in self.voice_radios.items() if rb.isChecked()), "best_deepgram")
        tone_pref = next((k for k, rb in self.tone_radios.items() if rb.isChecked()), "warm")
        billing_pref = next((k for k, rb in self.billing_radios.items() if rb.isChecked()), "openrouter_one_bill")
        budget_pref = next((k for k, rb in self.budget_radios.items() if rb.isChecked()), "balanced")
        return recommend_setup_plan(
            selected_needs,
            voice_pref=voice_pref,
            tone_pref=tone_pref,
            billing_pref=billing_pref,
            budget_pref=budget_pref,
        )

    # ------------------------------------------------------------------ Page 2: Live Tick-Off Checklist
    def _build_page2_checklist(self):
        scroll, _, lay = _make_scrolled_page()

        top_row = QHBoxLayout()
        hdr = QLabel("Step 2 of 2 — Paste Your Keys & Tick Everything Off")
        hdr.setStyleSheet("font-size:17px; font-weight:700; color:#f0f6fc;")
        top_row.addWidget(hdr, 1)
        self.checklist_progress_label = QLabel("0 / 0 Ready")
        self.checklist_progress_label.setStyleSheet(
            "font-family:Consolas, monospace; font-size:12.5px; font-weight:700; "
            "color:#eab308; background:#29230f; border:1px solid #eab308; border-radius:6px; padding:4px 10px;"
        )
        top_row.addWidget(self.checklist_progress_label)
        lay.addLayout(top_row)

        self.checklist_summary_label = QLabel("")
        self.checklist_summary_label.setWordWrap(True)
        self.checklist_summary_label.setStyleSheet("color:#8b949e; font-size:12.5px;")
        lay.addWidget(self.checklist_summary_label)

        self.checklist_container = QWidget()
        self.checklist_layout = QVBoxLayout(self.checklist_container)
        self.checklist_layout.setContentsMargins(0, 0, 0, 0)
        self.checklist_layout.setSpacing(10)
        lay.addWidget(self.checklist_container)
        lay.addStretch(1)

        nav = QHBoxLayout()
        back_btn = QPushButton("← Change Answers")
        back_btn.setToolTip("Go back to Step 1 questionnaire")
        back_btn.clicked.connect(lambda: self.pages_stack.setCurrentIndex(1))
        nav.addWidget(back_btn)
        nav.addStretch(1)
        apply_btn = QPushButton("✓ Apply & Finish Setup")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setToolTip("Save selected OpenRouter hub, voice & personality settings and finish")
        apply_btn.setStyleSheet("QPushButton { background:#238636; color:#ffffff; border:none; padding:8px 18px; border-radius:6px; font-weight:700; }")
        apply_btn.clicked.connect(self._apply_and_finish_wizard)
        nav.addWidget(apply_btn)
        lay.addLayout(nav)

        self.pages_stack.addWidget(scroll)

    def _advance_to_checklist(self):
        plan = self._gather_questionnaire_plan()
        self.populate_checklist(plan)
        self.pages_stack.setCurrentIndex(2)

    def populate_checklist(self, plan: dict[str, Any]) -> None:
        self._current_plan = dict(plan)
        while self.checklist_layout.count():
            item = self.checklist_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._checklist_widgets.clear()

        billing_desc = (
            f"1-Bill Hub via OpenRouter ({plan.get('openrouter_tier', 'balanced').title()} tier)"
            if plan.get("auto_fill_seats")
            else "Direct BYOK Keys"
        )
        self.checklist_summary_label.setText(
            f"Tailored Plan: {billing_desc} · Voice: {plan.get('voice_pref', '').replace('_', ' ').title()} · "
            "Click 'Open Site ↗' to grab a key, paste it below (encrypted immediately via Windows DPAPI), and click 'Test'."
        )

        for idx, spec in enumerate(plan.get("required_items") or []):
            cred_key = str(spec["credential_key"])
            has_existing = False
            try:
                has_existing = bool((self.credential_store.get_api_key(cred_key) or "").strip())
            except Exception:
                has_existing = False

            card = QFrame()
            c_lay = QVBoxLayout(card)
            _style_wizard_card(card, f"wizardKeyCard_{idx}", c_lay, pad_h=12, pad_v=10)
            c_lay.setSpacing(7)

            row_top = QHBoxLayout()
            tick_lbl = QLabel("✅ Ready" if has_existing else ("⚪ Optional" if spec.get("optional") else "⬜ Needed"))
            tick_lbl.setStyleSheet(
                "font-weight:700; font-size:12px; color:#22c55e;"
                if has_existing
                else ("font-weight:600; font-size:12px; color:#8b949e;" if spec.get("optional") else "font-weight:700; font-size:12px; color:#eab308;")
            )
            title_lbl = QLabel(f"<b>{spec['title']}</b>")
            title_lbl.setTextFormat(Qt.TextFormat.RichText)
            title_lbl.setStyleSheet("font-size:13.5px; color:#f0f6fc;")
            open_btn = QPushButton("Open Site ↗")
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setToolTip(f"Open {spec['url']} in your web browser to create or copy this API key")
            open_btn.clicked.connect(lambda _c=False, u=spec["url"]: webbrowser.open(u))
            row_top.addWidget(tick_lbl)
            row_top.addWidget(title_lbl, 1)
            row_top.addWidget(open_btn)
            c_lay.addLayout(row_top)

            sub_lbl = QLabel(spec["subtitle"])
            sub_lbl.setWordWrap(True)
            sub_lbl.setStyleSheet("color:#8b949e; font-size:12px;")
            c_lay.addWidget(sub_lbl)

            row_in = QHBoxLayout()
            key_edit = QLineEdit()
            key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            key_edit.setPlaceholderText(
                "✓ Existing DPAPI key already stored (paste a new key only if you want to replace it)"
                if has_existing
                else "Paste API key here — auto-saves & encrypts with Windows DPAPI"
            )
            key_edit.setToolTip(f"Enter API key for {spec['title']}")

            show_btn = QPushButton("👁")
            show_btn.setCheckable(True)
            show_btn.setToolTip("Show or hide entered key text")
            show_btn.toggled.connect(
                lambda chk, le=key_edit: le.setEchoMode(QLineEdit.EchoMode.Normal if chk else QLineEdit.EchoMode.Password)
            )

            test_btn = QPushButton("Test")
            test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            test_btn.setToolTip("Verify key & check live credit balance if supported")

            status_lbl = QLabel("Encrypted key detected in DPAPI vault." if has_existing else "Waiting for key…")
            status_lbl.setWordWrap(True)
            status_lbl.setStyleSheet("color:#86efac; font-size:11.5px;" if has_existing else "color:#8b949e; font-size:11.5px;")

            def _on_key_edited(raw_val: str, ckey=cred_key, t_lbl=tick_lbl, s_lbl=status_lbl, opt=bool(spec.get("optional"))):
                clean = (raw_val or "").strip()
                if clean:
                    try:
                        self.credential_store.set_api_key(ckey, clean)
                        t_lbl.setText("✅ Ready")
                        t_lbl.setStyleSheet("font-weight:700; font-size:12px; color:#22c55e;")
                        s_lbl.setText("Saved & encrypted with Windows DPAPI.")
                        s_lbl.setStyleSheet("color:#86efac; font-size:11.5px;")
                    except Exception as exc:
                        s_lbl.setText(f"Could not save key: {exc}")
                        s_lbl.setStyleSheet("color:#f87171; font-size:11.5px;")
                else:
                    exists_now = bool((self.credential_store.get_api_key(ckey) or "").strip())
                    if not exists_now:
                        t_lbl.setText("⚪ Optional" if opt else "⬜ Needed")
                        t_lbl.setStyleSheet("font-weight:600; font-size:12px; color:#8b949e;" if opt else "font-weight:700; font-size:12px; color:#eab308;")
                        s_lbl.setText("Waiting for key…")
                        s_lbl.setStyleSheet("color:#8b949e; font-size:11.5px;")
                self._refresh_checklist_progress()

            def _on_test_clicked(_c=False, sp=spec, le=key_edit, t_lbl=tick_lbl, s_lbl=status_lbl):
                ckey = str(sp["credential_key"])
                val = le.text().strip() or (self.credential_store.get_api_key(ckey) or "").strip()
                if not val:
                    s_lbl.setText("Paste a key first before testing.")
                    s_lbl.setStyleSheet("color:#eab308; font-size:11.5px;")
                    return
                if sp.get("supports_balance") or ckey in {"openrouter", "deepgram"}:
                    try:
                        from voice_service import fetch_tts_account_balance
                        res = fetch_tts_account_balance(ckey, api_key=val)
                        if res.get("ok"):
                            t_lbl.setText("✅ Verified")
                            t_lbl.setStyleSheet("font-weight:700; font-size:12px; color:#22c55e;")
                            s_lbl.setText(str(res.get("summary") or "Verified OK"))
                            s_lbl.setStyleSheet("color:#86efac; font-size:11.5px;")
                        else:
                            s_lbl.setText(str(res.get("summary") or "Verification failed — check key"))
                            s_lbl.setStyleSheet("color:#f87171; font-size:11.5px;")
                    except Exception as exc:
                        s_lbl.setText(f"Check error: {exc}")
                        s_lbl.setStyleSheet("color:#eab308; font-size:11.5px;")
                else:
                    t_lbl.setText("✅ Ready")
                    t_lbl.setStyleSheet("font-weight:700; font-size:12px; color:#22c55e;")
                    s_lbl.setText("Key stored & encrypted locally via Windows DPAPI.")
                    s_lbl.setStyleSheet("color:#86efac; font-size:11.5px;")
                self._refresh_checklist_progress()

            key_edit.textEdited.connect(_on_key_edited)
            test_btn.clicked.connect(_on_test_clicked)

            row_in.addWidget(key_edit, 1)
            row_in.addWidget(show_btn)
            row_in.addWidget(test_btn)

            if spec.get("kind") == "voice":
                test_voice_btn = QPushButton("🔊 Test Voice")
                test_voice_btn.setToolTip("Play a brief sample with your configured voice engine")
                def _on_test_voice(_c=False, ckey=cred_key, le=key_edit, s_lbl=status_lbl):
                    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
                        s_lbl.setText("Voice check simulated OK (offscreen mode).")
                        return
                    try:
                        from voice_service import speak_agent_response
                        speak_agent_response(
                            "Hi, this is Fairybread. Your voice setup is ready!",
                            config_path=self.config_path,
                            credential_store=self.credential_store,
                        )
                        s_lbl.setText("Triggered live voice sample.")
                    except Exception as exc:
                        s_lbl.setText(f"Voice test note: {exc}")
                test_voice_btn.clicked.connect(_on_test_voice)
                row_in.addWidget(test_voice_btn)

            c_lay.addLayout(row_in)
            c_lay.addWidget(status_lbl)

            self.checklist_layout.addWidget(card)
            self._checklist_widgets.append({
                "spec": spec,
                "tick_label": tick_lbl,
                "key_edit": key_edit,
                "status_label": status_lbl,
            })

        self._refresh_checklist_progress()

    def _refresh_checklist_progress(self) -> None:
        required = [w for w in self._checklist_widgets if not w["spec"].get("optional")]
        target_list = required or self._checklist_widgets
        ready_n = 0
        for item in target_list:
            ckey = str(item["spec"]["credential_key"])
            entered = bool(item["key_edit"].text().strip())
            stored = False
            try:
                stored = bool((self.credential_store.get_api_key(ckey) or "").strip())
            except Exception:
                stored = False
            if entered or stored:
                ready_n += 1
        total_n = len(target_list)
        all_ok = (ready_n >= total_n and total_n > 0)
        self.checklist_progress_label.setText(f"{ready_n} / {total_n} Ready")
        if all_ok:
            self.checklist_progress_label.setStyleSheet(
                "font-family:Consolas, monospace; font-size:12.5px; font-weight:700; "
                "color:#22c55e; background:#11281b; border:1px solid #22c55e; border-radius:6px; padding:4px 10px;"
            )
        else:
            self.checklist_progress_label.setStyleSheet(
                "font-family:Consolas, monospace; font-size:12.5px; font-weight:700; "
                "color:#eab308; background:#29230f; border:1px solid #eab308; border-radius:6px; padding:4px 10px;"
            )

    def _apply_and_finish_wizard(self):
        plan = dict(self._current_plan or self._gather_questionnaire_plan())
        try:
            for item in self._checklist_widgets:
                ckey = str(item["spec"]["credential_key"])
                raw = item["key_edit"].text().strip()
                if raw:
                    self.credential_store.set_api_key(ckey, raw)
                if item["spec"].get("kind") == "provider":
                    has_k = bool((self.credential_store.get_api_key(ckey) or "").strip())
                    if has_k or ckey == "openrouter":
                        save_provider_config(
                            provider_name=ckey,
                            enabled=True if has_k else None,
                            model=item["spec"].get("default_model") or None,
                            base_url=item["spec"].get("default_base_url") or None,
                            config_path=self.config_path,
                        )
            hub_patch = plan.get("hub_settings_patch") or {}
            if hub_patch:
                save_openrouter_hub_settings(hub_patch, config_path=self.config_path)
            pers_patch = plan.get("personalization_patch") or {}
            if pers_patch:
                save_personalization_settings(pers_patch, config_path=self.config_path)
            voice_patch = plan.get("voice_settings_patch") or {}
            if voice_patch:
                from voice_service import save_voice_settings
                save_voice_settings(voice_patch, config_path=self.config_path)
            save_ui_settings({"setup_wizard_completed": True}, config_path=self.config_path)
        except Exception as exc:
            QMessageBox.warning(self, "Setup Save Error", str(exc))
            return

        parent = self.parent()
        if parent is not None and hasattr(parent, "reload_providers_from_config"):
            try:
                parent.reload_providers_from_config()
            except Exception:
                pass
        self.accept()

    # ------------------------------------------------------------------ Page 3: Selective Restore Backup
    def _build_page3_restore(self):
        scroll, _, lay = _make_scrolled_page()

        hdr = QLabel("Restore From Backup (.zip)")
        hdr.setStyleSheet("font-size:17px; font-weight:700; color:#f0f6fc;")
        lay.addWidget(hdr)

        sub = QLabel(
            "Choose a Fairybread backup (.zip) to inspect its contents and choose exactly what to restore "
            "(your Memories & Conversations, your Settings & Profiles, and/or your Encrypted API Keys). "
            "If you exported Data and Keys separately, you can restore both archives one after another right here."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#8b949e; font-size:12.5px;")
        lay.addWidget(sub)

        pick_card = QFrame()
        p_lay = QVBoxLayout(pick_card)
        _style_wizard_card(pick_card, "wizardRestorePickCard", p_lay)
        p_lay.setSpacing(8)

        pick_row = QHBoxLayout()
        self.restore_path_label = QLabel("No backup .zip selected yet.")
        self.restore_path_label.setWordWrap(True)
        self.restore_path_label.setStyleSheet("color:#c9d1d9; font-size:12.5px;")
        choose_btn = QPushButton("📂 Choose Backup (.zip)…")
        choose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_btn.setToolTip("Select a Fairybread backup archive to inspect and restore")
        choose_btn.clicked.connect(self._browse_backup_zip)
        pick_row.addWidget(self.restore_path_label, 1)
        pick_row.addWidget(choose_btn)
        p_lay.addLayout(pick_row)

        self.restore_info_label = QLabel("")
        self.restore_info_label.setWordWrap(True)
        self.restore_info_label.setStyleSheet("color:#8b949e; font-size:12px;")
        p_lay.addWidget(self.restore_info_label)

        self.restore_mem_check = QCheckBox("🧠 Restore Memory Palace, Conversations & Projects")
        self.restore_mem_check.setToolTip("Restore SQLite Memory Palace (memory.db), sessions, and uploaded/generated files")
        self.restore_settings_check = QCheckBox("⚙ Restore Settings, Profiles & Themes")
        self.restore_settings_check.setToolTip("Restore palace_config.json settings and custom UI themes")
        self.restore_keys_check = QCheckBox("🔑 Restore Encrypted API Keys")
        self.restore_keys_check.setToolTip("Unlock password-protected vault (if locked) and re-seal API keys into local Windows DPAPI")
        for box in (self.restore_mem_check, self.restore_settings_check, self.restore_keys_check):
            box.setEnabled(False)
            p_lay.addWidget(box)

        pw_row = QHBoxLayout()
        self.restore_pw_label = QLabel("Backup Password:")
        self.restore_pw_edit = QLineEdit()
        self.restore_pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.restore_pw_edit.setPlaceholderText("Required if backup contains password-locked API keys")
        self.restore_pw_edit.setToolTip("Password used to lock API keys inside the backup archive")
        pw_row.addWidget(self.restore_pw_label)
        pw_row.addWidget(self.restore_pw_edit, 1)
        p_lay.addLayout(pw_row)
        self.restore_pw_label.hide()
        self.restore_pw_edit.hide()

        self.restore_keys_check.toggled.connect(self._sync_restore_pw_visibility)

        act_row = QHBoxLayout()
        self.restore_exec_btn = QPushButton("♻️ Restore Selected")
        self.restore_exec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_exec_btn.setToolTip("Restore only the checked components from this backup archive")
        self.restore_exec_btn.setEnabled(False)
        self.restore_exec_btn.setStyleSheet("QPushButton { background:#238636; color:#ffffff; border:none; padding:7px 14px; border-radius:6px; font-weight:700; }")
        self.restore_exec_btn.clicked.connect(self._execute_selective_restore)

        self.restore_another_btn = QPushButton("+ Restore Another Backup (.zip)…")
        self.restore_another_btn.setToolTip("Load a second backup archive (e.g., separate API Keys backup after restoring Data)")
        self.restore_another_btn.clicked.connect(self._browse_backup_zip)
        self.restore_another_btn.hide()

        act_row.addWidget(self.restore_exec_btn)
        act_row.addWidget(self.restore_another_btn)
        act_row.addStretch(1)
        p_lay.addLayout(act_row)

        self.restore_status_label = QLabel("")
        self.restore_status_label.setWordWrap(True)
        self.restore_status_label.setStyleSheet("color:#86efac; font-size:12px;")
        p_lay.addWidget(self.restore_status_label)

        lay.addWidget(pick_card)
        lay.addStretch(1)

        nav = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.setToolTip("Return to Welcome choices")
        back_btn.clicked.connect(lambda: self.pages_stack.setCurrentIndex(0))
        nav.addWidget(back_btn)
        nav.addStretch(1)

        self.restore_handoff_btn = QPushButton("Next: Set Up API Keys Now →")
        self.restore_handoff_btn.setToolTip("Your data is restored — continue into Guided Setup to configure your API keys")
        self.restore_handoff_btn.setStyleSheet("QPushButton { background:#1f6feb; color:#ffffff; border:none; padding:8px 14px; border-radius:6px; font-weight:700; }")
        self.restore_handoff_btn.clicked.connect(lambda: self.pages_stack.setCurrentIndex(1))
        self.restore_handoff_btn.hide()
        nav.addWidget(self.restore_handoff_btn)

        self.restore_done_btn = QPushButton("Done")
        self.restore_done_btn.setToolTip("Close Wizard and return to Fairybread")
        self.restore_done_btn.clicked.connect(self._finish_restore_page)
        nav.addWidget(self.restore_done_btn)
        lay.addLayout(nav)

        self.pages_stack.addWidget(scroll)

    def _finish_restore_page(self):
        self._mark_wizard_completed()
        self.accept()

    def _sync_restore_pw_visibility(self):
        needs_pw = bool(
            self.restore_keys_check.isChecked()
            and self._zip_info.get("password_protected", False)
        )
        self.restore_pw_label.setVisible(needs_pw)
        self.restore_pw_edit.setVisible(needs_pw)

    def load_backup_zip_for_restore(self, zip_path: Path) -> None:
        from backup_service import inspect_backup_zip
        info = inspect_backup_zip(Path(zip_path))
        self._selected_zip_path = Path(zip_path)
        self._zip_info = info
        self.restore_path_label.setText(f"Archive: {self._selected_zip_path.name} ({info.get('file_count', 0)} files)")
        parts = []
        if info.get("has_memory"):
            parts.append("Memory & Chats")
        if info.get("has_settings"):
            parts.append("Settings & Themes")
        if info.get("has_credentials"):
            parts.append("Encrypted API Keys" + (" [Password-Locked]" if info.get("password_protected") else " [Same-PC DPAPI]"))
        self.restore_info_label.setText("Contains: " + (", ".join(parts) if parts else "No recognized sections"))

        for chk, flag in (
            (self.restore_mem_check, bool(info.get("has_memory"))),
            (self.restore_settings_check, bool(info.get("has_settings"))),
            (self.restore_keys_check, bool(info.get("has_credentials"))),
        ):
            chk.setEnabled(flag)
            chk.setChecked(flag)
        self.restore_exec_btn.setEnabled(any(bool(info.get(k)) for k in ("has_memory", "has_settings", "has_credentials")))
        self.restore_pw_edit.clear()
        self._sync_restore_pw_visibility()

    def _browse_backup_zip(self):
        fp, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Fairybread Backup Archive",
            str(Path.home() / "Documents"),
            "Backup ZIP (*.zip);;All Files (*.*)",
        )
        if not fp:
            return
        try:
            self.load_backup_zip_for_restore(Path(fp))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Backup Archive", str(exc))

    def _execute_selective_restore(self):
        if not self._selected_zip_path:
            return
        from backup_service import restore_full_backup_zip
        try:
            summary = restore_full_backup_zip(
                self._selected_zip_path,
                config_path=self.config_path,
                backup_password=self.restore_pw_edit.text(),
                restore_memory=self.restore_mem_check.isChecked(),
                restore_settings=self.restore_settings_check.isChecked(),
                restore_credentials=self.restore_keys_check.isChecked(),
            )
        except Exception as exc:
            self.restore_status_label.setStyleSheet("color:#f87171; font-size:12px;")
            self.restore_status_label.setText(f"⚠ Restore error: {exc}")
            return

        self.restored_anything = True
        keys_n = int(summary.get("restored_keys_count") or 0)
        if self.restore_keys_check.isChecked() and not summary.get("skipped_credentials"):
            self._restored_keys_any = True

        msg = f"✓ Restored {summary.get('restored_files', 0)} item(s) cleanly"
        if keys_n > 0:
            msg += f" (unlocked & re-sealed {keys_n} API key(s) into Windows DPAPI)"
        elif summary.get("skipped_credentials"):
            msg += " — Note: Unencrypted DPAPI keys from another PC were skipped; configure keys in Guided Setup or restore your password-locked Keys backup."
        self.restore_status_label.setStyleSheet("color:#86efac; font-size:12px;")
        self.restore_status_label.setText(msg)
        self.restore_another_btn.show()

        has_any_keys = False
        try:
            has_any_keys = len(self.credential_store.list_providers()) > 0
        except Exception:
            has_any_keys = self._restored_keys_any
        self.restore_handoff_btn.setVisible(not has_any_keys)

        try:
            save_ui_settings({"setup_wizard_completed": True}, config_path=self.config_path)
        except Exception:
            pass
        parent = self.parent()
        if parent is not None:
            for meth in ("reload_providers_from_config", "refresh_sessions", "load_history"):
                fn = getattr(parent, meth, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass


class SpendBillingDialog(QDialog):
    """3-Layer Live Spend & Billing Dashboard: Active Conversation, Resettable Per-Provider Cycle, & Cumulative."""

    def __init__(
        self,
        parent=None,
        *,
        conv_ledger: ConversationCostLedger | None = None,
        global_ledger: GlobalBillingLedger | None = None,
        credential_store: CredentialStore | None = None,
    ):
        super().__init__(parent)
        self.conv_ledger = conv_ledger or ConversationCostLedger()
        self.global_ledger = global_ledger or get_global_billing_ledger()
        self.credential_store = credential_store or CredentialStore()
        self._balance_cache: dict[str, str] = {}

        self.setWindowTitle("Fairybread — Spend & Billing Tickers")
        self.setWindowFlags(
            (
                self.windowFlags()
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(820, 620)
        self.setMinimumSize(700, 500)
        self.setStyleSheet(
            "QDialog { background:#0d1117; color:#e6edf3; } "
            "QLabel { color:#e6edf3; } "
            "QPushButton { background:#161b22; color:#e6edf3; border:1px solid #30363d; border-radius:6px; padding:5px 10px; font-weight:600; } "
            "QPushButton:hover { border-color:#58a6ff; background:#1f2735; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top_bar = QHBoxLayout()
        title = QLabel("💵 Spend & Billing Tickers (Cumulative, Resettable Per-Provider & Live Session)")
        title.setStyleSheet("font-size:15.5px; font-weight:700; color:#f0f6fc;")
        top_bar.addWidget(title, 1)
        self.refresh_bal_btn = QPushButton("🔄 Refresh Live Balances")
        self.refresh_bal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_bal_btn.setToolTip("Fetch remaining prepaid USD credit from OpenRouter and Deepgram APIs")
        self.refresh_bal_btn.clicked.connect(self._refresh_live_balances)
        top_bar.addWidget(self.refresh_bal_btn)
        root.addLayout(top_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body_widget = QWidget()
        self._body_lay = QVBoxLayout(self._body_widget)
        self._body_lay.setContentsMargins(2, 2, 2, 2)
        self._body_lay.setSpacing(12)
        scroll.setWidget(self._body_widget)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setToolTip("Close Spend & Billing window")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self.rebuild_view()

    def rebuild_view(self) -> None:
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        snap = self.global_ledger.snapshot()
        c = self.conv_ledger

        # Card 1: Active Conversation
        conv_card = QFrame()
        c_lay = QVBoxLayout(conv_card)
        _style_wizard_card(conv_card, "spendConvCard", c_lay)
        c_lay.setSpacing(5)
        c_hdr = QLabel("<b>1. Active Conversation (Live Session Ticker)</b>")
        c_hdr.setTextFormat(Qt.TextFormat.RichText)
        c_lay.addWidget(c_hdr)
        c_tot = c.total_cost_usd
        c_details = QLabel(
            f"Total This Conversation: <b>{format_usd_compact(c_tot)} USD</b> &nbsp;|&nbsp; "
            f"Chat LLMs: {format_usd_compact(c.llm_cost_usd)} ({(c.input_tokens + c.output_tokens):,} tokens) &nbsp;|&nbsp; "
            f"Pictures: {c.image_count} ({format_usd_compact(c.image_cost_usd)}) &nbsp;|&nbsp; "
            f"Voice Live: {format_usd_compact(c.voice_tts_cost_usd + c.voice_stt_cost_usd)} "
            f"({c.voice_tts_seconds:.0f}s TTS / {c.voice_stt_seconds:.0f}s STT)"
        )
        c_details.setTextFormat(Qt.TextFormat.RichText)
        c_details.setWordWrap(True)
        c_details.setStyleSheet("color:#90d7c1; font-size:12.5px;")
        c_lay.addWidget(c_details)
        self._body_lay.addWidget(conv_card)

        # Card 2: Per-Provider Spend Since Last Paid (with Mark Paid / Reset button per row)
        prov_card = QFrame()
        p_lay = QVBoxLayout(prov_card)
        _style_wizard_card(prov_card, "spendProvidersCard", p_lay)
        p_lay.setSpacing(8)
        p_hdr = QLabel("<b>2. Per-Provider Spend Since Last Paid (Reset Each Time You Pay / Top Up)</b>")
        p_hdr.setTextFormat(Qt.TextFormat.RichText)
        p_lay.addWidget(p_hdr)

        _non_billing_keys = {"email_connector"}
        stored_provs: list[str] = []
        try:
            stored_provs = [
                p for p in self.credential_store.list_providers()
                if str(p).strip().lower() not in _non_billing_keys
            ]
        except Exception:
            stored_provs = []

        prov_map: dict[str, dict[str, Any]] = dict(snap.get("providers") or {})
        all_names = list(dict.fromkeys([*prov_map.keys(), *stored_provs]))

        if not all_names:
            empty_lbl = QLabel("No provider spend or API keys recorded yet.")
            empty_lbl.setStyleSheet("color:#8b949e; font-size:12px;")
            p_lay.addWidget(empty_lbl)
        else:
            for pname in sorted(all_names):
                pdata = prov_map.get(pname, {})
                cyc = float(pdata.get("cycle_usd", 0.0) or 0.0)
                life = float(pdata.get("lifetime_usd", 0.0) or 0.0)
                last_rst = str(pdata.get("last_reset_at") or "").strip()
                rst_txt = last_rst[:16].replace("T", " ") if last_rst else "Never reset"
                disp = PROVIDER_CATALOG.get(pname, {}).get("display_name", pname.title())

                row_w = QFrame()
                row_w.setObjectName(f"spendProvRow_{pname}")
                row_w.setStyleSheet(
                    f"QFrame#spendProvRow_{pname} {{ background:#0d1117; border:1px solid #21262d; border-radius:7px; }}"
                )
                r_lay = QHBoxLayout(row_w)
                r_lay.setContentsMargins(10, 7, 10, 7)
                r_lay.setSpacing(10)

                info_txt = (
                    f"<b>{disp}</b> — Since Paid: <span style='color:#eab308;'>{format_usd_compact(cyc)}</span> "
                    f"&nbsp;·&nbsp; All-Time: {format_usd_compact(life)} &nbsp;·&nbsp; Last Paid: {rst_txt}"
                )
                if pname in self._balance_cache:
                    info_txt += f"<br><span style='color:#86efac; font-size:11.5px;'>Live Balance: {self._balance_cache[pname]}</span>"
                info_lbl = QLabel(info_txt)
                info_lbl.setTextFormat(Qt.TextFormat.RichText)
                info_lbl.setWordWrap(True)
                r_lay.addWidget(info_lbl, 1)

                reset_btn = QPushButton("↺ Mark Paid / Reset")
                reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                reset_btn.setToolTip(f"Reset {disp}'s 'Since Last Paid' counter to $0.000 (keeps All-Time total & logs reset date)")
                reset_btn.clicked.connect(lambda _c=False, p=pname: self._mark_paid(p))
                r_lay.addWidget(reset_btn)
                p_lay.addWidget(row_w)

        self._body_lay.addWidget(prov_card)

        # Card 3: All-Time Cumulative Summary + Payment History
        cum_card = QFrame()
        cm_lay = QVBoxLayout(cum_card)
        _style_wizard_card(cum_card, "spendCumulativeCard", cm_lay)
        cm_lay.setSpacing(5)
        cm_hdr = QLabel("<b>3. All-Time Cumulative Totals Across All Sessions</b>")
        cm_hdr.setTextFormat(Qt.TextFormat.RichText)
        cm_lay.addWidget(cm_hdr)
        cm_txt = QLabel(
            f"All-Time Total Spend: <b>{format_usd_compact(snap.get('lifetime_total_usd', 0.0))} USD</b> &nbsp;|&nbsp; "
            f"Chat LLMs: {format_usd_compact(snap.get('lifetime_llm_usd', 0.0))} &nbsp;|&nbsp; "
            f"Pictures: {int(snap.get('lifetime_image_count', 0))} ({format_usd_compact(snap.get('lifetime_image_usd', 0.0))}) &nbsp;|&nbsp; "
            f"Voice (TTS + STT): {format_usd_compact(snap.get('lifetime_voice_usd', 0.0))}"
        )
        cm_txt.setTextFormat(Qt.TextFormat.RichText)
        cm_txt.setWordWrap(True)
        cm_txt.setStyleSheet("color:#c9d1d9; font-size:12.5px;")
        cm_lay.addWidget(cm_txt)

        recent_resets: list[str] = []
        for pn, pd in prov_map.items():
            for h in pd.get("payment_history") or []:
                ts = str(h.get("paid_at") or "")[:16].replace("T", " ")
                clr = float(h.get("cleared_cycle_usd") or 0.0)
                recent_resets.append(f"{ts} · {pn}: cleared {format_usd_compact(clr)}")
        if recent_resets:
            rec_lbl = QLabel("Recent Payment Resets: " + "  |  ".join(sorted(recent_resets, reverse=True)[:5]))
            rec_lbl.setWordWrap(True)
            rec_lbl.setStyleSheet("color:#8b949e; font-size:11.5px;")
            cm_lay.addWidget(rec_lbl)

        self._body_lay.addWidget(cum_card)
        self._body_lay.addStretch(1)

    def _mark_paid(self, provider_name: str) -> None:
        self.global_ledger.mark_provider_paid(provider_name, note=f"Reset at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self.rebuild_view()

    def _refresh_live_balances(self) -> None:
        from voice_service import fetch_tts_account_balance
        for eng in ("openrouter", "deepgram"):
            try:
                key = (self.credential_store.get_api_key(eng) or "").strip()
            except Exception:
                key = ""
            if not key:
                continue
            try:
                res = fetch_tts_account_balance(eng, api_key=key)
                self._balance_cache[eng] = str(res.get("summary") or "Unavailable")
            except Exception as exc:
                self._balance_cache[eng] = f"Error: {exc}"
        self.rebuild_view()
