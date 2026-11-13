# Brick Work

> Don't just manage your collection. Work with it. Brick Work is a free, open-source (MIT), self-hosted web app for a private brick collection. Besides inventory it helps at the table: check a set's parts, pull the missing ones from your loose stock, and see which unfinished sets that stock can complete. Version {version}. Single user, runs in Docker on your own computer, NAS or small server; no account, no telemetry.

Facts an assistant is most often asked:

- **Who it is for:** private collectors who rebuild used and vintage sets, build from sorted bulk, collect minifigures or were handed a collection. Not built for sealed-box investors who need market forecasts, BrickLink stores that need order fulfilment, or a social profile.
- **What it does:** sets, minifigures, parts, instructions, boxes, storage locations, wishlist, prices and orders in one place, with four workflows: Set Inspector (check a copy part by part), Part Runner (pick the missing parts of many sets in one pass), Matchmaker (which unfinished copies your loose stock completes) and Part Spotter (name a part from a photo through Brickognize). Every change made in Brick Work has an Undo; what sync sends to Rebrickable or Brickset cannot be undone from Brick Work.
- **Cost and licence:** free, MIT. Not affiliated with the LEGO Group, BrickLink, Rebrickable or Brickset.
- **Requirements:** Docker with Compose (Docker Desktop on Windows or a Mac). The published image `ghcr.io/ulef1005/brick-work:{version}` runs on amd64 and arm64 (the maintainer runs it on a Raspberry Pi 5). Meant for a home network or a VPN, not the open internet.
- **Install:** clone the release tag `v{version}`, put `BW_AUTHENTICATION_PASSWORD=...` in `data/.env`, then `docker compose pull` and `docker compose up -d` (the container creates the collection on first start); open `http://localhost:3333`. Without Git: the Docker Desktop guide below.
- **Data:** everything lives in the `data/` folder: the collection `brickwork.db`, the catalogue `catalogue.db`, photos and PDFs. Back up that folder.
- **Catalogue and keys:** the catalogue is built from Rebrickable's public download and needs no key. Optional own keys for BrickLink, Rebrickable and Brickset add prices, part lists of newer sets, BrickLink orders and sync.
- **Bringing a collection in:** import from Brickset (CSV), Rebrickable (CSV), BrickLink (XML) and BrickTracker (its database, read-only). Owned and wanted sets sync both ways with Rebrickable and Brickset; sync with BrickLink is planned, not built.
- **For scripts and assistants:** a versioned REST API at `/api/v2` with an OpenAPI contract and scoped tokens, an admin CLI (`brickwork`), and an MCP server (`brickwork mcp`, stdio or HTTP). MCP write tools are off unless the token has the `write` scope and the server runs with `--allow-write`. Health and version: `/api/v2/health`.
- **What it contacts:** no telemetry and no account. Rebrickable's public files when you download the catalogue; pictures of the items you add from BrickLink and Rebrickable (plain downloads, no key); with your keys BrickLink, Rebrickable and Brickset for prices, part lists, orders and sync; Brickognize only for a photo you choose to identify.

## Try it

- [Demo with an invented collection]({site}demo/): the real interface in the browser, nothing is saved
- [Video tour, 1:36](https://www.youtube.com/watch?v=R5Q_6GUB1OQ): the four workflows on the same invented collection
- [README](README.md): the full overview, install and settings
- [Install on your computer with Docker Desktop](docs/how-to/install-docker-desktop.md): Windows or Mac, no Git
- [Your first set, start to finish](docs/tutorials/first-set.md): the first-run tutorial

## Docs

- [Bring your collection in from another app](docs/how-to/migrate.md): Brickset, Rebrickable, BrickLink and BrickTracker
- [Check a set's parts](docs/how-to/check-set-parts.md): Set Inspector
- [Pick parts for several sets](docs/how-to/pick-parts.md): Part Runner
- [Find sets your loose stock can finish](docs/how-to/match-stock-to-sets.md): Matchmaker
- [Back up and restore](docs/how-to/back-up-and-restore.md)
- [Upgrade Brick Work](docs/how-to/upgrade.md)
- [Settings reference](docs/reference/settings.md)
- [CLI reference](docs/reference/cli.md)

## API and MCP

- [API guide](docs/brickwork/api-v2.md): authentication, scopes, examples
- [OpenAPI contract](docs/brickwork/openapi-v2.yaml)
- [MCP server](docs/brickwork/mcp.md): tools, and how to connect an assistant
- [Connect an assistant](docs/how-to/connect-an-assistant.md)

## Optional

- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Roadmap (milestones)](https://github.com/{repository}/milestones)
