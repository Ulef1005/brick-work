"""The migration as one command (design 8.2, issue #109 M.7c): pin check, write, independent proof, report, publish only on PASS.

`run(src, catalogue, mappings, out, report, pin=None)`:
1. hash the catalogue and every mapping file (`--mappings` and the shipped ones) and, with `pin`, refuse before anything is written when
   they differ from the pinned run (the cutover is pinned to the rehearsal; the 3.3 file naturally differs and is not pinned);
2. `Migration.write(record_event=False)`: the whole migration in one transaction, lists attached (8.6), file under a temporary name;
3. `prove(...)`: the read-back proof on its own read-only connection (8.7);
4. the report (8.8), with the proof;
5. PASS: the migration event and `meta.migrated_from` get the report digest, then `publish()` creates `out`. FAIL: the report says so,
   the temporary file is removed, `out` never exists.

Pinning covers the catalogue and the mapping files, not the output: the mint depends on the catalogue's ids and the mappings it was built from."""
from dataclasses import dataclass, field
import json
import re
import time
from pathlib import Path

from .mappings import MAPPINGS_DIR
from .migrate import Migration, MigrationError, sha256_file
from .migrate_proof import prove
from .migrate_report import write_report

RESERVATION = '.migration-run'                                # held while a run owns the report folder
PIN_BLOCK = re.compile(r'```json pins\n(.*?)\n```', re.S)


class Refused(MigrationError):
    """The run was refused before anything was written (a pin that differs, an existing output, a report folder in use, a 3.3 file with a WAL...)."""


class PinMismatch(Refused):
    """The catalogue or a mapping file differs from the pinned run; `.differences` lists them."""

    def __init__(self, message, differences):
        super().__init__(message)
        self.differences = differences


@dataclass
class RunResult:
    result: str                                               # 'PASS' | 'FAIL'
    published: bool
    out: Path
    report: Path
    digest: str
    proof: dict
    migration: object                                         # the MigrationResult
    seconds: float
    pins: dict = field(default_factory=dict)


def hash_tree(directory):
    """{relative path: sha256} of every file under `directory`, sorted (hidden files and __pycache__ left out)."""
    directory = Path(directory)
    out = {}
    for path in sorted(p for p in directory.rglob('*') if p.is_file()):
        rel = path.relative_to(directory)
        if any(part.startswith('.') or part == '__pycache__' for part in rel.parts):
            continue
        out[rel.as_posix()] = sha256_file(path)
    return out


def compute_pins(catalogue, mappings):
    if not Path(mappings).is_dir():
        raise Refused(f'the mappings directory {mappings} does not exist')
    return {'catalogue': {'name': Path(catalogue).name, 'sha256': sha256_file(catalogue)},
            'mappings': hash_tree(mappings), 'shipped_mappings': hash_tree(MAPPINGS_DIR)}


def read_pins(path):
    """The pins of an earlier run: from its proof.json, or from the fenced `json pins` block of its summary.md (or the report folder)."""
    path = Path(path)
    if path.is_dir():
        path = path / 'proof.json'
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise Refused(f'cannot read the pin file {path}: {exc}') from None
    try:
        pins = json.loads(text).get('pins')
    except (ValueError, AttributeError):
        found = PIN_BLOCK.search(text)
        pins = json.loads(found.group(1)) if found else None
    if not isinstance(pins, dict) or not {'catalogue', 'mappings', 'shipped_mappings'} <= set(pins):
        raise Refused(f'{path} carries no pins (it must be the proof.json or summary.md of an earlier run)')
    return pins


def check_pin(pinned, pins):
    diff = []
    if pinned['catalogue'].get('sha256') != pins['catalogue']['sha256']:
        diff.append(f'catalogue: pinned {pinned["catalogue"].get("sha256")}, now {pins["catalogue"]["sha256"]}')
    for group in ('mappings', 'shipped_mappings'):
        for name in sorted(set(pinned[group]) | set(pins[group])):
            if pinned[group].get(name) != pins[group].get(name):
                diff.append(f'{group}/{name}: pinned {pinned[group].get(name)}, now {pins[group].get(name)}')
    if diff:
        raise PinMismatch(f'the catalogue or the mapping files differ from the pinned run ({len(diff)}): {diff[0]}', diff)


def run(src, catalogue, mappings, out, report, *, pin=None, actor='migration', after_write=None):
    """Run the migration; returns a `RunResult`. Raises `Refused` before any write, `NeedsDecision` (rows listed) when 3.3 rows cannot be
    carried, other `MigrationError`s for a failed write. `after_write(migration)` is called between the write and the proof (tests tamper there)."""
    started = time.monotonic()
    pins = compute_pins(catalogue, mappings)
    if pin is not None:
        check_pin(read_pins(pin), pins)
    report = Path(report)
    if report.exists() and (not report.is_dir() or any(report.iterdir())):
        raise Refused(f'the report folder {report} exists and is not empty')
    created = not report.exists()
    report.mkdir(parents=True, exist_ok=True)
    reservation = report / RESERVATION

    def release():
        reservation.unlink(missing_ok=True)
        if created and report.is_dir() and not any(report.iterdir()):
            report.rmdir()                                    # a run that wrote no report leaves no folder behind
    try:
        reservation.open('x').close()                         # exclusive: a second run on the same folder is refused here
    except FileExistsError:
        raise Refused(f'the report folder {report} is in use by another run') from None
    try:
        m = Migration(src, catalogue, out, actor=actor)
    except (MigrationError, FileExistsError) as exc:
        release()
        raise Refused(str(exc)) from exc
    published = False
    try:
        if m.result.catalogue['sha256'] != pins['catalogue']['sha256']:
            # the catalogue the migration opened is not the one hashed (and pinned) above: it was replaced in between
            raise Refused(f'the catalogue {catalogue} changed between the pin check and the start of the migration')
        result = m.write(record_event=False)
        if after_write is not None:
            after_write(m)
        proof = prove(m.temp_path, catalogue, src, result)
        m.check_inputs()
        digest = write_report(result, proof, pins, report, out_path=m.out_path, seconds=time.monotonic() - started)
        if proof['result'] == 'PASS':
            if compute_pins(catalogue, mappings) != pins:
                raise MigrationError('the catalogue or a mapping file changed during the run: the report pins no longer describe it')
            m.record_event(digest)
            m.finish(digest)
            _final_check(m, digest)
            m.publish()
            published = True
        else:
            m.abort()
        return RunResult(proof['result'], published, m.out_path, report, digest, proof, result, time.monotonic() - started, pins)
    finally:
        if not published:
            m.abort()
        release()


def _final_check(m, digest):
    """After the event and the digest: the file is still what the proof saw, with exactly one event that names the report."""
    db = m.db
    problems = []
    if [tuple(x) for x in db.execute('PRAGMA foreign_key_check')]:
        problems.append('foreign_key_check')
    if db.execute('SELECT count(*) FROM main.event').fetchone()[0] != 1:
        problems.append('the file does not hold exactly one event')
    if json.loads(db.execute("SELECT value FROM main.meta WHERE key='migrated_from'").fetchone()[0]).get('report_digest') != digest:
        problems.append('meta.migrated_from does not carry the report digest')
    event = db.execute('SELECT new_value FROM main.event').fetchone()
    if event is None or json.loads(event[0]).get('report_digest') != digest:
        problems.append('the event does not carry the report digest')
    if problems:
        raise MigrationError('after the report digest was written: ' + '; '.join(problems))
