#!/usr/bin/env bash
# mouselessCK installer for a quick, script-based install under /usr/local.
# For a clean system-wide install prefer the RPM (see README, "Install as RPM").
#
#   sudo ./install.sh              install dependencies, files and services
#   sudo ./install.sh --no-deps    skip "dnf install"
#   sudo ./install.sh --no-start   install files only, no trial, nothing enabled
#
# Before enabling anything at boot, the daemon runs a 90-second trial that
# switches itself off unless you confirm, by typing, that the keyboard works.
#
# Undo everything with: sudo ./uninstall.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=/usr/local
PYLIBDIR="$PREFIX/lib/mouselessck"
LIBEXECDIR="$PREFIX/libexec/mouselessck"
BINDIR="$PREFIX/bin"
DOCDIR="$PREFIX/share/doc/mouselessck"
CONFDIR=/etc/mouselessck
MANIFEST="$CONFDIR/.install-manifest"
DEPS=(python3 python3-evdev python3-pyudev python3-gobject python3-cairo gtk4 gtk4-layer-shell glib2)

INSTALL_DEPS=1
START=1
TRIAL_SECONDS=90
for arg in "$@"; do
    case "$arg" in
        --no-deps) INSTALL_DEPS=0 ;;
        --no-start) START=0 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWARNING: %s\033[0m\n' "$*" >&2; }

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo $0 $*" >&2; exit 1; }
if rpm -q mouselessck >/dev/null 2>&1; then
    echo "The mouselessck RPM is installed. Remove it first (sudo dnf remove mouselessck)." >&2
    exit 1
fi

if (( INSTALL_DEPS )); then
    # Only official Fedora packages, through dnf (signed repositories).
    # Nothing is downloaded from anywhere else, now or at run time.
    say "Installing dependencies"
    dnf install -y "${DEPS[@]}"
fi

# Every file written below is recorded in a root-owned manifest, so that
# uninstall.sh removes exactly these files and nothing else.
mkdir -p "$CONFDIR"
: > "$MANIFEST.tmp"
put() {  # put MODE SOURCE DEST
    install -D -m "$1" "$2" "$3"
    echo "$3" >> "$MANIFEST.tmp"
}
subst() {  # subst MODE TEMPLATE DEST
    local tmp
    tmp="$(mktemp)"
    sed -e "s|@PYLIBDIR@|$PYLIBDIR|g" -e "s|@LIBEXECDIR@|$LIBEXECDIR|g" \
        -e "s|@BINDIR@|$BINDIR|g" -e "s|@DOCDIR@|$DOCDIR|g" "$2" > "$tmp"
    put "$1" "$tmp" "$3"
    rm -f "$tmp"
}

say "Installing files under $PREFIX and /etc"
for f in "$HERE"/src/mouselessck/*.py; do
    put 0644 "$f" "$PYLIBDIR/mouselessck/$(basename "$f")"
done
subst 0755 "$HERE/bin/mouselessckd.in" "$LIBEXECDIR/mouselessckd"
subst 0755 "$HERE/bin/mouselessck-indicator.in" "$BINDIR/mouselessck-indicator"
subst 0644 "$HERE/data/mouselessck.service.in" /etc/systemd/system/mouselessck.service
subst 0644 "$HERE/data/mouselessck-indicator.service.in" /etc/systemd/user/mouselessck-indicator.service
put 0644 "$HERE/data/70-mouselessck.rules" /etc/udev/rules.d/70-mouselessck.rules
put 0644 "$HERE/data/mouselessck.sysusers" /etc/sysusers.d/mouselessck.conf
put 0644 "$HERE/data/mouselessck-modules.conf" /etc/modules-load.d/mouselessck.conf
put 0644 "$HERE/README.md" "$DOCDIR/README.md"
put 0755 "$HERE/tools/probe_mouse.py" "$DOCDIR/probe_mouse.py"
put 0755 "$HERE/tools/mouselessck-trial" "$LIBEXECDIR/mouselessck-trial"
if [[ -e "$CONFDIR/config.toml" ]]; then
    install -m 0644 "$HERE/config/config.toml" "$CONFDIR/config.toml.new"
    warn "kept your $CONFDIR/config.toml; the shipped one is config.toml.new"
else
    install -m 0644 "$HERE/config/config.toml" "$CONFDIR/config.toml"
fi
mv "$MANIFEST.tmp" "$MANIFEST"

say "Checking the configuration"
"$LIBEXECDIR/mouselessckd" --check-config

say "Creating the service user and device permissions"
systemd-sysusers /etc/sysusers.d/mouselessck.conf
modprobe uinput || warn "could not load the uinput module"
udevadm control --reload-rules
udevadm trigger --action=change --sysname-match=uinput || true
if command -v restorecon >/dev/null; then
    restorecon -R "$PYLIBDIR" "$LIBEXECDIR" "$BINDIR/mouselessck-indicator" \
        /etc/systemd/system/mouselessck.service /etc/systemd/user/mouselessck-indicator.service \
        /etc/udev/rules.d/70-mouselessck.rules "$CONFDIR" 2>/dev/null || true
fi

# --- Meta+M conflict check against the invoking user's KDE shortcuts.
# The file is read AS THAT USER (runuser), never as root: a symlink planted in
# a home directory must not let this root script read someone else's files.
USER_NAME="${SUDO_USER:-}"
if [[ -n "$USER_NAME" && "$USER_NAME" != root ]]; then
    PATTERN='(^|[=,	])Meta\+M(,|	|$)'
    SHORTCUTS="$(getent passwd "$USER_NAME" | cut -d: -f6)/.config/kglobalshortcutsrc"
    # shellcheck disable=SC2016  # $1/$2 are expanded by the inner sh, on purpose
    if MATCHES="$(runuser -u "$USER_NAME" -- sh -c \
            '[ -r "$2" ] && grep -nE "$1" "$2"' sh "$PATTERN" "$SHORTCUTS")"; then
        warn "Meta+M is already a KDE global shortcut:"
        printf '%s\n' "$MATCHES" | sed 's/^/    /' >&2
        warn "mouselessCK will take it over. Change [toggle] in $CONFDIR/config.toml if you need it."
    else
        say "Meta+M is free in your KDE shortcuts"
    fi
fi

systemctl daemon-reload
if (( START )); then
    # Start the icon first so it is visible during the trial.
    if [[ -n "$USER_NAME" && "$USER_NAME" != root ]]; then
        USER_ID="$(id -u "$USER_NAME")"
        if [[ -S "/run/user/$USER_ID/bus" ]]; then
            runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_ID" \
                DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" \
                sh -c 'systemctl --user daemon-reload && systemctl --user restart mouselessck-indicator.service' \
                || warn "start the indicator yourself: systemctl --user start mouselessck-indicator"
        fi
    fi

    if [[ ! -t 0 ]]; then
        warn "No terminal to confirm a trial run: mouselessCK is installed but NOT enabled."
        echo "Run the trial when ready: sudo $LIBEXECDIR/mouselessck-trial"
        exit 0
    fi

    # --- Trial run with a dead-man timer (see tools/mouselessck-trial).
    # The real, sandboxed service runs for TRIAL_SECONDS and systemd stops it
    # whatever happens. It is enabled at boot only if you type "yes" THROUGH
    # it, which proves the keyboard still works with mouselessCK in the middle.
    say "Trial run: mouselessCK stops on its own after $TRIAL_SECONDS seconds"
    if ! "$LIBEXECDIR/mouselessck-trial" "$TRIAL_SECONDS"; then
        warn "Installed but NOT enabled: nothing runs at boot."
        echo "  Try again: sudo $LIBEXECDIR/mouselessck-trial"
        echo "  Remove it: sudo ./uninstall.sh"
        exit 1
    fi
    sleep 1
    systemctl --no-pager --lines=5 status mouselessck.service || true
fi

cat <<EOF

mouselessCK is installed.

  Toggle mouse mode ........ Meta+M (the icon appears bottom-right)
  Emergency stop ........... hold both Shift keys + Esc, or: sudo systemctl stop mouselessck
  Logs ..................... journalctl -u mouselessck
  Keyboards taken over ..... sudo $LIBEXECDIR/mouselessckd --list

One-time KDE setting (recommended): System Settings > Mouse & Touchpad >
device "mouselessCK Virtual Mouse" > set the acceleration profile to Flat,
so the speed comes only from mouselessCK's own curve.
EOF
