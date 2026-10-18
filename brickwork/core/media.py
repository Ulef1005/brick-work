"""Where pictures and PDFs live (#27): BW_MEDIA_PATH, or by default the folder that holds the database.

Stored paths stay relative ("data/images/...", "data/instructions/...", "data/thumbs/...",
"data/identifications/..."), so moving the media means moving that data/ tree to the media folder;
nothing in the database changes. The database, the BrickLink catalogue and import or sync plans stay
beside the database. Every writer and every serving route resolves files through media_root() and
keeps its is_relative_to check against it.
"""
import os
from pathlib import Path


def store_dir(db):
    return Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve().parent


def root_for(database_path):
    """The media root for a database file path."""
    configured = os.environ.get('BW_MEDIA_PATH', '').strip()
    return Path(configured).expanduser().resolve() if configured else Path(database_path).resolve().parent


def media_root(db):
    return root_for(db.execute('PRAGMA database_list').fetchone()[2])
