#!/usr/bin/env python3
"""Manual end-to-end run of the catalogue builder: scripts/store4_build_dump.py <dump dir> <out catalogue.db> [collection.db].

Prints time, size and counts. Not part of the gate (it needs a real Rebrickable dump, which is never committed)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brickwork.store4.builder import build  # noqa: E402


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    report = build(argv[1], argv[2], collection=argv[3] if len(argv) == 4 else None, app_version='4.0-manual')
    print(f"seconds {report['seconds']}  bytes {report['bytes']}  ({report['bytes'] / 1e6:.1f} MB)  build {report['build_id']}  "
          f"seeded_from {report['seeded_from']}  catalogue_id {report['catalogue_id']}")
    print(f"item_high_water {report['item_high_water']}  color_high_water {report['color_high_water']}")
    print(json.dumps(report['counts'], indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
