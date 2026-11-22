# Milestone U (Brand and redesign): handoff for the next agent

Written 2026-11-22 by the cloud thread that took U over from the local brick-work session (Ulf, 22.11.: "do all the required work to deliver milestone U"; merge each PR on green CI after self-review). U is GitHub milestone 26 and ships as v1.2. Target: on prod before end of November; checkpoint 26.11.; fallback v1.2.1 without #512 and #526. The gate #506 is Ulf's.

## Merged
| PR | What |
|---|---|
| #609 | Set detail in B′, frame 12 (#507) |
| #610 | Storage on a phone marks no row (#512 part) |
| #611 | T1: the other collection lists |
| #612 | T2: item detail pages (minifigure, part, instruction, box) |
| #613 | T4 + T6: Complete sets, Wishlist, Prices (`bw-planning-b.css`) |
| #614 | T9 + T8 + Appearance: Tools & Admin pages, Statistics, API tokens, Collection sync (`bw-admin-b.css`) |

## Open
| Issue / row | State | Branch / PR | Next |
|---|---|---|---|
| #501 T7 Add | Built, local gate clean | `u/501-t7-add`, #615 | Merge on green |
| #501 T3 Set Inspector start | Built, local gate running | `u/501-t3-inspector`, #616 | Merge on green |
| #501 T7 rest | Not started | none | Scan a set barcode (frame 57), first run without keys (frame 26) |
| #501 T5 | Not started | none | Storage labels and places (R4-03, L01). Pre-existing: the purchase places table layout looks broken |
| #501 T10 | Not started | none | Jump results, module states (R2) |
| #501 T2 rest | Not started | none | Edit sheet and copy chooser: dialogs sit outside every page scope, so they need their own rules |
| #501 small | Not started | none | Tokens page heading rule; admin intro sentence below the rule; frame 15 type sizes |
| #502 + #467 | Not started | none | Docs theme (generated: `scripts/docs_theme.py`), README hero, Pages demo, social previews |
| #503 | Not started | none | Baselines round for Ulf after #501 lands |
| #512 | Open | none | Dark mode round over every screen; fallback v1.2.1 |
| #526 / draft #542 | Open | #542 | Website; likely v1.2.1 |

## How the T rows are built
- One stylesheet per row group in `static/web/toni/*-b.css`, tokens only, scoped by the page root plus `:not(#_)` bumps (pages are not `.b-prime` roots). Every new sheet goes into `static/web/toni/sw.js`.
- Status is shape plus a word (solid, hatched, dashed, the X chip for "not checked"); chart bars are ink, complete violet (BRAND § 10, round 5 answers T8's question).
- A template change moves bench hashes: update only the intended entries in `tests/bench_reference.json`.
- After every merge the other open U branches conflict in `CHANGELOG.md` (sometimes `sw.js`): merge `origin/main` and keep both sides.

## Tests
- Local gate: `BW_CHROME_NO_SANDBOX=1 scripts/check.sh` (about 11 min). In the cloud `tests/test_upgrade_path.py::test_a_050_collection_reaches_the_current_schema_step_by_step` always fails (ATTACH with a `file:` URI in the container); it passes in CI. Every other test passed on each U branch.
- PR CI has no Chrome; the push run on `main` renders and is the judge (green after #612).

## Release (needs Ulf or the Mac)
- 24.11.: status on #506. 26.11.: propose the v1.2 cut (or v1.2.1 split).
- Release notes must say "back up first": v1.2 carries schema 4.7.
- Deploy and tag are done from Ulf's Mac.
