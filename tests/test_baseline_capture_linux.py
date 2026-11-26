"""#503: the screen gate's references are Linux renders (ADR 0022), so `capture` writes none anywhere else. In its own file because
tests/test_screen_gate.py is not part of the check."""
import pytest

from scripts import screen_gate as gate


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_capture_writes_no_baseline_off_linux(platform, monkeypatch, capsys):
    monkeypatch.setattr(gate.sys, 'platform', platform)
    monkeypatch.setattr(gate, 'load', lambda: pytest.fail('the states were read'))
    monkeypatch.setattr(gate, 'render', lambda *a, **k: pytest.fail('a render was started'))
    assert gate.capture([], 'chrome') == 2
    assert 'Linux only' in capsys.readouterr().out


def test_capture_renders_on_linux(monkeypatch):
    seen = []
    monkeypatch.setattr(gate.sys, 'platform', 'linux')
    monkeypatch.setattr(gate, 'render', lambda entries, out_for, chrome: seen.append(chrome) or [])
    assert gate.capture(['no-such-screen'], 'chrome') == 0 and seen == ['chrome']
