"""Key names <-> virtual-key codes, and mouse button names."""
from . import winapi

_NAME_TO_VK = {}
_VK_TO_NAME = {}


def _add(name, vk, *aliases):
    _NAME_TO_VK[name.lower()] = vk
    _VK_TO_NAME.setdefault(vk, name)
    CANONICAL[name.lower()] = name
    for alias in aliases:
        _NAME_TO_VK[alias.lower()] = vk
        CANONICAL[alias.lower()] = name


CANONICAL = {}

for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _add(_c, ord(_c))
for _d in range(10):
    _add(str(_d), 0x30 + _d, f"D{_d}")
for _f in range(1, 25):
    _add(f"F{_f}", 0x6F + _f)
for _n in range(10):
    _add(f"NumPad{_n}", 0x60 + _n, f"Num{_n}")

_add("Backspace", 0x08, "Back")
_add("Tab", 0x09)
_add("Enter", 0x0D, "Return")
_add("Shift", 0x10)
_add("Ctrl", 0x11, "Control")
_add("Alt", 0x12, "Menu")
_add("Pause", 0x13)
_add("CapsLock", 0x14, "Capital")
_add("Esc", 0x1B, "Escape")
_add("Space", 0x20)
_add("PageUp", 0x21, "Prior")
_add("PageDown", 0x22, "Next")
_add("End", 0x23)
_add("Home", 0x24)
_add("Left", 0x25)
_add("Up", 0x26)
_add("Right", 0x27)
_add("Down", 0x28)
_add("PrintScreen", 0x2C, "Snapshot")
_add("Insert", 0x2D)
_add("Delete", 0x2E, "Del")
_add("LWin", 0x5B)
_add("RWin", 0x5C)
_add("Apps", 0x5D)
_add("Multiply", 0x6A)
_add("Add", 0x6B)
_add("Subtract", 0x6D)
_add("Decimal", 0x6E)
_add("Divide", 0x6F)
_add("NumLock", 0x90)
_add("ScrollLock", 0x91, "Scroll")
_add("LShift", 0xA0, "LShiftKey")
_add("RShift", 0xA1, "RShiftKey")
_add("LCtrl", 0xA2, "LControlKey")
_add("RCtrl", 0xA3, "RControlKey")
_add("LAlt", 0xA4, "LMenu")
_add("RAlt", 0xA5, "RMenu")
_add("VolumeMute", 0xAD)
_add("VolumeDown", 0xAE)
_add("VolumeUp", 0xAF)
_add("MediaNext", 0xB0)
_add("MediaPrev", 0xB1)
_add("MediaStop", 0xB2)
_add("MediaPlay", 0xB3)
# OEM keys: the name refers to the position on the US layout.
_add("Semicolon", 0xBA, "Oem1")
_add("Equals", 0xBB, "Oemplus")
_add("Comma", 0xBC, "Oemcomma")
_add("Minus", 0xBD, "OemMinus")
_add("Period", 0xBE, "OemPeriod")
_add("Slash", 0xBF, "Oem2", "OemQuestion")
_add("Grave", 0xC0, "Oem3", "Oemtilde")
_add("LBracket", 0xDB, "Oem4", "OemOpenBrackets")
_add("Backslash", 0xDC, "Oem5")
_add("RBracket", 0xDD, "Oem6")
_add("Quote", 0xDE, "Oem7")
_add("Oem102", 0xE2)

# Mouse buttons that can be used as triggers (and in macros).
MOUSE_BUTTONS = {
    "MouseLeft": "left",
    "MouseRight": "right",
    "MouseMiddle": "middle",
    "MouseX1": "x1",
    "MouseX2": "x2",
}
WHEEL_TRIGGERS = ("WheelUp", "WheelDown")
for _m in list(MOUSE_BUTTONS) + list(WHEEL_TRIGGERS):
    CANONICAL[_m.lower()] = _m

# Modifiers for combinations (e.g. Ctrl+F1).
MODIFIERS = {
    "Ctrl": (0x11, {"LCtrl", "RCtrl", "Ctrl"}),
    "Shift": (0x10, {"LShift", "RShift", "Shift"}),
    "Alt": (0x12, {"LAlt", "RAlt", "Alt"}),
    "Win": (0x5B, {"LWin", "RWin"}),
}
MODIFIER_KEYS = set().union(*(names for _, names in MODIFIERS.values()))


def vk_from_name(name):
    """Returns the VK for a key name, or None."""
    low = name.lower()
    if low in _NAME_TO_VK:
        return _NAME_TO_VK[low]
    if low.startswith("vk_"):
        try:
            return int(low[3:], 0)
        except ValueError:
            return None
    return None


def name_from_vk(vk):
    return _VK_TO_NAME.get(vk, f"VK_0x{vk:02X}")


def canonical(name):
    """Normalized name of a key/button, or None if unknown."""
    low = name.strip().lower()
    if low in CANONICAL:
        return CANONICAL[low]
    vk = vk_from_name(low)
    return name_from_vk(vk) if vk is not None else None


def is_mouse(name):
    return name in MOUSE_BUTTONS or name in WHEEL_TRIGGERS


def label(name):
    """Readable label: for OEM keys it adds the character on the current layout."""
    vk = vk_from_name(name)
    if vk is not None and (0xBA <= vk <= 0xC0 or 0xDB <= vk <= 0xE2):
        ch = winapi.vk_to_char(vk)
        if ch:
            return f"{name} [{ch}]"
    return name


def all_trigger_names():
    names = sorted({v for v in _VK_TO_NAME.values()}, key=lambda n: (len(n) > 1, n))
    return list(MOUSE_BUTTONS) + list(WHEEL_TRIGGERS) + names


def current_modifiers(exclude=None):
    """Set of the modifiers currently pressed (excluding the trigger itself)."""
    pressed = set()
    for mod, (vk, names) in MODIFIERS.items():
        if exclude in names:
            continue
        if mod == "Win":
            down = winapi.is_key_down(0x5B) or winapi.is_key_down(0x5C)
        else:
            down = winapi.is_key_down(vk)
        if down:
            pressed.add(mod)
    return pressed
