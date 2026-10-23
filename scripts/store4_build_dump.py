#!/usr/bin/env python3
"""Manual end-to-end run of the catalogue builder: scripts/store4_build_dump.py <dump dir> <out catalogue.db> [collection.db] [--local DIR].

Prints time, size and counts. Not part of the gate (it needs a real Rebrickable dump, which is never committed)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brickwork.store4.builder import build  # noqa: E402


def main(argv):
    args, local = list(argv[1:]), None
    if '--local' in args:
        at = args.index('--local')
        local = args[at + 1] if at + 1 < len(args) else None
        del args[at:at + 2]
    if len(args) not in (2, 3) or ('--local' in argv and local is None):
        print(__doc__)
        return 2
    report = build(args[0], args[1], collection=args[2] if len(args) == 3 else None, app_version='4.0-manual', local_dir=local)
    print(f"seconds {report['seconds']}  bytes {report['bytes']}  ({report['bytes'] / 1e6:.1f} MB)  build {report['build_id']}  "
          f"seeded_from {report['seeded_from']}  catalogue_id {report['catalogue_id']}")
    print(f"item_high_water {report['item_high_water']}  color_high_water {report['color_high_water']}")
    print(json.dumps(report['counts'], indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
