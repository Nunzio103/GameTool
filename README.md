# GameTool

Keyboard and mouse macros for Windows, with an on-screen overlay for a crosshair and text.
Written in Python (tkinter), using the Win32 API through `ctypes`.

## Download

Download `GameTool.exe` from the **Releases** page and run it. You don't need to install Python.
Windows asks for administrator rights at startup (see [Known limitations](#known-limitations)).

> Windows Defender or SmartScreen may flag the exe because it isn't signed and it installs
> keyboard and mouse hooks. If you don't trust the binary, run the app from source instead.

Your data (macros, profiles, settings) is stored in `%APPDATA%\GameTool`.
For a **portable** setup, create a folder named `data` next to `GameTool.exe` and the app will use it instead.

## Running from source

You need Python 3.10 or later on Windows.

```bat
pip install -r requirements.txt
python main.py
```

You can also double-click `GameTool.bat`. When run from source, the app stores its data in the project's `data/` folder.

## How to use it

The window has a sidebar with a control panel (status, **▶ Start / ■ Stop**, and the **Overlay**
and **Incognito** switches) and five pages: *Key bindings*, *Macro editor*, *Crosshair*, *On-screen text*
and *Settings*.

1. **Macro editor**: create a macro, then type its commands or press **● Record**.
   Each macro has a script that runs when the key is pressed and an optional one that runs when it is released.
   **▶ Test** runs the macro after 3 seconds.
2. **Key bindings**: press **Add…**, then **Detect…** and press the key you want.
   Combinations such as Ctrl+F1 and the mouse side buttons work too. Then pick the macro and the mode.
3. Press **Start** in the sidebar. Macros never fire while GameTool itself is in the foreground,
   so you can always switch back to the app and press **Stop**, even if you bound the left mouse button.

### Modes

| Mode | What it does |
|---|---|
| Once | runs the macro once per key press |
| Repeat N times | runs the macro N times |
| Repeat while held | repeats the macro for as long as you hold the key |
| Toggle on/off | the first press starts the loop, the second press stops it |

The "on release" script runs when you let go of the key. In toggle mode it runs when you stop the loop.

### Other features

- **Profiles**, each with its own bindings, and an **"Active only in"** filter:
  macros fire only while a specific `.exe` is in the foreground.
- **Crosshair** and **on-screen text**: a transparent, click-through overlay with a customizable crosshair
  and text items (placeholders `{time}`, `{timesec}` = time with seconds, `{date}`).
  The overlay is always off at startup. Turn it on with the **Overlay** switch or its hotkey (`F8` by default).
  Changes are saved automatically.
- **Import .amc**: converts macros in `.amc` format into GameTool macros.
- **Incognito mode**: reads the keyboard and mouse by polling instead of system hooks.
  The original key always reaches the target program, and the mouse wheel can't be used as a trigger.
- If Windows silently disables the input hooks (it can happen when the system is under heavy load),
  GameTool notices and reinstalls them on its own.
- Keys a macro left pressed are released when the macro stops.

## Macro commands

```
KeyDown A / KeyUp A      KeyPress A [ms]
Delay 25                 Delay 20-40   (random)
LeftDown / LeftUp / LeftClick   (also Right, Middle, X1, X2)
MoveR dx dy              MoveTo x y
WheelUp [n]              WheelDown [n]
Text "hello"             Repeat 5 ... EndRepeat
# comment
```

Key names: `A`–`Z`, `0`–`9`, `F1`–`F24`, `Space`, `Enter`, `Tab`, `Esc`, `Backspace`, `LShift`/`RShift`,
`LCtrl`/`RCtrl`, `LAlt`/`RAlt`, `LWin`/`RWin`, arrows (`Up`, `Down`, `Left`, `Right`), `Insert`, `Delete`,
`Home`, `End`, `PageUp`, `PageDown`, `CapsLock`, `NumPad0`–`NumPad9`, and more. Not sure about a key's name?
Use **Record** and press it.

## Building the exe

```bat
pip install -r requirements.txt pyinstaller
python -m PyInstaller GameTool.spec
```

The result is `dist\GameTool.exe`.

## Project layout

| File | Contents |
|---|---|
| `gametool/winapi.py` | ctypes bindings: hooks, `SendInput`, 1 ms timer |
| `gametool/hooks.py` | global keyboard and mouse hooks (`WH_KEYBOARD_LL` / `WH_MOUSE_LL`), polling for incognito mode, hook watchdog |
| `gametool/keys.py` | conversion between key names and virtual-key codes |
| `gametool/script.py` | macro parser and runner, `.amc` import |
| `gametool/engine.py` | links triggers to macros, handles modes and key blocking |
| `gametool/recorder.py` | macro recorder |
| `gametool/overlay.py` | crosshair and text overlay |
| `gametool/storage.py` | JSON storage |
| `gametool/paths.py` | data and resource paths (source or exe) |
| `gametool/gui.py` | user interface |

## Known limitations

- If the target program runs as administrator, GameTool must too, otherwise Windows doesn't deliver
  the keys to it. That's why the app asks for elevation at startup.
- Input is simulated with `SendInput`, which means at the software level.
- OEM key names (Grave, Semicolon, …) follow the US layout. The app also shows the matching
  character on your own layout.

## Disclaimer

Many online games forbid macros and automation tools in their terms of service, and anti-cheat systems
can get your account suspended. Check the game's rules before using GameTool. You use it at your own risk.

## License

The code is released under the [MIT](LICENSE) license.
The [Titillium Web](https://fonts.google.com/specimen/Titillium+Web) font in `data/fonts` is distributed
under the SIL Open Font License 1.1 (`data/fonts/OFL.txt`).
