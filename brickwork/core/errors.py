"""Stable domain failures and their transport status, independent of Flask."""
from types import MappingProxyType

HTTP_STATUS = MappingProxyType({
    'bad_request': 400, 'unknown_filter': 400, 'unauthorized': 401,
    'forbidden': 403, 'read_only_instance': 403, 'not_found': 404,
    'method_not_allowed': 405,
    'archived': 409, 'conflict': 409, 'stale_match': 409, 'undo_blocked': 409,
    'not_undoable': 409, 'idempotency_conflict': 409, 'precondition_failed': 412,
    'payload_too_large': 413, 'unsupported_media_type': 415,
    'validation_failed': 422, 'unsupported_setting': 422,
    'source_not_configured': 424, 'source_disabled': 424, 'catalogue_not_loaded': 424,
    'idempotency_key_required': 428, 'budget_exhausted': 429, 'source_throttled': 429, 'too_many_attempts': 429,
    'source_error': 502, 'not_set_up': 503, 'api_disabled': 503,
    'db_unavailable': 503, 'internal_error': 500,
})


class BrickWorkError(ValueError):
    """A public failure with a stable code; detail must never contain credentials."""
    code = 'validation_failed'

    def __init__(self, detail=None, **context):
        super().__init__(detail or self.code.replace('_', ' ').capitalize())
        self.context = context

    @property
    def status(self):
        return HTTP_STATUS[self.code]


# One typed exception per public code, all sharing the single status table.
for _code in HTTP_STATUS:
    _name = ''.join(word.capitalize() for word in _code.split('_'))
    globals()[_name] = type(_name, (BrickWorkError,), {'code': _code, '__module__': __name__})
del _code, _name
