---
audience: user
verified: 1.0
---

# Metrics

## Completeness

| Field | Value |
|---|---|
| Definition | The state of one copy: Sealed, Complete or Incomplete, chosen by hand (`manual`) or worked out (`derived`); none recorded shows as Not checked |
| Formula | Derived: `Complete` if the copy has the "Set is checked" status and no non-spare part outside a minifigure has `missing > 0` or `damaged > 0` and no minifigure has `missing > 0`; else `Incomplete`. Manual: the chosen value |
| Unit | State (Sealed, Complete, Incomplete, Not checked) |
| Good | Complete |
| Since | 0.5.0 |
| Code | `brickwork/store4/copies.py::derived_completeness` |

A copy added without a completeness shows Not checked. Choosing a value makes it manual; choosing the value a derived copy already has keeps it derived. The API returns the stored and the derived value at `GET /api/v2/copies/{id}/completeness`, with `completeness_source`, `checked`, `missing`, `damaged` and `missing_figures`.

Plain-language explanation: [Concepts › Completeness](../concepts/completeness.md).
