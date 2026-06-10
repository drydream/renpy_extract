"""Ren'Py EN→TH Translation Tool — standalone."""
import base64, csv, io, os, pickle, platform, re, shutil, subprocess, sys, zipfile, zlib
import queue, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

APP_VERSION = '1.1.0'
try:
    import app_updater
except Exception:
    app_updater = None

# ─── Paths ────────────────────────────────────────────────────────────────────

# Frozen (PyInstaller onefile): bundled data lives in sys._MEIPASS.
# Development: everything sits next to this script.
if getattr(sys, 'frozen', False):
    _SCRIPT_DIR = sys._MEIPASS
else:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_SCRIPT_DIR, '_renpy_tools')
DEFAULT_FONT = os.path.join(_SCRIPT_DIR, 'font', 'IBMPlexSansThai-Regular.ttf')
UNREN_PS1 = os.path.join(CACHE_DIR, 'UnRen-Powershell-forall.ps1')
if not os.path.isfile(UNREN_PS1):  # fall back to the original external copy
    UNREN_PS1 = r'E:\h\UnRen-Powershell-forallv9.4\UnRen-Powershell-forall.ps1'

_SKIP_RPA_DIRS = {'camera', 'director', 'tl'}
_SKIP_RPA_FILES = {
    'ActionEditor', 'image_viewer', 'wordcounter',
    '00camera_statements', '00warper', 'spline', 'keymap',
    'animation_images', 'gallery_button', 'transform',
}

def _rpa_needs_extract(path):
    clean = path.strip().replace('\\', '/')
    if not clean.endswith('.rpyc'):
        return False
    parts = clean.split('/')
    if any(p.lower() in _SKIP_RPA_DIRS for p in parts[:-1]):
        return False
    stem = parts[-1][:-5]
    if stem in _SKIP_RPA_FILES:
        return False
    return True


SKIP_KEYWORDS = {
    'label', 'jump', 'call', 'return', 'pass', 'menu', 'pause',
    'if', 'elif', 'else', 'for', 'while',
    'init', 'define', 'default', 'python',
    'image', 'show', 'hide', 'scene', 'with', 'at', 'as',
    'behind', 'onlayer', 'zorder', 'camera',
    'transform', 'parallel', 'block', 'choice', 'repeat', 'event',
    'play', 'stop', 'queue', 'voice', 'audio',
    'screen', 'style', 'nvl', 'use', 'add', 'has', 'null',
    'key', 'timer', 'window', 'layer', 'tag', 'id',
    'hbox', 'vbox', 'fixed', 'grid', 'side', 'frame',
    'viewport', 'drag', 'draggroup', 'mousearea', 'hotspot',
    'text', 'input', 'button', 'textbutton', 'imagebutton',
    'bar', 'vbar', 'hotbar',
    'font', 'size', 'color', 'language', 'layout',
    'background', 'foreground', 'hover_background', 'idle_background',
    'action', 'hovered', 'unhovered', 'selected', 'sensitive',
    'value', 'range', 'placeholder', 'variable', 'allow', 'exclude',
    'prefix', 'suffix', 'copypaste',
    'style_prefix', 'style_suffix', 'variant',
    'text_style',
    'idle', 'hover', 'insensitive', 'ground', 'thumb',
    'selected_idle', 'selected_hover', 'selected_insensitive',
    'focus_mask',
    'fit', 'shader', 'mouse', 'focus', 'preferred_side',
    'size_group', 'mousewheel', 'scrollbars',
}

# ─── Tool extraction ──────────────────────────────────────────────────────────

def ensure_tools(log_fn=None):
    rpatool = os.path.join(CACHE_DIR, 'rpatool.py')
    unrpyc  = os.path.join(CACHE_DIR, 'unrpyc.py')
    if os.path.isfile(rpatool) and os.path.isfile(unrpyc):
        return True, None
    if not os.path.isfile(UNREN_PS1):
        return False, f"UnRen PS1 not found:\n{UNREN_PS1}"
    if log_fn: log_fn("Extracting tools from UnRen PS1…")
    content = open(UNREN_PS1, encoding='utf-8', errors='ignore').read()
    rpatool_b64 = decompcab_b64 = None
    for line in content.split('\n'):
        s = line.strip()
        if '$rpatool' in s and '=' in s and len(s) > 200:
            try: rpatool_b64 = s.split('"')[1]
            except: pass
        if '$decompcab' in s and '=' in s and len(s) > 5000:
            try: decompcab_b64 = s.split('"')[1]
            except: pass
    if not rpatool_b64 or not decompcab_b64:
        return False, "Could not parse embedded tools from UnRen PS1."
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(rpatool, 'w', encoding='utf-8') as f:
        f.write(base64.b64decode(rpatool_b64).decode('utf-8', errors='replace'))
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(decompcab_b64))) as zf:
        zf.extractall(CACHE_DIR)
    if log_fn: log_fn("Tools ready.")
    return True, None


def find_python(game_root):
    is64 = platform.machine().endswith('64')
    dirs = []
    if is64:
        dirs += ['lib/py3-windows-x86_64', 'lib/windows-x86_64', 'lib/py2-windows-x86_64']
    dirs += ['lib/py3-windows-i686', 'lib/windows-i686', 'lib/py2-windows-i686']
    for d in dirs:
        exe = os.path.join(game_root, *d.split('/'), 'python.exe')
        if os.path.isfile(exe):
            return exe
    return None


def make_env(game_root, python_exe):
    env = os.environ.copy()
    env['PYTHONHOME'] = os.path.dirname(python_exe)
    parts = [CACHE_DIR]
    lib_root = os.path.join(game_root, 'lib')
    if os.path.isdir(lib_root):
        for name in ['pythonlib2.7', 'python2.7', 'python3.9', 'python3.10',
                     'python3.11', 'python3.8', 'python3.12']:
            p = os.path.join(lib_root, name)
            if os.path.isdir(p):
                parts.append(p)
                break
    env['PYTHONPATH'] = os.pathsep.join(parts)
    return env


def scan_folder(path):
    rpy = rpyc = rpa = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ('tl', '__pycache__', 'cache')]
        for f in files:
            if   f.endswith('.rpy'):  rpy  += 1
            elif f.endswith('.rpyc'): rpyc += 1
            elif f.endswith('.rpa'):  rpa  += 1
    return rpy, rpyc, rpa


def run_proc(cmd, cwd, env, log_fn):
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace'
    )
    for line in proc.stdout:
        if log_fn: log_fn(line.rstrip())
    proc.wait()
    return proc.returncode


def _rpa_load_index(f):
    """Parse an RPA-3.0/2.0 header + index from an open binary file.
    Returns {name: [(offset, dlen, start_prefix), ...]} or None if format unknown."""
    header = f.readline()
    if header.startswith(b'RPA-3.0'):
        parts = header.split()
        offset, key = int(parts[1], 16), int(parts[2], 16)
    elif header.startswith(b'RPA-2.0'):
        offset, key = int(header.split()[1], 16), None
    else:
        return None
    f.seek(offset)
    index = pickle.loads(zlib.decompress(f.read()), encoding='latin-1')
    norm = {}
    for name, entries in index.items():
        out = []
        for entry in entries:
            off, dlen = entry[0], entry[1]
            if key is not None:
                off ^= key; dlen ^= key
            start = entry[2] if len(entry) > 2 else b''
            if isinstance(start, str):
                start = start.encode('latin-1')
            out.append((off, dlen, start))
        norm[name.replace('\\', '/')] = out
    return norm


def _extract_rpa_fallback(game_root, game_dir, python_exe, rpa_path, log_fn):
    """Subprocess rpatool fallback for unknown RPA formats."""
    name = os.path.basename(rpa_path)
    if not python_exe:
        if log_fn: log_fn(f"  ERROR: {name} needs rpatool fallback but game Python not found.")
        return False
    ok, err = ensure_tools(log_fn)
    if not ok:
        if log_fn: log_fn(f"ERROR: {err}")
        return False
    rpatool = os.path.join(CACHE_DIR, 'rpatool.py')
    env = make_env(game_root, python_exe)
    listing = []
    run_proc([python_exe, '-O', rpatool, '-l', rpa_path],
             game_dir, env, lambda l: listing.append(l))
    rpyc_count = sum(1 for l in listing if l.strip().endswith('.rpyc'))
    if rpyc_count == 0:
        if log_fn: log_fn(f"  Skipping {name} (no .rpyc scripts)")
        return True
    needed = [l.strip() for l in listing if _rpa_needs_extract(l)]
    skipped = rpyc_count - len(needed)
    if not needed:
        if log_fn: log_fn(f"  Skipping {name} (all scripts are engine/tool files)")
        return True
    if log_fn:
        skip_note = f", {skipped} engine/tool files skipped" if skipped else ""
        log_fn(f"Extracting {name} ({len(needed)} script files{skip_note})…")
    rc = run_proc([python_exe, '-O', rpatool, '-x', rpa_path] + needed,
                  game_dir, env, log_fn)
    if rc != 0:
        return False
    all_files = [l.strip() for l in listing if l.strip()]
    if all(fl.endswith('.rpyc') for fl in all_files):
        try:
            os.remove(rpa_path)
            if log_fn: log_fn(f"  Deleted {name} (scripts extracted, no longer needed)")
        except Exception as e:
            if log_fn: log_fn(f"  WARNING: could not delete {name}: {e}")
    return True


def do_extract_rpa(game_root, game_dir, python_exe, log_fn):
    rpa_files = []
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d not in ('tl', '__pycache__', 'cache')]
        for f in sorted(files):
            if f.endswith('.rpa'):
                rpa_files.append(os.path.join(root, f))
    if not rpa_files:
        if log_fn: log_fn("No .rpa files found.")
        return True
    ok_all = True
    for rpa_path in rpa_files:
        name = os.path.basename(rpa_path)
        try:
            with open(rpa_path, 'rb') as f:
                index = _rpa_load_index(f)
                if index is None:
                    if log_fn: log_fn(f"  {name}: unknown RPA format — trying rpatool fallback")
                    if not _extract_rpa_fallback(game_root, game_dir, python_exe, rpa_path, log_fn):
                        ok_all = False
                    continue
                names = list(index)
                rpyc_count = sum(1 for n in names if n.endswith('.rpyc'))
                if rpyc_count == 0:
                    if log_fn: log_fn(f"  Skipping {name} (no .rpyc scripts)")
                    continue
                needed = [n for n in names if _rpa_needs_extract(n)]
                skipped = rpyc_count - len(needed)
                if not needed:
                    if log_fn: log_fn(f"  Skipping {name} (all scripts are engine/tool files)")
                    continue
                if log_fn:
                    skip_note = f", {skipped} engine/tool files skipped" if skipped else ""
                    log_fn(f"Extracting {name} ({len(needed)} script files{skip_note})…")
                for n in needed:
                    dest = os.path.join(game_dir, *n.split('/'))
                    parent = os.path.dirname(dest)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(dest, 'wb') as out:
                        for off, dlen, start in index[n]:
                            f.seek(off)
                            out.write(start + f.read(dlen - len(start)))
                    if log_fn: log_fn(f"  {n}")
            if all(n.endswith('.rpyc') for n in names):
                try:
                    os.remove(rpa_path)
                    if log_fn: log_fn(f"  Deleted {name} (scripts extracted, no longer needed)")
                except Exception as e:
                    if log_fn: log_fn(f"  WARNING: could not delete {name}: {e}")
        except Exception as e:
            if log_fn: log_fn(f"  ERROR extracting {name}: {e}")
            ok_all = False
    return ok_all


def do_decompile(game_root, game_dir, python_exe, log_fn):
    ok, err = ensure_tools(log_fn)
    if not ok: log_fn(f"ERROR: {err}"); return False
    boot = os.path.join(CACHE_DIR, '_unrpyc_boot.py')
    with open(boot, 'w') as f:
        f.write(
            'import sys, os\n'
            '_here = os.path.dirname(os.path.abspath(__file__))\n'
            'if _here not in sys.path:\n'
            '    sys.path.insert(0, _here)\n'
            'sys.argv[0] = os.path.join(_here, "unrpyc.py")\n'
            '_src = open(sys.argv[0], "rb").read()\n'
            'exec(compile(_src, sys.argv[0], "exec"))\n'
        )
    procs = min(4, os.cpu_count() or 1)
    rc = run_proc(
        [python_exe, '-O', boot, '--clobber', '--processes', str(procs), game_dir],
        game_dir, make_env(game_root, python_exe), log_fn
    )
    if rc != 0 and procs > 1:
        if log_fn: log_fn(f"  Parallel decompile failed (rc={rc}) — retrying single-process…")
        rc = run_proc(
            [python_exe, '-O', boot, '--clobber', '--processes', '1', game_dir],
            game_dir, make_env(game_root, python_exe), log_fn
        )
    ren_conflicts = 0
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d not in ('tl', '__pycache__', 'cache')]
        ren_bases = {f[:-7] for f in files if f.endswith('_ren.py')}
        for base in ren_bases:
            rpy = os.path.join(root, base + '.rpy')
            if os.path.isfile(rpy):
                try:
                    os.remove(rpy)
                    ren_conflicts += 1
                except Exception:
                    pass
    if log_fn and ren_conflicts:
        log_fn(f"  Removed {ren_conflicts} decompiled .rpy conflicting with _ren.py source")
    removed = 0
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d not in ('tl', '__pycache__', 'cache')]
        for f in files:
            if f.endswith('.rpyc'):
                rpy = os.path.join(root, f[:-1])
                if os.path.isfile(rpy):
                    try:
                        os.remove(os.path.join(root, f))
                        removed += 1
                    except Exception:
                        pass
    if log_fn and removed:
        log_fn(f"  Deleted {removed} stale .rpyc files (matching .rpy present)")
    _fix_custom_displayables(game_dir, log_fn)
    return rc == 0


_ZOOM_PROPS = re.compile(r'^\s+(zoom_amount|zoom_speed|zoom_min|zoom_max|start_zoom|zoom_align|zoom_callback)\b')

def _fix_custom_displayables(game_dir, log_fn=None):
    fixed = 0
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d not in ('tl', '__pycache__', 'cache')]
        for fname in files:
            if not fname.endswith('.rpy'): continue
            path = os.path.join(root, fname)
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
            except Exception:
                continue
            changed = False
            for i, line in enumerate(lines):
                if not _ZOOM_PROPS.match(line): continue
                prop_indent = len(line) - len(line.lstrip())
                for j in range(i - 1, -1, -1):
                    jl = lines[j]
                    if not jl.strip(): continue
                    if len(jl) - len(jl.lstrip()) < prop_indent:
                        if re.match(r'\s+viewport\s*:', jl):
                            lines[j] = jl.replace('viewport:', 'zoom_viewport:', 1)
                            changed = True
                        break
            if changed:
                _write_atomic(path, lines)
                fixed += 1
    if log_fn and fixed:
        log_fn(f"  Fixed zoom_viewport: decompile error in {fixed} files")


def _read_file(path):
    for enc in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
    return []


def _write_atomic(path, lines):
    """Write to .tmp then atomically replace, so a crash never corrupts the original."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    os.replace(tmp, path)


_TAG_RE = re.compile(r'\{[^{}]*\}|\[[^\[\]]*\]')

def _tags_match(eng, thai):
    """True if the Thai text preserves every {tag} and [variable] from the English."""
    return sorted(_TAG_RE.findall(eng)) == sorted(_TAG_RE.findall(thai))


def _is_translatable(text):
    clean = re.sub(r'\[.*?\]|\{[^}]*\}', '', text).strip()
    if not clean:
        return False
    if re.search(r'[/\\]|\.(?:png|jpg|jpeg|gif|webp|bmp|mp3|ogg|wav|flac|ttf|otf)\b', clean, re.I):
        return False
    if re.match(r'^#[0-9a-fA-F]{3,8}$', clean):
        return False
    if re.match(r'^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$', clean):
        return False
    return bool(re.search(r'[a-zA-Z]', clean))


_SCREEN_TEXT_WIDGETS = set()

def parse_rpy_file(path, rel_path):
    rows = []
    seen = set()
    lines = _read_file(path)
    in_menu = False; menu_indent = -1
    in_layeredimage = False; layeredimage_indent = -1
    in_screen = False; screen_indent = -1
    in_image_atl = False; image_atl_indent = -1
    in_python = False; python_indent = -1
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip('\n')
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        if in_layeredimage and indent <= layeredimage_indent:
            in_layeredimage = False
        if re.match(r'^\s*layeredimage\b', line):
            in_layeredimage = True; layeredimage_indent = indent; continue
        if in_screen and indent <= screen_indent:
            in_screen = False
        if re.match(r'^\s*screen\b', line):
            in_screen = True; screen_indent = indent; continue
        if in_image_atl and indent <= image_atl_indent:
            in_image_atl = False
        if re.match(r'^\s*(?:image|transform)\b[^=]*:\s*$', line):
            in_image_atl = True; image_atl_indent = indent; continue
        if in_python and indent <= python_indent:
            in_python = False
        if re.match(r'^\s*(?:init\s+(?:-?\d+\s+)?)?\bpython\b[^:]*:\s*$', line):
            in_python = True; python_indent = indent; continue
        m_phone = re.match(r'^\s+\$\s+\w[\w.]*\.send_phone_message\([^,]+,\s*"((?:[^"\\]|\\.)*)"', line)
        if m_phone:
            text = m_phone.group(1)
            if text.strip() and _is_translatable(text):
                key = (i, text)
                if key not in seen:
                    seen.add(key)
                    rows.append({'file': rel_path, 'line': i, 'type': 'dialogue',
                                 'character': 'phone_msg', 'english': text, 'thai': ''})
            continue
        if re.match(r'^\s*menu(\s+\w+)?\s*:', line):
            in_menu = True; menu_indent = indent; continue
        if in_menu and stripped and indent <= menu_indent:
            in_menu = False
        if in_menu:
            m = re.match(r'^\s+"((?:[^"\\]|\\.)*)"\s*:', line)
            if m:
                rows.append({'file': rel_path, 'line': i, 'type': 'menu_choice',
                             'character': '', 'english': m.group(1), 'thai': ''})
                continue
        m = re.match(r'^\s+(?:(\w+)(?:\s+\w+)*\s+)?u?"((?:[^"\\]|\\.)*)"(\s+with\s+\w+)?(\s+id\s+"[^"]*")?[^"]*$', line)
        if m:
            char, text = m.group(1), m.group(2)
            if char in _SCREEN_TEXT_WIDGETS:
                pass
            else:
                if in_layeredimage or in_image_atl or in_python:
                    pass
                elif text.strip() and char not in SKIP_KEYWORDS and not in_screen and _is_translatable(text):
                    key = (i, text)
                    if key not in seen:
                        seen.add(key)
                        rows.append({'file': rel_path, 'line': i,
                                     'type': 'dialogue' if char else 'narration',
                                     'character': char or '', 'english': text, 'thai': ''})
                continue
        m2 = re.match(r'^\s+(\w+)\s+(?:_\()?u?"((?:[^"\\]|\\.)*)"', line)
        if m2:
            widget, text = m2.group(1), m2.group(2)
            if widget in _SCREEN_TEXT_WIDGETS and not in_python and text.strip() and _is_translatable(text):
                key = (i, text)
                if key not in seen:
                    seen.add(key)
                    rows.append({'file': rel_path, 'line': i,
                                 'type': 'ui_text',
                                 'character': widget, 'english': text, 'thai': ''})
        m3 = re.match(r'^\s+"(?:[^"\\]|\\.)*"\s+u?"((?:[^"\\]|\\.)*)"[^"]*$', line)
        if m3:
            text = m3.group(1)
            if not in_layeredimage and not in_image_atl and not in_screen and not in_python and text.strip() and _is_translatable(text):
                key = (i, text)
                if key not in seen:
                    seen.add(key)
                    rows.append({'file': rel_path, 'line': i, 'type': 'dialogue',
                                 'character': '', 'english': text, 'thai': ''})
    return rows


_SKIP_SCAN_DIRS = {'tl', '__pycache__', 'cache'} | _SKIP_RPA_DIRS

def extract_strings(game_dir, log_fn=None):
    rows = []
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_SCAN_DIRS]
        for fname in sorted(files):
            if fname.endswith('.rpy'):
                path = os.path.join(root, fname)
                rel = os.path.relpath(path, game_dir)
                try:
                    fr = parse_rpy_file(path, rel)
                except Exception as e:
                    if log_fn: log_fn(f"  SKIPPED {rel}: {e}")
                    continue
                if log_fn: log_fn(f"  {rel}: {len(fr)} strings")
                rows.extend(fr)
    return rows


def write_world_setting(path, rows, game_dir):
    import datetime
    game_name = os.path.basename(os.path.dirname(game_dir)) or os.path.basename(game_dir)
    today = datetime.date.today().isoformat()

    # character counts (dialogue only, skip blanks)
    char_counts = {}
    type_counts = {}
    for r in rows:
        t = r['type']
        type_counts[t] = type_counts.get(t, 0) + 1
        c = r['character'].strip()
        if t == 'dialogue' and c and c != 'phone_msg':
            char_counts[c] = char_counts.get(c, 0) + 1

    lines = [
        f"# World Setting — {game_name}",
        f"",
        f"> Auto-generated {today}. Fill in the Glossary and Notes before sending to AI.",
        f"",
        f"## Characters",
        f"",
        f"| Name | Dialogue lines |",
        f"|------|---------------|",
    ]
    for name, cnt in sorted(char_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {name} | {cnt} |")
    if not char_counts:
        lines.append("| *(none detected)* | — |")

    lines += [
        f"",
        f"## String Statistics",
        f"",
        f"| Type | Count |",
        f"|------|-------|",
    ]
    for t, cnt in sorted(type_counts.items()):
        lines.append(f"| {t} | {cnt} |")
    lines.append(f"| **Total** | **{len(rows)}** |")

    lines += [
        f"",
        f"## Glossary / Terms",
        f"",
        f"> Add game-specific proper nouns, place names, and recurring terms here.",
        f"",
        f"| English | Thai | Notes |",
        f"|---------|------|-------|",
        f"|  |  |  |",
        f"",
        f"## Translation Notes",
        f"",
        f"- **Target language:** Thai",
        f"- **Tone:** (fill in — formal / casual / etc.)",
        f"- **Special rules:** (fill in)",
    ]

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def setup_font(game_dir, font_src, log_fn=None):
    font_name = os.path.basename(font_src)
    fonts_dir = os.path.join(game_dir, 'fonts')
    os.makedirs(fonts_dir, exist_ok=True)
    dst = os.path.join(fonts_dir, font_name)
    if os.path.abspath(font_src) != os.path.abspath(dst):
        shutil.copy2(font_src, dst)
    if log_fn: log_fn(f"Font copied → game/fonts/{font_name}")

    # Scan .rpy files for hardcoded font literals (e.g. inline screen-language font props).
    # These are never exposed via gui.* or renpy.style.styles, so runtime scanning misses them.
    _font_pat = re.compile(
        r'(?:text_)?font\s+["\']([^"\']+\.(?:ttf|otf|woff2?))["\']', re.IGNORECASE)
    static_fonts: set = set()
    for _root, _dirs, _files in os.walk(game_dir):
        for _fname in _files:
            if not _fname.endswith('.rpy'):
                continue
            try:
                with open(os.path.join(_root, _fname), 'r', encoding='utf-8', errors='ignore') as _rf:
                    for _line in _rf:
                        for _m in _font_pat.finditer(_line):
                            _v = _m.group(1).strip()
                            if _v and _v != font_name and not _v.endswith('/' + font_name):
                                static_fonts.add(_v)
            except Exception:
                pass
    if log_fn and static_fonts:
        log_fn(f"Fonts found in .rpy files: {', '.join(sorted(static_fonts))}")
    static_fonts_repr = repr(sorted(static_fonts))

    override_path = os.path.join(game_dir, '_thai_font.rpy')
    _KNOWN = [
        "default", "text", "say_dialogue", "say_label", "say_thought",
        "input", "nvl_dialogue", "nvl_label", "nvl_thought",
        "nvl_menu_choice", "nvl_menu_choice_chosen",
        "menu_choice", "menu_choice_chosen",
        "button_text", "choice_button_text", "quick_button_text",
        "check_button_text", "radio_button_text",
        "confirm_prompt_text", "confirm_button_text",
        "label_text", "notify_text", "game_menu_label_text",
        "history_text", "history_name",
        "pref_label_text", "pref_button_text",
        "slot_button_text", "help_text", "about_text",
    ]
    known_str = ', '.join(f'"{s}"' for s in _KNOWN)
    with open(override_path, 'w', encoding='utf-8') as f:
        f.write(
            f'init 999 python:\n'
            f'    _f = "fonts/{font_name}"\n'
            f'    # Strategy 0: font_replacement_map — intercepts at render time.\n'
            f'    # Pre-seeded with fonts scanned from .rpy files at tool-generation time\n'
            f'    # so inline screen-language font properties (e.g. phone/chat UIs) are caught.\n'
            f'    try:\n'
            f'        _olds = set({static_fonts_repr})\n'
            f'        for _attr in dir(gui):\n'
            f'            _v = getattr(gui, _attr, None)\n'
            f'            if isinstance(_v, str) and (_attr.endswith("_font") or _attr == "font") and _v != _f:\n'
            f'                _olds.add(_v)\n'
            f'        try:\n'
            f'            for _sn in list(renpy.style.styles):\n'
            f'                try:\n'
            f'                    _sf = getattr(style, _sn).font\n'
            f'                    if isinstance(_sf, str) and _sf and _sf != _f:\n'
            f'                        _olds.add(_sf)\n'
            f'                except Exception: pass\n'
            f'        except Exception: pass\n'
            f'        for _old in _olds:\n'
            f'            for _b in (False, True):\n'
            f'                for _i in (False, True):\n'
            f'                    config.font_replacement_map[(_old, _b, _i)] = (_f, _b, _i)\n'
            f'    except Exception: pass\n'
            f'\n'
            f'init 1000 python:\n'
            f'    _f = "fonts/{font_name}"\n'
            f'    # Strategy 1: override every gui.*_font store variable.\n'
            f'    try:\n'
            f'        for _attr in dir(gui):\n'
            f'            if _attr.endswith("_font") or _attr == "font":\n'
            f'                try:\n'
            f'                    if isinstance(getattr(gui, _attr, None), str):\n'
            f'                        setattr(gui, _attr, _f)\n'
            f'                except Exception: pass\n'
            f'    except Exception: pass\n'
            f'    # Strategy 2: iterate all registered styles by name.\n'
            f'    try:\n'
            f'        for _sn in list(renpy.style.styles):\n'
            f'            try: getattr(style, _sn).font = _f\n'
            f'            except Exception: pass\n'
            f'    except Exception: pass\n'
            f'    # Strategy 3: named fallback for built-in Ren\'Py styles.\n'
            f'    for _sn in [{known_str}]:\n'
            f'        try: getattr(style, _sn).font = _f\n'
            f'        except Exception: pass\n'
            f'    style.default.font = _f\n'
        )
    rpyc_path = override_path[:-4] + '.rpyc'
    if os.path.isfile(rpyc_path):
        try:
            os.remove(rpyc_path)
            if log_fn: log_fn(f"Deleted stale _thai_font.rpyc")
        except Exception as e:
            if log_fn: log_fn(f"WARNING: could not delete _thai_font.rpyc: {e}")
    if log_fn: log_fn(f"Font override written → game/_thai_font.rpy")


def fill_tl_thai(game_dir, csv_path, log_fn=None):
    tl_dir = os.path.join(game_dir, 'tl', 'thai')
    if not os.path.isdir(tl_dir):
        return 0, "tl/thai/ not found. Run 'Generate Template' first."
    en_to_th = {}
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                thai = row.get('thai', '').strip()
                if thai:
                    en_to_th[row['english']] = thai
    except Exception as e:
        return 0, str(e)
    if not en_to_th:
        return 0, "No translations found in CSV (thai column is empty)."
    template_files = []
    for root, dirs, files in os.walk(tl_dir):
        for fname in sorted(files):
            if fname.endswith('.rpy') and not fname.startswith('_'):
                template_files.append(os.path.join(root, fname))
    if not template_files:
        return 0, "NO_TEMPLATES"
    if log_fn: log_fn(f"  Found {len(template_files)} template files in tl/thai/")
    total = 0
    for path in template_files:
        rel = os.path.relpath(path, tl_dir)
        try:
            lines = _read_file(path)
            changed = 0
            i = 0
            while i < len(lines):
                original = None
                # Dialogue blocks: commented original, empty quoted line below.
                m = re.match(r'^\s+#\s*(?:\w+\s+)?"((?:[^"\\]|\\.)*)"', lines[i].rstrip())
                if m:
                    original = m.group(1)
                else:
                    # `translate thai strings:` blocks: old "..." / new ""
                    m_old = re.match(r'^\s+old\s+"((?:[^"\\]|\\.)*)"\s*$', lines[i].rstrip())
                    if m_old:
                        original = m_old.group(1)
                if original is not None and original in en_to_th:
                    thai = en_to_th[original]
                    if not _tags_match(original, thai):
                        if log_fn: log_fn(f"  TAG MISMATCH (skipped): {original[:60]}")
                    else:
                        j = i + 1
                        while j < len(lines) and not lines[j].strip():
                            j += 1
                        if j < len(lines) and '""' in lines[j]:
                            new = lines[j].replace('""', '"{}"'.format(thai.replace('"', '\\"')), 1)
                            if new != lines[j]:
                                lines[j] = new
                                changed += 1
                i += 1
            if changed:
                _write_atomic(path, lines)
                if log_fn: log_fn(f"  {rel}: {changed} filled")
            total += changed
        except Exception as e:
            if log_fn: log_fn(f"  SKIPPED {rel}: {e}")
    return total, f"Filled {total} translations in tl/thai/."


def apply_inplace(game_dir, csv_path, backup, log_fn=None):
    trans = {}
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                thai = row.get('thai', '').strip()
                if thai:
                    trans[(row['file'].strip(), int(row['line']))] = (row['english'], thai)
    except Exception as e:
        return 0, str(e)
    if not trans:
        return 0, "No translations found (thai column is empty)."
    by_file = {}
    for (rf, ln), v in trans.items():
        by_file.setdefault(rf, {})[ln] = v
    total = 0
    for rel_file, line_map in by_file.items():
        try:
            full = os.path.join(game_dir, rel_file)
            if not os.path.isfile(full): continue
            lines = _read_file(full)
            if backup: shutil.copy2(full, full + '.bak')
            changed = 0
            for ln, (eng, th) in line_map.items():
                idx = ln - 1
                if 0 <= idx < len(lines):
                    raw = lines[idx]
                    kw_m = re.match(r'^\s+(\w+)\b', raw)
                    if kw_m and kw_m.group(1) in SKIP_KEYWORDS and kw_m.group(1) not in _SCREEN_TEXT_WIDGETS:
                        continue
                    if not _tags_match(eng, th):
                        if log_fn: log_fn(f"  TAG MISMATCH (skipped): {eng[:60]}")
                        continue
                    th_safe = th.replace('"', '\\"')
                    new = raw.replace(f'"{eng}"', f'"{th_safe}"', 1)
                    if new != raw:
                        lines[idx] = new; changed += 1
            _write_atomic(full, lines)
            rpyc = full[:-4] + '.rpyc'
            if os.path.isfile(rpyc):
                os.remove(rpyc)
            if log_fn: log_fn(f"  {rel_file}: {changed} replaced")
            total += changed
        except Exception as e:
            if log_fn: log_fn(f"  SKIPPED {rel_file}: {e}")
    return total, f"Done — {total} lines replaced."


def restore_from_backup(game_dir, log_fn=None):
    count = 0
    for root, _, files in os.walk(game_dir):
        for fn in files:
            if fn.endswith('.bak'):
                bak = os.path.join(root, fn)
                orig = bak[:-4]
                try:
                    shutil.copy2(bak, orig)
                    os.remove(bak)
                    count += 1
                    if log_fn: log_fn(f"  Restored: {os.path.relpath(orig, game_dir)}")
                except Exception as e:
                    if log_fn: log_fn(f"  WARNING: could not restore {fn}: {e}")
    return count


# ─── GUI ─────────────────────────────────────────────────────────────────────

GREEN  = '#1a7a1a'
RED    = '#b00000'
GRAY   = '#666666'
ORANGE = '#b05000'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Ren'Py EN→TH Translation Tool  v{APP_VERSION}")
        self.minsize(720, 900)
        self.resizable(True, True)

        self._q           = queue.Queue()
        self._busy        = False
        self._action_btns = []

        self._game_root  = ''
        self._game_dir   = ''
        self._python_exe = ''
        self._scan_res   = None
        self._csv_out    = ''

        self._build()
        self._poll()
        if app_updater:
            app_updater.cleanup_after_update()
            self._startup_update_check()

    def _build(self):
        self._build_content(self)
        lf = ttk.LabelFrame(self, text="Log", padding=6)
        lf.pack(fill='both', expand=True, padx=14, pady=(6, 14))
        self._log = scrolledtext.ScrolledText(lf, height=8, state='disabled', wrap='word')
        self._log.pack(fill='both', expand=True)
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=14, pady=(0, 10))
        self._upd_lbl = ttk.Label(bar, text=f"v{APP_VERSION}", foreground=GRAY)
        self._upd_lbl.pack(side='left')
        ttk.Button(bar, text="Check for Updates…",
                   command=self._open_updater).pack(side='right')

    def _open_updater(self):
        if app_updater is None:
            messagebox.showerror("Error", "app_updater.py not found next to the app.")
            return
        win = getattr(self, '_upd_win', None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        self._upd_win = app_updater.UpdateDialog(self, APP_VERSION)

    def _startup_update_check(self):
        def work():
            try:
                tag = app_updater.latest_release_tag()
                if tag and app_updater.is_newer(tag, APP_VERSION):
                    self._ui(lambda: self._upd_lbl.configure(
                        text=f"v{APP_VERSION}  —  Update available: {tag}",
                        foreground=ORANGE))
            except Exception:
                pass  # offline / rate-limited — run normally
        threading.Thread(target=work, daemon=True).start()

    def _build_content(self, parent):
        outer = ttk.Frame(parent, padding=14)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)

        top = ttk.LabelFrame(outer, text="Game Root Folder", padding=8)
        top.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Select the folder that contains  renpy/  game/  lib/  (the game's root):") \
            .grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
        self._folder_var = tk.StringVar()
        ttk.Entry(top, textvariable=self._folder_var).grid(row=1, column=0, sticky='ew', padx=(0, 6))
        ttk.Button(top, text="Browse…", command=self._browse_root).grid(row=1, column=1, padx=(0, 6))
        self._scan_btn = ttk.Button(top, text="Scan", width=8, command=self._do_scan)
        self._scan_btn.grid(row=1, column=2)
        self._action_btns.append(self._scan_btn)

        rf = ttk.LabelFrame(outer, text="Scan Results", padding=8)
        rf.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        self._result_lbl = ttk.Label(rf, text="No folder scanned yet.")
        self._result_lbl.pack(anchor='w')

        s1 = ttk.LabelFrame(outer,
            text="Step 1 — Prepare  (extract .rpa archives + decompile .rpyc files)", padding=8)
        s1.grid(row=2, column=0, sticky='ew', pady=(0, 8))
        s1.columnconfigure(0, weight=1)
        self._s1_lbl = ttk.Label(s1, text="Waiting for scan…", foreground=GRAY)
        self._s1_lbl.grid(row=0, column=0, sticky='w')
        self._s1_btn = ttk.Button(s1, text="Run Prepare",
                                  command=self._do_prepare, state='disabled')
        self._s1_btn.grid(row=1, column=0, sticky='w', pady=(6, 0))

        s2 = ttk.LabelFrame(outer, text="Step 2 — Extract English text  →  CSV file", padding=8)
        s2.grid(row=3, column=0, sticky='ew', pady=(0, 8))
        s2.columnconfigure(0, weight=1)
        self._s2_lbl = ttk.Label(s2, text="Waiting…", foreground=GRAY)
        self._s2_lbl.grid(row=0, column=0, columnspan=2, sticky='w')
        self._s2_btn = ttk.Button(s2, text="Extract & Save CSV",
                                  command=self._do_extract, state='disabled')
        self._s2_btn.grid(row=1, column=0, sticky='w', pady=(6, 0))
        self._s2_open = ttk.Button(s2, text="Open folder",
                                   command=self._open_csv_folder, state='disabled')
        self._s2_open.grid(row=1, column=1, padx=(8, 0), pady=(6, 0))

        s3 = ttk.LabelFrame(outer,
            text="Step 3 — Translate  (open CSV with your AI, fill 'thai' column, save)", padding=8)
        s3.grid(row=4, column=0, sticky='ew', pady=(0, 8))
        s3.columnconfigure(1, weight=1)
        self._s3_lbl = ttk.Label(s3,
            text="After Step 2, open the saved CSV with your AI translator.\n"
                 "Fill in the 'thai' column for every row, then save the file.",
            foreground=GRAY)
        self._s3_lbl.grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
        ttk.Label(s3, text="Translated CSV:").grid(row=1, column=0, sticky='w')
        self._csv_var = tk.StringVar()
        ttk.Entry(s3, textvariable=self._csv_var).grid(row=1, column=1, padx=6, sticky='ew')
        ttk.Button(s3, text="Browse…", command=self._browse_csv).grid(row=1, column=2)

        s4lang = ttk.LabelFrame(outer,
            text="Step 4 — Thai Language Setup  (font + language option in preferences)", padding=8)
        s4lang.grid(row=5, column=0, sticky='ew', pady=(0, 8))
        s4lang.columnconfigure(1, weight=1)
        self._font_var = tk.StringVar(value=DEFAULT_FONT if os.path.isfile(DEFAULT_FONT) else '')
        _font_ok = os.path.isfile(DEFAULT_FONT)
        ttk.Label(s4lang,
            text="Built-in Thai font (IBM Plex Sans Thai) is installed automatically."
                 if _font_ok else
                 "WARNING: built-in font missing — font\\IBMPlexSansThai-Regular.ttf not found.",
            foreground=GRAY if _font_ok else RED).grid(
            row=1, column=0, columnspan=3, sticky='w', pady=(0, 6))
        self._use_tl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(s4lang,
            text="Create tl/thai/ translation folder  (adds Thai option in game preferences)",
            variable=self._use_tl_var).grid(
            row=2, column=0, columnspan=3, sticky='w')
        self._s4_btn = ttk.Button(s4lang, text="Apply Font & Language Setup",
                                  command=self._do_setup_lang, state='disabled')
        self._s4_btn.grid(row=3, column=0, columnspan=3, sticky='w', pady=(6, 0))
        self._s4_lbl = ttk.Label(s4lang, text="")
        self._s4_lbl.grid(row=4, column=0, columnspan=3, sticky='w', pady=(4, 0))

        s5 = ttk.LabelFrame(outer, text="Step 5 — Apply Translations", padding=8)
        s5.grid(row=6, column=0, sticky='ew', pady=(0, 8))
        s5.columnconfigure(0, weight=1)
        self._backup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(s5, text="Backup original .rpy files first  (.bak copies)",
                        variable=self._backup_var).grid(row=0, column=0, sticky='w')
        self._s5_btn = ttk.Button(s5, text="Apply Translations",
                                  command=self._do_apply, state='disabled')
        self._s5_btn.grid(row=1, column=0, sticky='w', pady=(6, 0))
        self._s5_lbl = ttk.Label(s5, text="")
        self._s5_lbl.grid(row=2, column=0, sticky='w', pady=(4, 0))
        self._s5_restore_btn = ttk.Button(s5, text="Restore from Backup (.bak)",
                                          command=self._do_restore, state='disabled')
        self._s5_restore_btn.grid(row=3, column=0, sticky='w', pady=(4, 0))

    # ── Queue / threading ─────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True: self._q.get_nowait()()
        except queue.Empty: pass
        self.after(50, self._poll)

    def _ui(self, fn, *a): self._q.put(lambda: fn(*a))
    def _log_line(self, msg): self._ui(self._write_log, msg)

    def _write_log(self, msg):
        self._log.configure(state='normal')
        self._log.insert('end', msg + '\n')
        self._log.see('end')
        self._log.configure(state='disabled')

    def _run(self, fn, done_cb):
        self._busy = True
        for btn in self._action_btns: btn.configure(state='disabled')
        def worker():
            fn()
            self._ui(self._finish, done_cb)
        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, done_cb):
        self._busy = False
        for btn in self._action_btns: btn.configure(state='normal')
        done_cb()

    # ── Browse helpers ────────────────────────────────────────────────────────

    def _browse_root(self):
        d = filedialog.askdirectory(title="Select game root folder")
        if d:
            self._folder_var.set(d)
            self._do_scan()

    def _browse_csv(self):
        p = filedialog.askopenfilename(
            title="Select translated CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if p:
            self._csv_var.set(p)
            self._s5_btn.configure(state='normal')
            self._s5_restore_btn.configure(state='normal')

    def _open_csv_folder(self):
        if self._csv_out and os.path.isfile(self._csv_out):
            os.startfile(os.path.dirname(self._csv_out))

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _do_scan(self):
        root = self._folder_var.get().strip()
        if not root or not os.path.isdir(root):
            messagebox.showerror("Error", "Please select a valid folder.")
            return
        game_dir = os.path.join(root, 'game')
        if not os.path.isdir(game_dir):
            data_dir = os.path.join(root, 'data')
            if os.path.isdir(data_dir):
                game_dir = data_dir
            else:
                parent = os.path.dirname(root)
                if os.path.isdir(os.path.join(parent, 'renpy')):
                    if messagebox.askyesno("Wrong folder?",
                        f"Looks like you selected the game/ subfolder.\n"
                        f"Switch to parent?\n\n{parent}"):
                        self._folder_var.set(parent)
                        self._do_scan()
                    return
                game_dir = root
        python_exe = find_python(root)
        rpy, rpyc, rpa = scan_folder(game_dir)
        self._game_root = root
        self._game_dir  = game_dir
        self._python_exe = python_exe
        self._scan_res  = (rpy, rpyc, rpa)
        self._apply_scan(rpy, rpyc, rpa, python_exe)

    def _apply_scan(self, rpy, rpyc, rpa, python_exe):
        py_line = f"  Python : {python_exe}" if python_exe else "  Python : NOT FOUND"
        self._result_lbl.configure(
            text=(f"  .rpa archives : {rpa}\n"
                  f"  .rpyc compiled: {rpyc}\n"
                  f"  .rpy source   : {rpy}\n"
                  f"{py_line}"), foreground='black')
        needs = rpa > 0 or rpyc > 0
        if not needs and rpy > 0:
            self._s1_lbl.configure(text="No preparation needed — .rpy files present.", foreground=GREEN)
            self._s1_btn.configure(state='disabled')
            self._s2_btn.configure(state='normal')
            self._s2_lbl.configure(text=f"Ready — {rpy} .rpy files found.", foreground='black')
        elif needs and python_exe:
            parts = []
            if rpa:  parts.append(f"extract {rpa} .rpa")
            if rpyc: parts.append(f"decompile {rpyc} .rpyc")
            self._s1_lbl.configure(text="Needs: " + "  +  ".join(parts), foreground=ORANGE)
            self._s1_btn.configure(state='normal')
        elif needs and not python_exe:
            self._s1_lbl.configure(
                text="Cannot auto-prepare: game Python not found.", foreground=RED)
            self._s1_btn.configure(state='disabled')
        else:
            self._s1_lbl.configure(text="No game files found.", foreground=RED)
        if rpy == 0:
            self._s2_lbl.configure(text="Waiting for Step 1…", foreground=GRAY)
            self._s2_btn.configure(state='disabled')
        if self._game_dir:
            self._s4_btn.configure(state='normal')
            self._s5_restore_btn.configure(state='normal')

    # ── Step 1: Prepare ───────────────────────────────────────────────────────

    def _do_prepare(self):
        if self._busy: return
        rpy, rpyc, rpa = self._scan_res
        self._s1_btn.configure(state='disabled')
        self._write_log("\n── Step 1: Prepare ──")
        def work():
            if rpa > 0:
                self._log_line("Extracting .rpa archives…")
                do_extract_rpa(self._game_root, self._game_dir, self._python_exe, self._log_line)
            if rpyc > 0:
                self._log_line("\nDecompiling .rpyc files…")
                do_decompile(self._game_root, self._game_dir, self._python_exe, self._log_line)
        def done():
            rpy2, rpyc2, rpa2 = scan_folder(self._game_dir)
            self._scan_res = (rpy2, rpyc2, rpa2)
            if rpy2 > 0:
                self._s1_lbl.configure(text=f"Done — {rpy2} .rpy files ready.", foreground=GREEN)
                self._s2_lbl.configure(text=f"Ready — {rpy2} .rpy files found.", foreground='black')
                self._s2_btn.configure(state='normal')
            else:
                self._s1_lbl.configure(text="Still no .rpy files. Check log.", foreground=RED)
                self._s1_btn.configure(state='normal')
        self._run(work, done)

    # ── Step 2: Extract ───────────────────────────────────────────────────────

    def _do_extract(self):
        if self._busy: return
        self._s2_btn.configure(state='disabled')
        self._write_log("\n── Step 2: Extracting text ──")
        _rows = [None]
        def work():
            _rows[0] = extract_strings(self._game_dir, self._log_line)
        def done():
            rows = _rows[0] or []
            if not rows:
                self._s2_lbl.configure(text="No strings found.", foreground=RED)
                self._s2_btn.configure(state='normal')
                return
            csv_path = os.path.join(self._game_root, 'translation.csv')
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.DictWriter(f, fieldnames=['file','line','type','character','english','thai'])
                w.writeheader()
                w.writerows(rows)
            self._csv_out = csv_path
            self._csv_var.set(csv_path)
            ws_path = os.path.join(self._game_root, 'world_setting.md')
            write_world_setting(ws_path, rows, self._game_dir)
            self._s2_lbl.configure(text=f"Saved {len(rows)} strings  →  {csv_path}", foreground=GREEN)
            self._s2_open.configure(state='normal')
            self._s3_lbl.configure(foreground='black')
            self._s5_btn.configure(state='normal')
            self._s5_restore_btn.configure(state='normal')
            self._write_log(f"\nExtracted {len(rows)} strings → {csv_path}")
            self._write_log(f"World setting → {ws_path}")
        self._run(work, done)

    # ── Step 4: Font & Language Setup ─────────────────────────────────────────

    def _do_setup_lang(self):
        if self._busy: return
        if not self._game_dir:
            messagebox.showerror("Error", "Please scan a game folder first.")
            return
        font_src = self._font_var.get().strip()
        if (not font_src or not os.path.isfile(font_src)) and os.path.isfile(DEFAULT_FONT):
            font_src = DEFAULT_FONT          # built-in font — no Browse needed
            self._font_var.set(DEFAULT_FONT)
        use_tl   = self._use_tl_var.get()
        self._s4_btn.configure(state='disabled')
        self._write_log("\n── Step 4: Thai Language Setup ──")
        def work():
            if font_src and os.path.isfile(font_src):
                setup_font(self._game_dir, font_src, self._log_line)
            elif font_src:
                self._log_line(f"WARNING: Font file not found: {font_src}")
            else:
                self._log_line("WARNING: Built-in font missing — font install skipped. "
                               "Expected: " + DEFAULT_FONT)
            if not font_src and use_tl:
                tl_dir = os.path.join(self._game_dir, 'tl', 'thai')
                os.makedirs(tl_dir, exist_ok=True)
        def done():
            tl_dir = os.path.join(self._game_dir, 'tl', 'thai')
            tl_exists = os.path.isdir(tl_dir)
            parts = []
            if font_src and os.path.isfile(font_src): parts.append("font copied")
            if tl_exists: parts.append("tl/thai/ ready")
            msg = "Done — " + ", ".join(parts) if parts else "Done."
            self._s4_lbl.configure(text=msg, foreground=GREEN)
            self._write_log(f"\n{msg}")
            self._s4_btn.configure(state='normal')
        self._run(work, done)

    # ── Step 5: Apply Translations ────────────────────────────────────────────

    def _do_apply(self):
        if self._busy: return
        csv_path = self._csv_var.get().strip()
        if not csv_path or not os.path.isfile(csv_path):
            messagebox.showerror("Error", "Please select a translated CSV file (Step 3).")
            return
        if not self._game_dir:
            messagebox.showerror("Error", "Please scan a game folder first.")
            return
        use_tl = self._use_tl_var.get()
        self._s5_btn.configure(state='disabled')
        self._write_log("\n── Step 5: Applying translations ──")
        _res = [None]
        def work():
            if use_tl:
                count, msg = fill_tl_thai(self._game_dir, csv_path, self._log_line)
                if count == 0:
                    self._log_line(
                        "tl/thai/ templates not available — falling back to direct replacement…")
                    _res[0] = apply_inplace(self._game_dir, csv_path,
                                            self._backup_var.get(), self._log_line)
                else:
                    _res[0] = (count, msg)
            else:
                _res[0] = apply_inplace(self._game_dir, csv_path,
                                        self._backup_var.get(), self._log_line)
        def done():
            count, msg = _res[0]
            self._s5_lbl.configure(text=msg, foreground=GREEN if count > 0 else RED)
            self._write_log(f"\n{msg}")
            self._s5_btn.configure(state='normal')
            if count > 0: messagebox.showinfo("Done", msg)
            else:         messagebox.showwarning("Warning", msg)
        self._run(work, done)

    def _do_restore(self):
        if self._busy: return
        if not self._game_dir:
            messagebox.showerror("Error", "Please scan a game folder first.")
            return
        if not messagebox.askyesno("Restore from Backup",
                "This will overwrite current .rpy files with the .bak backup copies.\n\nAre you sure?"):
            return
        self._s5_restore_btn.configure(state='disabled')
        self._write_log("\n── Restoring from backup ──")
        _count = [0]
        def work():
            _count[0] = restore_from_backup(self._game_dir, self._log_line)
        def done():
            n = _count[0]
            if n > 0:
                msg = f"Restored {n} file(s) from backup."
                self._write_log(f"\n{msg}")
                messagebox.showinfo("Done", msg)
            else:
                msg = "No .bak files found in game folder."
                self._write_log(f"\n{msg}")
                messagebox.showwarning("Warning", msg)
            self._s5_restore_btn.configure(state='normal')
        self._run(work, done)


if __name__ == '__main__':
    App().mainloop()
