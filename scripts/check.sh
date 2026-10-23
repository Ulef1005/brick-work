#!/usr/bin/env bash
set -euo pipefail

python=python3
if [[ -n "${APP_VENV:-}" && -x "$APP_VENV/bin/python" ]]; then
  python="$APP_VENV/bin/python"
elif [[ -x .venv/bin/python ]]; then
  python=.venv/bin/python
fi
echo "Using Python interpreter: $python"
"$python" scripts/check_names.py
"$python" -m pytest tests/test_standalone_smoke.py -q
"$python" -m pytest tests/ -q

if command -v node >/dev/null 2>&1; then
  shopt -s nullglob
  for harness in tests/*_runtime.cjs; do
    node "$harness"
  done
else
  echo "NOTE: node is not installed; skipping Node runtime harnesses."
fi

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-banner
else
  echo "NOTE: gitleaks is not installed; skipping secret scan."
fi

"$python" scripts/check_api_contract.py

# The docs check in report mode over the commits not yet landed (CI passes the pushed range);
# the blocking check is the commit hook in .githooks/ (App Standard, Repo & checks).
range=${DOCS_RANGE:-}
if [[ -z $range ]] && git rev-parse --verify --quiet '@{upstream}' >/dev/null; then
  range='@{upstream}..HEAD'
fi
if [[ -n $range ]]; then
  python3 scripts/check_docs.py range "$range"
else
  echo 'NOTE: no upstream and no DOCS_RANGE; docs check skipped'
fi

"$python" -m scripts.generate_api_writes
