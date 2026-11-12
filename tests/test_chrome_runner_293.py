"""The Chrome runner's start and retry logic (#293), tested with fake browsers: no Chrome is needed, only node (the CDP launcher) and a shell.

scripts/chrome_launch.cjs starts Chrome for the CDP harnesses (the screen gate's capture_screens.cjs, the tests/toni_*.cjs); scripts/chrome.py's
dump_dom() runs `chrome --headless=new --dump-dom` for the rendered tests. On macOS under load a start prints its `DevTools listening` line and then
stalls, never prints it, or ends in `Teardown watchdog expired`; both retry the whole launch with a fresh profile. The fake browsers behave like that."""
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from scripts import chrome as chrome_tool
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]
NOISE = 'CVDisplayLinkCreateWithCGDisplay failed. CVReturn: -6670'

FAKE_NODE = r"""#!/usr/bin/env node
const fs=require('node:fs'),http=require('node:http');
const mode=process.env.FAKE_MODE, count=process.env.FAKE_COUNT;
fs.appendFileSync(count,'x');
const attempt=fs.readFileSync(count,'utf8').length;
process.stderr.write('[0101/000000.000000:ERROR:ui/display/mac/cv_display_link_mac.mm:188] %s\n');
if(mode==='silent'){process.stderr.write('something went wrong in attempt '+attempt+'\n');setInterval(()=>{},1000);}
else if(mode==='line-then-stall'&&attempt===1){process.stderr.write('DevTools listening on ws://127.0.0.1:1/devtools/browser/dead\n');setInterval(()=>{},1000);}   // port 1: nothing answers
else{
 const server=http.createServer((req,res)=>{res.end(JSON.stringify([{type:'page',webSocketDebuggerUrl:'ws://127.0.0.1/page'}]));});
 server.listen(0,'127.0.0.1',()=>process.stderr.write('DevTools listening on ws://127.0.0.1:'+server.address().port+'/devtools/browser/abc\n'));   // no DevToolsActivePort file is written
}
""" % NOISE

DRIVER = """
const {launch}=require(%r);
(async()=>{
 const b=await launch(process.argv[2]);
 console.log(JSON.stringify({port:b.port,profile:b.profile}));
 await b.stop();
})().catch(e=>{console.error(e.message);process.exit(1);});
"""


def run_launcher(tmp_path, monkeypatch, mode):
    node = rendered.need_node()
    fake = tmp_path / 'fake-chrome'
    fake.write_text(FAKE_NODE.replace('#!/usr/bin/env node', f'#!{node}'))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    driver = tmp_path / 'driver.cjs'
    driver.write_text(DRIVER % str(ROOT / 'scripts' / 'chrome_launch.cjs'))
    count = tmp_path / 'count'
    env = dict(os.environ, FAKE_MODE=mode, FAKE_COUNT=str(count), BW_CHROME_START_MS='800', BW_CHROME_ATTEMPTS='3')
    result = subprocess.run([node, str(driver), str(fake)], capture_output=True, text=True, timeout=60, env=env)
    return result, len(count.read_text()) if count.exists() else 0


def test_a_printed_devtools_line_counts_as_started_without_the_port_file(tmp_path, monkeypatch):
    result, starts = run_launcher(tmp_path, monkeypatch, 'ok')
    assert result.returncode == 0, result.stderr
    assert starts == 1                                           # started once: the Linux path is one launch, as before
    assert json.loads(result.stdout)['port'].isdigit()


def test_a_start_that_prints_the_line_and_then_stalls_is_launched_again(tmp_path, monkeypatch):
    result, starts = run_launcher(tmp_path, monkeypatch, 'line-then-stall')
    assert result.returncode == 0, result.stderr
    assert starts == 2                                           # the stalled process was killed, a second one started
    profile = json.loads(result.stdout)['profile']
    assert not Path(profile).exists()                            # stop() removed it


def test_a_start_that_never_prints_fails_after_all_attempts_with_the_last_stderr_lines(tmp_path, monkeypatch):
    result, starts = run_launcher(tmp_path, monkeypatch, 'silent')
    assert result.returncode == 1
    assert starts == 3
    assert 'Chrome did not start after 3 attempts' in result.stderr
    assert 'something went wrong in attempt 3' in result.stderr  # the last attempt's stderr is shown
    assert 'CVDisplayLink' not in result.stderr                  # the macOS noise line is not


def test_attempts_and_the_start_wait_can_be_set(tmp_path, monkeypatch):
    source = (ROOT / 'scripts' / 'chrome_launch.cjs').read_text()
    assert 'BW_CHROME_ATTEMPTS' in source and 'BW_CHROME_START_MS' in source and '||30000' in source and '||3,' in source


FAKE_SH = """#!/bin/bash
count="$FAKE_COUNT"; echo x >> "$count"; n=$(wc -l < "$count" | tr -d " ")
echo '[0101/000000.000000:ERROR:ui/display/mac/cv_display_link_mac.mm:188] %s' >&2
case "$FAKE_MODE" in
 ok) echo '<html>dom</html>';;
 flaky) if [ "$n" -lt 3 ]; then echo 'Teardown watchdog expired; recording dump and terminating.' >&2; exit 2; fi; echo '<html>dom</html>';;
 stall) if [ "$n" -lt 3 ]; then sleep 30; fi; echo '<html>dom</html>';;
 dead) echo "failure number $n" >&2; echo '<html>half</html>'; exit 2;;
esac
""" % NOISE


def fake_dump(tmp_path, monkeypatch, mode):
    fake = tmp_path / 'fake-chrome.sh'
    fake.write_text(FAKE_SH)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv('FAKE_MODE', mode)
    monkeypatch.setenv('FAKE_COUNT', str(tmp_path / 'count'))
    monkeypatch.setattr(chrome_tool.time, 'sleep', lambda s: None)
    return str(fake)


def starts(tmp_path):
    return len((tmp_path / 'count').read_text().splitlines())


def test_dump_dom_returns_the_dom_of_a_clean_run_after_one_launch(tmp_path, monkeypatch):
    fake = fake_dump(tmp_path, monkeypatch, 'ok')
    assert chrome_tool.dump_dom(fake, 'file:///x.html') == '<html>dom</html>\n'
    assert starts(tmp_path) == 1


def test_dump_dom_runs_a_failed_launch_again(tmp_path, monkeypatch):
    fake = fake_dump(tmp_path, monkeypatch, 'flaky')
    assert chrome_tool.dump_dom(fake, 'file:///x.html') == '<html>dom</html>\n'
    assert starts(tmp_path) == 3                                  # the watchdog exit twice, the third run is fine


def test_dump_dom_kills_a_stalled_launch_at_the_timeout_and_runs_it_again(tmp_path, monkeypatch):
    fake = fake_dump(tmp_path, monkeypatch, 'stall')
    assert chrome_tool.dump_dom(fake, 'file:///x.html', timeout=1) == '<html>dom</html>\n'
    assert starts(tmp_path) == 3


def test_dump_dom_gives_up_with_the_reason_and_never_returns_the_dom_of_a_failed_run(tmp_path, monkeypatch):
    fake = fake_dump(tmp_path, monkeypatch, 'dead')
    with pytest.raises(RuntimeError) as error:
        chrome_tool.dump_dom(fake, 'file:///x.html')
    message = str(error.value)
    assert 'after 3 attempts' in message and 'exit 2' in message and 'failure number 3' in message
    assert 'CVDisplayLink' not in message
    assert starts(tmp_path) == 3


def test_dump_dom_passes_the_flags_the_tests_used_to(tmp_path, monkeypatch):
    calls = []
    real = subprocess.Popen
    monkeypatch.setattr(chrome_tool.subprocess, 'Popen', lambda command, **kw: calls.append(command) or real(['true'], **kw))
    chrome_tool.dump_dom('/bin/chrome', 'file:///x.html', budget_ms=3000)
    command = calls[0]
    assert command[:2] == ['/bin/chrome', '--headless=new'] and '--no-sandbox' in command and '--virtual-time-budget=3000' in command
    assert command[-2:] == ['--dump-dom', 'file:///x.html'] and any(c.startswith('--user-data-dir=') for c in command)


def test_the_headless_shell_is_only_an_opt_in_on_macos_and_never_the_gates_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(chrome_tool, 'explicit', lambda: None)
    monkeypatch.setattr(chrome_tool, 'pinned_cached', lambda: '/cache/chrome')
    monkeypatch.setattr(chrome_tool, 'shell_cached', lambda: '/cache/shell')
    monkeypatch.delenv('BW_CHROME_HEADLESS_SHELL', raising=False)
    monkeypatch.setattr(chrome_tool, 'platform_key', lambda: 'mac-arm64')
    assert chrome_tool.find(fetch=False) == ('/cache/chrome', 'pinned')            # off by default
    monkeypatch.setenv('BW_CHROME_HEADLESS_SHELL', '1')
    assert chrome_tool.find(fetch=False) == ('/cache/shell', 'shell')
    monkeypatch.setattr(chrome_tool, 'platform_key', lambda: 'linux64')            # Linux and CI keep the full Chrome whatever the variable says
    assert chrome_tool.find(fetch=False) == ('/cache/chrome', 'pinned')
    monkeypatch.setattr(chrome_tool, 'platform_key', lambda: 'mac-arm64')
    assert chrome_tool.main(['pinned']) == 0                                        # the gate's mode ignores the variable
