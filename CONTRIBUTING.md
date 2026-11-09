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

`scripts/check.sh` is the same gate CI runs: the name check, the standalone smoke test (no keys, no network), the full test suite, the Node runtime harnesses, a gitleaks secret scan when gitleaks is installed, and the API contract checks. Tests use synthetic data only; never add a fixture taken from a real collection.

Enable the commit hooks once per clone: `git config core.hooksPath .githooks`. The `commit-msg` hook blocks a commit that changes app source (`brickwork/`, `templates/`, `static/`, `app.py`, `wsgi.py`, `bin/`, `entrypoint.sh`) without a change to the user docs (any Markdown file under `docs/` except `docs/adr/` and `docs/milestones/`), unless the message ends with a `Docs: none, <reason>` trailer. The `post-commit` hook re-checks the finished commit as a whole and warns, which covers `--amend` and `--no-verify`. `scripts/check.sh` reports the same for every commit in the range it checks.

### Rendered tests

Tests that run JavaScript or draw a page need Node.js and Chrome, and they never skip silently: a missing tool **fails** the test. `scripts/check.sh` finds Chrome through `scripts/chrome.py`: the `CHROME` environment variable if set, else the pinned Chrome for Testing in `~/.cache/brickwork/chrome/<version>/` (downloaded on first use, about 150 to 200 MB, checked by version and SHA-256; Linux x86-64 and macOS on Apple silicon), else a system Chrome or Chromium. Set `BW_CHROME_CACHE` to move the cache; set `CHROME` to a binary on other platforms. No npm packages are involved.

Without a network or a browser you can run `BW_SKIP_RENDERED=1 APP_VENV=.venv bash scripts/check.sh`: the rendered tests are then skipped, and the summary ends with a "Skipped rendered tests" list naming each one. CI never sets it.

The screenshot gate (`tests/test_screen_gate.py`) compares the app with approved baseline captures; see `design/DESIGN-CHECK.md`. When you change a screen on purpose, regenerate its candidates with `python scripts/screen_gate.py capture <NN-Screen>` and say so in the pull request; the maintainer approves baselines.

The README and Pages pictures are captures of the built app on the demo's richer world: regenerate them with `python scripts/site_shots.py` (not gate baselines; the world is invented, `brickwork/demo/showcase.py`).

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

The release commit bumps the image tag in `compose.yaml` together with `brickwork/version.py`; `tests/test_compose_image.py` fails if they differ.

To build an existing tag again, run the workflow by hand with that tag.

## Licence of contributions

Brick Work is MIT-licensed. By submitting a contribution you agree that it is licensed under the same [MIT licence](LICENSE) as the project (inbound = outbound). No sign-off or CLA is required.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
