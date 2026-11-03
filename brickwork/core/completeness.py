"""The shared derived-copy completeness rule; callers own writes and receipts."""
from ..store4 import copies


# User docs: docs/reference/metrics.md#completeness
def derived_state(db, copy_id):
    """`complete` or `incomplete` for a copy whose completeness is derived, else None: the 4.0 rule is `store4.copies`'s
    (live, non-spare, non-figure lines; retired lines are no lines)."""
    return copies.derived_completeness(db, copy_id)
