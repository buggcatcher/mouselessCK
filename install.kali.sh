#!/usr/bin/env bash
# mouselessCK installer for Kali / Debian / Ubuntu (apt-based systems).
#
# It installs the Debian package equivalents of the Fedora dependencies, then
# hands over to the normal installer with --no-deps, which does the rest in a
# distro-agnostic way (files under /usr/local, the mouselessck service user,
# the /dev/uinput udev rule, and the 90-second confirmed trial).
#
#   sudo ./install.kali.sh              dependencies, files and the trial
#   sudo ./install.kali.sh --no-start   install files only, no trial, nothing enabled
#   sudo ./install.kali.sh --no-deps    skip apt (you installed the deps yourself)
#
# The core (keyboard-driven pointer, clicks, scroll) works on X11 and Wayland.
# The on-screen icon needs a Wayland wlroots/KDE/COSMIC session plus the
# gtk4-layer-shell packages; on the default Kali Xfce/X11 session there is no
# icon, exactly as on any X11 desktop. See KALI.md.
#
# Undo everything with: sudo ./uninstall.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Core, always required. These map 1:1 to the Fedora deps in install.sh:
#   python3-gobject -> python3-gi, python3-cairo -> python3-cairo + python3-gi-cairo,
#   gtk4 -> gir1.2-gtk-4.0 (pulls libgtk-4-1), glib2 -> libglib2.0-bin (gdbus).
CORE_DEPS=(python3 python3-evdev python3-pyudev python3-gi python3-gi-cairo
           python3-cairo gir1.2-gtk-4.0 libglib2.0-bin)
# Icon only. Kept separate so a missing layer-shell package never blocks the
# core install: without it the pointer and keys still work, just no icon.
ICON_DEPS=(libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0)

INSTALL_DEPS=1
PASS=()
for arg in "$@"; do
    case "$arg" in
        --no-deps) INSTALL_DEPS=0 ;;
        --no-start) PASS+=("$arg") ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWARNING: %s\033[0m\n' "$*" >&2; }

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo $0 $*" >&2; exit 1; }
command -v apt-get >/dev/null || { echo "apt-get not found: this script is for Debian-based systems (Kali/Ubuntu). On Fedora use ./install.sh." >&2; exit 1; }

if (( INSTALL_DEPS )); then
    export DEBIAN_FRONTEND=noninteractive
    say "Updating the package index (apt-get update)"
    apt-get update
    say "Installing core dependencies"
    apt-get install -y --no-install-recommends "${CORE_DEPS[@]}"
    say "Installing the on-screen-icon dependencies (optional)"
    if ! apt-get install -y --no-install-recommends "${ICON_DEPS[@]}"; then
        warn "gtk4-layer-shell is not available in this APT setup."
        warn "The pointer and keys will work; there will be no on-screen icon."
        warn "On Kali rolling it is usually available after 'apt-get update'."
    fi
fi

# Everything else is distro-agnostic and degrades gracefully on Kali:
#   * the Fedora-only 'rpm -q' check is skipped when rpm is absent;
#   * SELinux 'restorecon' is guarded by 'command -v' (Kali uses AppArmor);
#   * the KDE Meta+M check simply reports "free" on Xfce/GNOME.
say "Handing over to the common installer (install.sh --no-deps)"
# Invoked through bash so it runs even if the file's execute bit was lost in
# transit (zip/copy); install.sh installs its own helpers with explicit 0755.
exec bash "$HERE/install.sh" --no-deps "${PASS[@]}"
