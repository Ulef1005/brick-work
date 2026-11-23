---
audience: user
verified: 1.0
---

# Brick Work

Brick Work is a self-hosted web app for your brick collection: check a set's parts, pull the missing ones from your loose stock, and see which unfinished sets that stock can complete. It is for private collectors with a real, messy collection of built and boxed sets, loose parts and minifigures.

- [How-to guides](how-to/index.md): one task per page, from checking a set to backing up.
- [Concepts](concepts/index.md): what sets, copies, lots and stock mean, and how completeness is worked out.
- [Reference](reference/index.md): settings, the command line and metrics.
- [Tutorials](tutorials/index.md): complete paths through the app, start to finish; Get started in the app is the guided first run.

Installation is in the [README](https://github.com/Ulef1005/brick-work#install). The REST API and the MCP server have their own pages: [API v2 reference](developer/api-v2-reference.md) and [MCP server](brickwork/mcp.md), under Developers.

## Where Brick Work stands

Release 1.2 (schema 4.7) builds on 1.1: the new design on every screen, and Lost Parts from Rebrickable. Release 1.0 was the first after its maintainer set up a real collection from scratch through **Get started** on a test install and ran every workflow on it (milestone B).

The schema is stable and upgrades from 0.5.x are tested. You install by pulling the published multi-arch image from GHCR, with build provenance and an SBOM you can verify. Its maintainer uses Brick Work daily for a collection of about 200 set copies. Read the [CHANGELOG](https://github.com/Ulef1005/brick-work/blob/main/CHANGELOG.md) before upgrading.

- **New in 1.1:** set detection, stickers and the pull list for a bulk lot. Build Scout and **Build it**. Order missing parts with a BrickLink or Pick a Brick source per line. Change variant, part groups, Sell this copy, Value and gain, and the insurance report. Found in on part detail, complete-or-part-out figures for minifigures, and storage labels with QR codes. Find instructions with booklet previews (the Official source needs a page renderer you set up). User docs with eleven tutorials.
- **Shipped:** the Collection (sets, minifigures, parts, gear, books and catalogs). The Workbench (Part Spotter, Set Inspector, Lot Sorter, Part Runner, Matchmaker, Build Scout, Orders, Storage). Planning (Wishlist, Prices, Complete sets, Order missing parts) and Manage screens. **Get started**, a guided first run. An installable web app with its own look on phone and desktop. A versioned REST API with scoped tokens and Undo, an admin CLI and an MCP server. Orders from your BrickLink account, a confirmation e-mail or the order XML. Optional BrickLink item lists. A read-only importer for an older tracker database. Collection sync of owned and wanted sets with Rebrickable and Brickset.
- **Planned, not built:** sync with BrickLink (#143, open) and a pile check by photo. The order is kept in the [GitHub milestones](https://github.com/Ulef1005/brick-work/milestones) and the issues' priority labels (`now`, `next`, `later`). There are no dates.

Brick Work is self-hosted and single-user. It is meant for a home network or a VPN, not the open internet.

## Who it is for

Private collectors with a real, messy collection that should help them finish it. That means built and boxed sets, bags of sorted and unsorted parts, a few sets you know are short and a wishlist. It is often tracked in a spreadsheet or two other sites.

- **You rebuild used and vintage sets.** "I want to know exactly what is missing from each set." Set Inspector, then export the gaps as BrickLink XML.
- **You build from sorted bulk.** "Do I have it, how many, and which drawer?" Storage per item, Part Runner and Matchmaker.
- **You collect minifigures.** "Which figures can I put together from parts?" Loose figures with their parts, and Part Spotter to name a figure from a photo.
- **You were handed a collection.** "What is in this box, and what do I do with it?" One place for sets, copies and boxes, with storage.
- **You script things at home.** "I want Claude to talk to my collection." REST API, CLI and an MCP server over your own data.

Not built for sealed-box investors who need market forecasts, BrickLink stores that need order fulfilment, or anyone looking for a social profile. Other tools serve them well.

## Your data and what Brick Work contacts

Brick Work is self-hosted, with your data in one folder you back up. There is no account and no telemetry. Everything that needs no source key works offline once the catalogue is loaded. Collection reads, part checks, manual prices, storage changes and order imports from e-mail or XML need no key.

Brick Work contacts nothing until you ask:

- **Download the catalogue** fetches Rebrickable's public files and needs no key.
- Pictures of the items you add come from BrickLink and Rebrickable as plain downloads, with no key.
- With your own keys it calls BrickLink, Rebrickable and Brickset for inventories, pictures and prices.
- Photo identification sends the photo you choose to Brickognize.
- There is no telemetry and no account with this project.

## The services it works with

Sets, minifigures, parts, instructions, boxes, storage, prices, wishlist and orders live in one place. The browser, API, CLI and MCP server share one core and one database file, `brickwork.db`. Every item has a Brick Work id ([the data model](concepts/data-model.md)). The catalogue is built from Rebrickable's public download into a second file, `catalogue.db`, beside the collection. BrickLink, Rebrickable and Brickset numbers are links to those items. BrickLink's item lists are an optional addition.

The catalogue needs no key. Your own keys add prices, part lists for newer sets, BrickLink orders and sync. Brick Work bundles none of their data. It works next to BrickLink, Rebrickable and Brickset, not instead of them.

| Service | Catalogue | Orders | Sync |
|---|---|---|---|
| BrickLink | Available | Available | Planned |
| Rebrickable | Available | none | Available |
| Brickset | Available | none | Available |

Brick Work is not affiliated with these services. Rebrickable and Brickset are where the catalogue and the market live. Brick Work is where your own copies, parts and drawers live. [BrickTracker](https://gitea.baerentsen.space/FrederikBaerentsen/BrickTracker) is the self-hosted tracker Brick Work grew from. BrickStore, BrickEconomy and phone scanners do different jobs and sit well alongside.

## Use with AI assistants

An assistant that should know Brick Work can read [llms.txt](https://brick-work.app/llms.txt), the short facts about the app with links to the key pages, or [llms-full.txt](https://brick-work.app/llms-full.txt), the same facts and those pages in one file. To let an assistant work with a collection, connect it through the [MCP server](brickwork/mcp.md), or script it against the [API v2 reference](developer/api-v2-reference.md) and its [OpenAPI contract](https://github.com/Ulef1005/brick-work/blob/main/docs/brickwork/openapi-v2.yaml).

## Navigation

The top bar, the row of entries under it and the phone's tab bar share four groups: Collection, Workbench, Planning and Manage. Pick a group to see its entries in the row under the bar; on a phone the groups are the tab bar at the foot. The light, dark or automatic setting is the page **Manage › Appearance**.

Open **Workbench > Lot Sorter** to browse parts grouped by lot. Open a lot for **Which sets are in this lot?**, then its pull list.

Open **Planning > Order missing parts**, after **Complete sets**, to choose copies and review their missing parts. Complete sets keeps its ordering link.
