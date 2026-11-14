"""Makes `pytest -n auto --dist loadgroup` keep the tests of one `xdist_group` on one worker (#254, ADR 0024).

pytest-xdist 3.8.0 tags a grouped test by assigning its group to `item._nodeid`; pytest 9.2 builds `item.nodeid` from `item._id` and no longer reads
`_nodeid`, so with that pair the groups were silently ignored and the Chrome tests ran beside each other. This hook does the same through `_id`.
It does nothing when the group is already in the node id (a pytest or xdist where the original works), so it is safe to keep.
`tests/test_xdist_groups.py` fails if a future combination loses the grouping again."""
import os

from _pytest.nodeid import coerce_node_id

# --shard I/N (scripts/check.sh runs the suite as N parallel CI jobs, #364 item 1): a shard keeps whole units, so every xdist group stays on one
# job (the Chrome tests and the site and demo builds share a folder or a lock) and every test file that is in no group stays whole too. Units are
# dealt largest first to the lightest shard. A unit costs SHARD_COST[its key] seconds when listed (the site and demo builds, measured 2026-11-14
# on an 8-core machine), else COST_PER_TEST seconds a test. The cost only balances the shards; nothing depends on it being right.
COST_PER_TEST = 0.3
SHARD_COST = {'site-pages': 200.0, 'demo': 150.0, 'rendered': 90.0, 'tests/test_docs_drift.py': 70.0}
CHROME_OFF_COST = {'rendered': 5.0}   # BW_NO_CHROME=1 (a pull request): the Chrome tests skip at once


def pytest_addoption(parser):
    parser.addoption('--shard', default='', metavar='I/N', help='run only the I-th of N balanced shards of the collected tests (I from 1)')


def shard_of(units, count):
    """{unit key: shard number from 1} for `units` ({key: number of tests}) dealt over `count` shards, deterministic."""
    known = {**SHARD_COST, **(CHROME_OFF_COST if os.environ.get('BW_NO_CHROME') == '1' else {})}
    cost = {key: known.get(key, COST_PER_TEST * tests) for key, tests in units.items()}
    load = [0.0] * count
    placed = {}
    for key in sorted(units, key=lambda k: (-cost[k], k)):
        lightest = min(range(count), key=lambda i: (load[i], i))
        load[lightest] += cost[key]
        placed[key] = lightest + 1
    return placed


def unit_key(item):
    names = sorted({str(m.args[0] if m.args else m.kwargs.get('name', 'default')) for m in item.iter_markers('xdist_group')})
    return '_'.join(names) if names else item.nodeid.split('::', 1)[0]


def parse_shard(text):
    try:
        number, count = (int(part) for part in text.split('/'))
    except ValueError:
        raise SystemExit(f'--shard must look like 2/3, not {text!r}')
    if not 1 <= number <= count:
        raise SystemExit(f'--shard {text}: the shard number runs from 1 to {count}')
    return number, count


def select_shard(config, items):
    """Keep this shard's tests in `items`; report the rest as deselected. A shard with no test is an error: it would pass without checking anything."""
    number, count = parse_shard(config.getoption('--shard'))
    units = {}
    for item in items:
        key = unit_key(item)
        units[key] = units.get(key, 0) + 1
    placed = shard_of(units, count)
    kept = [item for item in items if placed[unit_key(item)] == number]
    if not kept:
        raise SystemExit(f'--shard {number}/{count} holds no test')
    dropped = [item for item in items if placed[unit_key(item)] != number]
    config.hook.pytest_deselected(items=dropped)
    items[:] = kept


def pytest_collection_modifyitems(config, items):
    if config.getoption('--shard'):
        select_shard(config, items)    # first: the group suffix that follows is added only to the tests that stay
    if not getattr(config.option, 'loadgroup', False):     # set on the workers by pytest-xdist when `--dist loadgroup` is given
        return
    for item in items:
        names = {str(m.args[0] if m.args else m.kwargs.get('name', 'default')) for m in item.iter_markers('xdist_group')}
        if names and '@' not in item.nodeid.rsplit(']', 1)[-1]:
            item._id = coerce_node_id(f'{item.nodeid}@{"_".join(sorted(names))}')
