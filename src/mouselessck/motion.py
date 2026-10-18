"""Pointer and scroll motion: a speed ramp integrated over time.

A key tap moves a little, holding it accelerates linearly from start_speed to
max_speed over accel_time seconds. Fractions are accumulated so slow speeds
still move smoothly. Scrolling is emitted in high-resolution wheel units
(120 per notch) plus classic notches for older applications.
"""

from __future__ import annotations

import math

from .config import Speed

HI_RES_PER_NOTCH = 120
MAX_STEP = 0.05  # seconds; caps the jump after a stall


def ramp(speed: Speed, held: float) -> float:
    if speed.accel_time <= 0:
        return speed.max_speed
    frac = min(1.0, max(0.0, held) / speed.accel_time)
    return speed.start_speed + (speed.max_speed - speed.start_speed) * frac


class Motion:
    def __init__(self, pointer: Speed, scroll: Speed, rate_hz: int):
        self.pointer = pointer
        self.scroll = scroll
        self.period = 1.0 / rate_hz
        self.reset()

    def reset(self) -> None:
        self.t0: float | None = None
        self.last: float | None = None
        self.mode: str | None = None
        self.acc_x = self.acc_y = 0.0
        self.acc_v = self.acc_h = 0.0
        self.notch_v = self.notch_h = 0

    def step(self, now: float, dx: int, dy: int, scrolling: bool,
             precision: bool) -> list[tuple]:
        """Advance to `now` and return the actions to emit."""
        mode = "scroll" if scrolling else "pointer"
        if self.t0 is None or self.mode != mode:
            self.reset()
            self.mode = mode
            self.t0 = now
            self.last = now - self.period  # the first tick moves at once
        dt = min(MAX_STEP, max(0.0, now - self.last))
        self.last = now
        if dx == 0 and dy == 0:
            return []

        norm = math.sqrt(0.5) if dx and dy else 1.0
        speed_cfg = self.scroll if scrolling else self.pointer
        speed = ramp(speed_cfg, now - self.t0)
        if precision:
            speed *= speed_cfg.precision_factor

        if not scrolling:
            self.acc_x += dx * norm * speed * dt
            self.acc_y += dy * norm * speed * dt
            ix, iy = int(self.acc_x), int(self.acc_y)
            self.acc_x -= ix
            self.acc_y -= iy
            return [("rel", ix, iy)] if ix or iy else []

        units = speed * HI_RES_PER_NOTCH * dt * norm
        self.acc_v += -dy * units  # wheel up (positive) when moving up
        self.acc_h += dx * units   # horizontal wheel right is positive
        iv, ih = int(self.acc_v), int(self.acc_h)
        self.acc_v -= iv
        self.acc_h -= ih
        self.notch_v += iv
        self.notch_h += ih
        lv = int(self.notch_v / HI_RES_PER_NOTCH)
        lh = int(self.notch_h / HI_RES_PER_NOTCH)
        self.notch_v -= lv * HI_RES_PER_NOTCH
        self.notch_h -= lh * HI_RES_PER_NOTCH
        if iv or ih or lv or lh:
            return [("wheel", iv, ih, lv, lh)]
        return []
