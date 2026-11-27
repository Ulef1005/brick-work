# Milestone decks

Each milestone has one clearly defined goal, set in its GitHub milestone and explained by a short deck (goal, what it delivers, how the gate is proven). When a milestone completes, its deck becomes its status report: every piece of work done with the achieved items highlighted, the important decisions (each an ADR in `docs/adr/`, summarised on a slide), what went well, what went badly and the room for improvement. Rules: ai-wiki `app-standard-github` § Milestones.

The decks are Slides artifacts on claude.ai (private to the owner); the PDFs here are their exports. The milestones follow the 0.5.0 go-live; the order is the promise, there are no due dates.

| Milestone | Goal in one line | Rough duration | Deck | PDF |
|---|---|---|---|---|
| 0 — Planning on GitHub | The post-go-live plan lives on GitHub; Ulf passes the gate | under 1 week (done 22 Oct) | [deck](https://claude.ai/artifact/RoWGLs5g4t18pGes93DyQx) | [status report PDF](0-planning-on-github.pdf) |
| 4.0 — Data model | Prod runs on schema 4.0: Brick Work ids, the catalogue from the Rebrickable dump, the collection migrated from 3.3 with a proof, API v2 | 18–22 weeks, before A (done 28 Oct, in 6 days; released as 0.6.0, milestone closed 4 Nov) | [deck](https://claude.ai/artifact/Jw4j5TdsHf7dYma9andG9R) | [status report PDF](4.0-data-model.pdf) |
| A — Onboarding | A new user goes from a fresh install to their own collection through one guided flow, with a local catalogue that holds set part lists | 2–3 weeks (re-planned 3 Nov after 4.0; was 5–6; built and closed 3 Nov, released as 0.8.0) | [deck](https://claude.ai/artifact/MF6FaLNA1kdaKsu5a1LBZY) | [status report PDF](a-onboarding.pdf) |
| B — Set up and test | The real collection is set up on test through onboarding and every workflow passes on it | 2–3 weeks (re-plan against 0.8.0 accepted 4 Nov; built 4–9 Nov, gate #96 with Ulf) | [deck](https://claude.ai/artifact/RtsxYVusN2F7dTWefzDGC6) | [status report PDF](b-set-up-and-test.pdf) |
| 1.0 — Stability release | Stable schema, tested upgrades from 0.5.x, published image | 2–3 weeks (built 4–5 Nov; v0.9.0 tagged 5 Nov, the gate waits on the first GHCR push) | [deck](https://claude.ai/artifact/HNUr6aVaeDdsXbAwxZMyfp) | [status report PDF](1.0-stability-release.pdf) |
| C — New functionality | The new functionality chosen after B ships: set detection, Build Scout, one order list, Change variant, grouped part lists, the docs standard | 11–16 Nov (scope decided 11 Nov, #98; built and closed 16 Nov; ships on prod with 1.1 together with D) | [deck](https://claude.ai/artifact/T43hZkMmcZAD9zzmDjAKif) | [status report PDF](c-new-functionality.pdf) |
| D — Value, selling and custom sets | Value and gain per copy with an insurance report, Sell this copy, part out, Found in, storage labels with QR codes and instruction downloads, then a code review of everything built for C and D | Decided 12 Nov that C and D ship together as 1.1; built and reviewed by 16 Nov; its gate (#430) passes when 1.1 is on prod | [deck](https://claude.ai/artifact/FqAkwCdLQsosc3u91sKjuD) | none: the deck is the status report (Ulf, 17 Nov) |
| M — First install, first hour | A collector on Docker, Unraid or a NAS gets to a working install without Git, and the first screen's promises work there | 18–23 Nov (v1.1.1 on 19 Nov, the rest with v1.2.0 on 23 Nov; listed in the MCP Registry 23 Nov) | [deck](https://claude.ai/artifact/LZXooxFkfQ3tq6gJDTKN6F) | [status report PDF](m-first-install-first-hour.pdf) |
| U — Brand and redesign | Every screen in the approved B′ look, light and dark, released as v1.2 before November ends | 20–23 Nov (built in four days; v1.2.0 on prod 23 Nov, a week early) | [deck](https://claude.ai/artifact/4Xbk6uKrVY5AKit9e4RpUk) | [status report PDF](u-brand-and-redesign.pdf) |
| V — Question pages on the site | Seven question pages on the site that answer a search and end in the demo | Built before v1.2, live with the v1.2.0 tag on 23 Nov | [deck](https://claude.ai/artifact/3YgdKdCfJV94jHwNV3X64t) | [status report PDF](v-question-pages.pdf) |

Milestone U's handoff for the next agent is [u-brand-and-redesign-handoff.md](u-brand-and-redesign-handoff.md).

## Handoffs

Dated records of a milestone built by several agents. A record is not kept up to date: the live status is on the GitHub issues.

- [N: Sync and files, as of 22 November 2026](n-handoff.md), gate #525
- [O: Faster at the table, as of 22 November 2026](o-faster-at-the-table-handoff.md), umbrella #303
- [P: Build state and custom sets, as of 22 November 2026](p-handoff.md), issues #14, #13 and #37
