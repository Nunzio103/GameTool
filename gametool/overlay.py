"""Transparent overlay with crosshair and text, always on top and click-through.

A transparent LAYERED window (via
UpdateLayeredWindow) covers the chosen monitor and draws a crosshair and text
over the game. It injects nothing into other processes: it's just a window
that stays on top and lets clicks through (WS_EX_TRANSPARENT).

Rendering is done with PIL; the window is updated with
UpdateLayeredWindow whenever something changes or when a placeholder
({time}, {timesec}, {date}) needs a refresh.
"""
import ctypes
import functools
import json
import threading
from ctypes import wintypes as wt
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

from PIL import Image, ImageDraw, ImageFont

from . import winapi
from .paths import DATA_DIR

USER32 = ctypes.WinDLL("user32", use_last_error=True)
GDI32 = ctypes.WinDLL("gdi32", use_last_error=True)

# --- window constants ---------------------------------------------------------
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_COMPOSITED = 0x02000000

ULW_ALPHA = 2
ULW_OPAQUE = 1

COLORREF = wt.DWORD

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1

# hotkeys
WM_HOTKEY = 0x0312
MOD_ALT = 1
MOD_CONTROL = 2
MOD_SHIFT = 4
MOD_NOREPEAT = 0x4000

# crosshair styles (the index is saved in the settings: don't change the order)
STYLES = [
    "Cross",
    "Cross with dot",
    "Dot",
    "Circle",
    "Circle with dot",
    "Circle with cross",
    "T cross",
    "Diagonal cross (X)",
    "Chevron",
    "PNG image",
]
STYLE_IMAGE = len(STYLES) - 1

ANCHORS = [
    "Top left", "Top center", "Top right",
    "Middle left", "Screen center", "Middle right",
    "Bottom left", "Bottom center", "Bottom right",
    "Next to the crosshair",
]
ANCHOR_CROSSHAIR = len(ANCHORS) - 1


# --- structures ------------------------------------------------------------------
class _POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]


class _BLENDFUNCTION(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND),
        ("message", wt.UINT),
        ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM),
        ("time", wt.DWORD),
        ("pt", _POINT),
    ]


USER32.UpdateLayeredWindow.argtypes = [
    wt.HWND, wt.HDC, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
    wt.HDC, ctypes.POINTER(_POINT), COLORREF, ctypes.POINTER(_BLENDFUNCTION), wt.UINT,
]
USER32.UpdateLayeredWindow.restype = wt.BOOL
USER32.GetDC.argtypes = [wt.HWND]
USER32.GetDC.restype = wt.HDC
USER32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
USER32.ReleaseDC.restype = ctypes.c_int
GDI32.CreateCompatibleDC.argtypes = [wt.HDC]
GDI32.CreateCompatibleDC.restype = wt.HDC
GDI32.DeleteDC.argtypes = [wt.HDC]
GDI32.DeleteDC.restype = wt.BOOL
GDI32.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
GDI32.SelectObject.restype = wt.HANDLE
GDI32.DeleteObject.argtypes = [wt.HANDLE]
GDI32.DeleteObject.restype = wt.BOOL
GDI32.CreateDIBSection.argtypes = [
    wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
    wt.HANDLE, wt.DWORD,
]
GDI32.CreateDIBSection.restype = wt.HBITMAP
USER32.SetWindowPos.argtypes = [
    wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT,
]
USER32.SetWindowPos.restype = wt.BOOL
USER32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
USER32.RegisterHotKey.restype = wt.BOOL
USER32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
USER32.UnregisterHotKey.restype = wt.BOOL


# --- colors ---------------------------------------------------------------------
def argb(r, g, b, a=255):
    """(r,g,b,a) 0-255 -> ARGB int 0xAABBGGRR (as in .NET)."""
    return ((a & 0xFF) << 24) | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def argb_to_rgba(c):
    a = (c >> 24) & 0xFF
    r = (c >> 16) & 0xFF
    g = (c >> 8) & 0xFF
    b = c & 0xFF
    return (r, g, b, a)


def color_from_hex(hexstr, opacity=100):
    """'#rrggbb' + opacity % -> ARGB int."""
    hexstr = (hexstr or "").lstrip("#")
    if len(hexstr) != 6:
        hexstr = "00FF00"
    r = int(hexstr[0:2], 16)
    g = int(hexstr[2:4], 16)
    b = int(hexstr[4:6], 16)
    a = max(0, min(255, round(opacity / 100.0 * 255)))
    return argb(r, g, b, a)


def _argb_to_hex(c):
    """ARGB int -> '#rrggbb'."""
    r = (c >> 16) & 0xFF
    g = (c >> 8) & 0xFF
    b = c & 0xFF
    return f"#{r:02X}{g:02X}{b:02X}"


def _argb_alpha_pct(c):
    """ARGB int -> opacity as a percentage (0-100)."""
    return round(((c >> 24) & 0xFF) / 255.0 * 100)


def hotkey_name(value):
    """Int .NET Keys -> readable label (e.g. 'F8', 'Ctrl + A', 'None')."""
    if not value:
        return "None"
    parts = []
    # .NET System.Windows.Forms.Keys modifier flags (official MS values):
    #   Shift = 0x10000, Control = 0x20000, Alt = 0x40000, KeyCode = 0xFFFF
    if (value & 0x20000):
        parts.append("Ctrl")
    if (value & 0x10000):
        parts.append("Shift")
    if (value & 0x40000):
        parts.append("Alt")
    code = value & 0xFFFF  # Keys.KeyCode: the key code only
    if 0x30 <= code <= 0x39:      # D0..D9
        parts.append(chr(ord("0") + (code - 0x30)))
    elif 0x41 <= code <= 0x5A:    # A..Z
        parts.append(chr(code))
    elif 0x70 <= code <= 0x87:    # F1..F24
        parts.append("F" + str(code - 0x6F))
    elif code in _SPECIAL_KEYS:
        parts.append(_SPECIAL_KEYS[code])
    else:
        parts.append(_VK_TO_NAME.get(code, f"VK_{code:X}"))
    return " + ".join(parts)


from .keys import _VK_TO_NAME  # noqa: E402

# special .NET Keys codes (key & Keys.KeyCode == VK value)
_SPECIAL_KEYS = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x1B: "Esc",
    0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete", 0x5D: "Menu",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "Shift", 0xA1: "Shift", 0xA2: "Ctrl", 0xA3: "Ctrl",
    0xA4: "Alt", 0xA5: "Alt", 0x5B: "Win", 0x5C: "Win",
}


# --- settings ---------------------------------------------------------------
@dataclass
class CrosshairSettings:
    visible: bool = True
    style: int = 1            # Cross with dot
    color: int = argb(0, 255, 0)
    size: int = 8
    thickness: int = 2
    gap: int = 3
    dot_size: int = 2
    outline: bool = True
    outline_color: int = argb(0, 0, 0)
    outline_width: int = 1
    image_path: str = ""
    scale: int = 100
    offset_x: int = 0
    offset_y: int = 0


@dataclass
class TextItem:
    visible: bool = True
    text: str = "New text"
    font_name: str = "Segoe UI"
    font_size: int = 28
    bold: bool = True
    italic: bool = False
    color: int = argb(255, 255, 255)
    outline: bool = True
    outline_color: int = argb(0, 0, 0)
    outline_width: int = 2
    background: bool = False
    background_color: int = argb(0, 0, 0, 128)
    anchor: int = 1           # Top center
    offset_x: int = 0
    offset_y: int = 40

    def short(self):
        s = (self.text or "").replace("\r", "")
        nl = s.find("\n")
        if nl >= 0:
            s = s[:nl] + " …"
        return s if s.strip() else "(empty)"


@dataclass
class OverlaySettings:
    crosshair: CrosshairSettings = field(default_factory=CrosshairSettings)
    texts: List[TextItem] = field(default_factory=list)  # no text until the user creates one
    texts_visible: bool = True
    monitor: int = 0
    hotkey_all: int = 0x77      # F8
    hotkey_crosshair: int = 0
    hotkey_texts: int = 0x78    # F9
    start_minimized: bool = False


SETTINGS_FILE = DATA_DIR / "overlay.json"


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return OverlaySettings()
    s = OverlaySettings()
    try:
        ch = data.get("crosshair", {})
        s.crosshair = CrosshairSettings(**{k: ch[k] for k in CrosshairSettings.__dataclass_fields__ if k in ch})
        s.texts = [TextItem(**{k: t[k] for k in TextItem.__dataclass_fields__ if k in t})
                   for t in data.get("texts", [])]
        s.texts_visible = bool(data.get("texts_visible", True))
        s.monitor = int(data.get("monitor", 0))
        s.hotkey_all = int(data.get("hotkey_all", s.hotkey_all))
        s.hotkey_crosshair = int(data.get("hotkey_crosshair", 0))
        s.hotkey_texts = int(data.get("hotkey_texts", s.hotkey_texts))
        s.start_minimized = bool(data.get("start_minimized", False))
    except (TypeError, ValueError, KeyError):
        return OverlaySettings()
    return s


def save_settings(s):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


# --- rendering ------------------------------------------------------------------
def expand_placeholders(text, now=None):
    import datetime as _dt
    now = now or _dt.datetime.now()
    seconds, minutes, date = now.strftime("%H:%M:%S"), now.strftime("%H:%M"), now.strftime("%d/%m/%Y")
    text = text or ""
    for old, new in (("{timesec}", seconds), ("{orasec}", seconds), ("{time}", minutes),
                     ("{ora}", minutes), ("{date}", date), ("{data}", date)):
        text = text.replace(old, new)
    return text


@functools.lru_cache(maxsize=64)
def _load_font(font_name, size, bold, italic):
    size = max(6, int(size))
    candidates = []
    name = font_name or "Segoe UI"
    suffix = "Bold" if bold else "Regular"
    candidates.append(f"{name} {suffix}.ttf")
    if italic:
        candidates.append(f"{name} Italic.ttf")
    candidates.append(f"{name}.ttf")
    candidates.append("segoeui.ttf")
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_crosshair(draw, cx, cy, c, scale=1.0, outline=True):
    """Draws the crosshair at the center (cx, cy). scale is for the enlarged preview."""
    t = max(1, c.thickness)
    length = max(0, c.size)
    gap = max(0, c.gap)
    color = argb_to_rgba(c.color)
    ocolor = argb_to_rgba(c.outline_color)

    def stroke(fn, *a, **k):
        if outline and c.outline_width > 0:
            fn(*a, outline=ocolor, width=int(t + 2 * c.outline_width), **k)
        fn(*a, outline=color, width=int(t), **k)

    s = c.style
    if s == STYLE_IMAGE:
        if _draw_image_crosshair(draw, cx, cy, c, scale):
            return
        s = 1  # missing or unreadable image: cross with dot, never an invisible crosshair

    def line(x1, y1, x2, y2):
        if outline and c.outline_width > 0:
            draw.line((x1, y1, x2, y2), fill=ocolor, width=int(t + 2 * c.outline_width))
        draw.line((x1, y1, x2, y2), fill=color, width=int(t))

    def ellipse(x0, y0, x1, y1):
        stroke(draw.ellipse, (x0, y0, x1, y1))

    def rect(x0, y0, x1, y1):
        if outline and c.outline_width > 0:
            draw.rectangle((x0 - c.outline_width, y0 - c.outline_width,
                            x1 + c.outline_width, y1 + c.outline_width), fill=ocolor)
        draw.rectangle((x0, y0, x1, y1), fill=color)

    dot = False
    arms = False
    circle = False
    diag = False
    chevron = False
    top = True
    if s == 0:
        arms = True
    elif s == 1:
        arms = dot = True
    elif s == 2:
        dot = True
    elif s == 3:
        circle = True
    elif s == 4:
        circle = dot = True
    elif s == 5:
        circle = arms = True
    elif s == 6:
        arms = dot = True
        top = False
    elif s == 7:
        diag = dot = True
    elif s == 8:
        chevron = True

    if circle:
        r = max(1, gap + length)
        ellipse(cx - r, cy - r, cx + r, cy + r)
    if diag and length > 0:
        d0 = gap + t / 2.0
        d1 = max(d0, gap + length - t / 2.0)
        k0 = d0 / 1.41421356
        k1 = d1 / 1.41421356
        line(cx + k0, cy + k0, cx + k1, cy + k1)
        line(cx - k0, cy + k0, cx - k1, cy + k1)
        line(cx + k0, cy - k0, cx + k1, cy - k1)
        line(cx - k0, cy - k0, cx - k1, cy - k1)
    if chevron:
        k = max(1, length) / 1.41421356
        ay = cy + gap
        line(cx - k, ay + k, cx, ay)
        line(cx, ay, cx + k, ay + k)
    if arms:
        half = (t - 1) / 2.0
        x0 = cx - half
        x1 = cx + half
        y0 = cy - half
        y1 = cy + half
        rect(x1 + gap + 1, y0, x1 + gap + 1 + length, y1)            # right
        rect(x0 - gap - length, y0, x0 - gap - 1, y1)                # left
        rect(x0, y1 + gap + 1, x1, y1 + gap + 1 + length)            # bottom
        if top:
            rect(x0, y0 - gap - length, x1, y0 - gap - 1)            # top
    if dot:
        d = max(1, c.dot_size)
        rect(cx - (d - 1) / 2.0, cy - (d - 1) / 2.0, cx + (d - 1) / 2.0, cy + (d - 1) / 2.0)


_img_cache = {}


def _get_image(path):
    img = _img_cache.get(path)
    if img is None:
        try:
            img = Image.open(path).convert("RGBA")
        except (OSError, ValueError):
            return None
        _img_cache[path] = img
    return img


def _draw_image_crosshair(draw, cx, cy, c, scale=1.0):
    if not c.image_path:
        return False
    img = _get_image(c.image_path)
    if img is None:
        return False
    sc =max(1, c.scale) / 100.0 * scale
    w = max(1, round(img.width * sc))
    h = max(1, round(img.height * sc))
    resized = img.resize((w, h), Image.BILINEAR)
    # the image's own colors, alpha multiplied by the color's opacity
    alpha = (c.color >> 24) & 0xFF
    if alpha < 255:
        resized.putalpha(resized.getchannel("A").point(lambda v: v * alpha // 255))
    target = draw._image
    layer = Image.new("RGBA", target.size, (0, 0, 0, 0))
    layer.paste(resized, (round(cx - w / 2), round(cy - h / 2)))
    target.alpha_composite(layer)
    return True


def draw_text_item(draw, w, h, cx, cy, t, now=None):
    """Draws a text item with anchor, outline and background. Returns None or the bbox."""
    s = expand_placeholders(t.text, now).replace("\r\n", "\n").replace("\r", "\n")
    if not s.strip():
        return
    font = _load_font(t.font_name, t.font_size, t.bold, t.italic)
    color = argb_to_rgba(t.color)
    ocolor = argb_to_rgba(t.outline_color)

    lines = s.split("\n")
    # per-line measurements
    line_metrics = []
    for ln in lines:
        bbox = font.getbbox(ln)
        line_metrics.append((ln, bbox, font.getlength(ln)))
    line_h = font.size
    ascent = font.getmetrics()[0]
    total_h = line_h * len(lines)

    # horizontal alignment
    max_w = max((m[2] for m in line_metrics), default=0)
    near_crosshair = t.anchor == ANCHOR_CROSSHAIR
    col = 1 if near_crosshair else t.anchor % 3
    row = 1 if near_crosshair else t.anchor // 3

    if near_crosshair:
        ax, ay = cx, cy
    else:
        ax = 0 if col == 0 else (w / 2.0 if col == 1 else w)
        ay = 0 if row == 0 else (h / 2.0 if row == 1 else h)

    ext = max(t.outline_width if t.outline else 0, 8 if t.background else 0)
    box_w = max_w
    box_h = total_h

    if col == 0:
        bx = ax + ext
    elif col == 1:
        bx = ax - box_w / 2
    else:
        bx = ax - box_w - ext
    if row == 0:
        by = ay + ext
    elif row == 1:
        by = ay - box_h / 2
    else:
        by = ay - box_h - ext
    bx += t.offset_x
    by += t.offset_y

    # background
    if t.background:
        pad = 8 + (t.outline_width if t.outline else 0)
        bgc = argb_to_rgba(t.background_color)
        draw.rounded_rectangle(
            (bx - pad, by - pad, bx + box_w + pad, by + box_h + pad),
            radius=6, fill=bgc)

    # text, line by line
    y = by
    for ln, bbox, ln_w in line_metrics:
        x = bx
        if col == 1:
            x = bx + (box_w - ln_w) / 2
        elif col == 2:
            x = bx + (box_w - ln_w)
        if t.outline and t.outline_width > 0:
            ow = t.outline_width
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((x + dx, y + dy), ln, font=font, fill=ocolor)
        draw.text((x, y), ln, font=font, fill=color)
        y += line_h


def render(settings, w, h, show_cross, show_texts, now=None):
    """Returns a w×h RGBA image with the overlay (or None if there is nothing to show)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = w // 2 + settings.crosshair.offset_x
    cy = h // 2 + settings.crosshair.offset_y
    if show_texts:
        for t in settings.texts:
            if t.visible:
                draw_text_item(draw, w, h, cx, cy, t, now)
    if show_cross and settings.crosshair.visible:
        draw_crosshair(draw, cx, cy, settings.crosshair)
    return img


def render_preview(settings, size=200):
    """Crosshair preview on a dark grid background, for the GUI."""
    img = Image.new("RGBA", (size, size), (11, 17, 25, 255))
    draw = ImageDraw.Draw(img)
    step = max(12, size // 9)
    for x in range(step // 2, size, step):
        draw.line((x, 0, x, size), fill=(0, 225, 255, 20), width=1)
    for y in range(step // 2, size, step):
        draw.line((0, y, size, y), fill=(0, 225, 255, 20), width=1)
    c = settings.crosshair
    if c.visible:
        draw_crosshair(draw, size // 2, size // 2, c)
    return img


# --- overlay window (thread with message loop) ---------------------------------
class _BMP_INFO(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


BI_RGB = 0
DIB_RGB_COLORS = 0

# private messages to the overlay thread
WM_APP_REFRESH = 0x8000 + 1   # redraw
WM_APP_HOTKEYS = 0x8000 + 2   # re-register the hotkeys
WM_TIMER = 0x0113
TIMER_CLOCK = 1               # refresh of the {time}/{timesec}/{date} placeholders
TIMER_TOP = 2                 # bring the overlay back to the top

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

WNDPROC = ctypes.WINFUNCTYPE(winapi.LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG,
                                  wt.LONG, wt.DWORD, wt.DWORD)
USER32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC,
                                   wt.DWORD, wt.DWORD, wt.DWORD]
USER32.SetWinEventHook.restype = wt.HANDLE
USER32.UnhookWinEvent.argtypes = [wt.HANDLE]
USER32.UnhookWinEvent.restype = wt.BOOL
USER32.IsWindowVisible.argtypes = [wt.HWND]
USER32.IsWindowVisible.restype = wt.BOOL


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC,
                                      ctypes.POINTER(wt.RECT), wt.LPARAM)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


USER32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), _MONITORENUMPROC, wt.LPARAM]
USER32.EnumDisplayMonitors.restype = wt.BOOL
USER32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(_MONITORINFO)]
USER32.GetMonitorInfoW.restype = wt.BOOL
USER32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
USER32.RegisterClassW.restype = wt.ATOM
USER32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
USER32.UnregisterClassW.restype = wt.BOOL
USER32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
]
USER32.CreateWindowExW.restype = wt.HWND
USER32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
USER32.DefWindowProcW.restype = winapi.LRESULT
USER32.DestroyWindow.argtypes = [wt.HWND]
USER32.DestroyWindow.restype = wt.BOOL
USER32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
USER32.ShowWindow.restype = wt.BOOL
USER32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
USER32.PostMessageW.restype = wt.BOOL
USER32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wt.HWND, wt.UINT, wt.UINT]
USER32.GetMessageW.restype = wt.BOOL
USER32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
USER32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
USER32.DispatchMessageW.restype = winapi.LRESULT
USER32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
USER32.SetTimer.restype = ctypes.c_size_t
USER32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
USER32.KillTimer.restype = wt.BOOL
USER32.GetSystemMetrics.argtypes = [ctypes.c_int]
USER32.GetSystemMetrics.restype = ctypes.c_int


def list_monitors():
    """[(x, y, w, h, primary), ...] via EnumDisplayMonitors."""
    result = []

    def cb(hmon, _hdc, _lprc, _l):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if USER32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            rc = info.rcMonitor
            result.append((rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top,
                           bool(info.dwFlags & 1)))
        return True

    USER32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(cb), 0)
    if not result:
        result = [(0, 0, USER32.GetSystemMetrics(0), USER32.GetSystemMetrics(1), True)]
    return result


class Overlay:
    """Transparent top-most window with crosshair/text.

    It has its own thread with a message loop (for RegisterHotKey). Call start()
    once, then update() to redraw and stop() to close. All Win32 calls on
    the window happen in the overlay thread: other threads send it messages
    with PostMessage.
    """

    CLASS_NAME = "GameToolOverlay"

    def __init__(self, settings, on_hotkey=None):
        self.settings = settings
        self.on_hotkey = on_hotkey or (lambda _id: None)
        self._hwnd = None
        self._thread = None
        self._ready = threading.Event()
        self._hk_done = threading.Event()
        self._hk_failed = []
        # the overlay is off at startup: the user turns it on (switch or hotkey)
        self._show_all = False
        self._show_cross = True
        self._show_texts = True
        self._clock = ""

    # --- monitors ---------------------------------------------------------------
    def monitors(self):
        return list_monitors()

    def _monitor_rect(self):
        mons = list_monitors()
        i = self.settings.monitor
        if 0 <= i < len(mons):
            return mons[i]
        return mons[0]

    # --- lifecycle ----------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="Overlay", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def stop(self):
        if self._hwnd:
            USER32.PostMessageW(self._hwnd, 0x0012, 0, 0)  # WM_QUIT
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def set_show(self, show_all=None, show_cross=None, show_texts=None):
        if show_all is not None:
            self._show_all = show_all
            if show_all:
                self._show_cross = True
                self._show_texts = True
        if show_cross is not None:
            self._show_cross = show_cross
            self._show_all = True
        if show_texts is not None:
            self._show_texts = show_texts
            self._show_all = True
        self.update()

    def toggle(self, hid):
        """Action of a hotkey (1 = everything, 2 = crosshair, 3 = text)."""
        if hid == 1:
            self._show_all = not self._show_all
        elif hid == 2:
            self._show_cross = not self._show_cross
            self._show_all = True
        elif hid == 3:
            self._show_texts = not self._show_texts
            self._show_all = True
        self.update()

    @property
    def show_all(self):
        return self._show_all

    # --- hotkeys -----------------------------------------------------------------
    def register_hotkeys(self):
        """Re-registers the hotkeys from the settings; returns the unavailable ones.

        RegisterHotKey must be called from the thread that owns the window, so
        from another thread a message is sent and the result is awaited.
        """
        if not self._hwnd:
            return []
        if threading.current_thread() is self._thread:
            return self._register_hotkeys()
        self._hk_done.clear()
        USER32.PostMessageW(self._hwnd, WM_APP_HOTKEYS, 0, 0)
        self._hk_done.wait(timeout=1)
        return list(self._hk_failed)

    def _register_hotkeys(self):
        failed = []
        pairs = [(1, self.settings.hotkey_all),
                 (2, self.settings.hotkey_crosshair),
                 (3, self.settings.hotkey_texts)]
        for hid, val in pairs:
            USER32.UnregisterHotKey(self._hwnd, hid)
            if not val:
                continue
            mod = MOD_NOREPEAT
            # .NET Keys modifier flags (official MS values) -> RegisterHotKey
            if (val & 0x40000):  # Alt
                mod |= MOD_ALT
            if (val & 0x20000):  # Control
                mod |= MOD_CONTROL
            if (val & 0x10000):  # Shift
                mod |= MOD_SHIFT
            code = val & 0xFFFF
            if not USER32.RegisterHotKey(self._hwnd, hid, mod, code):
                failed.append(hotkey_name(val))
        self._hk_failed = failed
        return failed

    def _unregister_hotkeys(self):
        for hid in (1, 2, 3):
            USER32.UnregisterHotKey(self._hwnd, hid)

    # --- image update --------------------------------------------------
    def update(self):
        """Asks for a redraw (can be called from any thread)."""
        if self._hwnd:
            USER32.PostMessageW(self._hwnd, WM_APP_REFRESH, 0, 0)

    def _has_placeholders(self):
        for t in self.settings.texts:
            if t.visible and "{" in (t.text or ""):
                return True
        return False

    def _push(self):
        """Draws the current image and sends it to the layered window."""
        x, y, w, h, _ = self._monitor_rect()
        cross = self._show_all and self._show_cross and self.settings.crosshair.visible
        texts = (self._show_all and self._show_texts and self.settings.texts_visible
                 and any(t.visible for t in self.settings.texts))
        if not cross and not texts:
            USER32.ShowWindow(self._hwnd, 0)  # SW_HIDE
            return
        img = render(self.settings, w, h, cross, texts)
        self._layered(img, x, y)
        USER32.ShowWindow(self._hwnd, 8)  # SW_SHOWNA
        self._keep_on_top()

    def _keep_on_top(self):
        """Brings the overlay back to the top of the TOPMOST windows.

        Many games in borderless window mode are TOPMOST too: when they
        take focus they go above the overlay, which must then be put back
        on top (both when the window changes and with a timer).
        """
        if self._hwnd and USER32.IsWindowVisible(self._hwnd):
            USER32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _layered(self, img, x, y):
        """UpdateLayeredWindow with a 32bpp top-down DIB (premultiplied alpha)."""
        w, h = img.size
        # UpdateLayeredWindow with AC_SRC_ALPHA wants premultiplied colors
        buf = img.convert("RGBa").tobytes("raw", "BGRa")

        screen_dc = USER32.GetDC(None)
        mem_dc = GDI32.CreateCompatibleDC(screen_dc)
        info = _BMP_INFO()
        info.biSize = ctypes.sizeof(_BMP_INFO)
        info.biWidth = w
        info.biHeight = -h  # top-down
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        # CreateDIBSection(hdc, pbmi, usage, ppvBits, hSection, offset) -> HBITMAP
        hbit = GDI32.CreateDIBSection(mem_dc, ctypes.byref(info), DIB_RGB_COLORS,
                                      ctypes.byref(bits), None, 0)
        if not hbit or not bits.value:
            GDI32.DeleteDC(mem_dc)
            USER32.ReleaseDC(None, screen_dc)
            return False
        ctypes.memmove(bits, buf, len(buf))
        old = GDI32.SelectObject(mem_dc, hbit)
        size = _SIZE(w, h)
        src = _POINT(0, 0)
        dst = _POINT(x, y)
        blend = _BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        ok = USER32.UpdateLayeredWindow(self._hwnd, screen_dc, ctypes.byref(dst),
                                        ctypes.byref(size), mem_dc, ctypes.byref(src),
                                        0, ctypes.byref(blend), ULW_ALPHA)
        GDI32.SelectObject(mem_dc, old)
        GDI32.DeleteObject(hbit)
        GDI32.DeleteDC(mem_dc)
        USER32.ReleaseDC(None, screen_dc)
        return bool(ok)

    # --- message loop -----------------------------------------------------------
    def _run(self):
        # the callback must stay alive while the class is registered
        self._wnd_proc = WNDPROC(self._wnd_proc_impl)
        hinst = winapi.kernel32.GetModuleHandleW(None)
        wc = _WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = hinst
        wc.lpszClassName = self.CLASS_NAME
        USER32.RegisterClassW(ctypes.byref(wc))

        ex = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW |
              WS_EX_TOPMOST | WS_EX_NOACTIVATE)
        self._hwnd = USER32.CreateWindowExW(
            ex, self.CLASS_NAME, "GameTool overlay", WS_POPUP,
            0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            USER32.UnregisterClassW(self.CLASS_NAME, hinst)
            self._ready.set()
            return

        self._register_hotkeys()
        USER32.SetTimer(self._hwnd, TIMER_CLOCK, 250, None)
        USER32.SetTimer(self._hwnd, TIMER_TOP, 50, None)
        # as soon as another window (the game) becomes active, go back on top right away
        self._fg_proc = WINEVENTPROC(lambda *a: self._keep_on_top())
        fg_hook = USER32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._fg_proc,
            0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        self._ready.set()
        self._push()

        msg = _MSG()
        while USER32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            USER32.TranslateMessage(ctypes.byref(msg))
            USER32.DispatchMessageW(ctypes.byref(msg))

        if fg_hook:
            USER32.UnhookWinEvent(fg_hook)
        USER32.KillTimer(self._hwnd, TIMER_CLOCK)
        USER32.KillTimer(self._hwnd, TIMER_TOP)
        self._unregister_hotkeys()
        hwnd, self._hwnd = self._hwnd, None
        USER32.DestroyWindow(hwnd)
        USER32.UnregisterClassW(self.CLASS_NAME, hinst)

    def _wnd_proc_impl(self, hwnd, msg, wparam, lparam):
        try:
            if msg == 0x0084:  # WM_NCHITTEST
                return -1  # HTTRANSPARENT: let clicks through
            if msg == WM_HOTKEY:
                self.on_hotkey(wparam)
                return 0
            if msg == WM_APP_REFRESH:
                self._push()
                return 0
            if msg == WM_APP_HOTKEYS:
                self._register_hotkeys()
                self._hk_done.set()
                return 0
            if msg == WM_TIMER and wparam == TIMER_TOP:
                # some games make themselves TOPMOST again after taking focus (or all the time)
                self._keep_on_top()
                return 0
            if msg == WM_TIMER and wparam == TIMER_CLOCK:
                # redraw only when the placeholder text really changes
                if self._has_placeholders():
                    clock = expand_placeholders("{orasec} {data}")
                    if clock != self._clock:
                        self._clock = clock
                        self._push()
                return 0
            if msg == 0x007E:  # WM_DISPLAYCHANGE
                self._push()
                return 0
        except Exception:  # a drawing error must not close the overlay
            import traceback
            traceback.print_exc()
            return 0
        return USER32.DefWindowProcW(hwnd, msg, wparam, lparam)
