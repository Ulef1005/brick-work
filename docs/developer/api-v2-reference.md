# API v2 reference

Every operation of the REST API at `/api/v2`, generated when the site is built from [the OpenAPI contract](../brickwork/openapi-v2.yaml), the file the app itself checks its routes against. Authentication, tokens and worked examples are in the [API v2 contract](../brickwork/api-v2.md) guide.

## Part membership

`GET /api/v2/items/{id}/supersets?color=<id>` lists catalogue sets and minifigures containing a part in one Brick Work colour. It reads local data only. Use a read token. Merged item ids redirect to their survivor.

Optional query parameters: `type=all|sets|minifigures`, `q`, `sort=newest|oldest|name|number`, `limit` (1–100, default 15), and `offset` (default 0). Owned copies and loose figures come first and replace their catalogue item’s row. Multiple owned copies remain separate. Spare parts are excluded. Set membership includes expanded subsets and figure components.

The `data` rows carry item bodies, quantity, ownership, copy/stock identity, label, storage, year, theme and wishlist state. `counts` counts distinct catalogue sets and minifigures; `total` counts displayed rows after filtering. `catalogue=false` means only owned holders are available; `colour_unmatched=true` means unknown-colour catalogue membership cannot be assigned to the requested colour.

The generated MCP tool `get_part_supersets` accepts a provider, kind, part number and provider colour number. It resolves item and colour before making the REST request. The full surface now has 204 implemented operations and 77 MCP tools.

## All operations

```python exec="on" idprefix=""
from scripts.docs_reference import api_v2
print(api_v2())
```
