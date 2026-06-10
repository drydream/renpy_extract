# CLAUDE.md

## Project: Ren'Py EN→TH Translation Tool

Standalone Windows app (tkinter GUI) that translates Ren'Py games English→Thai.
Repo: https://github.com/drydream/renpy_extract

### Files

- `renpy.py` — main app. 5-step GUI workflow: Scan → Prepare (.rpa extract + .rpyc decompile) → Extract text to CSV → (user translates CSV) → Thai font/language setup → Apply translations. `APP_VERSION` constant near the top.
- `app_updater.py` — auto-update + version rollback via GitHub Releases API. Stdlib only (urllib). Detached `.bat` swap pattern for the locked exe; `cleanup_after_update()` runs on launch.
- `_renpy_tools/` — bundled tools: `rpatool.py`, `unrpyc.py` + `decompiler/` (primary), `UnRen-Powershell-forall.ps1` (fallback source).
- `font/` — IBM Plex Sans Thai (OFL). `IBMPlexSansThai-Regular.ttf` is the embedded default — Step 4 uses it automatically, no Browse needed.
- Sibling projects (separate folders/repos under `D:\claude-workspace\every_translate_tool\`): `rpgm_tool\`, `unity_tool\`, `translate_tool\` (github.com/drydream/translate_tool).

### Commands

```
python renpy.py                  # run from source
python -m PyInstaller --onefile --noconsole --name renpy --add-data "font;font" --add-data "_renpy_tools;_renpy_tools" renpy.py
gh release create vX.Y.Z dist\renpy.exe --title "vX.Y.Z" --notes "..."
```

### Release rules

- Bump `APP_VERSION` in `renpy.py` BEFORE building — must match the release tag (`v` prefix on tag only).
- Asset must be named `renpy.exe` (updater picks asset matching the running exe name).
- Verify with `python -c "import py_compile; py_compile.compile('renpy.py', doraise=True)"` minimum; user tests the GUI visually.

### Path rules

- Frozen (PyInstaller): bundled data resolves via `sys._MEIPASS`; the real app folder is `os.path.dirname(sys.executable)` (updater writes `temp_update/` there).
- Dev: everything sits next to the script.
- Never hardcode absolute paths (the old `E:\h\...` UnRen path is fallback-only).

---

## Behavioral Guidelines

Guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
