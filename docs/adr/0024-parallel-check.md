# 0024. The check runs its tests in parallel, its screen gate on several Chrome processes, and a docs-only change skips the app

- **Status:** accepted
- **Date:** 2026-11-09
- **Decided by:** the maintainer chose all three measures on 2026-11-09 ("Parallel tests", "Docs-only PRs fast path", "Parallel screen gate"), recorded on issue #254; after the first CI runs, the screen gate back to one Chrome session ("One session by default", 2026-11-09, PR #261). The App Standard rule that followed is "CI wall-clock" in Repo & checks (a PR check should finish in about 10 minutes).

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

**The screen gate: one Chrome session, as its own step.** The maintainer chose a parallel screen gate too, and it was built: the capture jobs went out in batches of 12 to up to four `capture_screens.cjs` processes, each a fresh Chrome. On the Mac its captures stayed within the noise of two serial runs, but the deciding Linux run (PR #261) failed: captures differed in drop-down (`<select>`) text, about 1 px lower. Under full load several came and went (9, then 3); `52-Place` at 1440 px, light, failed with the same 3,145 pixels in every run, also with the gate as its own step and one process. The cause is the session: the approved baselines were rendered in ONE Chrome session of all 198 captures, and what a session carries from page to page (the app's `sessionStorage` and `localStorage`, cached fonts and styles) shows in some captures; `52-Place` came seventh in a fresh session instead of 151st. A leak between tests was ruled out by a diagnostic run (the worker's environment unchanged; on the Mac the captures were byte-identical alone and inside the parallel run). So, with the maintainer's choice ("One session by default"):
- the gate renders in one Chrome session again, exactly as the baselines were made; `BW_GATE_WORKERS` > 1 renders in parallel batches for quick local review images only, never for a baseline or a deciding run;
- `scripts/check.sh` runs `tests/test_screen_gate.py` as its own step (`screen-gate`, without xdist) after the parallel tests, so the busy cores of the test workers never share a run with it;
- `BW_GATE_KEEP=<folder>` keeps the gate's actual captures for an inspection like this one.
A gate whose captures do not depend on the session (clean storage and warmed fonts per capture, all baselines rendered again once) would let the captures run in parallel; that is a follow-up issue.

## Consequences

- Measured locally on the same Mac (8 cores), `scripts/check.sh` in full: **876 s before, 237 to 292 s after** (three runs: 257, 292, 237; about a third); `pytest` 831 s for 4,102 tests before, 200 to 256 s for 4,121 after (the 19 new tests are the scope, group and guard tests of this change; none was removed or loosened); the screen gate's 198 captures 150 s on one Chrome process, 46 s on four; a docs-only run (`BW_CHECK_MODE=docs`) 85 s. The gate's pixels: two serial renders differ from each other in 38 of 198 captures by at most 0.037 % of the pixels (the gate allows 0.05 %), and a serial and a parallel render differ in 30 by the same amount, so the parallel render adds no noise; the 198 advisory differences against the Linux baselines on the Mac are the same 198 as before.
- On CI (PR #261): the `check` job took 7.5 minutes with the gate inside the parallel run (it took 22 to 25); with the gate as its own step about 2.5 minutes more, measured on the PR's final run and recorded on the app page. A docs-only pull request should take about 3 to 4 minutes, most of it setup.
- A test may no longer rely on run order, on another test's leftovers or on a path, port or environment variable another test could use at once. `BW_TEST_WORKERS=1` gives the serial run back for debugging.
- A new rendered test must join the group; the guard in `rendered.chrome()` says so when it does not.
- A docs-only pull request does not run the app tests or the screen gate. The gate runs in full on the push to `main` after the merge, so a mistake in that classification costs a red `main` and not a bad release.
- `check.sh` and the workflow's change detection are generic and come from app-template: the change goes to the wiki-agent as an App Standard candidate.

## Amended: the gate is parallel again (#267, 2026-11-11)

The follow-up named above was done. `scripts/capture_screens.cjs`, in the gate's deterministic mode, now starts every capture from an empty browser (it clears the cache, the origin's stored data and the web storage), loads every declared font face, and lays the page out again once the fonts are in. The cause of the 1 px was that last point: a form control laid out before its webfont arrived kept the fallback font's metrics in a fresh Chrome process, while a warm session had the font already; clearing storage alone did not change it (`gate-agree` on CI, 14 captures differed with and without it). `scripts/screen_gate.py agree` (and the `gate-agree` workflow) renders every approved state on one process and on four and compares them: on Linux, 198 captures, 0 differ. The gate's default is up to four processes again; `BW_GATE_WORKERS=1` gives the single session back. Six states changed against the old baselines by a few hundred to a few thousand pixels (text 1 px lower in a drop-down); their baselines were rendered again in CI and approved by the maintainer.

## Links

Issue #254; [ADR 0022](0022-design-roll-out.md) (rendered tests never skip silently, the screen gate); `CONTRIBUTING.md` (running the gate, the group rule, the docs-only path); `design/DESIGN-CHECK.md`.

## Amendment, 2026-11-14 (#364)

The single `check` job turned out to be the slowest part of a pull request (a median of about 600 s for `check.sh`, with pytest the larger share on the 4-vCPU runner). Option 1 above, a split into several jobs, is now done, and its objection no longer holds: `main` has no required-check rule, and the workflow's last job is still named `check`, passes only when all three shard jobs did, and is what a pull request's checks list. `pytest --shard I/N` (`tests/xdist_groups.py`) deals whole xdist groups and whole test files to the jobs, largest cost first; `scripts/check.sh` takes `BW_SHARD=I/N`; shard 1 runs every step that is neither the browser step nor pytest, so each still runs once. `tests/test_shard.py` checks that the shards together hold every test once and that no group is split. The rest of this decision stands: each shard still runs `pytest -n auto --dist loadgroup`.
