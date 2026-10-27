"""The invented collection of M.10 batch A (issue #112): part list screens on a set with three Rebrickable versions, a BrickLink list,
copies in every state the copy page and the Switch sheet show. Shared by `tests/test_m10_a.py` and the frame script
`design/approval/112-m10-a/build_frames.py`. Dump rows marked `syn` are invented; the fixture catalogue is `tests/app4.py`'s."""
from brickwork.store4 import copies, fetched, identity
from tests.app4 import RICH, make_pair

# 1000-1 "Syn Castle Keep": three versions. v1 3001 red 4, 3023 white 2 (+ a red spare); v2 adds 3001 white 2 and a third white 3023;
# v3 drops 3023 white, takes 3001 red to 3 and adds a Duplo brick; the figure's quantity goes 2, 2, 1. 1000-2 has one version.
EXTRA_DUMP = {
    **RICH,
    'inventories': [*RICH['inventories'], [9003, 2, '1000-1'], [9004, 3, '1000-1']],
    'inventory_parts': [*RICH['inventory_parts'],
                        [9003, '3001', 4, 4, 'False', ''], [9003, '3023', 15, 3, 'False', ''], [9003, '3001', 15, 2, 'False', ''], [9003, '3023', 4, 1, 'True', ''],
                        [9004, '3001', 4, 3, 'False', ''], [9004, '3001', 15, 2, 'False', ''], [9004, '2071pr0001', 14, 1, 'False', '']],
    'inventory_minifigs': [*RICH['inventory_minifigs'], [9003, 'fig-000004', 2], [9004, 'fig-000004', 1]],
}


def make_a_pair(tmp_path):
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA_DUMP)


class World:
    def __init__(self, **ids):
        self.__dict__.update(ids)


def fetch_bricklink(coll, set_item, parts, figures=()):
    """Store a BrickLink list as the adapters do: its items and colours projected first. `parts` are (item, colour, spare, quantity)."""
    db = coll.db
    with db:
        for i in [set_item, *(p[0] for p in parts), *(f[0] for f in figures)]:
            identity.project(db, i)
        for c in {p[1] for p in parts}:
            identity.project_color(db, c)
        return fetched.write_fetched(db, set_item, 'bricklink', parts, figures)


def build_world(coll, *, bricklink=True):
    """Copies by role. `bricklink`: a fetched BrickLink list exists for 1000-1 (and the BrickLink key is the caller's to set)."""
    keep, gate = coll.item('sets', '1000-1'), coll.item('sets', '1000-2')
    brick, plate, duplo_brick = coll.item('parts', '3001'), coll.item('parts', '3023'), coll.item('parts', '2071pr0001')
    figure = coll.item('minifigs', 'fig-000004')
    red, white, yellow = coll.colour('4'), coll.colour('15'), coll.colour('14')
    wizard = coll.local('minifigure', 'Syn Wizard', born_key='syn001')              # a BrickLink-only figure: no Rebrickable list (design 4.5)
    if bricklink:
        fetch_bricklink(coll, keep, [(brick, red, 0, 4), (plate, white, 0, 3), (duplo_brick, yellow, 0, 1)], [(figure, 1), (wizard, 1)])
    v = lambda n: {'source': 'rebrickable', 'version': n}                          # noqa: E731
    # A: on version 2 of 3 with marks: what the Switch sheet says will not carry over to version 3.
    copy_a = coll.add_copy('1000-1', choice=v(2), condition='used', completeness='incomplete')
    coll.mark(copy_a, '3001', '4', missing=4)
    coll.mark(copy_a, '3023', '15', missing=1, checked=1)
    coll.mark(copy_a, '3001', '15', damaged=1)
    coll.mark_figure(copy_a, 'fig-000004', missing=2)
    # B: on BrickLink's list (a figure with no Rebrickable list among its lines).
    copy_b = coll.add_copy('1000-1', choice={'source': 'bricklink'}, condition='new', completeness='sealed') if bricklink else None
    # C: the same as A, switched through the page by the frames.
    copy_c = coll.add_copy('1000-1', choice=v(2), condition='used', completeness='incomplete')
    coll.mark(copy_c, '3001', '4', missing=4)
    coll.mark(copy_c, '3023', '15', missing=1, checked=1)
    # F: switched from version 1 to version 3: lines with marks were retired and are kept.
    copy_f = coll.add_copy('1000-1', choice=v(1), condition='used', completeness='incomplete')
    coll.mark(copy_f, '3023', '15', missing=1, checked=1)
    coll.mark(copy_f, '3001', '4', missing=3)
    coll.mark_figure(copy_f, 'fig-000004', missing=1)
    copies.switch_part_list(coll.db, copy_f, v(3), via='cli')
    # E: built from version 3 before a re-download changed it (the copy's digest and its figure line's digest no longer match).
    copy_e = coll.add_copy('1000-1', choice=v(3), condition='used')
    coll.sql("UPDATE copy SET inventory_digest='digest-before-the-re-download' WHERE id=?", (copy_e,))
    coll.sql("UPDATE copy_figure SET inventory_digest='figure-digest-before' WHERE copy_id=?", (copy_e,))
    coll.sql("UPDATE copy_part SET quantity=1 WHERE copy_id=? AND copy_figure_id IS NULL AND item_id=? AND color_id=?", (copy_e, brick, white))
    coll.sql("UPDATE copy_part SET quantity=quantity+1 WHERE id=(SELECT min(id) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL)", (copy_e,))
    # D: BrickLink's list wanted for set 1000-2, nothing fetched: pending, its job waiting for today's budget.
    copy_d = coll.add_copy('1000-2', choice={'source': 'bricklink'}, condition='used') if bricklink else None
    if copy_d:
        coll.sql("UPDATE job SET state='waiting_for_budget', error_code='budget', retry_at='2026-10-28T00:00:00.000Z' WHERE id=(SELECT pending_job_id FROM copy WHERE id=?)", (copy_d,))
    return World(keep=keep, gate=gate, brick=brick, plate=plate, figure=figure, red=red, white=white, yellow=yellow, wizard=wizard,
                 copy_a=copy_a, copy_b=copy_b, copy_c=copy_c, copy_d=copy_d, copy_e=copy_e, copy_f=copy_f)
