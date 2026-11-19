"""Engine: intercepts the bound keys and runs their macros."""
import os
import threading

from . import keys, script, winapi


class _Task(threading.Thread):
    """Runs a macro for a single press of the trigger."""

    def __init__(self, engine, binding, ops, trigger):
        super().__init__(daemon=True, name=f"Macro-{binding.macro}")
        self.engine = engine
        self.binding = binding
        self.press_ops, self.release_ops = ops
        self.trigger = trigger
        self.interrupt = threading.Event()  # stops the loop of the press script
        self.released = threading.Event()   # the trigger has been released
        self.killed = threading.Event()     # full stop (engine turned off)
        self.runner = script.Runner(user_keys=engine.hook.user_keys)

    def on_release(self):
        self.released.set()
        if self.binding.mode == "hold":
            self.interrupt.set()

    def stop(self):
        """Stops the loop (used by toggle): the release script still runs."""
        self.interrupt.set()
        self.released.set()

    def kill(self):
        self.killed.set()
        self.stop()

    def run(self):
        winapi.boost_current_thread()  # Delays stay accurate even while the game loads the CPU
        b = self.binding
        try:
            if b.mode == "once":
                self.runner.run(self.press_ops, self.interrupt)
            elif b.mode == "repeat":
                for _ in range(max(1, b.count)):
                    if not self.runner.run(self.press_ops, self.interrupt):
                        break
            else:  # hold / toggle: repeats until interrupted
                needs_gap = not script.has_delay(self.press_ops)
                while not self.interrupt.is_set():
                    if not self.press_ops:
                        self.interrupt.wait()
                        break
                    if not self.runner.run(self.press_ops, self.interrupt):
                        break
                    if needs_gap:  # avoid flooding the system with a loop that has no pauses
                        self.interrupt.wait(0.001)
                # loop interrupted halfway: release whatever is still pressed
                self.runner.release_all()

            # wait for the release only if there is something to run then: if the
            # release got lost, the macro would stay "running" and ignore every press
            if self.release_ops:
                self.released.wait()
                if not self.killed.is_set():
                    self.runner.run(self.release_ops, self.killed)
        finally:
            self.runner.release_all()
            self.engine._task_done(self)


class Engine:
    def __init__(self, store, hook, notify=None):
        self.store = store
        self.hook = hook
        self.notify = notify or (lambda kind, data: None)
        self.enabled = False
        self._own_pid = os.getpid()
        self._index = {}
        self._process = ""
        self._pressed = set()
        self._blocked = set()
        self._tasks = {}
        self._lock = threading.RLock()
        self.reload()
        hook.listeners.append(self.on_event)
        hook.hot_vks = self._hot_vks

    def _hot_vks(self):
        """VKs of the triggers: in incognito mode they are read on every cycle."""
        return {vk for vk in map(keys.vk_from_name, list(self._index)) if vk is not None}

    def _own_window_active(self):
        """True if a GameTool window is in the foreground.

        Macros don't fire in that case: otherwise a blocked trigger (for
        example the left click) would make it impossible to press "Stop".
        """
        return winapi.foreground_pid() == self._own_pid

    # --- configuration -------------------------------------------------------
    def reload(self):
        """Reloads the bindings from the active profile."""
        profile = self.store.active_profile
        index = {}
        for b in profile.bindings:
            index.setdefault(b.trigger, []).append(b)
        # combinations with more modifiers take precedence
        for lst in index.values():
            lst.sort(key=lambda b: len(b.modifiers), reverse=True)
        self._index = index
        self._process = profile.process.strip().lower()

    def set_enabled(self, value):
        self.enabled = bool(value)
        # start from a clean state: a lost release must not make the key
        # ignored forever (mistaken for autorepeat)
        self.reset_input_state()
        self.notify("enabled", self.enabled)

    def reset_input_state(self):
        """Stops the macros and forgets the pressed/blocked keys.

        Call it when the way input is read changes (hooks/incognito),
        because releases that happen during the switch can be lost.
        """
        self.stop_all()
        self._pressed.clear()
        self._blocked.clear()

    def stop_all(self):
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            task.kill()

    # --- event handling (hook thread) -------------------------------------------
    def on_event(self, ev):
        if ev.ours or ev.kind == "move":
            return False
        name = ev.name
        is_wheel = name in keys.WHEEL_TRIGGERS

        if ev.kind == "up":
            self._pressed.discard(name)
            with self._lock:
                task = self._tasks.get(name)
            if task is not None and task.binding.mode != "toggle":
                task.on_release()
            if name in self._blocked:
                self._blocked.discard(name)
                return True
            return False

        # --- press ---
        # only the keyboard has autorepeat: for the mouse a second press
        # is always real (even if we missed the previous release)
        autorepeat = name in self._pressed and not keys.is_mouse(name)
        if not is_wheel:
            self._pressed.add(name)

        if autorepeat:
            return name in self._blocked
        if not self.enabled:
            return False

        binding = self._match(name)
        if binding is None:
            return False
        if self._own_window_active():
            return False
        if self._process and winapi.foreground_process_name().lower() != self._process:
            return False

        self._trigger(binding, name)
        if is_wheel:
            with self._lock:
                task = self._tasks.get(name)
            if task is not None and binding.mode != "toggle":
                task.on_release()
        if binding.block:
            if not is_wheel:
                self._blocked.add(name)
            return True
        return False

    def _match(self, name):
        candidates = self._index.get(name)
        if not candidates:
            return None
        pressed = keys.current_modifiers(exclude=name)
        for b in candidates:
            if set(b.modifiers) <= pressed:
                return b
        return None

    def _trigger(self, binding, name):
        with self._lock:
            task = self._tasks.get(name)
            if task is not None and task.is_alive():
                if binding.mode == "toggle":
                    task.stop()
                    self.notify("stopped", binding)
                # in the other modes, ignore the new press while the macro is running
                return
            ops = self.store.compiled(binding.macro)
            if ops is None:
                self.notify("error", f"Macro '{binding.macro}' is missing or has errors")
                return
            task = _Task(self, binding, ops, name)
            self._tasks[name] = task
        task.start()
        self.notify("run", binding)

    def _task_done(self, task):
        with self._lock:
            if self._tasks.get(task.trigger) is task:
                del self._tasks[task.trigger]
