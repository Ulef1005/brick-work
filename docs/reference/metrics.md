# Metrics

## Completeness

| Field | Value |
|---|---|
| Definition | The state of one copy: Sealed, Complete or Incomplete, chosen by hand (`manual`) or worked out (`derived`); none recorded shows as Not checked |
| Formula | Derived: `Complete` if the copy has the "Set is checked" status and no non-spare part outside a minifigure has `missing > 0` or `damaged > 0` and no minifigure has `missing > 0`; else `Incomplete`. Manual: the chosen value |
| Unit | State (Sealed, Complete, Incomplete, Not checked) |
| Good | Complete |
| Since | 0.5.0 |
| Code | `brickwork/core/completeness.py::derived_state` |

A copy added without a completeness starts as derived Incomplete; choosing a value makes it manual. The API returns both the stored and the derived value at `GET /api/v1/copies/{id}/completeness`.

Plain-language explanation: [Concepts › Completeness](../concepts/completeness.md).
