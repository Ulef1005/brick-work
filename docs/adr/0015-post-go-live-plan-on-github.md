# 0015. The post-go-live plan lives in GitHub milestones

- **Status:** accepted
- **Date:** 2026-10-22
- **Decided by:** Ulf (maintainer), in the planning session that set up milestone 0; gate [#82](https://github.com/Ulef1005/brick-work/issues/82)

## Context

The build plan ended at the 0.5.0 go-live on 2026-10-18. The work after it (a guided first run, setting the real collection up on test, a stability release and new functionality) had no plan of its own: some of it sat in open issues (#10, #11, #12 and the to-verify issues), the rest only in conversation. Issues, dependencies and the maintainer's queues were already on GitHub, so a separate written plan would drift from them. The maintainer's planning rules put the plan into milestones, each with one checkable goal, a gate issue and a supporting deck.

## Options considered

1. **GitHub milestones in build order, with the post-go-live work as build milestones** — one milestone per phase, one issue per work item, Blocked-by links, a gate issue the maintainer closes; the new-functionality milestone is filled from the roadmap by a decision issue once testing is done.
2. **Roadmap only** — every new piece of work is an enhancement placed on the public roadmap (Now / Next / Later), with no milestones; nothing would tie onboarding and testing together or gate the 1.0 release on them.
3. **A new written project plan** — a phase list kept outside the repository; a second source next to the issues.

Recommendation at the time: option 1.

## Decision

The post-go-live plan is five GitHub milestones in this order: 0 (Planning on GitHub), A (Onboarding), B (Set up and test), 1.0 (Stability release) and C (New functionality). Each has one goal, a rough duration, a gate issue assigned to the maintainer and a deck indexed in [`docs/milestones/README.md`](../milestones/README.md). What C holds is decided in [#98](https://github.com/Ulef1005/brick-work/issues/98) after B, from the roadmap's open enhancements. No new project plan is written outside the repository.

## Consequences

- The order is the promise; milestones carry no due dates.
- Every milestone ends with a status report: its deck is updated with the work done, the decisions (each an ADR), a retrospective and what carries over, and its PDF is exported again, before the gate issue is closed.
- C is a build milestone fed from the roadmap; enhancements outside it stay on the roadmap as before.
- 1.0 waits on B: no stability release before the real collection has been set up and every workflow tested.

## Links

Milestones 0 (4), A (5), B (6), 1.0 (3), C (7); gate issues #82, #88, #96, #97, #99; decision #98; decks commit `2e1b4f1`.
