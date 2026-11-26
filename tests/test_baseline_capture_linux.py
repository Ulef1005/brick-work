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


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_the_command_refuses_before_it_looks_for_chrome(platform, monkeypatch, capsys):
    monkeypatch.setattr(gate.sys, 'platform', platform)
    monkeypatch.setattr(gate.subprocess, 'run', lambda *a, **k: pytest.fail('chrome.py was started'))
    assert gate.main(['capture']) == 2
    assert 'Linux only' in capsys.readouterr().out


def test_capture_renders_a_state_not_yet_approved_on_linux(monkeypatch):
    seen = []
    states = {'states': [{'screen': '09-Collection', 'section': 'x', 'state': '', 'built': True, 'approved': False}]}
    monkeypatch.setattr(gate.sys, 'platform', 'linux')
    monkeypatch.setattr(gate, 'load', lambda: states)
    monkeypatch.setattr(gate, 'render', lambda entries, out_for, chrome: seen.append(entries) or [])
    assert gate.capture(['09'], 'chrome') == 0 and seen == [states['states']]
