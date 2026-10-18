from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..sql import BrickSQL


# Grab the list of checkboxes to create a list of SQL columns
def migration_0007(sql: 'BrickSQL', /) -> dict[str, Any]:
    # Don't realy on sql files as they could be removed in the future
    sql.cursor.execute('SELECT "bricktracker_set_checkboxes"."id" FROM "bricktracker_set_checkboxes"')  # noqa: E501
    records = sql.cursor.fetchall()

    return {
        'sources': ', '.join([
            '"bricktracker_set_statuses_old"."status_{id}"'.format(id=record['id'])  # noqa: E501
            for record
            in records
        ]),
        'targets': ', '.join([
            '"status_{id}"'.format(id=record['id'])
            for record
            in records
        ]),
        'structure': ', '.join([
            '"status_{id}" BOOLEAN NOT NULL DEFAULT 0'.format(id=record['id'])
            for record
            in records
        ])
    }
