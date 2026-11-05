# Demo illustrations

Original flat illustrations for the invented collection of the demo (`brickwork/demo/showcase.py`) and for the README and Pages pictures: a brick-built scene for each set, a generic figure in the colours of its parts for each minifigure, and a flat drawing of the part's shape in its colour for each part, gear, book and catalog.

They are drawn from shapes by [`scripts/demo_art.py`](../../scripts/demo_art.py) with Pillow, deterministically, in the app's style (flat fills, a hairline in a darker shade, no shadows, transparent ground). **Nothing is taken from, traced from or derived from BrickLink, Rebrickable, Brickset or LEGO pictures.** They are original artwork made for this project, MIT as the project (see [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES.md)).

`manifest.json` maps `<namespace>/<number>[/<colour>]` (the catalogue's own keys: `sets/99101-1`, `minifigs/fig-990001`, `parts/3001/5`) to a file. The demo world stores each one through the app's own `picture` table (source *Demo illustration*) under `data/images/` in its media folder, so the app shows it like any picture. Regenerate with `python scripts/demo_art.py`; `python scripts/demo_art.py --check` fails when the world needs a picture the manifest lacks.
