#!/usr/bin/python3 -I
"""Step-by-step scroll probe: one direction at a time, started with Enter.

    sudo python3 tools/probe_scroll.py

Put the pointer over a page that can scroll in every direction (zoomed in,
not at an edge). Before each step the terminal says what will be sent and
what the text on the page should do. After each step type what you saw:
  m = the text moved as expected     n = nothing moved
  w = the text moved the WRONG way
At the end a summary is printed: paste it back.

Steps 5-8 send the high-resolution and the classic wheel events separately,
to find out which of the two the desktop ignores. Touches no keyboard.
"""

import sys
import time

try:
    from evdev import UInput, ecodes as e
except ImportError:
    sys.exit("python3-evdev is missing: sudo dnf install python3-evdev")

HI_V = getattr(e, "REL_WHEEL_HI_RES", 0x0B)
HI_H = getattr(e, "REL_HWHEEL_HI_RES", 0x0C)
LO_V, LO_H = e.REL_WHEEL, e.REL_HWHEEL
NOTCHES = 4  # per step: big enough to see, small enough not to hit an edge

# (label, what the text should do, hi-res code, classic code, sign, send hi, send classic)
STEPS = [
    ("DOWN, both event kinds", "text moves UP", HI_V, LO_V, -1, True, True),
    ("UP, both event kinds", "text moves DOWN", HI_V, LO_V, +1, True, True),
    ("RIGHT, both event kinds", "text moves LEFT", HI_H, LO_H, +1, True, True),
    ("LEFT, both event kinds", "text moves RIGHT", HI_H, LO_H, -1, True, True),
    ("LEFT, high-resolution only", "text moves RIGHT", HI_H, LO_H, -1, True, False),
    ("LEFT, classic only", "text moves RIGHT", HI_H, LO_H, -1, False, True),
    ("RIGHT, high-resolution only", "text moves LEFT", HI_H, LO_H, +1, True, False),
    ("RIGHT, classic only", "text moves LEFT", HI_H, LO_H, +1, False, True),
]


def send(ui, hi, lo, sign, use_hi, use_lo) -> str:
    """Send NOTCHES notches; return a one-line description of what was sent."""
    hi_total = lo_total = 0
    for notch in range(NOTCHES):
        for _ in range(12):                      # 12 x 10 units = 1 notch
            if use_hi:
                ui.write(e.EV_REL, hi, 10 * sign)
                hi_total += 10 * sign
            ui.syn()
            time.sleep(0.015)
        if use_lo:
            ui.write(e.EV_REL, lo, sign)
            lo_total += sign
            ui.syn()
    parts = []
    if use_hi:
        parts.append(f"{e.REL[hi]} total {hi_total:+d}")
    if use_lo:
        parts.append(f"{e.REL[lo]} total {lo_total:+d}")
    return ", ".join(parts)


def main() -> int:
    caps = {
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
        e.EV_REL: [e.REL_X, e.REL_Y, LO_V, LO_H, HI_V, HI_H],
    }
    try:
        ui = UInput(caps, name="mouselessCK Probe Mouse", bustype=e.BUS_VIRTUAL,
                    phys="mouselessck/probe")
    except (PermissionError, OSError) as exc:
        sys.exit(f"cannot open /dev/uinput ({exc}). Run with sudo.")

    results = []
    with ui:
        time.sleep(1.0)
        print(__doc__.split("\n\n")[2])
        for i, (label, expect, hi, lo, sign, use_hi, use_lo) in enumerate(STEPS, 1):
            print(f"\n--- STEP {i}/{len(STEPS)}: {label}")
            print(f"    expected: {expect}")
            input("    keep the pointer on the page, then press Enter... ")
            print("    sending:", send(ui, hi, lo, sign, use_hi, use_lo))
            seen = ""
            while seen not in ("m", "n", "w"):
                seen = input("    what did you see? [m]oved as expected / [n]othing / [w]rong way: ").strip().lower()
            results.append((i, label, {"m": "OK", "n": "NOTHING", "w": "WRONG WAY"}[seen]))

    print("\n===== SUMMARY (paste this back) =====")
    for i, label, verdict in results:
        print(f"{i}. {label:30} {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
