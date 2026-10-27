"""#68: the Collection sync pages before setup. Split off from test_bw_small_68.py by M.8i part 1, which ports the rest; the sync pages are M.8j's
(still the 3.3 text)."""
import pytest

from tests.web_fixtures import app, apps, logged_in  # noqa: F401


@pytest.mark.parametrize('path', ['/manage/sync', '/manage/sync/rebrickable/link'])
def test_pages_before_setup_show_the_notice(app, path, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'not-set-up' / 'brickwork.db'))
    response = logged_in(app).get(path)
    assert response.status_code == 503
    assert 'database is not available' in response.get_data(as_text=True)
