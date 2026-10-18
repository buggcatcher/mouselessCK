NAME    := mouselessck
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' src/mouselessck/__init__.py)
TARBALL := dist/$(NAME)-$(VERSION).tar.gz

.PHONY: help test lint dist srpm rpm probe clean

help:
	@echo "make test    run the unit tests (needs python3-pytest)"
	@echo "make lint    byte-compile the sources and check the shell scripts"
	@echo "make dist    build $(TARBALL)"
	@echo "make rpm     build the RPM with rpmbuild (needs rpm-build)"
	@echo "make probe   phase 0: check that the desktop accepts a virtual mouse (sudo)"

test:
	python3 -m pytest -q tests

lint:
	python3 -m py_compile src/mouselessck/*.py tools/*.py
	bash -n install.sh uninstall.sh
	@command -v shellcheck >/dev/null && shellcheck install.sh uninstall.sh || true

dist:
	mkdir -p dist
	tar --exclude=dist --exclude='__pycache__' --exclude='.pytest_cache' \
	    --transform 's,^\.,$(NAME)-$(VERSION),' -czf $(TARBALL) .
	cp packaging/$(NAME).spec dist/

rpm: dist
	rpmbuild -ta $(TARBALL)

probe:
	sudo python3 tools/probe_mouse.py

clean:
	rm -rf dist .pytest_cache
	find . -name '__pycache__' -type d -exec rm -rf {} +
