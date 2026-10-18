"""Offline migration contracts; all records and identifiers are invented."""
from contextlib import closing
import importlib
import json
from pathlib import Path
import sqlite3

import pytest

from brickwork.core.importer.migrate import ProofError, file_hash, migrate
from brickwork.core.importer.projection import date, money, packed
from brickwork.web import cli

FIXTURES = Path(__file__).parent


def migration_connection(path, *, read_only=False):
    """Inspect the original 3.2 migration output without running later upgrades.

    Its deterministic bytes and proof are tested independently of the core connect()'s
    automatic 3.3 upgrade, covered by test_bw_api_m0.
    """
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) if read_only else sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def insert(db, table, **row):
    db.execute(f'INSERT INTO "{table}" ({",".join(chr(34)+k+chr(34) for k in row)}) VALUES ({",".join("?" for _ in row)})', tuple(row.values()))


@pytest.fixture
def legacy(tmp_path):
    apppath, webpath = tmp_path / 'app.db', tmp_path / 'extras.db'
    app = sqlite3.connect(apppath); web = sqlite3.connect(webpath)
    app.executescript((FIXTURES / 'app.sql').read_text())
    web.executescript((FIXTURES / 'web.sql').read_text())
    catalogpath = tmp_path / 'blcat.db'
    with sqlite3.connect(catalogpath) as catalog:
        catalog.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT,normalized_name TEXT,category TEXT)')
        catalog.executemany('INSERT INTO items VALUES(?,?,NULL,NULL,NULL)',
            [('S', 'new-set'), ('M', 'bl-figure'), ('P', 'bl-part'), ('P', 'other-part'), ('P', 'uncolored-part'), ('P', 'resolution-only')])
    for r in [dict(id=0, name='Unknown', type='solid'), dict(id=11, name='Invented blue', type='solid')]:
        insert(web, 'bricklink_colors', **r)
    insert(web, 'color_map', bricklink_color_id=11, color_id=71)
    insert(web, 'color_map', bricklink_color_id=0, color_id=9999)
    insert(app, 'bricktracker_metadata_storages', id='store', name='Shelf')
    insert(app, 'bricktracker_metadata_purchase_locations', id='shop', name='Shop')
    for table in ('rebrickable_sets', 'bricktracker_wishes'):
        insert(app, table, set='old-set', name='Invented set', year=2001, theme_id=12, number_of_parts=4,
               image='data/images/set.png', url='https://example.test/set',
               **(dict(number='old', version=1, last_modified='2020-01-01') if table == 'rebrickable_sets' else {}))
    (tmp_path / 'data/images').mkdir(parents=True)
    (tmp_path / 'data/images/set.png').write_bytes(b'invented-image-bytes')
    (tmp_path / 'data/images/parts').mkdir()
    (tmp_path / 'data/images/parts/unused.jpg').write_bytes(b'invented-cache-bytes')
    insert(app, 'bricktracker_sets', id='copy', set='old-set', description='Private note', storage='store',
           purchase_location='shop', purchase_date=0, purchase_price=12.345)
    insert(web, 'copy_status', copy_id='copy', condition='N', completeness='S', updated_at='2022-01-01')
    insert(web, 'copy_valuation', copy_id='copy', current_value='19.2300', current_value_currency=None, pinned=1)
    for n in ('rb-figure', 'rb-review', 'rb-cache-only'):
        insert(app, 'rebrickable_minifigures', figure=n, number=1, name='Invented '+n, image='https://example.test/'+n, number_of_parts=2)
    insert(web, 'minifig_bricklink', figure='rb-figure', bricklink_id='bl-figure', source='manual', set_num='old-set', resolved_at='2022-01-01')
    insert(web, 'bricklink_figures', bricklink_id='bl-figure', figure='rb-figure', state='manual', candidates_json='[]', parts_json='[]', resolved_at='2022-01-01')
    for number in ('rb-figure', 'rb-review'):
        insert(app, 'bricktracker_minifigures', id='copy', figure=number, quantity=1)
    insert(web, 'minifig_missing', copy_id='copy', figure='rb-figure', missing=1, updated_at='2022-01-02')
    for number, bl, url in [('rb-part', 'bl-part', 'https://example.test/a'), ('rb-duplicate', 'bl-part', 'https://example.test/conflict'),
                            ('rb-poster', None, None), ('rb-gear', None, None), ('rb-nocolor', 'uncolored-part', None)]:
        insert(app, 'rebrickable_parts', part=number, color_id=71, color_name='Invented blue', name='Invented part', category=1,
               image='https://example.test/part', image_id='unused', url=url, bricklink_color_id=11, bricklink_part_num=bl)
    # Same translated key survives as distinct copy_parts lineage rows.
    for n, number in enumerate(('rb-part', 'rb-duplicate', 'rb-poster', 'rb-gear'), start=1):
        insert(app, 'bricktracker_parts', id='copy', figure='rb-review' if n == 1 else None,
               part=number, color=71, spare=0, quantity=n, element=None, rebrickable_inventory=n, missing=2 if n == 1 else 0, damaged=1 if n == 1 else 0, checked=1)
    insert(web, 'part_resolutions', bricklink='resolution-only', parts='[{"part_num":"rb-resolution","name":"Invented"}]', resolved_at='2022-01-01', source='manual')
    insert(app, 'bricktracker_parts', id='copy', figure=None, part='rb-resolution', color=71, spare=1, quantity=1, rebrickable_inventory=5, missing=0, damaged=0, checked=0)
    insert(app, 'bricktracker_individual_parts', id='loose-part', part='rb-part', color=71, quantity=3, description='', missing=0, damaged=0, checked=0)
    insert(app, 'bricktracker_individual_minifigures', id='loose-figure', figure='rb-figure', quantity=2, description='Loose note')
    insert(web, 'loose_minifig_status', individual_id='loose-figure', condition='U', updated_at='2022-01-01')
    insert(web, 'loose_minifig_imports', import_key='opaque:rb-figure', individual_id='loose-figure', figure='rb-figure', quantity=2, created_at='2022-01-01')
    insert(app, 'bricktracker_individual_minifigure_parts', id='loose-figure', part='rb-part', color=71, spare=0, quantity=2, missing=0, damaged=0, checked=0, rebrickable_inventory=7)
    insert(web, 'loose_instructions', id='instruction', set_num='new-set', quantity=1, created_at='2022-01-01')
    insert(web, 'wish_meta', set='old-set', max_price=0.125, condition='any', updated_at='2022-01-01')
    for plural in ('statuses', 'tags', 'owners'):
        insert(app, 'bricktracker_metadata_'+plural, id='invented', name='Invented '+plural, **(dict(displayed_on_grid=0) if plural=='statuses' else {}))
        # All three flag kinds must have different identifiers in the target.
        kind={'statuses':'status','tags':'tag','owners':'owner'}[plural]
        if plural != 'statuses':
            app.execute(f'UPDATE bricktracker_metadata_{plural} SET id=?', (kind+'invented',))
            app.execute(f'ALTER TABLE bricktracker_set_{plural} RENAME COLUMN {kind}_invented TO {kind}_{kind}invented')
            if plural == 'owners':
                app.execute('ALTER TABLE bricktracker_wish_owners RENAME COLUMN owner_invented TO owner_ownerinvented')
        column=kind+'_'+('invented' if plural=='statuses' else kind+'invented')
        insert(app, 'bricktracker_set_'+plural, id='copy', **{column:1})
        insert(app, 'bricktracker_set_'+plural, id='gone', **{column:0})
    price=dict(set_num='new-set', slot='new', price=1.125, currency=None, source='brickset', observed_at='2022-01-01', sold=None, min=0.5, max=2.0, qty=None, guide_type=None, region=None)
    insert(web, 'price_history', id=4, **price)
    insert(web, 'price_history', id=8, **price)  # Exact duplicate retained; latest id wins.
    insert(web, 'price_slots', **price)
    insert(web, 'price_slots', **dict(price, slot='boxed', source='manual', price=5.0))  # Current-only observation.
    insert(web, 'minifig_price_history', id=4, bricklink_id='bl-figure', slot='bricklink_used', source='bricklink_stock', price=3.0, min=2.0, max=4.0, observed_at=None)
    partprice=dict(item_type='P',item_no='bl-part',color_id=11,condition='U',guide_type='sold',region='EU',currency='EUR',price='2.3400',qty=1,min='1.00',max='4.00',observed_at='2022-01-01',source='bricklink',last_error=None,last_attempt_at='2022-01-01')
    insert(web, 'part_price_history', id=4, **partprice)
    insert(web, 'part_price_history', id=9, **dict(partprice, price=None, last_error='invented error', observed_at=None, last_attempt_at='2022-01-02'))
    insert(web, 'part_prices', id=77, **dict(partprice, price=None, last_error='invented error', observed_at=None, last_attempt_at='2022-01-02'))
    insert(web, 'price_tracking', set_num='old-set', origin='wanted', first_seen='2022-01-01')
    insert(web, 'fetch_log', id=1, set_num='old-set', source='bricklink', at='2022-01-01', ok=1, detail='invented')
    insert(web, 'price_settings', id=1, bricklink_region='EU', bricklink_currency='EUR', incomplete_discount_pct=20,
           repair_shipping='3.00', repair_fees='0.50', repair_min_order='0', repair_use_loose_stock=0)
    insert(web, 'minifig_parts_bl', figure='rb-figure', fetched_at='2022-01-01', parts_json=packed([
        dict(bricklink=['bl-part'],color_id=11,quantity=1),dict(bricklink=['bl-part','other-part'],color_id=11,quantity=2)]))
    insert(web, 'identifications', id='recognition',created_at='2022-01-01',has_thumb=1,missing_count=0,
           candidates=packed([dict(bricklink='bl-part',score=0.9,name='Invented',img_url='https://example.test/image',parts=['rb-part'])]))
    insert(web, 'identification_actions', id=1,identification_id='recognition',kind='loose',at='2022-01-01',part_num='rb-part',color_id=71,color_name='Invented blue',quantity=1)
    app.commit();web.commit();app.close();web.close()
    decisions=tmp_path/'decisions.json'
    decisions.write_text(packed(dict(version=1,decided='2022-01-03',minifigs=[dict(source_id='rb-review',context='old-set',item_type='?',item_no='rebrickable:rb-review',status='to_check',method='review',evidence={'score':'0.1'})],
        manual=[dict(kind='set',source_id='old-set',item_type='S',item_no='new-set',status='manual',method='invented'),
                dict(kind='part',source_id='rb-gear/71',item_type='G',item_no='invented-gear',color_id=None,status='manual',method='invented')],
        to_check=[dict(kind='part',source_id='rb-poster/71',item_type='?',item_no='rebrickable:rb-poster',status='to_check',method='review')])) )
    (tmp_path/'Gear.xml').write_text('<INVENTORY><ITEM><ITEMTYPE>G</ITEMTYPE><ITEMID>invented-gear</ITEMID></ITEM></INVENTORY>')
    return dict(app_db=apppath,web_db=webpath,decisions=decisions,catalogues=tmp_path,
                out_db=tmp_path/'brickwork.db',report_dir=tmp_path/'proof')


def test_migration_mapping_and_determinism(legacy):
    before={k:file_hash(legacy[k]) for k in ('app_db','web_db','decisions')}
    result=migrate(**legacy)
    assert result['ok'] and result['integrity_check']==['ok'] and not result['foreign_key_check']
    assert all(r['count_ok'] and r['checksum_ok'] for r in result['tables'].values())
    assert before=={k:file_hash(legacy[k]) for k in before}
    with closing(migration_connection(legacy['out_db'])) as db:
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.2'
        assert all(r[0] is None for r in db.execute('SELECT archived_at FROM storages'))
        assert result['tables']['storages']['checksum_ok']
        assert result['tables']['storages']['source_non_null']['archived_at'] == 0
        assert result['tables']['storages']['target_non_null']['archived_at'] == 0
        copy=dict(db.execute('SELECT * FROM copies').fetchone())
        assert copy['set_no']=='new-set' and copy['purchase_price']=='12.345' and copy['purchase_date']=='1970-01-01T00:00:00+00:00'
        assert copy['note']=='Private note' and copy['current_value']=='19.2300' and copy['purchase_currency'] is None
        assert copy['completeness_source']=='manual' and copy['pinned']==1
        assert db.execute("SELECT count(*) FROM copy_parts WHERE item_no='bl-part'").fetchone()[0]==2
        assert db.execute('SELECT parent_minifig_type,parent_minifig,missing,damaged,checked FROM copy_parts WHERE id=1').fetchone()[:]==('?', 'rebrickable:rb-review',2,1,1)
        assert db.execute("SELECT condition,missing,damaged,checked FROM loose_stock WHERE id='loose-part'").fetchone()[:]==('U',0,0,0)
        assert db.execute("SELECT condition,missing FROM loose_stock WHERE id='instruction'").fetchone()[:]==(None,None)
        assert db.execute("SELECT missing FROM copy_minifigs WHERE minifig_no='bl-figure'").fetchone()[0]==1
        assert db.execute("SELECT color_id FROM copy_parts WHERE item_type='G'").fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM item_flags').fetchone()[0]==3
        assert db.execute("SELECT max_price FROM wishlist").fetchone()[0]=='0.125'
        assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0]==6
        assert db.execute("SELECT observation_id FROM price_current WHERE guide='valuation'").fetchone()[0]==2
        assert db.execute("SELECT currency FROM price_current WHERE guide='valuation'").fetchone()[0] is None
        assert db.execute("SELECT last_attempt_at FROM price_watch WHERE item_type='P'").fetchone()[0]=='2022-01-02'
        assert db.execute("SELECT local_path,kind FROM item_images WHERE item_type='S' LIMIT 1").fetchone()[:] == ('data/images/set.png', 'photo')
        assert db.execute("SELECT kind FROM item_images WHERE item_no='bl-part' LIMIT 1").fetchone()[0] == 'render'
        assert db.execute("SELECT local_path FROM item_images WHERE item_no='bl-part' LIMIT 1").fetchone()[0]=='data/images/parts/unused.jpg'
        assert db.execute("SELECT value FROM item_properties WHERE item_no='bl-part' AND key='url'").fetchone() is None
        assert db.execute("SELECT item_no FROM id_match WHERE source_id='rb-cache-only'").fetchone()[0] is None
        assert tuple(db.execute("SELECT method,decided_at FROM id_match WHERE kind='part' AND source_id='rb-resolution'").fetchone())==('manual','2022-01-01')
        assert tuple(db.execute("SELECT method,context FROM id_match WHERE source_id='rb-figure'").fetchone())==('manual','old-set')
        assert db.execute("SELECT part_num,color_id FROM identification_actions").fetchone()[:]==('bl-part',11)
        assert json.loads(db.execute('SELECT candidates FROM identifications').fetchone()[0])[0]['parts']==['bl-part']
        assert db.execute('SELECT count(*) FROM source_freshness').fetchone()[0]==18
        assert db.execute("SELECT max_age_days FROM source_freshness WHERE source='manual' AND kind='pictures'").fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM events').fetchone()[0]==sum(result['tables'][t]['actual'] for t in ('copies','copy_parts','copy_minifigs','loose_stock','loose_minifig_parts','wishlist','flags','item_flags','settings','lots'))
    digest=file_hash(legacy['out_db'])
    other=dict(legacy,out_db=legacy['out_db'].with_name('second.db'),report_dir=legacy['report_dir'].with_name('proof2'))
    migrate(**other)
    assert file_hash(other['out_db'])==digest
    with pytest.raises(FileExistsError):migrate(**legacy)
    assert file_hash(legacy['out_db'])==digest
    migrate(**legacy,replace=True)
    assert file_hash(legacy['out_db'])==digest


def test_money_dates():
    assert money(None) is None and money('1.2300')=='1.2300' and money(1e-7)=='0.0000001'
    assert date(None) is None and date('existing-time')=='existing-time'
    with pytest.raises(ValueError):money(float('inf'))


def test_fail_closed_proof_and_missing_colour(legacy):
    # Models the real snapshot block: an authoritative bridge refers to a
    # colour absent from the source colours, so no repair is invented.
    with sqlite3.connect(legacy['web_db']) as db:db.execute('DELETE FROM bricklink_colors WHERE id=11')
    with pytest.raises(ProofError):migrate(**legacy)
    assert not legacy['out_db'].exists()
    report=json.loads((legacy['report_dir']/'proof.json').read_text())
    assert not report['ok'] and report['foreign_key_check'] and report['input_hashes_unchanged']
    assert not list(legacy['out_db'].parent.glob('*.migrating*'))


def test_approved_missing_colours_are_added_with_evidence(legacy):
    with sqlite3.connect(legacy['web_db']) as db:
        db.execute('DELETE FROM bricklink_colors WHERE id=0')
        insert(db, 'color_map', bricklink_color_id=117, color_id=76)
    with sqlite3.connect(legacy['app_db']) as db:
        insert(db, 'rebrickable_parts', part='rb-not-applicable', color_id=9999,
               name='Invented neutral part', bricklink_part_num='bl-part',
               bricklink_color_id=0, bricklink_color_name='(Not Applicable)')
        insert(db, 'bricktracker_parts', id='copy', part='rb-not-applicable', color=9999,
               spare=0, quantity=1, missing=0, damaged=0, checked=0, rebrickable_inventory=101)
    before = {k: file_hash(legacy[k]) for k in ('app_db', 'web_db')}
    report = migrate(**legacy)
    assert report['ok'] and not report['foreign_key_check']
    assert before == {k: file_hash(legacy[k]) for k in before}
    assert [r['color_id'] for r in report['colors_added_from_evidence']] == [0, 117]
    assert '## Colours added from evidence' in (legacy['report_dir'] / 'proof.md').read_text()
    with closing(migration_connection(legacy['out_db'])) as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM colors ORDER BY color_id')] == [
            (0, '(Not Applicable)', None, None), (11, 'Invented blue', 'solid', None),
            (117, None, None, None)]
        records = {r['source_id']: json.loads(r['payload']) for r in db.execute(
            "SELECT * FROM source_records WHERE source='rebrickable' AND kind='migration'")}
        assert len(records['colors:0']['records']) == 2
        assert records['colors:0']['records'][0] == {
            'table': 'color_map', 'record': {'bricklink_color_id': 0, 'color_id': 9999}}
        assert records['colors:0']['records'][1]['record']['bricklink_color_name'] == '(Not Applicable)'
        assert records['colors:117']['records'] == [
            {'table': 'color_map', 'record': {'bricklink_color_id': 117, 'color_id': 76}}]
        assert db.execute('SELECT color_id FROM copy_parts WHERE source_ref=101').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM copy_parts WHERE color_id=117').fetchone()[0] == 0
    second = dict(legacy, out_db=legacy['out_db'].with_name('second.db'),
                  report_dir=legacy['report_dir'].with_name('proof2'))
    migrate(**second)
    assert file_hash(legacy['out_db']) == file_hash(second['out_db'])


def test_missing_colour_zero_requires_consistent_name_evidence(legacy):
    with sqlite3.connect(legacy['web_db']) as db:
        db.execute('DELETE FROM bricklink_colors WHERE id=0')
    with sqlite3.connect(legacy['app_db']) as db:
        insert(db, 'rebrickable_parts', part='rb-neutral', color_id=9999,
               bricklink_color_id=0, bricklink_color_name='Unapproved name')
    with pytest.raises(ValueError, match='name evidence'):
        migrate(**legacy)
    assert not legacy['out_db'].exists()


def test_checksum_failure_preserves_existing_output(legacy,monkeypatch):
    legacy['out_db'].write_bytes(b'keep-existing-file')
    module=importlib.import_module('brickwork.core.importer.migrate')
    original=module.project;calls=0
    def changed(*args):
        nonlocal calls
        rows,listing=original(*args);calls+=1
        if calls==2:rows['copies'][0]['note']='different'
        return rows,listing
    monkeypatch.setattr(module,'project',changed)
    with pytest.raises(ProofError):migrate(**legacy,replace=True)
    assert legacy['out_db'].read_bytes()==b'keep-existing-file'
    report=json.loads((legacy['report_dir']/'proof.json').read_text())
    assert not report['tables']['copies']['checksum_ok']


def test_refuse_inputs_and_symlinks(legacy):
    with pytest.raises(ValueError):migrate(**dict(legacy,out_db=legacy['app_db']),replace=True)
    legacy['out_db'].symlink_to(legacy['web_db'])
    with pytest.raises(ValueError):migrate(**legacy,replace=True)


def test_cli_offline(legacy,monkeypatch,capsys):
    def forbidden(*args):raise AssertionError('live context must not be initialized')
    monkeypatch.setattr(cli,'application_context',forbidden)
    argv=['migrate']
    for option,key in [('app','app_db'),('extras','web_db'),('decisions','decisions'),('catalogue','catalogues'),('out','out_db'),('report','report_dir')]:
        argv+=['--'+option,str(legacy[key])]
    assert cli.main(argv)==0
    assert 'checksum_ok: True' in capsys.readouterr().out
    assert cli.main(argv)==1


def test_unmatched_colours_and_parts_keep_collection_state(legacy):
    with sqlite3.connect(legacy['app_db']) as db:
        insert(db,'bricktracker_parts',id='copy',figure=None,part='invented-unmatched',color=404,spare=0,quantity=7,
               rebrickable_inventory=99,missing=3,damaged=2,checked=1)
    result=migrate(**legacy)
    assert result['ok']
    with closing(migration_connection(legacy['out_db'])) as db:
        row=db.execute("SELECT item_type,item_no,color_id,quantity,missing,damaged,checked FROM copy_parts WHERE source_ref=99").fetchone()
        assert tuple(row)==('?', 'rebrickable:invented-unmatched',None,7,3,2,1)
        assert db.execute("SELECT status FROM id_match WHERE kind='color' AND source_id='404'").fetchone()[0]=='unmatched'
    assert any(r['kind']=='part' and r['source_id']=='invented-unmatched' and r['status']=='unmatched' for r in result['reviews'])


def test_confirmed_context_and_typed_manual_exceptions(legacy):
    d=json.loads(legacy['decisions'].read_text())
    d['minifigs'][0].update(item_type='M',item_no='bl-figure',status='matched',method='confirmed')
    # Do not create a collision with the existing required minifigure.
    with sqlite3.connect(legacy['app_db']) as db:
        db.execute("DELETE FROM bricktracker_minifigures WHERE figure='rb-figure'")
    with sqlite3.connect(legacy['web_db']) as db:
        db.execute('DELETE FROM minifig_missing')
    d['manual'].append(dict(kind='part',source_id='rb-duplicate/71',item_type='M',item_no='bl-figure',color_id=None,status='manual',method='invented'))
    d['manual'].append(dict(kind='part',source_id='rb-poster/71',item_type='P',item_no='other-part',color_id=0,status='manual',method='invented'))
    d['to_check']=[]
    legacy['decisions'].write_text(packed(d))
    migrate(**legacy)
    with closing(migration_connection(legacy['out_db'])) as db:
        assert tuple(db.execute('SELECT parent_minifig_type,parent_minifig FROM copy_parts WHERE id=1').fetchone())==('M','bl-figure')
        assert tuple(db.execute('SELECT item_type,item_no,color_id FROM copy_parts WHERE id=2').fetchone())==('M','bl-figure',None)
        assert tuple(db.execute('SELECT item_type,item_no,color_id FROM copy_parts WHERE id=3').fetchone())==('P','other-part',0)
        assert db.execute("SELECT missing FROM copy_minifigs").fetchone()[0]==0


def test_ambiguous_colour_and_disagreeing_bridge(legacy):
    with sqlite3.connect(legacy['web_db']) as db:
        insert(db,'color_map',bricklink_color_id=0,color_id=71)
    migrate(**legacy)
    with closing(migration_connection(legacy['out_db'])) as db:
        assert db.execute("SELECT status FROM id_match WHERE kind='color' AND source_id='71'").fetchone()[0]=='to_check'
        assert tuple(db.execute('SELECT item_type,color_id FROM copy_parts WHERE id=1').fetchone())==('?',None)


def test_lots_and_used_defaults_with_absent_joins(legacy):
    with sqlite3.connect(legacy['app_db']) as db:
        insert(db,'bricktracker_individual_part_lots',id='invented-lot',name='Lot',description='Lot note',created_date=1,
               storage='store',purchase_location='shop',purchase_date=2,purchase_price=0.0001)
        db.execute("UPDATE bricktracker_individual_parts SET lot_id='invented-lot'")
    with sqlite3.connect(legacy['web_db']) as db:
        db.execute('DELETE FROM copy_valuation');db.execute('DELETE FROM copy_status')
    migrate(**legacy)
    with closing(migration_connection(legacy['out_db'])) as db:
        assert tuple(db.execute('SELECT pinned,completeness,completeness_source,updated_at FROM copies').fetchone())==(0,None,None,None)
        assert tuple(db.execute('SELECT note,created_date,purchase_price FROM lots').fetchone())==('Lot note','1970-01-01T00:00:01+00:00','0.0001')
        assert db.execute("SELECT count(*) FROM events WHERE entity LIKE 'lots:%'").fetchone()[0]==1


def test_catalogue_validation_and_true_orphans(legacy):
    (legacy['catalogues']/'Gear.xml').write_text('<INVENTORY/>')
    with pytest.raises(ValueError,match='Gear'):migrate(**legacy)
    (legacy['catalogues']/'Gear.xml').write_text('<INVENTORY><ITEM><ITEMTYPE>G</ITEMTYPE><ITEMID>invented-gear</ITEMID></ITEM></INVENTORY>')
    with sqlite3.connect(legacy['app_db']) as db:
        db.execute("UPDATE bricktracker_set_statuses SET status_invented=1 WHERE id='gone'")
    with pytest.raises(ValueError,match='orphan'):migrate(**legacy)


def test_only_local_images_are_projected(legacy):
    (legacy['app_db'].parent / 'data/images/set.png').unlink()
    result = migrate(**legacy)
    with closing(migration_connection(legacy['out_db'])) as db:
        assert not db.execute("SELECT 1 FROM item_images WHERE item_type='S'").fetchone()
        assert not db.execute('SELECT 1 FROM item_images WHERE local_path IS NULL').fetchone()
        assert all((legacy['app_db'].parent / r[0]).is_file()
                   for r in db.execute('SELECT local_path FROM item_images'))
        assert 'data/images/set.png' in db.execute(
            "SELECT payload FROM source_records WHERE kind='rebrickable_sets'").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO item_images(item_type,item_no,source,kind) VALUES('S','new-set','rebrickable','render')")
    assert any(r['rule'] == 'image URL retained raw; local file absent' for r in result['transformations'])


def test_real_catalogue_layout_and_gear_db(legacy, monkeypatch):
    catalogue = legacy['catalogues'] / 'bricklink-catalog.db'
    (legacy['catalogues'] / 'blcat.db').rename(catalogue)
    with sqlite3.connect(catalogue) as db:
        insert(db, 'items', item_type='G', item_no='invented-gear')
    (legacy['catalogues'] / 'Gear.xml').unlink()
    legacy.update(catalogues=catalogue, catalogue_src=catalogue.parent / 'xml')
    def forbidden(*args):
        raise AssertionError('live context must not be initialized')
    monkeypatch.setattr(cli, 'application_context', forbidden)
    argv = ['migrate']
    for option, key in [('app','app_db'), ('extras','web_db'), ('decisions','decisions'),
                        ('catalogue','catalogues'), ('catalogue-src','catalogue_src'),
                        ('out','out_db'), ('report','report_dir')]:
        argv += ['--' + option, str(legacy[key])]
    assert cli.main(argv) == 0
    with sqlite3.connect(catalogue) as db:
        db.execute("UPDATE items SET item_no='different-gear' WHERE item_type='G'")
    with pytest.raises(ValueError, match='BrickLink catalogue'):
        migrate(**legacy, replace=True)


def test_catalogue_xml_fallback_separate_directory(legacy):
    catalogue = legacy['catalogues'] / 'bricklink-catalog.db'
    (legacy['catalogues'] / 'blcat.db').rename(catalogue)
    xml = legacy['catalogues'] / 'xml'
    xml.mkdir()
    (legacy['catalogues'] / 'Gear.xml').rename(xml / 'Gear.xml')
    legacy.update(catalogues=catalogue, catalogue_src=xml)
    assert migrate(**legacy)['ok']
    assert 'Gear.xml' in json.loads((legacy['report_dir'] / 'proof.json').read_text())['inputs_sha256']
    with pytest.raises(ValueError, match='distinct'):
        migrate(**dict(legacy, out_db=xml / 'Gear.xml'), replace=True)


def test_old_catalogue_form_deprecated(legacy):
    with pytest.warns(FutureWarning, match='deprecated'):
        assert migrate(**legacy)['ok']


def test_cache_rows_carried_and_non_cache_still_blocked(legacy):
    rows = [dict(part_num='rb-part', bricklink_part='bl-part', checked_at=0.0, error=None),
            dict(part_num='new-evidence', bricklink_part='cache-only-target', checked_at=1.0, error=None),
            dict(part_num='failed', bricklink_part=None, checked_at=2.0, error='not found'),
            dict(part_num=None, bricklink_part=None, checked_at=3.0, error='no identity'),
            dict(part_num='rb-part', bricklink_part='bl-part', checked_at=4.0, error='previous error'),
            dict(part_num='conflict', bricklink_part='bl-part', checked_at=None, error=None),
            dict(part_num='conflict', bricklink_part='other-part', checked_at=5.0, error=None)]
    with sqlite3.connect(legacy['web_db']) as db:
        for row in rows:
            insert(db, 'part_image_mappings', **row)
    result = migrate(**legacy)
    assert result['ok'] and len(result['cache_rows_carried']) == len(rows)
    assert '## Cache rows carried' in (legacy['report_dir'] / 'proof.md').read_text()
    assert not any(r['table'] == 'part_image_mappings' for r in result['dropped_columns'])
    with closing(migration_connection(legacy['out_db'])) as db:
        matches = {r['source_id']: dict(r) for r in db.execute("SELECT * FROM id_match WHERE kind='part-image'")}
        assert matches['rb-part']['item_no'] == 'bl-part'
        assert matches['new-evidence']['item_no'] is None
        assert matches['failed']['status'] == 'unmatched'
        assert matches['conflict']['status'] == 'to_check'
        assert matches['rb-part']['decided_at'] == '1970-01-01T00:00:04+00:00'
        retained = [entry['record'] for match in matches.values()
                    for entry in json.loads(match['evidence_json']) if 'record' in entry]
        retained += [entry['record'] for r in db.execute("SELECT payload FROM source_records WHERE kind='part-image'")
                     for entry in json.loads(r[0])['records']]
        assert sorted(map(packed, retained)) == sorted(map(packed, rows))
    second = dict(legacy, out_db=legacy['out_db'].with_name('second.db'), report_dir=legacy['report_dir'].with_name('proof2'))
    migrate(**second)
    assert file_hash(legacy['out_db']) == file_hash(second['out_db'])
    with sqlite3.connect(legacy['web_db']) as db:
        insert(db, 'house_loose_transfers', event_id=1, payload='{}', applied_at='2022-01-01')
    with pytest.raises(ValueError, match='Approved empty drop now contains data: house_loose_transfers'):
        migrate(**legacy, replace=True)


def test_approved_proof_adjusts_only_image_and_cache_counts(legacy, monkeypatch):
    from brickwork.core.importer import proof
    from brickwork.core.importer.projection import project
    baseline, listing = project(legacy['app_db'], legacy['web_db'], legacy['decisions'],
                                legacy['catalogues'] / 'blcat.db')
    counts = {table: len(rows) for table, rows in baseline.items()}
    counts['schema_meta'] = 1
    counts['item_properties'] -= sum(r['rule'] == 'name mapped' for r in listing)
    counts['item_images'] += sum(r['rule'] == 'image URL retained raw; local file absent' for r in listing)
    monkeypatch.setattr(proof, 'APPROVED_COUNTS', counts)
    verify = proof.verify
    def approved_verify(db, expected, transformations, **kwargs):
        return verify(db, expected, transformations, approved=True)
    monkeypatch.setattr(proof, 'verify', approved_verify)
    with sqlite3.connect(legacy['web_db']) as db:
        insert(db, 'part_image_mappings', part_num='rb-part', bricklink_part='bl-part', checked_at=0)
        insert(db, 'part_image_mappings', part_num=None, error='no identity')
    result = migrate(**legacy)
    assert result['ok']
    assert result['tables']['id_match']['expected'] == counts['id_match'] + 1
    assert result['tables']['source_records']['expected'] == counts['source_records'] + 1
    assert result['tables']['item_images']['expected'] == len(baseline['item_images'])
    counts['copies'] += 1
    with pytest.raises(ProofError):
        migrate(**legacy, replace=True)


def test_182_wishes_flags_and_colour_mapping_deterministic(legacy):
    with sqlite3.connect(legacy['app_db']) as db:
        for n in range(181):
            insert(db, 'bricktracker_wishes', set=f'wish-{n}', name='Synthetic wish')
        insert(db, 'bricktracker_wish_owners', set='old-set', owner_ownerinvented=1)
    before = {k:file_hash(legacy[k]) for k in ('app_db','web_db')}
    result = migrate(**legacy)
    assert result['ok'] and result['wishlist_mapping']['legacy'] == 182
    assert result['wishlist_mapping']['part_colour_keys'] == 0
    with closing(migration_connection(legacy['out_db'], read_only=True)) as db:
        assert db.execute('SELECT count(*),sum(quantity),count(color_id) FROM wishlist').fetchone()[:] == (182,182,0)
        assert db.execute("SELECT entity_id FROM item_flags WHERE entity_type='wishlist'").fetchone()[0] == str(db.execute("SELECT id FROM wishlist WHERE item_no='new-set'").fetchone()[0])
    other = dict(legacy,out_db=legacy['out_db'].with_name('second.db'),report_dir=legacy['report_dir'].with_name('second-proof'))
    assert migrate(**other)['ok']
    assert file_hash(other['out_db']) == file_hash(legacy['out_db'])
    assert before == {k:file_hash(legacy[k]) for k in before}


def test_legacy_part_colour_wish_and_flag(legacy):
    key = json.dumps(['rb-part',71])
    with sqlite3.connect(legacy['app_db']) as db:
        insert(db, 'bricktracker_wishes', set=key, name='Coloured part')
        insert(db, 'bricktracker_wish_owners', set=key, owner_ownerinvented=1)
    report = migrate(**legacy)
    assert report['ok'] and report['wishlist_mapping']['part_colour_keys'] == 1
    with closing(migration_connection(legacy['out_db'],read_only=True)) as db:
        wish = db.execute("SELECT id,color_id,quantity FROM wishlist WHERE item_type='P'").fetchone()
        assert wish[1:] == (11,1)
        assert db.execute("SELECT entity_id FROM item_flags WHERE entity_type='wishlist'").fetchone()[0] == str(wish['id'])


def test_names_catalogue_precedence_and_retained_fallback(legacy):
    with sqlite3.connect(legacy['catalogues'] / 'blcat.db') as db:
        db.execute("UPDATE items SET name='Canonical part' WHERE item_no='bl-part'")
        db.execute("UPDATE items SET name='Canonical set' WHERE item_no='new-set'")
    result = migrate(**legacy)
    assert result['ok']
    assert 'Result: PASS' in (legacy['report_dir'] / 'proof.md').read_text()
    with migration_connection(legacy['out_db']) as db:
        for kind, number, name, source in [('P','bl-part','Canonical part','bricklink'),
                ('S','new-set','Canonical set','bricklink'),
                ('M','bl-figure','Invented rb-figure','rebrickable')]:
            assert db.execute('SELECT name FROM items WHERE item_type=? AND item_no=?', (kind,number)).fetchone()[0] == name
            row = db.execute("SELECT value,source FROM item_properties WHERE item_type=? AND item_no=? AND key='name'", (kind,number)).fetchone()
            assert tuple(row) == (name, source)
        assert db.execute("SELECT name FROM items WHERE item_no='resolution-only'").fetchone()[0] is None
        assert db.execute("SELECT name FROM search_index WHERE item_no='bl-part'").fetchone()[0] == 'Canonical part'


def test_optional_extras_cli(legacy, capsys):
    before = file_hash(legacy['app_db'])
    argv = ['migrate']
    for option, key in [('app', 'app_db'), ('decisions', 'decisions'), ('catalogue', 'catalogues'),
                        ('out', 'out_db'), ('report', 'report_dir')]:
        argv += ['--' + option, str(legacy[key])]
    assert cli.main(argv) == 0, capsys.readouterr().err
    assert file_hash(legacy['app_db']) == before
    with migration_connection(legacy['out_db'], read_only=True) as db:
        assert db.execute('SELECT count(*) FROM copies').fetchone()[0] == 1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_import_available_in_tools_admin(legacy, tmp_path, monkeypatch):
    from flask import Flask
    from brickwork.app import setup_app
    from tests.web_fixtures import ROOT
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'uninitialized.db'))
    monkeypatch.setenv('BW_AUTHENTICATION_KEY', 'synthetic-session')
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.delenv('BW_AUTHENTICATION_PASSWORD', raising=False)
    monkeypatch.delenv('BW_READ_ONLY', raising=False)
    app = Flask('import-tests', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config['TESTING'] = True
    client = app.test_client()
    response = client.get('/manage/import-legacy')
    assert response.status_code == 200
    assert 'Import from BrickTracker' in response.text
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']
    form = {option: str(legacy[key]) for option, key in [('app', 'app_db'), ('extras', 'web_db'),
        ('decisions', 'decisions'), ('catalogue', 'catalogues'), ('out', 'out_db'), ('report', 'report_dir')]}
    assert client.post('/manage/import-legacy/migrate', data=form).status_code == 400
    assert not legacy['out_db'].exists()
    before = {key: file_hash(legacy[key]) for key in ('app_db', 'web_db')}
    form['csrf_token'] = csrf
    response = client.post('/manage/import-legacy/migrate', data=form)
    assert response.status_code == 200 and 'Import complete' in response.text
    assert {key: file_hash(legacy[key]) for key in before} == before
    output_hash = file_hash(legacy['out_db'])
    assert 'Output exists' in client.post('/manage/import-legacy/migrate', data=form).text
    assert file_hash(legacy['out_db']) == output_hash
    monkeypatch.setenv('BW_READ_ONLY', '1')
    assert client.post('/manage/import-legacy/migrate', data=form).status_code == 403


@pytest.mark.parametrize('source', ['derived', 'manual'])
def test_migrated_checked_copy_without_session(legacy, source):
    from brickwork.core import admin, checker
    # Metadata identity survives the actual migration, including its arbitrary id.
    with sqlite3.connect(legacy['app_db']) as old:
        old.execute("UPDATE bricktracker_metadata_statuses SET name='Set is checked'")
    migrate(**legacy)
    with admin.database(legacy['out_db']) as db:
        with db:
            db.execute("UPDATE copies SET completeness_source=?, completeness='S'", (source,))
            db.execute('UPDATE copy_parts SET checked=0, missing=0, damaged=0')
            db.execute('UPDATE copy_minifigs SET missing=0')
            checker.recompute(db, 'copy')
        assert checker.checked_flag(db) == 'invented'
        assert checker.session(db, 'copy') is None
        assert checker.view(db, 'copy', legacy['out_db'].parent)['copy']['set_checked']
        assert checker.choices(db, legacy['out_db'].parent)[0]['copy']['set_checked']
        assert checker.copy(db, 'copy')['completeness'] == ('C' if source == 'derived' else 'S')
        with db:
            db.execute('UPDATE copy_minifigs SET missing=1')
            checker.recompute(db, 'copy')
        assert checker.copy(db, 'copy')['completeness'] == ('I' if source == 'derived' else 'S')

