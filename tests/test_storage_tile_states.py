"""The Storage page's set tile (bw_storage.html set_tile) reads a copy's state as the Sets list's tile does (Argon review, 23.11.): a copy
marked Complete by hand counts its whole list as found, and a copy with only damaged parts marked is checked, not "Not checked"."""
from pathlib import Path

from bs4 import BeautifulSoup

from tests.app4 import app4, pair  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parent.parent


def tile_text(app4, copy):
    tile = dict(name='Passenger Train', item_no='7938-1', price=None, image=None, item_id=None, theme=None, year=None, unresolved=False,
                copies=[dict(dict(id='c1', lot=None, storage_id=None, place_id=None), **copy)])
    source = (ROOT / 'templates/web/toni/web/bw_storage.html').read_text()
    start = source.index('{% macro set_tile(tile) %}')
    macro = source[start:source.index('{% endmacro %}', start) + len('{% endmacro %}')]     # the macro alone: the page needs its own context
    with app4.test_request_context('/workbench/storage'):
        html = app4.jinja_env.from_string(macro + '{{ set_tile(tile) }}').render(tile=tile)
    return BeautifulSoup(str(html), 'html.parser').select_one('.bartxt').get_text(' ', strip=True)


def test_a_copy_marked_complete_by_hand_reads_complete(app4):
    text = tile_text(app4, dict(completeness='complete', bar=[0, 0, 375, 0, 0, '']))
    assert 'Not checked' not in text and 'complete' in text


def test_a_copy_with_only_damaged_parts_reads_its_damage(app4):
    text = tile_text(app4, dict(completeness='incomplete', bar=[0, 0, 375, 0, 2, '']))
    assert 'Not checked' not in text and '2 damaged' in text


def test_a_copy_never_checked_still_reads_not_checked(app4):
    assert 'Not checked' in tile_text(app4, dict(completeness=None, bar=[0, 0, 375, 0, 0, '']))
