"""Parsing and dispatch use mocks: no command can reach a source client."""
from contextlib import nullcontext
import json
from unittest.mock import Mock

import pytest

from brickwork.web import cli

# argv, service, exact service arguments.
CASES = [
    (['setup'], 'setup', {}),
    (['check'], 'brickwork_check', {}),
    (['catalogue', 'status'], 'catalogue_status', {}),
    (['catalogue', 'import', 'bricklink', '--from', 'DIR'], 'catalogue_import_bricklink', {'directory': 'DIR'}),
    (['prices', 'refresh', '6081-1'], 'prices_refresh', {'set_num': '6081-1'}),
    (['settings', 'show'], 'settings_show', {}),
    (['settings', 'set', 'incomplete_discount_pct', '40'], 'settings_set',
     {'key': 'incomplete_discount_pct', 'value': '40'}),
    (['sources', 'status'], 'sources_status', {}),
    (['brickset', 'refresh'], 'brickset_refresh', {'sets': []}),
    (['brickset', 'refresh', '123-1', '456-1'], 'brickset_refresh', {'sets': ['123-1', '456-1']}),
    (['worker'], 'jobs_worker', {}),
]


@pytest.mark.parametrize('new,operation,kwargs', CASES)
def test_dispatch_and_json(new, operation, kwargs, monkeypatch, capsys):
    result = ({'app': {'integrity_check': ['ok'], 'foreign_key_check': []}} if operation == 'brickwork_check'
              else {'answer': ['ok', 1]})
    service = Mock(return_value=result)
    monkeypatch.setattr(cli.admin_ops, operation, service)
    monkeypatch.setattr(cli, 'application_context', lambda operation: nullcontext())
    for argv in (['--json', *new], [*new, '--json']):
        assert cli.main(argv) == 0
        service.assert_called_with(**kwargs)
        assert json.loads(capsys.readouterr().out) == result
    assert cli.main(new) == 0
    assert capsys.readouterr().out


@pytest.mark.parametrize('argv', [[], ['prices'], ['settings', 'set', 'secret', 'value'],
                                  ['catalogue', 'import', 'bricklink'], ['catalogue', 'import', 'brickset'],
                                  ['prices', 'due'], ['wanted', 'add', 'x'], ['owned', 'add', 'x'],
                                  ['collection', 'import', 'in.xml']])
def test_usage_errors_and_removed_commands(argv, monkeypatch):
    context = Mock(side_effect=AssertionError('must not initialize'))
    monkeypatch.setattr(cli, 'application_context', context)
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
    context.assert_not_called()


def test_migrate_is_gone_and_names_the_4_0_command(monkeypatch, capsys):
    # The old importer's `brickwork migrate` is removed on the 4.0 line (M.8a); it must not call its old service.
    monkeypatch.setattr(cli, 'application_context', Mock(side_effect=AssertionError('must not initialize')))
    service = Mock(side_effect=AssertionError('must not run'))
    monkeypatch.setattr(cli.admin_ops, 'migrate', service)
    assert cli.main(['migrate', '--app', 'app.db', '--extras', 'extras.db',
                     '--decisions', 'decisions.json', '--catalogue', 'DIR',
                     '--out', 'brickwork.db', '--report', 'REPORT', '--replace']) == 1
    service.assert_not_called()
    assert 'python -m brickwork.store4 migrate' in capsys.readouterr().err


def test_operation_error_and_secret(monkeypatch, capsys):
    from flask import Flask
    app = Flask('secret-test')
    app.config['REBRICKABLE_API_KEY'] = 'sensitive-api-value'
    monkeypatch.setattr(cli, 'application_context', lambda operation: app.app_context())
    monkeypatch.setattr(cli.admin_ops, 'prices_refresh', Mock(side_effect=ValueError('bad sensitive-api-value')))
    assert cli.main(['prices', 'refresh', '6081-1']) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'sensitive-api-value' not in output.err
    assert 'bad [set]' in output.err


def test_check_failed(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'application_context', lambda operation: nullcontext())
    monkeypatch.setattr(cli.admin_ops, 'brickwork_check', Mock(return_value={
        'app': {'integrity_check': ['ok'], 'foreign_key_check': [{'table': 'broken'}]}}))
    assert cli.main(['--json', 'check']) == 1
    assert json.loads(capsys.readouterr().out)['app']['foreign_key_check']


def test_failed_fetch_exit_code(monkeypatch, capsys):
    result = {'set_num': '6081-1', 'ok': False}
    monkeypatch.setattr(cli, 'application_context', lambda operation: nullcontext())
    monkeypatch.setattr(cli.admin_ops, 'prices_refresh', Mock(return_value=result))
    assert cli.main(['--json', 'prices', 'refresh', '6081-1']) == 1
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize('new,operation,kwargs', CASES)
def test_service_exception_exit_code(new, operation, kwargs, monkeypatch, capsys):
    from flask import Flask
    app = Flask('operation-error-test')
    monkeypatch.setattr(cli, 'application_context', lambda operation: app.app_context())
    monkeypatch.setattr(cli.admin_ops, operation, Mock(side_effect=ValueError('operation failed')))
    assert cli.main(new) == 1
    assert capsys.readouterr().err == 'Web error: operation failed\n'


def test_json_between_groups(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'application_context', lambda operation: nullcontext())
    monkeypatch.setattr(cli.admin_ops, 'catalogue_import_bricklink', Mock(return_value={'loaded': True}))
    for argv in (['catalogue', '--json', 'import', 'bricklink', '--from', 'DIR'],
                 ['catalogue', 'import', '--json', 'bricklink', '--from', 'DIR']):
        assert cli.main(argv) == 0
        assert json.loads(capsys.readouterr().out) == {'loaded': True}


def test_executable_entry_points():
    from pathlib import Path
    import os
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'])
    for command in ([str(root / 'bin/brickwork'), 'migrate'],
                    [sys.executable, '-m', 'brickwork.web', 'migrate'],
                    [sys.executable, '-m', 'brickwork.web.cli', 'migrate']):
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == 2
        assert result.stdout == ''
        assert 'the following arguments are required' in result.stderr


def test_bw_key_redaction(monkeypatch, capsys):
    from flask import Flask
    app = Flask('bw-secret')
    monkeypatch.setattr(cli, 'application_context', lambda _: app.app_context())
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'bw-secret-value')
    monkeypatch.setattr(cli.admin_ops, 'brickset_refresh', Mock(side_effect=ValueError('bad bw-secret-value')))
    assert cli.main(['brickset', 'refresh', '123-1']) == 1
    assert 'bw-secret-value' not in capsys.readouterr().err


def test_import_jobs_cli_arguments(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'application_context', lambda _: nullcontext())
    run = Mock(return_value={'id': 42, 'state': 'done'})
    monkeypatch.setattr(cli.admin_ops, 'import_item', run)
    assert cli.main(['--json', 'import', 'P', 'synthetic-p']) == 0
    run.assert_called_once_with(item_type='P', item_no='synthetic-p')
    listed = Mock(return_value=[])
    monkeypatch.setattr(cli.admin_ops, 'jobs_list', listed)
    assert cli.main(['jobs', '--failed']) == 0
    listed.assert_called_once_with(failed=True)
    retry = Mock(return_value={'id': 42, 'state': 'waiting_for_budget'})
    monkeypatch.setattr(cli.admin_ops, 'jobs_retry', retry)
    assert cli.main(['--json', 'jobs', 'retry', '42', 'pictures']) == 0
    retry.assert_called_once_with(job=42, step='pictures')
    run.return_value = {'state': 'failed'}
    assert cli.main(['import', 'S', '123-1']) == 1
    assert callable(run.call_args.kwargs['progress'])
