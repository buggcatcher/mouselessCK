"""mouselessckd: the system daemon.

Grabs every physical keyboard, republishes each one through a virtual clone,
and drives a virtual mouse while mouse mode is on. All decisions are made by
the pure Engine; this module only moves events between devices.

SECURITY - read this before changing anything in this file.
This process sees every key press, passwords included. The rules it follows:
  * Key codes never leave the process: no logging of key codes or of
    exception messages (they can contain a key code, e.g. "KeyError: 30"),
    no files, no network (the systemd unit also forbids it).
  * Keys are kept in memory only while physically held (routes, raw_held),
    then forgotten. Nothing is buffered or recorded.
  * The only outputs are the virtual clones, the virtual mouse and the
    one-way "on"/"off" state socket.
  * It must never leave the user without a keyboard: crashes release the
    grabs (kernel), hangs are killed (watchdog), bugs fail open
    (_fail_open), and both Shift + Esc always ends it (_panic_check).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
import traceback
from pathlib import Path

from evdev import InputDevice, UInput, ecodes

from . import __version__, devices, sdnotify, session
from . import keycodes as K
from .config import Config, load
from .engine import Engine
from .ipc import StateServer

log = logging.getLogger("mouselessck")

GRAB_POLL = 0.05       # seconds between checks for released keys before a grab
HOTPLUG_SETTLE = 0.3   # seconds to let udev finish with a new device
PANIC_CHORD = frozenset({K.KEY_LEFTSHIFT, K.KEY_RIGHTSHIFT, K.KEY_ESC})


def describe_error(exc: BaseException) -> str:
    """Exception type and code location only, NEVER str(exc).

    An exception message in the key path can contain the key code being
    processed (KeyError: 30 is the letter A). Logging it would put a
    keystroke in the journal, so only the type and the call stack are kept.
    """
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in reversed(frames))
    return f"{type(exc).__name__} at {where or 'unknown location'}"


class Proxy:
    """One grabbed keyboard interface and its virtual clone."""

    def __init__(self, dev: InputDevice, clone: UInput):
        self.dev = dev
        self.clone = clone
        self.path = dev.path
        self.keys = devices.key_caps(dev)
        self.leds = devices.has_leds(dev)


class Daemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.engine = Engine(cfg)
        self.proxies: dict[str, Proxy] = {}
        self.attaching: set[str] = set()
        self.mouse: UInput | None = None
        self.state = StateServer(cfg.socket_path)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.motion_task: asyncio.Task | None = None
        self.stopping = asyncio.Event()
        self.tasks: list[asyncio.Task] = []
        self.raw_held: set[tuple[str, int]] = set()  # (device, code) held, for the panic chord
        self.failed = False               # fail-open after an internal error
        self.exit_code = 0
        self.mode_reason: str | None = None  # why mouse mode changed, for the log

    # ------------------------------------------------------------ lifecycle
    async def run(self) -> int:
        self.loop = asyncio.get_running_loop()
        # Replace asyncio's default handler, which would log exception
        # messages (see describe_error) for errors in reader callbacks.
        self.loop.set_exception_handler(self._loop_error)
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.loop.add_signal_handler(sig, self.stopping.set)

        self.mouse = devices.make_mouse()
        await self.state.start()
        for dev in devices.candidates(self.cfg.ignore_devices):
            self.attaching.add(dev.path)
            self.tasks.append(asyncio.create_task(self._attach(dev)))
        self._start_hotplug()
        self.tasks.append(asyncio.create_task(session.watch(self._on_lock)))
        if (interval := sdnotify.watchdog_interval()) is not None:
            self.tasks.append(asyncio.create_task(self._watchdog(interval)))

        sdnotify.notify("READY=1\nSTATUS=mouse mode off")
        log.info("mouselessCK %s running", __version__)
        await self.stopping.wait()
        await self.shutdown()
        return self.exit_code

    async def shutdown(self) -> None:
        sdnotify.notify("STOPPING=1")
        self._set_off("service stopping")
        for task in self.tasks:
            task.cancel()
        for proxy in list(self.proxies.values()):
            self._detach(proxy, reason="shutdown")
        if self.mouse:
            self.mouse.close()
        await self.state.close()
        log.info("stopped")

    def _loop_error(self, _loop, context: dict) -> None:
        exc = context.get("exception")
        if exc is not None:
            log.error("unexpected error: %s", describe_error(exc))
        else:
            log.error("unexpected event-loop error")  # message omitted on purpose

    async def _watchdog(self, interval: float) -> None:
        # Pings come from the event loop itself: if the loop hangs, the pings
        # stop, systemd kills the process and the kernel releases the grabs.
        while True:
            sdnotify.notify("WATCHDOG=1")
            await asyncio.sleep(interval)

    # -------------------------------------------------------------- devices
    async def _attach(self, dev: InputDevice) -> None:
        clone = None
        try:
            # Grabbing while a key is down would hide its release from the
            # desktop and leave it stuck: wait until the keyboard is idle.
            while dev.active_keys():
                await asyncio.sleep(GRAB_POLL)
            # Create the clone BEFORE grabbing, so the desktop never sees a
            # moment with no keyboard. EVIOCGRAB makes this process the only
            # reader of the device: from now on keys reach the desktop only
            # through the clone. The kernel drops the grab automatically when
            # our file descriptor closes (exit, crash, kill).
            clone = devices.make_clone(dev)
            dev.grab()
        except Exception as exc:  # noqa: BLE001 - the device may vanish meanwhile
            # Device errors (EBUSY, ENODEV) carry no key data.
            log.warning("cannot take %s (%s): %s", dev.name, dev.path, exc)
            if clone is not None:
                clone.close()
            dev.close()
            return
        finally:
            self.attaching.discard(dev.path)

        proxy = Proxy(dev, clone)
        self.proxies[proxy.path] = proxy
        assert self.loop is not None
        self.loop.add_reader(dev.fd, self._read_device, proxy)
        self.loop.add_reader(clone.fd, self._read_clone, proxy)
        log.info("keyboard attached: %s (%s)", dev.name, dev.path)

    def _detach(self, proxy: Proxy, reason: str) -> None:
        if self.proxies.pop(proxy.path, None) is None:
            return
        assert self.loop is not None
        for fd in (proxy.dev.fd, proxy.clone.fd):
            try:
                self.loop.remove_reader(fd)
            except (ValueError, OSError):
                pass
        self._apply(self.engine.drop_source(proxy.path))
        # Forget this device's raw key state too: a key still physically held
        # when the keyboard goes away must not linger in the panic-chord set
        # (the engine's own state is cleared by drop_source above; raw_held is
        # the daemon's separate copy, read before any engine logic).
        self.raw_held = {held for held in self.raw_held if held[0] != proxy.path}
        for close in (proxy.dev.ungrab, proxy.clone.close, proxy.dev.close):
            try:
                close()
            except OSError:
                pass
        log.info("keyboard detached (%s): %s", reason, proxy.path)

    def _maybe_attach(self, path: str) -> None:
        if path in self.proxies or path in self.attaching:
            return
        try:
            dev = InputDevice(path)
        except OSError:
            return
        # Never grab our own virtual devices: that would feed our output back
        # into our input in an endless loop.
        if (devices.is_own(dev) or dev.name in self.cfg.ignore_devices
                or not devices.is_keyboard(dev)):
            dev.close()
            return
        self.attaching.add(path)
        self.tasks.append(asyncio.create_task(self._attach(dev)))

    def _start_hotplug(self) -> None:
        try:
            import pyudev
        except ImportError:
            log.warning("pyudev missing: rescanning for keyboards every 3 s")
            self.tasks.append(asyncio.create_task(self._rescan()))
            return
        monitor = pyudev.Monitor.from_netlink(pyudev.Context())
        monitor.filter_by(subsystem="input")
        monitor.start()
        assert self.loop is not None
        self.loop.add_reader(monitor.fileno(), self._on_udev, monitor)

    def _on_udev(self, monitor) -> None:
        while (device := monitor.poll(timeout=0)) is not None:
            node = device.device_node or ""
            if not node.startswith("/dev/input/event"):
                continue
            if device.action == "add":
                assert self.loop is not None
                self.loop.call_later(HOTPLUG_SETTLE, self._maybe_attach, node)
            elif device.action == "remove" and node in self.proxies:
                self._detach(self.proxies[node], reason="unplugged")

    async def _rescan(self) -> None:
        from evdev import list_devices
        while True:
            await asyncio.sleep(3)
            for path in list_devices():
                self._maybe_attach(path)

    # --------------------------------------------------------------- events
    def _read_device(self, proxy: Proxy) -> None:
        try:
            events = list(proxy.dev.read())
        except BlockingIOError:
            return
        except OSError:
            self._detach(proxy, reason="read error")
            return
        now = time.monotonic()
        for ev in events:
            if ev.type == ecodes.EV_KEY:
                # 1. The emergency chord is checked first, on raw events, so
                #    nothing below (engine, config) can prevent it.
                if self._panic_check(proxy.path, ev.code, ev.value):
                    return
                # 2. After an internal error every key passes straight through.
                if self.failed:
                    # Fail-open: the keyboard works as if we were not here.
                    if ev.value != 2:
                        self._write(proxy.clone, ev.type, ev.code, ev.value)
                    continue
                # 3. Normal path: the engine decides, _apply executes.
                try:
                    self._apply(self.engine.on_key(proxy.path, ev.code, ev.value, now))
                except Exception as exc:  # noqa: BLE001 - never leave a dead keyboard
                    self._fail_open("key handling", exc)
                    # The key that hit the bug is delivered too, not lost.
                    if ev.value != 2:
                        self._write(proxy.clone, ev.type, ev.code, ev.value)
            elif ev.type in (ecodes.EV_REL, ecodes.EV_ABS):
                # Knobs and wheels on keyboards (volume dials): pass through.
                self._write(proxy.clone, ev.type, ev.code, ev.value)
        self._kick_motion()

    # ----------------------------------------------------------- safety net
    def _panic_check(self, src: str, code: int, value: int) -> bool:
        """Both Shift keys + Esc held together: give the keyboards back and
        exit. Checked on raw events, before any mouselessCK logic, so it
        works even if that logic is broken.

        Keys are tracked per (device, code): unplugging a keyboard while a key
        is held, or holding the same modifier on a second keyboard, can no
        longer leave a phantom key behind (see _detach). The chord still spans
        keyboards, so the test is on the union of codes held anywhere."""
        if value == 1:
            self.raw_held.add((src, code))
        elif value == 0:
            self.raw_held.discard((src, code))
        if PANIC_CHORD <= {held_code for _, held_code in self.raw_held}:
            log.warning("emergency chord (both Shift + Esc): releasing keyboards and exiting")
            self.exit_code = 0  # a clean exit: systemd does not restart us
            self.stopping.set()
            return True
        return False

    def _fail_open(self, where: str, exc: BaseException) -> None:
        """An internal error must never leave the keyboard dead: switch to
        plain pass-through, drop mouse mode, and log the bug (type and code
        location only, see describe_error)."""
        if self.failed:
            return
        log.error("internal error in %s: %s; mouse mode disabled, keyboards pass through",
                  where, describe_error(exc))
        self.failed = True
        self.engine.on = False
        if self.mouse:
            for button in (K.BTN_LEFT, K.BTN_RIGHT, K.BTN_MIDDLE):
                self._write(self.mouse, ecodes.EV_KEY, button, 0)
        self.state.publish(False)
        sdnotify.notify("STATUS=pass-through only after an internal error (see the journal)")

    def _read_clone(self, proxy: Proxy) -> None:
        """The desktop sets keyboard LEDs (Caps Lock, Num Lock) on the clone;
        copy them to the real keyboard so its lights keep working."""
        try:
            for ev in proxy.clone.read():
                if ev.type == ecodes.EV_LED and proxy.leds:
                    proxy.dev.set_led(ev.code, ev.value)
        except BlockingIOError:
            pass
        except OSError:
            pass

    def _on_lock(self, reason: str) -> None:
        self._set_off(reason)

    def _set_off(self, reason: str) -> None:
        """Leave mouse mode for a reason other than Meta+M; the reason goes
        into the single "mouse mode off" log line."""
        self.mode_reason = reason
        try:
            self._apply(self.engine.force_off())
        finally:
            self.mode_reason = None

    # -------------------------------------------------------------- motion
    def _kick_motion(self) -> None:
        if self.engine.motion_active() and (self.motion_task is None or self.motion_task.done()):
            self.motion_task = asyncio.create_task(self._motion_loop())

    async def _motion_loop(self) -> None:
        period = 1.0 / self.cfg.rate_hz
        try:
            while not self.failed and self.engine.motion_active():
                self._apply(self.engine.tick(time.monotonic()))
                await asyncio.sleep(period)
            self.engine.tick(time.monotonic())  # resets the ramp
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._fail_open("pointer motion", exc)

    # ------------------------------------------------------------- actions
    @staticmethod
    def _write(device: UInput, etype: int, code: int, value: int) -> None:
        try:
            device.write(etype, code, value)
            device.syn()
        except OSError as exc:
            # Never log `code`/`value` here: they are the key being typed.
            log.warning("write to a virtual device failed: %s", type(exc).__name__)

    def _apply(self, actions: list[tuple]) -> None:
        mouse = self.mouse
        for act in actions:
            kind = act[0]
            if kind == "key":
                proxy = self.proxies.get(act[1])
                if proxy:
                    self._write(proxy.clone, ecodes.EV_KEY, act[2], act[3])
            elif kind == "guard":
                self._guard(act[1])
            elif kind == "btn" and mouse:
                self._write(mouse, ecodes.EV_KEY, act[1], act[2])
            elif kind == "rel" and mouse:
                if act[1]:
                    mouse.write(ecodes.EV_REL, K.REL_X, act[1])
                if act[2]:
                    mouse.write(ecodes.EV_REL, K.REL_Y, act[2])
                mouse.syn()
            elif kind == "wheel" and mouse:
                _, v, h, lv, lh = act
                for code, value in ((K.REL_WHEEL_HI_RES, v), (K.REL_HWHEEL_HI_RES, h),
                                    (K.REL_WHEEL, lv), (K.REL_HWHEEL, lh)):
                    if value:
                        mouse.write(ecodes.EV_REL, code, value)
                mouse.syn()
            elif kind == "mode":
                on = act[1]
                self.state.publish(on)
                sdnotify.notify(f"STATUS=mouse mode {'on' if on else 'off'}")
                reason = f" ({self.mode_reason})" if self.mode_reason else ""
                log.info("mouse mode %s%s", "on" if on else "off", reason)

    def _guard(self, src: str) -> None:
        """Tap a harmless key (F24 by default) while Meta is held, so KDE does
        not treat the Meta release as a lone Meta press and open the launcher.
        This is the only key mouselessCK ever invents."""
        proxy = self.proxies.get(src)
        if proxy is None:
            return
        for code in self.cfg.guard_keys:
            if code in proxy.keys:
                self._write(proxy.clone, ecodes.EV_KEY, code, 1)
                self._write(proxy.clone, ecodes.EV_KEY, code, 0)
                return


# ------------------------------------------------------------------- CLI
def list_keyboards(cfg: Config) -> int:
    print("Keyboards mouselessCK would take over:")
    found = devices.candidates(cfg.ignore_devices)
    for dev in found:
        print(f"  {dev.path:20} {dev.name}  [{dev.phys}]")
        dev.close()
    if not found:
        print("  none (are you root or in the 'input' group?)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mouselessckd", description=__doc__.splitlines()[0])
    parser.add_argument("-c", "--config", help="configuration file (default /etc/mouselessck/config.toml)")
    parser.add_argument("--list", action="store_true", help="list the keyboards that would be grabbed and exit")
    parser.add_argument("--check-config", action="store_true", help="validate the configuration and exit")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    # The journal gets device and mode changes only, never key codes.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s",
                        stream=sys.stderr)
    try:
        cfg = load(args.config)
    except (OSError, ValueError) as exc:
        print(f"mouselessckd: configuration error: {exc}", file=sys.stderr)
        return 2
    if args.check_config:
        print("configuration OK")
        return 0
    if args.list:
        return list_keyboards(cfg)
    try:
        return asyncio.run(Daemon(cfg).run())
    except PermissionError as exc:
        print(f"mouselessckd: permission denied ({exc}). Run as root or as the "
              "mouselessck service user.", file=sys.stderr)
        return 1
