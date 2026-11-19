# Fairybread — Beta v0.9.1d (Win_x64) Changelog
**Release Date:** 2026-11-19
**Version:** `v0.9.1d_beta_Win_x64` (Minor Letter Iteration `d` of `v0.9.1`)

## Summary of Changes in `v0.9.1d`
1. **Hardwired Edition Gate (`FAIRYBREAD_EDITION = "public"` vs `"developer"`):**
   - **Public (non-Dev) Edition** still includes Experimental Mode (Free Talk lounge, Shared Experimental Memory, Agent Mail), but **live code self-modification (`/autopatch`, `[IDLE_PATCH]`, `⚡ Live Patch`, and source-mirror writing) is hardwired OFF** in code (`palace_config.py`, `idle_service.py`, `orchestrator.py`, `palace_gui.py`).
   - Public installers physically omit `palace_ouroboros.py`, `palace_watchdog.py`, `palace_promote.py`, and `test_*.py` so public installs cannot fork themselves or bypass restrictions.
   - Public users see clear notices in Settings, About, README, User Guide, and `fairybread.me` explaining why self-patching is disabled in non-Dev builds and inviting them to post proposed patches to **https://fairybread.me/forum.html** or email **bm069au@gmail.com**.
2. **Installer `payload/` Packaging Bug Fixed:**
   - Cleaned stray duplicate files out of `dist/Fairybread_Beta_v0.9.1_Installer/` root and updated `payload/` directly so both Public and Developer `Win_x64` zips are clean (~370 KB) and ship the exact `v0.9.1d` code.
