"""Configuration loading for mouselessCK.

The file is TOML (default /etc/mouselessck/config.toml). Every value has a
default, so an empty or missing file gives the documented behaviour.
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import keycodes as K

DEFAULT_PATH = Path("/etc/mouselessck/config.toml")

DEFAULTS: dict = {
    "toggle": {
        # Exactly this modifier (left or right) plus the key toggles mouse mode.
        "modifier": "meta",
        "key": "KEY_M",
        # Tapped while Meta is down so KDE does not treat the release as a
        # lone Meta press (which opens the application launcher).
        "guard_keys": ["KEY_F24", "KEY_LEFTCTRL"],
    },
    "keys": {
        "up": ["KEY_W", "KEY_UP"],
        "down": ["KEY_S", "KEY_DOWN"],
        "left": ["KEY_A", "KEY_LEFT"],
        "right": ["KEY_D", "KEY_RIGHT"],
        "scroll": ["KEY_SPACE"],
        "precision": ["KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"],
        "left_click": ["KEY_J", "KEY_ENTER"],
        "middle_click": ["KEY_K"],
        "right_click": ["KEY_L"],
        "passthrough": ["KEY_ESC"],
    },
    "pointer": {
        "rate_hz": 100,
        "start_speed": 120.0,   # pixels per second when a key is first pressed
        "max_speed": 1600.0,    # pixels per second after accel_time
        "accel_time": 0.6,      # seconds to go from start to max speed
        "precision_factor": 0.25,
    },
    "scroll": {
        "start_speed": 4.0,     # wheel notches per second
        "max_speed": 30.0,
        "accel_time": 0.8,
        "precision_factor": 0.25,
    },
    "devices": {
        # Device names left alone (exact match).
        "ignore": [],
    },
    "ipc": {
        "socket": "/run/mouselessck/state.sock",
    },
    "indicator": {
        "corner": "bottom-right",  # bottom-right, bottom-left, top-right, top-left
        "size": 36,
        "margin": 12,
        "opacity": 0.75,
    },
}

CORNERS = {"bottom-right", "bottom-left", "top-right", "top-left"}
MODIFIER_SETS = {"meta": K.META, "ctrl": K.CTRL, "alt": K.ALT}


@dataclass
class Speed:
    start_speed: float
    max_speed: float
    accel_time: float
    precision_factor: float


@dataclass
class Config:
    toggle_modifier: str
    toggle_key: int
    guard_keys: list[int]
    directions: dict[int, tuple[int, int]]
    scroll_keys: frozenset[int]
    precision_keys: frozenset[int]
    buttons: dict[int, int]
    passthrough: frozenset[int]
    rate_hz: int
    pointer: Speed
    scroll: Speed
    ignore_devices: frozenset[str]
    socket_path: str
    indicator: dict = field(default_factory=dict)

    @property
    def toggle_modifier_codes(self) -> frozenset[int]:
        return MODIFIER_SETS[self.toggle_modifier]


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _codes(names) -> list[int]:
    if isinstance(names, str):
        names = [names]
    return [K.code_for(n) for n in names]


def _speed(section: dict) -> Speed:
    speed = Speed(
        start_speed=float(section["start_speed"]),
        max_speed=float(section["max_speed"]),
        accel_time=float(section["accel_time"]),
        precision_factor=float(section["precision_factor"]),
    )
    if speed.start_speed <= 0 or speed.max_speed < speed.start_speed:
        raise ValueError("speeds must be positive and max_speed >= start_speed")
    if speed.accel_time < 0 or not 0 < speed.precision_factor <= 1:
        raise ValueError("accel_time must be >= 0 and precision_factor in (0, 1]")
    return speed


def build(raw: dict | None = None) -> Config:
    """Build a validated Config from a (possibly partial) dictionary."""
    data = _merge(DEFAULTS, raw or {})
    toggle, keys = data["toggle"], data["keys"]

    modifier = str(toggle["modifier"]).lower()
    if modifier not in MODIFIER_SETS:
        raise ValueError(f"toggle.modifier must be one of {sorted(MODIFIER_SETS)}")

    directions: dict[int, tuple[int, int]] = {}
    for name, vector in (("up", (0, -1)), ("down", (0, 1)),
                         ("left", (-1, 0)), ("right", (1, 0))):
        for code in _codes(keys[name]):
            directions[code] = vector

    buttons: dict[int, int] = {}
    for name, button in (("left_click", K.BTN_LEFT), ("middle_click", K.BTN_MIDDLE),
                         ("right_click", K.BTN_RIGHT)):
        for code in _codes(keys[name]):
            buttons[code] = button

    toggle_key = K.code_for(toggle["key"])
    mapped = set(directions) | set(buttons) | set(_codes(keys["scroll"]))
    if toggle_key in mapped:
        raise ValueError("the toggle key cannot also be a mouse key")

    indicator = dict(data["indicator"])
    if indicator["corner"] not in CORNERS:
        raise ValueError(f"indicator.corner must be one of {sorted(CORNERS)}")

    # The daemon deletes and recreates this path at start-up, so it must be a
    # plain absolute path under /run (in practice its RuntimeDirectory).
    socket_path = str(data["ipc"]["socket"])
    if not socket_path.startswith("/run/") or ".." in socket_path.split("/"):
        raise ValueError("ipc.socket must be an absolute path under /run/")

    rate = int(data["pointer"]["rate_hz"])
    if not 20 <= rate <= 500:
        raise ValueError("pointer.rate_hz must be between 20 and 500")

    return Config(
        toggle_modifier=modifier,
        toggle_key=toggle_key,
        guard_keys=_codes(toggle["guard_keys"]),
        directions=directions,
        scroll_keys=frozenset(_codes(keys["scroll"])),
        precision_keys=frozenset(_codes(keys["precision"])),
        buttons=buttons,
        passthrough=frozenset(_codes(keys["passthrough"])),
        rate_hz=rate,
        pointer=_speed(data["pointer"]),
        scroll=_speed(data["scroll"]),
        ignore_devices=frozenset(data["devices"]["ignore"]),
        socket_path=socket_path,
        indicator=indicator,
    )


def load(path: str | Path | None = None) -> Config:
    """Load the configuration file; a missing file means all defaults.

    tomllib only parses data (no code execution), and every value is
    validated in build(). The file is owned by root and read-only for the
    service, so a user cannot change the keys the daemon reacts to."""
    file = Path(path) if path else DEFAULT_PATH
    raw: dict = {}
    if file.exists():
        with file.open("rb") as handle:
            raw = tomllib.load(handle)
    elif path:
        raise FileNotFoundError(file)
    return build(raw)
