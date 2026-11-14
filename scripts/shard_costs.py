"""Rewrite tests/shard_costs.json from a pytest run with durations (#364, item 1): what `--shard` uses to balance the CI jobs.

    BW_NO_CHROME=1 python -m pytest tests/ --ignore=tests/test_screen_gate.py -q -n auto --dist loadgroup --durations=0 > /tmp/dur.txt
    python scripts/shard_costs.py /tmp/dur.txt

Each unit (an xdist group, else a test file) gets the seconds of its setup, call and teardown phases added up; the shard deal only needs the
proportions, so a run on any machine will do. Units under a second are left out (they cost 0.1 s a test by default)."""
import json
from pathlib import Path
import re
import sys

OUT = Path(__file__).resolve().parent.parent / 'tests' / 'shard_costs.json'


def costs(text):
    total = {}
    for line in text.splitlines():
        found = re.match(r'\s*([\d.]+)s (?:setup|call|teardown)\s+(tests/\S+?\.py)::\S*?(?:@([\w-]+))?\s*$', line)
        if found:
            unit = found[3] or found[2]
            total[unit] = total.get(unit, 0.0) + float(found[1])
    return {unit: round(seconds, 1) for unit, seconds in sorted(total.items()) if seconds >= 1}


if __name__ == '__main__':
    data = costs(Path(sys.argv[1]).read_text())
    OUT.write_text(json.dumps(data, indent=1) + '\n')
    print(f'{len(data)} units, {sum(data.values()):.0f} s in all, written to {OUT}')
