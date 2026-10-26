"""Activation: a catalogue build becomes the collection's (design 6.1 step 3)."""
import json

from .audit import Events, need_catalogue, transaction
from .connect import check_compatible, now
from .identity import held_colour_keys, project_color

HIGH_WATER = (('catalogue_item_high_water', 'item_high_water'), ('catalogue_color_high_water', 'color_high_water'))


def activate(db, *, via='cli', actor=None):
    """Record the attached catalogue's builds, bind its id, copy the high-water marks and project every catalogue colour
    with its links, in one transaction. Idempotent: a build that is active already changes nothing and writes no event.

    Returns {builds, bound, colours, colour_links, item_high_water, color_high_water}."""
    need_catalogue(db, 'activation')
    with transaction(db, 'activation'):
        report, changed = apply_activation(db)
        if changed:
            newest = db.execute('SELECT max(id) FROM catalogue.build').fetchone()[0]
            Events(db, via, actor).write('catalogue_build', newest, 'activated', None, json.dumps(report, sort_keys=True))
    return report


def apply_activation(db):
    """The writes of `activate`, inside the caller's open transaction and without the event (the 3.3 migration runs them
    inside its own single transaction and writes its one migration event instead). Returns (report, changed)."""
    cat = dict(db.execute('SELECT key, value FROM catalogue.meta').fetchall())
    coll = dict(db.execute('SELECT key, value FROM main.meta').fetchall())
    bound = coll.get('catalogue_id')
    check_compatible(db)
    have = {r[0] for r in db.execute('SELECT id FROM main.catalogue_build')}
    new = [r for r in db.execute('SELECT id, kind, mapping_version, counts_json FROM catalogue.build ORDER BY id') if r['id'] not in have]
    stamp = now()
    db.executemany("INSERT INTO main.catalogue_build(id, kind, mapping_version, activated_at, reconciled_at, counts_json) VALUES(?, ?, ?, ?, NULL, ?)",
                   [(r['id'], r['kind'], r['mapping_version'], stamp, r['counts_json']) for r in new])
    binding = bound is None
    if binding:
        db.execute("INSERT INTO main.meta(key, value) VALUES('catalogue_id', ?)", (cat['catalogue_id'],))
    marks = {}
    for mine, theirs in HIGH_WATER:
        marks[mine] = max(int(coll.get(mine) or 0), int(cat.get(theirs) or 0))
        if coll.get(mine) != str(marks[mine]):
            db.execute('INSERT OR REPLACE INTO main.meta(key, value) VALUES(?, ?)', (mine, str(marks[mine])))
    before = (db.execute('SELECT count(*) FROM main.color').fetchone()[0], db.execute('SELECT count(*) FROM main.color_link').fetchone()[0])
    held = held_colour_keys(db)                          # protection comes from before this activation, not from colours it projects itself
    for (color_id,) in db.execute('SELECT id FROM catalogue.color ORDER BY id').fetchall():
        project_color(db, color_id, held)
    after = (db.execute('SELECT count(*) FROM main.color').fetchone()[0], db.execute('SELECT count(*) FROM main.color_link').fetchone()[0])
    report = dict(builds=[r['id'] for r in new], bound=binding, colours=after[0] - before[0], colour_links=after[1] - before[1],
                  item_high_water=marks['catalogue_item_high_water'], color_high_water=marks['catalogue_color_high_water'])
    changed = bool(new) or binding or report['colours'] or report['colour_links'] or any(
        coll.get(mine) != str(marks[mine]) for mine, _ in HIGH_WATER)
    return report, changed
