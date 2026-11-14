"""Minimal ctypes bindings to the Win32 APIs used by the app.

Contains: structures for the low-level hooks (keyboard/mouse), SendInput
to simulate input, and a few utilities (high-resolution timer, foreground
process).
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

# Value written to dwExtraInfo to recognize the input we generate.
MAGIC = 0x4D4B4559  # "MKEY"

# --- hook / message constants -------------------------------------------------
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C

LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01

# --- SendInput constants -------------------------------------------------------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

MAPVK_VK_TO_VSC_EX = 4
MAPVK_VSC_TO_VK_EX = 3
MAPVK_VK_TO_CHAR = 2

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

VK_PAUSE = 0x13


# --- structures ----------------------------------------------------------------
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

# --- prototypes ----------------------------------------------------------------
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT
user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
user32.MapVirtualKeyW.restype = wt.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


# --- sending input --------------------------------------------------------------
def _send(inputs):
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key_input(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(vk, scan, flags, 0, MAGIC)
    return inp


def _mouse_input(dx=0, dy=0, data=0, flags=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, MAGIC)
    return inp


# --- last state we sent for each VK (for incognito mode) ------
# With hooks our input is recognizable by dwExtraInfo == MAGIC; with
# polling only the key state is visible. Here we note what we sent and
# when, so the polling can tell which state changes come from macros.
_sent = {}  # vk -> (down, perf_counter)
_GENERIC_TO_LEFT = {0x10: 0xA0, 0x11: 0xA2, 0x12: 0xA4}
_BUTTON_VK = {"left": 0x01, "right": 0x02, "middle": 0x04, "x1": 0x05, "x2": 0x06}


def _mark_sent(vk, down):
    entry = (down, time.perf_counter())
    _sent[vk] = entry
    if vk in _GENERIC_TO_LEFT:  # generic Shift/Ctrl/Alt arrive as the left key
        _sent[_GENERIC_TO_LEFT[vk]] = entry


def sent_by_us(vk, down, window=0.25):
    """True if the last input we sent for vk put the key in the `down` state
    less than `window` seconds ago."""
    entry = _sent.get(vk)
    return entry is not None and entry[0] == down and time.perf_counter() - entry[1] <= window


def send_vk(vk, down):
    """Sends a key by scancode (compatible with DirectInput/games)."""
    _mark_sent(vk, down)
    sc = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)
    flags = 0 if down else KEYEVENTF_KEYUP
    if sc == 0 or vk == VK_PAUSE:
        _send([_key_input(vk=vk, flags=flags)])
        return
    flags |= KEYEVENTF_SCANCODE
    if sc & 0xFF00 in (0xE000, 0xE100):
        flags |= KEYEVENTF_EXTENDEDKEY
    _send([_key_input(vk=vk, scan=sc & 0xFF, flags=flags)])


def send_scancode(sc, down):
    vk = scancode_to_vk(sc)
    if vk:
        _mark_sent(vk, down)
    flags =KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    if sc & 0xFF00 in (0xE000, 0xE100):
        flags |= KEYEVENTF_EXTENDEDKEY
    _send([_key_input(scan=sc & 0xFF, flags=flags)])


_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
    "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
}


def send_mouse_button(button, down):
    fdown, fup, data = _BUTTON_FLAGS[button]
    _mark_sent(_BUTTON_VK[button], down)
    _send([_mouse_input(data=data, flags=fdown if down else fup)])


def send_mouse_move_rel(dx, dy):
    _send([_mouse_input(dx=dx, dy=dy, flags=MOUSEEVENTF_MOVE)])


def send_mouse_move_abs(x, y):
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) - 1, 1)
    vh = max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) - 1, 1)
    nx = round((x - vx) * 65535 / vw)
    ny = round((y - vy) * 65535 / vh)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    _send([_mouse_input(dx=nx, dy=ny, flags=flags)])


def send_wheel(delta):
    _send([_mouse_input(data=delta, flags=MOUSEEVENTF_WHEEL)])


def send_text(text):
    inputs = []
    raw = text.encode("utf-16-le")
    for i in range(0, len(raw), 2):
        unit = int.from_bytes(raw[i:i + 2], "little")
        inputs.append(_key_input(scan=unit, flags=KEYEVENTF_UNICODE))
        inputs.append(_key_input(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    _send(inputs)


# --- utilities -----------------------------------------------------------------
def is_key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def vk_to_char(vk):
    """Character printed on the key in the current layout (e.g. 'ò')."""
    ch = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_CHAR) & 0x7FFFFFFF
    return chr(ch) if ch else ""


def scancode_to_vk(sc):
    return user32.MapVirtualKeyW(sc, MAPVK_VSC_TO_VK_EX)


def foreground_pid():
    """PID of the process that owns the foreground window (0 if none)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_process_name():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return process_name(pid.value)


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND


def window_processes():
    """Names (.exe) of the processes with at least one visible window, in alphabetical order."""
    pids = set()

    def callback(hwnd, _):
        # only visible top-level windows with a title (no tooltips, overlays, ...)
        if (user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0
                and not user32.GetWindow(hwnd, 4)):  # GW_OWNER
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.add(pid.value)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    pids.discard(os.getpid())
    names = {process_name(pid) for pid in pids}
    names.discard("")
    names -= {"explorer.exe", "TextInputHost.exe", "ApplicationFrameHost.exe", "SystemSettings.exe"}
    return sorted(names, key=str.lower)


def process_name(pid):
    """Executable name of a process (e.g. 'game.exe'), or "" if not accessible."""
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def enable_high_res_timer():
    winmm.timeBeginPeriod(1)


shell32 = ctypes.WinDLL("shell32")
shell32.IsUserAnAdmin.restype = wt.BOOL
shell32.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]
shell32.ShellExecuteW.restype = wt.HINSTANCE


def is_admin():
    """True if the process has administrator rights (elevated token)."""
    try:
        return bool(shell32.IsUserAnAdmin())
    except OSError:
        return False


def run_as_admin(exe, params, cwd):
    """Starts exe elevated (UAC prompt). True if it started successfully;
    False if the user declined or the start failed."""
    result = shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1)  # SW_SHOWNORMAL
    return (result or 0) > 32  # values <= 32 are error codes (5 = declined)


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def add_private_font(path):
    """Makes a .ttf file available to this process only (without installing it)."""
    try:
        FR_PRIVATE = 0x10
        return ctypes.windll.gdi32.AddFontResourceExW(ctypes.c_wchar_p(path), FR_PRIVATE, None) > 0
    except (AttributeError, OSError):
        return False


def style_title_bar(widget, caption_rgb=None):
    """Dark title bar (Windows 10/11) and, on Windows 11, a custom color."""
    try:
        user32.GetParent.argtypes = [wt.HWND]
        user32.GetParent.restype = wt.HWND
        hwnd = user32.GetParent(widget.winfo_id()) or widget.winfo_id()
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(wt.HWND(hwnd), 20, ctypes.byref(dark), ctypes.sizeof(dark))
        if caption_rgb:
            r, g, b = (int(caption_rgb[i:i + 2], 16) for i in (1, 3, 5))
            color = wt.DWORD(r | (g << 8) | (b << 16))
            dwm.DwmSetWindowAttribute(wt.HWND(hwnd), 35, ctypes.byref(color), ctypes.sizeof(color))
    except (AttributeError, OSError):
        pass


def precise_sleep(seconds, stop_event: threading.Event = None):
    """Millisecond-accurate wait. Returns True if interrupted by stop_event."""
    end = time.perf_counter() + seconds
    while True:
        if stop_event is not None and stop_event.is_set():
            return True
        remaining = end - time.perf_counter()
        if remaining <= 0:
            return False
        if remaining > 0.02:
            chunk = min(remaining - 0.01, 0.05)
            if stop_event is not None:
                stop_event.wait(chunk)
            else:
                time.sleep(chunk)
        elif remaining > 0.002:
            time.sleep(0.001)
        else:
            time.sleep(0)


# --- DWM (window borders) ----------------------------------------------------
DWMWA_CAPTION_COLOR = 35
DWMWA_BORDER_COLOR = 34
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def dwm_captions(hwnd):
    """(dwmapi, caption attribute, border attribute, corner attribute)."""
    dwm = ctypes.windll.dwmapi
    dwm.DwmSetWindowAttribute.argtypes = [wt.HWND, ctypes.c_int, wt.LPVOID, ctypes.c_uint]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_int
    return dwm, DWMWA_CAPTION_COLOR, DWMWA_BORDER_COLOR, DWMWA_WINDOW_CORNER_PREFERENCE


def dwm_round(hwnd, pref=DWMWCP_ROUND):
    dwm, _, _, corner = dwm_captions(hwnd)
    val = ctypes.c_int(pref)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), corner, ctypes.byref(val), ctypes.sizeof(val))


def dwm_square(hwnd):
    dwm, _, _, corner = dwm_captions(hwnd)
    val = ctypes.c_int(0)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), corner, ctypes.byref(val), ctypes.sizeof(val))


def dwm_caption(hwnd, rgb):
    dwm, cap, _, _ = dwm_captions(hwnd)
    color = wt.DWORD(rgb)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), cap, ctypes.byref(color), ctypes.sizeof(color))


def dwm_border(hwnd, rgb):
    dwm, _, border, _ = dwm_captions(hwnd)
    color = wt.DWORD(rgb)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), border, ctypes.byref(color), ctypes.sizeof(color))


def dwm_blur(hwnd):
    dwm, _, _, _ = dwm_captions(hwnd)
    val = ctypes.c_int(1)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val))


def dwm_no_blur(hwnd):
    dwm, _, _, _ = dwm_captions(hwnd)
    val = ctypes.c_int(0)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val))


# --- stealth polling (no hooks) -------------------------------------------
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetCursorPos.restype = wt.BOOL


def stealth_mouse_pos():
    """Current cursor position."""
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# --- hook watchdog ------------------------------------------------------
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wt.BOOL
kernel32.GetTickCount.restype = wt.DWORD


def tick_count():
    """Milliseconds since Windows started (wraps to zero every 49.7 days)."""
    return kernel32.GetTickCount()


def last_input_tick():
    """tick_count() of the last input (keyboard/mouse) received by the system."""
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return tick_count()
    return info.dwTime
