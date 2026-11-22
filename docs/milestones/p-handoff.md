# Milestone P handoff: build state and custom sets

Pick-up point for milestone P ([GitHub milestone 21](https://github.com/Ulef1005/brick-work/milestone/21)), written 22.11.2026 by the milestone P cloud thread. It is a repo-only record (`docs/milestones/` is not built into the site). The issue comments it links hold the details.

## State

- Open issues: #14 build state and parts availability (approved), #13 custom sets and MOCs (candidate), #37 BrickLink Custom Items (approved). #22 was closed on 18.11. (its content lives in #14 and #13).
- Order (Ulf, 18.11.): #14, then #13, then #37.
- **Research only:** no code, no `p/*` branch, no PR, no issue claimed.
- No design frames exist for #14 or #13, only the Claude Design hand-offs of 18.10. on the issues.

## Decisions (Ulf, 22.11.)

1. Research now, code later: code starts after v1.2 ships (prod target 30.11.).
2. #14 is approved ("14 is approved").
3. Lent parts go in a new `copy_lending` table, not `stock_transfer`, because `stock_transfer.stock_id` is NOT NULL and making it nullable is a table rebuild, not an additive step. [Proposal on #14](https://github.com/Ulef1005/brick-work/issues/14#issuecomment-7081174551), [decision](https://github.com/Ulef1005/brick-work/issues/14#issuecomment-7081182150).
4. #13: fetching a MOC by its Rebrickable number is dropped ("drop it"). Rebrickable removed its MOC API on 2020-04-19, so a published MOC comes in from a downloaded file. [Facts](https://github.com/Ulef1005/brick-work/issues/13#issuecomment-7081106791).
5. The test MOC is Rebrickable MOC-154520, with an LDCad parts bin export (`.pbg`): a fifth import format, and its lines repeat, so they must be summed. [Format](https://github.com/Ulef1005/brick-work/issues/13#issuecomment-7081174755).

## Waiting for

| Issue | Waits for |
|---|---|
| #14 | v1.2 shipped (milestone U, owned by local sessions); the schema slot after N: branch `n/551-added-via` already takes 4.7 → 4.8, so #14 takes the next number; frames after v1.2, with Ulf's written approval |
| #13 | #14 merged; LDraw → BrickLink coverage measured on MOC-154520 (needs a Rebrickable key on an install that reaches rebrickable.com, which is blocked from the cloud environment and bot-checked in the browser); a check that no BrickLink catalogue item uses `MOC-` or `BW-` (needs a full catalogue dump); label `candidate` → `approved`; frames |
| #37 | One real BrickLink export (order XML or store inventory) that contains a custom item (BrickLink was down on 22.11.); #13 merged (`BW-` namespace) |

## Next steps

Per issue, in the pick-up comments: [#14](https://github.com/Ulef1005/brick-work/issues/14#issuecomment-7081298392), [#13](https://github.com/Ulef1005/brick-work/issues/13#issuecomment-7081298664), [#37](https://github.com/Ulef1005/brick-work/issues/37#issuecomment-7081298878). In short:

1. #14 backend on `p/14-build-state`: a schema step through `UPGRADES` (`copy.build_state` plus `copy_lending`); one pool function replacing `workbench.available()` for every reader (grep `available(`); derived completeness incomplete while a lending is open; part out (keep or dissolve), return and build state over the API, CLI and MCP, each one undoable event.
2. #13 on `p/13-custom-sets`: update Decision 2 in the issue body, measure coverage, then the custom identity and the import.
3. #37 on `p/37-custom-items`: confirm the marker (empty `ITEMID` plus `DESCRIPTION`) on the sample first.

## Notes

- The "What exists" sections in #14, #13 and #37 name 4.0 paths (`core/schema.sql`, `copies`). The real ones are `brickwork/store4/brickwork.sql` (`copy`, `copy_part`, `stock_transfer`), `brickwork/core/workbench.py` and `brickwork/core/completeness.py`.
- Don't touch milestone U (v1.2, local brick-work sessions), N (`n/*`) or V (`v/*`).
