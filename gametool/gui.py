"""Graphical interface (tkinter): dark gaming-style theme, sidebar navigation."""
import copy
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from . import keys, overlay, script, winapi
from .engine import Engine
from .hooks import InputHook
from .paths import DATA_DIR, FONTS_DIR, RESOURCE_DIR
from .recorder import Recorder
from .storage import MODES, Binding, Macro, Profile, Store

APP_NAME = "GameTool"
ALL_WINDOWS = "(all windows)"
MODE_BY_LABEL = {label: key for key, label in MODES.items()}

# --- palette: dark + neon accents -----------------------------------------------
BG = "#0a0e15"          # page background
SIDEBAR = "#0d121b"     # sidebar, status bar, window title
CARD = "#121a26"        # cards
FIELD = "#0b1119"       # text fields, lists, tables
RAISED = "#1a2433"      # secondary buttons, table headings
HOVER = "#243149"
BORDER = "#22304a"
TEXT = "#e7eef8"
MUTED = "#8b98ad"
DIM = "#4d5b72"
ACCENT = "#00e1ff"      # neon cyan
ACCENT_HOVER = "#66efff"
ACCENT_PRESS = "#00b4cc"
ACCENT_DIM = "#0c3442"  # selection
ON_ACCENT = "#03121a"   # text on cyan background
VIOLET = "#9d7bff"
GREEN = "#2cff9e"
RED = "#ff3d6e"
RED_HOVER = "#ff6b91"
RED_PRESS = "#d92e5a"
RED_DIM = "#3a1220"
ORANGE = "#ffb648"
NAV_HOVER = "#131c29"
NAV_SELECTED = "#0e2230"

# --- fonts: Titillium Web if available, otherwise Segoe UI ------------------
UI_FONT = "Segoe UI"
UI_SEMIBOLD = ("Segoe UI Semibold",)
UI_SIZE = 10
SCALE = 1.0  # DPI factor (1.0 = 96 dpi)


def px(n):
    """Logical pixels -> real pixels according to the screen DPI."""
    return int(round(n * SCALE))


def load_fonts(root):
    """Loads the .ttf files in data/fonts (for this process only) and picks the font."""
    global UI_FONT, UI_SEMIBOLD, UI_SIZE
    if FONTS_DIR.is_dir():
        for ttf in FONTS_DIR.glob("*.ttf"):
            winapi.add_private_font(str(ttf))
    families = set(tkfont.families(root))
    if "Titillium Web" in families:
        UI_FONT = "Titillium Web"
        # Titillium is smaller than Segoe at the same point size
        UI_SIZE = 11
        UI_SEMIBOLD = (("Titillium Web SemiBold",) if "Titillium Web SemiBold" in families
                       else ("Titillium Web", "bold"))


def ui(size=0):
    return (UI_FONT, UI_SIZE + size)


def ui_semibold(size=0):
    family, *weight = UI_SEMIBOLD
    return (family, UI_SIZE + size, *weight)


def ui_bold(size=0):
    return (UI_FONT, UI_SIZE + size, "bold")


INCOGNITO_HELP = (
    "No system hooks: the keyboard and mouse are read by polling "
    "(GetAsyncKeyState / GetCursorPos).\n"
    "Limits: the original key always reaches the game (the \"Block\" option has no effect) "
    "and the mouse wheel can't be used as a trigger. Recording and \"Detect…\" work, "
    "but the pressed key isn't blocked.")


# =====================================================================================
# reusable widgets
# =====================================================================================
class Tooltip:
    """Small help box shown on mouse hover."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        if self._job is None:
            self._job = self.widget.after(400, self._show)

    def _show(self):
        self._job = None
        if self.tip is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.configure(background=ACCENT_DIM)
        tk.Label(self.tip, text=self.text, justify="left", background=RAISED, foreground=TEXT,
                 font=ui(-1), padx=10, pady=6, wraplength=px(340)).pack(padx=1, pady=1)
        self.tip.update_idletasks()
        # keep it on screen
        x = min(x, self.tip.winfo_screenwidth() - self.tip.winfo_reqwidth() - 8)
        self.tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class Switch(tk.Canvas):
    """Drawn on/off switch (easier to read than a checkbox)."""

    def __init__(self, parent, variable, command=None, background=CARD):
        self._sw, self._sh = px(42), px(22)
        super().__init__(parent, width=self._sw, height=self._sh, background=background,
                         highlightthickness=0, borderwidth=0, cursor="hand2")
        self.variable = variable
        self.command = command
        self.enabled = True
        self._hover = False
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        variable.trace_add("write", lambda *a: self._draw())
        self._draw()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self._draw()

    def _set_hover(self, hover):
        self._hover = hover
        self._draw()

    def _click(self, _event=None):
        if not self.enabled:
            return "break"
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
        return "break"

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        on = bool(self.variable.get())
        w, h = self._sw - 1, self._sh - 1
        if not self.enabled:
            track, knob = (ACCENT_DIM if on else RAISED), DIM
        elif on:
            track, knob = (ACCENT_HOVER if self._hover else ACCENT), ON_ACCENT
        else:
            track, knob = (HOVER if self._hover else RAISED), MUTED
        self.create_oval(0, 0, h, h, fill=track, outline=track)
        self.create_oval(w - h, 0, w, h, fill=track, outline=track)
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=track, outline=track)
        pad = max(2, px(3))
        d = h - 2 * pad
        x = w - pad - d if on else pad
        self.create_oval(x, pad, x + d, pad + d, fill=knob, outline=knob)


class NavItem(tk.Frame):
    """Sidebar entry."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, background=SIDEBAR, cursor="hand2")
        self.selected = False
        self.bar = tk.Frame(self, background=SIDEBAR, width=px(3))
        self.bar.pack(side="left", fill="y")
        self.icon = tk.Label(self, text=icon, background=SIDEBAR, foreground=DIM, font=ui(1),
                             width=2, anchor="center")
        self.icon.pack(side="left", padx=(px(12), px(6)), pady=px(5))
        self.label = tk.Label(self, text=text, background=SIDEBAR, foreground=MUTED,
                              font=ui_semibold(), anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self, self.icon, self.label):
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self._paint(True))
            w.bind("<Leave>", lambda e: self._paint(False))

    def set_selected(self, selected):
        self.selected = selected
        self._paint(False)

    def _paint(self, hover):
        if self.selected:
            bg, fg, icon, bar = NAV_SELECTED, TEXT, ACCENT, ACCENT
        elif hover:
            bg, fg, icon, bar = NAV_HOVER, TEXT, MUTED, NAV_HOVER
        else:
            bg, fg, icon, bar = SIDEBAR, MUTED, DIM, SIDEBAR
        self.configure(background=bg)
        self.bar.configure(background=bar)
        self.icon.configure(background=bg, foreground=icon)
        self.label.configure(background=bg, foreground=fg)


class Flow(tk.Frame):
    """Lays widgets out in a row and wraps when space runs out."""

    def __init__(self, parent, background=CARD, hgap=None, vgap=None):
        super().__init__(parent, background=background, height=1)
        self.hgap = px(8) if hgap is None else hgap
        self.vgap = px(8) if vgap is None else vgap
        self.items = []
        self._width = None
        self._job = None
        self.bind("<Configure>", self._on_configure)

    def add(self, widget, gap=None):
        self.items.append((widget, gap))
        widget.bind("<Configure>", lambda e: self.relayout(), add="+")
        self.relayout()
        return widget

    def relayout(self):
        if self._job is None:
            self._job = self.after_idle(self._layout)

    def _on_configure(self, event):
        if event.width != self._width:
            self._layout()

    def _layout(self):
        self._job = None
        if not self.winfo_exists():
            return
        width = self.winfo_width()
        self._width = width
        if width <= 1:
            width = 10 ** 6
        rows, row, x = [], [], 0
        for widget, gap in self.items:
            g = self.hgap if gap is None else gap
            rw = widget.winfo_reqwidth()
            if row and x + g + rw > width:
                rows.append(row)
                row, x = [], 0
            if row:
                x += g
            row.append((widget, x))
            x += rw
        if row:
            rows.append(row)
        y = 0
        for row in rows:
            rh = max(w.winfo_reqheight() for w, _ in row)
            for widget, x in row:
                widget.place(x=x, y=y + (rh - widget.winfo_reqheight()) // 2)
            y += rh + self.vgap
        height = max(1, y - self.vgap) if rows else 1
        if int(self.cget("height")) != height:
            self.configure(height=height)


class CardGrid(ttk.Frame):
    """Grid of cards: as many columns as fit, at least one."""

    def __init__(self, parent, min_width, gap=None):
        super().__init__(parent, style="Page.TFrame")
        self.min_width = min_width
        self.gap = px(14) if gap is None else gap
        self.cards = []
        self._cols = None
        self.bind("<Configure>", lambda e: self._layout())

    def add(self, card):
        self.cards.append(card)
        self._cols = None
        self._layout()
        return card

    def _layout(self):
        width = self.winfo_width()
        if width <= 1:
            width = self.min_width
        cols = max(1, min(len(self.cards), (width + self.gap) // (self.min_width + self.gap)))
        if cols == self._cols:
            return
        self._cols = cols
        for c in range(len(self.cards) + 1):
            self.columnconfigure(c, weight=0, uniform="")
        for c in range(cols):
            self.columnconfigure(c, weight=1, uniform="card")
        for i, card in enumerate(self.cards):
            r, c = divmod(i, cols)
            card.grid(row=r, column=c, sticky="nsew",
                      padx=(0 if c == 0 else self.gap, 0), pady=(0 if r == 0 else self.gap, 0))


class Scrollable(ttk.Frame):
    """Vertically scrollable area; the mouse wheel is handled by App._on_wheel."""

    def __init__(self, parent):
        super().__init__(parent, style="Page.TFrame")
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, borderwidth=0,
                                yscrollincrement=px(24))
        self.canvas.scrollable = True
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns", padx=(px(6), 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body = ttk.Frame(self.canvas, style="Page.TFrame")
        win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))


def wrap_label(parent, text, style="Muted.TLabel"):
    """Label that wraps to the available width."""
    lbl = ttk.Label(parent, text=text, style=style, justify="left", wraplength=px(300))
    lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(px(120), e.width)))
    return lbl


# =====================================================================================
# key capture and binding dialog
# =====================================================================================
class KeyCapture:
    """Captures the next key (or mouse button) pressed, with its modifiers.

    Works in the hook thread; the result is passed to `deliver`, which sends
    it back to the GUI thread.
    """

    def __init__(self, hook, deliver, on_done, allow_modifiers=True):
        self.hook = hook
        self.deliver = deliver
        self.on_done = on_done
        self.allow_modifiers = allow_modifiers
        self.done = False
        self.blocked = set()
        self.mods_down = []

    def start(self):
        self.hook.exclusive = self._handler

    def cancel(self):
        if self.hook.exclusive == self._handler:
            self.hook.exclusive = None

    def _finish(self, name, mods):
        self.done = True
        if not self.blocked:
            self.cancel()
        mods = sorted(mods) if self.allow_modifiers else []
        self.deliver(lambda: self.on_done(name, mods))

    def _handler(self, ev):
        if ev.ours or ev.kind == "move":
            return False
        name = ev.name
        if self.done:
            # block the release of the captured key, then free the hook
            if ev.kind == "up" and name in self.blocked:
                self.blocked.discard(name)
                if not self.blocked:
                    self.cancel()
                return True
            return False
        if ev.kind == "down":
            if name in keys.MODIFIER_KEYS:
                if name not in self.mods_down:
                    self.mods_down.append(name)
                return False
            if name not in keys.WHEEL_TRIGGERS:
                self.blocked.add(name)
            self._finish(name, keys.current_modifiers(exclude=name))
            return True
        # release of a modifier pressed on its own -> that is the chosen key
        if name in self.mods_down:
            if self.mods_down and self.mods_down[-1] == name:
                self._finish(name, keys.current_modifiers(exclude=name))
            else:
                self.mods_down.remove(name)
        return False


class BindingDialog(tk.Toplevel):
    def __init__(self, app, binding=None):
        super().__init__(app.root)
        self.app = app
        self.result = None
        self.capture = None
        self.title("Edit binding" if binding else "New binding")
        self.transient(app.root)
        self.resizable(False, False)
        b = binding or Binding(trigger="", macro="")
        self.configure(background=CARD)

        frm = ttk.Frame(self, padding=px(20))
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="Key", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 12))
        self.trigger_var = tk.StringVar(value=b.trigger)
        self.trigger_cb = ttk.Combobox(frm, textvariable=self.trigger_var, width=22,
                                       values=keys.all_trigger_names())
        self.trigger_cb.grid(row=0, column=1, sticky="we", pady=4)
        self.capture_btn = ttk.Button(frm, text="Detect…", style="Small.TButton", command=self._start_capture)
        self.capture_btn.grid(row=0, column=2, padx=(6, 0), pady=4)

        ttk.Label(frm, text="Modifiers", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 12))
        mods = ttk.Frame(frm)
        mods.grid(row=1, column=1, columnspan=2, sticky="w")
        self.mod_vars = {}
        for i, mod in enumerate(keys.MODIFIERS):
            var = tk.BooleanVar(value=mod in b.modifiers)
            ttk.Checkbutton(mods, text=mod, variable=var).grid(row=0, column=i, padx=(0, 8))
            self.mod_vars[mod] = var

        ttk.Label(frm, text="Macro", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 12))
        self.macro_var = tk.StringVar(value=b.macro)
        ttk.Combobox(frm, textvariable=self.macro_var, state="readonly", width=34,
                     values=sorted(app.store.macros)).grid(row=2, column=1, columnspan=2, sticky="we", pady=4)

        ttk.Label(frm, text="Mode", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 12))
        self.mode_var = tk.StringVar(value=MODES.get(b.mode, MODES["once"]))
        mode_cb = ttk.Combobox(frm, textvariable=self.mode_var, state="readonly", width=34,
                               values=list(MODES.values()))
        mode_cb.grid(row=3, column=1, columnspan=2, sticky="we", pady=4)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._update_count_state())

        ttk.Label(frm, text="Repeat count", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=4, padx=(0, 12))
        self.count_var = tk.IntVar(value=max(1, b.count))
        self.count_sb = ttk.Spinbox(frm, from_=1, to=100000, textvariable=self.count_var, width=8)
        self.count_sb.grid(row=4, column=1, sticky="w", pady=4)

        self.block_var = tk.BooleanVar(value=b.block)
        ttk.Checkbutton(frm, text="Block the original key (other apps don't receive it)",
                        variable=self.block_var).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 4))

        self.hint = ttk.Label(frm, text="", foreground=ORANGE)
        self.hint.grid(row=6, column=0, columnspan=3, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(btns, text="OK", style="Accent.TButton", command=self._ok).pack(side="right", padx=8)

        self._update_count_state()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.update_idletasks()
        root = app.root
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        winapi.style_title_bar(self, SIDEBAR)
        self.grab_set()
        self.trigger_cb.focus_set()

    def _update_count_state(self):
        state = "normal" if MODE_BY_LABEL.get(self.mode_var.get()) == "repeat" else "disabled"
        self.count_sb.configure(state=state)

    def _start_capture(self):
        self.capture_btn.configure(text="Press…", state="disabled")
        self.hint.configure(text="Press a key, a combination or a mouse button…")
        self.capture = KeyCapture(self.app.hook, self.app.call_soon, self._captured)
        self.capture.start()

    def _captured(self, name, mods):
        if not self.winfo_exists():
            return
        self.capture = None
        self.trigger_var.set(name)
        for mod, var in self.mod_vars.items():
            var.set(mod in mods)
        self.capture_btn.configure(text="Detect…", state="normal")
        self.hint.configure(text="")
        if name == "MouseLeft" and self.block_var.get():
            self.hint.configure(text="Warning: if you block the left click, you won't be able to click normally.")

    def _cancel(self):
        if self.capture:
            self.capture.cancel()
        self.destroy()

    def _ok(self):
        trigger = keys.canonical(self.trigger_var.get())
        if not trigger:
            messagebox.showerror(APP_NAME, "Invalid key.", parent=self)
            return
        if not self.macro_var.get():
            messagebox.showerror(APP_NAME, "Choose a macro.", parent=self)
            return
        try:
            count = int(self.count_var.get())
        except (tk.TclError, ValueError):
            count = 1
        self.result = Binding(
            trigger=trigger,
            macro=self.macro_var.get(),
            modifiers=sorted(m for m, v in self.mod_vars.items() if v.get()),
            mode=MODE_BY_LABEL.get(self.mode_var.get(), "once"),
            count=max(1, count),
            block=self.block_var.get(),
        )
        if self.capture:
            self.capture.cancel()
        self.destroy()


# =====================================================================================
# application
# =====================================================================================
class App:
    def __init__(self, root):
        global SCALE
        self.root = root
        SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.queue = queue.Queue()
        self.store = Store()
        self.hook = InputHook()
        # in incognito mode no hooks are installed, not even for a moment at startup
        self.hook.start(stealth=bool(self.store.settings.get("incognito")))
        self.engine = Engine(self.store, self.hook, notify=self._engine_notify)
        self.recorder = None
        self.current_macro = None
        self._validate_job = None
        self._last_power = 0.0
        self._incognito_busy = False
        self._editor_layout = None
        self._ov_hk_capture = None
        self._ov_save_job = None
        self._ov_hints = []
        # crosshair/text overlay: starts off, the user turns it on
        self.ov_settings = overlay.load_settings()
        self._ov_loading = True
        self.overlay = overlay.Overlay(self.ov_settings, on_hotkey=self._on_overlay_hotkey)
        self.overlay.start()

        root.title(APP_NAME)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(px(1200), int(sw * 0.92)), min(px(780), int(sh * 0.88))
        root.geometry(f"{width}x{height}")
        root.minsize(min(px(860), width), min(px(620), height))
        root.configure(background=BG)
        self._set_icon()
        self._setup_style()
        self._create_vars()
        self._build_ui()
        root.update_idletasks()
        winapi.style_title_bar(root, SIDEBAR)
        self._ov_load_all()
        self._ov_loading = False
        self._ov_update_preview()
        self._refresh_profiles()
        self._refresh_macro_list()
        self._update_status()
        self._update_incognito()
        self._update_ov_hints()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind_all("<Control-s>", lambda e: self.save_macro())
        root.bind_all("<MouseWheel>", self._on_wheel)
        self._poll()
        self.root.after(1000, self._watchdog)

    # --- infrastructure -----------------------------------------------------------
    def call_soon(self, fn):
        """Runs fn in the GUI thread (can be called from any thread)."""
        self.queue.put(fn)

    def _poll(self):
        try:
            while True:
                self.queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        self.root.after(30, self._poll)

    def _watchdog(self):
        """Checks every second that Windows hasn't removed the input hooks."""
        try:
            if not self._incognito_busy:
                if self.hook.check_alive():
                    self.engine.reset_input_state()
                    self.set_status("⚠  Windows had turned off key input: restored", error=True)
                self.hook.prune_user_keys()
        except Exception:
            traceback.print_exc()
        self.root.after(1000, self._watchdog)

    def _engine_notify(self, kind, data):
        self.call_soon(lambda: self._on_engine(kind, data))

    def _on_engine(self, kind, data):
        if kind == "enabled":
            self._update_status()
            self.set_status("Macros on" if data else "Macros off")
        elif kind == "run":
            self.set_status(f"▶  {data.macro}   ({data.trigger_label()})")
        elif kind == "stopped":
            self.set_status(f"■  {data.macro} stopped")
        elif kind == "error":
            self.set_status(f"⚠  {data}", error=True)

    def _on_wheel(self, event):
        """Mouse wheel over scrollable areas (lists and editors scroll by themselves)."""
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        if widget is None or widget.winfo_class() in ("Text", "Listbox", "Treeview", "TCombobox", "TSpinbox"):
            return
        while widget is not None:
            if getattr(widget, "scrollable", False):
                first, last = widget.yview()
                if first > 0 or last < 1:
                    steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
                    widget.yview_scroll(steps, "units")
                return
            widget = widget.master

    def _set_icon(self):
        """Window icon: assets/icon.ico, or a diamond drawn on the fly."""
        ico = RESOURCE_DIR / "assets" / "icon.ico"
        if ico.is_file():
            # in the exe iconphoto is not enough: Tk falls back to the default icon (the feather)
            self.root.iconbitmap(str(ico))
            self.root.iconbitmap(default=str(ico))
            return
        size = 32
        self._icon = tk.PhotoImage(width=size, height=size)
        c = (size - 1) / 2
        for y in range(size):
            for x in range(size):
                d = abs(x - c) + abs(y - c)
                color = ACCENT_PRESS if d <= 6 else ACCENT if d <= 14 else None
                if color:
                    self._icon.put(color, (x, y))
        self.root.iconphoto(True, self._icon)

    # --- style -------------------------------------------------------------------
    def _setup_style(self):
        load_fonts(self.root)
        default = tkfont.nametofont("TkDefaultFont")
        default.configure(family=UI_FONT, size=UI_SIZE)
        tkfont.nametofont("TkTextFont").configure(family=UI_FONT, size=UI_SIZE)
        self.mono = tkfont.Font(family="Consolas", size=11)
        self.mono_small = tkfont.Font(family="Consolas", size=9)
        semibold = ui_semibold()

        root = self.root
        # combobox drop-down lists (they are classic tk widgets)
        root.option_add("*TCombobox*Listbox.background", FIELD)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
        root.option_add("*TCombobox*Listbox.selectForeground", ACCENT)
        root.option_add("*TCombobox*Listbox.font", ui())
        root.option_add("*TCombobox*Listbox.borderWidth", 0)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=CARD, foreground=TEXT, fieldbackground=FIELD,
                        bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, troughcolor=CARD,
                        selectbackground=ACCENT_DIM, selectforeground=TEXT, insertcolor=ACCENT,
                        focuscolor=ACCENT, arrowcolor=MUTED, font=ui())
        style.map(".", foreground=[("disabled", DIM)])

        # containers and labels (inside cards by default)
        style.configure("TFrame", background=CARD)
        style.configure("Page.TFrame", background=BG)
        style.configure("TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
        style.configure("Field.TLabel", background=CARD, foreground=MUTED, font=semibold)
        style.configure("Section.TLabel", background=CARD, foreground=ACCENT, font=ui_bold(-2))
        style.configure("Ok.TLabel", background=CARD, foreground=GREEN)
        style.configure("Error.TLabel", background=CARD, foreground=RED)
        style.configure("PageTitle.TLabel", background=BG, foreground=TEXT, font=ui_bold(9))
        style.configure("PageSub.TLabel", background=BG, foreground=MUTED, font=ui(-1))
        style.configure("TSeparator", background=BORDER)

        # buttons
        def button(name, bg, hover, press, fg, border, font=semibold, padding=(px(14), px(6)),
                   disabled_bg=CARD, fg_hover=None):
            style.configure(name, background=bg, foreground=fg, bordercolor=border,
                            lightcolor=bg, darkcolor=bg, focuscolor=bg, padding=padding,
                            font=font, relief="flat", borderwidth=1, anchor="center", width=0)
            style.map(name,
                      background=[("disabled", disabled_bg), ("pressed", press), ("active", hover)],
                      lightcolor=[("disabled", disabled_bg), ("pressed", press), ("active", hover)],
                      darkcolor=[("disabled", disabled_bg), ("pressed", press), ("active", hover)],
                      focuscolor=[("pressed", press), ("active", hover)],
                      bordercolor=[("disabled", BORDER), ("focus", ACCENT), ("active", hover)],
                      foreground=[("disabled", DIM), ("active", fg_hover or fg)])

        button("TButton", RAISED, HOVER, ACCENT_DIM, TEXT, BORDER)
        button("Accent.TButton", ACCENT, ACCENT_HOVER, ACCENT_PRESS, ON_ACCENT, ACCENT)
        button("Danger.TButton", RED_DIM, RED_PRESS, RED, RED, RED, fg_hover="white")
        button("Small.TButton", RAISED, HOVER, ACCENT_DIM, TEXT, BORDER, padding=(px(10), px(3)))
        button("SmallAccent.TButton", ACCENT, ACCENT_HOVER, ACCENT_PRESS, ON_ACCENT, ACCENT,
               padding=(px(10), px(3)))
        button("SmallOn.TButton", ACCENT_DIM, HOVER, ACCENT_DIM, ACCENT, ACCENT, padding=(px(10), px(3)))
        button("Power.TButton", ACCENT, ACCENT_HOVER, ACCENT_PRESS, ON_ACCENT, ACCENT,
               font=ui_bold(2), padding=(px(12), px(8)))
        button("Power.Danger.TButton", RED, RED_HOVER, RED_PRESS, "white", RED,
               font=ui_bold(2), padding=(px(12), px(8)))

        # fields
        field_common = dict(fieldbackground=FIELD, foreground=TEXT, bordercolor=BORDER,
                            lightcolor=FIELD, darkcolor=FIELD, insertcolor=ACCENT, padding=px(5))
        style.configure("TEntry", **field_common)
        style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  fieldbackground=[("readonly", FIELD), ("disabled", CARD)])
        style.configure("TCombobox", **field_common, background=FIELD, arrowcolor=MUTED,
                        selectbackground=FIELD, selectforeground=TEXT, arrowsize=px(13))
        style.map("TCombobox",
                  fieldbackground=[("readonly", FIELD), ("disabled", CARD)],
                  background=[("active", RAISED), ("pressed", HOVER)],
                  arrowcolor=[("active", ACCENT)],
                  bordercolor=[("focus", ACCENT), ("active", HOVER)],
                  lightcolor=[("focus", ACCENT)])
        style.configure("TSpinbox", **field_common, background=FIELD, arrowcolor=MUTED, arrowsize=px(11))
        style.map("TSpinbox",
                  fieldbackground=[("disabled", CARD)],
                  background=[("active", RAISED)],
                  arrowcolor=[("disabled", DIM), ("active", ACCENT)],
                  bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])

        for name in ("TCheckbutton", "TRadiobutton"):
            style.configure(name, background=CARD, foreground=TEXT, indicatorbackground=FIELD,
                            indicatorforeground=ON_ACCENT, upperbordercolor=DIM,
                            lowerbordercolor=DIM, indicatormargin=(0, 0, px(6), 0), padding=(2, 2))
            style.map(name,
                      background=[("active", CARD)],
                      foreground=[("disabled", DIM), ("active", ACCENT)],
                      indicatorbackground=[("selected", ACCENT), ("active", RAISED)],
                      upperbordercolor=[("selected", ACCENT), ("active", ACCENT)],
                      lowerbordercolor=[("selected", ACCENT), ("active", ACCENT)])

        # table
        rowheight = default.metrics("linespace") + px(14)
        style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD, rowheight=rowheight,
                        borderwidth=0)
        style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", ACCENT)])
        style.configure("Treeview.Heading", background=RAISED, foreground=MUTED,
                        bordercolor=BORDER, lightcolor=RAISED, darkcolor=RAISED,
                        relief="flat", padding=(px(10), px(6)), font=ui_bold(-2))
        style.map("Treeview.Heading", background=[("active", HOVER)], lightcolor=[("active", HOVER)],
                  darkcolor=[("active", HOVER)], foreground=[("active", TEXT)])

        # thin scrollbars, without arrows
        for orient in ("Vertical", "Horizontal"):
            name = f"{orient}.TScrollbar"
            style.layout(name, [(f"{orient}.Scrollbar.trough", {
                "sticky": "nswe",
                "children": [(f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
            })])
            style.configure(name, troughcolor=FIELD, background=RAISED, bordercolor=FIELD,
                            lightcolor=RAISED, darkcolor=RAISED, gripcount=0, arrowsize=px(8))
            style.map(name, background=[("pressed", ACCENT), ("active", HOVER)],
                      lightcolor=[("pressed", ACCENT), ("active", HOVER)],
                      darkcolor=[("pressed", ACCENT), ("active", HOVER)])

    # --- UI construction -------------------------------------------------------------
    def _create_vars(self):
        self.ov_on_var = tk.BooleanVar(value=False)
        self.incognito_var = tk.BooleanVar(value=self.hook.stealth)
        self.ov_on_var.trace_add("write", lambda *a: self._update_ov_hints())

    def _build_ui(self):
        bar = tk.Frame(self.root, background=SIDEBAR)
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, background=BORDER, height=1).pack(fill="x")
        self.statusbar = tk.Label(bar, text="Ready", anchor="w", background=SIDEBAR, foreground=MUTED,
                                  font=ui(-1), padx=px(14), pady=px(4))
        self.statusbar.pack(fill="x")

        main = tk.Frame(self.root, background=BG)
        main.pack(fill="both", expand=True)
        main.columnconfigure(2, weight=1)
        main.rowconfigure(0, weight=1)
        self._build_sidebar(main)
        tk.Frame(main, background=BORDER, width=1).grid(row=0, column=1, sticky="ns")
        self.content = tk.Frame(main, background=BG)
        self.content.grid(row=0, column=2, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.pages = {}
        self._build_bindings_page()
        self._build_macro_page()
        self._build_crosshair_page()
        self._build_texts_page()
        self._build_settings_page()
        self.show_page("bindings")

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, background=SIDEBAR, width=px(236))
        side.grid(row=0, column=0, sticky="ns")
        side.pack_propagate(False)

        brand = tk.Frame(side, background=SIDEBAR)
        brand.pack(fill="x", padx=px(18), pady=(px(14), px(10)))
        tk.Label(brand, text="◆", background=SIDEBAR, foreground=ACCENT,
                 font=(UI_FONT, 22, "bold")).pack(side="left", padx=(0, px(10)))
        names = tk.Frame(brand, background=SIDEBAR)
        names.pack(side="left")
        tk.Label(names, text="GAMETOOL", background=SIDEBAR, foreground=TEXT,
                 font=ui_bold(5)).pack(anchor="w")
        tk.Label(names, text="MACROS  ·  CROSSHAIR  ·  OVERLAY", background=SIDEBAR, foreground=DIM,
                 font=ui_bold(-4)).pack(anchor="w")

        # control panel: status, Start/Stop, global switches
        self.control = tk.Frame(side, background=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.control.pack(fill="x", padx=px(14))
        ctl = tk.Frame(self.control, background=CARD)
        ctl.pack(fill="x", padx=px(12), pady=px(10))
        self.status_lbl = tk.Label(ctl, text="", background=CARD, font=ui_bold(-1), anchor="w")
        self.status_lbl.pack(fill="x")
        self.profile_lbl = tk.Label(ctl, text="", background=CARD, foreground=MUTED, font=ui(-2), anchor="w")
        self.profile_lbl.pack(fill="x", pady=(0, px(8)))
        self.power_btn = ttk.Button(ctl, text="", style="Power.TButton", command=self.toggle_enabled)
        self.power_btn.pack(fill="x")
        Tooltip(self.power_btn, "Turns all macros on or off.\n\nMacros never fire while GameTool is "
                                "in the foreground, so you can always come back here and press Stop.")
        tk.Frame(ctl, background=BORDER, height=1).pack(fill="x", pady=px(10))
        row, self.ov_switch = self._switch_row(ctl, "Overlay", self.ov_on_var, self._ov_toggle)
        row.pack(fill="x")
        Tooltip(row, "Shows or hides the crosshair and text over the game. Always off at startup.")
        row, self.inc_switch = self._switch_row(ctl, "Incognito", self.incognito_var, self.toggle_incognito)
        row.pack(fill="x", pady=(px(8), 0))
        Tooltip(row, INCOGNITO_HELP)

        nav = tk.Frame(side, background=SIDEBAR)
        nav.pack(fill="x", pady=(px(10), 0))
        self.nav_items = {}
        sections = (
            ("MACROS", (("bindings", "⌨", "Key bindings"), ("macros", "✎", "Macro editor"))),
            ("OVERLAY", (("crosshair", "⊕", "Crosshair"), ("texts", "Aa", "On-screen text"))),
            ("SYSTEM", (("settings", "⚙", "Settings"),)),
        )
        for title, items in sections:
            tk.Label(nav, text=title, background=SIDEBAR, foreground=DIM, font=ui_bold(-3),
                     anchor="w").pack(fill="x", padx=px(18), pady=(px(6), 0))
            for key, icon, text in items:
                item = NavItem(nav, icon, text, lambda k=key: self.show_page(k))
                item.pack(fill="x")
                self.nav_items[key] = item

    def _switch_row(self, parent, text, var, command, background=CARD):
        row = tk.Frame(parent, background=background)
        tk.Label(row, text=text, background=background, foreground=TEXT, font=ui_semibold()).pack(side="left")
        sw = Switch(row, var, command, background=background)
        sw.pack(side="right")
        return row, sw

    def _page(self, key, title, subtitle):
        page = ttk.Frame(self.content, style="Page.TFrame", padding=(px(24), px(18), px(24), px(16)))
        page.grid(row=0, column=0, sticky="nsew")
        head = ttk.Frame(page, style="Page.TFrame")
        head.pack(fill="x", pady=(0, px(14)))
        # actions are packed first: when space runs out the title shrinks, not them
        actions = ttk.Frame(head, style="Page.TFrame")
        actions.pack(side="right", anchor="s", padx=(px(12), 0))
        titles = ttk.Frame(head, style="Page.TFrame")
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text=title.upper(), style="PageTitle.TLabel").pack(anchor="w")
        tk.Frame(titles, background=ACCENT, height=px(2), width=px(40)).pack(anchor="w", pady=(0, px(4)))
        sub = ttk.Label(titles, text=subtitle, style="PageSub.TLabel", wraplength=px(420))
        sub.pack(anchor="w", fill="x")
        sub.bind("<Configure>", lambda e: sub.configure(wraplength=max(px(160), e.width)))
        self.pages[key] = page
        return page, actions

    def _card(self, parent, title=None, accent=ACCENT):
        outer = tk.Frame(parent, background=CARD, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BORDER, borderwidth=0)
        outer.actions = None
        if title:
            head = tk.Frame(outer, background=CARD)
            head.pack(fill="x", padx=px(14), pady=(px(12), px(2)))
            outer.actions = tk.Frame(head, background=CARD)
            outer.actions.pack(side="right")
            tk.Frame(head, background=accent, width=px(3), height=px(15)).pack(side="left", padx=(0, px(8)))
            tk.Label(head, text=title.upper(), background=CARD, foreground=TEXT,
                     font=ui_bold(-1)).pack(side="left")
        outer.body = ttk.Frame(outer, padding=(px(14), px(8), px(14), px(14)))
        outer.body.pack(fill="both", expand=True)
        return outer

    def show_page(self, key):
        self.pages[key].tkraise()
        for k, item in self.nav_items.items():
            item.set_selected(k == key)

    # --- small form builders ----------------------------------------------------
    def _form(self, parent):
        form = ttk.Frame(parent)
        form.columnconfigure(1, weight=1)
        form.next_row = 0
        return form

    def _form_row(self, form, label, widget, sticky="w"):
        r = form.next_row
        form.next_row += 1
        ttk.Label(form, text=label, style="Muted.TLabel").grid(row=r, column=0, sticky="w",
                                                               pady=px(3), padx=(0, px(12)))
        widget.grid(row=r, column=1, sticky=sticky, pady=px(3))
        return widget

    def _spin(self, parent, var, lo, hi, width=6):
        return ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=width)

    def _color_field(self, parent, var):
        """Hex field with a color swatch that opens the color picker."""
        frame = ttk.Frame(parent)
        ttk.Entry(frame, textvariable=var, width=9).pack(side="left")
        swatch = tk.Label(frame, width=3, background="#000000", cursor="hand2",
                          highlightthickness=1, highlightbackground=BORDER)
        swatch.pack(side="left", fill="y", padx=(px(6), 0))

        def refresh(*_):
            h = var.get().strip().lstrip("#")
            if len(h) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in h):
                swatch.configure(background="#" + h)

        def pick(_event=None):
            h = var.get().strip()
            try:
                result = colorchooser.askcolor(color=h if h.startswith("#") else "#" + h,
                                               parent=self.root, title="Pick a color")
            except tk.TclError:
                result = colorchooser.askcolor(parent=self.root, title="Pick a color")
            if result and result[1]:
                var.set(result[1].upper())

        var.trace_add("write", refresh)
        swatch.bind("<Button-1>", pick)
        Tooltip(swatch, "Click to pick a color")
        refresh()
        return frame

    # --- page: key bindings ------------------------------------------------------
    def _build_bindings_page(self):
        page, _ = self._page("bindings", "Key bindings",
                             "Link a key, a key combination or a mouse button to a macro. "
                             "Each profile has its own bindings.")

        pc = self._card(page, "Profile", accent=VIOLET)
        pc.pack(fill="x")
        flow = Flow(pc.body)
        flow.pack(fill="x")
        self.profile_var = tk.StringVar()
        self.profile_cb = flow.add(ttk.Combobox(flow, textvariable=self.profile_var, state="readonly", width=22))
        self.profile_cb.bind("<<ComboboxSelected>>", lambda e: self.select_profile(self.profile_var.get()))
        flow.add(ttk.Button(flow, text="＋ New", style="Small.TButton", command=self.new_profile))
        flow.add(ttk.Button(flow, text="Rename", style="Small.TButton", command=self.rename_profile))
        flow.add(ttk.Button(flow, text="Delete", style="Small.TButton", command=self.delete_profile))
        lbl = flow.add(ttk.Label(flow, text="Active only in  ⓘ", style="Field.TLabel"), gap=px(24))
        self.process_var = tk.StringVar()
        self.process_cb = flow.add(ttk.Combobox(flow, textvariable=self.process_var, width=24,
                                                postcommand=self._refresh_process_list))
        self.process_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_process())
        self.process_cb.bind("<Return>", lambda e: self.apply_process())
        self.process_cb.bind("<FocusOut>", lambda e: self.apply_process())
        process_help = ("Macros only work while this program is in the foreground. "
                        "Open the list to choose among the running programs (start the game first), "
                        "or type the name of the .exe.")
        Tooltip(lbl, process_help)
        Tooltip(self.process_cb, process_help)

        tc = self._card(page, "Assigned keys")
        tc.pack(fill="both", expand=True, pady=(px(14), 0))
        ttk.Button(tc.actions, text="Remove", style="Small.TButton",
                   command=self.remove_binding).pack(side="right", padx=(px(6), 0))
        ttk.Button(tc.actions, text="Edit…", style="Small.TButton",
                   command=self.edit_binding).pack(side="right", padx=(px(6), 0))
        ttk.Button(tc.actions, text="＋ Add…", style="SmallAccent.TButton",
                   command=self.add_binding).pack(side="right")

        body = tc.body
        cols = ("trigger", "macro", "mode", "block")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for col, text, width in (("trigger", "KEY", 150), ("macro", "MACRO", 230),
                                 ("mode", "MODE", 190), ("block", "BLOCK ORIGINAL", 120)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=px(width), minwidth=px(70), anchor="w", stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("missing", foreground=ORANGE)
        self.tree.bind("<Double-1>", lambda e: self.edit_binding())
        self.tree.bind("<Delete>", lambda e: self.remove_binding())
        self.bindings_hint = ttk.Label(body, text="", style="Muted.TLabel")
        self.bindings_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(8), 0))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

    # --- page: macro editor ------------------------------------------------------
    def _build_macro_page(self):
        page, actions = self._page("macros", "Macro editor",
                                   "Type the commands yourself or record the keyboard and mouse. "
                                   "Ctrl+S saves.")
        ttk.Button(actions, text="Save", style="Accent.TButton", command=self.save_macro).pack(side="right")
        ttk.Button(actions, text="▶  Test (3 s)", command=self.test_macro).pack(side="right", padx=(0, px(8)))

        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # macro list
        lc = self._card(body, "Your macros", accent=VIOLET)
        lc.grid(row=0, column=0, sticky="nsw", padx=(0, px(14)))
        box = tk.Frame(lc.body, background=FIELD, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=ACCENT)
        box.pack(fill="both", expand=True)
        self.macro_list = tk.Listbox(
            box, width=22, exportselection=False, activestyle="none", font=ui(),
            background=FIELD, foreground=TEXT, selectbackground=ACCENT_DIM, selectforeground=ACCENT,
            borderwidth=0, relief="flat", highlightthickness=0)
        lsb = ttk.Scrollbar(box, orient="vertical", command=self.macro_list.yview)
        lsb.pack(side="right", fill="y")
        self.macro_list.pack(side="left", fill="both", expand=True, padx=px(4), pady=px(4))
        self.macro_list.configure(yscrollcommand=lsb.set)
        self.macro_list.bind("<<ListboxSelect>>", lambda e: self._on_macro_select())
        lb = ttk.Frame(lc.body)
        lb.pack(fill="x", pady=(px(10), 0))
        for i, (text, cmd, st) in enumerate((("＋ New", self.new_macro, "SmallAccent.TButton"),
                                             ("Duplicate", self.duplicate_macro, "Small.TButton"),
                                             ("Delete", self.delete_macro, "Small.TButton"),
                                             ("Import .amc…", self.import_amc, "Small.TButton"))):
            ttk.Button(lb, text=text, command=cmd, style=st).grid(
                row=i // 2, column=i % 2, sticky="we", padx=px(2), pady=px(2))
        lb.columnconfigure((0, 1), weight=1)

        # editor
        ec = self._card(body, "Selected macro")
        ec.grid(row=0, column=1, sticky="nsew")
        self.help_var = tk.BooleanVar(value=True)
        self.help_btn = ttk.Button(ec.actions, text="?  Commands", style="SmallOn.TButton",
                                   command=self._toggle_help)
        self.help_btn.pack(side="right")
        editor = ec.body

        meta = ttk.Frame(editor)
        meta.pack(fill="x")
        ttk.Label(meta, text="Name", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.name_var).grid(row=0, column=1, sticky="we", padx=(px(10), 0), pady=px(2))
        ttk.Label(meta, text="Description", style="Field.TLabel").grid(row=1, column=0, sticky="w")
        self.desc_var = tk.StringVar()
        ttk.Entry(meta, textvariable=self.desc_var).grid(row=1, column=1, sticky="we", padx=(px(10), 0), pady=px(2))
        meta.columnconfigure(1, weight=1)

        rec = Flow(editor)
        rec.pack(fill="x", pady=(px(10), px(10)))
        self.rec_btn = rec.add(ttk.Button(rec, text="●  Record", style="Danger.TButton",
                                          command=self.toggle_recording))
        self.rec_target = tk.StringVar(value="press")
        rec.add(ttk.Label(rec, text="into", style="Muted.TLabel"), gap=px(12))
        rec.add(ttk.Radiobutton(rec, text="Press", value="press", variable=self.rec_target))
        rec.add(ttk.Radiobutton(rec, text="Release", value="release", variable=self.rec_target))
        self.rec_delays = tk.BooleanVar(value=True)
        self.rec_moves = tk.BooleanVar(value=False)
        rec.add(ttk.Checkbutton(rec, text="Delays", variable=self.rec_delays), gap=px(18))
        rec.add(ttk.Checkbutton(rec, text="Mouse movement", variable=self.rec_moves))

        self.editor_body = ttk.Frame(editor)
        self.editor_body.pack(fill="both", expand=True)
        self.editor_body.columnconfigure(0, weight=1)
        self.press_frame, self.press_text = self._editor_section(self.editor_body, "When the key is pressed")
        self.release_frame, self.release_text = self._editor_section(self.editor_body, "When the key is released")

        self.help_frame = ttk.Frame(self.editor_body)
        ttk.Label(self.help_frame, text="COMMANDS", style="Section.TLabel").pack(anchor="w", pady=(0, px(4)))
        help_box = tk.Frame(self.help_frame, background=FIELD, highlightthickness=1, highlightbackground=BORDER)
        help_box.pack(fill="both", expand=True)
        # height=1: grows with the card without taking space from the editors
        help_text = tk.Text(help_box, width=41, height=1, wrap="none", font=self.mono_small,
                            background=FIELD, foreground=MUTED, relief="flat", borderwidth=0,
                            highlightthickness=0, padx=px(8), pady=px(6), cursor="arrow")
        help_text.insert("1.0", script.SYNTAX_HELP)
        help_text.configure(state="disabled")
        help_text.pack(fill="both", expand=True)
        self.editor_body.bind("<Configure>", lambda e: self._layout_macro_editor())

        self.error_lbl = ttk.Label(editor, text="", anchor="w")
        self.error_lbl.pack(fill="x", pady=(px(8), 0))
        self._layout_macro_editor()

    def _editor_section(self, parent, title):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text=title.upper(), style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, px(4)))
        text = self._make_editor(frame)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        return frame, text

    def _toggle_help(self):
        self.help_var.set(not self.help_var.get())
        self.help_btn.configure(style="SmallOn.TButton" if self.help_var.get() else "Small.TButton")
        self._layout_macro_editor()

    def _layout_macro_editor(self):
        """Command help on the right if there is room, otherwise below the editors."""
        width = self.editor_body.winfo_width()
        wide = width <= 1 or width >= px(620)
        key = (wide, self.help_var.get())
        if key == self._editor_layout:
            return
        self._editor_layout = key
        eb = self.editor_body
        self.press_frame.grid(row=0, column=0, sticky="nsew")
        self.release_frame.grid(row=1, column=0, sticky="nsew", pady=(px(10), 0))
        eb.rowconfigure(0, weight=3)
        eb.rowconfigure(1, weight=2)
        if not self.help_var.get():
            self.help_frame.grid_remove()
            eb.rowconfigure(2, weight=0)
        elif wide:
            self.help_frame.grid(row=0, column=1, rowspan=2, columnspan=1, sticky="nsew",
                                 padx=(px(12), 0), pady=0)
            eb.rowconfigure(2, weight=0)
        else:
            self.help_frame.grid(row=2, column=0, rowspan=1, columnspan=1, sticky="nsew",
                                 padx=0, pady=(px(10), 0))
            eb.rowconfigure(2, weight=2)

    # --- page: crosshair ----------------------------------------------------------
    def _overlay_hint(self, page, before):
        lbl = tk.Label(page, text="", background=BG, foreground=ORANGE, font=ui(-1),
                       anchor="w", justify="left")
        self._ov_hints.append((lbl, before))
        return lbl

    def _update_ov_hints(self):
        on = self.ov_on_var.get()
        hk = overlay.hotkey_name(self.ov_settings.hotkey_all)
        text = ("◉  The overlay is off: turn it on with the \"Overlay\" switch in the sidebar"
                + (f" or with the {hk} key." if self.ov_settings.hotkey_all else "."))
        for lbl, before in self._ov_hints:
            if on:
                lbl.pack_forget()
            else:
                lbl.configure(text=text)
                lbl.pack(fill="x", pady=(0, px(10)), before=before)

    def _build_crosshair_page(self):
        page, actions = self._page("crosshair", "Crosshair",
                                   "A crosshair that stays on top of the game. "
                                   "Changes apply right away and are saved automatically.")
        ttk.Button(actions, text="Restore defaults", style="Small.TButton",
                   command=self._ov_reset).pack(side="right")
        sc = Scrollable(page)
        self._overlay_hint(page, sc)
        sc.pack(fill="both", expand=True)
        grid = CardGrid(sc.body, px(310))
        grid.pack(fill="x")

        # variables
        self.ov_vis = tk.BooleanVar()
        self.ov_style_var = tk.StringVar()
        self.ov_color = tk.StringVar()
        self.ov_opacity = tk.IntVar()
        self.ov_image = tk.StringVar()
        self.ov_scale = tk.IntVar()
        self.ov_size = tk.IntVar()
        self.ov_thick = tk.IntVar()
        self.ov_gap = tk.IntVar()
        self.ov_dot = tk.IntVar()
        self.ov_outline = tk.BooleanVar()
        self.ov_outline_color = tk.StringVar()
        self.ov_outline_w = tk.IntVar()
        self.ov_offx = tk.IntVar()
        self.ov_offy = tk.IntVar()

        # preview
        c = grid.add(self._card(grid, "Preview"))
        self.ov_preview = tk.Label(c.body, background=FIELD, highlightthickness=1, highlightbackground=BORDER)
        self.ov_preview.pack(pady=(0, px(10)))
        row, _ = self._switch_row(c.body, "Show crosshair", self.ov_vis, self._ov_changed)
        row.pack(fill="x")
        f = ttk.Frame(c.body)
        f.pack(fill="x", pady=(px(8), 0))
        ttk.Label(f, text="Style", style="Muted.TLabel").pack(side="left", padx=(0, px(10)))
        ttk.Combobox(f, textvariable=self.ov_style_var, state="readonly", width=20,
                     values=overlay.STYLES).pack(side="left", fill="x", expand=True)

        # look
        c = grid.add(self._card(grid, "Look"))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Color", self._color_field(form, self.ov_color))
        self._form_row(form, "Opacity %", self._spin(form, self.ov_opacity, 5, 100))
        img = ttk.Frame(form)
        ttk.Entry(img, textvariable=self.ov_image, width=12).pack(side="left", fill="x", expand=True)
        ttk.Button(img, text="…", style="Small.TButton", command=self._ov_pick_image).pack(side="left", padx=(px(4), 0))
        self._form_row(form, "PNG image", img, sticky="we")
        self._form_row(form, "Image scale %", self._spin(form, self.ov_scale, 10, 1000))

        # shape
        c = grid.add(self._card(grid, "Shape"))
        form = self._form(c.body)
        form.pack(fill="x")
        for label, var, lo, hi in (("Length / radius", self.ov_size, 0, 400),
                                   ("Thickness", self.ov_thick, 1, 50),
                                   ("Gap from center", self.ov_gap, 0, 300),
                                   ("Dot size", self.ov_dot, 1, 50)):
            self._form_row(form, label, self._spin(form, var, lo, hi))

        # outline
        c = grid.add(self._card(grid, "Outline"))
        row, _ = self._switch_row(c.body, "Outline on", self.ov_outline, self._ov_changed)
        row.pack(fill="x", pady=(0, px(6)))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Color", self._color_field(form, self.ov_outline_color))
        self._form_row(form, "Thickness", self._spin(form, self.ov_outline_w, 1, 10))

        # position
        c = grid.add(self._card(grid, "Position"))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Offset X (px)", self._spin(form, self.ov_offx, -4000, 4000, 7))
        self._form_row(form, "Offset Y (px)", self._spin(form, self.ov_offy, -4000, 4000, 7))
        ttk.Button(c.body, text="Back to center", style="Small.TButton",
                   command=self._ov_center).pack(anchor="w", pady=(px(8), 0))

        # live update while typing in the fields too (not only with the arrows)
        self.ov_style_var.trace_add("write", lambda *a: self._ov_changed())
        for var in (self.ov_color, self.ov_opacity, self.ov_size, self.ov_thick, self.ov_gap,
                    self.ov_dot, self.ov_outline_color, self.ov_outline_w,
                    self.ov_offx, self.ov_offy, self.ov_image, self.ov_scale):
            var.trace_add("write", lambda *a: self._ov_changed())

    # --- page: on-screen text ---------------------------------------------------
    def _build_texts_page(self):
        page, actions = self._page("texts", "On-screen text",
                                   "Text shown over the game: reminders, the time, the date… "
                                   "Changes apply right away and are saved automatically.")
        ttk.Button(actions, text="＋  Add text", style="Accent.TButton",
                   command=self._ov_add_text).pack(side="right")
        body = ttk.Frame(page, style="Page.TFrame")
        self._overlay_hint(page, body)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.ov_texts_vis = tk.BooleanVar()
        lc = self._card(body, "Text items", accent=VIOLET)
        lc.grid(row=0, column=0, sticky="nsw", padx=(0, px(14)))
        row, _ = self._switch_row(lc.body, "Show text", self.ov_texts_vis, self._ov_changed)
        row.pack(fill="x", pady=(0, px(8)))
        box = tk.Frame(lc.body, background=FIELD, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="both", expand=True)
        self.ov_text_list = tk.Listbox(box, width=22, height=6, exportselection=False, activestyle="none",
                                       font=ui(), background=FIELD, foreground=TEXT,
                                       selectbackground=ACCENT_DIM, selectforeground=ACCENT,
                                       borderwidth=0, relief="flat", highlightthickness=0)
        self.ov_text_list.pack(fill="both", expand=True, padx=px(4), pady=px(4))
        self.ov_text_list.bind("<<ListboxSelect>>", lambda e: self._ov_load_text())
        tb = ttk.Frame(lc.body)
        tb.pack(fill="x", pady=(px(10), 0))
        for i, (text, cmd) in enumerate((("Duplicate", self._ov_dup_text), ("Delete", self._ov_del_text),
                                         ("↑  Up", lambda: self._ov_move_text(-1)),
                                         ("↓  Down", lambda: self._ov_move_text(1)))):
            ttk.Button(tb, text=text, style="Small.TButton", command=cmd).grid(
                row=i // 2, column=i % 2, sticky="we", padx=px(2), pady=px(2))
        tb.columnconfigure((0, 1), weight=1)

        right = ttk.Frame(body, style="Page.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.txt_empty = tk.Label(right, text="No text yet.\n\nPress \"＋ Add text\" to create one.",
                                  background=BG, foreground=MUTED, font=ui(1), justify="center")
        self.txt_editor = Scrollable(right)
        grid = CardGrid(self.txt_editor.body, px(320))
        grid.pack(fill="x")

        self.ov_t_vis = tk.BooleanVar()
        self.ov_t_font = tk.StringVar()
        self.ov_t_size = tk.IntVar()
        self.ov_t_bold = tk.BooleanVar()
        self.ov_t_italic = tk.BooleanVar()
        self.ov_t_color = tk.StringVar()
        self.ov_t_opacity = tk.IntVar()
        self.ov_t_outline = tk.BooleanVar()
        self.ov_t_outline_color = tk.StringVar()
        self.ov_t_outline_w = tk.IntVar()
        self.ov_t_bg = tk.BooleanVar()
        self.ov_t_bg_color = tk.StringVar()
        self.ov_t_bg_opacity = tk.IntVar()
        self.ov_t_anchor = tk.StringVar()
        self.ov_t_offx = tk.IntVar()
        self.ov_t_offy = tk.IntVar()

        # content
        c = grid.add(self._card(grid, "Content"))
        row, _ = self._switch_row(c.body, "Visible", self.ov_t_vis, self._ov_text_changed)
        row.pack(fill="x", pady=(0, px(8)))
        self.ov_t_text = tk.Text(c.body, height=3, width=24, wrap="word", font=ui(),
                                 background=FIELD, foreground=TEXT, insertbackground=ACCENT,
                                 selectbackground=ACCENT_DIM, selectforeground=TEXT,
                                 relief="flat", borderwidth=0, highlightthickness=1,
                                 highlightbackground=BORDER, highlightcolor=ACCENT, padx=8, pady=6)
        self.ov_t_text.pack(fill="x")
        self.ov_t_text.bind("<KeyRelease>", lambda e: self._ov_text_changed())
        wrap_label(c.body, "Placeholders: {time} · {timesec} · {date}").pack(fill="x", pady=(px(6), 0))

        # font
        c = grid.add(self._card(grid, "Font"))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Font", ttk.Combobox(form, textvariable=self.ov_t_font, width=18,
                                                  values=self._ov_fonts()), sticky="we")
        self._form_row(form, "Size", self._spin(form, self.ov_t_size, 6, 400))
        style_row = ttk.Frame(form)
        ttk.Checkbutton(style_row, text="Bold", variable=self.ov_t_bold,
                        command=self._ov_text_changed).pack(side="left")
        ttk.Checkbutton(style_row, text="Italic", variable=self.ov_t_italic,
                        command=self._ov_text_changed).pack(side="left", padx=(px(10), 0))
        self._form_row(form, "Style", style_row)
        self._form_row(form, "Color", self._color_field(form, self.ov_t_color))
        self._form_row(form, "Opacity %", self._spin(form, self.ov_t_opacity, 5, 100))

        # effects
        c = grid.add(self._card(grid, "Effects"))
        row, _ = self._switch_row(c.body, "Outline", self.ov_t_outline, self._ov_text_changed)
        row.pack(fill="x", pady=(0, px(4)))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Outline color", self._color_field(form, self.ov_t_outline_color))
        self._form_row(form, "Thickness", self._spin(form, self.ov_t_outline_w, 1, 20))
        row, _ = self._switch_row(c.body, "Background", self.ov_t_bg, self._ov_text_changed)
        row.pack(fill="x", pady=(px(10), px(4)))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Background color", self._color_field(form, self.ov_t_bg_color))
        self._form_row(form, "Opacity %", self._spin(form, self.ov_t_bg_opacity, 5, 100))

        # position
        c = grid.add(self._card(grid, "Position"))
        form = self._form(c.body)
        form.pack(fill="x")
        self._form_row(form, "Anchor",
                       ttk.Combobox(form, textvariable=self.ov_t_anchor, state="readonly", width=20,
                                    values=overlay.ANCHORS), sticky="we")
        self._form_row(form, "Offset X (px)", self._spin(form, self.ov_t_offx, -8000, 8000, 7))
        self._form_row(form, "Offset Y (px)", self._spin(form, self.ov_t_offy, -8000, 8000, 7))

        self.ov_t_font.trace_add("write", lambda *a: self._ov_text_changed())
        self.ov_t_anchor.trace_add("write", lambda *a: self._ov_text_changed())
        for var in (self.ov_t_size, self.ov_t_color, self.ov_t_opacity, self.ov_t_outline_color,
                    self.ov_t_outline_w, self.ov_t_bg_color, self.ov_t_bg_opacity,
                    self.ov_t_offx, self.ov_t_offy):
            var.trace_add("write", lambda *a: self._ov_text_changed())

    # --- page: settings ----------------------------------------------------
    def _build_settings_page(self):
        page, _ = self._page("settings", "Settings",
                             "How keyboard and mouse input is read, plus the overlay's monitor and hotkeys.")
        sc = Scrollable(page)
        sc.pack(fill="both", expand=True)
        grid = CardGrid(sc.body, px(380))
        grid.pack(fill="x")

        c = grid.add(self._card(grid, "Incognito mode", accent=VIOLET))
        row, self.inc_switch_page = self._switch_row(c.body, "Incognito on", self.incognito_var,
                                                     self.toggle_incognito)
        row.pack(fill="x")
        self.inc_state_lbl = ttk.Label(c.body, text="", style="Section.TLabel")
        self.inc_state_lbl.pack(anchor="w", pady=(px(8), 0))
        wrap_label(c.body, INCOGNITO_HELP).pack(fill="x", pady=(px(6), 0))

        c = grid.add(self._card(grid, "Overlay"))
        form = self._form(c.body)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.ov_monitor = tk.StringVar()
        self.ov_monitor_cb = ttk.Combobox(form, textvariable=self.ov_monitor, state="readonly", width=24,
                                          postcommand=self._ov_refresh_monitors)
        self.ov_monitor_cb.bind("<<ComboboxSelected>>", lambda e: self._ov_changed())
        self._form_row(form, "Monitor", self.ov_monitor_cb, sticky="we")
        ttk.Label(form, text="HOTKEYS (they work in the game too)", style="Section.TLabel").grid(
            row=form.next_row, column=0, columnspan=3, sticky="w", pady=(px(12), px(4)))
        form.next_row += 1
        self.ov_hk_all = tk.StringVar()
        self.ov_hk_cross = tk.StringVar()
        self.ov_hk_texts = tk.StringVar()
        for label, var, which in (("Show/hide everything", self.ov_hk_all, "all"),
                                  ("Crosshair only", self.ov_hk_cross, "cross"),
                                  ("Text only", self.ov_hk_texts, "texts")):
            r = form.next_row
            form.next_row += 1
            ttk.Label(form, text=label, style="Muted.TLabel").grid(row=r, column=0, sticky="w",
                                                                   pady=px(3), padx=(0, px(12)))
            ttk.Entry(form, textvariable=var, width=14, state="readonly").grid(row=r, column=1, sticky="we", pady=px(3))
            ttk.Button(form, text="Change…", style="Small.TButton",
                       command=lambda w=which: self._ov_capture_hotkey(w)).grid(
                row=r, column=2, padx=(px(6), 0), pady=px(3))
        self.ov_hk_warn = wrap_label(c.body, "", style="Error.TLabel")
        self.ov_hk_warn.pack(fill="x", pady=(px(6), 0))

        c = grid.add(self._card(grid, "Data"))
        wrap_label(c.body, f"Macros, profiles and settings are saved in:\n{DATA_DIR}").pack(fill="x")
        ttk.Button(c.body, text="Open folder", style="Small.TButton",
                   command=self._open_data_dir).pack(anchor="w", pady=(px(8), 0))

    def _open_data_dir(self):
        try:
            os.startfile(DATA_DIR)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open the folder:\n{exc}")

    # --- overlay: logic -----------------------------------------------------------
    def _ov_fonts(self):
        try:
            return sorted({f for f in tkfont.families(self.root) if not f.startswith("@")}, key=str.lower)
        except tk.TclError:
            return ["Segoe UI"]

    def _ov_current_text(self):
        sel = self.ov_text_list.curselection()
        if not sel:
            return None
        i = sel[0]
        if 0 <= i < len(self.ov_settings.texts):
            return self.ov_settings.texts[i]
        return None

    def _ov_update_preview(self):
        try:
            img = overlay.render_preview(self.ov_settings, size=px(200))
            from PIL import ImageTk
            self._ov_preview_img = ImageTk.PhotoImage(img)
            self.ov_preview.configure(image=self._ov_preview_img)
        except Exception:
            traceback.print_exc()

    def _ov_changed(self):
        if self._ov_loading:
            return
        self._ov_apply_crosshair()
        self._ov_apply_options()
        self._ov_update_preview()
        self._ov_refresh_overlay()
        self._ov_schedule_save()

    def _ov_text_changed(self):
        if self._ov_loading:
            return
        self._ov_apply_text()
        self._ov_refresh_overlay()
        self._ov_schedule_save()

    def _ov_schedule_save(self):
        """Automatic save (groups changes made in a row)."""
        if self._ov_save_job:
            self.root.after_cancel(self._ov_save_job)
        self._ov_save_job = self.root.after(800, self._ov_save)

    def _ov_save(self):
        self._ov_save_job = None
        try:
            overlay.save_settings(self.ov_settings)
        except OSError as exc:
            self.set_status(f"⚠  Could not save the overlay settings: {exc}", error=True)

    def _ov_apply_crosshair(self):
        if self._ov_loading:
            return
        c = self.ov_settings.crosshair
        c.visible = self.ov_vis.get()
        style = self.ov_style_var.get()
        c.style = overlay.STYLES.index(style) if style in overlay.STYLES else 1
        c.color = self._ov_color(self.ov_color, self._ov_spin(self.ov_opacity, 100), c.color)
        c.size = self._ov_spin(self.ov_size, 0)
        c.thickness = self._ov_spin(self.ov_thick, 1)
        c.gap = self._ov_spin(self.ov_gap, 0)
        c.dot_size = self._ov_spin(self.ov_dot, 1)
        c.outline = self.ov_outline.get()
        c.outline_color = self._ov_color(self.ov_outline_color, 100, c.outline_color)
        c.outline_width = self._ov_spin(self.ov_outline_w, 1)
        c.offset_x = self._ov_spin(self.ov_offx, 0)
        c.offset_y = self._ov_spin(self.ov_offy, 0)
        c.image_path = self.ov_image.get().strip()
        c.scale = self._ov_spin(self.ov_scale, 100)

    def _ov_pick_image(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Crosshair image",
            filetypes=[("Images", "*.png *.bmp *.gif *.jpg *.jpeg"), ("All files", "*.*")])
        if not path:
            return
        self.ov_image.set(path)
        self.ov_style_var.set(overlay.STYLES[overlay.STYLE_IMAGE])

    def _ov_apply_text(self):
        if self._ov_loading:
            return
        t = self._ov_current_text()
        if t is None:
            return
        t.visible = self.ov_t_vis.get()
        t.text = self.ov_t_text.get("1.0", "end-1c")
        t.font_name = self.ov_t_font.get() or "Segoe UI"
        t.font_size = self._ov_spin(self.ov_t_size, 28)
        t.bold = self.ov_t_bold.get()
        t.italic = self.ov_t_italic.get()
        t.color = self._ov_color(self.ov_t_color, self._ov_spin(self.ov_t_opacity, 100), t.color)
        t.outline = self.ov_t_outline.get()
        t.outline_color = self._ov_color(self.ov_t_outline_color, 100, t.outline_color)
        t.outline_width = self._ov_spin(self.ov_t_outline_w, 1)
        t.background = self.ov_t_bg.get()
        t.background_color = self._ov_color(self.ov_t_bg_color, self._ov_spin(self.ov_t_bg_opacity, 50),
                                            t.background_color)
        anchor = self.ov_t_anchor.get()
        t.anchor = overlay.ANCHORS.index(anchor) if anchor in overlay.ANCHORS else 1
        t.offset_x = self._ov_spin(self.ov_t_offx, 0)
        t.offset_y = self._ov_spin(self.ov_t_offy, 0)
        self._ov_refresh_list()

    def _ov_apply_options(self):
        if self._ov_loading:
            return
        self.ov_settings.texts_visible = self.ov_texts_vis.get()
        mons = self._ov_monitors()
        idx = self.ov_monitor_cb.current()
        self.ov_settings.monitor = idx if 0 <= idx < len(mons) else 0

    def _ov_spin(self, var, default):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return default

    def _ov_color(self, var, opacity, current):
        """'#rrggbb' from the field + opacity; if the field isn't valid (yet) keeps the current color."""
        hexstr = var.get().strip().lstrip("#")
        if len(hexstr) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in hexstr):
            return overlay.color_from_hex(hexstr, opacity)
        return overlay.color_from_hex(overlay._argb_to_hex(current), opacity)

    def _ov_monitors(self):
        if not hasattr(self, "_ov_mons_cache"):
            self._ov_mons_cache = overlay.list_monitors()
        return self._ov_mons_cache

    def _ov_refresh_monitors(self):
        self._ov_mons_cache = overlay.list_monitors()
        mons = self._ov_mons_cache
        labels = [f"Monitor {i+1}: {w}×{h}" + (" (primary)" if p else "")
                  for i, (x, y, w, h, p) in enumerate(mons)]
        self.ov_monitor_cb.configure(values=labels)
        cur = self.ov_settings.monitor
        if 0 <= cur < len(labels):
            self.ov_monitor.set(labels[cur])

    def _ov_refresh_list(self):
        sel = self.ov_text_list.curselection()
        self.ov_text_list.delete(0, "end")
        for t in self.ov_settings.texts:
            self.ov_text_list.insert("end", ("  " if t.visible else "· ") + t.short())
        if sel and sel[0] < len(self.ov_settings.texts):
            self.ov_text_list.selection_set(sel[0])
        self._ov_update_text_editor()

    def _ov_update_text_editor(self):
        """Text editor if there is at least one text item, otherwise a message."""
        if self.ov_settings.texts:
            self.txt_empty.grid_remove()
            self.txt_editor.grid(row=0, column=0, sticky="nsew")
        else:
            self.txt_editor.grid_remove()
            self.txt_empty.grid(row=0, column=0, sticky="nsew")

    def _ov_refresh_overlay(self):
        if self.overlay is not None:
            self.overlay.update()

    def _on_overlay_hotkey(self, hid):
        """Called from the overlay thread when one of its hotkeys is pressed."""
        def apply():
            self.overlay.toggle(hid)
            self.ov_on_var.set(self.overlay.show_all)
        self.call_soon(apply)

    def _ov_toggle(self):
        # hide without stopping the thread, so the hotkeys keep working
        self.overlay.set_show(show_all=self.ov_on_var.get())
        self.set_status("Overlay on" if self.ov_on_var.get() else "Overlay off")

    def _ov_reset(self):
        if not messagebox.askyesno(APP_NAME, "Restore the crosshair settings to their defaults?\n\n"
                                             "Your on-screen text is not affected."):
            return
        texts, texts_visible = self.ov_settings.texts, self.ov_settings.texts_visible
        self.ov_settings = overlay.OverlaySettings()
        self.ov_settings.texts, self.ov_settings.texts_visible = texts, texts_visible
        self.overlay.settings = self.ov_settings
        self._ov_loading = True
        self._ov_load_all()
        self._ov_loading = False
        self._ov_register_hotkeys()
        self._ov_save()
        self._ov_update_preview()
        self._ov_refresh_overlay()

    def _ov_center(self):
        self._ov_loading = True
        self.ov_offx.set(0)
        self.ov_offy.set(0)
        self._ov_loading = False
        self._ov_changed()

    # --- text items -------------------------------------------------------------
    def _ov_select_text(self, index):
        self._ov_refresh_list()
        self.ov_text_list.selection_clear(0, "end")
        if 0 <= index < len(self.ov_settings.texts):
            self.ov_text_list.selection_set(index)
            self.ov_text_list.see(index)
            self._ov_load_text()
        self._ov_refresh_overlay()
        self._ov_schedule_save()

    def _ov_add_text(self):
        self._ov_apply_text()
        t = overlay.TextItem()
        t.offset_y = 40 + 50 * len(self.ov_settings.texts)
        self.ov_settings.texts.append(t)
        self._ov_select_text(len(self.ov_settings.texts) - 1)
        self.ov_t_text.focus_set()
        self.ov_t_text.tag_add("sel", "1.0", "end-1c")

    def _ov_dup_text(self):
        i = self._ov_text_sel()
        if i is None:
            return
        self._ov_apply_text()
        t = copy.deepcopy(self.ov_settings.texts[i])
        t.offset_y += 50
        self.ov_settings.texts.insert(i + 1, t)
        self._ov_select_text(i + 1)

    def _ov_del_text(self):
        i = self._ov_text_sel()
        if i is None:
            return
        del self.ov_settings.texts[i]
        self._ov_select_text(min(i, len(self.ov_settings.texts) - 1))

    def _ov_move_text(self, delta):
        i = self._ov_text_sel()
        if i is None:
            return
        j = i + delta
        if j < 0 or j >= len(self.ov_settings.texts):
            return
        self._ov_apply_text()
        lst = self.ov_settings.texts
        lst[i], lst[j] = lst[j], lst[i]
        self._ov_select_text(j)

    def _ov_text_sel(self):
        sel = self.ov_text_list.curselection()
        return sel[0] if sel else None

    def _ov_load_text(self):
        t = self._ov_current_text()
        if t is None:
            return
        was_loading = self._ov_loading
        self._ov_loading = True
        self.ov_t_vis.set(t.visible)
        self.ov_t_text.delete("1.0", "end")
        self.ov_t_text.insert("1.0", t.text)
        self.ov_t_font.set(t.font_name)
        self.ov_t_size.set(t.font_size)
        self.ov_t_bold.set(t.bold)
        self.ov_t_italic.set(t.italic)
        self.ov_t_color.set(overlay._argb_to_hex(t.color))
        self.ov_t_opacity.set(overlay._argb_alpha_pct(t.color))
        self.ov_t_outline.set(t.outline)
        self.ov_t_outline_color.set(overlay._argb_to_hex(t.outline_color))
        self.ov_t_outline_w.set(t.outline_width)
        self.ov_t_bg.set(t.background)
        self.ov_t_bg_color.set(overlay._argb_to_hex(t.background_color))
        self.ov_t_bg_opacity.set(overlay._argb_alpha_pct(t.background_color))
        self.ov_t_anchor.set(overlay.ANCHORS[t.anchor] if 0 <= t.anchor < len(overlay.ANCHORS) else overlay.ANCHORS[1])
        self.ov_t_offx.set(t.offset_x)
        self.ov_t_offy.set(t.offset_y)
        self._ov_loading = was_loading

    # --- overlay hotkeys ---------------------------------------------------------
    def _ov_capture_hotkey(self, which):
        var = {"all": self.ov_hk_all, "cross": self.ov_hk_cross, "texts": self.ov_hk_texts}[which]
        if self._ov_hk_capture is not None:
            self._ov_hk_capture.cancel()
        var.set("Press a key…")

        def done(name, mods):
            self._ov_hk_capture = None
            val = self._ov_vk_to_net(name, mods)
            self._ov_hk_raw[which] = val
            var.set(overlay.hotkey_name(val))
            self._ov_register_hotkeys()
            self._ov_save()
            self._update_ov_hints()

        self._ov_hk_capture = KeyCapture(self.hook, self.call_soon, done, allow_modifiers=True)
        self._ov_hk_capture.start()

    def _ov_vk_to_net(self, name, mods):
        """Key name + modifiers -> .NET Keys value."""
        vk = keys._NAME_TO_VK.get(name.lower())
        if vk is None:
            return 0
        val = vk & 0xFFFF
        if "Ctrl" in mods:
            val |= 0x20000
        if "Shift" in mods:
            val |= 0x10000
        if "Alt" in mods:
            val |= 0x40000
        return val

    def _ov_register_hotkeys(self):
        if self.overlay is None:
            return
        s = self.ov_settings
        s.hotkey_all = self._ov_hk_raw.get("all", 0)
        s.hotkey_crosshair = self._ov_hk_raw.get("cross", 0)
        s.hotkey_texts = self._ov_hk_raw.get("texts", 0)
        failed = self.overlay.register_hotkeys()
        self.ov_hk_warn.configure(
            text=("These keys are already used by another program: " + ", ".join(failed))
            if failed else "")

    # --- initial load ------------------------------------------------------------
    def _ov_load_all(self):
        s = self.ov_settings
        c = s.crosshair
        self.ov_on_var.set(self.overlay.show_all)
        self.ov_vis.set(c.visible)
        self.ov_style_var.set(overlay.STYLES[c.style] if 0 <= c.style < len(overlay.STYLES) else overlay.STYLES[1])
        self.ov_color.set(overlay._argb_to_hex(c.color))
        self.ov_opacity.set(overlay._argb_alpha_pct(c.color))
        self.ov_size.set(c.size)
        self.ov_thick.set(c.thickness)
        self.ov_gap.set(c.gap)
        self.ov_dot.set(c.dot_size)
        self.ov_outline.set(c.outline)
        self.ov_outline_color.set(overlay._argb_to_hex(c.outline_color))
        self.ov_outline_w.set(c.outline_width)
        self.ov_offx.set(c.offset_x)
        self.ov_offy.set(c.offset_y)
        self.ov_image.set(c.image_path)
        self.ov_scale.set(c.scale)
        self.ov_texts_vis.set(s.texts_visible)
        self._ov_refresh_list()
        self.ov_monitor.set("")
        self._ov_refresh_monitors()
        self.ov_hk_all.set(overlay.hotkey_name(s.hotkey_all))
        self.ov_hk_cross.set(overlay.hotkey_name(s.hotkey_crosshair))
        self.ov_hk_texts.set(overlay.hotkey_name(s.hotkey_texts))
        self._ov_hk_raw = {"all": s.hotkey_all, "cross": s.hotkey_crosshair, "texts": s.hotkey_texts}
        if s.texts:
            self.ov_text_list.selection_clear(0, "end")
            self.ov_text_list.selection_set(0)
            self._ov_load_text()

    def _make_editor(self, parent):
        # minimum height: the grid shares out the space by weight
        box = tk.Frame(parent, background=FIELD, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=ACCENT)
        box.grid(row=1, column=0, sticky="nsew")
        text = tk.Text(box, wrap="none", undo=True, font=self.mono, height=2, width=20,
                       background=FIELD, foreground=TEXT, insertbackground=ACCENT,
                       selectbackground=ACCENT_DIM, selectforeground=TEXT, relief="flat",
                       borderwidth=0, highlightthickness=0, padx=px(10), pady=px(8), insertwidth=2)
        sb = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        sb.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(yscrollcommand=sb.set)
        # cyan border while the editor has focus
        text.bind("<FocusIn>", lambda e: box.configure(highlightbackground=ACCENT), add="+")
        text.bind("<FocusOut>", lambda e: box.configure(highlightbackground=BORDER), add="+")
        text.tag_configure("cmd", foreground=ACCENT)
        text.tag_configure("comment", foreground=DIM)
        text.tag_configure("num", foreground=ORANGE)
        text.tag_configure("error", background=RED_DIM)
        text.bind("<<Modified>>", self._on_editor_modified)
        return text

    # --- on/off state -------------------------------------------------------------
    def _update_status(self):
        on = self.engine.enabled
        self.status_lbl.configure(text="●  MACROS ON" if on else "●  MACROS OFF",
                                  foreground=GREEN if on else RED)
        self.power_btn.configure(text="■   STOP" if on else "▶   START",
                                 style="Power.Danger.TButton" if on else "Power.TButton")
        self.control.configure(highlightbackground=GREEN if on else BORDER)

    def toggle_enabled(self):
        # a double click must not turn on and immediately off again
        now = time.monotonic()
        if now - self._last_power < 0.4:
            return
        self._last_power = now
        self.engine.set_enabled(not self.engine.enabled)
        self._update_status()

    def toggle_incognito(self):
        """Switches mode in a separate thread: the GUI doesn't freeze and repeated
        clicks during the switch are ignored."""
        want = bool(self.incognito_var.get())
        if self._incognito_busy or want == self.hook.stealth:
            self.incognito_var.set(self.hook.stealth)
            return
        self._incognito_busy = True
        for sw in (self.inc_switch, self.inc_switch_page):
            sw.set_enabled(False)
        self.set_status("Switching input mode…")

        def work():
            error = None
            try:
                self.hook.set_stealth(want)
            except OSError as exc:
                error = exc
            # releases that happened during the switch may have been lost
            self.engine.reset_input_state()
            self.call_soon(lambda: self._incognito_done(error))

        threading.Thread(target=work, name="IncognitoSwitch", daemon=True).start()

    def _incognito_done(self, error):
        self._incognito_busy = False
        for sw in (self.inc_switch, self.inc_switch_page):
            sw.set_enabled(True)
        on = self.hook.stealth
        self._update_incognito()
        if error is not None:
            messagebox.showerror(APP_NAME, f"Could not switch incognito mode:\n{error}")
            return
        self.store.settings["incognito"] = on
        self.store.save_settings()
        self.set_status("Incognito on: no system hooks, polling only" if on
                        else "Incognito off: system hooks active")

    def _update_incognito(self):
        on = self.hook.stealth
        if self.incognito_var.get() != on:
            self.incognito_var.set(on)
        self.inc_state_lbl.configure(text="INPUT: POLLING (NO HOOKS)" if on
                                     else "INPUT: SYSTEM HOOKS")

    def set_status(self, text, error=False):
        self.statusbar.configure(text=text, foreground=RED if error else MUTED)

    # --- profiles --------------------------------------------------------------------
    def _refresh_profiles(self):
        self.profile_cb.configure(values=sorted(self.store.profiles))
        profile = self.store.active_profile
        self.profile_var.set(profile.name)
        self.process_var.set(profile.process or ALL_WINDOWS)
        self.profile_lbl.configure(text=f"Profile: {profile.name}"
                                        + (f"  ·  only {profile.process}" if profile.process else ""))
        self._refresh_bindings()

    def select_profile(self, name):
        if name not in self.store.profiles:
            return
        self.engine.stop_all()
        self.store.settings["active_profile"] = name
        self.store.save_settings()
        self.engine.reload()
        self._refresh_profiles()
        self.set_status(f"Active profile: {name}")

    def _ask_profile_name(self, title, initial=""):
        name = simpledialog.askstring(APP_NAME, title, initialvalue=initial, parent=self.root)
        if name is None:
            return None
        name = name.strip()
        if not name:
            return None
        if name in self.store.profiles and name != initial:
            messagebox.showerror(APP_NAME, "A profile with this name already exists.")
            return None
        return name

    def new_profile(self):
        name = self._ask_profile_name("Name of the new profile:")
        if name:
            self.store.save_profile(Profile(name))
            self.select_profile(name)

    def rename_profile(self):
        old = self.store.active_profile
        name = self._ask_profile_name("New profile name:", old.name)
        if name and name != old.name:
            self.store.save_profile(Profile(name, old.process, old.bindings), old_name=old.name)
            self.store.settings["active_profile"] = name
            self.store.save_settings()
            self._refresh_profiles()

    def delete_profile(self):
        if len(self.store.profiles) <= 1:
            messagebox.showinfo(APP_NAME, "There must be at least one profile.")
            return
        name = self.store.active_profile.name
        if messagebox.askyesno(APP_NAME, f"Delete the profile '{name}'?"):
            self.store.delete_profile(name)
            self.select_profile(sorted(self.store.profiles)[0])

    def _refresh_process_list(self):
        try:
            names = winapi.window_processes()
        except OSError:
            names = []
        current = self.store.active_profile.process
        if current and current.lower() not in {n.lower() for n in names}:
            names.insert(0, current)
        self.process_cb.configure(values=[ALL_WINDOWS] + names)

    def apply_process(self):
        profile = self.store.active_profile
        value = self.process_var.get().strip()
        if value == ALL_WINDOWS:
            value = ""
        if not value:
            self.process_var.set(ALL_WINDOWS)
        if value != profile.process:
            profile.process = value
            self.store.save_profile(profile)
            self.engine.reload()
            self._refresh_profiles()
            self.set_status(f"Profile active only in: {value}" if value else "Profile active in all windows")

    # --- key bindings -----------------------------------------------------------
    def _refresh_bindings(self, select_index=None):
        self.tree.delete(*self.tree.get_children())
        bindings = self.store.active_profile.bindings
        for i, b in enumerate(bindings):
            missing = b.macro not in self.store.macros
            macro = f"⚠ {b.macro} (missing)" if missing else b.macro
            mode = MODES.get(b.mode, b.mode)
            if b.mode == "repeat":
                mode = f"Repeat {b.count} times"
            label = "+".join(sorted(b.modifiers) + [keys.label(b.trigger)])
            self.tree.insert("", "end", iid=str(i), values=(label, macro, mode, "Yes" if b.block else "No"),
                             tags=("missing",) if missing else ())
        if select_index is not None and self.tree.exists(str(select_index)):
            self.tree.selection_set(str(select_index))
            self.tree.see(str(select_index))
        self.bindings_hint.configure(
            text="Double-click a row to edit it  ·  Delete to remove it" if bindings
            else "No keys assigned yet: press \"＋ Add…\" to link a key to a macro.")

    def _selected_binding_index(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _save_bindings(self, select_index=None):
        self.store.save_profile(self.store.active_profile)
        self.engine.reload()
        self._refresh_bindings(select_index)

    def _conflicts(self, binding, ignore_index=None):
        for i, b in enumerate(self.store.active_profile.bindings):
            if i != ignore_index and b.trigger == binding.trigger and sorted(b.modifiers) == sorted(binding.modifiers):
                return True
        return False

    def add_binding(self):
        if not self.store.macros:
            messagebox.showinfo(APP_NAME, "Create a macro first on the \"Macro editor\" page.")
            return
        dlg = BindingDialog(self)
        self.root.wait_window(dlg)
        if dlg.result:
            if self._conflicts(dlg.result):
                messagebox.showerror(APP_NAME, f"'{dlg.result.trigger_label()}' is already assigned.")
                return
            bindings = self.store.active_profile.bindings
            bindings.append(dlg.result)
            self._save_bindings(len(bindings) - 1)

    def edit_binding(self):
        idx = self._selected_binding_index()
        if idx is None:
            return
        bindings = self.store.active_profile.bindings
        dlg = BindingDialog(self, copy.deepcopy(bindings[idx]))
        self.root.wait_window(dlg)
        if dlg.result:
            if self._conflicts(dlg.result, ignore_index=idx):
                messagebox.showerror(APP_NAME, f"'{dlg.result.trigger_label()}' is already assigned.")
                return
            bindings[idx] = dlg.result
            self._save_bindings(idx)

    def remove_binding(self):
        idx = self._selected_binding_index()
        if idx is None:
            return
        del self.store.active_profile.bindings[idx]
        self._save_bindings()

    # --- macros: list ---------------------------------------------------------------
    def _refresh_macro_list(self, select=None):
        names = sorted(self.store.macros, key=str.lower)
        self.macro_list.delete(0, "end")
        for n in names:
            self.macro_list.insert("end", n)
        target = select or self.current_macro or (names[0] if names else None)
        if target in names:
            i = names.index(target)
            self.macro_list.selection_clear(0, "end")
            self.macro_list.selection_set(i)
            self.macro_list.see(i)
            self._load_macro(target)
        else:
            self._load_macro(None)

    def _on_macro_select(self):
        sel = self.macro_list.curselection()
        if not sel:
            return
        name = self.macro_list.get(sel[0])
        if name == self.current_macro:
            return
        if not self._confirm_discard():
            # restore the previous selection without losing the changes
            names = self.macro_list.get(0, "end")
            self.macro_list.selection_clear(0, "end")
            if self.current_macro in names:
                self.macro_list.selection_set(names.index(self.current_macro))
            return
        self._refresh_macro_list(name)

    def _editor_values(self):
        return Macro(
            name=self.name_var.get().strip(),
            description=self.desc_var.get().strip(),
            on_press=self.press_text.get("1.0", "end-1c").strip(),
            on_release=self.release_text.get("1.0", "end-1c").strip(),
        )

    def _is_dirty(self):
        if self.current_macro is None or self.current_macro not in self.store.macros:
            return False
        saved = self.store.macros[self.current_macro]
        cur = self._editor_values()
        return (cur.name, cur.description, cur.on_press, cur.on_release) != (
            saved.name, saved.description.strip(), saved.on_press.strip(), saved.on_release.strip())

    def _confirm_discard(self):
        if not self._is_dirty():
            return True
        answer = messagebox.askyesnocancel(APP_NAME, f"Save the changes to '{self.current_macro}'?")
        if answer is None:
            return False
        if answer:
            return self.save_macro()
        return True

    def _load_macro(self, name):
        self.current_macro = name
        macro = self.store.macros.get(name) if name else None
        self.name_var.set(macro.name if macro else "")
        self.desc_var.set(macro.description if macro else "")
        for widget, value in ((self.press_text, macro.on_press if macro else ""),
                              (self.release_text, macro.on_release if macro else "")):
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
            widget.edit_reset()
        self._validate()

    def _unique_macro_name(self, base):
        name, i = base, 2
        while name in self.store.macros:
            name = f"{base} {i}"
            i += 1
        return name

    def new_macro(self):
        if not self._confirm_discard():
            return
        macro = Macro(self._unique_macro_name("New macro"))
        self.store.save_macro(macro)
        self._refresh_macro_list(macro.name)

    def duplicate_macro(self):
        if not self.current_macro or not self._confirm_discard():
            return
        src = self.store.macros[self.current_macro]
        macro = Macro(self._unique_macro_name(f"{src.name} (copy)"), src.description, src.on_press, src.on_release)
        self.store.save_macro(macro)
        self._refresh_macro_list(macro.name)

    def delete_macro(self):
        name = self.current_macro
        if not name:
            return
        users = [(p, b) for p in self.store.profiles.values() for b in p.bindings if b.macro == name]
        msg = f"Delete the macro '{name}'?"
        if users:
            msg += f"\n\nThis also removes the {len(users)} key binding(s) that use it."
        if not messagebox.askyesno(APP_NAME, msg):
            return
        for profile in {id(p): p for p, _ in users}.values():
            profile.bindings = [b for b in profile.bindings if b.macro != name]
            self.store.save_profile(profile)
        self.store.delete_macro(name)
        self.current_macro = None
        self.engine.reload()
        self._refresh_bindings()
        self._refresh_macro_list()

    def import_amc(self):
        if not self._confirm_discard():
            return
        paths = filedialog.askopenfilenames(
            title="Import .amc macros",
            filetypes=[(".amc macros", "*.amc"), ("All files", "*.*")])
        last = None
        for path in paths:
            try:
                data = script.import_amc(path)
            except Exception as exc:  # malformed file
                messagebox.showerror(APP_NAME, f"Could not import {path}:\n{exc}")
                continue
            macro = Macro(self._unique_macro_name(data["name"].strip()), data["description"],
                          data["on_press"], data["on_release"])
            self.store.save_macro(macro)
            last = macro.name
        if last:
            self._refresh_macro_list(last)
            self.set_status(f"Imported {len(paths)} macro(s)")

    # --- macros: editor ----------------------------------------------------------
    def save_macro(self):
        if self.current_macro is None:
            return False
        macro = self._editor_values()
        if not macro.name:
            messagebox.showerror(APP_NAME, "The macro name can't be empty.")
            return False
        if macro.name != self.current_macro and macro.name in self.store.macros:
            messagebox.showerror(APP_NAME, "A macro with this name already exists.")
            return False
        self.store.save_macro(macro, old_name=self.current_macro)
        self.current_macro = macro.name
        self.engine.reload()
        self._refresh_bindings()
        self._refresh_macro_list(macro.name)
        self.set_status(f"Macro '{macro.name}' saved")
        return True

    def _on_editor_modified(self, event):
        widget = event.widget
        if widget.edit_modified():
            widget.edit_modified(False)
            if self._validate_job:
                self.root.after_cancel(self._validate_job)
            self._validate_job = self.root.after(250, self._validate)

    def _highlight(self, widget):
        for tag in ("cmd", "comment", "num", "error"):
            widget.tag_remove(tag, "1.0", "end")
        lines = widget.get("1.0", "end-1c").split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if not stripped:
                continue
            start = len(line) - len(stripped)
            if stripped.startswith("#") or stripped.startswith("//"):
                widget.tag_add("comment", f"{i}.{start}", f"{i}.end")
                continue
            end = start + len(stripped.split()[0])
            widget.tag_add("cmd", f"{i}.{start}", f"{i}.{end}")
            pos = end
            for token in stripped.split()[1:]:
                idx = line.find(token, pos)
                if token.lstrip("-").replace("-", "").isdigit():
                    widget.tag_add("num", f"{i}.{idx}", f"{i}.{idx + len(token)}")
                pos = idx + len(token)

    def _validate(self):
        self._validate_job = None
        errors = []
        for label, widget in (("Press", self.press_text), ("Release", self.release_text)):
            self._highlight(widget)
            try:
                script.parse(widget.get("1.0", "end-1c"))
            except script.ScriptError as exc:
                errors.append(f"{label} – {exc}")
                widget.tag_add("error", f"{exc.line_no}.0", f"{exc.line_no}.end")
        if self.current_macro is None:
            self.error_lbl.configure(text="")
        elif errors:
            self.error_lbl.configure(text="⚠  " + "   |   ".join(errors), style="Error.TLabel")
        else:
            self.error_lbl.configure(text="✓  Syntax OK", style="Ok.TLabel")

    def test_macro(self):
        values = self._editor_values()
        try:
            script.parse(values.on_press)
            script.parse(values.on_release)
        except script.ScriptError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return

        def countdown(n):
            if n > 0:
                self.set_status(f"The macro starts in {n}…  (put the cursor where you need it)")
                self.root.after(1000, countdown, n - 1)
            else:
                script.test_run(values.on_press, values.on_release, delay_before=0)
                self.set_status(f"▶  Testing '{values.name}'")

        countdown(3)

    def toggle_recording(self):
        if self.current_macro is None:
            return
        target = self.press_text if self.rec_target.get() == "press" else self.release_text
        if self.recorder is None:
            self.recorder = Recorder(self.hook, self.rec_delays.get(), self.rec_moves.get())
            for w in (self.press_text, self.release_text):
                w.configure(state="disabled")
            self.recorder.start()
            self.rec_btn.configure(text="■  Stop recording")
            self.set_status("Recording… (macros are paused)  Press 'Stop recording' to finish.")
        else:
            text = self.recorder.stop()
            self.recorder = None
            for w in (self.press_text, self.release_text):
                w.configure(state="normal")
            if text:
                existing = target.get("1.0", "end-1c")
                if existing.strip():
                    text = ("\n" if not existing.endswith("\n") else "") + text
                target.insert("end", text)
                target.see("end")
            self.rec_btn.configure(text="●  Record")
            self.set_status("Recording finished — remember to save")
            self._validate()

    # --- closing -------------------------------------------------------------------
    def on_close(self):
        if not self._confirm_discard():
            return
        if self.recorder:
            self.recorder.stop()
        if self._ov_save_job:
            self.root.after_cancel(self._ov_save_job)
            self._ov_save()
        self.engine.set_enabled(False)
        if self.overlay is not None:
            self.overlay.stop()
        self.hook.stop()
        self.root.destroy()
