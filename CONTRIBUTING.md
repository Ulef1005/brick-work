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
- Anything larger, or anything that changes a screen: open or comment on an issue first, so the design can be agreed before you write code. Screens follow the design reference in `design/`.

Out of scope: running a BrickLink store, investment forecasting from market data, social features, and pile scanning as the main way to add parts.

## Set up and run the checks

You need Python 3.14 and, for the browser harnesses, Node.js (no npm packages are needed).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
APP_VENV=.venv bash scripts/check.sh
```

`scripts/check.sh` is the same gate CI runs: the name check, the standalone smoke test (no keys, no network), the full test suite, the Node runtime harnesses, a gitleaks secret scan when gitleaks is installed, and the API contract checks. Tests use synthetic data only; never add a fixture taken from a real collection.

For a running app, follow the Docker steps in the [README](README.md).

## Pull requests

- One change per pull request, with tests, and `scripts/check.sh` green.
- Schema changes go in an additive upgrade in `brickwork/core/upgrade.py`, not in `schema.sql`.
- Keep the API contract (`docs/brickwork/api-v1.md`, `openapi-v1.yaml`) in step with any API change; the contract checks enforce it.
- Write commit messages that say what changed and why.

## Licence of contributions

Brick Work is MIT-licensed. By submitting a contribution you agree that it is licensed under the same [MIT licence](LICENSE) as the project (inbound = outbound). No sign-off or CLA is required.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
