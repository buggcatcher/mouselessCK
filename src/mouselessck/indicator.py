"""mouselessck-indicator: the on-screen mouse-mode icon.

Runs in the user's graphical session, unprivileged. It reads only "on"/"off"
from the daemon's state socket and shows a small translucent icon in a corner
of every monitor while mouse mode is on.

SECURITY: this program has no access to the keyboard and sends nothing to
the daemon. Anything other than "on" is treated as "off", and when the
daemon is unreachable the icon is hidden: it never claims a mode it does not
know.

The icon is a Wayland layer-shell surface on the overlay layer: it stays
above all windows (full-screen ones too), never takes keyboard focus, and
clicks pass through it. KDE Plasma, wlroots compositors (Sway, Hyprland,
niri) and COSMIC support layer-shell; GNOME does not.
"""

from __future__ import annotations

import argparse
import logging
import math
import socket
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
except (ValueError, ImportError):  # library not installed
    LayerShell = None

import cairo
from gi.repository import Gdk, GLib, Gtk

from . import __version__
from .config import load

log = logging.getLogger("mouselessck-indicator")

RECONNECT_SECONDS = 2
MAX_BUFFER = 64  # the daemon only ever sends "on\n" or "off\n"
CSS = "window.mouselessck { background: transparent; box-shadow: none; }"
ACCENT = (0.30, 0.60, 1.00)


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class Indicator:
    def __init__(self, app: Gtk.Application, cfg):
        self.app = app
        self.socket_path = cfg.socket_path
        ind = cfg.indicator
        self.corner = ind["corner"]
        self.size = int(ind["size"])
        self.margin = int(ind["margin"])
        self.opacity = float(ind["opacity"])
        self.windows: list[Gtk.Window] = []
        self.on = False
        self.sock: socket.socket | None = None
        self.buffer = b""

    # ------------------------------------------------------------- windows
    def start(self) -> None:
        display = Gdk.Display.get_default()
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(CSS)
        else:
            provider.load_from_data(CSS.encode(), -1)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        display.get_monitors().connect("items-changed", lambda *_: self.rebuild())
        self.rebuild()
        self.connect()

    def rebuild(self) -> None:
        for win in self.windows:
            win.destroy()
        monitors = Gdk.Display.get_default().get_monitors()
        self.windows = [self._make_window(monitors.get_item(i))
                        for i in range(monitors.get_n_items())]
        self._show(self.on)

    def _make_window(self, monitor) -> Gtk.Window:
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class("mouselessck")
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "mouselessck")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)
        LayerShell.set_monitor(win, monitor)
        vertical, horizontal = self.corner.split("-")
        edges = (LayerShell.Edge.TOP if vertical == "top" else LayerShell.Edge.BOTTOM,
                 LayerShell.Edge.LEFT if horizontal == "left" else LayerShell.Edge.RIGHT)
        for edge in edges:
            LayerShell.set_anchor(win, edge, True)
            LayerShell.set_margin(win, edge, self.margin)

        area = Gtk.DrawingArea()
        area.set_content_width(self.size)
        area.set_content_height(self.size)
        area.set_can_target(False)
        area.set_draw_func(self._draw)
        win.set_child(area)
        win.connect("realize", self._click_through)
        return win

    @staticmethod
    def _click_through(win: Gtk.Window) -> None:
        surface = win.get_surface()
        try:
            surface.set_input_region(cairo.Region())  # empty: clicks pass through
        except (TypeError, AttributeError) as exc:
            log.warning("cannot make the icon click-through: %s", exc)

    def _draw(self, _area, cr, width, height) -> None:
        s = min(width, height)
        a = self.opacity
        # translucent dark disc
        cr.arc(width / 2, height / 2, s / 2, 0, 2 * math.pi)
        cr.set_source_rgba(0.10, 0.11, 0.13, 0.55 * a)
        cr.fill()
        # mouse body
        bw, bh = s * 0.40, s * 0.60
        x, y = (width - bw) / 2, (height - bh) / 2
        split = y + bh * 0.42
        # left button lit in the accent colour: "the mouse is yours"
        cr.save()
        _rounded_rect(cr, x, y, bw, bh, bw / 2)
        cr.clip()
        cr.rectangle(x, y, bw / 2, split - y)
        cr.set_source_rgba(*ACCENT, a)
        cr.fill()
        cr.restore()
        _rounded_rect(cr, x, y, bw, bh, bw / 2)
        cr.set_line_width(max(1.5, s * 0.06))
        cr.set_source_rgba(1, 1, 1, a)
        cr.stroke()
        cr.move_to(x, split)
        cr.line_to(x + bw, split)
        cr.move_to(width / 2, y)
        cr.line_to(width / 2, split)
        cr.stroke()

    def _show(self, on: bool) -> None:
        self.on = on
        for win in self.windows:
            win.set_visible(on)

    # -------------------------------------------------------------- socket
    def connect(self) -> bool:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            sock.setblocking(False)
        except OSError:
            GLib.timeout_add_seconds(RECONNECT_SECONDS, self.connect)
            return False
        self.sock = sock
        GLib.io_add_watch(sock.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                          self._on_data)
        log.info("connected to %s", self.socket_path)
        return False  # one-shot when used as a timeout

    def _on_data(self, _fd, _condition) -> bool:
        try:
            data = self.sock.recv(256) if self.sock else b""
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            self._disconnect()
            return False
        self.buffer += data
        if len(self.buffer) > MAX_BUFFER and b"\n" not in self.buffer:
            # Not our daemon's protocol: drop the connection instead of
            # buffering without limit.
            self._disconnect()
            return False
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self._show(line.strip() == b"on")
        return True

    def _disconnect(self) -> None:
        if self.sock:
            self.sock.close()
        self.sock = None
        self.buffer = b""
        self._show(False)  # unknown state: show nothing rather than a lie
        log.info("daemon unavailable, retrying")
        GLib.timeout_add_seconds(RECONNECT_SECONDS, self.connect)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mouselessck-indicator",
                                     description="On-screen indicator for mouselessCK mouse mode.")
    parser.add_argument("-c", "--config", help="configuration file")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if LayerShell is None:
        log.error("gtk4-layer-shell is not installed: sudo dnf install gtk4-layer-shell")
        return 0  # not a crash: do not make systemd restart us in a loop
    try:
        cfg = load(args.config)
    except (OSError, ValueError) as exc:
        log.error("configuration error: %s", exc)
        return 2

    app = Gtk.Application(application_id="io.github.mouselessck.Indicator")
    state: dict = {}

    def on_activate(application: Gtk.Application) -> None:
        if state:
            return
        if not LayerShell.is_supported():
            log.error("this desktop does not support the layer-shell protocol "
                      "(GNOME does not): the on-screen indicator is unavailable")
            application.quit()
            return
        application.hold()
        state["indicator"] = Indicator(application, cfg)
        state["indicator"].start()

    app.connect("activate", on_activate)
    return app.run([sys.argv[0]])
