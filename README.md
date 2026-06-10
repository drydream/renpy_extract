# Ren'Py EN→TH Translation Tool

Standalone Windows app for translating Ren'Py games from English to Thai.
No installation needed — download one `.exe` and run.

**[⬇ Download latest version](https://github.com/drydream/renpy_extract/releases/latest)**

## Features

- Extract `.rpa` archives and decompile `.rpyc` files (built-in tools, no external dependencies)
- Extract all English dialogue/UI text to a CSV file
- Apply translated CSV back into the game (in-place or via `tl/thai/` language folder)
- Embedded Thai font (IBM Plex Sans Thai) installed into the game automatically
- Adds a Thai language option to the game's preferences screen
- Backup & restore of original game files
- Built-in auto-updater with version rollback (pick any release from the dropdown)

## How to use

1. **Scan** — select the game's root folder (the one containing `game/`, `lib/`, `renpy/`)
2. **Step 1 Prepare** — extracts `.rpa` archives and decompiles `.rpyc` files
3. **Step 2 Extract** — saves all English text to a CSV file
4. **Step 3 Translate** — open the CSV with your AI translator, fill the `thai` column, save
5. **Step 4 Thai Language Setup** — click Apply (built-in Thai font is used automatically)
6. **Step 5 Apply Translations** — writes the Thai text into the game

Made a mistake? **Restore from Backup** puts the original files back.

## Updates

The app checks GitHub for new versions on startup. Click **Check for Updates…**
(bottom-right) to upgrade — or roll back to any older version from the dropdown.

## Build from source

```
pip install pyinstaller
pyinstaller --onefile --noconsole --name renpy --add-data "font;font" --add-data "_renpy_tools;_renpy_tools" renpy.py
```

Output: `dist\renpy.exe`

## Credits

- [unrpyc](https://github.com/CensoredUsername/unrpyc) — .rpyc decompiler
- [rpatool](https://github.com/Shizmob/rpatool) — .rpa archive tool
- [UnRen](https://f95zone.to/threads/unren-bat-v1-0-11d-rpa-extractor-rpyc-decompiler-console-developer-menu-enabler.3083/) — fallback tool source
- [IBM Plex Sans Thai](https://github.com/IBM/plex) — font (SIL Open Font License)
