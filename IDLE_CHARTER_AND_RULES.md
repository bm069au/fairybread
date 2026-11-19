# Fairybread Code Versioning, Sandbox Isolation & 3-Tier Promotion Rules

## 1. The Core Architecture
Fairybread operates on a strict 3-tier boundary to prevent autonomous AI agents from ever corrupting or mutating the master development repository:

### Tier 1: Agent Sandbox & Staging (AI-Owned)
- **Locations:** `C:\Palace_Idle_Sandbox\staging\`, `source_mirror\`, and `C:\Palace_Live\`.
- **Ownership:** Autonomous AI Agents (Idle Mode, Experimental Mode, Autopatch).
- **Rule:** Agents may freely inspect, stage, test (`py_compile` + `unittest`), and hot-reboot within their own sandbox.
- **Boundary:** Agents MUST NEVER claim a patch is "Live in Production" or attempt to mutate the main development codebase on drive `E:`.

### Tier 2: Master Development Repository (Owner-Owned)
- **Location:** `E:\Visual_studio\Palace\` (Master local workspace).
- **Ownership:** Brett Martin Moore (`bm069au`).
- **Rule:** The master repository on `E:` is strictly protected. Autopatch and watchdog reboots will NEVER automatically overwrite files on `E:`.
- **Promotion:** Only after Brett reviews the staged diffs and explicitly authorizes promotion will files be copied from the sandbox to `E:`.

### Tier 3: Remote Git Repositories (Public & Private)
- **Repositories:**
  - Public Release: `https://github.com/bm069au/fairybread`
  - Developer Release: `https://github.com/bm069au/fairybread-dev` (100% Private)
- **Rule:** Git commits and pushes happen ONLY from `E:\Visual_studio\Palace\` after Brett's manual review and promotion. Agents have zero direct push access to Git remotes.

---

## 2. Standard Review & Promotion Commands

### Review Staged Changes (Diff Check)
To compare what the agents changed in their sandbox versus the master `E:` repository:
```powershell
python E:\Visual_studio\Palace\palace_promote.py --diff
```

### Promote Staged Changes to Main (E: Repository)
Once Brett reviews and approves the changes:
```powershell
python E:\Visual_studio\Palace\palace_promote.py --promote
```

### Push Promoted Code to Git Remotes
After promotion and verification on `E:`:
```powershell
python E:\Visual_studio\Palace\palace_promote.py --git-push "Brief description of changes"
```
