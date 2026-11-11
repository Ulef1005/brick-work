"""Benchmark of Build Scout on a real catalogue file (#9): the two indexes, then a ranking of the whole catalogue for a pile, cold and warm.

    python scripts/bench_build_scout.py path/to/catalogue.db            # a random 2,000-line pile, 5 runs
    python scripts/bench_build_scout.py path/to/catalogue.db --lines 8000 --runs 9

The file is opened read-only. The pile is drawn from real sets as `scripts/bench_set_scoring.py` does. It times what Build Scout does for a
request after the stock is read: `Scout` (the load and both indexes, once per catalogue build and process), then `ranked` over every set that shares a
part with the pile and `figures_of`, for a new pile each run. The target is the ranking of the full catalogue in a few seconds warm; PASS or FAIL
against `TARGET`. Nothing here is a test."""
import argparse
import resource
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brickwork.core import build_scout, set_scoring  # noqa: E402
from scripts.bench_set_scoring import attach, pile as draw  # noqa: E402

TARGET = 3.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('catalogue')
    parser.add_argument('--lines', type=int, default=2000)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--seed', type=int, default=1)
    args = parser.parse_args(argv)
    if not Path(args.catalogue).is_file():
        parser.error(f'no such file: {args.catalogue}')
    db = attach(args.catalogue)
    started = time.perf_counter()
    scout = build_scout.Scout(db)
    built = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == 'darwin' else 1024)
    parts, figures = scout.parts, scout.figures
    print(f'catalogue   {args.catalogue}')
    print(f'indexes     parts {parts.total} sets, {len(parts.posting)} lines, {sum(len(p[0]) for p in parts.posting.values())} postings; figures {figures.total} sets')
    print(f'build       {built:.2f} s (load and both indexes), peak memory {peak:.0f} MB (the process)')
    times, sharing, kept = [], [], []
    for run in range(args.runs):
        pile = set_scoring.clean(draw(parts, args.lines, args.seed + run))
        started = time.perf_counter()
        found, share = build_scout.ranked(scout, pile, min_percent=0)
        build_scout.figures_of(scout, pile)
        times.append(time.perf_counter() - started)
        sharing.append(share)
        started = time.perf_counter()
        found, _ = build_scout.ranked(scout, pile)
        kept.append((time.perf_counter() - started, len(found)))
    print(f'ranking     median {statistics.median(times):.2f} s, max {max(times):.2f} s over {args.runs} piles of {args.lines} lines '
          f'(every set sharing a part, min 0 %: median {int(statistics.median(sharing))} sets)')
    print(f'default     median {statistics.median(t for t, _ in kept):.2f} s with the default minimum of {build_scout.DEFAULT_MIN_PERCENT} % '
          f'(median {int(statistics.median(n for _, n in kept))} sets kept)')
    ok = max(times) < TARGET
    print(f'target      {TARGET:.0f} s for the whole catalogue warm: {"PASS" if ok else "FAIL"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
