# 0024. The check runs its tests in parallel, its screen gate on several Chrome processes, and a docs-only change skips the app

- **Status:** accepted
- **Date:** 2026-11-09
- **Decided by:** the maintainer chose all three measures on 2026-11-09 ("Parallel tests", "Docs-only PRs fast path", "Parallel screen gate"), recorded on issue #254. The App Standard rule that followed is "CI wall-clock" in Repo & checks (a PR check should finish in about 10 minutes).

## Context

The `check` job took about 22 minutes (25 with setup) on every pull request, and almost all of it was `scripts/check.sh`. Measured on main, on a Mac with 8 cores, `pytest tests/` took 844 s for 4,092 tests run one at a time:

- about 470 s: some 4,050 in-process tests at about 0.1 s each;
- about 280 s: the tests that use Chrome, the demo export or the site build; 148 s of it is `test_approved_states_match_their_baselines`, which rendered its 198 captures one after another;
- the standalone smoke tests ran twice (their own step, then inside `tests/`);
- a pull request that changed one line of a how-to ran all of it.

## Options considered

1. **A faster runner or a split into several jobs.** Costs money or changes the job names that branch protection would require; the tests still run serially inside each job.
2. **Parallel tests (pytest-xdist), a docs-only fast path, a parallel screen gate** (the maintainer's choice). Uses the cores the runner already has, keeps the single `check` job and its name, and each part is independent of the others.
3. **Trim the suite.** Rules out nothing on its own, but means removing or weakening tests; refused.

## Decision

Option 2, as three parts.

**Parallel tests.** `scripts/check.sh` runs `pytest -n auto --dist loadgroup` (pytest-xdist 3.8.0, pinned in `requirements-dev.txt` with its one dependency execnet). Tests that share Chrome or the screen gate's world folder go in the xdist group `rendered` (`tests/rendered.py`: `@rendered.group`, or `pytestmark = rendered.group` for `tests/test_screen_gate.py`); `--dist loadgroup` runs a group on one worker, one test at a time. `rendered.chrome()` fails a test that is not in the group, so a new Chrome test cannot forget it. Three things the move to workers showed:

- **pytest-xdist 3.8.0 ignores its groups on pytest 9.2.** It tags a grouped test through `item._nodeid`, which pytest 9.2 no longer reads (`item._id`). The first runs put the gate tests on three workers at once, each waiting for the world folder's lock for 80 s, and a Chrome geometry test failed to start its browser beside the gate's four. `tests/xdist_groups.py` applies the group through `_id`; `tests/test_xdist_groups.py` fails if a future pair loses the grouping again.
- **Zensical's cache is shared.** `scripts/build_site.py` built the user docs from `mkdocs.yml` in the repo root, so every build used and cleared (`--clean`) the same `.cache`; concurrent builds panicked or reported missing pages, and seven site tests errored. Each build now has its own temporary folder with a copy of `docs/` and its own cache.
- **Module fixtures that build the demo or the site run once per worker that needs them**, about a minute each under load. `tests/test_demo.py` and `tests/test_site_pages.py` are each one group (`demo`, `site-pages`), so one worker builds each fixture. That is for time, not for shared state: the demo export and the site build use their own `tmp_path`, temporary folders and no ports, and change `os.environ` only in their own process.

The tests that only run a Node harness need no group. `BW_RENDERED_SKIPS` works with workers: the controller writes each skip once, without the group suffix, and `check.sh` lists them. The summary file `BW_GATE_SUMMARY` is written by the one worker that runs the gate. The separate smoke step is gone: `tests/` includes `tests/test_standalone_smoke.py`, and since every step of `check.sh` runs whatever the earlier ones did, an early smoke step brought no earlier failure and only ran the tests twice.

**Docs-only fast path.** The workflow's `Which check` step asks `scripts/check_scope.py BASE HEAD` for a pull request: the files changed since the merge base (`git diff --name-only --no-renames BASE...HEAD`; the full history is fetched). When every one is documentation, `check.sh` runs in `BW_CHECK_MODE=docs`: the name check, the docs and site tests (`tests/test_docs_*.py`, `test_site_pages.py`, `test_install_docs.py`, `test_changelog_order.py`; they build the site and the demo it contains), the secret scan and the docs-range report. Documentation is `docs/`, `scripts/site/`, `mkdocs.yml`, `CHANGELOG.md` and `README.md`, except `docs/brickwork/` and `docs/data-model-4.0/`: the API and MCP contract, the cutover table and the schema design, which app tests and `check_api_contract.py` read. `design/` (the screen baselines among it) always runs the full gate. Pushes to `main`, a new branch (its `before` is all zeros, and a push event runs everything anyway), a force push, an empty or failing diff and any unlisted file run the full gate. The job is still `check` in the workflow `check`.

**Parallel screen gate.** `scripts/screen_gate.py` hands the capture jobs, in batches of 12 consecutive jobs, to up to four `capture_screens.cjs` processes at once (`BW_GATE_WORKERS`, default the cores, at most four). Each process starts its own Chrome with its own profile and debugging port; each job sets its viewport, colour scheme and page, and the process sets the fixed clock, the no-animation style and reduced motion for itself, so the output does not depend on which process takes a job. The fonts, the clock and the settings are unchanged, and `test_a_state_renders_the_same_twice` still holds.

## Consequences

- Measured locally on the same Mac (8 cores), `scripts/check.sh` in full: **876 s before, 237 to 292 s after** (three runs: 257, 292, 237; about a third); `pytest` 831 s for 4,102 tests before, 200 to 256 s for 4,121 after (the 19 new tests are the scope, group and guard tests of this change; none was removed or loosened); the screen gate's 198 captures 150 s on one Chrome process, 46 s on four; a docs-only run (`BW_CHECK_MODE=docs`) 85 s. The gate's pixels: two serial renders differ from each other in 38 of 198 captures by at most 0.037 % of the pixels (the gate allows 0.05 %), and a serial and a parallel render differ in 30 by the same amount, so the parallel render adds no noise; the 198 advisory differences against the Linux baselines on the Mac are the same 198 as before.
- CI expectation: the runner has 4 cores, not 8, and the install, Chrome download (cached) and gitleaks steps are unchanged, so the `check` job should take about 8 to 10 minutes (it took 22 to 25); the first pull request measures it, and the number goes on the app page. A docs-only pull request should take about 3 to 4 minutes, most of it setup.
- A test may no longer rely on run order, on another test's leftovers or on a path, port or environment variable another test could use at once. `BW_TEST_WORKERS=1` gives the serial run back for debugging.
- A new rendered test must join the group; the guard in `rendered.chrome()` says so when it does not.
- A docs-only pull request does not run the app tests or the screen gate. The gate runs in full on the push to `main` after the merge, so a mistake in that classification costs a red `main` and not a bad release.
- `check.sh` and the workflow's change detection are generic and come from app-template: the change goes to the wiki-agent as an App Standard candidate.

## Links

Issue #254; [ADR 0022](0022-design-roll-out.md) (rendered tests never skip silently, the screen gate); `CONTRIBUTING.md` (running the gate, the group rule, the docs-only path); `design/DESIGN-CHECK.md`.
