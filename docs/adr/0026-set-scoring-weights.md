# 0026. Set scoring: inverse-frequency weight, swaps never in the score

- **Status:** accepted
- **Date:** 2026-11-11
- **Decided by:** the brief of issue #199 ("one engine, features on top"; swaps listed separately and never folded into the score); the weight formula is the implementer's choice inside it, for review on the pull request.

## Context

Several features need to answer "which sets does this pile of parts come from?": set detection in a lot (#200, #201, #202) and Buildable sets (#9). They must not each invent a score. The catalogue holds about 28,000 sets and 1.6 million inventory lines; a lot has some 2,000 distinct lines. A part that sits in thousands of sets (a 1 x 2 plate) says almost nothing about the origin of a pile, a part in two sets says a great deal. A near match (the right part in another colour, an older mould of the same part) is useful to show but is not evidence that the set is the origin.

## Options considered

1. **Count matches.** The number of lines or pieces covered. Simple, but common parts drown rare ones: a big set of bricks outranks the one set that holds the pile's rare parts.
2. **Inverse frequency per line, `w = ln(N / df)`** (N candidate sets, df the sets that hold the line). Rare lines weigh most, a line in every set weighs 0, no tuning constant. Standard IDF without smoothing: df is at least 1 for every line that is in the index, so the logarithm is defined; a line in all sets (which does not happen) weighs 0, which is the right answer for it.
3. **`ln(1 + N / df)`** (smoothed). Never 0, so a line every set holds still counts a little. Rejected: no line is in every set, and the smoothing lifts the weight of common lines, which is what the weighting is to prevent.
4. **Fold swaps into the score at a discount.** Raises recall for lots that mix colours. Rejected: the score would no longer say what is in the pile; a feature that wants swaps can read them and decide.

## Decision

Option 2. For each (part, colour) line, `w = ln(N / df)`. A set's **evidence** is the sum, over the lines it holds that the pile also has, of `w * min(have, need) / need`; its **coverage** is the evidence over the sum of `w` over all its lines. Sets are ranked by evidence, then coverage, then set id; absolute evidence rather than coverage, so a small set that happens to consist of one common brick does not outrank the large set that holds the pile's rare parts. A line is **distinctive** when at most 25 candidate sets hold it, and each set reports the distinctive lines found of its own.

Index semantics: candidates are sets with a live latest inventory and at least one line; spares are left out (ADR 0011); a minifigure counts through its parts (the figure's latest inventory, times its quantity in the set) and as a whole-figure line, two separate lines of the set; sub-sets (`inventory_set`) are expanded into their parent with the quantity multiplied, with a cycle guard.

**Swaps are never part of the score.** The same part in another colour, or an alternate mould (part relationships of type A and M, either direction), is listed per returned set, from the input's leftover on a line against the set's unmet lines. They enter no number: not the evidence, the coverage, the covered counts or the rank. A set that shares only swap lines with a pile is not ranked.

The engine is a Python service (`brickwork/core/set_scoring.py`) over the attached catalogue, read-only: inverted lists per line in compact arrays, built once per catalogue build and process (keyed by the catalogue's id space, its newest build, the file's stamp and the collection's activated builds), the ranking cached per input and build, the page's detail built fresh. Its API is `GET /api/v2/planning/set-scores` over a lot, a storage, all loose stock or a saved selection, with the MCP tool `get_planning_set_scores`; an arbitrary multiset is not an API input because a read is a GET and the contract ties every other method to a write scope, an event and an idempotency key.

## Consequences

- One definition of "how much of this pile does that set explain" for every feature; a feature that wants another reading (coverage first, a threshold, swaps) changes its use of the result, not the engine.
- The weight depends on the catalogue: a rebuild with more sets shifts every weight a little, and a cached result is dropped with the old build.
- The first query after a start or a new build pays for the index (seconds on 28,000 sets, hundreds of MB at the peak of the load); later queries touch only the sets that share a line with the pile.
- The distinctive threshold (25 sets) and the cut of 20 swaps per set are constants in the module, not settings.
- A feature that needs to score a list it holds in memory calls `score` from Python; if an API for that is wanted it needs its own decision about the contract's rule for non-GET reads.

## Links

Issue #199; [ADR 0011](0011-part-list-rule.md); the reference page Set scoring (`docs/reference/set-scoring.md`).
