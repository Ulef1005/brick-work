"""`--shard I/N` (tests/xdist_groups.py, #364 item 1): the CI jobs together run every test once, and a group is never split."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests import xdist_groups

ROOT = Path(__file__).resolve().parents[1]
COUNT = 3


def test_the_deal_is_deterministic_complete_and_balanced():
    units = {f'tests/test_{i}.py': 10 + i for i in range(40)} | {'site-pages': 12, 'demo': 20, 'rendered': 300}
    first = xdist_groups.shard_of(units, COUNT)
    assert first == xdist_groups.shard_of(dict(reversed(list(units.items()))), COUNT)     # the order of collection does not matter
    assert set(first) == set(units) and set(first.values()) == {1, 2, 3}
    cost = [sum(xdist_groups.SHARD_COST.get(k, xdist_groups.COST_PER_TEST * n) for k, n in units.items() if first[k] == shard) for shard in (1, 2, 3)]
    assert max(cost) < 1.5 * min(cost), cost


@pytest.mark.parametrize('text', ['', '3', '0/3', '4/3', 'a/b', '1/2/3'])
def test_a_bad_shard_is_refused(text):
    with pytest.raises(SystemExit):
        xdist_groups.parse_shard(text)


REPORT = """
import json, sys
import pytest
from tests.xdist_groups import unit_key

class Report:
    seen = {}

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        self.seen = {item.nodeid.split('@')[0]: unit_key(item) for item in items}

report = Report()
code = pytest.main(['--collect-only', '-q', '-p', 'no:cacheprovider', 'tests/', *sys.argv[2:]], plugins=[report])
json.dump(report.seen, open(sys.argv[1], 'w'))
sys.exit(int(code))
"""


def collected(tmp_path, name, *args):
    """{node id: unit key} of the tests a collection holds, from a child pytest (a collection inside this one would share its plugins)."""
    out = tmp_path / f'{name}.json'
    run = subprocess.run([sys.executable, '-c', REPORT, str(out), *args], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-1500:] + run.stderr[-1500:]
    return json.loads(out.read_text())


def test_the_shards_together_hold_every_test_once_and_keep_each_unit_whole(tmp_path):
    everything = collected(tmp_path, 'all')
    shards = [collected(tmp_path, f's{number}', '--shard', f'{number}/{COUNT}') for number in range(1, COUNT + 1)]
    flat = [test for shard in shards for test in shard]
    assert len(flat) == len(set(flat)) == len(everything) and set(flat) == set(everything)
    assert all(shards), [len(shard) for shard in shards]
    homes = {}
    for number, shard in enumerate(shards):
        for unit in shard.values():
            homes.setdefault(unit, set()).add(number)
    assert [unit for unit, where in homes.items() if len(where) > 1] == []             # a group, or a file in no group, is never split
    assert {'site-pages', 'demo', 'rendered'} <= set(homes)
