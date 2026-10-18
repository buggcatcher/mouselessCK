Name:           mouselessck
Version:        1.0.4
Release:        1%{?dist}
Summary:        Drive the mouse pointer from the keyboard (Meta+M toggle)
License:        MIT
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pytest
BuildRequires:  systemd-rpm-macros

Requires:       python3
Requires:       python3-evdev
Requires:       python3-pyudev
Requires:       glib2
# on-screen indicator
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4
Requires:       gtk4-layer-shell
%{?systemd_requires}

%description
mouselessCK turns the keyboard into a mouse. Tap Meta+M to enter mouse mode:
WASD or the arrow keys move the pointer, Space plus a direction scrolls,
J or Enter, K and L click. Left Shift slows the pointer down for precision.
Tap Meta+M again to type normally. A small translucent icon shows when mouse
mode is on. Works below the compositor (evdev/uinput), so it runs on KDE
Plasma, GNOME, wlroots compositors and X11; the icon needs layer-shell.

%prep
%autosetup

%build
# pure Python, nothing to build

%install
install -d %{buildroot}%{python3_sitelib}/mouselessck
install -m 0644 src/mouselessck/*.py %{buildroot}%{python3_sitelib}/mouselessck/

subst() {
    sed -e 's|@PYLIBDIR@|%{python3_sitelib}|g' \
        -e 's|@LIBEXECDIR@|%{_libexecdir}/mouselessck|g' \
        -e 's|@BINDIR@|%{_bindir}|g' \
        -e 's|@DOCDIR@|%{_docdir}/%{name}|g' "$1" > "$2"
}
install -d %{buildroot}%{_libexecdir}/mouselessck %{buildroot}%{_bindir} \
           %{buildroot}%{_unitdir} %{buildroot}%{_userunitdir}
subst bin/mouselessckd.in %{buildroot}%{_libexecdir}/mouselessck/mouselessckd
subst bin/mouselessck-indicator.in %{buildroot}%{_bindir}/mouselessck-indicator
chmod 0755 %{buildroot}%{_libexecdir}/mouselessck/mouselessckd %{buildroot}%{_bindir}/mouselessck-indicator
subst data/mouselessck.service.in %{buildroot}%{_unitdir}/mouselessck.service
subst data/mouselessck-indicator.service.in %{buildroot}%{_userunitdir}/mouselessck-indicator.service

install -Dm 0644 data/70-mouselessck.rules %{buildroot}%{_udevrulesdir}/70-mouselessck.rules
install -Dm 0644 data/mouselessck.sysusers %{buildroot}%{_sysusersdir}/mouselessck.conf
install -Dm 0644 data/mouselessck-modules.conf %{buildroot}%{_modulesloaddir}/mouselessck.conf
install -Dm 0644 config/config.toml %{buildroot}%{_sysconfdir}/mouselessck/config.toml
install -Dm 0755 tools/probe_mouse.py %{buildroot}%{_docdir}/%{name}/probe_mouse.py
install -Dm 0755 tools/probe_scroll.py %{buildroot}%{_docdir}/%{name}/probe_scroll.py
install -Dm 0755 tools/probe_reverse.py %{buildroot}%{_docdir}/%{name}/probe_reverse.py
install -Dm 0755 tools/mouselessck-trial %{buildroot}%{_libexecdir}/mouselessck/mouselessck-trial

%check
%{python3} -m pytest -q tests

%post
%udev_rules_update
%systemd_post mouselessck.service
%systemd_user_post mouselessck-indicator.service

%preun
%systemd_preun mouselessck.service
%systemd_user_preun mouselessck-indicator.service

%postun
%udev_rules_update
%systemd_postun_with_restart mouselessck.service

%files
%license LICENSE
%doc README.md SECURITY.md CHANGELOG.md docs/DESIGN.md
%{_docdir}/%{name}/probe_mouse.py
%{_docdir}/%{name}/probe_scroll.py
%{_docdir}/%{name}/probe_reverse.py
%{python3_sitelib}/mouselessck/
%{_libexecdir}/mouselessck/
%{_bindir}/mouselessck-indicator
%{_unitdir}/mouselessck.service
%{_userunitdir}/mouselessck-indicator.service
%{_udevrulesdir}/70-mouselessck.rules
%{_sysusersdir}/mouselessck.conf
%{_modulesloaddir}/mouselessck.conf
%dir %{_sysconfdir}/mouselessck
%config(noreplace) %{_sysconfdir}/mouselessck/config.toml

%changelog
* Sun Oct 18 2026 Marko Ilincic - 1.0.4-1
- Precision on either Shift key, not only the left one.
- Trial: a "yes" counts only if mouselessCK is still running and has taken
  over at least one keyboard.
- One log line per mode change, with the reason (lock, sleep, stopping).
- Diagnostic probes: probe_scroll.py, probe_reverse.py, probe_mouse.py --hscroll.

* Sun Oct 18 2026 Marko Ilincic - 1.0.4-1
- Trial: a confirmation typed after the emergency stop no longer enables
  the service. One log line per mode change, with the reason.
- Diagnostic tools: probe_scroll.py, probe_reverse.py.

* Sun Oct 18 2026 Marko Ilincic - 1.0.3-1
- Emergency chord tracks keys per keyboard: unplugging a keyboard with a
  key held, or holding the same modifier on two keyboards, no longer leaves
  a phantom key (independent review).

* Sun Oct 18 2026 Marko Ilincic - 1.0.2-1
- Security review: errors logged without messages (no key codes), bounded
  one-way state socket, gdbus and layer-shell by absolute path, socket path
  validation, trial runs the fully sandboxed unit, uninstall allowlist,
  user files read as the user, SECURITY.md.

* Sun Oct 18 2026 Marko Ilincic - 1.0.1-1
- Safety net: emergency chord (both Shift + Esc), fail-open on internal
  errors, restart limit, 90-second confirmed trial before enabling.

* Sun Oct 18 2026 Marko Ilincic - 1.0.0-1
- First release: Meta+M toggle, WASD/arrows, Space scroll, J/Enter K L clicks,
  precision on left Shift, layer-shell indicator, hardened systemd service.
