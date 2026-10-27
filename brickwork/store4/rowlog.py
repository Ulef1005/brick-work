"""A before/after log of row changes that can be verified and put back exactly (M.8i part 2, issue #110; design 3.5, 3.6).

A merge, an unmerge and a kind move touch many tables. Each change is recorded as `{t: table, b: row before or None, a: row after or
None}`; a row is the dict of its stored columns (generated columns left out) plus `_rowid` for a table whose rowid is its key (an INTEGER PRIMARY KEY, or no
declared key at all; issue #124). `verify` says whether the
database still holds every `a` (and still lacks every deleted row), which is the "nothing moved since" test of Undo; `restore` puts
the `b` rows back in the reverse order, byte for byte. The log is plain JSON, so it is the receipt."""
from .errors import Store4Error


class RowLog:
    def __init__(self, db, changes=None):
        self.db = db
        self.changes = list(changes or [])
        self._cache = {}

    # ---- table facts
    def cols(self, table):
        if ('cols', table) not in self._cache:
            self._cache['cols', table] = [r['name'] for r in self.db.execute(f'PRAGMA main.table_xinfo("{table}")') if r['hidden'] == 0]
        return self._cache['cols', table]

    def has_rowid(self, table):
        if ('rowid', table) not in self._cache:
            sql = self.db.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            self._cache['rowid', table] = 'WITHOUT ROWID' not in sql.upper().replace('\n', ' ')
        return self._cache['rowid', table]

    def pk(self, table):
        if ('pk', table) not in self._cache:
            rows = sorted((r['pk'], r['name']) for r in self.db.execute(f'PRAGMA main.table_info("{table}")') if r['pk'])
            self._cache['pk', table] = [name for _, name in rows]
        return self._cache['pk', table]

    def rowid_key(self, table):
        """Is the rowid the row's real key? Yes for an INTEGER PRIMARY KEY (it is the rowid) and for a table with no declared key. A table
        with another declared key (a uuid, a composite) is located by that key: its hidden rowid is reused by SQLite after a delete and
        renumbered by VACUUM, so it says nothing about which row this is (issue #124)."""
        if ('rowid_key', table) not in self._cache:
            info = [r for r in self.db.execute(f'PRAGMA main.table_info("{table}")') if r['pk']]
            self._cache['rowid_key', table] = self.has_rowid(table) and (not info or (len(info) == 1 and info[0]['type'].upper() == 'INTEGER'))
        return self._cache['rowid_key', table]

    def locator(self, table, row):
        if self.rowid_key(table):
            return 'rowid=?', [row['_rowid']]
        pk = self.pk(table)
        return ' AND '.join(f'"{c}"=?' for c in pk), [row[c] for c in pk]

    def _same(self, table, found, expected):
        """Rows compare without a `_rowid` that is not the key (an older receipt carries one for every table with a rowid)."""
        if not self.rowid_key(table):
            expected = {k: v for k, v in expected.items() if k != '_rowid'}
        return found == expected

    # ---- reading
    def select(self, table, where='1', args=()):
        names = ', '.join(f'"{c}"' for c in self.cols(table))
        lead = 'rowid AS _rowid, ' if self.rowid_key(table) else ''
        return [dict(r) for r in self.db.execute(f'SELECT {lead}{names} FROM main."{table}" WHERE {where}', tuple(args))]

    def get(self, table, row):
        where, args = self.locator(table, row)
        found = self.select(table, where, args)
        return found[0] if found else None

    # ---- writing (each records its change)
    def update(self, table, row, **sets):
        where, args = self.locator(table, row)
        marks = ', '.join(f'"{k}"=?' for k in sets)
        self.db.execute(f'UPDATE main."{table}" SET {marks} WHERE {where}', (*sets.values(), *args))
        key = row if self.rowid_key(table) else {**row, **{c: sets[c] for c in self.pk(table) if c in sets}}
        after = self.get(table, key)
        if after is None:
            raise Store4Error(f'{table} row vanished during an update')
        self.changes.append(dict(t=table, b=row, a=after))
        return after

    def delete(self, table, row):
        where, args = self.locator(table, row)
        self.db.execute(f'DELETE FROM main."{table}" WHERE {where}', args)
        self.changes.append(dict(t=table, b=row, a=None))

    def insert(self, table, **values):
        names = list(values)
        rowid = values.get('_rowid') if self.rowid_key(table) else None
        names = [c for c in names if c != '_rowid']
        columns = (['rowid'] if rowid is not None else []) + [f'"{c}"' for c in names]
        marks = ', '.join('?' * len(columns))
        cursor = self.db.execute(f'INSERT INTO main."{table}"({", ".join(columns)}) VALUES({marks})',
                                 ([rowid] if rowid is not None else []) + [values[c] for c in names])
        if self.rowid_key(table):
            after = self.get(table, {'_rowid': rowid if rowid is not None else cursor.lastrowid})
        else:
            after = self.get(table, values)
        self.changes.append(dict(t=table, b=None, a=after))
        return after

    # ---- verifying and restoring
    def _key(self, change):
        row = change['a'] if change['a'] is not None else change['b']
        if self.rowid_key(change['t']):
            return change['t'], row['_rowid']
        return (change['t'], *[row[c] for c in self.pk(change['t'])])

    def verify(self):
        """The first change whose after-state is not what the database holds now, else None. A row changed twice (or deleted and its
        rowid taken by a row inserted later in the same log) is judged by the last change that touched it."""
        last = {}
        for change in self.changes:
            last[self._key(change)] = change
        for change in last.values():
            if change['a'] is None:
                if self.get(change['t'], change['b']) is not None:
                    return change
            elif not self._same(change['t'], self.get(change['t'], change['a']), change['a']):
                return change
        return None

    def restore(self):
        for change in reversed(self.changes):
            table, before, after = change['t'], change['b'], change['a']
            if before is None:
                where, args = self.locator(table, after)
                self.db.execute(f'DELETE FROM main."{table}" WHERE {where}', args)
            elif after is None:
                self.insert_row(table, before)
            else:
                where, args = self.locator(table, after)
                names = [c for c in self.cols(table)]
                self.db.execute(f'UPDATE main."{table}" SET {", ".join(chr(34) + c + chr(34) + "=?" for c in names)} WHERE {where}',
                                ([before[c] for c in names] + args))

    def insert_row(self, table, row):
        names = self.cols(table)
        with_rowid = self.rowid_key(table)
        columns = (['rowid'] if with_rowid else []) + [f'"{c}"' for c in names]
        values = ([row['_rowid']] if with_rowid else []) + [row[c] for c in names]
        self.db.execute(f'INSERT INTO main."{table}"({", ".join(columns)}) VALUES({", ".join("?" * len(columns))})', values)

    def tables(self):
        return sorted({c['t'] for c in self.changes})
