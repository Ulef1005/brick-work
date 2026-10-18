"""Collection sync transport (#10): credentials, link, pull and send for Rebrickable and Brickset.

Plans and sends need the network and run outside any transaction (`detached`); a pull apply is one
undoable write (`execute`). The connect body holds a password: replay compares a keyed fingerprint,
and the password is never stored, logged, echoed or returned.
"""
from flask import jsonify

from . import api, database
from .operations import answer, json_input, no_input, run
from .serializers import public
from ..core import api_writes as service, errors, secrets, sync


def _known(source):
    if source not in sync.SOURCES:
        raise errors.NotFound('Unknown sync source')
    return source


@api.get('/sync/<source>')
def get_sync_by_source(source):
    no_input()
    return jsonify(data=public(sync.status(database(), _known(source)), 'SyncStatus'))


@api.get('/sync/<source>/lists')
def get_sync_by_source_lists(source):
    no_input()
    return jsonify(data=public(sync.lists(database(), _known(source)), ['SyncList']))


@api.put('/sync/<source>/link')
def put_sync_by_source_link(source):
    data = json_input()
    _known(source)
    return answer(run(service.execute, dict(data, source=source),
                      lambda: (sync.link(database(), source, data), 200), 'SyncStatus'))


@api.post('/sync/<source>/pull/plan')
def post_sync_by_source_pull_plan(source):
    no_input()
    _known(source)
    return answer(run(service.detached, {'source': source}, lambda: (sync.plan_pull(database(), source), 201), 'SyncPlan'))


@api.post('/sync/<source>/pull/apply')
def post_sync_by_source_pull_apply(source):
    data = _apply_input(source)

    def action():
        return sync.apply_pull(database(), data['plan_id'], data.get('ticked')), 200
    return answer(run(service.execute, dict(data, source=source), action, 'SyncApplied'))


@api.post('/sync/<source>/send/plan')
def post_sync_by_source_send_plan(source):
    no_input()
    _known(source)
    return answer(run(service.detached, {'source': source}, lambda: (sync.plan_send(database(), source), 201), 'SyncPlan'))


@api.post('/sync/<source>/send/apply')
def post_sync_by_source_send_apply(source):
    data = _apply_input(source)

    def action():
        return sync.apply_send(database(), data['plan_id'], data.get('ticked')), 200
    return answer(run(service.detached, dict(data, source=source), action, 'SyncSent'))


def _apply_input(source):
    _known(source)
    data = json_input()
    if set(data) - {'plan_id', 'ticked'} or not isinstance(data.get('plan_id'), str):
        raise errors.ValidationFailed('Send {"plan_id": …, "ticked": [row keys]}')
    plan = sync.load_plan(database(), data['plan_id'])
    if plan['source'] != source:
        raise errors.ValidationFailed('This plan belongs to another source')
    return data


# Credentials: one-time connect (username + password sent straight to the site) or a pasted token/hash.

@api.post('/sources/<source>/user/connect')
def post_sources_source_user_connect(source):
    _known(source)
    data = json_input()
    if set(data) != {'username', 'password'}:
        raise errors.ValidationFailed('Supply username and password')
    secrets.remember(data['password'] if isinstance(data['password'], str) else '')
    body = dict(source=source, fingerprint=secrets.fingerprint(data))

    def action():
        return sync.connect(database(), source, data['username'], data['password']), 200
    return answer(run(service.detached, body, action, 'SyncCredentials'))


@api.put('/sources/<source>/user')
def put_sources_source_user(source):
    _known(source)
    data = json_input()
    if set(data) != {'value'}:
        raise errors.ValidationFailed('Supply value')
    body = dict(source=source, fingerprint=secrets.fingerprint(data))
    return answer(run(service.execute, body, lambda: (sync.paste(database(), source, data['value']), 200), 'SyncCredentials'))


@api.delete('/sources/<source>/user')
def delete_sources_source_user(source):
    _known(source)
    no_input()
    return answer(run(service.execute, {'source': source}, lambda: (sync.remove(database(), source), 200), 'SyncCredentials'))


@api.post('/sources/<source>/user/test')
def post_sources_source_user_test(source):
    _known(source)
    no_input()
    return answer(run(service.detached, {'source': source}, lambda: (sync.test(database(), source), 200), 'KeyTest'))
