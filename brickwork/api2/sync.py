"""The collection sync and the BrickTracker import (M.11d, issue #113).

Sync (`core/sync`) compares the collection with a site's (Rebrickable, Brickset) in two steps, a plan and its apply. A plan reaches the
network and runs outside any transaction (`write(detached=True)`), writes nothing to the collection and expires after 24 hours; a pull apply
is one undoable write; a send apply makes the ticked remote calls (admin; remote changes are not undone). The BrickTracker import
(`core/importer/bricktracker.py`) takes an uploaded `app.db`, streamed to a private file that is deleted whatever happens, and answers a plan;
applying it writes the ticked rows in one transaction that Undo reverses (admin)."""
import sqlite3

from flask import current_app, jsonify

from ..core import errors, sync
from ..core.sync import part_lists
from ..core.importer import bricktracker
from ..core import own_import
from . import database, route
from .read import respond
from .writes import Done, write


def known(source):
    if source not in sync.SOURCES:
        raise errors.NotFound('Unknown sync source')
    return source


@route('/sync/<source>')
def get_sync_by_source(source):
    from .read import arguments
    arguments()
    return respond(sync.status(database(), known(source)))


@route('/sync/<source>/lists')
def get_sync_by_source_lists(source):
    from .read import arguments
    arguments()
    return respond(sync.lists(database(), known(source)))              # one remote call: no read snapshot is held while it runs


@route('/sync/<source>/link', 'PUT')
@write
def put_sync_by_source_link(db, body, source):
    return Done(sync.link(db, known(source), body))


@route('/sync/<source>/pull/plan', 'POST')
@write(detached=True)
def post_sync_by_source_pull_plan(db, body, source):
    return Done(sync.plan_pull(db, known(source)), status=201)


@route('/sync/<source>/send/plan', 'POST')
@write(detached=True)
def post_sync_by_source_send_plan(db, body, source):
    return Done(sync.plan_send(db, known(source)), status=201)


def plan_of(db, body, source, direction):
    plan = sync.load_plan(db, body['plan_id'], direction)
    if plan['source'] != source:
        raise errors.ValidationFailed('This plan belongs to another source')
    return plan


@route('/sync/<source>/pull/apply', 'POST')
@write
def post_sync_by_source_pull_apply(db, body, source):
    plan_of(db, body, known(source), 'pull')
    return Done(sync.apply_pull(db, body['plan_id'], body.get('ticked'), lost=body.get('lost_ticked'), picks=body.get('copy_picks'),
                                lists=body.get('list_choices')))


@route('/sync/<source>/send/apply', 'POST')
@write(detached=True)
def post_sync_by_source_send_apply(db, body, source):
    plan_of(db, body, known(source), 'send')
    return Done(sync.apply_send(db, body['plan_id'], body.get('ticked')))


# ---------- Rebrickable part lists into loose stock (#471) ----------

@route('/sync/rebrickable/parts/plan', 'POST')
@write(detached=True)
def post_sync_rebrickable_parts_plan(db, body):
    """Compare the chosen Rebrickable part lists with the loose parts in their lots; writes nothing, the plan expires after 24 hours."""
    return Done(part_lists.plan(db), status=201)


@route('/sync/rebrickable/parts/apply', 'POST')
@write
def post_sync_rebrickable_parts_apply(db, body):
    """Add the ticked rows' difference to loose stock in one transaction; `lots` puts a row into another live lot. Undo with POST /events/{id}/undo."""
    sync.load_plan(db, body['plan_id'], 'parts')
    return Done(part_lists.apply(db, body['plan_id'], body.get('ticked'), lots=body.get('lots')))


# ---------- the BrickTracker import ----------

@route('/imports/bricktracker', 'POST')
@write(detached=True)
def post_imports_bricktracker(db, body, content):
    """Plan an import from an uploaded BrickTracker database; nothing is written to the collection."""
    try:
        return Done(bricktracker.plan(db, content.path, name=content.name), status=201)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None


@route('/imports/<id>/apply', 'POST')
@write
def post_imports_by_id_apply(db, body, id):
    """Write the rows the plan marks add, in one transaction; the catalogue imports they queue start after the commit."""
    try:
        return Done(bricktracker.apply(db, id, body.get('decisions', {})))
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None


# ---------- the Brick Work own-file import (#524) ----------

@route('/imports/brickwork/plan', 'POST')
@write(detached=True)
def post_imports_brickwork_plan(db, body, content):
    """Plan an import from an uploaded Brick Work export zip; nothing is written to the collection."""
    plan = own_import.plan(db, content, sections=body.get('sections') or None)
    return Done({k: v for k, v in plan.items() if k != 'tables'}, status=201)


@route('/imports/brickwork/<plan_id>/apply', 'POST')
@write
def post_imports_brickwork_by_plan_id_apply(db, body, plan_id):
    """Write the rows the plan marks new, in one transaction; rows that differ are left alone. Undo with POST /events/{id}/undo (admin)."""
    try:
        return Done(own_import.apply(db, plan_id))
    except sqlite3.IntegrityError:
        current_app.logger.warning('own import apply refused by the store', exc_info=True)
        raise errors.ValidationFailed('The file holds a value this install does not accept') from None
