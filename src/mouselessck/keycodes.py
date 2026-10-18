"""Linux input event codes used by mouselessCK.

Values come from <linux/input-event-codes.h>. They are duplicated here so the
pure engine and the tests do not depend on python-evdev. Any other key name
accepted by python-evdev can still be used in the configuration file.
"""

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
EV_MSC = 0x04
EV_LED = 0x11
EV_REP = 0x14
EV_FF = 0x15

REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
REL_WHEEL_HI_RES = 0x0B
REL_HWHEEL_HI_RES = 0x0C

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

NAMES = {
    "KEY_ESC": 1,
    "KEY_1": 2, "KEY_2": 3, "KEY_3": 4, "KEY_4": 5, "KEY_5": 6,
    "KEY_6": 7, "KEY_7": 8, "KEY_8": 9, "KEY_9": 10, "KEY_0": 11,
    "KEY_MINUS": 12, "KEY_EQUAL": 13, "KEY_BACKSPACE": 14, "KEY_TAB": 15,
    "KEY_Q": 16, "KEY_W": 17, "KEY_E": 18, "KEY_R": 19, "KEY_T": 20,
    "KEY_Y": 21, "KEY_U": 22, "KEY_I": 23, "KEY_O": 24, "KEY_P": 25,
    "KEY_LEFTBRACE": 26, "KEY_RIGHTBRACE": 27, "KEY_ENTER": 28,
    "KEY_LEFTCTRL": 29,
    "KEY_A": 30, "KEY_S": 31, "KEY_D": 32, "KEY_F": 33, "KEY_G": 34,
    "KEY_H": 35, "KEY_J": 36, "KEY_K": 37, "KEY_L": 38,
    "KEY_SEMICOLON": 39, "KEY_APOSTROPHE": 40, "KEY_GRAVE": 41,
    "KEY_LEFTSHIFT": 42, "KEY_BACKSLASH": 43,
    "KEY_Z": 44, "KEY_X": 45, "KEY_C": 46, "KEY_V": 47, "KEY_B": 48,
    "KEY_N": 49, "KEY_M": 50,
    "KEY_COMMA": 51, "KEY_DOT": 52, "KEY_SLASH": 53, "KEY_RIGHTSHIFT": 54,
    "KEY_KPASTERISK": 55, "KEY_LEFTALT": 56, "KEY_SPACE": 57, "KEY_CAPSLOCK": 58,
    "KEY_F1": 59, "KEY_F2": 60, "KEY_F3": 61, "KEY_F4": 62, "KEY_F5": 63,
    "KEY_F6": 64, "KEY_F7": 65, "KEY_F8": 66, "KEY_F9": 67, "KEY_F10": 68,
    "KEY_NUMLOCK": 69, "KEY_SCROLLLOCK": 70,
    "KEY_102ND": 86, "KEY_F11": 87, "KEY_F12": 88,
    "KEY_KPENTER": 96, "KEY_RIGHTCTRL": 97, "KEY_KPSLASH": 98, "KEY_SYSRQ": 99,
    "KEY_RIGHTALT": 100,
    "KEY_HOME": 102, "KEY_UP": 103, "KEY_PAGEUP": 104, "KEY_LEFT": 105,
    "KEY_RIGHT": 106, "KEY_END": 107, "KEY_DOWN": 108, "KEY_PAGEDOWN": 109,
    "KEY_INSERT": 110, "KEY_DELETE": 111,
    "KEY_MUTE": 113, "KEY_VOLUMEDOWN": 114, "KEY_VOLUMEUP": 115, "KEY_POWER": 116,
    "KEY_PAUSE": 119,
    "KEY_LEFTMETA": 125, "KEY_RIGHTMETA": 126, "KEY_COMPOSE": 127,
    "KEY_F13": 183, "KEY_F14": 184, "KEY_F15": 185, "KEY_F16": 186,
    "KEY_F17": 187, "KEY_F18": 188, "KEY_F19": 189, "KEY_F20": 190,
    "KEY_F21": 191, "KEY_F22": 192, "KEY_F23": 193, "KEY_F24": 194,
    "KEY_UNKNOWN": 240,
    "BTN_LEFT": BTN_LEFT, "BTN_RIGHT": BTN_RIGHT, "BTN_MIDDLE": BTN_MIDDLE,
}

globals().update(NAMES)

CTRL = frozenset({NAMES["KEY_LEFTCTRL"], NAMES["KEY_RIGHTCTRL"]})
SHIFT = frozenset({NAMES["KEY_LEFTSHIFT"], NAMES["KEY_RIGHTSHIFT"]})
ALT = frozenset({NAMES["KEY_LEFTALT"], NAMES["KEY_RIGHTALT"]})
META = frozenset({NAMES["KEY_LEFTMETA"], NAMES["KEY_RIGHTMETA"]})
MODIFIERS = CTRL | SHIFT | ALT | META

LETTERS = frozenset(NAMES["KEY_" + c] for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Keys that never type text and always reach applications, even in mouse
# mode: volume, mute and power. Every code from 128 up (media, application
# and F13-F24 keys) is treated the same way by the engine.
NON_TYPING = frozenset({
    NAMES["KEY_MUTE"], NAMES["KEY_VOLUMEDOWN"],
    NAMES["KEY_VOLUMEUP"], NAMES["KEY_POWER"],
})


def code_for(name: str) -> int:
    """Return the event code for a key name such as "KEY_W"."""
    key = name.strip().upper()
    if key in NAMES:
        return NAMES[key]
    try:  # fall back to python-evdev's complete table when it is installed
        from evdev import ecodes
    except ImportError:
        ecodes = None
    if ecodes is not None:
        value = ecodes.ecodes.get(key)
        if isinstance(value, int):
            return value
    raise ValueError(f"unknown key name: {name!r}")
