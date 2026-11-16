"""Long selections must fit the server's request line: 200 storage labels, the order list of a big collection; the label zip is
streamed; a bad instruction job list is a 400. Invented data, no network."""
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from zipfile import ZipFile
import uuid

from bs4 import BeautifulSoup

from brickwork.core import labels, ledger
from tests.app4 import app4, client, coll, csrf, pair  # noqa: F401 (fixtures)
from tests.test_bw_order_missing_225 import SETTINGS, URL, page, ticked
from tests.test_storage_labels_31 import MATRIX

LIMIT = 8190
ROOT = Path(__file__).resolve().parents[1]


def test_entrypoint_raises_the_request_line_limit():
    assert f'--limit-request-line {LIMIT}' in (ROOT / 'entrypoint.sh').read_text()


def test_a_200_label_request_fits_the_request_line():
    ids = [uuid.uuid4().hex for _ in range(200)]
    line = 'GET /workbench/storage/labels/download?' + urlencode(dict(ids=','.join(ids), layout='a4-21', page='0')) + ' HTTP/1.1'
    assert len(line) < LIMIT


def test_label_zip_members_are_the_same_images(coll):
    for n in range(3):
        ledger.storage_save(coll.db, None, f'Box {n}')
    found = labels.plan(coll.db, [r['id'] for r in coll.db.execute('SELECT id FROM storage ORDER BY short_id')], 'tape-62', 'https://bricks.example')
    matrix = lambda payload: MATRIX
    data, mime, name = labels.download(found, matrix_factory=matrix)
    assert mime == 'application/zip' and name == 'storage-labels.zip'
    with ZipFile(BytesIO(data)) as archive:
        assert archive.namelist() == [r['short_id'] + '.png' for r in found['storages']]
        for row in found['storages']:
            expected = BytesIO()
            labels.label(row, 'tape-62', found['address']['value'], matrix).save(expected, 'PNG', dpi=(labels.DPI, labels.DPI))
            assert archive.read(row['short_id'] + '.png') == expected.getvalue()
    one = labels.plan(coll.db, [found['storages'][0]['id']], 'tape-62', 'https://bricks.example')
    assert labels.download(one, matrix_factory=matrix)[1:] == ('image/png', found['storages'][0]['short_id'] + '.png')


def many(coll, count):
    for key, value in SETTINGS.items():
        coll.setting(key, value)
    ids = []
    for _ in range(count):
        copy = coll.add_copy('1000-1', condition='used')
        coll.mark(copy, '3001', '4', missing=1)
        ids.append(copy)
    return ids


def request_line(url):
    return len('GET ' + url + ' HTTP/1.1')


def test_300_copies_give_short_links_that_resolve_to_the_same_selection(coll, client):
    ids = many(coll, 300)
    soup = page(client)
    assert len(ticked(soup)) == 300
    links = [soup.select_one('.oo-back')['href'], soup.select_one('.oo-export .button')['href']]
    links += [a['href'] for a in soup.select('.oo-tab')]
    review = page(client, sel='except', omit='', step='review')
    links.append(review.select_one('.oo-export .button')['href'])
    assert all(request_line(link) < LIMIT for link in links), [len(l) for l in links]
    export = client.get(review.select_one('.oo-export .button')['href'])
    assert export.status_code == 200
    explicit = client.get(URL + '/missing-parts.xml', query_string=dict(copy=ids))
    assert explicit.status_code == 200 and explicit.data == export.data
    # every copy but three: the same as ticking the others by hand
    omit = ids[:3]
    compact = page(client, sel='except', omit=','.join(omit))
    assert ticked(compact) == [i for i in ticked(page(client)) if i not in omit] and len(ticked(compact)) == 297
    by_hand = page(client, sel='1', copy=ticked(compact))
    assert ticked(by_hand) == ticked(compact)
    link = page(client, sel='except', omit=','.join(omit), step='review').select_one('.oo-export .button')['href']
    assert request_line(link) < LIMIT
    assert client.get(link).data == client.get(URL + '/missing-parts.xml', query_string=dict(copy=ticked(compact))).data
    assert parse_qs(urlsplit(link).query)['sel'] == ['except']


def test_an_instruction_find_with_a_bad_job_list_is_a_400(client, coll):
    assert client.get('/manage/instructions/find?jobs=abc').status_code == 400
    assert client.get('/manage/instructions/find?jobs=' + ','.join(['1'] * 51)).status_code == 400
    assert client.get('/manage/instructions/find?jobs=').status_code == 200
