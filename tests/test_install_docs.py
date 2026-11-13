"""The v0.9.0 tag has no pull-first compose.yaml, so no doc may tell its user to pull (#238)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("README.md", "docs/how-to/upgrade.md", "docs/how-to/back-up-and-restore.md", "scripts/site/landing.html")


def test_v090_install_steps_do_not_pull():
    for name in DOCS:
        text = (ROOT / name).read_text()
        for block in re.findall(r"```.*?```|<pre.*?</pre>", text, re.S):
            if "v0.9.0" in block:
                assert not re.search(r"^docker compose pull", block, re.M), f"{name}: a v0.9.0 step says docker compose pull"


INSTALL_PINS = ("README.md", "scripts/site/landing.html", "docs/how-to/install-docker-desktop.md")


def test_install_steps_name_the_current_release():
    """The install steps pin the release they install (a clone of its tag, its compose.yaml), so a release commit
    that bumps brickwork/version.py must bump them too, or a new user installs the old version."""
    from brickwork.version import __version__

    pins = {
        "README.md": r"git clone --branch (v[\w.-]+) ",
        "scripts/site/landing.html": r"git clone --branch (v[\w.{}-]+) ",
        "docs/how-to/install-docker-desktop.md": r"raw\.githubusercontent\.com/Ulef1005/brick-work/(v[\w.-]+)/compose\.yaml",
    }
    for name in INSTALL_PINS:
        found = [pin.replace("{version}", __version__) for pin in re.findall(pins[name], (ROOT / name).read_text())]   # the site templates fill the tag at build time
        assert found, f"{name}: no pinned install step found"
        assert set(found) == {f"v{__version__}"}, f"{name}: install pins {sorted(set(found))}, the app is v{__version__}"
