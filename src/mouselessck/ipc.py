"""State broadcast for the on-screen indicator.

SECURITY: this is the only channel between the privileged daemon and the
user's session, so it is deliberately poor:
  * one-way: the daemon sends "on" or "off", anything a client writes is
    read and thrown away (a client cannot influence the daemon);
  * it never carries key events, only the mode, so it is safe for any local
    user to read (mode 0666 lets the indicator of whoever is logged in
    connect without extra groups);
  * bounded: at most MAX_CLIENTS connections, and a client that stops
    reading is dropped, so another local user cannot exhaust memory.
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)

MAX_CLIENTS = 16          # indicators of logged-in users; more is abuse
MAX_PENDING = 256         # bytes queued for a client that does not read
READ_CHUNK = 256


class StateServer:
    def __init__(self, path: str):
        self.path = path
        self.on = False
        self.clients: set[asyncio.StreamWriter] = set()
        self.server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        # The path lives in the service's own RuntimeDirectory
        # (/run/mouselessck, writable only by the service user), so removing a
        # stale socket here cannot touch anyone else's files.
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.server = await asyncio.start_unix_server(self._client, path=self.path)
        os.chmod(self.path, 0o666)  # read-only in practice: see module docstring
        log.info("state socket at %s", self.path)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if len(self.clients) >= MAX_CLIENTS:
            writer.close()
            return
        self.clients.add(writer)
        try:
            writer.write(self._line())
            await writer.drain()
            while await reader.read(READ_CHUNK):
                pass  # one-way channel: client input is discarded unread
        except (ConnectionError, OSError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()

    def _line(self) -> bytes:
        return b"on\n" if self.on else b"off\n"

    def publish(self, on: bool) -> None:
        self.on = on
        for writer in list(self.clients):
            try:
                if writer.transport.get_write_buffer_size() > MAX_PENDING:
                    raise ConnectionError("client is not reading")
                writer.write(self._line())
            except (ConnectionError, OSError, AttributeError):
                self.clients.discard(writer)
                writer.close()

    async def close(self) -> None:
        if self.server:
            self.server.close()
        for writer in list(self.clients):
            writer.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass
