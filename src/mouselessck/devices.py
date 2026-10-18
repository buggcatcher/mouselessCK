"""Keyboard discovery, virtual clones and the virtual mouse (python-evdev)."""

from __future__ import annotations

import logging

from evdev import InputDevice, UInput, ecodes, list_devices

from . import keycodes as K

log = logging.getLogger(__name__)

PHYS_PREFIX = "mouselessck"
MOUSE_NAME = "mouselessCK Virtual Mouse"


def is_own(dev: InputDevice) -> bool:
    """True for devices this program created. They are never grabbed,
    otherwise our output would loop back into our input. A real keyboard
    cannot fake this: `phys` of USB, Bluetooth and i8042 devices is set by
    the kernel driver, not by the device."""
    return (dev.phys or "").startswith(PHYS_PREFIX)


def is_keyboard(dev: InputDevice) -> bool:
    """A keyboard here is any device that can type every letter A-Z.

    This catches both interfaces of keyboards that split their keys (such as
    6KRO and NKRO channels) and skips power buttons, lid switches, hotkey
    and media-only devices, mice and touchpads.
    """
    keys = set(dev.capabilities().get(ecodes.EV_KEY, []))
    return K.LETTERS <= keys


def candidates(ignore: frozenset[str]) -> list[InputDevice]:
    found = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        if is_own(dev) or dev.name in ignore or not is_keyboard(dev):
            dev.close()
            continue
        found.append(dev)
    return found


def make_clone(dev: InputDevice) -> UInput:
    """A virtual twin with the same name, ids and capabilities.

    Keeping name, vendor, product and bus type means the desktop treats the
    clone like the original: KDE per-device settings, keyboard layout, and
    libinput's pairing of an internal keyboard with the touchpad
    (disable-while-typing) keep working. Only `phys` differs, so we can
    recognise our own devices.
    """
    info = dev.info
    # Writes go only through /dev/uinput, which the udev rule opens to the
    # service group alone. The clone inherits capabilities, never data.
    return UInput.from_device(
        dev,
        filtered_types=(ecodes.EV_SYN, ecodes.EV_FF, ecodes.EV_MSC, ecodes.EV_REP),
        name=dev.name,
        vendor=info.vendor,
        product=info.product,
        version=info.version,
        bustype=info.bustype,
        phys=f"{PHYS_PREFIX}/{dev.phys or dev.path}",
    )


def make_mouse() -> UInput:
    caps = {
        ecodes.EV_KEY: [K.BTN_LEFT, K.BTN_RIGHT, K.BTN_MIDDLE],
        ecodes.EV_REL: [K.REL_X, K.REL_Y, K.REL_WHEEL, K.REL_HWHEEL,
                        K.REL_WHEEL_HI_RES, K.REL_HWHEEL_HI_RES],
    }
    return UInput(caps, name=MOUSE_NAME, vendor=0x0001, product=0x0001,
                  version=1, bustype=ecodes.BUS_VIRTUAL,
                  phys=f"{PHYS_PREFIX}/mouse")


def key_caps(dev: InputDevice) -> frozenset[int]:
    return frozenset(dev.capabilities().get(ecodes.EV_KEY, []))


def has_leds(dev: InputDevice) -> bool:
    return ecodes.EV_LED in dev.capabilities()
