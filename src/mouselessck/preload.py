"""Load gtk4-layer-shell before GTK.

gtk4-layer-shell must be linked before libwayland-client. From Python this
is done, as in the library's own example, by loading it with ctypes before
`gi` imports GTK. The runtime package ships only the versioned file
(libgtk4-layer-shell.so.0...), so it is located by glob.
"""

from __future__ import annotations

import ctypes
import glob


def find_library() -> str | None:
    # Only system library directories (owned by root) are searched, never the
    # current directory or the user's home.
    found = sorted(glob.glob("/usr/lib*/libgtk4-layer-shell.so*")
                   + glob.glob("/usr/local/lib*/libgtk4-layer-shell.so*"),
                   key=len)
    return found[0] if found else None


def load_layer_shell() -> bool:
    """Load the library by absolute path; return False if it is not installed.
    No bare library names: those would follow LD_LIBRARY_PATH."""
    path = find_library()
    if path is None:
        return False
    try:
        ctypes.CDLL(path)
        return True
    except OSError:
        return False
