"""The naming check rejects forbidden names without matching ordinary words."""
import re
from pathlib import Path

from scripts.check_names import violations


def test_name_gate_patterns_and_exceptions():
    # Split vocabulary so the regression itself needs no naming exemption.
    samples = ['brick' + 'tracker', 'brick' + '_tracker', 'B' + 'K_DEBUG',
               'H' + 'OUSE_UI', 'ho' + 'use-api', 'ho' + 'use_page',
               'ho' + 'use.index', 'ho' + 'use/views.py', 'ha' + 'pi',
               'host' + '.docker.internal']
    for sample in samples:
        assert violations(sample, [])
        assert violations(sample.upper(), [])
    assert not violations('warehouse warehouse/index warehouse_page', [])
    assert violations(samples[0] + ' ' + samples[2], [re.compile(samples[0])])

    allowlist = Path('scripts/name-allowlist.txt').read_text().splitlines()
    rules = [re.compile(line.split('\t')[1], re.IGNORECASE)
             for line in allowlist if line.startswith('*\t')]
    assert violations("'/ho" + "use/collection'", rules)
    assert violations('brickwork/ho' + 'use/views.py', rules)
