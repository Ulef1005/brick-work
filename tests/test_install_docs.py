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
