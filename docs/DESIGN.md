# mouselessCK design summary

The decisions behind mouselessCK, why each was taken and what was rejected.

## Principle

Mouse mode is the *safe* state: keys pressed there cannot type into a window.
Typing mode is where a stray key matters. So the switch from mouse mode back
to typing happens only on purpose (Meta+M), never on a timeout. The single
automatic exit is the screen lock or suspend, where keys can only reach the
password field and the indicator is not visible.

## Decisions

| # | Decision | Why |
| --- | --- | --- |
| 1 | Work at the kernel level: evdev in, uinput out | Wayland forbids global key capture; a uinput device is a real device for libinput, so every compositor accepts it |
| 2 | Always-on proxy with one virtual clone per grabbed interface | The toggle key must never leak; one path for all keys means no stuck keys; clones keep names, ids and capabilities (media keys, volume knob, KDE per-device settings, touchpad pairing) |
| 3 | Toggle with Meta+M | Applications do not use Meta, and no Ctrl+Shift letter is free; a guard key tap stops KDE from opening the launcher on the Meta release |
| 4 | On-screen layer-shell icon instead of a LED | The compact keyboard has no LED; the laptop LED is shared with Caps Lock and hidden when the lid is closed |
| 5 | In mouse mode plain keys are swallowed; Esc, Ctrl/Alt/Meta chords and media keys pass | A stray key does no harm; chords are deliberate (Ctrl+C after a drag-selection) |
| 6 | Shift is held back in mouse mode and released to apps only for chords | Otherwise precision movement would make Shift+clicks and turn vertical scrolling horizontal |
| 7 | Physical key codes | Layout-independent |
| 8 | Python + python3-evdev, pure engine separated from I/O | Short and auditable; the engine is unit-tested without hardware |
| 9 | High-resolution wheel events plus classic notches | Smooth scrolling in modern apps, still works in old ones |
| 10 | System service under a dedicated user, hardened unit, watchdog | Works at login and lock screens; a crash or hang never leaves the keyboard dead |

## Engine invariants (tested)

* A key's release goes where its press went, whatever the mode.
* Leaving mouse mode releases every virtual mouse button.
* Kernel autorepeat events are dropped; the compositor repeats keys itself.
* J and Enter share the left button: it is down while either is held.

## Tested hardware

Dell laptop (AT keyboard, event3) and an Evision RGB compact keyboard
(USB 320f:505b) that exposes four input devices: interface 0 carries all
keys and the LEDs, interface 1 carries media keys (and letters in NKRO mode),
plus an axis and a macro mouse that are ignored. Fedora 43, KDE Plasma 6.7.5,
kernel 7.2.
