"""GameTool — keyboard/mouse macros and crosshair/text overlay."""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

if sys.platform != "win32":
    sys.exit("GameTool only runs on Windows.")

from gametool import winapi  # noqa: E402
from gametool.gui import APP_NAME, App  # noqa: E402

ELEVATED_FLAG = "--elevated"


def ensure_admin():
    """If we are not administrator, restart the app elevated (UAC).

    Returns True if this process should go on, False if it should exit
    (the elevated instance was started or the user chose to quit).
    Needed because Windows doesn't let a non-elevated program read or send
    input to a game running as administrator.
    """
    if winapi.is_admin():
        return True
    args = [a for a in sys.argv[1:] if a != ELEVATED_FLAG]
    # if we already are the "elevated" instance but have no rights, don't retry forever
    if ELEVATED_FLAG not in sys.argv[1:]:
        script = os.path.abspath(sys.argv[0])
        params = subprocess.list2cmdline([script, *args, ELEVATED_FLAG])
        if winapi.run_as_admin(sys.executable, params, os.path.dirname(script)):
            return False
    root = tk.Tk()
    root.withdraw()
    go_on = messagebox.askyesno(
        APP_NAME,
        "GameTool is not running as administrator.\n\n"
        "Macros may not work in games that run as administrator.\n\n"
        "Continue anyway?",
        icon="warning", parent=root)
    root.destroy()
    return go_on


def main():
    if not ensure_admin():
        return
    winapi.enable_dpi_awareness()
    winapi.enable_high_res_timer()
    root = tk.Tk()
    try:
        App(root)
    except OSError as exc:
        messagebox.showerror(APP_NAME, f"Could not install the input hooks:\n{exc}")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
