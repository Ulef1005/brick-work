"""Makes `pytest -n auto --dist loadgroup` keep the tests of one `xdist_group` on one worker (#254, ADR 0024).

pytest-xdist 3.8.0 tags a grouped test by assigning its group to `item._nodeid`; pytest 9.2 builds `item.nodeid` from `item._id` and no longer reads
`_nodeid`, so with that pair the groups were silently ignored and the Chrome tests ran beside each other. This hook does the same through `_id`.
It does nothing when the group is already in the node id (a pytest or xdist where the original works), so it is safe to keep.
`tests/test_xdist_groups.py` fails if a future combination loses the grouping again."""
from _pytest.nodeid import coerce_node_id


def pytest_collection_modifyitems(config, items):
    if not getattr(config.option, 'loadgroup', False):     # set on the workers by pytest-xdist when `--dist loadgroup` is given
        return
    for item in items:
        names = {str(m.args[0] if m.args else m.kwargs.get('name', 'default')) for m in item.iter_markers('xdist_group')}
        if names and '@' not in item.nodeid.rsplit(']', 1)[-1]:
            item._id = coerce_node_id(f'{item.nodeid}@{"_".join(sorted(names))}')
