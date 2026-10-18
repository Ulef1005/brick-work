"""Build the static demo: the real UI on invented sample data, for the project's Pages site.

    python3 scripts/build_demo.py OUT [--base /brick-work/demo/]

OUT must not exist. Runs offline from the repository alone (design/test-data supplies the catalogue
facts; the collection, prices and owners are invented; no pictures). Writes are answered with
"Demo with sample data: changes are not saved". Exit 1 when an exported page holds a private pattern
or loads anything from outside. build_site.py can import build_demo(out, base).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_demo(out, base='/brick-work/demo/'):
    from brickwork.demo.export import export
    return export(Path(out), base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    parser.add_argument('--base', default='/brick-work/demo/')
    options = parser.parse_args(argv)
    try:
        manifest = build_demo(options.out, options.base)
    except (RuntimeError, FileExistsError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{len(manifest['pages'])} pages and {len(manifest['gets'])} saved reads in {options.out} (base {options.base})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
