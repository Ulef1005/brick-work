# Milestone U (Brand and redesign): handoff for brick-work-product

Written 2026-11-22, 19:15 UTC, by the cloud thread that took U over from the local brick-work session. It stopped here because the budget ran out (Ulf, 22.11.). U is GitHub milestone 26 and ships as v1.2. Target: on prod before end of November, checkpoint 26.11. The gate #506 is Ulf's. **This file prescribes no order: product decides what gets built when.**

## Merged to main
| PR | What |
|---|---|
| #609 | Set detail in B′, frame 12 (#507) |
| #610 | Storage on a phone marks no row (#512 part) |
| #611 | #501 T1: the other collection lists |
| #612 | #501 T2: item detail pages |
| #613 | #501 T4 + T6: Complete sets, Wishlist, Prices |
| #614 | #501 T9 + T8 + Appearance: Tools & Admin pages, Statistics, API tokens, Collection sync |
| #615 | #501 T7: the Add page |
| #616 | #501 T3: Set Inspector's copy list |

The push run on main (with Chrome) was green after #612; later merges were not re-checked here.

## Open PRs, built and tested, not merged
Each needs: merge `origin/main` (CHANGELOG conflicts: keep both; `tests/bench_reference.json`: keep each branch's own changed entries, never duplicate keys), wait for green CI, squash-merge.

| PR | Branch | What | State |
|---|---|---|---|
| #618 | `u/501-t5-storage` | #501 T5: Purchase locations and Print labels in B′; **fixes two broken layouts** (places table wrapped every row since #46; Print labels dialog squeezed into the 480 px side sheet since #578) | main merged in, CI rerunning; targeted tests pass, bench unchanged |
| #620 | `u/501-t2-dialogs` | #501 T2 rest: edit sheet and copy chooser (`bw-sheet-b.css`) | main merged in, bench fixed, CI rerunning |
| #619 | `u/501-t10-shell` | #501 T10: Jump results and the Prices card states (dashed loading box, danger error, STALE tag) | **PR CI failed (3 shards); reason not read.** Targeted tests passed locally. First step: read the CI log |
| (no PR yet) | `u/501-t7-firstrun` | #501 T7: Get started pages in B′ (`bw-first-run-b.css`) | pushed; 143 targeted tests pass, bench unchanged; open the PR |
| #617 | `u/506-handoff` | this file | docs only |

None of #618 to #620 or the T7 branch ran the full local gate (`BW_CHROME_NO_SANDBOX=1 scripts/check.sh`); PR CI has no Chrome, so run it once before merging, or merge and watch the main push run.

## What is left, per issue (effort is a guess for one session)
| Issue | Left | Effort | Risk |
|---|---|---|---|
| #501 | Merge the four branches above. Small rest: the tokens page heading rule, the admin intro sentence below the rule, frame 15 type sizes. T7 "Scan a set barcode" (frame 57) is **not buildable**: the feature does not exist yet (O's #8) | 0.5 day | #619's CI failure is unknown; bench conflicts between branches |
| #502 + #467 | Docs theme (generated: `scripts/docs_theme.py` from the tokens), README hero and first screen, docs screenshots, Pages demo, social previews | 1 to 2 days | Screenshots need the final #501 look; README badge row needs the release |
| #503 | Screen-gate baselines re-rendered for every approved screen, a round for Ulf | 0.5 day + Ulf's review | Must follow the last #501 merge; Mac vs Linux font rendering |
| #512 | Dark mode round over every screen, then the dark tokens | 1 to 2 days + design round | Needs Ulf's approval of a round; the planned v1.2.1 fallback |
| #526 / #542 | Marketing website in B′ (draft #542) | 1 to 2 days | V (#594) waits on it; planned v1.2.1 fallback |
| #506 | Gate: Ulf's | Ulf | |

## Only a local session (or Ulf) can do
- Deploy to test and prod, tag v1.2, publish the image.
- Check with the shipped fonts on a Mac (cloud renders with a fallback font; the CI tolerance holds for that).
- The Hydrogen review, if wanted before the cut.
- Release notes must say "back up first": v1.2 carries schema 4.7.

## Fallback options for the 26.11. checkpoint
1. **v1.2 = what is on main now plus #618 (layout fixes) and the other ready branches**; #502/#467, #503, #512, #526 move to v1.2.1.
2. **v1.2 waits for #502/#467 and #503** (docs and baselines match the release); #512 and #526 in v1.2.1.
3. **Full U as planned**; most likely misses end of November.

## How the rows were built (for whoever continues)
- One stylesheet per row group, `static/web/toni/*-b.css`, tokens only, page root plus `:not(#_)` bumps (pages are not `.b-prime` roots; dialogs sit outside `.b-prime`). Every new sheet goes into `static/web/toni/sw.js`.
- Status is shape plus a word (solid, hatched, dashed, the X chip); chart bars ink, complete violet.
- A template change in `base.html` moves every page's bench hash; append to `shell.css` instead.
- In the cloud `tests/test_upgrade_path.py::test_a_050…` always fails (ATTACH with a `file:` URI); it passes in CI.
