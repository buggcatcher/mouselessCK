import pytest

from mouselessck import keycodes as K
from mouselessck.config import build
from mouselessck.engine import Engine

TDP, TCC = "event3", "event14"


@pytest.fixture
def eng():
    return Engine(build())


def press(e, code, src=TCC, t=0.0):
    return e.on_key(src, code, 1, t)


def release(e, code, src=TCC, t=0.0):
    return e.on_key(src, code, 0, t)


def tap(e, code, src=TCC, t=0.0):
    return press(e, code, src, t) + release(e, code, src, t)


def toggle(e, src=TCC):
    acts = press(e, K.KEY_LEFTMETA, src)
    acts += tap(e, K.KEY_M, src)
    acts += release(e, K.KEY_LEFTMETA, src)
    return acts


def keys(acts):
    return [a for a in acts if a[0] == "key"]


# ---------------------------------------------------------------- typing mode
def test_typing_mode_forwards_everything(eng):
    assert tap(eng, K.KEY_W) == [("key", TCC, K.KEY_W, 1), ("key", TCC, K.KEY_W, 0)]
    assert not eng.on


def test_autorepeat_is_dropped(eng):
    press(eng, K.KEY_A)
    assert eng.on_key(TCC, K.KEY_A, 2, 0.1) == []


# --------------------------------------------------------------------- toggle
def test_meta_m_toggles_and_m_never_reaches_apps(eng):
    acts = toggle(eng)
    assert eng.on
    assert ("mode", True) in acts
    assert ("guard", TCC) in acts
    assert all(a[2] != K.KEY_M for a in keys(acts))
    # Meta itself is forwarded, press and release
    assert ("key", TCC, K.KEY_LEFTMETA, 1) in acts
    assert ("key", TCC, K.KEY_LEFTMETA, 0) in acts
    acts = toggle(eng)
    assert not eng.on and ("mode", False) in acts


def test_toggle_across_keyboards(eng):
    press(eng, K.KEY_LEFTMETA, TDP)
    tap(eng, K.KEY_M, TCC)
    assert eng.on


def test_meta_shift_m_is_not_the_toggle(eng):
    press(eng, K.KEY_LEFTMETA)
    press(eng, K.KEY_LEFTSHIFT)
    acts = tap(eng, K.KEY_M)
    assert not eng.on
    assert ("key", TCC, K.KEY_M, 1) in acts


def test_plain_m_types_m(eng):
    assert ("key", TCC, K.KEY_M, 1) in tap(eng, K.KEY_M)


# ----------------------------------------------------------------- mouse mode
def test_plain_keys_are_swallowed_in_mouse_mode(eng):
    toggle(eng)
    for code in (K.KEY_Q, K.KEY_E, K.KEY_1, K.KEY_BACKSPACE, K.KEY_TAB):
        assert keys(tap(eng, code)) == []


def test_esc_passes_enter_does_not(eng):
    toggle(eng)
    assert keys(tap(eng, K.KEY_ESC)) == [("key", TCC, K.KEY_ESC, 1), ("key", TCC, K.KEY_ESC, 0)]
    acts = tap(eng, K.KEY_ENTER)
    assert keys(acts) == []
    assert acts == [("btn", K.BTN_LEFT, 1), ("btn", K.BTN_LEFT, 0)]


def test_ctrl_chord_passes_even_for_mapped_keys(eng):
    toggle(eng)
    press(eng, K.KEY_LEFTCTRL)
    assert keys(tap(eng, K.KEY_C)) == [("key", TCC, K.KEY_C, 1), ("key", TCC, K.KEY_C, 0)]
    assert ("key", TCC, K.KEY_W, 1) in tap(eng, K.KEY_W)


def test_media_keys_always_pass(eng):
    toggle(eng)
    assert keys(tap(eng, K.KEY_VOLUMEUP))
    assert keys(tap(eng, 164))  # KEY_PLAYPAUSE


def test_clicks_j_and_enter_share_the_left_button(eng):
    toggle(eng)
    assert press(eng, K.KEY_J) == [("btn", K.BTN_LEFT, 1)]
    assert press(eng, K.KEY_ENTER) == []          # already down
    assert release(eng, K.KEY_J) == []            # Enter still holds it
    assert release(eng, K.KEY_ENTER) == [("btn", K.BTN_LEFT, 0)]
    assert tap(eng, K.KEY_K) == [("btn", K.BTN_MIDDLE, 1), ("btn", K.BTN_MIDDLE, 0)]
    assert tap(eng, K.KEY_L) == [("btn", K.BTN_RIGHT, 1), ("btn", K.BTN_RIGHT, 0)]


def test_leaving_mouse_mode_releases_buttons(eng):
    toggle(eng)
    press(eng, K.KEY_J)  # drag in progress
    acts = toggle(eng)
    assert ("btn", K.BTN_LEFT, 0) in acts
    assert release(eng, K.KEY_J) == []  # its release stays swallowed


def test_release_follows_press_across_toggle(eng):
    press(eng, K.KEY_A)              # typed in typing mode
    toggle(eng)
    assert release(eng, K.KEY_A) == [("key", TCC, K.KEY_A, 0)]


def test_shift_is_held_back_then_flushed_for_chords(eng):
    toggle(eng)
    press(eng, K.KEY_LEFTCTRL)
    assert press(eng, K.KEY_LEFTSHIFT) == []
    acts = press(eng, K.KEY_T)
    assert acts == [("key", TCC, K.KEY_LEFTSHIFT, 1), ("key", TCC, K.KEY_T, 1)]
    assert release(eng, K.KEY_LEFTSHIFT) == [("key", TCC, K.KEY_LEFTSHIFT, 0)]


def test_shift_alone_never_reaches_apps_in_mouse_mode(eng):
    toggle(eng)
    assert tap(eng, K.KEY_LEFTSHIFT) == []


def test_force_off(eng):
    toggle(eng)
    press(eng, K.KEY_L)
    acts = eng.force_off()
    assert ("mode", False) in acts and ("btn", K.BTN_RIGHT, 0) in acts
    assert eng.force_off() == []


def test_drop_source_releases_buttons_but_not_keys(eng):
    toggle(eng)
    press(eng, K.KEY_J, TCC)
    acts = eng.drop_source(TCC)
    assert acts == [("btn", K.BTN_LEFT, 0)]
    assert not eng.routes


# --------------------------------------------------------------------- motion
def run(eng, seconds, start=0.0):
    out, t = [], start
    while t < start + seconds:
        t += 0.01
        out += eng.tick(t)
    return out


def test_movement_directions(eng):
    toggle(eng)
    press(eng, K.KEY_D)
    rel = [a for a in run(eng, 0.2) if a[0] == "rel"]
    assert sum(a[1] for a in rel) > 0 and sum(a[2] for a in rel) == 0
    release(eng, K.KEY_D)
    press(eng, K.KEY_UP)
    rel = [a for a in run(eng, 0.2, 1.0) if a[0] == "rel"]
    assert sum(a[2] for a in rel) < 0


def test_no_motion_outside_mouse_mode(eng):
    press(eng, K.KEY_D)
    assert not eng.motion_active()
    assert eng.tick(0.01) == []


def test_precision_is_slower(eng):
    toggle(eng)
    press(eng, K.KEY_D)
    fast = sum(a[1] for a in run(eng, 0.5))
    release(eng, K.KEY_D)
    press(eng, K.KEY_LEFTSHIFT)
    press(eng, K.KEY_D)
    slow = sum(a[1] for a in run(eng, 0.5, 2.0))
    assert 0 < slow < fast / 3


def test_space_turns_directions_into_scroll(eng):
    toggle(eng)
    press(eng, K.KEY_SPACE)
    press(eng, K.KEY_S)
    acts = run(eng, 0.5)
    assert all(a[0] == "wheel" for a in acts)
    assert sum(a[1] for a in acts) < 0           # scrolling down
    assert sum(a[3] for a in acts) <= -1         # at least one classic notch
    release(eng, K.KEY_S)
    press(eng, K.KEY_D)
    acts = run(eng, 0.3, 2.0)
    assert sum(a[2] for a in acts) > 0           # horizontal, to the right


def test_space_alone_does_nothing(eng):
    toggle(eng)
    assert tap(eng, K.KEY_SPACE) == []
    assert not eng.motion_active()


def test_right_shift_is_precision_too(eng):
    toggle(eng)
    press(eng, K.KEY_D)
    fast = sum(a[1] for a in run(eng, 0.5))
    release(eng, K.KEY_D)
    press(eng, K.KEY_RIGHTSHIFT)
    press(eng, K.KEY_D)
    slow = sum(a[1] for a in run(eng, 0.5, 2.0))
    assert 0 < slow < fast / 3
    assert keys(release(eng, K.KEY_RIGHTSHIFT)) == []   # never reached apps
