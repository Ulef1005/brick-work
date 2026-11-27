"""Portable Brick Work export zip endpoint (ADR 0040, #524)."""
from flask import Response, request

from ..core import errors, own_export
from ..core.sources.base import day_of
from . import route
from .read import arguments, reading


@route('/export/brickwork.zip')
@reading
def get_export_brickwork_zip(db):
    arguments()
    values = request.args.getlist('sections')
    if len(values) > 1:
        raise errors.ValidationFailed('sections may not repeat')
    sections = values[0] if values else None
    result = own_export.build(db, sections=sections)
    total = sum(result['counts'].values())
    return Response(
        result['content'],
        mimetype='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename=brickwork-export-{day_of()}.zip',
            'X-Brickwork-Exported': str(total),
        },
    )
