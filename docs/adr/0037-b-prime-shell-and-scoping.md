# 0037. The B′ shell: scoped component CSS, guarded legacy rules, four groups on top

- **Status:** accepted; builds on [0036](0036-b-prime-tokens-and-type.md)
- **Date:** 2026-11-20
- **Decided by:** Ulf (direction B′ Drawer Tag and its frames, design/APPROVALS.md); brick-work-product for the order inside #492 (20 November 2026, issue comment on #492); brick-work-design for the shell heights and the band check (20 November 2026, message to the build session)

## Context

The approved frames draw the shell as four groups in a top bar, a row of entries under it, and on a phone a lockup bar, the row and a tab bar. The app had a sidebar, group sheets that opened from the phone tab bar, and a header. The frames' CSS (`B_COMPONENTS` in `design/sources/b/b_frames.py`) has to reach the app without a second copy that drifts, and without changing a screen that is not rebuilt yet.

## Decision

- **The frames' CSS is generated.** `scripts/b_prime_css.py` reads `B_COMPONENTS`, `DARK_CSS` and `SWAPS` with `ast` and writes `static/brickwork/b-prime.css`, every rule under the root class `.b-prime`. A rule changes in the frames first. A rule the generator cannot scope (an at-rule, a nested block, a selector on html, body or `:root`) stops the build. The frames draw the phone row's entries as `<span>` and the tab bar's as `<div>`; the app uses links, so the generator adds `.psub a` and `.tabbar a` beside them.
- **Scoping outranks legacy rules by specificity, not by `all: revert`.** The scope carries three `:not(#_)`, so a `.b-prime` rule beats any class-only legacy rule, `bw-*.css` included. Measured on frame 01, light, 1440, pinned Chrome 157 (device scale 2, a channel off by more than 16): the shell band differs by 0.019 % and the whole page by 0.002 % with the guards in place; without them the whole page differed by 4.7 %. `all: revert` was tried and gave 9.3 % on the band and broke SVG presentation attributes.
- **Legacy global rules skip `.b-prime`.** `scripts/legacy_guard.py` rewrites every selector of `toni.css`, `shell.css` and `remaining.css` to `:where(:not(.b-prime, .b-prime *))` on its subject, so a rebuilt subtree is untouched and an unrebuilt page is untouched too (844 screen-gate captures of main against this branch show no systematic change; every difference is under the gate's 0.05 %, except Storage labels, which differs from itself between two runs of main). After editing a legacy file run `python3 scripts/legacy_guard.py apply`; `check.sh` checks it.
- **The shell is plain links.** Four tabs on a desktop, each to the first entry of its group, and the group's entries in the row under them; on a phone the same entries sit under the lockup bar and the groups are the tab bar. Both sets are in the page and CSS shows one at 1024 px. Gear, Books and Catalogs stay hidden until held. There is no Sync entry until milestone N. The sidebar, the group sheets, the scrim and the appearance dialog are removed; the theme switch is the page Manage › Appearance, which already existed. Counts left the navigation and stay on their pages. Every old URL keeps working.
- **The heights are the frames'.** `--tw-topbar-h` (60 desktop, 56 phone), `--bw-sub-h` (44, 40) and `--tw-tabbar-h` (78) in `shell.css` equal what `scripts/b_prime_css.py shell_heights()` reads from the frame CSS (the phone row has no height of its own: 40 px, measured). A test compares them.
- **The app is checked against the frames in one browser.** `scripts/frame_check.py` renders the frame HTML and the built page in the pinned Chrome and compares them, never the committed frame PNGs (another browser build, about 5 % sub-pixel drift). The band rule is design-builder 1.5.5: up to 0.1 % passes, 0.1 to 2 % passes with a one-line note naming the regions, above 2 % or a height difference above 10 % of the taller shot fails. `--band` compares only the shell band, so the shell is checked before the page bodies are rebuilt. The pixel gate stays out of `check.sh` (Deviation B11); only the check's count line runs there.

## Consequences

- Frame 01, shell band: 0.02 % at 1440 (pass), 0.96 % at 390 in light and dark (note: the search and add icons of the lockup bar sit a few px from the frames' centres, because two 41 px targets must not overlap where the frames put the icons 38 px apart; the tab bar matches).
- The shell's page bodies are not part of this step; each screen issue brings its own frame data into the `frames` world of the gate.
- Tests of the removed sidebar, sheets and scrim are deleted or replaced by tests of the new links; `tests/test_shell_b.py` holds the new contract.
