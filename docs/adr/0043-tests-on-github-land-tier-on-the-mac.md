# 0043. Tests run on GitHub; the Mac runs the land tier

- **Status:** accepted
- **Date:** 2026-11-26
- **Decided by:** the maintainer approved the Repo Gates plan (ai-wiki `wiki/projects/repo-gates.md`) on 2026-11-26: tests run on GitHub only for GitHub repos, Chrome and Node tests run on pull requests, one secret scan per CI run, and the quarantine step goes. Brick Work's part was pulled forward the same day so the Brick Work pause could end sooner.

## Context

Before a merge, every session ran the whole gate on the maintainer's Mac: about 6,000 tests on one worker per core, plus Chrome. That took 300 to 455 seconds per run, and several sessions running it at once nearly overloaded the Mac. GitHub ran the same tests again on the pull request, and on a public repository its runners cost nothing. CI also ran the secret scan six times per run (the gitleaks action in each of four shards, then `gitleaks detect` and `gitleaks dir` in shard 1). Pull requests skipped every Chrome and Node test (2026-11-13), so the Mac was the only place they ran before a merge.

## Decision

- **Two tiers in `scripts/check.sh`.** With `CI` set (GitHub), it runs everything, as before. On the Mac it runs the land tier: the name gate, the token, theme, brand and design checks, the suite size, the API contract, the docs checks and the secret scan, but not the test suite, the Chrome step or the Node harnesses. It says so at the start ("Tests: not run here").
- **The private patterns check stays on the Mac.** `tests/test_public_snapshot.py` runs in the land tier with `BW_PRIVATE_PATTERNS_FILE`, which never goes to CI, so it still runs before every merge.
- **Pull requests run Chrome and Node tests.** `check.yml` no longer sets `BW_NO_CHROME` on pull requests, and it installs Node on every run. This replaces the 2026-11-13 decision, because the Mac no longer runs them.
- **One secret scan per CI run.** The gitleaks action runs in shard 1 only; a step after it sets `GATE_SECRET_SCAN=done` only when the scan succeeded. In CI, `check.sh` skips its own scan with that marker and fails without it. On the Mac, `check.sh` still scans the history and the working copy before a push, because on a public repository a pushed secret is public at once.
- **`BW_LOCAL_TESTS=1`** runs the tests on the Mac anyway, at most 4 workers under the machine lock (`heavy`, #729), for when GitHub cannot run them.
- **The quarantine count step goes.** The quarantine has been empty since M.11e (#113). `tests/test_quarantine.py` still keeps it empty.

## Consequences

- A landing on the Mac takes seconds to about a minute instead of 5 to 10 minutes, and adds no test load.
- A change is merged only when the pull request's `check` is green on its latest commit. The Mac no longer catches a red test before a push, so a failing pull request is fixed and pushed once.
- The pull request check gets slower by the Chrome and Node tests. It must stay within the 10-minute target (App Standard, CI wall-clock).
