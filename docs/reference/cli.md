# Command line

*Since 0.5.0.*

`brickwork` is the admin command line. It reads the same [settings](settings.md) as the app, so it works on the database named by `BW_DB_PATH`. In a Docker install, run it inside the container:

```text
docker compose exec brickwork brickwork <command> ...
```

> **On `main` (the 4.0 development line):** `setup` creates a 4.0 collection and says where `catalogue.db` goes, `mcp` talks API v2 (`/api/v2`), `migrate` (the BrickTracker-era importer) is gone (a 3.3 collection moves with `migrate4`), and `sync` and `import-bricktracker` run on the 4.0 store. The catalogue itself is built with `python -m brickwork.store4` (see [catalogue](#catalogue)). This page otherwise describes release 0.5.

Every command takes `--json` to print its result as JSON instead of plain lines, and `-h` for its usage. A command that fails prints the reason on standard error and exits with status 1. With `BW_READ_ONLY` on, the `token` and `wishlist` commands that change something are refused.

## setup

*Since 0.5.0.*

Creates the database at `BW_DB_PATH` (and its folder) if it does not exist yet, with the freshness rules a new collection starts with (prices 30 days, metadata 365 days, pictures never) and the three statuses Brick Work itself reads: *Set is checked*, *Box present* and *Instructions present*, which cannot be renamed or archived. Run it once before the first start. Running it again changes nothing, and a database set up by an older version is refused with the fix named.

```text
brickwork setup
```

## check

*Since 0.5.0.*

Checks the database: SQLite integrity and foreign keys of the collection, SQLite integrity of the catalogue file beside it, and the row count of every table. It then checks that the two files belong together (*since 4.0*), one named check each:

- `binding`: the collection is bound to this catalogue and every build it activated is in the catalogue file.
- `born_keys`: every catalogue item and colour in the collection has the same id and born key in the catalogue.
- `inventory_keys`: every part list the collection names (a set or figure and a version) exists in the catalogue.
- `digests`: projected items agree with the catalogue row they came from (once the collection is reconciled), and the part lists the collection names agree with their own lines.

A failed check prints what is wrong and the fix (restore the pair from one archive, or `catalogue rebuild`, or reconcile). A copy whose part list changed in the catalogue is counted, not a failure. Opens the files read-only. Exits with status 1 when a check finds a problem. The **Database** page of Tools & Admin runs the same check and keeps its result; this command does not.

```text
brickwork check
```

## worker

*Since 0.5.0.*

Works through the queued imports once (up to 100 jobs) and exits. Use it with `BW_EMBEDDED_WORKER=0` on a headless install, run periodically, for example from cron.

```text
brickwork worker
```

## token

*Since 0.5.0.*

Creates, lists and revokes API tokens. A new token's secret is printed once; only its hash is stored.

```text
brickwork token create --name NAME [--scope SCOPES] [--expires DAYSd]
brickwork token list
brickwork token revoke ID
```

| Argument | Command | Meaning |
|---|---|---|
| `--name NAME` | `create` | Required. A unique name, 1 to 80 characters; `bootstrap` is reserved. |
| `--scope SCOPES` | `create` | Comma-separated: `read`, `write`, `admin`. Default `read`. |
| `--expires DAYSd` | `create` | Lifetime in days, such as `90d`. Default: no expiry. |
| `ID` | `revoke` | The token id from `token list`. |

## mcp

*Since 0.5.0.*

Runs the MCP server for an assistant. By default it speaks MCP over standard input and output and calls the app's API. Read tools only, unless writes are allowed and the token has the scope for them.

```text
brickwork mcp [--transport stdio|http] [--in-process] [--api-url URL]
              [--token-file FILE] [--allow-write] [--host HOST] [--port PORT]
```

| Argument | Default | Meaning |
|---|---|---|
| `--transport` | `stdio` | `stdio` for a local assistant; `http` serves Streamable HTTP at `/mcp`. The HTTP server refuses to start without a login password, as the app does. |
| `--in-process` | off | Use the local database directly through an in-process API instead of calling a running app. |
| `--api-url URL` | `http://127.0.0.1:5000/api/v2` | The API to call when not in-process. For a default install, use `http://127.0.0.1:3333/api/v2`. |
| `--token-file FILE` | `BW_API_TOKEN` | A file holding the API token. Without it, the `BW_API_TOKEN` setting is used. |
| `--allow-write` | off | Turns on write tools, as `BW_MCP_WRITE=1` does. |
| `--host HOST` | `127.0.0.1` | Listen address for `--transport http`. |
| `--port PORT` | `5000` | Listen port for `--transport http`. |

## wishlist

*Since 0.5.0.*

Manages named wishlists and their wishes. A list is named by its id or its exact name. Run `brickwork setup` first.

```text
brickwork wishlist list [--archived]
brickwork wishlist create NAME
brickwork wishlist rename LIST NAME
brickwork wishlist archive LIST
brickwork wishlist restore LIST
brickwork wishlist move LIST WISH_ID [WISH_ID ...]
brickwork wishlist copy LIST WISH_ID [WISH_ID ...]
brickwork wishlist export LIST --format bricklink|rebrickable [--kind sets|parts]
brickwork wishlist undo EVENT_ID
```

| Argument | Command | Meaning |
|---|---|---|
| `--archived` | `list` | Include archived lists. |
| `NAME` | `create`, `rename` | The list's (new) name. |
| `LIST` | all but `list`, `create`, `undo` | A wishlist id or exact name. For `move` and `copy` it is the target list. For `export`, `all` exports every list. |
| `WISH_ID` | `move`, `copy` | Wish ids (the long hexadecimal ids) to move or copy, up to 500. |
| `--format` | `export` | Required. `bricklink` (Wanted List XML) or `rebrickable` (CSV). |
| `--kind` | `export` | `sets` or `parts`. Default `parts`. |
| `EVENT_ID` | `undo` | The event id a wishlist change printed. |

`export` prints the file to standard output and a summary (exported and omitted lines) to standard error.

## migrate4

*Since 4.0.0.*

Builds a new 4.0 collection file from a 3.3 one. It is the command `python -m brickwork.store4 migrate`, under the name the design gives it. The 3.3 file is opened read-only and never changed; the new file is published only when the independent proof passes. Run it on a copy first.

```text
brickwork migrate4 --in OLD_DB --catalogue CATALOGUE_DB --mappings MAPPINGS_DIR
                   --out NEW_DB --report REPORT_DIR [--pin PROOF]
```

| Argument | Meaning |
|---|---|
| `--in` | Required. The 3.3 `brickwork.db`. |
| `--catalogue` | Required. The `catalogue.db` the new ids are minted against. |
| `--mappings` | Required. The folder of mapping files that catalogue was built with. |
| `--out` | Required. The new file. It must not exist. |
| `--report` | Required. A new or empty folder for the proof and the report. |
| `--pin` | Optional. The `proof.json` or `summary.md` of an earlier run: refuse unless the catalogue and the mapping files are identical to that run's. |

The exit status is 0 when the proof passed and the file was published, 10 when the proof failed, 11 when the command refused before writing, and 12 when 3.3 rows need a decision.

## import-bricktracker

*Since 0.5.0; on the 4.0 store since 4.0.*

Imports a BrickTracker collection into the current database in two steps: make a plan, then apply it. BrickTracker stores Rebrickable numbers, so every set, part, figure and colour the catalogue knows is placed exactly; the rest is listed in the plan as not placed. One import is one event that **Undo** takes back ([Import from BrickTracker](../how-to/import-from-bricktracker.md)).

```text
brickwork import-bricktracker APP_DB [--plan-only] [--decisions DECISIONS_JSON]
brickwork import-bricktracker --apply PLAN_ID [--decisions DECISIONS_JSON]
```

| Argument | Meaning |
|---|---|
| `APP_DB` | The BrickTracker `app.db` of any version, opened read-only. Give either this or `--apply`. |
| `--plan-only` | Make the plan and stop; it prints the plan id, the summary and what is not placed. |
| `--apply PLAN_ID` | Apply a stored plan. A plan applies once. |
| `--decisions` | A JSON file mapping row keys (`copy:ID`, `stock:ID`, `lot:ID`, `wish:N:SET`) to `add` or `skip`. |

## catalogue

*Since 0.5.0.*

Shows how the catalogue stands and loads the optional BrickLink item lists. The catalogue (`catalogue.db`, beside the collection) is built and updated with `python -m brickwork.store4`; these two commands are the same operations under the app's name.

```text
brickwork catalogue status
brickwork catalogue import bricklink --from DIRECTORY
```

`status` prints the catalogue's builds, the activations in the collection, the last reconcile and the newest Rebrickable download. `import bricklink` builds a new catalogue with the BrickLink item lists found in `DIRECTORY`, activates it and reconciles the collection with it. The Rebrickable download and build are `python -m brickwork.store4 --data DIR catalogue download` and `catalogue import`; a catalogue copied in by hand needs `catalogue reconcile` once. **Tools & Admin → Catalogue** does the download, the build, the rebuild, the BrickLink lists and the reconcile from the browser ([Settings and maintenance](../how-to/settings-and-maintenance.md#catalogue)); the app also reconciles a catalogue that is not reconciled yet when it starts, and `brickwork worker` does the same.

## sources

*Since 0.5.0.*

Shows each source with its key state (never the key), its daily budget and the calls used today.

```text
brickwork sources status
```

## import

*Since 0.5.0.*

Queues the normal import of one item (a BrickLink type letter and a number, or the Rebrickable number) and runs it here, printing the progress. The item must be one Brick Work knows.

```text
brickwork import {S,P,M,G,B,C,I,O} ITEM_NO
```

## jobs

*Since 0.5.0.*

Lists the item jobs, newest first, or only the ones with a failed step. `retry` puts the failed steps of a job (or one step) back and runs the job here.

```text
brickwork jobs [--failed]
brickwork jobs retry JOB [STEP]
```

## brickset

*Since 0.5.0.*

Fetches Brickset's properties and retail price for the given sets, or for every set you hold or want when none is given. It runs each set's `metadata` step here and counts against Brickset's daily budget.

```text
brickwork brickset refresh [SET ...]
```

## prices

*Since 0.5.0.*

Fetches BrickLink's prices for one set you hold or want, new and used. It runs the set's `market_price` step here.

```text
brickwork prices refresh SET_NUM
```

## settings

*Since 0.5.0.*

Shows the preferences in force and changes one.

```text
brickwork settings show
brickwork settings set KEY VALUE
```

`KEY` is one of `bricklink_region`, `bricklink_currency`, `incomplete_discount_pct`, `retail_country`, `source_priority`, or `import_order:KIND` with `KIND` one of `set`, `part`, `minifigure`, `instructions`, `box`, `gear`, `book`, `catalog`. The two orders are JSON: `source_priority` is `{"pictures": {"part": ["bricklink"]}}`-shaped (see **Settings** in Tools & Admin), an import order lists the six steps once each. The BrickLink region and currency are locked once chosen; `BW_PRICE_SETTINGS_LOCK=0` unlocks them.

## sync

*Since 0.5.0; on the 4.0 store since 4.0.*

Collection sync with Rebrickable and Brickset ([Sync with Rebrickable and Brickset](../how-to/sync-collection.md)). Row keys of a plan name an item: `owned:ITEM_ID` or `wanted:ITEM_ID`.

```text
brickwork sync {rebrickable,brickset} {status,lists,link,pull,send,connect,paste,remove,test} [options]
```
