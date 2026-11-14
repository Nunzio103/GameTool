"""Saves macros, profiles and settings to disk (JSON files in DATA_DIR)."""
import json
import re
from dataclasses import asdict, dataclass, field

from . import script
from .paths import DATA_DIR

MACRO_DIR = DATA_DIR / "macros"
PROFILE_DIR = DATA_DIR / "profiles"
SETTINGS_FILE = DATA_DIR / "settings.json"

MODES = {
    "once": "Once",
    "repeat": "Repeat N times",
    "hold": "Repeat while held",
    "toggle": "Toggle on/off",
}


@dataclass
class Macro:
    name: str
    description: str = ""
    on_press: str = ""
    on_release: str = ""


@dataclass
class Binding:
    trigger: str                 # e.g. "F1", "MouseX1"
    macro: str                   # macro name
    modifiers: list = field(default_factory=list)  # e.g. ["Ctrl", "Shift"]
    mode: str = "once"
    count: int = 1
    block: bool = True           # block the original key


@dataclass
class Profile:
    name: str
    process: str = ""            # if set, active only while this .exe is in the foreground
    bindings: list = field(default_factory=list)


def _safe_filename(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "senza_nome"


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class Store:
    def __init__(self):
        for d in (MACRO_DIR, PROFILE_DIR):
            d.mkdir(parents=True, exist_ok=True)
        self.settings = {"active_profile": "Profile 1", "incognito": False}
        self.settings.update(_read_json(SETTINGS_FILE, {}))
        # settings no longer used (global Start/Stop key, state at startup)
        for obsolete in ("master_hotkey", "enabled"):
            self.settings.pop(obsolete, None)
        self.macros = {}
        self.profiles = {}
        self._compiled = {}
        self._load()

    # --- loading ----------------------------------------------------------
    def _load(self):
        for path in sorted(MACRO_DIR.glob("*.json")):
            data = _read_json(path, None)
            if isinstance(data, dict) and data.get("name"):
                m = Macro(**{k: data.get(k, "") for k in ("name", "description", "on_press", "on_release")})
                self.macros[m.name] = m
        for path in sorted(PROFILE_DIR.glob("*.json")):
            data = _read_json(path, None)
            if isinstance(data, dict) and data.get("name"):
                bindings = [Binding(**b) for b in data.get("bindings", [])]
                self.profiles[data["name"]] = Profile(data["name"], data.get("process", ""), bindings)
        if not self.macros:
            self._create_examples()
        if not self.profiles:
            self.save_profile(Profile("Profile 1"))
        if self.settings["active_profile"] not in self.profiles:
            self.settings["active_profile"] = next(iter(self.profiles))

    def _create_examples(self):
        self.save_macro(Macro(
            "Example - Double click",
            "Fast left double click.",
            "LeftClick\nDelay 40\nLeftClick",
        ))
        self.save_macro(Macro(
            "Example - Rapid fire",
            "Use it with the 'Repeat while held' mode.",
            "LeftDown\nDelay 20-30\nLeftUp\nDelay 30-45",
        ))
        self.save_macro(Macro(
            "Example - Text",
            "Types a message.",
            'Text "Hi! Typed by GameTool"\nKeyPress Enter',
        ))

    def save_settings(self):
        _write_json(SETTINGS_FILE, self.settings)

    # --- macros ------------------------------------------------------------------
    def save_macro(self, macro, old_name=None):
        if old_name and old_name != macro.name:
            self.delete_macro(old_name)
            for profile in self.profiles.values():
                changed = False
                for b in profile.bindings:
                    if b.macro == old_name:
                        b.macro = macro.name
                        changed = True
                if changed:
                    self.save_profile(profile)
        self.macros[macro.name] = macro
        self._compiled.pop(macro.name, None)
        _write_json(MACRO_DIR / f"{_safe_filename(macro.name)}.json", asdict(macro))

    def delete_macro(self, name):
        self.macros.pop(name, None)
        self._compiled.pop(name, None)
        path = MACRO_DIR / f"{_safe_filename(name)}.json"
        if path.exists():
            path.unlink()

    def compiled(self, name):
        """(press_ops, release_ops) of the macro, or None. Cached."""
        if name in self._compiled:
            return self._compiled[name]
        macro = self.macros.get(name)
        if macro is None:
            return None
        try:
            result = (script.parse(macro.on_press), script.parse(macro.on_release))
        except script.ScriptError:
            result = None
        self._compiled[name] = result
        return result

    # --- profiles ----------------------------------------------------------------
    def save_profile(self, profile, old_name=None):
        if old_name and old_name != profile.name:
            self.delete_profile(old_name)
        self.profiles[profile.name] = profile
        data = {
            "name": profile.name,
            "process": profile.process,
            "bindings": [asdict(b) for b in profile.bindings],
        }
        _write_json(PROFILE_DIR / f"{_safe_filename(profile.name)}.json", data)

    def delete_profile(self, name):
        self.profiles.pop(name, None)
        path = PROFILE_DIR / f"{_safe_filename(name)}.json"
        if path.exists():
            path.unlink()

    @property
    def active_profile(self):
        return self.profiles[self.settings["active_profile"]]
