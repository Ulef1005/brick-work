"""The migration mint (design 8.3, 8.8, 8.11; probes B2, B3, B5, B6 of design 12; issue #109 M.7a).

The catalogue is built at test time from real dump rows and shipped mapping rows (tests/regression/fixtures/catalogue/); rows named
`syn` are synthetic and added here for cases the real rows lack. B1 and B4 are covered by test_store4_identity.py.
The probe numbers follow design 12's table: B2 BrickLink colour 72 -> Pastel Blue, B3 the sticker sheets kept apart, B5 injective,
B6 BrickLink-space read-back equal. (Design 8.3 numbers some of them differently; the table is the one used.)"""
from contextlib import closing
import csv
import hashlib

import pytest

from brickwork.store4 import identity
from brickwork.store4.errors import CatalogueError
from brickwork.store4.mint import LOCAL_BASE, MintInvariantError, mint, write_report
from tests.store4_mint_fixtures import Store33, build_catalogue, colour_id, item_id, open_collection

SYN_DUMP = {
    'parts': [['syn-3023b', 'Synthetic Plate 1 x 2 variant', '14', 'Plastic']],
    'sets': [['syn-1', 'Synthetic set one', '2000', '663', '1', ''], ['syn-2', 'Synthetic set two', '2000', '663', '1', ''],
             ['syn-3', 'Synthetic set three', '2000', '663', '2', ''], ['syn-4', 'Synthetic set four', '2000', '663', '1', ''], ['syn-5', 'Synthetic set five', '2000', '663', '1', '']],
    'minifigs': [['fig-syn1', 'Synthetic figure', '1', '']],
    'inventories': [['9001', '1', 'syn-1'], ['9002', '1', 'fig-syn1'], ['9003', '1', 'syn-2'], ['9004', '1', 'syn-3'], ['9005', '1', 'syn-4'], ['9006', '1', 'syn-5']],
    'inventory_parts': [['9001', 'syn-3023b', '4', '1', 'False', ''], ['9002', 'syn-3023b', '4', '1', 'False', ''],
                        ['9004', '3023', '4', '1', 'False', ''], ['9004', 'syn-3023b', '4', '1', 'False', ''], ['9005', '3023', '4', '1', 'False', '']],
    'inventory_minifigs': [['9003', 'fig-syn1', '1'], ['9006', 'fig-000004', '1']],
}


def p(rb, key, colour=''):
    return [rb, colour, 'bricklink', 'P', key, 'matched', 'external_ids', '0']


SYN_PARTS = [p('3023', 'syn-amb'), p('syn-3023b', 'syn-amb'),            # one BrickLink number, two Rebrickable parts
             p('dupupn0123', 'syn-tel'), p('3001', 'syn-tel'),
             p('syn-3023b', 'syn-b'),
             p('3901', 'syn-comp'), p('3001', 'syn-comp')]               # two candidates, only 3901 is in fig-000004's list                                    # a second BrickLink number for syn-3023b alone           # a number whose other candidate is not in the set
SYN_LOCAL = [['fig-000004', '', 'bricklink', 'M', 'syn-fig-amb', 'matched', 'composition', '1'],
             ['fig-syn1', '', 'bricklink', 'M', 'syn-fig-amb', 'matched', 'composition', '1'],
             ['fig-syn1', '', 'bricklink', 'M', 'syn-fig-1', 'matched', 'composition', '1']]


@pytest.fixture
def world(tmp_path):
    cat = build_catalogue(tmp_path, extra_dump=SYN_DUMP, extra_parts=SYN_PARTS, extra_local=SYN_LOCAL)
    with closing(open_collection(tmp_path, cat)) as db:
        yield Store33(), db


def part(db, born):
    return item_id(db, 'parts', born)


# ---------- colours ----------

def test_colour_links_prefer_the_inverse_preferred_one(world):
    """B2: BrickLink 72 is shared by Maersk Blue and Pastel Blue; the one marked inverse_preferred (Pastel Blue) wins."""
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', '3001', 72)
    s.part(c, 'P', '3001', 77)
    s.part(c, 'P', '3001', 11)
    r = mint(s.db, db)
    assert r.colours[72].color_id == colour_id(db, '1051') != colour_id(db, '313')           # Pastel Blue, not Maersk Blue
    assert r.colours[72].rule == 'inverse_preferred' and len(r.colours[72].candidates) == 2
    assert r.colours[77].color_id == colour_id(db, '1103')                                   # Pearl Titanium over Pearl Dark Gray
    assert r.colours[11].rule == 'link' and r.colours[11].color_id == colour_id(db, '0')
    rows = {row[0]: row for row in r.colour_rows()[1]}
    assert rows[72][4] == 'inverse_preferred' and rows[77][4] == 'inverse_preferred'      # colours.csv lists 72 and 77


def test_unlinked_colours_become_local_and_null_becomes_colour_1(world):
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', '3001', 500)
    s.part(c, 'P', '3001', 501)
    s.part(c, 'P', '3001', None)
    s.part(c, 'P', '3023', 0)                                                                # BrickLink 0 links to "no colour"
    r = mint(s.db, db)
    assert r.colours[None].color_id == 1 and r.colours[None].rule == 'null'
    assert r.colours[0].color_id == 1 and r.colours[0].origin == 'catalogue'
    assert (r.colours[500].color_id, r.colours[501].color_id) == (LOCAL_BASE, LOCAL_BASE + 1)
    assert [(lc.bl_id, lc.name, lc.is_trans) for lc in r.local_colours] == [(500, 'Invented Trans Colour', 1), (501, 'Invented Solid', 0)]
    assert r.target('P', '3001', None).color_id == 1
    assert r.target('P', '3001', 500).color_id == LOCAL_BASE
    assert r.counts()['local colours'] == 2


# ---------- the item rules ----------

def test_rule_3_one_candidate_and_two_versions_of_a_set(world):
    s, db = world
    c = s.copy('2070-1')                                                                     # the set has two catalogue versions
    s.part(c, 'P', '3001', 5)
    s.wish('S', '2070-1')
    r = mint(s.db, db)
    d = r.items[('S', '2070-1', None)]
    assert (d.rule, d.item_id, d.origin) == (3, item_id(db, 'sets', '2070-1'), 'catalogue') and d.tables == ('copies', 'wishlist')
    assert d.rows == 2
    assert r.target('P', '3001', 5).item_id == part(db, '3001')
    assert r.items[('P', '3001', 5)].rule == 3 and r.items[('P', '3001', 5)].candidates == (part(db, '3001'),)


def test_rule_2_is_exhaustive_not_order_dependent(world):
    """A key with two catalogue candidates must stay ambiguous whichever the collection projected first (resolve_inverse's default
    would answer from one store and stop)."""
    s, db = world
    with pytest.raises(identity.AmbiguousIdentity):
        identity.resolve_inverse(db, 'P', 'syn-amb', '5', exhaustive=True)
    c = s.copy('9999-1')                                                                     # a set the catalogue lacks: no context
    s.part(c, 'P', 'syn-amb', 5)
    d = mint(s.db, db).items[('P', 'syn-amb', 5)]
    assert d.candidates == tuple(sorted((part(db, '3023'), part(db, 'syn-3023b')))) and d.rule == 4
    (o,) = d.holders.values()
    assert (o.rule, o.origin) == (5, 'local') and d.item_id is None


def test_leg_rule_candidates_are_scoped_to_the_minted_colour(world):
    """970c00 in Black is the black legs, in Red the red legs; in a colour nothing is scoped to there is no candidate (rule 5)."""
    s, db = world
    c = s.copy('2070-1')
    for colour in (11, 5, 1):
        s.part(c, 'P', '970c00', colour)
    r = mint(s.db, db)
    assert r.items[('P', '970c00', 11)].item_id == part(db, '970c03') and r.items[('P', '970c00', 11)].rule == 3
    assert r.items[('P', '970c00', 5)].item_id == part(db, '970c22')
    white = r.items[('P', '970c00', 1)]
    assert (white.rule, white.origin, white.candidates) == (5, 'local', ())


def test_rule_5_no_candidate_is_a_local_bricklink_born_item(world):
    """B4/B3 of design 8.3: a part nobody maps goes local with a matched/migration link."""
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', 'no-such-part', 5)
    s.db.execute("UPDATE items SET name='Invented part', year=1999 WHERE item_no='no-such-part'")
    r = mint(s.db, db)
    d = r.items[('P', 'no-such-part', 5)]
    assert (d.rule, d.origin, d.item_id) == (5, 'local', LOCAL_BASE)
    (item,) = r.local_items
    assert (item.local_id, item.kind, item.born_provider, item.born_namespace, item.born_key, item.name, item.year) == \
        (LOCAL_BASE, 'part', 'bricklink', 'P', 'no-such-part', 'Invented part', 1999)
    assert list(item.links.values())[0].__dict__ == dict(provider='bricklink', provider_kind='P', provider_key='no-such-part',
                                                         status='matched', method='migration', origin='migration', color_id=None)
    assert item.reasons == {'no_candidate'}


def test_rule_1_placeholders_take_their_kind_from_the_referencing_table(world):
    s, db = world
    c = s.copy('2070-1')
    s.part(c, '?', 'rebrickable:3001', 5)                                                    # copy_parts -> a part, in the catalogue
    s.figure(c, '?', 'rebrickable:fig-000004')                                               # copy_minifigs -> a figure, in the catalogue
    s.figure(c, '?', 'rebrickable:fig-999999')                                               # not in the catalogue
    s.part(c, '?', 'rebrickable:no-such', 5)
    s.copy('999999-1', item_type='?')
    s.db.execute("UPDATE copies SET set_no='rebrickable:999999-1' WHERE set_no='999999-1'")
    s.db.execute("UPDATE items SET item_no='rebrickable:999999-1' WHERE item_no='999999-1' AND item_type='?'")
    r = mint(s.db, db)
    part_hit = r.items[('?P', 'rebrickable:3001', 5)]
    fig_hit = r.items[('?M', 'rebrickable:fig-000004', None)]
    assert (part_hit.rule, part_hit.item_id, part_hit.kind) == (1, part(db, '3001'), 'part')
    assert (fig_hit.rule, fig_hit.item_id, fig_hit.kind) == (1, item_id(db, 'minifigs', 'fig-000004'), 'minifigure')
    fig_local = r.items[('?M', 'rebrickable:fig-999999', None)]
    part_local = r.items[('?P', 'rebrickable:no-such', 5)]
    set_local = r.items[('?S', 'rebrickable:999999-1', None)]
    assert [d.origin for d in (fig_local, part_local, set_local)] == ['local'] * 3
    by_id = {i.local_id: i for i in r.local_items}
    f, q, st = (by_id[d.item_id] for d in (fig_local, part_local, set_local))
    assert [(i.kind, i.born_provider, i.born_namespace, i.born_key) for i in (f, q, st)] == [
        ('minifigure', 'rebrickable', 'minifigs', 'fig-999999'), ('part', 'rebrickable', 'parts', 'no-such'),
        ('set', 'rebrickable', 'sets', '999999-1')]
    assert all(i.provider_status == {('bricklink', 'to_check', 'migration')} for i in (f, q, st))
    assert r.target('?', 'rebrickable:3001', 5, kind='part').item_id == part(db, '3001')
    assert r.counts()['placeholders resolved'] == 2 and r.counts()['placeholders local'] == 3


S1, S2, S3, S4, V1 = ('S', 'syn-1', None), ('S', 'syn-2', None), ('S', 'syn-3', None), ('S', 'syn-4', None), ('S', '2070-1', None)


def test_rule_4_is_decided_per_holder(world):
    """One BrickLink number, two sets whose lists each hold a different candidate: two targets, one per holder."""
    s, db = world
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)                                               # syn-1 holds syn-3023b only
    s.part(s.copy('syn-4'), 'P', 'syn-amb', 5)                                               # syn-4 holds 3023 only
    r = mint(s.db, db)
    d = r.items[('P', 'syn-amb', 5)]
    assert d.rule == 4 and d.item_id is None and not r.local_items                           # no row lands on the local item: none exists
    assert (d.holders[S1].rule, d.holders[S1].item_id) == (4, part(db, 'syn-3023b'))
    assert (d.holders[S4].rule, d.holders[S4].item_id) == (4, part(db, '3023'))
    assert r.target('P', 'syn-amb', 5, holder=S1).item_id != r.target('P', 'syn-amb', 5, holder=S4).item_id
    assert r.counts()['rule 4 holders resolved'] == 2 and r.counts()['rule 4 keys, every holder resolved'] == 1
    with pytest.raises(LookupError):
        r.target('P', 'syn-amb', 5)                                                          # every row has a holder: it must be named
    with pytest.raises(LookupError):
        r.target('P', 'syn-amb', 5, holder=S2)


def test_rule_4_a_holder_with_both_candidates_goes_local(world):
    s, db = world
    s.part(s.copy('syn-3'), 'P', 'syn-amb', 4)                                               # syn-3 holds both
    r = mint(s.db, db)
    d = r.items[('P', 'syn-amb', 4)]
    o = d.holders[S3]
    assert (o.rule, o.origin) == (5, 'local') and 'in the context' in o.note
    (item,) = r.local_items
    assert (item.reasons, item.local_id) == ({'ambiguous'}, o.item_id)
    assert {(l.provider, l.provider_kind, l.provider_key, l.status, l.method) for l in item.links.values()} == {
        ('bricklink', 'P', 'syn-amb', 'matched', 'migration'),
        ('rebrickable', 'parts', '3023', 'to_check', 'migration_candidate'), ('rebrickable', 'parts', 'syn-3023b', 'to_check', 'migration_candidate')}


def test_rule_4_a_mixed_key_only_the_tied_holders_rows_land_on_the_local_item(world):
    s, db = world
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)                                               # resolves
    s.part(s.copy('syn-3'), 'P', 'syn-amb', 5)                                               # ties
    s.part(s.copy('syn-3'), 'P', 'syn-amb', 5)
    r = mint(s.db, db)
    d = r.items[('P', 'syn-amb', 5)]
    assert (d.holders[S1].rule, d.holders[S3].rule, d.holders[S3].rows) == (4, 5, 2)
    (item,) = r.local_items
    assert d.holders[S3].item_id == item.local_id != d.holders[S1].item_id == part(db, 'syn-3023b')
    assert r.counts()['rule 4 keys, some holders resolved'] == 1 and r.counts()['rule 4 holders tied'] == 1


def test_rule_4_a_context_free_row_of_a_tied_key_takes_the_local_item(world):
    s, db = world
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)
    s.wish('P', 'syn-amb', 5)                                                                # no holder
    s.stock('P', 'syn-amb', 5)
    r = mint(s.db, db)
    d = r.items[('P', 'syn-amb', 5)]
    (item,) = r.local_items
    assert (d.free_rows, d.item_id, d.origin) == (2, item.local_id, 'local')
    assert r.target('P', 'syn-amb', 5).item_id == item.local_id                              # the key-level answer
    assert r.target('P', 'syn-amb', 5, holder=S1).item_id == part(db, 'syn-3023b')


def test_rule_4_the_context_is_the_sets_inventories_of_any_version(world):
    s, db = world
    s.part(s.copy('2070-1'), 'P', 'syn-tel', 5)                                              # dupupn0123 is in version 1 of 2070-1 only
    r = mint(s.db, db)
    o = r.items[('P', 'syn-tel', 5)].holders[V1]
    assert (o.rule, o.item_id) == (4, part(db, 'dupupn0123'))


def test_rule_4_all_copies_of_a_set_share_the_context(world):
    s, db = world
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)
    o = mint(s.db, db).items[('P', 'syn-amb', 5)].holders
    assert list(o) == [S1] and o[S1].rows == 2


def test_rule_4_the_context_of_a_loose_figure_part_is_the_figures_list(world):
    s, db = world
    s.part(s.copy('2070-1'), 'P', 'syn-amb', 5)                                              # a tied holder elsewhere
    stock = s.stock('M', 'syn-fig-1')                                                        # -> fig-syn1, whose list holds syn-3023b
    s.stock_part(stock, 'P', 'syn-amb', 5)
    r = mint(s.db, db)
    d = r.items[('P', 'syn-amb', 5)]
    fig = ('M', 'syn-fig-1', None)
    assert (d.holders[fig].rule, d.holders[fig].item_id) == (4, part(db, 'syn-3023b'))
    assert d.holders[V1].rule == 5 and r.items[fig].rule == 3


def test_a_loose_figure_part_with_no_candidate_in_the_figures_list_goes_local(world):
    s, db = world
    s.stock_part(s.stock('M', 'syn-fig-0004'), 'P', 'syn-amb', 5)                            # fig-000004's list holds neither candidate
    (o,) = mint(s.db, db).items[('P', 'syn-amb', 5)].holders.values()
    assert (o.rule, o.origin) == (5, 'local')


def test_a_figure_part_without_a_resolved_figure_has_no_context(world):
    s, db = world
    s.stock_part(s.stock('M', 'syn-fig-amb'), 'P', 'syn-amb', 5)                             # the figure is ambiguous itself
    r = mint(s.db, db)
    assert r.items[('M', 'syn-fig-amb', None)].rule == 4 and r.items[('M', 'syn-fig-amb', None)].item_id is not None   # its loose row is local
    (o,) = r.items[('P', 'syn-amb', 5)].holders.values()
    assert o.rule == 5


def test_rule_4_for_figures_uses_the_sets_figure_lines(world):
    s, db = world
    c = s.copy('syn-2')                                                                      # syn-2's inventory holds fig-syn1
    s.figure(c, 'M', 'syn-fig-amb')
    o = mint(s.db, db).items[('M', 'syn-fig-amb', None)].holders[S2]
    assert (o.rule, o.item_id) == (4, item_id(db, 'minifigs', 'fig-syn1'))


def test_injectivity_runs_across_holders(world):
    """syn-amb under syn-1 and syn-b both mean syn-3023b: different keys, one target, so one loses - under that holder only."""
    s, db = world
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)
    s.part(s.copy('syn-4'), 'P', 'syn-amb', 5)                                               # -> 3023: no clash
    for _ in range(2):
        s.part(s.copy('2070-1'), 'P', 'syn-b', 5)                                            # -> syn-3023b, more rows
    r = mint(s.db, db)
    (col,) = r.collisions
    assert (col.loser, col.keeper, col.reason, col.holders) == (('P', 'syn-amb', 5), ('P', 'syn-b', 5), 'most_rows', (S1,))
    d = r.items[('P', 'syn-amb', 5)]
    assert d.holders[S1].collision == 'loser' and d.holders[S1].origin == 'local'
    assert (d.holders[S4].collision, d.holders[S4].item_id) == (None, part(db, '3023'))      # the other holder is untouched
    assert r.items[('P', 'syn-b', 5)].collision == 'keeper'
    (item,) = r.local_items
    assert item.reasons == {'collision'} and col.loser_local_id == item.local_id == d.holders[S1].item_id


def test_one_key_on_several_items_is_not_a_collision(world):
    s, db = world
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)
    s.part(s.copy('syn-4'), 'P', 'syn-amb', 5)
    assert not mint(s.db, db).collisions


def test_a_placeholder_of_the_wrong_kind_is_an_unidentified_local_item(world):
    """The catalogue holds the zero-part set 10018247-1 as `gear`; a `?` copy of it needs a set. The born key belongs to the catalogue
    item (the unique item_born index would refuse a second), so the local item has none and links to the catalogue item."""
    s, db = world
    s.copy('rebrickable:10018247-1', item_type='?')
    r = mint(s.db, db)
    d = r.items[('?S', 'rebrickable:10018247-1', None)]
    assert (d.rule, d.origin) == (1, 'local') and 'is a gear' in d.note
    (item,) = r.local_items
    assert (item.kind, item.born_provider, item.born_namespace, item.born_key, item.reasons) == ('set', None, None, None, {'wrong_kind'})
    assert [(l.provider, l.provider_kind, l.provider_key, l.status, l.method) for l in item.links.values()] == [
        ('rebrickable', 'sets', '10018247-1', 'to_check', 'migration_wrong_kind')]
    assert item.provider_status == {('bricklink', 'to_check', 'migration')}


def test_the_plan_never_has_a_local_item_whose_born_key_exists(world):
    s, db = world
    s.part(s.copy('2070-1'), 'P', 'no-such', 5)
    db.execute("INSERT INTO main.item(id, origin, kind, kind_source, name, born_provider, born_namespace, born_key, created_at, updated_at) "
               "VALUES(1000000050, 'local', 'part', 'namespace', 'x', 'bricklink', 'P', 'no-such', 'now', 'now')")
    with pytest.raises(MintInvariantError, match='already has'):
        mint(s.db, db)


def test_losers_of_one_number_in_two_colours_that_share_a_target_are_reported(world):
    """BrickLink colour 0 and NULL both mean colour 1: the two 311.1stk01 losers land on one local item and colour. The mint
    cannot tell them apart without merging two 3.3 keys, so it reports them instead."""
    s, db = world
    c = s.copy('2070-1')
    for _ in range(3):
        s.part(s.copy('2070-1'), 'P', '310.3stk01', None)
    s.part(c, 'P', '311.1stk01', None)
    s.part(c, 'P', '311.1stk01', 0)
    r = mint(s.db, db)
    assert r.unresolved == [(('P', '311.1stk01', None), ('P', '311.1stk01', 0))]
    assert r.check_injective() == []
    r.unresolved.clear()                                                                     # the check itself sees the shared target
    assert r.check_injective() == [(('P', '311.1stk01', None), ('P', '311.1stk01', 0))]


def test_a_part_of_a_figure_in_a_copy_uses_the_figure_the_set_resolved_to(world):
    """The figure has two candidates; syn-5 holds fig-000004, so the figure is that one under syn-5. The part's context is fig-000004's
    list: of its two candidates only 3901 is in it, so the part resolves (rule 4) instead of going local."""
    s, db = world
    c = s.copy('syn-5')
    s.figure(c, 'M', 'syn-fig-amb')
    fig, st = ('M', 'syn-fig-amb', None), ('S', 'syn-5', None)
    s.part(c, 'P', 'syn-comp', 5, parent=('M', 'syn-fig-amb'))
    r = mint(s.db, db)
    assert r.items[fig].holders[st].item_id == item_id(db, 'minifigs', 'fig-000004')
    d = r.items[('P', 'syn-comp', 5)]
    assert list(d.holders) == [(fig, st)]
    assert (d.holders[(fig, st)].rule, d.holders[(fig, st)].item_id) == (4, part(db, '3901'))
    assert r.target('P', 'syn-comp', 5, holder=(fig, st)).item_id == part(db, '3901')
    assert any('@' in row[3] for row in r.mint_rows()[1])                                     # the pair is labelled in mint.csv


def test_g_b_c_i_use_the_set_number_only_where_the_theme_kind_agrees(world):
    s, db = world
    for t in 'GBCIS':
        s.wish(t, '10018247-1')                                                              # a zero-part set the theme table made `gear`
    r = mint(s.db, db)
    gear = r.items[('G', '10018247-1', None)]
    assert (gear.rule, gear.item_id) == (3, item_id(db, 'sets', '10018247-1')) and gear.kind == 'gear'
    for t in 'BCIS':                                                                         # book, catalog, instructions, set: kind differs
        d = r.items[(t, '10018247-1', None)]
        assert (d.rule, d.origin, d.candidates) == (5, 'local', ()), t


# ---------- figures: with and without the composition file ----------

def test_figures_through_the_composition_links(world):
    s, db = world
    s.wish('M', 'syn-fig-0004')
    r = mint(s.db, db)
    d = r.items[('M', 'syn-fig-0004', None)]
    assert (d.rule, d.item_id) == (3, item_id(db, 'minifigs', 'fig-000004'))
    assert r.composition_file and 'with the figure composition file' in r.case


def test_without_the_composition_file_every_figure_is_local(tmp_path):
    cat = build_catalogue(tmp_path, composition=False)
    with closing(open_collection(tmp_path, cat)) as db:
        s = Store33()
        s.wish('M', 'syn-fig-0004')
        s.wish('M', 'twn381')
        r = mint(s.db, db)
    assert not r.composition_file and 'without the figure composition file' in r.case
    assert [(d.rule, d.origin) for k, d in sorted(r.items.items())] == [(5, 'local'), (5, 'local')]
    assert {i.born_namespace for i in r.local_items} == {'M'} and r.counts()['rule 5'] == 2


# ---------- injectivity ----------

def sticker_copy(s, n310=1, n311=1, n312=0):
    c = s.copy('2070-1')
    for key, n in (('310.3stk01', n310), ('311.1stk01', n311), ('312.3stk01', n312)):
        for _ in range(n):
            s.part(c, 'P', key, None)                                                       # note: one key, several rows is one group count
    return c


def test_b3_the_sticker_sheets_are_kept_apart(world):
    """310.3stk01 keeps 003402; 311.1stk01 becomes local with a to_check collision link; nothing is summed."""
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', '310.3stk01', None)
    s.part(c, 'P', '311.1stk01', None)
    r = mint(s.db, db)
    sheet = item_id(db, 'parts', '003402')
    keeper, loser = r.items[('P', '310.3stk01', None)], r.items[('P', '311.1stk01', None)]
    assert (keeper.item_id, keeper.collision) == (sheet, 'keeper')
    assert (loser.collision, loser.origin, loser.rule) == ('loser', 'local', 3) and loser.item_id >= LOCAL_BASE
    (col,) = r.collisions
    assert (col.loser, col.keeper, col.shared_item_id, col.reason, col.loser_local_id) == (
        ('P', '311.1stk01', None), ('P', '310.3stk01', None), sheet, 'lowest_number', loser.item_id)
    item = next(i for i in r.local_items if i.local_id == loser.item_id)
    assert item.reasons == {'collision'} and (item.born_provider, item.born_namespace, item.born_key) == ('bricklink', 'P', '311.1stk01')
    assert {(l.provider, l.provider_kind, l.provider_key, l.status, l.method) for l in item.links.values()} == {
        ('bricklink', 'P', '311.1stk01', 'matched', 'migration'), ('rebrickable', 'parts', '003402', 'to_check', 'migration_collision')}


def test_injectivity_tie_break_most_rows(world):
    s, db = world
    c = sticker_copy(s)
    s.part(c, 'P', '311.1stk01', 1)                                                         # a coloured row is another group; the null rows decide
    c2 = s.copy('2070-1')
    s.part(c2, 'P', '311.1stk01', None)
    s.part(s.copy('2070-1'), 'P', '311.1stk01', None)
    r = mint(s.db, db)
    sheet = item_id(db, 'parts', '003402')
    assert r.items[('P', '311.1stk01', None)].collision == 'keeper' and r.items[('P', '311.1stk01', None)].rows == 3
    assert r.items[('P', '310.3stk01', None)].collision == 'loser'
    assert [c.reason for c in r.collisions] == ['most_rows'] and r.collisions[0].shared_item_id == sheet


def test_injectivity_tie_break_preferred_link(tmp_path):
    """The key that is the item's preferred link in the colour keeps the item, even with fewer rows."""
    local = [['003402', '', 'bricklink', 'P', k, 'matched', 'external_ids', '1' if k == '312.3stk01' else '0']
             for k in ('310.3stk01', '311.1stk01', '312.3stk01')]
    cat = build_catalogue(tmp_path, local_parts=local)
    with closing(open_collection(tmp_path, cat)) as db:
        s = Store33()
        c = s.copy('2070-1')
        for key, n in (('310.3stk01', 3), ('311.1stk01', 2), ('312.3stk01', 1)):
            for _ in range(n):
                s.part(s.copy('2070-1'), 'P', key, None)
        s.part(c, 'P', '312.3stk01', None)
        r = mint(s.db, db)
    assert r.items[('P', '312.3stk01', None)].collision == 'keeper'
    assert sorted(c.loser[1] for c in r.collisions) == ['310.3stk01', '311.1stk01'] and {c.reason for c in r.collisions} == {'preferred_link'}


def test_a_placeholder_collides_with_its_bricklink_key(world):
    """`?` 3001 and BrickLink 3001 in Red are the same 4.0 target: the key with more rows keeps it, the other goes local."""
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', '3001', 5)
    s.part(c, '?', 'rebrickable:3001', 5)
    r = mint(s.db, db)
    assert r.items[('P', '3001', 5)].collision == 'keeper'                                   # tie on rows: the BrickLink number sorts first
    loser = r.items[('?P', 'rebrickable:3001', 5)]
    assert loser.collision == 'loser'
    item = next(i for i in r.local_items if i.local_id == loser.item_id)
    assert item.born_provider is None and item.reasons == {'collision'}                       # unidentified: it has no BrickLink number
    s.part(c, '?', 'rebrickable:3001', 5)                                                    # a second row does not change the group count
    s.part(s.copy('2070-1'), '?', 'rebrickable:3001', 5)
    r = mint(s.db, db)
    assert r.items[('?P', 'rebrickable:3001', 5)].collision == 'keeper' and r.items[('P', '3001', 5)].collision == 'loser'
    item = next(i for i in r.local_items if i.local_id == r.items[('P', '3001', 5)].item_id)
    assert (item.born_provider, item.born_namespace, item.born_key) == ('bricklink', 'P', '3001')



def test_b5_the_mint_is_injective(world):
    """No two 3.3 keys share a 4.0 target, whatever the collisions were."""
    s, db = world
    c = s.copy('2070-1')
    for key in ('310.3stk01', '311.1stk01', '312.3stk01'):
        s.part(c, 'P', key, None)
        s.part(c, 'P', key, 1)
    s.part(c, 'P', '3001', 5)
    s.part(c, '?', 'rebrickable:3001', 5)
    s.part(c, 'P', 'syn-amb', 5)
    s.part(s.copy('syn-1'), 'P', 'syn-amb', 5)
    s.part(c, 'P', '970c00', 11)
    r = mint(s.db, db)
    targets = {}
    for key, d in r.items.items():
        for holder in ([*d.holders] + ([None] if d.item_id is not None else [])):
            t = r.target(key[0] if not key[0].startswith('?') else '?', key[1], key[2], kind={'S': 'set', 'M': 'minifigure', 'P': 'part'}.get(key[0][-1]),
                         holder=holder)
            colour = t.color_id if key[0] in ('P', '?P') else None
            assert targets.get((t.item_id, colour), key) == key, (key, targets.get((t.item_id, colour)))
            targets[(t.item_id, colour)] = key
    assert r.counts()['collisions'] == 5


def test_b6_read_back_in_bricklink_space_equals_the_3_3_keys(world):
    """The independent proof (design 8.7) inverts the mint table: every 4.0 (item, colour) maps back to the 3.3 key it came from, and
    eight lines of one copy insert under the 4.0 line key with no collision."""
    s, db = world
    c = s.copy('2070-1')
    lines = [('P', '310.3stk01', None), ('P', '311.1stk01', None), ('P', '312.3stk01', None), ('P', '3001', 5), ('P', '3023', 5),
             ('P', '970c00', 11), ('P', '970c00', 5), ('P', 'no-such', 5)]
    for item_type, number, colour in lines:
        s.part(c, item_type, number, colour)
    r = mint(s.db, db)
    inverse = {}
    for key in lines:
        t = r.target(*key)
        assert (t.item_id, t.color_id) not in inverse
        inverse[(t.item_id, t.color_id)] = key
    line_keys = {(r.target(*k).item_id, r.target(*k).color_id, 0) for k in lines}            # the 4.0 copy_part key: item, colour, spare
    assert len(line_keys) == 8
    assert [inverse[(r.target(*k).item_id, r.target(*k).color_id)] for k in lines] == lines


# ---------- the plan, the reports, and what the mint must not do ----------

def test_the_mint_writes_nothing_and_ids_are_deterministic(tmp_path):
    import sqlite3
    cat = build_catalogue(tmp_path, extra_dump=SYN_DUMP, extra_parts=SYN_PARTS)
    src_path = tmp_path / 'bw33.db'
    s = Store33()
    s.part(s.copy('2070-1'), 'P', 'no-such', 500)
    s.part(s.copy('2070-1'), 'P', '311.1stk01', None)
    s.part(s.copy('2070-1'), 'P', '310.3stk01', None)
    s.db.commit()
    with closing(sqlite3.connect(src_path)) as out:
        s.db.backup(out)
    digest = hashlib.sha256(src_path.read_bytes()).hexdigest()
    with closing(open_collection(tmp_path, cat)) as db:
        before = hashlib.sha256((tmp_path / 'brickwork-4.db').read_bytes()).hexdigest()
        changes = db.total_changes
        with closing(sqlite3.connect(f'file:{src_path}?mode=ro', uri=True)) as ro:
            first = mint(ro, db).report_files()
            second = mint(ro, db).report_files()
        assert db.total_changes == changes and db.execute('SELECT count(*) FROM main.item').fetchone()[0] == 0
    assert first == second
    assert hashlib.sha256(src_path.read_bytes()).hexdigest() == digest
    assert hashlib.sha256((tmp_path / 'brickwork-4.db').read_bytes()).hexdigest() == before


def test_local_ids_continue_after_the_collections_local_range(world):
    s, db = world
    s.part(s.copy('2070-1'), 'P', 'no-such', 500)
    db.execute("INSERT INTO main.item(id, origin, kind, kind_source, name, created_at, updated_at) "
               "VALUES(1000000007, 'local', 'part', 'namespace', 'x', 'now', 'now')")
    r = mint(s.db, db)
    assert [i.local_id for i in r.local_items] == [1000000008] and r.colours[500].color_id == LOCAL_BASE


def test_report_files(world, tmp_path):
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', '311.1stk01', None)
    s.part(c, 'P', '310.3stk01', None)
    s.part(c, 'P', '3001', 72)
    s.db.execute("UPDATE items SET name='=cmd()' WHERE item_no='311.1stk01'")                # a spreadsheet formula in a name
    r = mint(s.db, db)
    paths = write_report(r, tmp_path / 'report')
    assert sorted(p.name for p in paths) == ['collisions.csv', 'colours.csv', 'local-items.csv', 'mint.csv']
    with open(tmp_path / 'report' / 'mint.csv', newline='') as f:
        mint_rows = list(csv.DictReader(f))
    assert len(mint_rows) == len(r.items) == 4 and 'holder' in mint_rows[0]
    assert {row['item_no']: (row['rule'], row['collision']) for row in mint_rows}['311.1stk01'] == ('3', 'loser')
    with open(tmp_path / 'report' / 'local-items.csv', newline='') as f:
        (local,) = list(csv.DictReader(f))
    assert local['name'] == "'=cmd()" and local['reasons'] == 'collision'
    with open(tmp_path / 'report' / 'collisions.csv', newline='') as f:
        (col,) = list(csv.DictReader(f))
    assert col['loser_item_no'] == '311.1stk01' and col['shared_item'] == 'parts/003402'
    with open(tmp_path / 'report' / 'colours.csv', newline='') as f:
        assert {row['bl_color_id'] for row in csv.DictReader(f)} == {'', '72'}


def test_counts(world):
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'P', '3001', 5)
    s.part(c, '?', 'rebrickable:3001', 5)
    s.part(c, 'P', 'no-such', 5)
    s.part(c, 'P', 'syn-amb', 5)
    counts = mint(s.db, db).counts()
    assert counts['keys'] == 5 and counts['rule 1'] == 1 and counts['rule 3'] == 2 and counts['rule 5'] == 1 and counts['rule 4'] == 1
    assert counts['rule 4 holders'] == 1 and counts['rule 4 holders tied'] == 1 and counts['collisions'] == 1


def test_a_catalogue_is_required(tmp_path):
    from brickwork.store4.connect import connect
    with closing(connect(tmp_path / 'brickwork-4.db', tmp_path / 'none.db')) as db:
        with pytest.raises(CatalogueError):
            mint(Store33().db, db)


def test_the_candidate_helper_agrees_with_resolve_inverse(world):
    s, db = world
    for key, colour, bl in (('970c00', 'x', 11), ('970c00', 'y', 5), ('3001', 'z', 5), ('310.3stk01', 'w', 5)):
        found = identity.candidate_items(db, 'P', key, identity._inverse_color(db, 'bricklink', str(bl)))
        resolved = identity.resolve_inverse(db, 'P', key, str(bl), exhaustive=True)
        assert found == ([resolved[0]] if resolved else [])


# ---------- rule 6: type_crossed (a part BrickLink files as gear, book, ...) ----------

def test_a_part_filed_as_gear_is_crossed_to_the_part_in_the_sets_list(world):
    """BrickLink files some parts of a set under another type (G for the Chima cards); the catalogue links them under P. A G row in a
    part table is looked up as P, in the holder's catalogue list: one hit carries the line as that part, and no local gear item is made."""
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'G', '2071c01pb01', None)
    r = mint(s.db, db)
    t = r.target('G', '2071c01pb01', None, holder=('S', '2070-1', None))
    assert t.item_id == part(db, '2071pr0001') and t.color_id == 1
    d = r.items[('G', '2071c01pb01', None)]
    assert (d.rule, d.kind, d.crossed) == (6, 'part', True) and d.holders[('S', '2070-1', None)].rule == 6
    assert r.local_items == []                                            # no local gear item for a key whose only rows were carried
    header, rows = r.crossed_rows()
    assert [(x[0], x[1], x[3], x[5]) for x in rows] == [('G', '2071c01pb01', 'S:2070-1', part(db, '2071pr0001'))]
    assert r.counts()['type_crossed holders'] == 1 and r.check_injective() == []


def test_a_crossed_line_without_context_support_stays_a_gear_item(world):
    s, db = world
    c = s.copy('2070-1')
    s.part(c, 'G', '3001', None)                                          # P 3001 exists, but 2070-1's list does not hold it
    r = mint(s.db, db)
    d = r.items[('G', '3001', None)]
    t = r.target('G', '3001', None, holder=('S', '2070-1', None))
    assert d.holders[('S', '2070-1', None)].rule == 5 and t.item_id >= LOCAL_BASE
    [item] = r.local_items
    assert (item.kind, item.born_provider, item.born_namespace, item.born_key) == ('gear', 'bricklink', 'G', '3001')
    assert r.counts()['type_crossed holders without context support'] == 1
