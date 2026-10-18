"""Minimal systemd notification support (READY, WATCHDOG, STATUS).

Implemented directly on the notification socket so the daemon needs no
extra dependency. Does nothing when not started by systemd.
"""

from __future__ import annotations

import os
import socket


def notify(message: str) -> bool:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
        return True
    except OSError:
        return False


def watchdog_interval() -> float | None:
    """Seconds between watchdog pings (half the configured timeout)."""
    usec = os.environ.get("WATCHDOG_USEC")
    pid = os.environ.get("WATCHDOG_PID")
    if not usec or (pid and int(pid) != os.getpid()):
        return None
    return int(usec) / 2_000_000
