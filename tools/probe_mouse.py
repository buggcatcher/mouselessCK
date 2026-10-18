#!/usr/bin/python3 -I
"""Phase 0 probe: check that your desktop accepts a virtual mouse.

Run it BEFORE installing anything else:

    sudo dnf install python3-evdev
    sudo python3 tools/probe_mouse.py

It creates a temporary virtual mouse, then
  1. moves the pointer around a 200 px square,
  2. scrolls down then up three notches in high-resolution steps,
  3. scrolls right then left,
and removes the device. Open a long web page first to see the scrolling.
It touches no keyboard and changes nothing on the system.

    sudo python3 tools/probe_mouse.py --hscroll

runs only a slow, labelled horizontal test (left, right, left, right) to
check the direction of horizontal scrolling. Put the pointer over a page
that can scroll sideways and is NOT at its left edge.
"""

import sys
import time

try:
    from evdev import UInput, ecodes as e
except ImportError:
    sys.exit("python3-evdev is missing: sudo dnf install python3-evdev")

REL_WHEEL_HI_RES = getattr(e, "REL_WHEEL_HI_RES", 0x0B)
REL_HWHEEL_HI_RES = getattr(e, "REL_HWHEEL_HI_RES", 0x0C)


def hscroll_test(ui, scroll) -> None:
    """Each step is announced, then waits 2 s, so browsers end their wheel
    'transaction' and every step starts fresh."""
    print("Horizontal test. Watch the page; each step lasts about 1 second.")
    for label, direction in (("LEFT", -1), ("RIGHT", 1), ("LEFT", -1), ("RIGHT", 1)):
        time.sleep(2.0)
        print(f"  now scrolling the view {label} (REL_HWHEEL {direction:+d})")
        for _ in range(2):  # 6 notches in total
            scroll(REL_HWHEEL_HI_RES, e.REL_HWHEEL, direction)


def main() -> int:
    hscroll_only = "--hscroll" in sys.argv[1:]
    caps = {
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
        e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL,
                   REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES],
    }
    try:
        ui = UInput(caps, name="mouselessCK Probe Mouse", bustype=e.BUS_VIRTUAL,
                    phys="mouselessck/probe")
    except (PermissionError, OSError) as exc:
        sys.exit(f"cannot open /dev/uinput ({exc}). Run with sudo.")

    with ui:
        print("Virtual mouse created; waiting 1 s for the desktop to pick it up...")
        time.sleep(1.0)

        def scroll(code_hi, code_lo, direction):
            acc = 0
            for _ in range(36):            # 3 notches = 360 units in 10-unit steps
                ui.write(e.EV_REL, code_hi, 10 * direction)
                acc += 10
                if acc >= 120:
                    ui.write(e.EV_REL, code_lo, direction)
                    acc -= 120
                ui.syn()
                time.sleep(0.02)

        if hscroll_only:
            hscroll_test(ui, scroll)
            print("Done. Tell me which steps moved the page, and in which direction.")
            return 0

        print("1/3 Moving the pointer around a square")
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            for _ in range(50):
                ui.write(e.EV_REL, e.REL_X, dx * 4)
                ui.write(e.EV_REL, e.REL_Y, dy * 4)
                ui.syn()
                time.sleep(0.01)

        print("2/3 Scrolling down, then up")
        scroll(REL_WHEEL_HI_RES, e.REL_WHEEL, -1)
        time.sleep(0.3)
        scroll(REL_WHEEL_HI_RES, e.REL_WHEEL, 1)

        print("3/3 Scrolling right, then left")
        scroll(REL_HWHEEL_HI_RES, e.REL_HWHEEL, 1)
        time.sleep(0.3)
        scroll(REL_HWHEEL_HI_RES, e.REL_HWHEEL, -1)

    print("Done. If the pointer moved and the page scrolled smoothly, phase 0 passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
