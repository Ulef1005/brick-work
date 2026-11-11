"""Benchmark of the set-scoring engine on a real catalogue file (#199): index build, a cold and a warm query, a page of detail.

    python scripts/bench_set_scoring.py path/to/catalogue.db            # a random 2,000-line pile, 5 runs
    python scripts/bench_set_scoring.py path/to/catalogue.db --lines 500 --runs 9 --seed 3

The file is opened read-only (it is never changed). The pile is drawn from real sets: the lines of randomly chosen sets, a few parts
from each, until it has the wanted number of distinct (part, colour) lines, so it mixes common and rare lines as a real lot does.
The target is a 2,000-line pile ranked and its first page built in under 10 s on the machine that serves the app (cold: the index is
built by the first query); the script prints PASS or FAIL against it. Nothing here is a test: the suite's scale test is
`tests/test_set_scoring.py`, on invented data."""
import argparse
import random
import resource
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brickwork.core import set_scoring  # noqa: E402

TARGET = 10.0


def attach(path):
    db = sqlite3.connect(':memory:')
    db.execute('ATTACH DATABASE ? AS catalogue', (f'file:{Path(path).resolve()}?mode=ro',))
    return db


def pile(index, lines, seed):
    """`lines` distinct (item, colour) lines from random sets' lines, each with a quantity of 1 to 4."""
    rng = random.Random(seed)
    sets, taken = list(range(index.total)), {}
    by_set = {}
    chosen = rng.sample(sets, min(len(sets), max(50, lines // 10)))
    wanted = set(chosen)
    for key, (positions, _) in index.posting.items():
        for position in positions:
            if position in wanted:
                by_set.setdefault(position, []).append(key)
    pool = [k for position in chosen for k in by_set.get(position, ())]
    rng.shuffle(pool)
    for key in pool:
        if len(taken) >= lines:
            break
        taken.setdefault(set_scoring.unkey(key), rng.randint(1, 4))
    return taken


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('catalogue', help='the path of a catalogue.db')
    parser.add_argument('--lines', type=int, default=2000)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--seed', type=int, default=1)
    args = parser.parse_args(argv)
    if not Path(args.catalogue).is_file():
        parser.error(f'no such file: {args.catalogue}')
    db = attach(args.catalogue)

    started = time.perf_counter()
    rows = set_scoring.load_rows(db)
    loaded = time.perf_counter() - started
    started = time.perf_counter()
    index = set_scoring.build_index(rows)
    built = time.perf_counter() - started
    del rows
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == 'darwin' else 1024)
    print(f'catalogue   {args.catalogue}')
    print(f'index       {index.total} sets, {len(index.posting)} lines, {sum(len(p[0]) for p in index.posting.values())} postings')
    print(f'            load {loaded:.2f} s, build {built:.2f} s, peak memory {peak:.0f} MB (the process, including the load)')
    parts = pile(index, args.lines, args.seed)
    print(f'pile        {len(parts)} distinct lines, {sum(parts.values())} pieces (seed {args.seed})')

    set_scoring._INDEXES.clear()
    set_scoring._RESULTS.clear()
    started = time.perf_counter()
    cold = set_scoring.score(db, parts)
    cold_time = time.perf_counter() - started
    print(f'cold        {cold_time:.2f} s  (index built: {cold["index_built"]}; {cold["total"]} sets share a line; top: {cold["results"][0]["set_item_id"]})')

    times = []
    for run in range(args.runs):
        other = pile(index, args.lines, args.seed + 1 + run)            # a new input each run: nothing is cached
        started = time.perf_counter()
        answer = set_scoring.score(db, other)
        times.append(time.perf_counter() - started)
        assert not answer['cached']
    print(f'warm index  median {statistics.median(times):.2f} s, max {max(times):.2f} s over {args.runs} new inputs (rank + first page of 20)')

    started = time.perf_counter()
    again = set_scoring.score(db, parts, limit=20, offset=20)
    print(f'cached      {time.perf_counter() - started:.3f} s  (second page of the first input; cached: {again["cached"]})')

    ok = cold_time < TARGET
    print(f'target      {TARGET:.0f} s for a {len(parts)}-line pile against the full catalogue, cold: {"PASS" if ok else "FAIL"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
