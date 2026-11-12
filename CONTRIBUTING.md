# Contributing to Brick Work

Thank you for helping. Brick Work is maintained by one person in spare time, so this page says what helps most and what to expect.

## Report a bug or suggest a feature

- **Bugs:** open an issue with the **Bug** template. Say what happened, what you expected, the steps, and where (version or image tag, install method, device and browser).
- **Features:** open an issue with the **Enhancement** template and describe the job, not only the feature: *"When ___, I want to ___, so I can ___."* Say how you do it today.
- **Security problems:** do not open an issue; see [SECURITY.md](SECURITY.md).

Never put personal data in an issue: no real purchase lines, order numbers, addresses, host names or keys. Use sample data in screenshots.

New issues get the `needs-triage` label. The maintainer triages them, fills the design outline below the divider, and marks them `approved` once scope and decisions are settled. The public roadmap shows the order (Now, Next, Later).

## Contributions that are welcome

- Bug fixes with a test that fails before the fix.
- Imports from other collection apps and file formats.
- Translations are not set up yet; ask first.
- Anything larger, or anything that changes a screen: open or comment on an issue first, so the design can be agreed before you write code. Screens follow the design reference in `design/` (checked with `design/DESIGN-CHECK.md`); the design kit, with the brand and the data-type language, is the `brickwork-design` skill in `.claude/skills/brickwork-design/`.

Out of scope: running a BrickLink store, investment forecasting from market data, social features, and pile scanning as the main way to add parts.

## Set up and run the checks

You need Python 3.14 and, for the browser harnesses, Node.js (no npm packages are needed).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
APP_VENV=.venv bash scripts/check.sh
```

`scripts/check.sh` is the same gate CI runs: the name check, the full test suite in parallel (which includes the standalone smoke test: no keys, no network), then the screenshot gate on its own, the Node runtime harnesses, a gitleaks secret scan when gitleaks is installed, and the API contract checks. Tests use synthetic data only; never add a fixture taken from a real collection.

The tests run in parallel: `scripts/check.sh` calls `pytest -n auto --dist loadgroup` (pytest-xdist, one worker per core; `BW_TEST_WORKERS=1` runs them one at a time, which is the way to debug an order-dependent failure). A test must therefore not depend on another test, on run order, or on a fixed path, port or environment variable that two tests could use at once: use `tmp_path`, port 0 and `monkeypatch`. See [ADR 0024](docs/adr/0024-parallel-check.md).

**Docs-only pull requests.** CI runs the docs check, the docs and site tests (which build the site) and the secret scan, not the app, when every changed file is under `docs/` (except `docs/brickwork/` and `docs/data-model-4.0/`, which hold the API contract, the cutover table and the schema design that app tests read), `scripts/site/`, `mkdocs.yml`, `CHANGELOG.md` or `README.md` (`scripts/check_scope.py`). A push to `main`, a new branch, anything else in the change, or a diff CI cannot compute runs everything. The job and its name (`check`) are the same. Locally: `BW_CHECK_MODE=docs APP_VENV=.venv bash scripts/check.sh`.

Enable the commit hooks once per clone: `git config core.hooksPath .githooks`. The `commit-msg` hook blocks a commit that changes app source (`brickwork/`, `templates/`, `static/`, `app.py`, `wsgi.py`, `bin/`, `entrypoint.sh`) without a change to the user docs (any Markdown file under `docs/` except `docs/adr/` and `docs/milestones/`), unless the message ends with a `Docs: none, <reason>` trailer. The `post-commit` hook re-checks the finished commit as a whole and warns, which covers `--amend` and `--no-verify`. `scripts/check.sh` reports the same for every commit in the range it checks.

### Rendered tests

Tests that run JavaScript or draw a page need Node.js and Chrome, and they never skip silently: a missing tool **fails** the test. `scripts/check.sh` finds Chrome through `scripts/chrome.py`: the `CHROME` environment variable if set, else the pinned Chrome for Testing in `~/.cache/brickwork/chrome/<version>/` (downloaded on first use, about 150 to 200 MB, checked by version and SHA-256; Linux x86-64 and macOS on Apple silicon), else a system Chrome or Chromium. Set `BW_CHROME_CACHE` to move the cache; set `CHROME` to a binary on other platforms. No npm packages are involved.

Without a network or a browser you can run `BW_SKIP_RENDERED=1 APP_VENV=.venv bash scripts/check.sh`: the rendered tests are then skipped, and the summary ends with a "Skipped rendered tests" list naming each one. CI never sets it.

**New rendered tests.** A test that draws a page in Chrome, renders the screen gate or uses the gate's shared world folder (`/tmp/bw-gate-world`, held through one lock) joins the xdist group `rendered`: `@rendered.group` on the test, or `pytestmark = rendered.group` on the module (`tests/rendered.py`). The tests of the group run one at a time on one worker, so they never share Chrome or the folder; `rendered.chrome()` fails a test that is not in it. A test that only runs a Node harness (`rendered.need_node()`) on its own temporary files needs no group. `BW_SKIP_RENDERED` works with the workers: each records its skips in the same file and `check.sh` lists them all.

The screenshot gate (`tests/test_screen_gate.py`) compares the app with approved baseline captures; see `design/DESIGN-CHECK.md`. When you change a screen on purpose, regenerate its candidates with `python scripts/screen_gate.py capture <NN-Screen>` and say so in the pull request; the maintainer approves baselines. The gate's world fixes the clock, the fonts, the animation and the footer version (`GATE_VERSION` in `scripts/screen_gate.py`), so a release never changes a baseline. `tests/test_gate_world_clock.py` builds the demo and showcase worlds through the gate's own `world()` and fails at once, naming table and column, when a timestamp in them is not `clock.FIXED_NOW` (or a date the dataset sets on purpose), so a stamp taken on the real clock shows up there and not as a pixel difference after a full gate run. The gate renders its captures on up to four Chrome processes at once (`BW_GATE_WORKERS=1` for one; the captures are the same whichever process takes them).

The README and Pages pictures are captures of the built app on the demo's richer world: regenerate them with `python scripts/site_shots.py` (not gate baselines; the world is invented, `brickwork/demo/showcase.py`).

After a change to the demo (`brickwork/demo/`, its shim or its export), run `python scripts/check_demo_pages.py`: it builds the demo, loads every page in the pinned Chrome, light and dark, and fails on a broken picture, a stylesheet without rules, or a missing-picture note that sits in a box under 120 px or spills out of it (#197). It is not part of `scripts/check.sh` (about 2,600 page loads).

For a running app, follow the Docker steps in the [README](README.md).

## Pull requests

- One change per pull request, with tests, and `scripts/check.sh` green.
- Schema changes (4.0 line) go in `brickwork/store4/brickwork.sql` (the collection) or `catalogue.sql`, with a migration test; an existing file reaches the current version through an in-place step in `store4.connect.UPGRADES` (additive only; a new file from the schema must match an upgraded one, `tests/test_store4_upgrade.py`; see schema notes 4.1).
- Keep the API contract (`docs/brickwork/api-v2.md`, `openapi-v2.yaml`; v1's files stay as the reference) in step with any API change; the contract checks enforce it.
- Write commit messages that say what changed and why.

## Releases and the container image

A release is a `vX.Y.Z` tag on `main`, made by the maintainer, with the matching `CHANGELOG.md` section as its notes. The tag starts the `release` workflow (`.github/workflows/release.yml`):

- It builds the image natively on amd64 and arm64 and runs the same fresh-install smoke test as the `docker` workflow, before anything is pushed.
- It then pushes `ghcr.io/ulef1005/brick-work` as one multi-architecture image, tagged `X.Y.Z`, `X.Y` and `X`, plus `latest` for a release without a pre-release suffix (`v1.0.0-rc.1` gets only its own tag). An alias (`X.Y`, `X`, `latest`) only ever moves to the highest stable release it covers, so building an older tag again never moves it back. Releases run one at a time. A build provenance attestation and an SPDX SBOM attestation are pushed with it.
- Nothing is pushed unless the repository variable `GHCR_PUBLISH` is `true`. Until it is set, a tag only builds and tests, and the run says it published nothing. The maintainer sets it for the first push. The `compose.yaml` of the v0.9.0 tag builds from source (`build: .`) and the tag is never moved, so the pull-first install starts with the first release cut from `main` after it.

The release commit bumps the image tag in `compose.yaml` together with `brickwork/version.py`; `tests/test_compose_image.py` fails if they differ. It also bumps the version the install steps pin (the README's and the landing page's `git clone --branch`, the `compose.yaml` link in [Install on your computer with Docker Desktop](docs/how-to/install-docker-desktop.md)); `tests/test_install_docs.py` fails if one is left behind.

To build an existing tag again, run the workflow by hand with that tag.

The full checklist, from deciding the release to what follows the tag (changelog, user docs, upgrade guide, pictures, website, demo, image checks, Unraid template), is in [RELEASING](RELEASING.md).

## Licence of contributions

Brick Work is MIT-licensed. By submitting a contribution you agree that it is licensed under the same [MIT licence](LICENSE) as the project (inbound = outbound). No sign-off or CLA is required.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
