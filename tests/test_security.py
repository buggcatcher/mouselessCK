"""Security properties that must not regress."""

import asyncio

import pytest

from mouselessck.config import build


def test_errors_are_logged_without_their_message():
    pytest.importorskip("evdev")
    from mouselessck.daemon import describe_error
    try:
        {}[30]  # KeyError: 30 -> would reveal the letter A
    except KeyError as exc:
        text = describe_error(exc)
    assert text.startswith("KeyError at ")
    assert "30" not in text.split(" at ")[0]
    assert ": 30" not in text


def test_internal_error_log_contains_no_key_code(caplog):
    pytest.importorskip("evdev")
    from mouselessck.daemon import Daemon
    d = Daemon(build())
    d.state.publish = lambda on: None
    try:
        raise KeyError(30)
    except KeyError as exc:
        d._fail_open("key handling", exc)
    assert d.failed
    assert "KeyError(30)" not in caplog.text and "KeyError: 30" not in caplog.text


def test_socket_path_must_stay_under_run():
    for bad in ("/etc/passwd", "relative.sock", "/run/../etc/x.sock"):
        with pytest.raises(ValueError):
            build({"ipc": {"socket": bad}})


def test_state_socket_limits_clients_and_ignores_input(tmp_path):
    from mouselessck import ipc

    async def scenario():
        server = ipc.StateServer(str(tmp_path / "s.sock"))
        await server.start()
        conns = []
        for _ in range(ipc.MAX_CLIENTS + 3):
            conns.append(await asyncio.open_unix_connection(server.path))
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        accepted = len(server.clients)
        reader, writer = conns[0]
        assert await reader.readline() == b"off\n"
        writer.write(b"on\n" * 100)          # a client cannot change the state
        await writer.drain()
        await asyncio.sleep(0.05)
        state = server.on
        for _, w in conns:
            w.close()
        await server.close()
        return accepted, state

    accepted, state = asyncio.run(scenario())
    assert accepted == ipc.MAX_CLIENTS
    assert state is False


def test_layer_shell_is_never_loaded_by_bare_name(monkeypatch):
    from mouselessck import preload
    loaded = []
    monkeypatch.setattr(preload, "find_library", lambda: None)
    monkeypatch.setattr(preload.ctypes, "CDLL", lambda name: loaded.append(name))
    assert preload.load_layer_shell() is False
    assert loaded == []
