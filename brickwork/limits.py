"""Request body limits, checked before a body is read (#62).

Werkzeug refuses a body over `request.max_content_length` with 413 before parsing it, so a large upload
never reaches a temp file or memory first. The route's own size checks (8 MB photos for identification,
15 MB photos, 20 MB PDFs, the database import) stay as the exact limits; these caps sit just above them.
"""
import os

from flask import request
from werkzeug.exceptions import RequestEntityTooLarge

MB = 1024 * 1024
FRAMING = MB  # multipart boundaries and form fields around the file
JSON_LIMIT = 4 * MB  # every non-multipart body: JSON, forms, pasted order text
IDENTIFICATION_LIMIT = 8 * MB + FRAMING  # API and browser photo identification


def upload_limit():
    """The largest legitimate body: the database import (BW_IMPORT_MAX_MB, default 200) plus framing."""
    return int(os.environ.get('BW_IMPORT_MAX_MB', '200')) * MB + FRAMING


# Multipart uploads: the route's own file limit plus framing. First match wins; the rest get the import limit.
UPLOADS = (
    (lambda p: p.endswith('/identifications') or p == '/workbench/part-to-inventory/detect', 8),
    (lambda p: p == '/manage/add/review', 8),  # photo mode; the list-file mode checks its 2 MB itself
    (lambda p: p.startswith('/workbench/orders/action/'), 1),
    (lambda p: p.endswith('/photos') or p.startswith('/collection/save/'), 15),
    (lambda p: p.endswith('/instruction-files') or p.startswith('/manage/') and not p.startswith('/manage/import-legacy'), 20),
)


def body_limit():
    if request.mimetype != 'multipart/form-data':
        return JSON_LIMIT
    path = request.path.rstrip('/')
    for match, megabytes in UPLOADS:
        if match(path):
            return megabytes * MB + FRAMING
    return upload_limit()


def install(app):
    """Set the global cap and the per-request caps once per app."""
    if app.extensions.get('bw_body_limits'):
        return
    app.extensions['bw_body_limits'] = True
    if app.config.get('MAX_CONTENT_LENGTH') is None:
        app.config['MAX_CONTENT_LENGTH'] = upload_limit()

    @app.before_request
    def bounded_body():
        limit = min(body_limit(), app.config['MAX_CONTENT_LENGTH'] or upload_limit())
        # A declared length over the cap is refused before any handler looks at the request; a body sent
        # without a length (chunked) is cut off by Werkzeug at the same cap while it is read.
        if request.content_length is not None and request.content_length > limit:
            raise RequestEntityTooLarge()
        request.max_content_length = limit
