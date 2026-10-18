"""Watch logind for screen locks and suspend.

Mouse mode swallows typing, and the on-screen indicator is not visible on the
lock screen. A password typed there with mouse mode on would vanish without
explanation, so mouse mode is switched off whenever a session locks or the
system prepares to sleep. On the lock screen keys only reach the password
field, so leaving mouse mode there is safe.

`gdbus monitor` (from glib2, present on every Fedora desktop) is used instead
of a D-Bus library to keep the daemon dependency-free.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

log = logging.getLogger(__name__)

# Absolute path, not a PATH lookup: the daemon must never run a program
# someone could place earlier in PATH. gdbus only LISTENS to logind signals;
# it receives no key data and its output is only matched against the three
# patterns below.
GDBUS = "/usr/bin/gdbus"
COMMAND = [GDBUS, "monitor", "--system", "--dest", "org.freedesktop.login1"]


def is_lock_signal(line: str) -> bool:
    return (
        "PrepareForSleep (true" in line
        or ".Session.Lock ()" in line
        or "'LockedHint': <true>" in line
    )


async def watch(on_lock: Callable[[str], None]) -> None:
    if not os.access(GDBUS, os.X_OK):
        log.warning("gdbus not found: mouse mode will not turn off on screen lock")
        return
    while True:
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *COMMAND,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace")
                if is_lock_signal(line):
                    on_lock("sleep" if "PrepareForSleep" in line else "lock")
            await proc.wait()
            log.warning("logind monitor exited with %s, restarting", proc.returncode)
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                proc.terminate()
            raise
        except (OSError, ValueError) as exc:  # ValueError: absurdly long line
            log.warning("cannot watch logind: %s", type(exc).__name__)
        await asyncio.sleep(5)
