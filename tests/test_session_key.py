"""The browser session key file (a follow-up of the review of #59 to #64, ported from test_bw_review_followups in M.11c): a second starter reads the
first one's key, a loose mode is tightened, a damaged key is replaced and no half-written file is left behind."""
from brickwork.web.auth import session_key


def test_session_key_second_starter_reads_the_first_and_mode_is_tightened(tmp_path, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    first = session_key()
    key = tmp_path / 'session.key'
    key.chmod(0o644)
    assert session_key() == first and key.stat().st_mode & 0o777 == 0o600
    key.write_bytes(b'\xff\xfe')
    repaired = session_key()                                  # a damaged key is replaced, and the new one is kept
    assert len(repaired) >= 32 and session_key() == repaired
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('.session.key.')]
