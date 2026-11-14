#!/usr/bin/env bash
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
# The tests run in parallel (pytest-xdist; ADR 0024): one worker per core, and the tests of the xdist group `rendered` (Chrome, the screen gate's
# shared world folder; tests/rendered.py) one at a time on one worker. BW_TEST_WORKERS overrides the count (1 runs them serially).
pytest_args=(-q -n "${BW_TEST_WORKERS:-auto}" --dist loadgroup)
# BW_SHARD=I/N (CI runs N jobs, #364): this run is the I-th. Every shard runs its share of the pytest tests (`--shard`, tests/xdist_groups.py: whole
# xdist groups, deterministic, a test file or group is never split, tests/test_shard.py checks the shards add up to the suite). Shard 1 alone runs every
# other step, so each of them still runs once per pull request; the other shards run the browser step and pytest only.
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
step() {
  local name=$1
  shift
  "$@" || failed+=("$name")
}

browser() {
  # A Chrome for the geometry and screenshot tests: CHROME, else the pinned Chrome for Testing in the cache (downloaded the first time,
  # checked by version and SHA-256), else a system Chrome (scripts/chrome.py; CONTRIBUTING, Rendered tests).
  local found
  if [[ ${BW_NO_CHROME:-} == 1 ]]; then
    echo "NOTE: BW_NO_CHROME=1, so every Chrome test and every Node test is skipped and named below (CI sets it on pull requests; run them by hand before a release)."
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
    echo "NOTE: BW_NO_CHROME=1, so the Node runtime harnesses are skipped and named below (CI sets it on pull requests; a push to main runs them)."
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
    node "$harness" || { echo "FAILED: $harness"; rc=1; }
  done
  return $rc
}

secrets() {
  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "NOTE: gitleaks is not installed; skipping secret scan."
    return 0
  fi
  local rc=0 base tree f repo=$PWD
  gitleaks detect --no-banner || rc=1
  # History alone misses what is not committed yet: scan the working copy of every tracked and untracked,
  # not ignored file too. Both scans always run; a copy that fails fails the step, so a partial tree never passes.
  base=$(mktemp -d) || return 1
  tree=$base/tree
  mkdir "$tree" || { rm -rf "$base"; return 1; }
  if git ls-files -z --cached --others --exclude-standard > "$base/list"; then
    while IFS= read -r -d '' f; do
      if [[ -f $f ]]; then
        mkdir -p "$tree/$(dirname "$f")" && cp -p "$f" "$tree/$f" || { echo "ERROR: cannot copy $f for the secret scan"; rc=1; }
      fi
    done < "$base/list"
    # Scan from inside the copy: fingerprints are then repo-relative (path:rule:line), so .gitleaksignore matches.
    (cd "$tree" && gitleaks dir --no-banner --gitleaks-ignore-path "$repo/.gitleaksignore" .) || rc=1
  else
    echo 'ERROR: git ls-files failed; working-copy secret scan not run'
    rc=1
  fi
  rm -rf "$base"
  return $rc
}

quarantine() {
  # Tests that wait for their module's port to the 4.0 store (tests/quarantine.py; the list can only shrink). Importing them to
  # count would need the 3.3 store, so the tests are counted statically: every `def test_*`, parametrised cases not expanded.
  "$python" - <<'PY'
import ast
import sys
sys.path.insert(0, '.')
from tests.quarantine import QUARANTINE
tests = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')
            for name in QUARANTINE for n in ast.walk(ast.parse(open(name).read())))
print(f'quarantined: {len(QUARANTINE)} files / {tests} tests (def test_ counted, parametrised cases not expanded)')
PY
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
  step docs-tests "$python" -m pytest tests/test_docs_*.py tests/test_vale.py tests/test_site_pages.py tests/test_install_docs.py tests/test_changelog_order.py "${pytest_args[@]}"
  step secrets secrets
  step docs docs
else
  step chrome browser
  if (( shard_first )); then
    step names "$python" scripts/check_names.py
    step tokens "$python" scripts/tokens_base.py check
    step docs-theme "$python" scripts/docs_theme.py check
    step brand "$python" scripts/brand_assets.py check
    step screens "$python" scripts/design_screens.py check
  fi
  # The standalone smoke test (tests/test_standalone_smoke.py) runs inside this step; it has no step of its own, which would only run it twice
  # (every step runs whatever the earlier ones did, so an early smoke step brought no earlier failure; #254).
  step pytest "$python" -m pytest tests/ --ignore=tests/test_screen_gate.py "${pytest_args[@]}" ${shard_args[@]+"${shard_args[@]}"}   # the + form: bash 3.2 (macOS) fails an empty array under set -u
  # The screenshot gate (tests/test_screen_gate.py) no longer runs here (Ulf, 2026-11-13: screens are approved from frames in a review artifact).
  # Run it by hand: python -m pytest tests/test_screen_gate.py -q -p no:xdist
  if (( shard_first )); then
    step quarantine quarantine
    step suite-size "$python" scripts/check_suite_size.py
    step runtimes runtimes
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
echo '--- Screenshot gate ---'
echo 'Screenshot gate: not run (removed from the check, 2026-11-13)'

if ((${#failed[@]})); then
  printf 'FAILED: %s\n' "${failed[*]}"
  exit 1
fi
echo 'All checks passed'
