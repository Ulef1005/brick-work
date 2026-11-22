# Milestone V: handoff (question pages)

Written 2026-11-22 by the cloud thread that built milestone V, so another agent can pick up the remaining work. Repo-only record, not part of the docs site (`docs/milestones/` is in `exclude_docs`).

V = GitHub milestone 27, "V — Question pages on the site". It has two issues: [#544](https://github.com/Ulef1005/brick-work/issues/544) (seven question pages) and gate [#549](https://github.com/Ulef1005/brick-work/issues/549), which Ulf closes.

The full state is on GitHub, in [#544's handoff comment](https://github.com/Ulef1005/brick-work/issues/544#issuecomment-7081534241) and [#594's handoff comment](https://github.com/Ulef1005/brick-work/pull/594#issuecomment-7081535372).

## Done
- [Draft PR #594](https://github.com/Ulef1005/brick-work/pull/594) is on branch `v/544-question-pages` (commits `95bd62fd` and `51ddd64a`). It holds:
  - the seven pages (`scripts/site/pages/question-1..7-*.html`);
  - a Questions section in `llms.md`;
  - `/questions/` in the sitemap;
  - the LEGO® name test and the per-page checks.
- Site tests pass locally. CI is green on both commits.
- #544 is claimed, and the demo's coverage per page is posted on the issue.
- The marketing advisor's answer, with the seven draft texts, is in [v-question-pages-marketing-advice.md](v-question-pages-marketing-advice.md).

## Decisions (Ulf, 2026-11-22)
- P7 ends in the demo's Sets list ("Demo Sets list", on a decision card).
- The docs-fallback rule is recorded in marketing's decision log ("yes").
- Earlier, in the thread: "draft the pr" (draft early, ahead of the "after #526" timing), and "relay them to marketing", done through the ask-role advisor.

## The marketing decision-log entry
- Target: ai-wiki `wiki/agentic/roles/marketing/brick-work/marketing-brick-work-log.md`, section `## Log`, as the last entry.
- It was appended, uncommitted, on 2026-11-22 to `/Users/ulf/Workspace/ai-wiki` on `ulfs-macbook-pro-local` (main at `c2111f81`). That is not the checkout the wiki-agent uses, so the wiki-agent copies it from the appendix below.

## Waiting, and on whom
1. **brick-work-marketing**
   - Review the texts in #594.
   - Decide the advisor's edits: the P4 copy rule, four Claims rows, "LEGO.com" never as link text, and naming Rebrickable and BrickLink.
   - Verify the Pick a Brick pause and "free"/"new sets only" on LEGO's replacement-parts page.
2. **#542 (#526)** merges first. Then merge main into `v/544-question-pages` and keep both sides.
3. **brick-work-design**
   - Write the BRAND.md § 9 and DESIGN-CHECK.md line 80 exception lines.
   - Add a link style for `.steps .d a`.
4. **Whoever picks it up**
   - Run the full `scripts/check.sh` after the merge.
   - Check the frames at 1440 and 390, light and dark.
   - Mark #594 ready. Ulf merges it.
   - Make the milestone deck `docs/milestones/v-question-pages.pdf` for #549 (not started).

## Appendix: the decision-log entry, verbatim

- 2026-11-22 — brick-work (the cloud build thread for milestone V, relayed by Ulf; ask-role advisor, Opus 5.5, read-only) asked for the last step and the texts of the seven #544 question pages, given what the static demo at main 83918ec shows (Set Inspector and Sell this copy yes; Lot Sorter, Order missing parts, QR labels and Build Scout no; the sync page empty). Advice: P1, P2 and P5 end in the demo (Set Inspector, a set's Sell this copy card, Storage); P3, P4 and P6 end in the docs (bulk-lot tutorial, order-missing-parts guide, build-from-what-you-have tutorial, P6 with the Matchmaker demo in its text); P7 ends in the demo's Sets list, not the sync page. The rule "a page whose feature the demo cannot show ends in the docs" (#544, credited to marketing 2026-11-20) was not in this log before and is recorded here. The seven draft texts are in draft PR #594 for brick-work-marketing's review. Proposed and not yet written: P4's copy rule says loose stock first only with Use loose stock on (off by default); four Claims rows (Sell this copy, Storage and QR labels, Order missing parts, Lot Sorter pull list); link text never "LEGO.com" (the #544 name test fails it); naming Rebrickable and BrickLink in the answer-first sections (opinion). Still unverified: the Pick a Brick pause, and "free" and "new sets only" on the LEGO Group's replacement-parts page. Ulf: P7 "Demo Sets list" (decision card); the docs-fallback entry "yes".
