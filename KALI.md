# Running mouselessCK on Kali / Debian / Ubuntu

mouselessCK is written for Fedora, but only its **installer** is Fedora-specific
(it uses `dnf` and RPM package names). The daemon, the systemd unit, the udev
rule and the logind integration are all distro-agnostic. This folder adds what
is needed to install and run it on an apt-based system such as Kali.

Tested target here: **Kali Linux in VirtualBox** (Debian-based). The same steps
work on Debian and Ubuntu.

## What was changed from upstream

1. **`install.kali.sh`** (new) — installs the Debian package equivalents of the
   Fedora dependencies with `apt`, then delegates to the normal `install.sh
   --no-deps`, which handles everything else. The Fedora-only parts of
   `install.sh` degrade on their own on Kali: the `rpm -q` check is skipped when
   `rpm` is absent, SELinux `restorecon` is guarded by `command -v` (Kali uses
   AppArmor), and the KDE Meta+M shortcut check simply reports "free" on
   Xfce/GNOME.
2. **`src/mouselessck/preload.py`** (one function) — the on-screen icon loads
   `libgtk4-layer-shell` by absolute path. The original glob only looked in
   `/usr/lib*/` directly, which is where Fedora puts libraries; Debian/Ubuntu/
   Kali use **multiarch** and put the shared library one level deeper, in a
   triplet directory (`/usr/lib/x86_64-linux-gnu/`). The glob now also searches
   that level, so the icon can find its library on Kali. It still searches only
   root-owned system directories. (The exact diff is the second commit on this
   branch; see `pr/` for the patch series.)

Nothing else in the program was modified. The emergency chord, fail-open, the
sandboxed systemd unit, the one-way state socket and the 90-second trial are all
exactly as upstream.

## Install

```bash
sudo ./install.kali.sh
```

This installs the dependencies, puts the program under `/usr/local`, creates the
`mouselessck` service user, grants it `/dev/uinput`, and runs a **90-second
trial**: the real, sandboxed service runs with a hard 90-second limit enforced by
systemd, and is enabled at boot only if you type `yes` *through* mouselessCK
during the trial. If the keyboard misbehaves, do nothing and wait — or hold both
Shift keys and press Esc.

Then start the icon (only shows on a supported Wayland session, see below):

```bash
systemctl --user start mouselessck-indicator
```

Options: `--no-start` installs the files without the trial and enables nothing;
`--no-deps` skips `apt` if you installed the dependencies yourself.

Undo with `sudo ./uninstall.sh` (`--purge` also removes the configuration and the
service user).

## What to expect by session type

| Kali session | Pointer, clicks, scroll | On-screen icon |
| --- | --- | --- |
| **Xfce on X11** (Kali default) | yes | **no** — X11 has no layer-shell; this is normal, not a fault |
| GNOME on Wayland | yes | no (GNOME has no layer-shell) |
| KDE Plasma 6 (Wayland) | yes | yes |
| Sway, Hyprland, niri, other wlroots | yes | yes |

So on a stock Kali VM (Xfce/X11) everything works **except** the little icon,
exactly as on any X11 desktop. To get the icon, use a Wayland wlroots or KDE
session; the `gtk4-layer-shell` packages are installed by `install.kali.sh` when
available.

## Running inside a VM (VirtualBox)

- The guest kernel needs the `uinput` module. The installer runs `modprobe
  uinput` and drops a `modules-load.d` entry so it loads at boot. If `modprobe
  uinput` fails, your VM kernel lacks it — install the matching
  `linux-headers`/kernel for Kali or enable the module.
- VirtualBox often exposes an **absolute** USB-tablet pointer for mouse
  integration. mouselessCK adds a separate **relative** virtual mouse; the two
  coexist, no conflict.
- A VM is a good place to trial this: besides the emergency chord (both Shift +
  Esc) and the 90-second auto-off, you can always reset or power off the VM from
  the host, so you can never lock yourself out of the host machine.
- On X11 the desktop may apply its own pointer acceleration to the virtual
  mouse. If the pointer feels off, flatten it with
  `xinput --set-prop "mouselessCK Virtual Mouse" "libinput Accel Profile Enabled" 0, 1`
  (the KDE "Flat profile" setting mentioned in the main README is the KDE
  equivalent).

## Verify

```bash
make test     # unit tests, no hardware needed
make lint
sudo python3 tools/probe_mouse.py   # moves the pointer in a square and scrolls
```

All unit tests pass. This branch also fixes a pre-existing upstream failure
(`test_shipped_config_file_parses`): the shipped `config/config.toml` set the
indicator `size`/`margin` to values that differed from the coded defaults, so
the "shipped config equals defaults" assertion failed. The shipped template is
now aligned to the coded defaults (a template-only change, no behavioural
difference). It is a separate commit, so a maintainer can take it on its own.
