#!/usr/bin/env bash
# Remove a script-based mouselessCK install (made with install.sh).
#
#   sudo ./uninstall.sh            remove program and services, keep config
#   sudo ./uninstall.sh --purge    also remove /etc/mouselessck and the user
set -euo pipefail

CONFDIR=/etc/mouselessck
MANIFEST="$CONFDIR/.install-manifest"
PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo $0 $*" >&2; exit 1; }
[[ -r "$MANIFEST" ]] || { echo "No install manifest at $MANIFEST: nothing to remove." >&2; exit 1; }

echo "==> Stopping services"
systemctl stop mouselessck-trial.service 2>/dev/null || true
systemctl disable --now mouselessck.service 2>/dev/null || true
systemctl --global disable mouselessck-indicator.service 2>/dev/null || true
if [[ -n "${SUDO_USER:-}" ]]; then
    USER_ID="$(id -u "$SUDO_USER")"
    runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$USER_ID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" \
        systemctl --user stop mouselessck-indicator.service 2>/dev/null || true
fi

echo "==> Removing files"
# The manifest is root-owned, but this script runs as root, so it still only
# deletes paths inside the locations install.sh writes to, and never follows
# "..". Anything else in the manifest is reported and left alone.
allowed() {
    case "$1" in
        *..*) return 1 ;;
        /usr/local/lib/mouselessck/*|/usr/local/libexec/mouselessck/*|\
        /usr/local/share/doc/mouselessck/*|/usr/local/bin/mouselessck-indicator|\
        /etc/systemd/system/mouselessck.service|/etc/systemd/user/mouselessck-indicator.service|\
        /etc/udev/rules.d/70-mouselessck.rules|/etc/sysusers.d/mouselessck.conf|\
        /etc/modules-load.d/mouselessck.conf) return 0 ;;
        *) return 1 ;;
    esac
}
while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if allowed "$path"; then
        rm -f -- "$path"
    else
        echo "    skipped unexpected manifest entry: $path" >&2
    fi
done < "$MANIFEST"
rm -rf /run/systemd/system/mouselessck.service.d   # a leftover trial drop-in
rm -f "$MANIFEST"
rmdir /usr/local/lib/mouselessck/mouselessck /usr/local/lib/mouselessck \
      /usr/local/libexec/mouselessck /usr/local/share/doc/mouselessck 2>/dev/null || true
find /usr/local/lib/mouselessck -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf /usr/local/lib/mouselessck 2>/dev/null || true

if (( PURGE )); then
    echo "==> Removing configuration and the service user"
    rm -rf "$CONFDIR"
    userdel mouselessck 2>/dev/null || true
    groupdel mouselessck 2>/dev/null || true
fi

systemctl daemon-reload
udevadm control --reload-rules
udevadm trigger --action=change --sysname-match=uinput || true
echo "mouselessCK removed."
(( PURGE )) || echo "Configuration kept in $CONFDIR (use --purge to remove it)."
