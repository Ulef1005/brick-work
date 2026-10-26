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
fi
echo "Using Python interpreter: $python"
failed=()
step() {
  local name=$1
  shift
  "$@" || failed+=("$name")
}

runtimes() {
  if ! command -v node >/dev/null 2>&1; then
    echo "NOTE: node is not installed; skipping Node runtime harnesses."
    return 0
  fi
  local rc=0 harness
  shopt -s nullglob
  for harness in tests/*_runtime.cjs; do
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
}

step names "$python" scripts/check_names.py
step smoke "$python" -m pytest tests/test_standalone_smoke.py -q
step pytest "$python" -m pytest tests/ -q
step quarantine quarantine
step runtimes runtimes
step secrets secrets
step api-contract "$python" scripts/check_api_contract.py
step docs docs
step api-writes "$python" -m scripts.generate_api_writes

if ((${#failed[@]})); then
  printf 'FAILED: %s\n' "${failed[*]}"
  exit 1
fi
echo 'All checks passed'
