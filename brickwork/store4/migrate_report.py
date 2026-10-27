"""The migration report (design 8.8, issue #109 M.7c): the files in `<report dir>`, and the digest that goes into the event and `meta`.

Files: `summary.md`; the four of the mint (`mint.csv`, `collisions.csv`, `local-items.csv`, `colours.csv`); `summed-lines.csv` (Q7),
`extras.csv` (8.5; `extras-skipped.csv` lists the rows whose `source_ref` named no BrickLink line of their set), `attached.csv` and
`migrated-lists.csv` (Q12), `manual-decisions.csv` (C, in full) and `to-check.csv` (the open `to_check` and `unmatched` identity rows),
`not-carried.csv`, `settings.csv`, `proof.json`. Every other transformation the proof relies on has a file too, because the proof
subtracts exactly these from the comparison: `type-crossed.csv`, `figure-lines-from-parts.csv`, `figure-lines-retained-duplicate.csv`,
`non-part-lines.csv`, `value-fixes.csv`, `money-fills.csv`, `money-currency-dropped.csv`, `count-fixes.csv`, `timestamp-rules.csv`,
`tables.csv` (3.3 rows to 4.0 rows per table) and `wish-ids.csv` (the integer wish ids and their uuids).

Every cell goes through `csv_safe`. The report digest is the sha256 over the bytes of `summary.md` followed by the bytes of
`proof.json`."""
from contextlib import contextmanager
import csv
import hashlib
import json
import re
from pathlib import Path

from . import csv_safe
from . import mint as mint_module


def cell(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str, separators=(',', ':'))
    return value


def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv_safe.writer(f)
        w.writerow(header)
        w.writerows([cell(v) for v in row] for row in rows)


def dict_csv(path, items, header=None):
    """Rows given as dicts; the columns are `header`, else the keys in the order they first appear."""
    items = list(items)
    if header is None:
        header = []
        for item in items:
            header += [k for k in item if k not in header]
    write_csv(path, header, ([item.get(k) for k in header] for item in items))
    return len(items)


def report_digest(directory):
    directory = Path(directory)
    return hashlib.sha256((directory / 'summary.md').read_bytes() + (directory / 'proof.json').read_bytes()).hexdigest()


def write_report(result, proof, pins, directory, *, out_path, seconds=None):
    """Write every report file. `proof` is the proof document (with 'result'); returns the digest of summary.md and proof.json."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    r = result
    mint_module.write_report(r.mint, directory)
    dict_csv(directory / 'summed-lines.csv', r.summed_lines)
    dict_csv(directory / 'extras.csv', ({**{k: v for k, v in e.items() if k not in ('before', 'after')},
                                         **{f'before_{k}': v for k, v in e['before'].items()}, **{f'after_{k}': v for k, v in e['after'].items()}}
                                        for e in r.extras))
    dict_csv(directory / 'extras-skipped.csv', r.extras_skipped_foreign_ref)
    attach_columns = ['kind', 'row', 'ref', 'label', 'status', 'reason', 'version', 'versions_tried', 'lines', 'ids_equal', 'bl_digest', 'catalogue_digest']
    dict_csv(directory / 'attached.csv', (a for a in r.attach if a['status'] == 'attached'), attach_columns)
    dict_csv(directory / 'migrated-lists.csv', (a for a in r.attach if a['status'] != 'attached'), attach_columns)
    dict_csv(directory / 'manual-decisions.csv', r.manual_decisions)
    dict_csv(directory / 'to-check.csv', [*r.to_check, *r.unmatched])
    write_csv(directory / 'not-carried.csv', ('name', 'count', 'why', 'samples'),
              ((name, v['count'], v['why'], v['samples']) for name, v in r.not_carried.items()))
    dict_csv(directory / 'settings.csv', r.settings, ['key', 'classification', 'value', 'key40', 'value40', 'note'])
    dict_csv(directory / 'type-crossed.csv', r.type_crossed)
    dict_csv(directory / 'figure-lines-from-parts.csv', r.figure_lines_from_parts)
    dict_csv(directory / 'figure-lines-retained-duplicate.csv', r.figure_lines_retained_duplicate)
    dict_csv(directory / 'non-part-lines.csv', r.non_part_lines)
    dict_csv(directory / 'value-fixes.csv', r.value_fixes)
    dict_csv(directory / 'money-fills.csv', r.money_fills)
    dict_csv(directory / 'money-currency-dropped.csv', r.money_currency_dropped)
    dict_csv(directory / 'count-fixes.csv', r.count_fixes)
    write_csv(directory / 'timestamp-rules.csv', ('field', 'rule', 'rows'), ((f, rule, n) for f, c in sorted(r.timestamp_rules.items()) for rule, n in sorted(c.items())))
    dict_csv(directory / 'tables.csv', r.tables, ['from', 'to', 'rows_33', 'rows_40', 'note'])
    write_csv(directory / 'wish-ids.csv', ('wish_id_33', 'wish_id_40'), sorted(r.wish_ids.items()))
    document = {**proof, 'pins': pins, 'inputs': {'source': r.source, 'catalogue': r.catalogue}, 'attach': r.attach_counts(), 'rows': r.counts()}
    (directory / 'proof.json').write_text(json.dumps(document, indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8')
    (directory / 'summary.md').write_text(summary(r, proof, pins, out_path, seconds), encoding='utf-8')
    return report_digest(directory)


def pct(n, total):
    return f'{n}/{total}' + (f' ({100 * n / total:.1f}%)' if total else '')


def summary(r, proof, pins, out_path, seconds):
    lines = [f'# Brick Work 3.3 to 4.0 migration: {proof["result"]}', '',
             f'- migrated at {r.migrated_at}' + (f', {seconds:.1f} s' if seconds is not None else ''),
             f'- 3.3 file `{r.source["name"]}` sha256 `{r.source["sha256"]}`',
             f'- catalogue `{r.catalogue["name"]}` sha256 `{r.catalogue["sha256"]}`',
             f'- output `{out_path}` ' + ('(published on PASS)' if proof['result'] == 'PASS' else '(NOT published: the proof failed)'), '',
             '## Proof', '', '| part | result | checked | differences |', '|---|---|---|---|']
    for name, p in proof['parts'].items():
        lines.append(f'| {name} | {p["result"]} | {p["checked"]} | {p["differences"]} |')
    for name, p in proof['parts'].items():
        for d in p['first_differences'][:5]:
            lines.append(f'\nFirst difference in {name}: `{json.dumps(d, default=str)[:300]}`')
    lines += ['', '## Rows', '', '| 3.3 | 4.0 | rows 3.3 | rows 4.0 | note |', '|---|---|---|---|---|']
    for t in r.tables:
        lines.append(f'| {t["from"]} | {t["to"]} | {t["rows_33"]} | {t["rows_40"]} | {t["note"]} |')
    names = {'copy': 'copies', 'figure': 'figure lines', 'loose_figure': 'loose figures'}
    lines += ['', '## Attached to Rebrickable lists (Q12, equal in BrickLink space)', '']
    for kind, c in sorted(r.attach_counts().items()):
        why = ', '.join(f'{k} {v}' for k, v in sorted(c['reasons'].items())) or 'none'
        lines.append(f'- {names[kind]}: {pct(c["attached"], c["total"])} attached; stayed migrated: {why}')
    different = sum(1 for a in r.attach if a['reason'] == 'ids_differ')
    lines.append(f'- equal in BrickLink space but kept migrated, lines on other 4.0 ids than the catalogue list (ids_differ): {different}')
    c = r.mint.counts()
    lines += ['', '## Mint', '', f'{c["keys"]} keys; rule 1 {c["rule 1"]}, rule 3 {c["rule 3"]}, rule 4 {c["rule 4"]} ({c["rule 4 holders"]} holders, '
              f'{c["rule 4 holders tied"]} tied), rule 5 {c["rule 5"]}, rule 6 {c["rule 6"]}; collisions {c["collisions"]}; local items {c["local items"]}; '
              f'local colours {c["local colours"]}.', '', '## Listed transformations (each has a file)', '',
              f'- Q7 sums: {len(r.summed_lines)} (`summed-lines.csv`)',
              f'- extras corrected: {len(r.extras)}; skipped (foreign source_ref): {len(r.extras_skipped_foreign_ref)} (`extras.csv`, `extras-skipped.csv`)',
              f'- gear carried as parts (type_crossed): {len(r.type_crossed)} (`type-crossed.csv`)',
              f'- figure lines taken from copy_parts: {len(r.figure_lines_from_parts)}; retained duplicates not added: '
              f'{len(r.figure_lines_retained_duplicate)}',
              f'- lines copy_part cannot hold: {len(r.non_part_lines)} (`non-part-lines.csv`)',
              f'- value fixes: {len(r.value_fixes)}; money fills: {len(r.money_fills)}; currencies without a price dropped: {len(r.money_currency_dropped)}; '
              f'count fixes: {len(r.count_fixes)}',
              f'- timestamps by rule: ' + '; '.join(f'{f} ' + ', '.join(f'{k} {v}' for k, v in sorted(cn.items())) for f, cn in sorted(r.timestamp_rules.items())),
              f'- price_current: {r.price_current.get("rows_33")} rows in 3.3, {r.price_current.get("rows_40")} recomputed, '
              f'{len(r.price_current.get("differences", []))} difference(s)',
              f'- manual identity decisions carried in full: {len(r.manual_decisions)}; open to_check {len(r.to_check)}, unmatched {len(r.unmatched)}',
              f'- not carried: ' + '; '.join(f'{n} {v["count"]}' for n, v in r.not_carried.items() if v['count']),
              f'- settings: ' + ', '.join(f'{k} {v}' for k, v in sorted(_count(s['classification'] for s in r.settings).items())),
              '', '## Pins', '', 'The catalogue and the mapping files this run used. `--pin` on the next run refuses unless these are equal.', '',
              '```json pins', json.dumps(pins, indent=1, sort_keys=True), '```', '']
    return '\n'.join(lines)


def _count(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ---------- reading a written report (the Tools & Admin view, design 8.8; M.10c) ----------

@contextmanager
def _long_fields():
    """The report's samples columns can exceed the csv module's 131,072-character field limit (the 26 Oct prod report's
    not-carried.csv: 1.9 MB). Raise it for one read and put it back, since the limit is process-wide."""
    before = csv.field_size_limit()
    csv.field_size_limit(1 << 30)
    try:
        yield
    finally:
        csv.field_size_limit(before)


def read_report(directory, *, expected_digest=None, decisions=12):
    """What the migration report in `directory` says, read-only: the summary's headline lines, the proof (per part), every file with its row
    count and size, the manual decisions (the first `decisions` rows of `manual-decisions.csv`, with the total) and the settings counts.
    `expected_digest` (from `meta.migrated_from`) is compared with the digest of the files on disk. None when there is no report there.
    Only files directly in `directory` are listed; a name is a plain file name, never a path."""
    directory = Path(directory)
    if not (directory / 'summary.md').is_file():
        return None
    try:
        proof = json.loads((directory / 'proof.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        proof = {}
    files = []
    for path in sorted(p for p in directory.iterdir() if p.is_file() and not p.name.startswith('.')):
        rows = None
        if path.suffix == '.csv':
            with open(path, newline='', encoding='utf-8') as f, _long_fields():
                rows = max(sum(1 for _ in csv.reader(f)) - 1, 0)
        files.append(dict(name=path.name, rows=rows, bytes=path.stat().st_size))
    decided, total = [], 0
    path = directory / 'manual-decisions.csv'
    if path.is_file():
        with open(path, newline='', encoding='utf-8') as f, _long_fields():
            for i, row in enumerate(csv.DictReader(f)):
                total += 1
                if i < decisions:
                    decided.append(row)
    settings = {}
    path = directory / 'settings.csv'
    if path.is_file():
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                settings[row['classification']] = settings.get(row['classification'], 0) + 1
    try:
        digest = report_digest(directory)
    except OSError:
        digest = None
    lines = (directory / 'summary.md').read_text(encoding='utf-8').splitlines()
    head = '\n'.join(lines[:8])
    found = re.search(r'migrated at (\S+?)(?:, ([\d.]+) s)?\n', head)
    source = re.search(r'3\.3 file `([^`]+)`', head)
    headline = dict(migrated_at=found.group(1) if found else None, seconds=found.group(2) if found else None, source=source.group(1) if source else None,
                    published='(published on PASS)' in head)
    return dict(directory=str(directory), result=proof.get('result'), parts=[dict(name=k, **{f: v.get(f) for f in ('result', 'what', 'checked', 'differences')})
                                                                         for k, v in (proof.get('parts') or {}).items()],
                headline=headline, title=lines[0].lstrip('# ') if lines else '', files=files, decisions=decided, decisions_total=total,
                decision_columns=list(decided[0]) if decided else [], settings=settings, digest=digest,
                digest_matches=None if expected_digest is None or digest is None else digest == expected_digest)
