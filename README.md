# Brick Work

Brick Work is a standalone Flask app for a LEGO collection: sets and loose stock, part checks, missing pieces, storage, wishes, prices and orders. The browser, API, CLI and MCP server share the v3 core and `brickwork.db`. Catalogue identities come from BrickLink. Source imports enrich those identities; they do not invent them.

## Status

Brick Work is pre-1.0. Its maintainer uses it daily for a collection of about 200 set copies, but the schema and the API can still change between minor versions; read the [CHANGELOG](CHANGELOG.md) before upgrading. It is self-hosted, single-user and meant for a home network or a VPN, not the open internet.

**What it does beyond inventory:** check a copy's parts against its inventory, pick missing parts from your sorted loose stock, see which incomplete sets your stock can finish, value copies against BrickLink prices, receive orders into stock, and keep storage locations, wishlists and instructions together. Everything is reachable from the browser (as an installable app), a versioned REST API with scoped tokens and Undo, an admin CLI, and an MCP server for AI assistants.

**What it contacts:** nothing until you add keys. With your own keys it calls BrickLink, Rebrickable and Brickset for catalogue data, inventories, pictures and prices; photo identification sends the photo you choose to Brickognize. There is no telemetry and no account with this project.

## Standalone installation with Docker

From this checkout, with Docker Compose installed:

```sh
mkdir -p data
sudo chown 1000:1000 data   # the container runs as uid 1000
cp .env.sample data/.env
# Edit data/.env before starting.
docker compose build
docker compose run --rm --entrypoint brickwork brickwork setup
docker compose up -d
```

Set `BW_AUTHENTICATION_PASSWORD` in `data/.env` first (see below), then open `http://localhost:3333`. The container runs as uid 1000 and writes only to `data/`; if an older image (which ran as root) created that folder, run `sudo chown -R 1000:1000 data` once. The `data` volume holds the database, local catalogue index, photos, PDFs and job state. Back it up together with your environment configuration. No separate application or service is required. The offline smoke test covers a fresh installation without source credentials.

Environment variables override `data/.env`; a root `.env` is the fallback. See [.env.sample](.env.sample). Set `BW_AUTHENTICATION_PASSWORD`: without one the server refuses to start, because anyone who can reach it could edit the collection, export the database and create API tokens. To run without login on purpose (a single trusted computer), set `BW_ALLOW_NO_LOGIN=1`. The session key is generated into `data/session.key` on first start unless you set `BW_AUTHENTICATION_KEY`. `compose.yaml` publishes the port on this computer only (`127.0.0.1:3333`); change that to `3333:3333` to reach the app from your network once a password is set. `BW_DB_PATH` defaults to `data/brickwork.db`; `BW_HOST`, `BW_PORT` and `BW_READ_ONLY` control serving and editing.

Pictures, thumbnails, own photos, identification thumbnails and instruction PDFs live in a `data/` folder under the media root. By default that is the folder holding the database; set `BW_MEDIA_PATH` to move them, for example to a NAS, while the database stays on fast local storage. Stored paths are relative, so moving the media means moving the `data/images`, `data/thumbs`, `data/instructions` and `data/identifications` folders there; nothing in the database changes. The database snapshot in Tools & Admin and `brickwork` exports never include media; back the media folder up separately.

```yaml
services:
  brickwork:
    environment:
      BW_DB_PATH: /app/data/brickwork.db
      BW_MEDIA_PATH: /media/brickwork      # pictures and PDFs in /media/brickwork/data/...
    volumes:
      - ./data:/app/data                   # database, catalogue, import and sync plans
      - /mnt/nas/brickwork:/media/brickwork
```

Failed logins and failed API token checks back off per client address: after `BW_LOGIN_MAX_FAILURES` failures (default 5), each further attempt waits 1 s, doubling up to `BW_LOGIN_MAX_DELAY` seconds (default 300); a success resets the counter. Behind a reverse proxy, set `BW_TRUSTED_PROXIES` to the number of proxies in front of the app (usually 1), so the client address, scheme and host come from their `X-Forwarded-*` headers; the default 0 trusts no forwarded header, which is right when clients reach the app directly. The counters live in the app process, so a restart clears them and several worker processes count separately: keep the app behind a VPN or a rate-limiting proxy when it is reachable from the internet.

## Catalogue, keys and jobs

Load your BrickLink catalogue XML files from `data/bricklink-catalog-src/` through **Tools & Admin → Catalogues & keys** or:

```sh
docker compose exec brickwork brickwork catalogue import bricklink --from data/bricklink-catalog-src
```

The resulting `bricklink-catalog.db` sits beside `brickwork.db`. Adding a new identity requires this catalogue. Collection reads, part checks, manual prices, storage changes and order imports from email/XML work without source keys.

Enter BrickLink, Rebrickable and Brickset keys in **Catalogues & keys**. Stored keys are encrypted with Fernet using `BW_SECRET_KEY`. Generate a key once, put it in `data/.env`, and retain it securely:

```sh
docker compose run --rm --entrypoint python brickwork -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Without `BW_SECRET_KEY`, key entry is disabled; environment credentials still work. A complete environment bundle overrides that source's stored bundle. BrickLink uses `BW_BRICKLINK_CONSUMER_KEY`, `BW_BRICKLINK_CONSUMER_SECRET`, `BW_BRICKLINK_TOKEN_VALUE`, `BW_BRICKLINK_TOKEN_SECRET`; Rebrickable uses `BW_REBRICKABLE_API_KEY`; Brickset uses `BW_BRICKSET_API_KEY`. Pages and API responses show configured state, origin and saved time, never key values. Brickognize needs no key.

The embedded worker drains queued imports by default. For a headless worker, set `BW_EMBEDDED_WORKER=0` and run `docker compose exec brickwork brickwork worker` periodically. Jobs retain progress and budget waits in SQLite. `BW_BRICKLINK_DAILY_BUDGET` defaults to 4,400, providing a safety margin for other tools sharing the key. Rebrickable and Brickognize budgets use `BW_REBRICKABLE_DAILY_BUDGET` and `BW_BRICKOGNIZE_DAILY_BUDGET`.

## Settings reference

Every setting is an environment variable, read from `data/.env` when it is not set in the environment. A test checks that this table and the code name the same settings.

| Setting | Default | What it does |
|---|---|---|
| `BW_AUTHENTICATION_PASSWORD` | none | The browser login password. Required unless `BW_ALLOW_NO_LOGIN=1`. |
| `BW_ALLOW_NO_LOGIN` | off | `1` runs without a password on purpose: anyone who can reach the app can edit it. |
| `BW_AUTHENTICATION_KEY` | generated | Signs browser sessions. Generated into `data/session.key` when empty; changing it ends every session. |
| `BW_SECURE_COOKIES` | off | `1` sends the session cookie only over HTTPS. Set it behind HTTPS. |
| `BW_TRUSTED_PROXIES` | `0` | Reverse proxies in front of the app whose `X-Forwarded-*` headers are trusted. Usually `1` behind a proxy. |
| `BW_LOGIN_MAX_FAILURES` | `5` | Failed logins or token checks per client before the back-off starts. |
| `BW_LOGIN_MAX_DELAY` | `300` | Longest back-off in seconds. |
| `BW_HOST` | `0.0.0.0` | Address the server listens on inside the container. |
| `BW_PORT` | `3333` | Port the server listens on. |
| `BW_DB_PATH` | `data/brickwork.db` | The database file. |
| `BW_MEDIA_PATH` | the database folder | Where pictures, thumbnails and PDFs live (under its `data/`). |
| `BW_READ_ONLY` | off | `1` refuses every change, in the browser and the API. |
| `BW_DEBUG` | off | `1` shows tracebacks on errors. Never on a reachable install. |
| `BW_DARK_MODE` | off | `1` makes dark the default theme (each browser can still choose). |
| `BW_HIDE_ADD_SET`, `BW_HIDE_ALL_SETS`, `BW_HIDE_ALL_MINIFIGURES`, `BW_HIDE_ALL_PARTS`, `BW_HIDE_ALL_PROBLEMS_PARTS`, `BW_HIDE_ALL_STORAGES`, `BW_HIDE_WISHES` | off | `1` hides that entry from the navigation. |
| `BW_SECRET_KEY` | none | Fernet key that encrypts source keys stored in the app. Without it, keys come from the environment only. |
| `BW_BRICKLINK_CONSUMER_KEY`, `BW_BRICKLINK_CONSUMER_SECRET`, `BW_BRICKLINK_TOKEN_VALUE`, `BW_BRICKLINK_TOKEN_SECRET` | none | BrickLink Store API credentials; a complete set overrides the stored one. |
| `BW_REBRICKABLE_API_KEY` | none | Rebrickable API key. |
| `BW_BRICKSET_API_KEY` | none | Brickset API key. |
| `BW_REBRICKABLE_USER_TOKEN`, `BW_BRICKSET_USER_HASH` | none | Your Rebrickable and Brickset accounts for collection sync, instead of connecting them in the app. |
| `BW_BRICKLINK_DAILY_BUDGET` | `4400` | BrickLink API calls per day (BrickLink allows 5,000; the rest is a margin for other tools on the same key). |
| `BW_REBRICKABLE_DAILY_BUDGET` | `1000` | Rebrickable API calls per day. |
| `BW_BRICKOGNIZE_DAILY_BUDGET` | `100` | Photo identifications per day. |
| `BW_PRICE_SETTINGS_LOCK` | on | Refuses changes to the BrickLink region and currency, which every stored price depends on; `0` allows them. |
| `BW_EMBEDDED_WORKER` | on | `0` leaves queued imports to `brickwork worker` (headless installs). |
| `BW_IMPORT_MAX_MB` | `200` | Largest upload, in MB, for a database import; also the cap for any request. |
| `BW_API_TOKEN` | none | A bootstrap API token with admin scope. Optional: stored tokens are created in the app or with `brickwork token create`. |
| `BW_MCP_WRITE` | off | `1` allows the MCP server's write tools (as `--allow-write`). |

## API and MCP

The sole API is `/api/v1`: [contract](docs/brickwork/api-v1.md), [OpenAPI](docs/brickwork/openapi-v1.yaml). Use `Authorization: Bearer TOKEN`. Set `BW_API_TOKEN` for a bootstrap admin token, or create scoped stored tokens after setup:

```sh
docker compose exec brickwork brickwork token create --name client --scope read,write --expires 90d
docker compose exec brickwork brickwork token list
docker compose exec brickwork brickwork token revoke TOKEN_ID
```

A created token secret is shown once; only its hash is stored. The bootstrap token cannot be revoked through the API. Writes return an audit event and, where supported, an Undo URL. Creates and quantity operations require an `Idempotency-Key`.

The MCP server uses the same API authorization and schemas. For stdio in a local install:

```sh
brickwork mcp --api-url http://127.0.0.1:3333/api/v1 --token-file /path/to/token
# Or use the local database through an in-process API:
brickwork mcp --in-process --token-file /path/to/token
```

Read tools are available by default. `--allow-write` enables write tools only when the calling token has sufficient scope. `--transport http --host 127.0.0.1 --port 5000` serves the HTTP MCP transport. See [MCP details](docs/brickwork/api-v1.md#7-mcp-server).

## Import an old collection

**Tools & Admin → Import from BrickTracker** and `brickwork migrate` share one read-only importer. Supply the old `app.db`, identity decisions JSON, a BrickLink catalogue database and a new output path; `--extras` optionally supplies the old extras database. No extras database is needed for normal operation.

```sh
brickwork migrate --app old/app.db --extras old/extras.db \
  --decisions decisions.json --catalogue bricklink-catalog.db \
  --out data/brickwork.db --report import-proof
```

Omit `--extras` if unavailable. Use `--catalogue-src` for the XML folder when Gear decisions require it. Existing outputs are refused unless the CLI's explicit `--replace` is used; the browser always refuses replacement. Review the row-count/checksum proof, then point `BW_DB_PATH` at the imported file and restart. The importer preserves the established historical mapping; review unresolved identities in the app.

## Development checks

```sh
.venv/bin/python -m pytest tests -q
APP_VENV=.venv bash scripts/check.sh
```

The check script includes the naming gate, a standalone smoke test with sockets blocked, the full Python suite, available JavaScript runtime harnesses and contract consistency checks.

## Documentation

The documentation site (published on GitHub Pages with the first public release) shows this README, the API reference rendered from [openapi-v1.yaml](docs/brickwork/openapi-v1.yaml), and the [MCP guide](docs/brickwork/mcp.md). The [API guide](docs/brickwork/api-v1.md) covers authentication, conventions and examples. Build the site locally with `python scripts/build_site.py _site`.

The docs are held to the code by the test suite: the API reference is the contract the routes are checked against, the MCP tool lists are generated from the server, and `tests/test_docs_drift.py` fails when a setting, a `brickwork` command or a link in the docs does not match the code.

## Contributing, security and conduct

Bug reports and feature requests are welcome as GitHub issues; see [CONTRIBUTING](CONTRIBUTING.md). Report security problems privately as described in [SECURITY](SECURITY.md). Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Repository

This GitHub repository is the canonical source: changes land here first. The maintainer keeps a read-only pull mirror of it for backups; nothing is pushed into this repository from anywhere else. The project's history before the first public release is not published.

## Licence and trademarks

MIT; see [LICENSE](LICENSE), which keeps the upstream copyright notice, and [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) for fonts and icons.

LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project. Brick Work bundles no catalogue data or images from BrickLink, Rebrickable or Brickset; each install uses its owner's keys.

## Acknowledgements

Brick Work was inspired by [BrickTracker](https://gitea.baerentsen.space/FrederikBaerentsen/BrickTracker), by Frederik Baerentsen and contributors. The upstream MIT notice is preserved in [LICENSE](LICENSE).
