# Security model of mouselessCK

mouselessCK reads every key you type, passwords included, and can inject
input into your session. This file states what it may and may not do, and
how to check that it keeps to it.

## What it can access

| Component | Runs as | Can read | Can write |
| --- | --- | --- | --- |
| `mouselessckd` (system service) | user `mouselessck`, groups `mouselessck`, `input` | every input device (keyboards, but also mice and touchpads it never grabs) | `/dev/uinput` (virtual devices), `/run/mouselessck/` |
| `mouselessck-indicator` (user service) | you | the line `on` / `off` from `/run/mouselessck/state.sock` | nothing |
| `install.sh`, `uninstall.sh`, `mouselessck-trial` | root, once, when you run them | the project folder | the files listed in `/etc/mouselessck/.install-manifest`, systemd and udev state |

## Promises, and where they are enforced

| Promise | Enforced by |
| --- | --- |
| No key ever leaves the process | No network (`RestrictAddressFamilies=AF_UNIX AF_NETLINK`, `IPAddressDeny=any`); no files written; read-only file system (`ProtectSystem=strict`, `ProtectHome`) |
| No key in the logs | Logs carry device names and mode changes only; errors are logged as type + code location, never their message (`describe_error`, `_loop_error` in `daemon.py`) |
| Keys are not stored | Only keys currently held are kept in memory (`Engine.routes`, `Daemon.raw_held`), removed on release |
| The indicator cannot influence the daemon | The state socket is one-way; client input is discarded; at most 16 clients; clients that stop reading are dropped (`ipc.py`) |
| No privilege for anyone else | `/dev/uinput` only for group `mouselessck` (no human members); service has no capabilities, `NoNewPrivileges`, syscall filter |
| No code injection through the environment | Launchers use `python3 -I`; `gdbus` and `libgtk4-layer-shell` are loaded by absolute path |
| No surprise downloads | Dependencies only via `dnf` from Fedora repositories; nothing is fetched at run time |
| You cannot be locked out | Crash: kernel releases the grab. Hang: watchdog (5 s). Bug: fail-open pass-through. Both Shift + Esc: immediate exit. Restart limit: 3 per minute. Install: 90-second trial that must be confirmed by typing. Boot: `systemd.mask=mouselessck.service` from GRUB |
| Uninstall removes only its own files | `uninstall.sh` deletes manifest entries only inside an allowlist of paths |

## Checking it yourself

```bash
# Everything that could reach outside the process (expect: only gdbus in
# session.py, the AF_UNIX sockets in ipc.py / sdnotify.py / indicator.py,
# ctypes in preload.py):
grep -rnE "subprocess|os\.system|eval\(|exec|socket|urllib|requests|http|ctypes|pickle" src/

# Every log line (none prints a key code):
grep -rnE "log\.|print\(" src/

# The sandbox score of the running service:
systemd-analyze security mouselessck

# What the service user may touch:
id mouselessck; ls -l /dev/uinput
```

## Reporting a problem

This is a personal project. If you find a way to read keys through
mouselessCK, or to make it misbehave from another account, stop the service
(`sudo systemctl disable --now mouselessck`) and open an issue privately.
