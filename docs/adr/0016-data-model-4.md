# 0016. Data model 4.0: Brick Work ids, a catalogue from the Rebrickable dump, one migration

- **Status:** accepted
- **Date:** 2026-10-23
- **Decided by:** Ulf (maintainer), on [#101](https://github.com/Ulef1005/brick-work/issues/101) (decisions of 22 and 23 Oct) and by approving the revised design on 2026-10-23

## Context

Brick Work 0.5 uses BrickLink's `(item_type, item_no)` as the identity of everything. Rebrickable and Brickset data is translated into it, and what cannot be translated becomes a `?` placeholder. Spike [#102](https://github.com/Ulef1005/brick-work/issues/102) showed that a local catalogue with set part lists can come only from Rebrickable's dump, because BrickStore's archive of BrickLink data has no shown permission. It also showed that the dump reaches BrickLink ids only through mappings, which are n:m: sticker sheets, `970cNN` legs whose BrickLink id depends on the colour, and assemblies. A Brick Work id touches 54 key references in 40 tables, so on 22 Oct the maintainer decided on a full redesign rather than patching the identity core. An initial design (22 Oct) was reviewed cold on 23 Oct ("approve with changes": two blockers, about 17–20 weeks) and revised; the revision is in [`docs/data-model-4.0/`](../data-model-4.0/README.md).

## Options considered

1. **Keep BrickLink keys as identity and add a Rebrickable catalogue beside them.** This is the smallest change, but every unmapped Rebrickable row stays a `?` placeholder, and the n:m cases cannot be expressed.
2. **A Brick Work id with provider links, patched into schema 3.x.** The identity changes, but the 40 tables keep typed pairs during a long transition.
3. **Schema 4.0 re-derived from the domain model** (two files, Brick Work ids, links with status, one migration with proof, API v2).

Recommendation at the time: option 3.

## Decision

Option 3, as designed in [`docs/data-model-4.0/data-model-design.md`](../data-model-4.0/data-model-design.md) with its DDL. In short:

- **Two files.** `catalogue.db` holds rebuildable reference data: the Rebrickable dump, mappings and optional BrickLink item lists. It is rebuilt into a new file and swapped in. `brickwork.db` holds what cannot be rebuilt: the collection, identity decisions, fetched part lists, local items, prices, keys and settings.
- **Brick Work ids are running numbers.** Every build reuses the ids it knows by provider key and never reuses a number. Items born in the collection are numbered from 1,000,000,000.
- **Providers link through `item_link`**: n:m, with status (`matched`, `inferred`, `manual`, `to_check`), method and evidence. A link can be scoped to one colour. A preferred BrickLink link exists per part and colour. "No match at a provider" is item state (`item_provider_status`). Only local or retired items can be merged away, with an audited, exact unmerge.
- **Part lists.** Onboarding imports the Rebrickable dump only; no account or key is needed. A copy names its part list by natural key `(set, version)` or as a fetched list. Its lines are updated in place on a switch and retired, never deleted. Rebrickable's latest version is the default. BrickLink's list can be chosen per set, by a global "prefer BrickLink when a key exists" switch, or in a part-list picker at Add. A copy that waits for BrickLink's list gets Rebrickable's list at once. It switches automatically only while nothing on it is checked; otherwise it asks. Minifigure parts come from the figure's own Rebrickable list.
- **BrickLink extras.** BrickLink's subset `quantity` includes `extra_quantity`, so required = quantity − extra and spare = extra.
- **Catalogue details.** Zero-part Rebrickable "sets" are classified by theme as a guess that a BrickLink link corrects. The dump's once-a-day rule is stated, not enforced. The picture source order is a setting.
- **The minifigure mapping.** It is first built once, privately, from BrickStore's database. The output lives under `data/` and stays out of the repository. Whether any figure mapping ships with every install is decided at the next public flip.
- **API v2** addresses items by Brick Work id with number lookups. **API v1 is switched off at 4.0** (`410 Gone`). `lego-add` and the House API pass-through switch at the cutover.
- **One migration from 3.3 with a proof in BrickLink space.** It carries the collection, prices, keys and API tokens, and the preference settings with the sync link. It does not carry events, `id_match` (including the 30 manual decisions), orders, identifications, Take/Give history, `source_records` or jobs; the migration report lists them. The 3.3 file is left untouched. The migration corrects the extras double count of BrickLink-sourced copies and lists each change.

## Consequences

- No code before this ADR; the work is the 4.0 milestone, ahead of milestone A, estimated at about 20 weeks (18–22, [`effort.md`](../data-model-4.0/effort.md)).
- The 0.5.x extras double count (`brickwork/core/add.py:332-336`) stays in 0.5.x and is corrected by the migration.
- Undo for changes made before 4.0 is gone with the events. The old file and the Borg archives keep them.
- `catalogue.db` joins the Borg unit.
- Clients of API v1 break at the cutover; the known ones switch in the same step.
- Shipping BrickLink-derived data (the figure mapping) remains open until the public flip. The BrickStore output must never enter the repository's history.
- Supersedes the identity parts of [0011](0011-part-list-rule.md) where they name BrickLink keys; its never-mixed rule stands and is now structural.

## Links

[#101](https://github.com/Ulef1005/brick-work/issues/101) (decisions), [#102](https://github.com/Ulef1005/brick-work/issues/102) (spike), [`docs/data-model-4.0/`](../data-model-4.0/README.md), ADRs [0006](0006-api-scope-and-conventions.md), [0011](0011-part-list-rule.md).
