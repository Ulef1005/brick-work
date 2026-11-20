# Brick Work

## Design reference
The app must follow the design in `design/`. Before building or changing a screen, and when asked to check compliance, follow `design/DESIGN-CHECK.md`:
- find the screen in `design/sources/frames.json`,
- compare against its PNGs in `design/screens/` (light and dark, 1440 / 1024 / 390),
- take exact values from the HTML in its screen folder (`design/screens/NN-<screen>/`) or the section in its `design/sources/BW *.dc.html` page,
- use tokens from `design/tokens/`, never new colours.

`design/sources/` is the design project's export; `design/` is organised per P2 by scripts; never hand-edit `sources/` or generated files. Report design gaps instead.

## LESSONS (read before you code; add a line when a task teaches one)
Each line cost a review round or a red run once. Newest at the bottom of its group.

**Screens and frames**
- Dialogs, sheets and overlays sit outside the `.b-prime` scope; a rule written for `.b-prime` never reaches them.
- `text-overflow: ellipsis` needs a block box (`display:block` or a block child) with `overflow:hidden`; on an inline span it does nothing.
- Node harness tests (`tests/*.cjs` with stubs) have no layout: they cannot prove geometry, spacing or truncation. Prove those with the rendered tests or `scripts/frame_check.py`.
- Check a frame with `python3 scripts/frame_check.py --only <folder> --report --keep <dir>` (it picks the venv itself), then open every capture: light and dark, 1440 and 390, frame and app side by side. A NOTE (0.1 % to 2 %) needs its regions named in the PR; no masks, no hidden elements.
- The registries in `scripts/frame_check.py` (TARGETS, VIEWPORT, TALL, CROP_BELOW, BODY_BUILT) and in `brickwork/demo/frames.py` are additive: on a rebase conflict keep both sides. A 390 frame that is an excerpt gets a CROP_BELOW entry (the bottom of the drawn tile row), not a mask.
- A picture in a tile has a fixed box (`width:100%;height:100%`, `object-fit:contain`) and a picture at the top of the page is `loading="eager"`. Otherwise the no-script capture rasterises it differently from run to run and `test_the_edge_states_render_the_same_twice` flakes.
- `test_the_edge_states_render_the_same_twice` is strict (0.01 %) when `CI` is set and allows 0.05 % on a developer machine, where a picture is sometimes rasterised 0.02 % differently from one capture to the next; the push run on main is the judge, never loosen the CI limit or add a retry.
- A state that waits for images in `design/screens/states.json` needs the wait in its script; a no-script state cannot have one, so give the image a fixed box instead.

**Data**
- A copy bar is six fields since schema 4.7: `[found, missing, total, figures, damaged, checked_by]`. Tests that compare a bar compare six.
- "Checked" is the status flag `Set is checked` OR `copy.checked_by`. Every reader (workbench, set detail progress, deductions, derived completeness, the Check page with no session) must read both.
- A schema step is additive and goes through `UPGRADES` in `brickwork/store4/connect.py`; a receipt written before it lacks the new column, so Undo compares through `as_current` (also for rows nested in a receipt, such as an order's `guard`).
- A review round finds the second reader of anything you add: after adding a column or a state, grep every place that reads its neighbour.

**CI and tests**
- A pull request sets `BW_NO_CHROME=1` and runs no Chrome test. Only the push run on `main` renders in Chrome, so a rendered test is not proved by a green PR check: run `scripts/check.sh` locally first. Pixel and geometry tolerances must hold on the Ubuntu runner's fallback font (the phone sub row is 38 px there, 40 with the shipped fonts).
- `tests/bench_reference.json` changes only when the intended entry changes; a changed hash elsewhere is a regression, not a baseline to refresh.
- Do not run the same gate twice for one tree: run targeted tests while you work, the full `scripts/check.sh` once at the end, and the read-only review in the background on the first commit.

**Commits**
- Commit path-limited with the message in a file: `git commit -F <file> -- <paths>`. A commit that changes app source needs a change under `docs/` or a `Docs: none, <reason>` trailer; a CHANGELOG entry is not a docs change.
