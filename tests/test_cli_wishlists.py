"""The `brickwork wishlist` commands on a 4.0 collection (the CLI half of test_bw_wishlists_api, ported with API v2, issue #113): create, copy,
export, undo, archive and restore, reporting wish ids as texts. Invented data."""
import json
from xml.etree import ElementTree as ET

from brickwork.web.cli import main
from tests.app4 import app4, coll, pair, world  # noqa: F401


def test_the_wishlist_commands_create_copy_export_undo_archive_and_restore(app4, world, capsys):
    assert main(['wishlist', 'create', 'CLI', '--json']) == 0
    target = json.loads(capsys.readouterr().out)['id']
    assert main(['wishlist', 'copy', target, world.wish_part, '--json']) == 0
    event = json.loads(capsys.readouterr().out)['event_id']
    assert main(['wishlist', 'export', 'CLI', '--format', 'bricklink']) == 0
    output = capsys.readouterr()
    assert ET.fromstring(output.out).findtext('ITEM/ITEMID') == '3023'
    assert json.loads(output.err)['exported'] == 1
    assert main(['wishlist', 'export', 'all', '--format', 'rebrickable', '--kind', 'parts', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['content'].startswith('Part,Color,Quantity')
    assert main(['wishlist', 'undo', str(event)]) == 0
    capsys.readouterr()
    assert main(['wishlist', 'archive', target, '--json']) == 0
    capsys.readouterr()
    assert main(['wishlist', 'restore', target, '--json']) == 0
    capsys.readouterr()
    assert main(['wishlist', 'copy', 'nowhere', world.wish_part]) == 1
    assert 'Wishlist error' in capsys.readouterr().err
