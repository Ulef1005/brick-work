"""
Migration 0027: Consolidate metadata tables - remove FK constraints from set metadata tables

This migration removes foreign key constraints from bricktracker_set_owners, _tags, and _statuses
so they can accept any entity ID (sets, individual parts, individual minifigures, individual part lots).

Since these tables have dynamically added columns, we need to read the schema and recreate the tables
with all existing columns but without the foreign key constraints.
"""
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..sql import BrickSQL

logger = logging.getLogger(__name__)


def migration_0027(sql: 'BrickSQL') -> dict[str, Any]:
    """
    Remove foreign key constraints from set metadata junction tables.

    This allows the tables to store metadata for any entity type, not just sets.
    """

    tables_to_migrate = [
        'bricktracker_set_owners',
        'bricktracker_set_tags',
        'bricktracker_set_statuses'
    ]

    for table_name in tables_to_migrate:
        logger.info('Migrating {table_name} to remove foreign key constraint'.format(
            table_name=table_name
        ))

        # Get the current table schema
        cursor = sql.cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        # Build column definitions for new table (without FK constraint)
        column_defs = []
        column_names = []
        for col in columns:
            col_name = col[1]
            col_type = col[2]
            col_not_null = col[3]
            col_default = col[4]
            col_pk = col[5]

            column_names.append(f'"{col_name}"')

            col_def = f'"{col_name}" {col_type}'
            if col_pk:
                col_def += ' PRIMARY KEY'
            if col_not_null and not col_pk:
                if col_default is not None:
                    col_def += f' NOT NULL DEFAULT {col_default}'
                else:
                    col_def += ' NOT NULL'
            elif col_default is not None:
                col_def += f' DEFAULT {col_default}'

            column_defs.append(col_def)

        # Create new table without foreign key constraint
        new_table_name = f'{table_name}_new'
        create_sql = f'CREATE TABLE "{new_table_name}" ({", ".join(column_defs)})'
        logger.debug('Creating new table: {sql}'.format(sql=create_sql))
        sql.cursor.execute(create_sql)

        # Copy all data
        column_list = ', '.join(column_names)
        copy_sql = f'INSERT INTO "{new_table_name}" ({column_list}) SELECT {column_list} FROM "{table_name}"'
        logger.debug('Copying data: {sql}'.format(sql=copy_sql))
        sql.cursor.execute(copy_sql)

        # Drop old table
        sql.cursor.execute(f'DROP TABLE "{table_name}"')

        # Rename new table to old name
        sql.cursor.execute(f'ALTER TABLE "{new_table_name}" RENAME TO "{table_name}"')

        logger.info('Successfully migrated {table_name}'.format(table_name=table_name))

    logger.info('Migration 0027 complete - all set metadata tables now accept any entity ID')

    return {}
