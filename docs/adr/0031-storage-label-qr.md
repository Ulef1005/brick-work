# 0031. Storage labels use Segno matrices and Pillow output

- **Status:** accepted
- **Date:** 2026-11-15
- **Decided by:** Ulf, issue #31 approved brief

## Context

Storage labels need working QR codes, readable names and predictable physical dimensions. The app already ships Pillow and the Inter and Geist Mono fonts.

## Options considered

1. Add a PDF library and a QR library.
2. Render QR matrices and labels with Pillow, including image-based PDFs.

## Decision

Use option 2. Add only Segno 1.6.6, pinned in requirements.txt. Segno is pure Python, has no dependencies and uses BSD-3-Clause.
Pillow writes 300 dpi PDF sheets and PNG tape labels. The image build installs Segno from requirements.txt without Dockerfile changes.

Use error correction M without automatic boosting. Preserve four quiet modules around a code whose module square measures at least 20 mm.
Sheet layouts use A4: 21 cells at 63.5 × 38.1 mm, or 14 cells at 99.1 × 38.1 mm.
Tape images measure 62 mm wide and 45 mm long. Each download accepts at most 200 storages.

The 21-cell layout starts 7.25 mm from the left and 15.15 mm from the top. Horizontal gaps measure 2.5 mm.
The 14-cell layout starts 4.65 mm from the left and 15.15 mm from the top. Horizontal gaps measure 2.5 mm.
No vertical gaps are added. Preview guides never enter downloads.

Schema 4.3 adds a unique short id and a counter outside Undo receipts. An insert trigger advances it under SQLite's write lock.
Backfill orders storages by creation timestamp and primary key. The primary key resolves equal timestamps deterministically.
The additive upgrade also runs after restoring an older backup. New and upgraded files use the same SQL.

The shipped monochrome line mark is rasterised from its SVG rectangles and cross in black.
Names use bundled Inter 600 at 56 pixels for narrow cells, 69 for wide cells and 40 for tape, at 300 dpi. Short ids use bundled Geist Mono. Names wrap to two lines, then an ellipsis.

## Consequences

PDFs contain raster pages, so file size exceeds a vector PDF. Output needs no system fonts or PDF library.
Read downloads remain available on read-only instances. The address setting follows the existing audited settings flow.
Segno is imported lazily. A missing install leaves other screens usable and gives the label dialog a retryable error.
