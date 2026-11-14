"""Macro language: parser, runner and import of .amc files.

One command per line; empty lines and lines starting with # or // are
ignored. See SYNTAX_HELP for the list of commands.
"""
import random
import re
import shlex
import threading
import time
import xml.etree.ElementTree as ET

from . import keys, winapi

SYNTAX_HELP = """\
KeyDown A / KeyUp A    press / release
KeyPress A [ms]        press and release
Delay 25               wait 25 ms
Delay 20-40            random wait
LeftDown / LeftUp      left button
LeftClick              left click
Right.. Middle.. X1.. X2..  (same)
MoveR dx dy            move (relative)
MoveTo x y             move (absolute)
WheelUp [n]            wheel up
WheelDown [n]          wheel down
Text "hello"           type text
Repeat 5 ... EndRepeat repeat a block
# text                 comment

Keys: A-Z 0-9 F1-F24 Space Enter
Tab Esc Backspace LShift RShift
LCtrl RCtrl LAlt RAlt LWin RWin
Up Down Left Right Insert Delete
Home End PageUp PageDown CapsLock
NumPad0-9 Add Subtract Multiply
Minus Equals Comma Period Slash
Grave Quote Semicolon LBracket
RBracket Backslash Oem102 sc:N

Don't know a key's name?
Use "Record" and press it.
"""

_BUTTON_WORDS = {"left": "left", "right": "right", "middle": "middle", "x1": "x1", "x2": "x2"}
_BUTTON_RE = re.compile(r"^(left|right|middle|x1|x2)(down|up|click)$")
_DELAY_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?$")


class ScriptError(Exception):
    def __init__(self, line_no, message):
        super().__init__(f"Line {line_no}: {message}")
        self.line_no = line_no


def _parse_key(token, line_no):
    if token.lower().startswith("sc:"):
        try:
            return ("sc", int(token[3:], 0))
        except ValueError:
            raise ScriptError(line_no, f"invalid scancode: {token}")
    vk = keys.vk_from_name(token)
    if vk is None:
        raise ScriptError(line_no, f"unknown key: {token}")
    return ("vk", vk)


def _int(token, line_no, what="number"):
    try:
        return int(token)
    except ValueError:
        raise ScriptError(line_no, f"invalid {what}: {token}")


def parse(text):
    """Converts the text into a list of operations. Raises ScriptError."""
    root = []
    stack = [(root, None, 0)]  # (current list, repeat count, line)
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        try:
            parts = shlex.split(line, posix=True)
        except ValueError as exc:
            raise ScriptError(line_no, str(exc))
        cmd, args = parts[0].lower(), parts[1:]
        ops = stack[-1][0]

        if cmd in ("keydown", "keyup"):
            if not args:
                raise ScriptError(line_no, "missing key")
            ops.append((cmd, _parse_key(args[0], line_no)))
        elif cmd == "keypress":
            if not args:
                raise ScriptError(line_no, "missing key")
            hold = _int(args[1], line_no, "duration") if len(args) > 1 else 0
            ops.append(("keypress", _parse_key(args[0], line_no), hold))
        elif cmd in ("delay", "sleep", "wait"):
            spec = " ".join(a for a in args if a.lower() != "ms")
            m = _DELAY_RE.match(spec)
            if not m:
                raise ScriptError(line_no, "Delay needs the milliseconds (e.g. Delay 20)")
            lo = float(m.group(1))
            hi = float(m.group(2)) if m.group(2) else lo
            if hi < lo:
                lo, hi = hi, lo
            ops.append(("delay", lo, hi))
        elif _BUTTON_RE.match(cmd):
            btn, action = _BUTTON_RE.match(cmd).groups()
            ops.append(("button", _BUTTON_WORDS[btn], action))
        elif cmd in ("mover", "moverel"):
            if len(args) < 2:
                raise ScriptError(line_no, "MoveR needs dx dy")
            ops.append(("mover", _int(args[0], line_no), _int(args[1], line_no)))
        elif cmd in ("moveto", "move"):
            if len(args) < 2:
                raise ScriptError(line_no, "MoveTo needs x y")
            ops.append(("moveto", _int(args[0], line_no), _int(args[1], line_no)))
        elif cmd in ("wheelup", "wheeldown"):
            n = _int(args[0], line_no) if args else 1
            ops.append(("wheel", (120 if cmd == "wheelup" else -120) * max(n, 1)))
        elif cmd == "wheel":
            if not args:
                raise ScriptError(line_no, "Wheel needs a value (e.g. 120)")
            ops.append(("wheel", _int(args[0], line_no)))
        elif cmd in ("text", "type"):
            ops.append(("text", " ".join(args)))
        elif cmd in ("repeat", "loop"):
            count = _int(args[0], line_no) if args else 1
            block = []
            ops.append(("repeat", count, block))
            stack.append((block, count, line_no))
        elif cmd in ("endrepeat", "endloop", "end"):
            if len(stack) == 1:
                raise ScriptError(line_no, "EndRepeat without Repeat")
            stack.pop()
        else:
            raise ScriptError(line_no, f"unknown command: {parts[0]}")
    if len(stack) > 1:
        raise ScriptError(stack[-1][2], "Repeat without EndRepeat")
    return root


# generic keys -> left/right variants seen by the hook
_GENERIC_VK = {0x10: (0xA0, 0xA1), 0x11: (0xA2, 0xA3), 0x12: (0xA4, 0xA5)}


class Runner:
    """Runs a list of operations while tracking the pressed keys/buttons,
    so they can be released if the macro is interrupted.

    user_keys: set of VKs the user is physically holding down.
    The macro doesn't release those keys, otherwise the game would
    consider them released while the finger is still on them (e.g. D to move).
    """

    def __init__(self, user_keys=None):
        self.user_keys = user_keys
        self.held_keys = set()
        self.held_buttons = set()
        self._lock = threading.Lock()

    def run(self, ops, stop_event=None):
        """Returns False if interrupted by stop_event."""
        for op in ops:
            if stop_event is not None and stop_event.is_set():
                return False
            kind = op[0]
            if kind == "keydown":
                self._key(op[1], True)
            elif kind == "keyup":
                self._key(op[1], False)
            elif kind == "keypress":
                self._key(op[1], True)
                if op[2] and winapi.precise_sleep(op[2] / 1000, stop_event):
                    self._key(op[1], False)
                    return False
                self._key(op[1], False)
            elif kind == "delay":
                ms = op[1] if op[1] == op[2] else random.uniform(op[1], op[2])
                if winapi.precise_sleep(ms / 1000, stop_event):
                    return False
            elif kind == "button":
                _, btn, action = op
                if action in ("down", "click"):
                    winapi.send_mouse_button(btn, True)
                    with self._lock:
                        self.held_buttons.add(btn)
                if action in ("up", "click"):
                    winapi.send_mouse_button(btn, False)
                    with self._lock:
                        self.held_buttons.discard(btn)
            elif kind == "mover":
                winapi.send_mouse_move_rel(op[1], op[2])
            elif kind == "moveto":
                winapi.send_mouse_move_abs(op[1], op[2])
            elif kind == "wheel":
                winapi.send_wheel(op[1])
            elif kind == "text":
                winapi.send_text(op[1])
            elif kind == "repeat":
                for _ in range(op[1]):
                    if not self.run(op[2], stop_event):
                        return False
        return True

    def _user_holds(self, key):
        if not self.user_keys:
            return False
        kind, code = key
        vk = winapi.scancode_to_vk(code) if kind == "sc" else code
        return any(v in self.user_keys for v in (vk,) + _GENERIC_VK.get(vk, ()))

    def _key(self, key, down):
        kind, code = key
        if not down and self._user_holds(key):
            with self._lock:
                self.held_keys.discard(key)
            return
        if kind == "sc":
            winapi.send_scancode(code, down)
        else:
            winapi.send_vk(code, down)
        with self._lock:
            (self.held_keys.add if down else self.held_keys.discard)(key)

    def release_all(self):
        with self._lock:
            held_keys, self.held_keys = self.held_keys, set()
            held_buttons, self.held_buttons = self.held_buttons, set()
        for key in held_keys:
            if self._user_holds(key):
                continue
            kind, code = key
            (winapi.send_scancode if kind == "sc" else winapi.send_vk)(code, False)
        for btn in held_buttons:
            winapi.send_mouse_button(btn, False)


def has_delay(ops):
    for op in ops:
        if op[0] in ("delay",) or (op[0] == "keypress" and op[2]):
            return True
        if op[0] == "repeat" and has_delay(op[2]):
            return True
    return False


# --- .amc file import ----------------------------------------------------------
def _convert_amc_line(line):
    parts = line.split()
    if not parts:
        return ""
    cmd = parts[0].lower()
    args = parts[1:]
    if cmd in ("keydown", "keyup") and args:
        try:
            sc = int(args[0])
        except ValueError:
            return f"{parts[0]} {args[0]}"
        vk = winapi.scancode_to_vk(sc)
        name = keys.name_from_vk(vk) if vk else None
        if name and not name.startswith("VK_"):
            return f"{'KeyDown' if cmd == 'keydown' else 'KeyUp'} {name}"
        return f"{'KeyDown' if cmd == 'keydown' else 'KeyUp'} sc:{sc}"
    if cmd == "delay" and args:
        return f"Delay {args[0]}"
    if _BUTTON_RE.match(cmd):
        return parts[0]
    if cmd in ("mover", "moverel") and len(args) >= 2:
        return f"MoveR {args[0]} {args[1]}"
    if cmd == "move" and len(args) >= 2:
        return f"MoveTo {args[0]} {args[1]}"
    if cmd in ("wheelup", "wheeldown"):
        return parts[0]
    return f"# (not converted) {line}"


def convert_amc_script(text):
    return "\n".join(_convert_amc_line(l.strip()) for l in text.splitlines() if l.strip())


def import_amc(path):
    """Reads an .amc file -> dict(name, description, on_press, on_release)."""
    tree = ET.parse(path)
    root = tree.getroot()
    node = root.find("DefaultMacro")
    if node is None:
        node = root

    def text_of(xpath):
        el = node.find(xpath)
        return (el.text or "").strip() if el is not None else ""

    return {
        "name": text_of("Major") or "Imported macro",
        "description": text_of("Description"),
        "on_press": convert_amc_script(text_of("KeyDown/Syntax")),
        "on_release": convert_amc_script(text_of("KeyUp/Syntax")),
    }


def test_run(on_press, on_release, delay_before=3.0):
    """Runs a test macro in a separate thread."""
    press_ops, release_ops = parse(on_press), parse(on_release)

    def worker():
        time.sleep(delay_before)
        runner = Runner()
        runner.run(press_ops)
        runner.run(release_ops)
        runner.release_all()

    threading.Thread(target=worker, daemon=True).start()
