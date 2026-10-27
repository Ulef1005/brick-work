"""Speed fixes of the API (the secret list read once per response): split out of test_bw_perf.py by M.8f, waiting for M.11."""
import pytest

from brickwork.core import secrets
from brickwork.core.sources import base


def test_api_public_reads_the_secret_list_once_per_response(monkeypatch):
    from brickwork.api import serializers
    calls = []
    monkeypatch.setattr(secrets, 'secret_values', lambda: calls.append(1) or [])
    rows = [{'id': str(i), 'name': f'Shelf {i}'} for i in range(40)]
    serializers.public(rows, ['Storage'])
    assert len(calls) == 1


def test_api_serialize_reads_the_secret_list_once(monkeypatch):
    monkeypatch.setenv('BW_FIXTURE_KEY', 'swordfish-123456')
    calls = []
    real = secrets.secret_values
    monkeypatch.setattr(secrets, 'secret_values', lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(base, 'secret_values', secrets.secret_values)
    from brickwork.core import api_reads
    monkeypatch.setattr(api_reads, 'secret_values', secrets.secret_values)
    out = api_reads.serialize({'rows': [{'name': 'swordfish-123456'} for _ in range(50)]})
    assert len(calls) == 1 and out['rows'][0]['name'] == '[set]'
