"""Foreman Bridge (ask_council.py) — Lets Max (Antigravity) dispatch prompts to the Palace AI Council.

Writes exchanges directly into the live SessionStore so any open Palace GUI window automatically
refreshes and displays the Foreman prompt + Council synthesis + individual AI responses in real time.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from bootstrap import build_palace
from credential_store import CredentialStore
from palace_config import load_enabled_provider_names, load_provider_configs
from provider_loader import load_configured_providers
from session_store import SessionStore


def run_foreman_query(
    prompt: str,
    *,
    providers_filter: list[str] | None = None,
    rounds: int = 2,
    include_context: bool = True,
    save_to_context: bool = True,
    include_palace_code: bool = False,
    project_folder: str = "",
) -> int:
    store = SessionStore()
    session_id = store.selected
    context = store.context(session_id)

    credentials = CredentialStore()
    provider_configs = load_provider_configs()
    loaded_providers = load_configured_providers(
        credentials,
        provider_configs=provider_configs,
    )
    enabled_names = load_enabled_provider_names()

    active_providers = {
        name: prov
        for name, prov in loaded_providers.items()
        if name in enabled_names
    }
    if providers_filter:
        wanted = {p.strip().lower() for p in providers_filter if p.strip()}
        active_providers = {
            name: prov
            for name, prov in loaded_providers.items()
            if name.lower() in wanted
        }

    if not active_providers:
        print("ERROR: No active AI providers available for Foreman query.", file=sys.stderr)
        return 1

    palace = build_palace(
        providers=active_providers,
        context_service=context,
    )

    provider_list_str = ", ".join(active_providers.keys())
    print(f"[Foreman -> Palace Council] Consulting ({provider_list_str}) | rounds={rounds} | session={session_id}")

    result = palace.run(
        prompt,
        provider_names=list(active_providers.keys()),
        include_context=include_context,
        save_to_context=save_to_context,
        max_rounds=rounds,
        include_palace_code=include_palace_code,
        project_folder=project_folder,
    )

    print("\n" + "=" * 72)
    print(f"CONTRIBUTORS: {', '.join(result.contributors or [])}")
    print("=" * 72)
    if result.speaker_messages:
        for msg in result.speaker_messages:
            sp = str(msg.get("speaker_id") or "ai").upper()
            ph = str(msg.get("phase") or "initial").upper()
            print(f"\n--- [{sp} | {ph}] ---")
            print(msg.get("content", ""))

    print("\n" + "=" * 72)
    print("COUNCIL SYNTHESIS")
    print("=" * 72)
    print(result.final_answer or "(No synthesis returned)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Foreman Bridge: Ask the Palace AI Council")
    parser.add_argument("--prompt", "-p", type=str, default="", help="Prompt text to send to the Council")
    parser.add_argument("--prompt-file", "-f", type=str, default="", help="Path to file containing prompt text")
    parser.add_argument("--providers", type=str, default="", help="Comma-separated provider names (default: all enabled)")
    parser.add_argument("--rounds", type=int, default=2, help="1 for Direct, 2 for Peer Deliberation (default: 2)")
    parser.add_argument("--no-history", action="store_true", help="Do not read or save session history")
    parser.add_argument("--tangent", action="store_true", help="Do not read prior history, but save this turn to Palace")
    parser.add_argument("--palace-code", action="store_true", help="Include Palace source code context")
    parser.add_argument("--project-folder", type=str, default="", help="Optional project folder path")
    args = parser.parse_args(argv)

    prompt_text = args.prompt.strip()
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt_text:
        print("ERROR: Provide --prompt or --prompt-file", file=sys.stderr)
        return 1

    prov_filter = [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None
    include_ctx = (not args.no_history) and (not args.tangent)
    save_ctx = not args.no_history

    return run_foreman_query(
        prompt_text,
        providers_filter=prov_filter,
        rounds=args.rounds,
        include_context=include_ctx,
        save_to_context=save_ctx,
        include_palace_code=args.palace_code,
        project_folder=args.project_folder,
    )


if __name__ == "__main__":
    raise SystemExit(main())
