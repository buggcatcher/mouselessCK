# Changelog

## 1.0.4 (2026-10-18)

- Precision on either Shift key, not only the left one.
- Trial: `yes` counts only if mouselessCK is still running and has taken over
  at least one keyboard (a confirmation typed after the emergency chord used
  to be accepted).
- One log line per mode change, with the reason (lock, sleep, stopping).
- Diagnostic probes: `probe_scroll.py`, `probe_reverse.py`,
  `probe_mouse.py --hscroll`.

## 1.0.3 (2026-10-18)

- The emergency chord tracks keys per keyboard: unplugging a keyboard with a
  key held, or holding the same modifier on two keyboards, no longer leaves a
  phantom key behind.

## 1.0.2 (2026-10-18)

- Security review: errors logged without their message (no key codes),
  bounded one-way state socket, `gdbus` and gtk4-layer-shell loaded by
  absolute path, socket path validation, trial runs the fully sandboxed unit,
  uninstall limited to known paths, user files read as the user.
- `SECURITY.md`.

## 1.0.1 (2026-10-18)

- Safety net: emergency chord (both Shift + Esc), fail-open on internal
  errors, restart limit, 90-second confirmed trial before enabling.

## 1.0.0 (2026-10-18)

- First release: Meta+M toggle, WASD/arrows, Space scroll, J/Enter, K, L
  clicks, precision on Shift, layer-shell indicator, hardened systemd service.
