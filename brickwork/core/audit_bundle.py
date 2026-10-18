"""Bundle existing core receipts into one API event without changing web audit."""
from contextlib import contextmanager
from contextvars import ContextVar

CAPTURE = ContextVar('api_audit_bundle', default=None)


@contextmanager
def capture():
    values=[]
    token=CAPTURE.set(values)
    try: yield values
    finally: CAPTURE.reset(token)


def latest(entity):
    return next(r for r in reversed(CAPTURE.get() or []) if r['entity']==entity)
