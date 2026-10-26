# Command line

*Since 0.5.0.*

`brickwork` is the admin command line. It reads the same [settings](settings.md) as the app, so it works on the database named by `BW_DB_PATH`. In a Docker install, run it inside the container:

```text
docker compose exec brickwork brickwork <command> ...
```

> **On `main` (the 4.0 development line):** `setup` creates a 4.0 collection and says where `catalogue.db` goes, `mcp` is refused until API v2, and `migrate` below is gone: a 3.3 collection moves with `python -m brickwork.store4 migrate`. This page otherwise describes release 0.5.

Every command takes `--json` to print its result as JSON instead of plain lines, and `-h` for its usage. A command that fails prints the reason on standard error and exits with status 1. With `BW_READ_ONLY` on, the `token` and `wishlist` commands that change something are refused.

## setup

*Since 0.5.0.*

Creates the database at `BW_DB_PATH` (and its folder) if it does not exist yet. Run it once before the first start. Running it again changes nothing.

```text
brickwork setup
```

## check

*Since 0.5.0.*

Checks the database: SQLite integrity, foreign keys, and the row count of every table. Opens the database read-only. Exits with status 1 when the integrity or foreign-key check finds a problem.

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
| `--api-url URL` | `http://127.0.0.1:5000/api/v1` | The API to call when not in-process. For a default install, use `http://127.0.0.1:3333/api/v1`. |
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
| `WISH_ID` | `move`, `copy` | Wish ids to move or copy, up to 500. |
| `--format` | `export` | Required. `bricklink` (Wanted List XML) or `rebrickable` (CSV). |
| `--kind` | `export` | `sets` or `parts`. Default `parts`. |
| `EVENT_ID` | `undo` | The event id a wishlist change printed. |

`export` prints the file to standard output and a summary (exported and omitted lines) to standard error.

## migrate

*Since 0.5.0.*

Builds a new Brick Work database from an older tracker's database. The old files are opened read-only and never changed. Writes a row-count and checksum proof to the report folder.

```text
brickwork migrate --app APP_DB --decisions DECISIONS_JSON --catalogue CATALOGUE_DB
                  --out NEW_DB --report REPORT_DIR
                  [--extras EXTRAS_DB] [--catalogue-src XML_DIR] [--replace]
```

| Argument | Meaning |
|---|---|
| `--app` | Required. The old tracker's `app.db`. |
| `--decisions` | Required. The identity decisions JSON file. |
| `--catalogue` | Required. A BrickLink catalogue database (`bricklink-catalog.db`). |
| `--out` | Required. Path of the new database. An existing file is refused unless `--replace` is given. |
| `--report` | Required. Folder for the proof (`proof.md`). |
| `--extras` | Optional. The old extras database, read-only. |
| `--catalogue-src` | Optional. Folder with BrickLink catalogue XML files, when Gear decisions need it. |
| `--replace` | Overwrite an existing `--out` file. |

Review the proof, then point `BW_DB_PATH` at the new file and restart.

## import-bricktracker

*Since 0.5.0.*

Imports a BrickTracker collection into the current database in two steps: make a plan, then apply it.

```text
brickwork import-bricktracker APP_DB [--plan-only] [--decisions DECISIONS_JSON]
brickwork import-bricktracker --apply PLAN_ID [--decisions DECISIONS_JSON]
```

| Argument | Meaning |
|---|---|
| `APP_DB` | The BrickTracker `app.db`, opened read-only. Give either this or `--apply`. |
| `--plan-only` | Make the plan and stop. |
| `--apply PLAN_ID` | Apply a stored plan. A plan applies once. |
| `--decisions` | A JSON file mapping row keys to `add` or `skip`. |

## catalogue

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork catalogue status
brickwork catalogue import bricklink --from DIRECTORY
```

## sources

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork sources status
```

## import

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork import {S,P,M,G,B,C,I,O} ITEM_NO
```

## jobs

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork jobs [--failed]
brickwork jobs retry JOB [STEP]
```

## brickset

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork brickset refresh [SET ...]
```

## prices

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork prices refresh SET_NUM
```

## settings

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork settings show
brickwork settings set KEY VALUE
```

## sync

*Since 0.5.0.*

This command changes with the 4.0 data model.

```text
brickwork sync {rebrickable,brickset} {status,lists,link,pull,send,connect,paste,remove,test} [options]
```
