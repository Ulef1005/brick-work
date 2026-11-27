#!/usr/bin/env bash
# GATE TABLE: the gate of brick-work (group: github-public; ai-wiki Test Standard § Gates, Repo Gates; ADR 0043).
# A change to this table or to this file needs Ulf's yes: the commit carries `Gate-Approved: <date> "<his words>"`.
# Tiers: commit = .githooks (pre-commit: private names; commit-msg: docs trailer); land = this script on the Mac;
#        ci = this script in check.yml (CI set; four shards, shard 1 runs the non-pytest steps).
#
# id                 tier       trigger                                       catches
# private-names      commit     the staged files (never in CI)                the maintainer's private names (patterns file)
# commit-msg         commit     every commit message                          app source changed without a user-docs change
# private-names      land       docs and full mode, off GitHub                the same names in the whole tracked tree
#                                                                             (full mode with tests: inside pytest);
#                                                                             patterns file found as at commit
# names, secrets     land, ci   docs and full mode                            names; secrets in history and working copy
#                                                                             (on GitHub: the gitleaks action, by its marker;
#                                                                             elsewhere it fails without gitleaks)
# docs               land, ci   docs and full mode                            the docs checks
# docs-tests         land, ci   docs mode, where tests run                    the docs and site tests
# tokens, docs-theme, brand, b-prime, legacy-guard, design-gate-count, screens, suite-size, api-contract,
# api-writes         land, ci   full mode                                     design, contract and suite checks
# chrome, pytest     ci         full mode (land: only with BW_LOCAL_TESTS=1)  the test suite with Chrome
# runtimes           ci         full mode (land: only with BW_LOCAL_TESTS=1)  the Node runtime harnesses
#
# Every step runs, so one failure cannot hide another; the failed steps are listed at the end (App Standard,
# Repo & checks, 2026-10-23).
set -uo pipefail
cd "$(dirname "$0")/.."

python=python3
if [[ -n "${APP_VENV:-}" && -x "$APP_VENV/bin/python" ]]; then
  python="$APP_VENV/bin/python"
elif [[ -x .venv/bin/python ]]; then
  python=.venv/bin/python
elif common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) \
    && [[ -x "$(dirname "$common")/.venv/bin/python" ]]; then
  # a session or task worktree has no .venv of its own: use the canonical checkout's (app-template e6fc10b, 2026-10-28)
  python="$(dirname "$common")/.venv/bin/python"
fi
echo "Using Python interpreter: $python"
failed=()
# Rendered tests (node harnesses, Chrome geometry and screenshots) never skip silently (ADR 0022): a missing tool fails the step, unless
# BW_SKIP_RENDERED=1 is set, and then every skipped test is named in the summary below. The test suite records its skips in $BW_RENDERED_SKIPS.
skips=$(mktemp) && : > "$skips" || exit 1
gate_summary=$(mktemp) && : > "$gate_summary" || exit 1
trap 'rm -f "$skips" "$gate_summary"' EXIT
export BW_RENDERED_SKIPS=$skips BW_GATE_SUMMARY=$gate_summary
# BW_CHECK_MODE=docs (CI sets it for a pull request that changes only documentation, scripts/check_scope.py; locally you may too) runs the name
# check, the docs checks, the site and docs tests (they build the site) and the secret scan, and not the app. Anything else is the full gate.
mode=${BW_CHECK_MODE:-full}
if [[ $mode != full && $mode != docs ]]; then echo "BW_CHECK_MODE must be full or docs, not $mode"; exit 2; fi
echo "Check mode: $mode"
# Two tiers (Repo Gates, ADR 0043): on GitHub (CI set) the gate runs everything, tests included. On the Mac it runs the land tier: every
# check except the test suite, Chrome and the Node harnesses, which the pull request's `check` runs, plus the private patterns check
# (tests/test_public_snapshot.py with BW_PRIVATE_PATTERNS_FILE), which only the Mac can run. BW_LOCAL_TESTS=1 runs the tests here too, at
# most 4 workers under the machine lock (when the GitHub minutes or the network are not available).
if [[ -n ${CI:-} || ${BW_LOCAL_TESTS:-} == 1 ]]; then run_tests=1; else run_tests=0; fi
if (( run_tests )); then echo "Tests: run here"; else echo "Tests: not run here; the pull request's check runs them on GitHub (BW_LOCAL_TESTS=1 runs them here)"; fi
# The tests run in parallel (pytest-xdist; ADR 0024): one worker per core in CI, 4 locally (Repo Gates: the M1), and the tests of the xdist group `rendered` (Chrome, the screen gate's
# shared world folder; tests/rendered.py) one at a time on one worker. BW_TEST_WORKERS overrides the count (1 runs them serially).
if [[ -n ${CI:-} ]]; then workers_default=auto; else workers_default=4; fi
pytest_args=(-q -n "${BW_TEST_WORKERS:-$workers_default}" --dist loadgroup)
# BW_SHARD=I/N (CI runs N jobs, #364): this run is the I-th. Every shard runs its share of the pytest tests (`--shard`, tests/xdist_groups.py: whole
# xdist groups, deterministic, a test file or group is never split, tests/test_shard.py checks the shards add up to the suite). Shard 1 alone runs every
# other step except the browser step, so each of them still runs once per pull request; every shard runs the browser step and pytest.
shard=${BW_SHARD:-}
shard_args=()
shard_first=1
if [[ -n $shard ]]; then
  if [[ $shard =~ ^([1-9][0-9]*)/([1-9][0-9]*)$ ]] && (( BASH_REMATCH[1] <= BASH_REMATCH[2] )); then
    shard_args=(--shard "$shard")
    (( BASH_REMATCH[1] == 1 )) || shard_first=0
  else
    echo "BW_SHARD must look like 2/3 (the second of three), not $shard"; exit 2
  fi
  echo "Shard: $shard"
fi
# The maintainer's private names, found as the commit hook finds them (.githooks/pre-commit): BW_PRIVATE_PATTERNS_FILE,
# else the shared file in ai-wiki, so a plain run of this script checks them too (Repo Gates). Without that file (a
# contributor) the generic patterns apply. A BW_PRIVATE_PATTERNS_FILE that names no file fails the private-names step.
if [[ -z ${GITHUB_ACTIONS:-} && -z ${BW_PRIVATE_PATTERNS_FILE:-} ]]; then
  shared=${HOME:-}/Workspace/ai-wiki/scripts/brick-work-private-patterns.txt
  if [[ -f $shared ]]; then
    export BW_PRIVATE_PATTERNS_FILE=$shared
    echo "Private patterns: $shared"
  else
    echo "NOTE: no private patterns file at $shared, so the private-names check uses the generic patterns only"
  fi
fi
step() {
  local name=$1
  shift
  "$@" || failed+=("$name")
}

# Repo Gates phase 1 (ai-wiki wiki/projects/repo-gates.md): one test or browser run at a time on this machine.
# heavy <program...> runs a program (not a shell function) under the machine lock ~/.cache/gate.lock, outside CI and
# only where /usr/bin/lockf exists (macOS); a nested gate (GATE_LOCK_HELD set by the outer one) does not lock again.
# Waiting is announced, and a step that waits longer than GATE_WAIT seconds (default 1800) fails instead of hanging.
heavy() {
  if [[ -n ${CI:-} || -n ${GATE_LOCK_HELD:-} || ! -x /usr/bin/lockf ]]; then "$@"; return; fi
  local lock="$HOME/.cache/gate.lock" wait="${GATE_WAIT:-1800}" rc=0
  mkdir -p "$HOME/.cache" || return
  /usr/bin/lockf -k -t 0 "$lock" true 2>/dev/null || rc=$?
  if (( rc == 75 )); then
    echo "gate: waiting up to ${wait}s for the machine lock ($lock: another gate is running tests; holder: lsof $lock)" >&2
  fi
  rc=0
  GATE_LOCK_HELD=1 /usr/bin/lockf -k -t "$wait" "$lock" "$@" || rc=$?
  if (( rc == 75 )); then echo "gate: gave up after ${wait}s waiting for the machine lock $lock" >&2; fi
  return "$rc"
}

browser() {
  # A Chrome for the geometry and screenshot tests: CHROME, else the pinned Chrome for Testing in the cache (downloaded the first time,
  # checked by version and SHA-256), else a system Chrome (scripts/chrome.py; CONTRIBUTING, Rendered tests).
  local found
  if [[ ${BW_NO_CHROME:-} == 1 ]]; then
    echo "NOTE: BW_NO_CHROME=1, so every Chrome test and every Node test is skipped and named below (set by hand; CI runs them on every pull request since 2026-11-26)."
    return 0
  fi
  if found=$(python3 scripts/chrome.py ensure); then
    export CHROME=$found
    echo "Chrome: $CHROME"
    return 0
  fi
  if [[ ${BW_SKIP_RENDERED:-} == 1 ]]; then
    echo "NOTE: no Chrome; BW_SKIP_RENDERED=1, so the Chrome tests are skipped and named below."
    return 0
  fi
  return 1
}

runtimes() {
  shopt -s nullglob
  local harnesses=(tests/*_runtime.cjs) rc=0 harness
  if [[ ${BW_NO_CHROME:-} == 1 ]]; then
    echo "NOTE: BW_NO_CHROME=1, so the Node runtime harnesses are skipped and named below (set by hand; CI runs them on every pull request since 2026-11-26)."
    (( ${#harnesses[@]} )) && printf '%s (BW_NO_CHROME=1)\n' "${harnesses[@]}" >> "$skips"   # an empty glob names nothing
    return 0
  fi
  if ! command -v node >/dev/null 2>&1; then
    if [[ ${BW_SKIP_RENDERED:-} == 1 ]]; then
      echo "NOTE: node is not installed; BW_SKIP_RENDERED=1, so the Node runtime harnesses are skipped and named below."
      printf '%s (node is not installed)\n' "${harnesses[@]}" >> "$skips"
      return 0
    fi
    echo "FAILED: node is not installed, so the Node runtime harnesses cannot run (set BW_SKIP_RENDERED=1 to skip them, named in the summary)."
    return 1
  fi
  for harness in "${harnesses[@]}"; do
    heavy node "$harness" || { echo "FAILED: $harness"; rc=1; }
  done
  return $rc
}

secrets() {
  if [[ -n ${GITHUB_ACTIONS:-} ]]; then
    # the step after the gitleaks action (shard 1, where this step runs) sets the marker only when the scan succeeded
    if [[ ${GATE_SECRET_SCAN:-} == "done" ]]; then
      echo "Secret scan: the workflow's gitleaks action (shard 1) is this run's one scan (Repo Gates)."
      return 0
    fi
    echo "ERROR: on GitHub the secret scan is the workflow's gitleaks step, and it did not run or did not pass (no GATE_SECRET_SCAN marker)"
    return 1
  fi
  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "FAILED: gitleaks is not installed, so the secret scan cannot run; install it (https://github.com/gitleaks/gitleaks#installing)."
    return 1
  fi
  local rc=0 base tree repo=$PWD
  gitleaks detect --no-banner || rc=1
  # History alone misses what is not committed yet: scan the working copy of every tracked and untracked,
  # not ignored file too. Both scans always run; a copy that fails fails the step, so a partial tree never passes.
  base=$(mktemp -d) || return 1
  tree=$base/tree
  mkdir "$tree" || { rm -rf "$base"; return 1; }
  if git ls-files -z --cached --others --exclude-standard > "$base/list"; then
    # One process copies them all: three per file (dirname, mkdir, cp) took most of the scan's time. A path that is
    # not a file (deleted, the deletion not committed) is left out; a file that cannot be copied is named and fails.
    "$python" - "$base/list" "$tree" <<'PY' || rc=1
import os
import shutil
import sys

with open(sys.argv[1], 'rb') as listing:
    names = [name for name in listing.read().split(b'\0') if name]
tree = os.fsencode(sys.argv[2])
failed = False
for name in names:
    if not os.path.isfile(name):
        continue
    target = os.path.join(tree, name)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(name, target)
    except OSError as error:
        print(f'ERROR: cannot copy {os.fsdecode(name)} for the secret scan: {error}')
        failed = True
sys.exit(1 if failed else 0)
PY
    # Scan from inside the copy: fingerprints are then repo-relative (path:rule:line), so .gitleaksignore matches.
    (cd "$tree" && gitleaks dir --no-banner --gitleaks-ignore-path "$repo/.gitleaksignore" .) || rc=1
  else
    echo 'ERROR: git ls-files failed; working-copy secret scan not run'
    rc=1
  fi
  rm -rf "$base"
  return $rc
}

docs() {
  # The docs check in report mode over the commits not yet landed (CI passes the pushed range);
  # the blocking check is the commit hook in .githooks/ (App Standard, Repo & checks).
  local range=${DOCS_RANGE:-}
  if [[ -z $range ]] && git rev-parse --verify --quiet '@{upstream}' >/dev/null; then
    range='@{upstream}..HEAD'
  fi
  if [[ -n $range ]]; then
    python3 scripts/check_docs.py range "$range"
  else
    echo 'NOTE: no upstream and no DOCS_RANGE; docs check skipped'
  fi
  # The page checks and Vale are a gate (App Docs Standard: User Docs and Developer Docs; doc-standard-v1 B6, the docs are migrated); the stale-page report is a report.
  # Vale needs its pinned binary (scripts/vale.py downloads it into the cache); with no network and no cached binary it is skipped with a note rather than
  # failing the gate, and CI, which has the network, always runs it.
  local rc=0
  python3 scripts/check_docs.py pages --gate || rc=1
  python3 scripts/check_docs.py stale
  if vale=$(python3 scripts/vale.py path 2>/dev/null); then
    VALE=$vale python3 scripts/vale.py check --gate || rc=1
  else
    echo 'NOTE: no Vale binary (no network and nothing cached); prose check skipped'
  fi
  return $rc
}

if [[ $mode == docs ]]; then
  if (( ! shard_first )); then echo "NOTE: docs mode runs on shard 1 only."; exit 0; fi
  step names "$python" scripts/check_names.py
  [[ -z ${GITHUB_ACTIONS:-} ]] && step private-names "$python" -m pytest -q -p no:xdist -p no:cacheprovider tests/test_public_snapshot.py
  (( run_tests )) && step docs-tests heavy "$python" -m pytest tests/test_docs_*.py tests/test_vale.py tests/test_site_pages.py tests/test_install_docs.py tests/test_changelog_order.py "${pytest_args[@]}"
  step secrets secrets
  step docs docs
else
  (( run_tests )) && step chrome browser
  if (( shard_first )); then
    step names "$python" scripts/check_names.py
    step tokens "$python" scripts/tokens_base.py check
    step docs-theme "$python" scripts/docs_theme.py check
    step brand "$python" scripts/brand_assets.py check
    step b-prime "$python" scripts/b_prime_css.py check
    step legacy-guard "$python" scripts/legacy_guard.py check
    step design-gate-count "$python" scripts/frame_check.py --count   # the count only; the render stays by hand (B11)
    step screens "$python" scripts/design_screens.py check
  fi
  # The standalone smoke test (tests/test_standalone_smoke.py) runs inside this step; it has no step of its own, which would only run it twice
  # (every step runs whatever the earlier ones did, so an early smoke step brought no earlier failure; #254).
  # The private patterns check on every run off GitHub (the patterns file never goes to CI), on shard 1 only, and
  # here only when the test suite does not run it anyway
  if [[ -z ${GITHUB_ACTIONS:-} ]] && (( shard_first && ! run_tests )); then
    step private-names "$python" -m pytest -q -p no:xdist -p no:cacheprovider tests/test_public_snapshot.py
  fi
  if (( run_tests )); then
    step pytest heavy "$python" -m pytest tests/ --ignore=tests/test_screen_gate.py "${pytest_args[@]}" ${shard_args[@]+"${shard_args[@]}"}   # the + form: bash 3.2 (macOS) fails an empty array under set -u
  fi
  # The screenshot gate (tests/test_screen_gate.py) no longer runs here (Ulf, 2026-11-13: screens are approved from frames in a review artifact).
  # Run it by hand: python -m pytest tests/test_screen_gate.py -q -p no:xdist
  if (( shard_first )); then
    step suite-size "$python" scripts/check_suite_size.py
    (( run_tests )) && step runtimes runtimes
    step secrets secrets
    step api-contract "$python" scripts/check_api_contract.py
    step docs docs
    step api-writes "$python" -m scripts.generate_api_writes
  fi
fi

echo
echo '--- Rendered tests ---'
if [[ -s $skips ]]; then
  sort -u "$skips" > "$skips.sorted"
  echo "Skipped rendered tests ($(wc -l < "$skips.sorted" | tr -d ' ')), BW_SKIP_RENDERED=1:"
  sed 's/^/  /' "$skips.sorted"
  rm -f "$skips.sorted"
else
  echo 'Skipped rendered tests: none (0)'
fi
if (( ! run_tests )); then
  echo '--- Tests ---'
  echo 'Tests: not run here (the test suite, Chrome and the Node harnesses); the pull request'"'"'s check runs them on GitHub. BW_LOCAL_TESTS=1 runs them here.'
fi
echo '--- Screenshot gate ---'
echo 'Screenshot gate: not run (removed from the check, 2026-11-13)'

if ((${#failed[@]})); then
  printf 'FAILED: %s\n' "${failed[*]}"
  exit 1
fi
echo 'All checks passed'
