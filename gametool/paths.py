"""Paths: user data (macros, profiles, settings) and resources bundled with the app."""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # PyInstaller exe: resources are extracted to a temporary folder (_MEIPASS),
    # so data can't live there. It goes to %APPDATA%\GameTool, unless
    # there is a "data" folder next to the exe (portable mode).
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _portable = Path(sys.executable).parent / "data"
    DATA_DIR = _portable if _portable.is_dir() else Path(os.environ.get("APPDATA") or Path.home()) / "GameTool"
else:
    RESOURCE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = RESOURCE_DIR / "data"

FONTS_DIR = RESOURCE_DIR / "data" / "fonts"
