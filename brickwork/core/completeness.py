"""The shared derived-copy completeness rule; callers own writes and receipts."""


def derived_state(db, copy_id):
    row = db.execute('SELECT completeness_source FROM copies WHERE id=?', (copy_id,)).fetchone()
    if not row or row['completeness_source'] != 'derived':
        return None
    checked = db.execute("""SELECT 1 FROM item_flags f JOIN flags s ON s.id=f.flag_id AND s.archived_at IS NULL
        WHERE f.entity_type='copy' AND f.entity_id=? AND s.kind='status'
        AND s.name='Set is checked'""", (copy_id,)).fetchone()
    # 4.8a: figure component rows and spares are not part of the set; a missing
    # whole figure still counts (copy_minifigs).
    defects = db.execute('''SELECT 1 FROM copy_parts WHERE copy_id=? AND coalesce(spare,0)=0 AND parent_minifig IS NULL
        AND (coalesce(missing,0)>0 OR coalesce(damaged,0)>0)
        UNION ALL SELECT 1 FROM copy_minifigs WHERE copy_id=? AND coalesce(missing,0)>0''',
        (copy_id, copy_id)).fetchone()
    return 'C' if checked and not defects else 'I'
