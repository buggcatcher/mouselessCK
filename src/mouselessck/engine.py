"""The mouselessCK state machine. Pure logic: no devices, no clock, no I/O.

The daemon feeds every key event from every grabbed keyboard into
Engine.on_key() and calls Engine.tick() at a fixed rate while the pointer is
moving. Both return a list of actions for the daemon to perform:

    ("key", src, code, value)   forward a key event to the clone of `src`
    ("guard", src)              tap a harmless key on the clone of `src`
    ("btn", button, value)      press or release a virtual mouse button
    ("rel", dx, dy)             move the virtual mouse
    ("wheel", v, h, lv, lh)     scroll: hi-res units and classic notches
    ("mode", on)                mouse mode changed

Invariants:
  * A key's release always goes where its press went (`routes`), whatever
    the mode is at release time. Nothing gets stuck.
  * In mouse mode, plain keys never reach applications. Esc, chords with
    Ctrl/Alt/Meta and non-typing keys (volume, media) do.
  * Leaving mouse mode releases every virtual mouse button.
"""

from __future__ import annotations

from . import keycodes as K
from .config import Config
from .motion import Motion

FWD = "forward"        # sent to applications
MOUSE = "mouse"        # consumed as a mouse control
SWALLOW = "swallow"    # dropped
TOGGLE = "toggle"      # the toggle key itself
PENDING = "pending"    # Shift held back in mouse mode (see _press)

Key = tuple  # (source id, key code)


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.on = False
        self.routes: dict[Key, str] = {}
        self.mods: dict[int, int] = {}            # modifier code -> holds
        self.dirs: dict[Key, tuple[int, int]] = {}
        self.scrolling: set[Key] = set()
        self.precise: set[Key] = set()
        self.buttons: dict[int, set[Key]] = {
            K.BTN_LEFT: set(), K.BTN_MIDDLE: set(), K.BTN_RIGHT: set(),
        }
        self.motion = Motion(cfg.pointer, cfg.scroll, cfg.rate_hz)

    # ----------------------------------------------------------------- input
    def on_key(self, src, code: int, value: int, now: float) -> list[tuple]:
        if value == 2:  # kernel autorepeat: the compositor repeats by itself
            return []
        key = (src, code)
        if value:
            return self._press(key, now)
        return self._release(key)

    def _held(self, codes) -> bool:
        return any(self.mods.get(c, 0) > 0 for c in codes)

    def _toggle_chord(self) -> bool:
        others = K.MODIFIERS - self.cfg.toggle_modifier_codes
        return self._held(self.cfg.toggle_modifier_codes) and not self._held(others)

    def _press(self, key: Key, now: float) -> list[tuple]:
        src, code = key
        acts: list[tuple] = []
        if key in self.routes:  # duplicate press without release: ignore
            return acts
        if code in K.MODIFIERS:
            self.mods[code] = self.mods.get(code, 0) + 1
        if code in self.cfg.precision_keys:
            self.precise.add(key)

        if code == self.cfg.toggle_key and self._toggle_chord():
            self.routes[key] = TOGGLE
            if self.cfg.toggle_modifier == "meta":
                acts.append(("guard", src))
            acts += self._set_mode(not self.on)
            return acts

        if code in K.MODIFIERS:
            if self.on and code in K.SHIFT:
                # In mouse mode Shift is held back: forwarding it at once
                # would turn clicks into Shift+clicks and vertical scrolling
                # into horizontal scrolling. It is released to applications
                # only if a chord or a passthrough key needs it.
                self.routes[key] = PENDING
                return acts
            self.routes[key] = FWD
            acts.append(("key", src, code, 1))
            return acts

        if not self.on:
            self.routes[key] = FWD
            acts.append(("key", src, code, 1))
            return acts

        # ---- mouse mode
        # What still reaches applications: chords with Ctrl/Alt/Meta (they
        # are deliberate), the configured passthrough keys (Esc), and keys
        # that cannot type text (volume, media, codes >= 128). A held-back
        # Shift is released first so that Ctrl+Shift+T stays Ctrl+Shift+T.
        if (self._held(K.CTRL | K.ALT | K.META)
                or code in self.cfg.passthrough
                or code in K.NON_TYPING or code >= 128):
            acts += self._flush_pending()
            self.routes[key] = FWD
            acts.append(("key", src, code, 1))
            return acts

        if code in self.cfg.directions:
            self.routes[key] = MOUSE
            self.dirs[key] = self.cfg.directions[code]
            return acts
        if code in self.cfg.scroll_keys:
            self.routes[key] = MOUSE
            self.scrolling.add(key)
            return acts
        if code in self.cfg.buttons:
            self.routes[key] = MOUSE
            holders = self.buttons[self.cfg.buttons[code]]
            if not holders:
                acts.append(("btn", self.cfg.buttons[code], 1))
            holders.add(key)
            return acts
        if code in self.cfg.precision_keys:
            self.routes[key] = MOUSE
            return acts

        # Every other key is dropped: this is what makes a forgotten mouse
        # mode harmless. The key code is not kept beyond its release.
        self.routes[key] = SWALLOW
        return acts

    def _release(self, key: Key) -> list[tuple]:
        src, code = key
        acts: list[tuple] = []
        if code in K.MODIFIERS and self.mods.get(code, 0) > 0:
            self.mods[code] -= 1
        self.precise.discard(key)
        route = self.routes.pop(key, None)

        if route is None:
            # Pressed before we grabbed the device: let the release through,
            # releasing an unpressed key is harmless.
            acts.append(("key", src, code, 0))
        elif route == FWD:
            acts.append(("key", src, code, 0))
        elif route == MOUSE:
            self.dirs.pop(key, None)
            self.scrolling.discard(key)
            for button, holders in self.buttons.items():
                if key in holders:
                    holders.discard(key)
                    if not holders:
                        acts.append(("btn", button, 0))
        # PENDING, TOGGLE and SWALLOW were never sent: nothing to release.
        if not self.dirs:
            self.motion.reset()
        return acts

    def _flush_pending(self) -> list[tuple]:
        acts = []
        for key, route in self.routes.items():
            if route == PENDING:
                self.routes[key] = FWD
                acts.append(("key", key[0], key[1], 1))
        return acts

    # ------------------------------------------------------------------ mode
    def _set_mode(self, on: bool) -> list[tuple]:
        if on == self.on:
            return []
        self.on = on
        acts: list[tuple] = [("mode", on)]
        if not on:
            for button, holders in self.buttons.items():
                if holders:
                    holders.clear()
                    acts.append(("btn", button, 0))
            self.dirs.clear()
            self.scrolling.clear()
            self.motion.reset()
            # A Shift still physically held becomes visible to applications.
            acts += self._flush_pending()
        return acts

    def force_off(self) -> list[tuple]:
        """Leave mouse mode (session locked, system suspending, shutdown)."""
        return self._set_mode(False)

    def drop_source(self, src) -> list[tuple]:
        """A device went away: forget its keys. Its clone is gone too, so
        key actions for it are dropped; mouse button releases are kept."""
        acts: list[tuple] = []
        for key in [k for k in self.routes if k[0] == src]:
            acts += self._release(key)
        return [a for a in acts if not (a[0] == "key" and a[1] == src)]

    # ---------------------------------------------------------------- motion
    def motion_active(self) -> bool:
        return self.on and bool(self.dirs)

    def tick(self, now: float) -> list[tuple]:
        if not self.motion_active():
            self.motion.reset()
            return []
        sx = sum(v[0] for v in self.dirs.values())
        sy = sum(v[1] for v in self.dirs.values())
        dx = (sx > 0) - (sx < 0)
        dy = (sy > 0) - (sy < 0)
        return self.motion.step(now, dx, dy, bool(self.scrolling), bool(self.precise))
