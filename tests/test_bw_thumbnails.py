"""Picture thumbnails: generation, cache, invalidation, safety and the templates that use them."""
from contextlib import closing
import os
from io import BytesIO
import threading
import time

import pytest

from bs4 import BeautifulSoup
from PIL import Image

from brickwork.core import thumbnails
from brickwork.core.connect import connect
from tests.app4 import app4, client, pair, world, coll  # noqa: F401 (fixtures)
from tests.web_fixtures import logged_in


def picture(pair, name='big.png', size=(1200, 900), color='white', item=None):
    """A stored picture file and its `picture` row for a part (a new local one named `name`, or `item`); returns (picture id, the file)."""
    path = pair.parent / 'data/images' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', size, color).save(path)
    with closing(connect(pair)) as db, db:
        item = item or db.execute("SELECT coalesce(max(id), 999999999) + 1 FROM item WHERE id>=1000000000").fetchone()[0]
        db.execute("INSERT OR IGNORE INTO item(id,origin,kind,kind_source,name,born_provider,born_namespace,born_key,created_at,updated_at) "
                   "VALUES(?,'local','part','bricklink',?,'bricklink','P',?,'a','a')", (item, name, name))
        return db.execute("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'rebrickable_api','render',?,'2099-01-01')",
                          (item, 'data/images/' + name)).lastrowid, path


@pytest.fixture(autouse=True)
def clean_state():
    thumbnails._pending.clear()
    thumbnails._skipped.clear()
    yield
    thumbnails._pending.clear()


def settle():
    deadline = time.time() + 10
    while thumbnails._pending and time.time() < deadline:
        time.sleep(0.01)


def get_once(client, identifier, width=None):
    return client.get(f'/manage/images/{identifier}' + (f'?w={width}' if width else ''))


def fetch(client, identifier, width=None):
    """A request that sees the finished thumbnail: the first (miss) request, the job, then again."""
    response = get_once(client, identifier, width)
    settle()
    return get_once(client, identifier, width) if width else response


def test_thumbnail_is_generated_cached_and_not_cropped(app4, pair):
    identifier, original = picture(pair)
    client = logged_in(app4)
    response = fetch(client, identifier, 320)
    assert response.status_code == 200
    assert response.mimetype in ('image/webp', 'image/jpeg')
    image = Image.open(BytesIO(response.data))
    assert image.size == (320, 240)                      # same aspect, never cropped
    assert len(response.data) < original.stat().st_size
    assert 'private' in response.headers['Cache-Control'] and 'max-age=86400' in response.headers['Cache-Control']
    assert 'public' not in response.headers['Cache-Control']
    assert Image.open(BytesIO(fetch(client, identifier, 640).data)).size == (640, 480)
    cached = sorted((pair.parent / 'data/thumbs').iterdir())
    assert len(cached) == 2
    mtimes = [p.stat().st_mtime_ns for p in cached]
    again = fetch(client, identifier, 320)
    assert again.data == response.data
    assert [p.stat().st_mtime_ns for p in sorted((pair.parent / 'data/thumbs').iterdir())] == mtimes   # cache hit
    assert fetch(client, identifier).data == original.read_bytes()                                  # no w: original


def test_thumbnail_is_regenerated_when_the_original_changes(app4, pair):
    identifier, original = picture(pair, color='white')
    client = logged_in(app4)
    first = fetch(client, identifier, 320).data
    Image.new('RGB', (1000, 1000), 'red').save(original)
    os.utime(original, ns=(original.stat().st_atime_ns, original.stat().st_mtime_ns + 5_000_000_000))
    second = Image.open(BytesIO(fetch(client, identifier, 320).data))
    assert second.size == (320, 320) and second.convert('RGB').getpixel((5, 5))[0] > 200 and second.convert('RGB').getpixel((5, 5))[1] < 60
    assert first != fetch(client, identifier, 320).data
    assert len([p for p in (pair.parent / 'data/thumbs').iterdir() if p.name.startswith(f'{identifier}-320-')]) == 1   # stale one removed


def test_unsupported_width_and_traversal_are_refused(app4, pair):
    identifier, _ = picture(pair)
    client = logged_in(app4)
    assert fetch(client, identifier, 999).status_code == 400
    assert client.get(f'/manage/images/{identifier}?w=../x').status_code == 400
    with closing(connect(pair)) as db, db:
        identifier_item = db.execute('SELECT item_id FROM picture WHERE id=?', (identifier,)).fetchone()[0]
        db.execute('PRAGMA ignore_check_constraints=ON')
        bad = db.execute("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/../../secret.png','2099-01-01')", (identifier_item,)).lastrowid
    (pair.parent / 'secret.png').write_bytes(b'x')
    assert fetch(client, bad, 320).status_code == 404
    assert fetch(client, bad).status_code == 404
    assert not (pair.parent / 'data/thumbs').exists() or not list((pair.parent / 'data/thumbs').glob(f'{bad}-*'))
    assert app4.test_client().get(f'/manage/images/{identifier}?w=320').status_code in (302, 401)


def test_animated_small_oversized_and_unreadable_images_fall_back_to_the_original(app4, pair, monkeypatch):
    client = logged_in(app4)
    gif, path = picture(pair, 'anim.gif', (800, 600))
    frames = [Image.new('RGB', (800, 600), c) for c in ('red', 'blue')]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=50, loop=0)
    assert fetch(client, gif, 320).data == path.read_bytes()
    small, path = picture(pair, 'small.png', (100, 100))
    assert fetch(client, small, 320).data == path.read_bytes()
    broken, path = picture(pair, 'broken.png', (10, 10))
    path.write_bytes(b'not an image')
    assert fetch(client, broken, 640).data == b'not an image'
    huge, path = picture(pair, 'huge.png', (900, 900))
    decoded = []
    real = Image.Image.load
    monkeypatch.setattr(Image.Image, 'load', lambda self, *a: decoded.append(1) or real(self, *a))
    monkeypatch.setattr(thumbnails, 'MAX_PIXELS', 1000)
    assert fetch(client, huge, 320).data == path.read_bytes()
    assert decoded == []                                    # refused from the header, nothing decoded
    assert not list((pair.parent / 'data/thumbs').glob('*')) if (pair.parent / 'data/thumbs').exists() else True


def test_pregenerate_builds_both_widths(pair):
    picture(pair, 'a.png', (700, 700))
    picture(pair, 'b.png', (200, 200))
    assert thumbnails.pregenerate(pair) == 2
    assert len(list((pair.parent / 'data/thumbs').iterdir())) == 2


def test_tile_templates_render_srcset_and_keep_the_original_for_the_lightbox(app4, pair):
    identifier, _ = picture(pair)
    with closing(connect(pair)) as db:
        item = db.execute('SELECT item_id FROM picture WHERE id=?', (identifier,)).fetchone()[0]
    client = logged_in(app4)
    base = f'/manage/images/{identifier}'
    found = {}
    for url in (f'/collection/item/{item}',):
        html = client.get(url).get_data(as_text=True)
        for tag in BeautifulSoup(html, 'html.parser').select('#content img'):
            if base in (tag.get('src') or ''):
                found[url] = found.get(url, 0) + 1
                assert tag['src'] == base + '?w=320'
                assert tag['srcset'] == f'{base}?w=320 320w, {base}?w=640 640w'
                assert tag['sizes'] and tag['data-full'] == base
    assert found == {f'/collection/item/{item}': 1}


def test_lightbox_script_opens_the_original():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'static/web/toni'
    assert "link.dataset.full||link.currentSrc" in (root / 'images.js').read_text()
    assert "dataset.bwLightbox" in (root / 'bw-collection.js').read_text()
    assert ".src=button.dataset.bwLightbox" not in (root / 'bw-collection.js').read_text()


def test_picture_attributes_cost_no_queries(app4, monkeypatch):
    from brickwork.core import admin
    monkeypatch.setattr(admin, 'database', lambda *a, **k: (_ for _ in ()).throw(AssertionError('query')))
    with app4.test_request_context('/'):
        attrs = app4.jinja_env.globals['bw_picture_attrs'](7, '96px')
    assert 'src="/manage/images/7?w=320"' in attrs and 'sizes="96px"' in attrs and 'data-full="/manage/images/7"' in attrs


def test_no_template_img_tag_points_at_the_full_size_route():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'templates').rglob('*.html'):
        for tag in re.findall(r'<img [^>]*>', path.read_text()):
            assert "url_for('web.bw_image'" not in tag, (path.name, tag[:80])
    used = [p.name for p in (root / 'templates').rglob('*.html') if 'bw_picture_attrs' in p.read_text()]
    assert {'bw_checker.html', 'bw_workbench.html', 'bw_planning.html', 'bw_storage.html', 'bw_ledger_macros.html', 'collection_modules.html'} <= set(used)


def test_miss_serves_the_original_and_schedules_one_job_without_resizing(app4, pair, monkeypatch):
    identifier, original = picture(pair)
    client = logged_in(app4)
    jobs = []
    monkeypatch.setattr(thumbnails, '_spawn', jobs.append)
    calls = []
    real = thumbnails._render
    monkeypatch.setattr(thumbnails, '_render', lambda *a: calls.append(a) or real(*a))
    first = get_once(client, identifier, 320)
    assert first.status_code == 200 and first.data == original.read_bytes()
    assert 'private' in first.headers['Cache-Control'] and 'max-age=86400' in first.headers['Cache-Control']
    assert len(jobs) == 1 and calls == []                  # request path never rendered
    assert get_once(client, identifier, 320).data == original.read_bytes() and len(jobs) == 1   # deduplicated
    get_once(client, identifier, 640)
    assert len(jobs) == 2                                  # another width is its own key
    jobs[0]()                                              # the job runs off-path
    assert len(calls) == 1 and len(thumbnails._pending) == 1     # only the 640 job is still queued
    second = get_once(client, identifier, 320)
    assert Image.open(BytesIO(second.data)).size == (320, 240) and second.data != original.read_bytes()


def test_concurrent_misses_schedule_one_job(app4, pair, monkeypatch):
    identifier, _ = picture(pair)
    jobs = []
    monkeypatch.setattr(thumbnails, '_spawn', jobs.append)
    results = []
    def request():
        results.append(get_once(logged_in(app4), identifier, 320).status_code)
    threads = [threading.Thread(target=request) for _ in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert results == [200] * 8 and len(jobs) == 1


def test_failed_generation_is_logged_once_and_not_retried(app4, pair, monkeypatch, caplog):
    identifier, original = picture(pair)
    client = logged_in(app4)
    jobs = []
    monkeypatch.setattr(thumbnails, '_spawn', jobs.append)
    monkeypatch.setattr(thumbnails, 'get', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    get_once(client, identifier, 320)
    jobs[0]()
    assert get_once(client, identifier, 320).data == original.read_bytes()
    assert len(jobs) == 1 and sum('could not be generated' in r.message for r in caplog.records) == 1
