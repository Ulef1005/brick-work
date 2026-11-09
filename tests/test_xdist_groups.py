"""The xdist group keeps its tests on one worker (tests/xdist_groups.py, #254): `--dist loadgroup` is how the Chrome and screen-gate tests avoid each other."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = '''
import os
import pytest

@pytest.mark.xdist_group('shared')
@pytest.mark.parametrize('i', range(8))
def test_in_the_group(i):
    open(os.environ['SAMPLE_OUT'], 'a').write(os.environ['PYTEST_XDIST_WORKER'] + '\\n')   # worker output is not shown under xdist

@pytest.mark.parametrize('i', range(8))
def test_outside_the_group(i):
    pass
'''


def test_the_tests_of_one_group_run_on_one_worker(tmp_path):
    (tmp_path / 'test_sample.py').write_text(SAMPLE)
    out = tmp_path / 'workers.txt'
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-n', '3', '--dist', 'loadgroup', '-p', 'tests.xdist_groups', '-p', 'no:cacheprovider',
                             '--rootdir', str(tmp_path), str(tmp_path / 'test_sample.py')],
                            capture_output=True, text=True, cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT), 'SAMPLE_OUT': str(out)})
    assert '16 passed' in result.stdout, result.stdout + result.stderr
    assert len(out.read_text().split()) == 8 and len(set(out.read_text().split())) == 1, out.read_text()
