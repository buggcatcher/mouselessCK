#!/usr/bin/python3 -I
"""Reversal probe: does a quick change of scroll direction reach libinput?

    sudo dnf install libinput-utils     # provides the `libinput` command
    sudo python3 tools/probe_reverse.py

The probe sends scroll bursts with the same events as the first probe, and at
the same time reads what libinput (the layer under KDE) makes of them. For
every burst it prints how much was SENT and how much libinput DELIVERED.

  * delivered == sent for every burst   -> the system is fine; the lost
    scroll happens in the application (browser, editor...)
  * delivered == 0 for a burst          -> libinput drops it; mouselessCK
    must work around it

No looking needed, but keep the pointer over a page if you want to watch.
Touches no keyboard.
"""

import re
import shutil
import subprocess
import sys
import threading
import time

try:
    from evdev import UInput, ecodes as e
except ImportError:
    sys.exit("python3-evdev is missing: sudo dnf install python3-evdev")

HI_V = getattr(e, "REL_WHEEL_HI_RES", 0x0B)
HI_H = getattr(e, "REL_HWHEEL_HI_RES", 0x0C)
NOTCHES = 3
SCROLL_RE = re.compile(
    r"vert\s+(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)\*?\s+horiz\s+(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)")

# Each scenario: (name, axis, first sign, pause in seconds, second sign)
SCENARIOS = [
    ("vertical   DOWN then UP,    0.3 s apart", "v", -1, 0.3, +1),
    ("horizontal RIGHT then LEFT, 0.3 s apart", "h", +1, 0.3, -1),
    ("horizontal LEFT then RIGHT, 0.3 s apart", "h", -1, 0.3, +1),
    ("horizontal RIGHT then LEFT, 2.0 s apart", "h", +1, 2.0, -1),
]
NAMES = {(+1, "v"): "UP", (-1, "v"): "DOWN", (+1, "h"): "RIGHT", (-1, "h"): "LEFT"}


def burst(ui, axis: str, sign: int) -> int:
    """Same pattern as probe_mouse.py: hi-res and classic in the same frame.
    Returns the hi-res units sent (120 per notch)."""
    hi, lo = (HI_V, e.REL_WHEEL) if axis == "v" else (HI_H, e.REL_HWHEEL)
    acc = sent = 0
    for _ in range(12 * NOTCHES):
        ui.write(e.EV_REL, hi, 10 * sign)
        sent += 10 * sign
        acc += 10
        if acc >= 120:
            ui.write(e.EV_REL, lo, sign)
            acc -= 120
        ui.syn()
        time.sleep(0.02)
    return sent


class LibinputReader:
    """Runs `libinput debug-events` on our own virtual device only and keeps
    (time, vert v120, horiz v120) for every scroll event it reports."""

    def __init__(self, device_path: str):
        cmd = ["libinput", "debug-events", "--device", device_path]
        if shutil.which("stdbuf"):
            cmd = ["stdbuf", "-oL", *cmd]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
        self.events: list[tuple[float, float, float]] = []
        self.raw: list[str] = []
        self.ready = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            now = time.monotonic()
            if "DEVICE_ADDED" in line:
                self.ready.set()
            if "SCROLL" in line:
                self.raw.append(line.rstrip())
                m = SCROLL_RE.search(line)
                if m:
                    self.events.append((now, float(m.group(2)), float(m.group(4))))

    def total(self, start: float, end: float, axis: str) -> float:
        """Delivered amount in the SAME sign convention as the kernel events.
        libinput reports vertical scrolling with positive = down, the kernel
        uses positive = up, so the vertical sum is negated."""
        i = 1 if axis == "v" else 2
        value = sum(ev[i] for ev in self.events if start <= ev[0] <= end)
        return -value if axis == "v" else value

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:
    if not shutil.which("libinput"):
        sys.exit("the `libinput` command is missing: sudo dnf install libinput-utils")
    caps = {
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
        e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL, HI_V, HI_H],
    }
    try:
        ui = UInput(caps, name="mouselessCK Probe Mouse", bustype=e.BUS_VIRTUAL,
                    phys="mouselessck/probe")
    except (PermissionError, OSError) as exc:
        sys.exit(f"cannot open /dev/uinput ({exc}). Run with sudo.")

    rows = []
    with ui:
        time.sleep(0.5)
        reader = LibinputReader(ui.device.path)
        if not reader.ready.wait(5):
            reader.stop()
            sys.exit("libinput did not open the probe device. Output:\n" + "\n".join(reader.raw[:10]))
        time.sleep(0.5)
        try:
            for name, axis, first, pause, second in SCENARIOS:
                print(f"--- {name}")
                for sign in (first, second):
                    t0 = time.monotonic()
                    sent = burst(ui, axis, sign)
                    time.sleep(0.25)              # let libinput report the tail
                    got = reader.total(t0, time.monotonic(), axis)
                    rows.append((name, NAMES[(sign, axis)], sent, got))
                    print(f"    {NAMES[(sign, axis)]:5} sent {sent:+5d}   libinput delivered {got:+7.0f}")
                    if sign == first:
                        time.sleep(max(0.0, pause - 0.25))
                time.sleep(2.0)
        finally:
            reader.stop()

    print("\n===== SUMMARY (paste this back) =====")
    for name, label, sent, got in rows:
        if abs(got - sent) <= abs(sent) * 0.25:
            verdict = "OK"
        elif abs(got) < 1:
            verdict = "LOST"
        elif got * sent < 0:
            verdict = "WRONG WAY"
        else:
            verdict = "PARTIAL"
        print(f"{name:42} {label:5} sent {sent:+5d} delivered {got:+7.0f}  {verdict}")
    if not reader.events and reader.raw:
        print("\n(could not read libinput's numbers; first raw lines:)")
        print("\n".join(reader.raw[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
