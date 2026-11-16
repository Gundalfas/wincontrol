"""wincontrol - desktop computer-use CLI for AI agents (Windows). Images/state: %TEMP%\\dpx (DPX_STATE_DIR).
Benchmarked against agent-desktop, Cua Driver and Windows-MCP: cheapest, fastest, 100 % success (see README).
Screenshots + real mouse/keyboard (unicode typing), OCR text with coordinates, UI Automation element list.
Works on any window, including RDP (bitmap only). Coordinates = pixels in the LATEST snap image.

FAST LOOP (each image you look at costs ~5-15 s of thinking; text costs ~1 s):
  1. `wincontrol ocr 'Label1|Label2'` (or `elements`) to find targets - prints text + click coordinates, no image needed
  2. chain actions in ONE shell call: wincontrol clicktext 'X' && wincontrol type '...' && wincontrol key enter && wincontrol ocr 'expected'
  3. verify with `ocr <expected text>`; use `snap`/`zoom` + image viewing only when the layout itself is unclear

  wincontrol windows                      list visible top-level windows (title | size)
  wincontrol use "<title regex>"          select the target window (remembered in the state dir)
  wincontrol snap [name] [--full]         screenshot of the target window -> <name>.png (<=1200 px wide; --full = original size); prints path, size
  wincontrol zoom X1 Y1 X2 Y2 [name]      enlarged crop of a region of the latest snap (for small text);
                                   then `click X Y --zoom` uses coordinates of the zoom image
  wincontrol click X Y [--double|--right|--zoom]
  wincontrol type 'text' | --file f.txt   types unicode text (newline = Enter) into the focused control. PowerShell treats
                                   LT quotes „“ as string quotes: use 'single quotes' or --file (UTF-8). Verify: elements Edit
  wincontrol key ctrl+s | enter | tab | esc | f2 | alt+f4 ...
  wincontrol scroll X Y N                 N>0 down, N<0 up (wheel notches)
  wincontrol wait SEC
  wincontrol start excel | notepad | <file>  launch a program or open a file, wait for its new window and make it the target
  wincontrol clip                         print clipboard text (RDP shares it): exact table data, e.g. SSMS grid ctrl+a, ctrl+shift+c
The user sees the agent: a coloured agent cursor with a name tag (DPX_AGENT, auto Claude/Codex) glides to targets,
clicks pulse a red ring, typing/keys show a caption. DPX_SHOW=0 disables, DPX_GLIDE_MS=250 sets glide time.
UIA (on by default, DPX_UIA=0 disables; native apps - exact names; RDP pictures have no elements):
  wincontrol elements ['A|B']             visible named controls: x,y<TAB>role<TAB>name[ = value]; no image tokens
  wincontrol clickname 'name' [N] [--double|--right]   click the Nth control with that name (exact, else contains)
OCR edition only (on by default, DPX_OCR=0 disables):
  wincontrol ocr ['A|B']                  text lines with click coordinates (snap-image space); filter = any of A, B (case/accent-insensitive)
  wincontrol clicktext 'text' [N] [--double]   click the Nth (default 1) OCR line containing text (accent/case-insensitive)
"""
import ctypes, ctypes.wintypes as W, json, os, re, sys, time, unicodedata
from pathlib import Path
from PIL import ImageGrab, Image

ctypes.windll.shcore.SetProcessDpiAwareness(2)
U = ctypes.windll.user32
# One state (target window, last snap scale) per AI session, so parallel agents never click with each other's coordinates.
# Codex first: a Codex started from Claude Code inherits CLAUDE_CODE_SESSION_ID.
_SESSION = next((os.environ[k] for k in ('DPX_SESSION', 'CODEX_THREAD_ID', 'CLAUDE_CODE_SESSION_ID', 'PASEO_AGENT_ID') if os.environ.get(k)), '')
STATE_DIR = Path(os.environ.get('DPX_STATE_DIR') or Path(os.environ.get('TEMP', '.')) / 'dpx' / (_SESSION[:12] or 'default'))
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE = STATE_DIR / 'state.json'
MAXW = 1200
OCR_ON = os.environ.get('DPX_OCR', '1') != '0'      # default ON (cheapest in our benchmark)


def load():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}


def save(**kw):
    s = load(); s.update(kw); STATE.write_text(json.dumps(s), encoding='utf-8')


def title(h):
    n = U.GetWindowTextLengthW(h); b = ctypes.create_unicode_buffer(n + 1); U.GetWindowTextW(h, b, n + 1); return b.value


def rect(h):
    r = W.RECT(); U.GetWindowRect(h, ctypes.byref(r)); return r


def windows():
    out = []
    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        if U.IsWindowVisible(h) and U.GetWindowTextLengthW(h) > 0 and title(h) != 'dpx-cursor':
            r = rect(h)
            if (r.right - r.left > 100 and r.bottom - r.top > 60) or U.IsIconic(h):   # minimized windows count too
                out.append(h)
        return True
    U.EnumWindows(cb, 0)
    return out


def target():
    s = load()
    h = s.get('hwnd')
    if h and U.IsWindow(h):
        return h
    pat = s.get('pattern') or os.environ.get('DPX_TARGET')
    if not pat:
        raise SystemExit('No target window: run `wincontrol windows` then `wincontrol use "<title regex>"`')
    for w in windows():
        if re.search(pat, title(w), re.I):
            save(hwnd=w, pattern=pat); return w
    raise SystemExit(f'No visible window matches {pat!r}; run `wincontrol windows`')


def root(h):
    return U.GetAncestor(h, 2) or h          # GA_ROOT


def focus(h):
    """Bring the target to the front and VERIFY it - a screenshot/click on a covered window would hit another app."""
    if root(U.GetForegroundWindow()) == h:
        return
    if U.IsIconic(h):
        U.ShowWindow(h, 9)
    for attempt in range(3):
        fg = U.GetWindowThreadProcessId(U.GetForegroundWindow(), None)
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        if attempt == 1:                     # foreground lock: a synthetic ALT tap lets SetForegroundWindow through
            U.keybd_event(0x12, 0, 0, 0); U.keybd_event(0x12, 0, 2, 0)
        if attempt == 2:                     # last resort: briefly topmost
            U.SetWindowPos(h, -1, 0, 0, 0, 0, 0x3); U.SetWindowPos(h, -2, 0, 0, 0, 0, 0x3)
        U.AttachThreadInput(me, fg, True); U.BringWindowToTop(h); U.SetForegroundWindow(h); U.AttachThreadInput(me, fg, False)
        time.sleep(0.15)
        if root(U.GetForegroundWindow()) == h:
            return
    raise SystemExit(f'wincontrol: could not bring {title(h)!r} to the front (now: {title(U.GetForegroundWindow())!r}); '
                     'close/minimize the covering window or `wincontrol use` it')


class PT(ctypes.Structure):
    _fields_ = [('x', W.LONG), ('y', W.LONG)]


def owner_at(sx, sy):
    return root(U.WindowFromPoint(PT(sx, sy)))


class KI(ctypes.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('extra', ctypes.c_size_t)]
class MI(ctypes.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('extra', ctypes.c_size_t)]
class IU(ctypes.Union):
    _fields_ = [('ki', KI), ('mi', MI), ('pad', ctypes.c_byte * 32)]
class INPUT(ctypes.Structure):
    _fields_ = [('type', W.DWORD), ('u', IU)]


def send(*i):
    arr = (INPUT * len(i))(*i); U.SendInput(len(i), arr, ctypes.sizeof(INPUT))


def kev(vk=0, scan=0, flags=0):
    i = INPUT(type=1); i.u.ki = KI(vk, scan, flags, 0, 0); return i


def mev(flags, data=0):
    i = INPUT(type=0); i.u.mi = MI(0, 0, data, flags, 0, 0); return i


VK = {'enter': 0x0D, 'return': 0x0D, 'tab': 0x09, 'esc': 0x1B, 'escape': 0x1B, 'backspace': 0x08, 'delete': 0x2E,
      'del': 0x2E, 'space': 0x20, 'pageup': 0x21, 'pgup': 0x21, 'pagedown': 0x22, 'pgdn': 0x22, 'end': 0x23,
      'home': 0x24, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28, 'insert': 0x2D, 'ctrl': 0x11,
      'control': 0x11, 'shift': 0x10, 'alt': 0x12, 'win': 0x5B, 'apps': 0x5D, 'menu': 0x5D,
      **{f'f{i}': 0x6F + i for i in range(1, 13)}}
EXT = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}


SHOW = os.environ.get('DPX_SHOW', '1') != '0'      # agent cursor overlay (for the user to follow the AI)
GLIDE_MS = int(os.environ.get('DPX_GLIDE_MS', '150'))
AGENT = os.environ.get('DPX_AGENT') or ('Codex' if os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SANDBOX') or os.environ.get('CODEX_CI')
                                        else 'Claude' if os.environ.get('CLAUDECODE') or os.environ.get('CLAUDE_CODE_ENTRYPOINT') else 'AI')
COLORS = {'claude': '#D97757', 'codex': '#111111', 'gemini': '#4285F4', 'rovo': '#0C66E4'}
PORT = int(os.environ.get('DPX_CURSOR_PORT', '47811'))


def _cursor_send(msg, wait_reply=False):
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sk.settimeout(0.15)
        sk.sendto(json.dumps(msg).encode('utf-8'), ('127.0.0.1', PORT))
        if wait_reply:
            return sk.recvfrom(64)[0] == b'pong'
        return True
    except OSError:
        return False
    finally:
        sk.close()


def _cursor_ensure():
    """Start the agent-cursor daemon (one per desktop) if it is not answering."""
    if _cursor_send({'op': 'ping'}, True):
        return True
    import subprocess
    exe = sys.executable.replace('python.exe', 'pythonw.exe')
    exe = exe if os.path.exists(exe) else sys.executable
    subprocess.Popen([exe, os.path.abspath(__file__), '_cursord'], creationflags=0x00000008 | 0x08000000, close_fds=True)
    for _ in range(30):
        time.sleep(0.1)
        if _cursor_send({'op': 'ping'}, True):
            return True
    return False


def glide(x, y):
    """Move the real cursor smoothly to (x, y); the agent cursor overlay animates alongside."""
    if not SHOW or GLIDE_MS <= 0:
        U.SetCursorPos(x, y); return
    if _cursor_ensure():
        _cursor_send({'op': 'move', 'x': x, 'y': y, 'ms': GLIDE_MS, 'name': AGENT})
    p = W.POINT(); U.GetCursorPos(ctypes.byref(p))
    steps = max(1, GLIDE_MS // 15)
    for i in range(1, steps + 1):
        t = i / steps; t = t * t * (3 - 2 * t)                     # ease in/out
        U.SetCursorPos(int(p.x + (x - p.x) * t), int(p.y + (y - p.y) * t)); time.sleep(GLIDE_MS / 1000 / steps)
    U.SetCursorPos(x, y)


def show(kind, x, y, text=''):
    """Agent cursor feedback: 'click' = pulse ring at the tip, 'text' = caption under the name tag."""
    if not SHOW or not _cursor_ensure():
        return
    if kind == 'click':
        _cursor_send({'op': 'click', 'x': x, 'y': y, 'name': AGENT})
    else:
        _cursor_send({'op': 'say', 'x': x, 'y': y, 'text': text[:60], 'name': AGENT})


def cursor_daemon():
    """One topmost, click-through, non-activating window: coloured arrow + name tag + click ring + caption.
    Listens on UDP 127.0.0.1:PORT; exits after DPX_CURSOR_IDLE seconds (default 120) without messages."""
    import socket, tkinter as tk
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sk.bind(('127.0.0.1', PORT))
    except OSError:
        return                                                     # another daemon already owns the port
    sk.setblocking(False)
    idle_limit = float(os.environ.get('DPX_CURSOR_IDLE', '120'))
    W_, H_, TIP = 420, 130, 40                                     # window size; arrow tip at (TIP, TIP)
    root = tk.Tk(); root.withdraw(); root.overrideredirect(True); root.title('dpx-cursor')   # title: hidden from `windows`
    root.attributes('-topmost', True); root.config(bg='magenta'); root.attributes('-transparentcolor', 'magenta')
    c = tk.Canvas(root, width=W_, height=H_, bg='magenta', highlightthickness=0); c.pack()
    st = {'x': 0, 'y': 0, 'anim': None, 'last': time.time(), 'shown': False, 'name': AGENT, 'cap_until': 0, 'ring': 0}

    def color():
        return COLORS.get(st['name'].lower(), '#7B2FF7')

    def draw():
        c.delete('all'); col = color(); t = TIP
        if st['ring'] > 0:                                         # click pulse
            r = 10 + (1 - st['ring']) * 22
            c.create_oval(t - r, t - r, t + r, t + r, outline='#ff2020', width=4)
        arrow = [t, t, t, t + 26, t + 7, t + 20, t + 12, t + 31, t + 17, t + 29, t + 12, t + 18, t + 21, t + 18]
        c.create_polygon(arrow, fill=col, outline='white', width=2)
        tag = st['name']; tx, ty = t + 22, t + 26
        tw = 9 * len(tag) + 18
        c.create_rectangle(tx, ty, tx + tw, ty + 22, fill=col, outline='white', width=1)
        c.create_text(tx + tw / 2, ty + 11, text=tag, fill='white', font=('Segoe UI', 10, 'bold'))
        if time.time() < st['cap_until']:
            c.create_rectangle(tx, ty + 26, tx + min(W_ - tx - 4, 9 * len(st['cap']) + 20), ty + 50, fill='#202020', outline='')
            c.create_text(tx + 8, ty + 38, text=st['cap'], fill='#ffd400', anchor='w', font=('Segoe UI', 11, 'bold'))

    def place(x, y):
        st['x'], st['y'] = x, y
        root.geometry(f'{W_}x{H_}+{int(x) - TIP}+{int(y) - TIP}')

    def ensure_shown():
        if st['shown']:
            return
        root.update_idletasks()
        hwnd = U.GetParent(root.winfo_id()) or root.winfo_id()
        ex = U.GetWindowLongW(hwnd, -20)
        U.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x08000000 | 0x80)   # layered, click-through, no-activate, toolwindow
        U.ShowWindow(hwnd, 4); U.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        st['hwnd'] = hwnd; st['shown'] = True

    def animate(x0, y0, x1, y1, ms, t0):
        k = min(1.0, (time.time() - t0) * 1000 / max(1, ms)); e = k * k * (3 - 2 * k)
        place(x0 + (x1 - x0) * e, y0 + (y1 - y0) * e)
        if k < 1:
            st['anim'] = root.after(15, animate, x0, y0, x1, y1, ms, t0)

    def pulse(v):
        st['ring'] = v; draw()
        if v > 0:
            root.after(30, pulse, round(v - 0.06, 2))

    def tick():
        try:
            while True:
                data, addr = sk.recvfrom(4096)
                m = json.loads(data.decode('utf-8')); st['last'] = time.time()
                if m.get('name'):
                    st['name'] = m['name']
                op = m.get('op')
                if op == 'ping':
                    sk.sendto(b'pong', addr); continue
                if op == 'quit':
                    root.destroy(); return
                if op in ('hide', 'unhide'):                       # keep the overlay out of screenshots / OCR
                    if st['shown']:
                        U.ShowWindow(st['hwnd'], 0 if op == 'hide' else 4); root.update()
                    sk.sendto(b'pong', addr); continue
                if not st['shown']:
                    place(m.get('x', 0), m.get('y', 0)); ensure_shown()
                if op == 'move':
                    if st['anim']:
                        root.after_cancel(st['anim'])
                    animate(st['x'], st['y'], m['x'], m['y'], m.get('ms', 250), time.time())
                elif op == 'click':
                    place(m['x'], m['y']); pulse(1.0)
                elif op == 'say':
                    st['cap'] = m.get('text', ''); st['cap_until'] = time.time() + 1.6; draw()
                    root.after(1700, draw)
                if st['shown']:
                    U.SetWindowPos(st['hwnd'], -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # stay above newly opened windows
        except BlockingIOError:
            pass
        except OSError:
            pass
        if time.time() - st['last'] > idle_limit:
            root.destroy(); return
        root.after(10, tick)

    draw(); root.after(10, tick); root.mainloop()


def cursor_xy():
    p = W.POINT(); U.GetCursorPos(ctypes.byref(p)); return p.x, p.y


def grab(h):
    r = rect(h)
    hidden = SHOW and _cursor_send({'op': 'hide'}, True)
    try:
        return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True), r
    finally:
        if hidden:
            _cursor_send({'op': 'unhide'})


def to_screen(x, y, zoom=False):
    s = load()
    if 'left' not in s:
        sys.exit('wincontrol: no coordinates yet - run `wincontrol snap`, `ocr` or `elements` first')
    if zoom:
        z = s['zoom']; x, y = z['x1'] + x / z['f'], z['y1'] + y / z['f']
    return int(s['left'] + x / s['scale']), int(s['top'] + y / s['scale'])


def fold(t):
    return ''.join(c for c in unicodedata.normalize('NFKD', t.lower()) if not unicodedata.combining(c))


TESS = os.environ.get('DPX_TESSERACT') or os.path.expandvars(r'%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe')
if not os.path.exists(TESS):
    TESS = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def _win_ocr(big, up, scale):
    """Windows OCR (en-US only: good at short English/ASCII labels, garbles Lithuanian letters)."""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import DataWriter
    rgba = big.convert('RGBA')
    w = DataWriter(); w.write_bytes(bytearray(rgba.tobytes('raw', 'BGRA')))
    sb = SoftwareBitmap.create_copy_from_buffer(w.detach_buffer(), BitmapPixelFormat.BGRA8, rgba.width, rgba.height,
                                                BitmapAlphaMode.PREMULTIPLIED)
    res = asyncio.run(_rec(OcrEngine.try_create_from_user_profile_languages(), sb))
    out = []
    for ln in res.lines:
        groups, prev = [], None          # Windows joins far-apart labels (menu bar) into one line -> split on wide gaps
        for b in ln.words:
            r_ = b.bounding_rect
            if prev is None or r_.x - prev > max(r_.height * 0.6, 6 * up):
                groups.append([])
            groups[-1].append((b.text, r_)); prev = r_.x + r_.width
        for g in groups:
            x1 = min(r_.x for _, r_ in g); y1 = min(r_.y for _, r_ in g)
            x2 = max(r_.x + r_.width for _, r_ in g); y2 = max(r_.y + r_.height for _, r_ in g)
            out.append((' '.join(t for t, _ in g), int((x1 + x2) / 2 / up * scale), int((y1 + y2) / 2 / up * scale)))
    return out


def _tess_ocr(big, up, scale):
    """Tesseract lit+eng (correct Lithuanian letters). Words grouped into lines by block/par/line."""
    import subprocess, tempfile
    if not os.path.exists(TESS):
        return []
    p = os.path.join(tempfile.gettempdir(), f'dpx-ocr-{os.getpid()}.bmp'); big.convert('L').save(p)   # bmp: no compression cost
    langs = os.environ.get('DPX_OCR_LANGS', 'lit+eng')
    td = os.environ.get('DPX_TESSDATA')                       # e.g. a tessdata_best folder
    tsv = subprocess.run([TESS, p, 'stdout', '-l', langs, '--psm', '11'] + (['--tessdata-dir', td] if td else []) + ['tsv'],
                         capture_output=True, text=True,
                         encoding='utf-8', errors='replace', creationflags=0x08000000).stdout
    lines = {}
    for row in tsv.splitlines()[1:]:
        f = row.split('\t')
        if len(f) < 12 or not f[11].strip() or float(f[10]) < 30:
            continue
        key = (f[2], f[3], f[4])
        x, y, w_, h_ = map(int, f[6:10])
        lines.setdefault(key, []).append((x, y, x + w_, y + h_, f[11]))
    out = []
    for ws in lines.values():
        ws.sort()
        x1 = min(w[0] for w in ws); y1 = min(w[1] for w in ws); x2 = max(w[2] for w in ws); y2 = max(w[3] for w in ws)
        out.append((' '.join(w[4] for w in ws), int((x1 + x2) / 2 / up * scale), int((y1 + y2) / 2 / up * scale)))
    return out


def ocr_lines(h, need=None):
    """Tesseract (Lithuanian) + Windows OCR in parallel; a Windows line is added only where Tesseract found nothing.
    need = folded texts the caller looks for: if fast Windows OCR (~0.3 s) already finds all of them, Tesseract (~2-4 s) is skipped."""
    from concurrent.futures import ThreadPoolExecutor
    img, r = grab(h)
    # OCR reads small UI text better when upscaled; 1.5x on big windows keeps quality at ~30 % less time (RDP 1936 px: 2.2 -> 1.6 s)
    up = 2 if img.width < 1200 else 1.5 if img.width < 2400 else 1
    # BICUBIC, not BILINEAR: bilinear blurs a Tk focus ring (dotted box) into the label and both engines lose the text
    big = img.resize((int(img.width * up), int(img.height * up)), Image.BICUBIC) if up != 1 else img
    scale = min(1.0, MAXW / img.width)
    save(left=r.left, top=r.top, scale=scale)
    if need and os.environ.get('DPX_OCR_FAST', '1') != '0':
        win = _win_ocr(big, up, scale)
        if all(any(n in fold(t) for t, _, _ in win) for n in need):
            return sorted(win, key=lambda z: (z[2] // 6, z[1]))
    with ThreadPoolExecutor(2) as ex:
        ft = ex.submit(_tess_ocr, big, up, scale); fw = ex.submit(_win_ocr, big, up, scale)
        tess, win = ft.result(), fw.result()
    out = list(tess)
    norm = lambda t: re.sub(r'\W', '', fold(t))
    for t, x, y in win:
        wt = norm(t)
        dup = any(abs(y - ty) < 8 and (abs(x - tx) < max(40, len(t) * 4) or (wt[:5] and wt[:5] in norm(tt)))
                  for tt, tx, ty in tess)
        if not dup:
            out.append((t, x, y))
    out.sort(key=lambda z: (z[2] // 6, z[1]))
    return out


UIA_ON = os.environ.get('DPX_UIA', '1') != '0'      # default ON (exact names in native apps)
ROLES = {'ButtonControl', 'EditControl', 'MenuItemControl', 'ListItemControl', 'TreeItemControl', 'TabItemControl',
         'ComboBoxControl', 'CheckBoxControl', 'RadioButtonControl', 'HyperlinkControl', 'DataItemControl',
         'SplitButtonControl', 'MenuBarControl', 'DocumentControl', 'TextControl', 'HeaderItemControl', 'CustomControl'}


def uia_elements(h, max_depth=25, limit=4000):
    """Visible named UI Automation elements of the window: (x, y in snap space, role, name, value)."""
    import uiautomation as auto
    root = auto.ControlFromHandle(h)
    r = rect(h); s = load(); scale = s.get('scale') or min(1.0, MAXW / max(1, r.right - r.left))
    if 'left' not in s:
        save(left=r.left, top=r.top, scale=scale)
    out, seen = [], 0
    for c, d in auto.WalkControl(root, includeTop=False, maxDepth=max_depth):
        seen += 1
        if seen > limit:
            break
        try:
            if c.ControlTypeName not in ROLES or c.IsOffscreen:
                continue
            name = (c.Name or '').strip()
            val = ''
            if c.ControlTypeName in ('EditControl', 'ComboBoxControl', 'DataItemControl'):
                try:
                    val = (c.GetValuePattern().Value or '')[:80]
                except Exception:
                    pass
            if not name and not val:
                continue
            b = c.BoundingRectangle
            if b.width() <= 0 or b.height() <= 0:
                continue
            x = ((b.left + b.right) / 2 - r.left) * scale; y = ((b.top + b.bottom) / 2 - r.top) * scale
            if 0 <= x <= (r.right - r.left) * scale and 0 <= y <= (r.bottom - r.top) * scale:
                out.append((int(x), int(y), c.ControlTypeName.replace('Control', ''), name[:80], val))
        except Exception:
            continue
    return out


async def _rec(engine, sb):
    return await engine.recognize_async(sb)


def pid_of(w):
    p = W.DWORD(); U.GetWindowThreadProcessId(w, ctypes.byref(p)); return p.value


def blocking_dialog(h):
    """The window that blocks a disabled target: its owned popup, else an enabled visible window of the same process."""
    pop = U.GetLastActivePopup(h)
    if pop and pop != h and U.IsWindowVisible(pop):
        return pop
    same = [w for w in windows() if w != h and pid_of(w) == pid_of(h) and U.IsWindowEnabled(w)]
    fg = root(U.GetForegroundWindow())
    return fg if fg in same else (same[0] if same else 0)


def note_front(h):
    """After an action: tell the agent when a dialog / another window took the front (e.g. an unexpected popup)."""
    if not U.IsWindow(h):                    # the action closed the target (Esc / Alt+F4 / Save) - nothing to report
        return
    fg = root(U.GetForegroundWindow())
    if not U.IsWindowEnabled(h):
        dlg = blocking_dialog(h)
        print(f'NOTE: dialog {title(dlg)!r} is open and blocks {title(h)!r} - handle it first (wincontrol use "{title(dlg)}")')
    elif fg and fg != h and title(fg) != 'dpx-cursor':
        print(f'NOTE: window {title(fg)!r} is now in front (not the target)')


def press_at(sx, sy, flags):
    """Glide to the screen point, show a red ring, then click (left / --right / --double).
    Refuses when another program's window covers the point (its own menus/popups are fine: same process)."""
    h = target()
    if not U.IsWindowEnabled(h):                     # a modal dialog of this app blocks input -> the click would be lost
        dlg = blocking_dialog(h)
        raise SystemExit(f'wincontrol: {title(h)!r} is blocked by the dialog {title(dlg)!r} - handle that dialog first '
                         f'(wincontrol use "{title(dlg)}", then ocr/elements); nothing was clicked')
    o = owner_at(sx, sy)
    pid = lambda w: (lambda p: (U.GetWindowThreadProcessId(w, ctypes.byref(p)), p.value)[1])(W.DWORD())
    if o and o != h and title(o) != 'dpx-cursor' and pid(o) != pid(h):
        raise SystemExit(f'wincontrol: point {sx},{sy} is covered by another window {title(o)!r} - not clicking; '
                         'take a new snap (the window may have moved) or close the covering window')
    glide(sx, sy); show('click', sx, sy); time.sleep(0.05)
    down, up = (0x8, 0x10) if '--right' in flags else (0x2, 0x4)
    for _ in range(2 if '--double' in flags else 1):
        send(mev(down), mev(up)); time.sleep(0.06)
    time.sleep(float(os.environ.get('DPX_SETTLE', '0.2')))      # let the app react before the next command
    note_front(h)


_LOCK = None


def input_lock(timeout=60):
    """One mouse/keyboard for everyone: input commands from parallel agents run one at a time (released at process exit)."""
    global _LOCK
    import msvcrt
    _LOCK = open(Path(os.environ.get('TEMP', '.')) / 'dpx-input.lock', 'a+')
    end = time.time() + timeout
    while True:
        try:
            _LOCK.seek(0); msvcrt.locking(_LOCK.fileno(), msvcrt.LK_NBLCK, 1); return
        except OSError:
            if time.time() > end:
                raise SystemExit('wincontrol: another agent is using the mouse/keyboard (lock busy 60 s)')
            time.sleep(0.05)


def main(argv):
    if argv and argv[0] == '_cursord':
        cursor_daemon(); return
    if not argv or argv[0] in ('-h', '--help', 'help'):
        head, rest = __doc__.split('UIA (')
        uia, ocr = rest.split('OCR edition only')
        print(head + ('UIA (' + uia if UIA_ON else '') + ('OCR edition only' + ocr if OCR_ON else '')); return
    cmd, *a = argv
    flags = {x for x in a if x.startswith('--')}; a = [x for x in a if not x.startswith('--')]
    if cmd in ('click', 'clicktext', 'clickname', 'type', 'key', 'scroll', 'drag'):
        input_lock()
    if cmd == 'clip':
        k = ctypes.windll.kernel32; k.GlobalLock.restype = ctypes.c_void_p; k.GlobalLock.argtypes = [ctypes.c_void_p]
        U.GetClipboardData.restype = ctypes.c_void_p
        for _ in range(10):                      # another process may hold the clipboard for a moment
            if U.OpenClipboard(None):
                break
            time.sleep(0.1)
        else:
            raise SystemExit('clipboard busy')
        try:
            hd = U.GetClipboardData(13)          # CF_UNICODETEXT
            txt = ctypes.wstring_at(k.GlobalLock(hd)) if hd else ''
            if hd:
                k.GlobalUnlock(ctypes.c_void_p(hd))
        finally:
            U.CloseClipboard()
        sys.stdout.write(txt.replace('\r\n', '\n') + ('' if txt.endswith(('\n', '\r\n')) else '\n')); return
    if cmd == 'windows':
        for w in windows():
            r = rect(w); print(f'{title(w)[:90]} | ' + ('minimized' if U.IsIconic(w) else f'{r.right - r.left}x{r.bottom - r.top}'))
        return
    if cmd == 'use':
        STATE.write_text('{}', encoding='utf-8'); save(pattern=a[0]); h = target()
        n = sum(1 for w in windows() if re.search(a[0], title(w), re.I))
        print('target:', title(h) + (f'  (WARNING: {n} windows match - using the frontmost; make the regex more specific)' if n > 1 else ''))
        return
    if cmd == 'start':                         # launch a program / open a file, wait for its NEW window and target it
        import subprocess
        before = set(windows())
        subprocess.Popen(['cmd', '/c', 'start', '', *a], creationflags=0x08000000)
        end = time.time() + float(os.environ.get('DPX_START_WAIT', '30'))
        while time.time() < end:
            new = [w for w in windows() if w not in before and title(w) != 'dpx-cursor']
            if new:
                time.sleep(1.0); new = [w for w in windows() if w not in before and title(w) != 'dpx-cursor'] or new
                w = new[0]; STATE.write_text('{}', encoding='utf-8'); save(hwnd=w, pattern=re.escape(title(w)))
                print('started; target:', title(w), '' if len(new) == 1 else f'(other new windows: {[title(x) for x in new[1:]]})'); return
            time.sleep(0.5)
        raise SystemExit(f'wincontrol: started {a[0]!r} but no new window appeared in time; run `wincontrol windows`')
    if cmd == 'wait':
        time.sleep(float(a[0])); print('ok'); return
    h = target()
    if cmd == 'snap':
        focus(h); img, r = grab(h)
        scale = 1.0 if '--full' in flags else min(1.0, MAXW / img.width)    # --full: original pixels (mockups)
        if scale < 1:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        save(left=r.left, top=r.top, scale=scale, snap_size=[img.width, img.height])
        p = (STATE_DIR / ((a[0] if a else 'snap') + '.png')) if not (a and ('/' in a[0] or '\\' in a[0])) else Path(a[0] + '.png'); img.save(p); save(last_snap=str(p))
        print(f'{p} {img.width}x{img.height}')
    elif cmd == 'zoom':
        x1, y1, x2, y2 = map(float, a[:4]); s = load()
        full, r = grab(h); sc = s['scale']
        crop = full.crop((int(x1 / sc), int(y1 / sc), int(x2 / sc), int(y2 / sc)))
        f = min(1200 / max(1, crop.width), 900 / max(1, crop.height), 4.0)   # zoom px per snap px (relative to full res)
        out = crop.resize((int(crop.width * f), int(crop.height * f)), Image.LANCZOS)
        fs = out.width / max(1e-6, (x2 - x1)); save(zoom={'x1': x1, 'y1': y1, 'f': fs})
        p = STATE_DIR / ((a[4] if len(a) > 4 else 'zoom') + '.png'); out.save(p)
        print(f'{p} {out.width}x{out.height} (use click X Y --zoom with these coordinates)')
    elif cmd == 'click':
        focus(h); x, y = to_screen(float(a[0]), float(a[1]), '--zoom' in flags)
        press_at(x, y, flags); print('ok')
    elif cmd == 'type':
        # --file: text from a UTF-8 file (no shell quoting: PowerShell treats „ “ ” as string quotes and breaks the text)
        text = Path(a[0]).read_text(encoding='utf-8-sig').replace('\r\n', '\n').rstrip('\n') if '--file' in flags else ' '.join(a)
        focus(h); show('text', *cursor_xy(), '⌨ ' + text[:60])
        for ch in text:
            if ch == '\n':
                send(kev(0x0D), kev(0x0D, 0, 2))
            else:
                send(kev(0, ord(ch), 4), kev(0, ord(ch), 6))
            time.sleep(0.012)
        print('ok'); note_front(h)
    elif cmd == 'key':
        focus(h); keys = [k.lower() for k in a[0].split('+')]; show('text', *cursor_xy(), '⌨ ' + a[0])
        bad = [k for k in keys if k not in VK and len(k) != 1]
        if bad:
            raise SystemExit(f'Unknown key {bad}; valid: single characters or ' + ', '.join(sorted(VK)))
        codes = [VK[k] if k in VK else (U.VkKeyScanW(ord(k)) & 0xFF) for k in keys]
        send(*[kev(c, 0, 1 if c in EXT else 0) for c in codes])
        send(*[kev(c, 0, (1 if c in EXT else 0) | 2) for c in reversed(codes)]); time.sleep(float(os.environ.get('DPX_SETTLE', '0.2'))); print('ok'); note_front(h)
    elif cmd == 'scroll':
        focus(h); x, y = to_screen(float(a[0]), float(a[1])); glide(x, y); show('text', x, y, ('↓ ' if int(a[2]) > 0 else '↑ ') + str(abs(int(a[2]))))
        send(mev(0x800, ctypes.c_uint32(-120 * int(a[2])).value)); time.sleep(0.4); print('ok')
    elif cmd in ('elements', 'clickname') and UIA_ON:
        focus(h)
        els = uia_elements(h)
        if cmd == 'elements':
            filt = [f for f in fold(a[0]).split('|') if f] if a else None     # 'A|B' like ocr
            shown = [e for e in els if not filt or any(f in fold(e[3] + ' ' + e[2]) for f in filt)]
            for x, y, role, name, val in shown[:300]:
                print(f'{x},{y}\t{role}\t{name}' + (f'\t= {val}' if val else ''))
            if len(shown) > 300:
                print(f'... {len(shown) - 300} more; add a filter')
        else:
            want = fold(a[0]); n = int(a[1]) if len(a) > 1 else 1
            hits = [e for e in els if fold(e[3]) == want] or [e for e in els if want in fold(e[3])]
            hits.sort(key=lambda e: e[2] in ('TextControl', 'Text'))     # a control beats its own label with the same name
            if len(hits) < n:
                raise SystemExit(f'no element named like {a[0]!r} ({len(hits)} hits); try `wincontrol elements <part>`')
            x, y, role, name, _ = hits[n - 1]; press_at(*to_screen(x, y), flags); print(f'clicked {role} {name!r} at {x},{y} ({len(hits)} hits)')
    elif cmd == 'ocr' and OCR_ON:
        focus(h)
        filt = [f for f in fold(a[0]).split('|') if f] if a else None     # 'A|B' = lines with A or B
        for t, x, y in ocr_lines(h, filt):
            if not filt or any(f in fold(t) for f in filt):
                print(f'{x},{y}\t{t}')
    elif cmd == 'clicktext' and OCR_ON:
        focus(h)
        want = fold(a[0]); n = int(a[1]) if len(a) > 1 else 1
        lines = ocr_lines(h, [want])
        hits = [(t, x, y) for t, x, y in lines if want in fold(t)]
        if len(hits) < n:   # the fast path may miss a 2nd/3rd hit -> full OCR
            lines = ocr_lines(h); hits = [(t, x, y) for t, x, y in lines if want in fold(t)]
        if not hits:   # OCR is English-only: Lithuanian letters come out garbled -> fuzzy match
            from difflib import SequenceMatcher
            def score(t):
                f = fold(t); k = len(want)
                return max((SequenceMatcher(None, want, f[i:i + k]).ratio() for i in range(max(1, len(f) - k + 1))), default=0)
            # 0.8: 0.7 let 'Mėlynas' match 'Geltonas' (D18) - a wrong click is worse than "not found"
            hits = [h_ for s_, h_ in sorted(((score(t), (t, x, y)) for t, x, y in lines), key=lambda z: -z[0]) if s_ >= 0.8]
        if len(hits) < n:
            raise SystemExit(f'text not found by OCR ({len(hits)} hits); try `wincontrol ocr` or a shorter text')
        t, x, y = hits[n - 1]; press_at(*to_screen(x, y), flags); print(f'clicked {t!r} at {x},{y} ({len(hits)} hits)')
    else:
        raise SystemExit('Unknown command. ' + __doc__)


if __name__ == '__main__':
    _t0 = time.time()
    try:
        main(sys.argv[1:])
    finally:
        if os.environ.get('DPX_TRACE') and sys.argv[1:2] != ['_cursord']:   # timing log: start, seconds, command
            with open(os.environ['DPX_TRACE'], 'a', encoding='utf-8') as f:
                f.write(f'{_t0:.2f}\t{time.time() - _t0:.2f}\t{" ".join(sys.argv[1:])[:80]}\n')
