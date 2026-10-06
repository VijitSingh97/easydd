PREFIX ?= /usr/local
ZSH_COMPLETION_DIR ?= $(PREFIX)/share/zsh/site-functions

.PHONY: test check install uninstall

test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v

check:
	python3 -c 'from pathlib import Path; p = Path("bin/easydd"); compile(p.read_text(), str(p), "exec")'

install:
	install -d "$(DESTDIR)$(PREFIX)/bin" "$(DESTDIR)$(ZSH_COMPLETION_DIR)"
	install -m 755 bin/easydd "$(DESTDIR)$(PREFIX)/bin/easydd"
	install -m 644 completions/_easydd "$(DESTDIR)$(ZSH_COMPLETION_DIR)/_easydd"

uninstall:
	rm -f "$(DESTDIR)$(PREFIX)/bin/easydd" "$(DESTDIR)$(ZSH_COMPLETION_DIR)/_easydd"
