"""The bench's outputs do not change (perf/whole-repo): the API v2 responses, the MCP tool outputs and the HTML of the main pages, on the
bench store at a small scale, hash to `tests/bench_reference.json`. The reference was taken from the code before any speed-up, so a
speed-up that changes any byte of an output fails here. Rebuild it only for an intended change of output:

    BW_BENCH_CACHE=$(mktemp -d) python scripts/bench.py --scale 0.05 --hashes > tests/bench_reference.json
"""
import json
from pathlib import Path

import pytest

from scripts import bench

REFERENCE = json.loads((Path(__file__).parent / 'bench_reference.json').read_text())
SCALE = 0.05


@pytest.fixture(scope='module')
def store(tmp_path_factory):
    folder = tmp_path_factory.mktemp('bench')
    ids = bench.build(folder, SCALE)
    return folder, ids


def test_every_output_is_the_one_before_the_speed_ups(store):
    folder, ids = store
    found = bench.hashes(folder, ids)
    assert set(found) == set(REFERENCE)
    assert {name for name in found if found[name] != REFERENCE[name]} == set()


def test_the_check_catches_a_changed_output(store, monkeypatch):
    """A deliberate breakage, one verdict lost, shows in the wishlist page, the wish list API and the MCP tool that reads it."""
    from brickwork.core import planning
    monkeypatch.setattr(planning, 'max_comparison', lambda row, rates=None, price=None, **kw: (None, None))
    folder, ids = store
    found = bench.hashes(folder, ids)
    changed = {name for name in found if found[name] != REFERENCE[name]}
    assert {'web planning wishlist', 'api wishes', 'mcp list_wishes'} <= changed
