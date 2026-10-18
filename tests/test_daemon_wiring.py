"""Daemon wiring with fake devices: checks that engine actions reach the
right virtual device, without needing /dev/uinput or real keyboards."""

import asyncio
from types import SimpleNamespace

import pytest

evdev = pytest.importorskip("evdev")
from evdev import ecodes  # noqa: E402

from mouselessck import keycodes as K  # noqa: E402
from mouselessck.config import build  # noqa: E402
from mouselessck.daemon import Daemon, Proxy  # noqa: E402


class FakeUInput:
    def __init__(self):
        self.events, self.fd, self.queue, self.closed = [], -1, [], False

    def write(self, etype, code, value):
        self.events.append((etype, code, value))

    def syn(self):
        self.events.append("syn")

    def read(self):
        if not self.queue:
            raise BlockingIOError
        out, self.queue = self.queue, []
        return iter(out)

    def close(self):
        self.closed = True


class FakeDev(FakeUInput):
    def __init__(self, path, keys, leds=True):
        super().__init__()
        self.path, self.name, self.phys = path, "Fake Keyboard", "usb-fake/input0"
        self.caps = {ecodes.EV_KEY: sorted(keys)}
        if leds:
            self.caps[ecodes.EV_LED] = [0, 1, 2]
        self.leds_set = []

    def capabilities(self):
        return self.caps

    def set_led(self, code, value):
        self.leds_set.append((code, value))

    def ungrab(self):
        pass


def ev(etype, code, value):
    return SimpleNamespace(type=etype, code=code, value=value)


@pytest.fixture
def setup():
    d = Daemon(build())
    d.mouse = FakeUInput()
    d.loop = SimpleNamespace(remove_reader=lambda fd: None)
    published = []
    d.state.publish = published.append
    keys = set(K.LETTERS) | {K.KEY_LEFTMETA, K.KEY_F24, K.KEY_ENTER, K.KEY_SPACE, K.KEY_LEFTCTRL}
    dev, clone = FakeDev("/dev/input/event14", keys), FakeUInput()
    proxy = Proxy(dev, clone)
    d.proxies[proxy.path] = proxy
    d._kick_motion = lambda: None  # no event loop in these tests
    return d, proxy, published


def feed(d, proxy, *events):
    proxy.dev.queue = [ev(ecodes.EV_KEY, c, v) for c, v in events]
    d._read_device(proxy)


def test_typing_is_forwarded_to_the_clone(setup):
    d, proxy, _ = setup
    feed(d, proxy, (K.KEY_A, 1), (K.KEY_A, 0))
    assert proxy.clone.events == [(1, K.KEY_A, 1), "syn", (1, K.KEY_A, 0), "syn"]


def test_toggle_guard_click_and_publish(setup):
    d, proxy, published = setup
    feed(d, proxy, (K.KEY_LEFTMETA, 1), (K.KEY_M, 1), (K.KEY_M, 0), (K.KEY_LEFTMETA, 0))
    assert published == [True]
    sent = [e for e in proxy.clone.events if e != "syn"]
    assert (1, K.KEY_F24, 1) in sent and (1, K.KEY_F24, 0) in sent   # guard tap
    assert all(code != K.KEY_M for _, code, _ in sent)
    feed(d, proxy, (K.KEY_J, 1), (K.KEY_J, 0), (K.KEY_Q, 1), (K.KEY_Q, 0))
    assert [e for e in d.mouse.events if e != "syn"] == [(1, K.BTN_LEFT, 1), (1, K.BTN_LEFT, 0)]
    assert (1, K.KEY_Q, 1) not in proxy.clone.events


def test_motion_and_wheel_reach_the_mouse(setup):
    d, proxy, _ = setup
    d.engine.on = True
    feed(d, proxy, (K.KEY_D, 1))
    for i in range(1, 20):
        d._apply(d.engine.tick(i * 0.01))
    assert any(e[1] == K.REL_X and e[2] > 0 for e in d.mouse.events if e != "syn")
    feed(d, proxy, (K.KEY_D, 0), (K.KEY_SPACE, 1), (K.KEY_W, 1))
    d.mouse.events.clear()
    for i in range(1, 60):
        d._apply(d.engine.tick(1 + i * 0.01))
    codes = {e[1] for e in d.mouse.events if e != "syn"}
    assert K.REL_WHEEL_HI_RES in codes and K.REL_WHEEL in codes


def test_leds_are_mirrored_to_the_real_keyboard(setup):
    d, proxy, _ = setup
    proxy.clone.queue = [ev(ecodes.EV_LED, 1, 1)]
    d._read_clone(proxy)
    assert proxy.dev.leds_set == [(1, 1)]


def test_detach_releases_held_button(setup):
    d, proxy, _ = setup
    d.engine.on = True
    feed(d, proxy, (K.KEY_J, 1))
    d.mouse.events.clear()
    d._detach(proxy, reason="test")
    assert (1, K.BTN_LEFT, 0) in d.mouse.events
    assert proxy.clone.closed and not d.proxies


def test_state_server_roundtrip(tmp_path):
    from mouselessck.ipc import StateServer

    async def scenario():
        server = StateServer(str(tmp_path / "state.sock"))
        await server.start()
        reader, writer = await asyncio.open_unix_connection(server.path)
        first = await reader.readline()
        server.publish(True)
        second = await reader.readline()
        writer.close()
        await server.close()
        return first, second

    assert asyncio.run(scenario()) == (b"off\n", b"on\n")


def test_lock_signal_parsing():
    from mouselessck.session import is_lock_signal
    assert is_lock_signal("/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)")
    assert not is_lock_signal("/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (false,)")
    assert is_lock_signal("/org/freedesktop/login1/session/_32: org.freedesktop.login1.Session.Lock ()")
    assert is_lock_signal("... PropertiesChanged ('org.freedesktop.login1.Session', {'LockedHint': <true>}, @as [])")


# ------------------------------------------------------------- safety net
def test_panic_chord_stops_the_daemon(setup):
    d, proxy, _ = setup
    feed(d, proxy, (K.KEY_LEFTSHIFT, 1), (K.KEY_RIGHTSHIFT, 1), (K.KEY_ESC, 1))
    assert d.stopping.is_set() and d.exit_code == 0


def test_panic_chord_works_even_if_the_engine_is_broken(setup):
    d, proxy, _ = setup
    d.engine.on_key = lambda *a: 1 / 0
    feed(d, proxy, (K.KEY_LEFTSHIFT, 1), (K.KEY_RIGHTSHIFT, 1), (K.KEY_ESC, 1))
    assert d.stopping.is_set()


def test_detach_clears_raw_held_so_no_phantom_panic(setup):
    # A key held when its keyboard is unplugged must not stay in the panic
    # set and make a later chord fire one key early on another keyboard.
    d, proxy, _ = setup
    dev2, clone2 = FakeDev("/dev/input/event15", set(K.LETTERS)), FakeUInput()
    proxy2 = Proxy(dev2, clone2)
    d.proxies[proxy2.path] = proxy2

    feed(d, proxy, (K.KEY_LEFTSHIFT, 1))          # hold Left Shift...
    assert (proxy.path, K.KEY_LEFTSHIFT) in d.raw_held
    d._detach(proxy, reason="unplugged")           # ...then yank the keyboard
    assert all(src != proxy.path for src, _ in d.raw_held)

    # Right Shift + Esc alone on the second keyboard is only two of three.
    feed(d, proxy2, (K.KEY_RIGHTSHIFT, 1), (K.KEY_ESC, 1))
    assert not d.stopping.is_set()


def test_panic_chord_still_spans_keyboards(setup):
    # The safety direction is preserved: the chord may be split across two
    # keyboards (e.g. one Shift on each), so it is never harder to trigger.
    d, proxy, _ = setup
    dev2, clone2 = FakeDev("/dev/input/event15", set(K.LETTERS)), FakeUInput()
    proxy2 = Proxy(dev2, clone2)
    d.proxies[proxy2.path] = proxy2

    feed(d, proxy, (K.KEY_LEFTSHIFT, 1))
    feed(d, proxy2, (K.KEY_RIGHTSHIFT, 1), (K.KEY_ESC, 1))
    assert d.stopping.is_set()


def test_same_modifier_on_two_keyboards_is_tracked_separately(setup):
    # Holding Left Shift on both keyboards and releasing it on one must not
    # drop it from the set while the other still holds it.
    d, proxy, _ = setup
    dev2, clone2 = FakeDev("/dev/input/event15", set(K.LETTERS)), FakeUInput()
    proxy2 = Proxy(dev2, clone2)
    d.proxies[proxy2.path] = proxy2

    feed(d, proxy, (K.KEY_LEFTSHIFT, 1))
    feed(d, proxy2, (K.KEY_LEFTSHIFT, 1))
    feed(d, proxy, (K.KEY_LEFTSHIFT, 0))           # release on the first only
    assert (proxy2.path, K.KEY_LEFTSHIFT) in d.raw_held
    feed(d, proxy2, (K.KEY_RIGHTSHIFT, 1), (K.KEY_ESC, 1))
    assert d.stopping.is_set()


def test_internal_error_fails_open(setup):
    d, proxy, published = setup
    d.engine.on = True
    d.engine.on_key = lambda *a: 1 / 0
    feed(d, proxy, (K.KEY_Q, 1), (K.KEY_Q, 0), (K.KEY_W, 1), (K.KEY_W, 0))
    assert d.failed and published[-1] is False
    sent = [e for e in proxy.clone.events if e != "syn"]
    # every key now reaches applications, including the one that failed
    assert sent == [(1, K.KEY_Q, 1), (1, K.KEY_Q, 0), (1, K.KEY_W, 1), (1, K.KEY_W, 0)]


def test_lock_logs_one_line_with_reason(setup, caplog):
    import logging
    d, proxy, _ = setup
    d.engine.on = True
    with caplog.at_level(logging.INFO, logger="mouselessck"):
        d._on_lock("lock")
    lines = [r.getMessage() for r in caplog.records if "mouse mode" in r.getMessage()]
    assert lines == ["mouse mode off (lock)"]
    assert d.mode_reason is None
