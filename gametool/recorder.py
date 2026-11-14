"""Records the keyboard/mouse into a macro script."""
from . import keys

_BUTTON_WORD = {"MouseLeft": "Left", "MouseRight": "Right", "MouseMiddle": "Middle",
                "MouseX1": "X1", "MouseX2": "X2"}
MOVE_INTERVAL = 0.015  # s between two recorded movements


class Recorder:
    def __init__(self, hook, record_delays=True, record_moves=False):
        self.hook = hook
        self.record_delays = record_delays
        self.record_moves = record_moves
        self.events = []      # (time, line)
        self._pressed = set()
        self._last_move = 0.0
        self.active = False

    def start(self):
        self.events = []
        self._pressed = set()
        self._last_move = 0.0
        self.active = True
        self.hook.want_moves = self.record_moves
        self.hook.exclusive = self._on_event

    def _on_event(self, ev):
        if ev.ours:
            return False
        if ev.kind == "move":
            if ev.time - self._last_move >= MOVE_INTERVAL:
                self._last_move = ev.time
                self.events.append((ev.time, f"MoveTo {ev.x} {ev.y}"))
            return False
        name = ev.name
        if name in keys.WHEEL_TRIGGERS:
            self.events.append((ev.time, name))
            return False
        if ev.kind == "down":
            if name in self._pressed:  # key autorepeat
                return False
            self._pressed.add(name)
        else:
            if name not in self._pressed:
                return False
            self._pressed.discard(name)
        suffix = "Down" if ev.kind == "down" else "Up"
        if name in _BUTTON_WORD:
            line = f"{_BUTTON_WORD[name]}{suffix}"
        else:
            line = f"Key{suffix} {name}"
        self.events.append((ev.time, line))
        return False

    def stop(self, strip_last_click=True):
        """Stops recording and returns the script.

        strip_last_click removes the final click used to press "Stop".
        """
        self.hook.exclusive = None
        self.hook.want_moves = False
        self.active = False
        events = list(self.events)
        if strip_last_click:
            for i in range(len(events) - 1, -1, -1):
                if events[i][1] == "LeftDown":
                    tail = [line for _, line in events[i + 1:]]
                    if all(l == "LeftUp" or l.startswith("MoveTo") for l in tail):
                        events = events[:i]
                    break
        # drop trailing movements (toward the Stop button)
        while events and events[-1][1].startswith("MoveTo"):
            events.pop()

        lines = []
        prev = None
        for t, line in events:
            if self.record_delays and prev is not None:
                ms = round((t - prev) * 1000)
                if ms > 0:
                    lines.append(f"Delay {ms}")
            lines.append(line)
            prev = t
        # release the keys still pressed
        for name in sorted(self._pressed - {"MouseLeft"}):
            lines.append(f"{_BUTTON_WORD[name]}Up" if name in _BUTTON_WORD else f"KeyUp {name}")
        return "\n".join(lines)
