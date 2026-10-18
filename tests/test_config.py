import pytest

from mouselessck import keycodes as K
from mouselessck.config import build, load
from mouselessck.motion import Motion


def test_defaults():
    cfg = build()
    assert cfg.toggle_key == K.KEY_M and cfg.toggle_modifier == "meta"
    assert cfg.buttons[K.KEY_ENTER] == K.BTN_LEFT
    assert cfg.directions[K.KEY_W] == (0, -1)
    assert K.KEY_SPACE in cfg.scroll_keys


def test_override_and_validation():
    cfg = build({"toggle": {"modifier": "ctrl", "key": "KEY_F9"}})
    assert cfg.toggle_key == K.KEY_F9
    with pytest.raises(ValueError):
        build({"toggle": {"key": "KEY_W"}})          # clashes with movement
    with pytest.raises(ValueError):
        build({"indicator": {"corner": "middle"}})
    with pytest.raises(ValueError):
        build({"keys": {"up": ["KEY_NOPE"]}})


def test_shipped_config_file_parses():
    from pathlib import Path
    cfg = load(Path(__file__).resolve().parents[1] / "config" / "config.toml")
    assert cfg == build()


def test_tap_is_small_hold_accelerates():
    cfg = build()
    m = Motion(cfg.pointer, cfg.scroll, cfg.rate_hz)
    first = m.step(0.0, 1, 0, False, False)
    assert first in ([], [("rel", 1, 0)])
    total, t = 0, 0.0
    while t < 1.0:
        t += 0.01
        for a in m.step(t, 1, 0, False, False):
            total += a[1]
    assert 800 < total < 1600   # ramps from 120 to 1600 px/s over 0.6 s
