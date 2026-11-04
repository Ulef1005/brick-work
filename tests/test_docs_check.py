"""The user-docs check (App Standard, Repo & checks): scripts/check_docs.py and the hook in .githooks/."""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)

PKG = check_docs.SOURCE[0]


@pytest.mark.parametrize(("paths", "message", "expected"), [
    ([PKG + "store.py"], "Add a store", True),
    ([PKG + "store.py", "docs/how-to/export.md"], "Add export", False),
    ([PKG + "store.py", "docs/index.md"], "Add export", False),
    ([PKG + "store.py"], "Refactor\n\nDocs: none, refactor only", False),
    ([PKG + "store.py"], "Refactor\n\nDocs: none", False),
    ([PKG + "store.py"], "Refactor\n\nDocs: nonexistent", True),
    ([PKG + "store.py", "docs/adr/0001-x.md"], "ADR only", True),
    (["static/app.js"], "UI tweak", True),
    (["app.py"], "Port", True),
    (["tests/test_store.py", "README.md"], "Tests", False),
    (["docs/runbook.md"], "Runbook", False),
])
def test_needs_docs(paths, message, expected):
    assert check_docs.needs_docs(paths, message) is expected


def test_comment_lines_do_not_count():
    assert check_docs.strip_comments("Fix\n# Docs: none\n") == "Fix"


@pytest.mark.parametrize("name", ["commit-msg", "post-commit"])
def test_hook_is_executable(name):
    hook = ROOT / ".githooks" / name
    assert hook.is_file() and hook.stat().st_mode & 0o111


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_hook_blocks_and_allows(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull}

    def git(*args, check=True):
        return subprocess.run(("git", *args), cwd=tmp_path, env=env, capture_output=True, text=True, check=check)

    git("init", "-q")
    shutil.copytree(ROOT / ".githooks", tmp_path / ".githooks")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/check_docs.py", tmp_path / "scripts/check_docs.py")
    git("config", "core.hooksPath", ".githooks")
    git("add", ".")
    git("commit", "-q", "-m", "Tooling")
    (tmp_path / PKG).mkdir(parents=True)
    (tmp_path / PKG / "app.py").write_text("x = 1\n")
    git("add", ".")
    blocked = git("commit", "-q", "-m", "Feature", check=False)
    assert blocked.returncode != 0 and "Docs: none" in blocked.stderr
    git("commit", "-q", "-m", "Feature\n\nDocs: none, scaffolding")
    (tmp_path / PKG / "app.py").write_text("x = 2\n")
    (tmp_path / "docs/how-to").mkdir(parents=True)
    (tmp_path / "docs/how-to/use.md").write_text("# Use\n")
    git("add", ".")
    git("commit", "-q", "-m", "Feature with docs")
    report = subprocess.run(("python3", "scripts/check_docs.py", "range", "HEAD~2..HEAD"), cwd=tmp_path,
                            env=env, capture_output=True, text=True, check=True)
    assert "0 commit(s)" in report.stdout
    # git quotes non-ASCII names in --name-only output unless -z is used
    (tmp_path / "static").mkdir()
    (tmp_path / "static/maße.js").write_text("x\n")
    git("add", ".")
    quoted = git("commit", "-q", "-m", "Umlaut source", check=False)
    assert quoted.returncode != 0 and "Docs: none" in quoted.stderr
    git("restore", "--staged", "static/maße.js")
    # a source file moved out of the watched paths is still a source change (rename detection off)
    (tmp_path / "app.py").write_text("".join(f"line {n}\n" for n in range(20)))
    git("add", "app.py")
    git("commit", "-q", "-m", "Add app.py\n\nDocs: none, test setup")
    git("mv", "app.py", "scripts/run_app.py")
    moved = git("commit", "-q", "-m", "Move app.py", check=False)
    assert moved.returncode != 0 and "Docs: none" in moved.stderr
    # an unreachable base (after a force push) is skipped, never an error
    gone = subprocess.run(("python3", "scripts/check_docs.py", "range", "1" * 40 + "..HEAD"), cwd=tmp_path,
                          env=env, capture_output=True, text=True, check=True)
    assert "skipped" in gone.stdout
    # an amend that drops the trailer passes commit-msg (nothing newly staged) but post-commit warns
    (tmp_path / "static/main.js").write_text("y\n")
    git("add", "static/main.js")
    git("commit", "-q", "-m", "Main\n\nDocs: none, wiring")
    amended = git("commit", "-q", "--amend", "-m", "Main")
    assert "post-commit" in amended.stderr and "Docs: none" in amended.stderr
    # --no-verify skips commit-msg; post-commit still reports
    (tmp_path / "static/other.js").write_text("z\n")
    git("add", "static/other.js")
    skipped = git("commit", "-q", "--no-verify", "-m", "Other")
    assert "post-commit" in skipped.stderr
    # a commit with docs gets no warning
    (tmp_path / "static/other.js").write_text("z2\n")
    (tmp_path / "docs/how-to/use.md").write_text("# Use, updated\n")
    git("add", ".")
    clean = git("commit", "-q", "-m", "Other with docs")
    assert "post-commit" not in clean.stderr
