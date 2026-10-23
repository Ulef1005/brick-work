# Data model 4.0

The approved design for Brick Work's schema 4.0, decided in [ADR 0016](../adr/0016-data-model-4.md) and built in the 4.0 milestone.

| File | What it holds |
|---|---|
| [data-model-design.md](data-model-design.md) | The design: two files, Brick Work ids, provider links, part lists, the collection, the catalogue lifecycle, API v2 and the migration from 3.3 |
| [schema-4.0.sql](schema-4.0.sql) | The DDL. Lines 1–217 are `catalogue.db`, from line 218 `brickwork.db`; load each half into its own database |
| [user-journey.md](user-journey.md) | A fresh install through onboarding, set 6081-1, loose parts and two loose figures, row by row |
| [effort.md](effort.md) | The estimate per piece, about 20 weeks (18–22) |

**Amended after this revision (2026-10-23, the maintainer):** decision F switches a copy to BrickLink's list automatically only while nothing on the copy is checked or marked; otherwise the copy offers "switch now?" and lists what would not carry over. The design text still describes the unconditional switch; ADR 0016 is authoritative.

The design names files of its review folder (`../data-model-design.md`, `c101.md`, `c101b.md`, the review). They are not in the repository: the decisions they hold are in ADR 0016 and on [#101](https://github.com/Ulef1005/brick-work/issues/101).
