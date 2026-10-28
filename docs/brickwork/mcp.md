# Brick Work MCP server

Brick Work ships an [MCP](https://modelcontextprotocol.io) server, so an AI assistant can read your collection and, if you allow it, change it. The server is a thin layer over the [REST API](api-v2.md): every tool call is one API request with your token, so scopes, Undo, idempotency and the audit log behave exactly as for any other API client.

## Before you start

1. A running Brick Work with the API on (see the README).
2. An API token. Create one in **Tools & Admin → API tokens**, or on the server:

   ```sh
   brickwork token create --name assistant --scope read
   ```

   Use `--scope read,write` only if the assistant may change things. The secret is shown once; keep it in a file only you can read, for example `data/mcp-token` (mode 600).

## Connect an assistant

### On the same computer (stdio)

The assistant starts the server itself. With Brick Work installed from source:

```sh
brickwork mcp --in-process --token-file data/mcp-token
```

`--in-process` uses the local database through the same API routes, with no network. To talk to a running instance instead, give its API address:

```sh
brickwork mcp --api-url http://127.0.0.1:3333/api/v2 --token-file data/mcp-token
```

In an assistant's MCP settings this is one server entry: the command `brickwork`, the arguments `mcp --in-process --token-file /path/to/mcp-token`, and the working directory of your Brick Work checkout. With Docker, run the same command through `docker compose exec -T brickwork brickwork mcp ...`.

### Over the network (HTTP)

```sh
brickwork mcp --transport http --host 127.0.0.1 --port 5000
```

This serves the MCP endpoint at `/mcp` next to the app. Each request must carry the caller's own token (`Authorization: Bearer ...`); the server never falls back to another token. Without a reverse proxy it listens on this computer only; put TLS in front of it before exposing it, and set `BW_TRUSTED_PROXIES` as described in the README.

## Reading and writing

- **Read tools** are always available.
- **Write tools** appear only when the token has the `write` scope **and** the server runs with `--allow-write` (or `BW_MCP_WRITE=1`). Both are needed: a write token alone does not enable them.
- **Admin work** (settings, source keys, catalogue import, database export, tokens) is never available as a tool. Use the app or the CLI.
- Every write returns an `event_id` and, where possible, an `undo_url`. The `undo_event` tool takes that id back.
- A write tool accepts an optional `idempotency_key`. Pass the same key when retrying a call, and the first result is returned instead of applying the change twice.
- `archive_*` tools archive. Nothing is hard-deleted through MCP, and archived records can be restored in the app.

## Items go by number

A tool never asks for a Brick Work item id. Ids are per install, and an assistant has no way to know them. It names an item the way you do, by number:

- `provider`: `bricklink` (the default) or `rebrickable`. A set has the same number in both.
- `kind`: `set`, `part`, `minifigure`, `instructions`, `box`, `gear`, `book` or `catalog`.
- `no`: the number, such as `1000-1` or `3001`.

`get_item`, `get_prices`, `record_price`, `refresh_price`, `import_item` and `set_figure_missing` take these three. Before the call, the server looks the number up (`lookup_item` does the same on its own). A number that names nothing is `not_found`. A number that names several items is `ambiguous`, and the answer lists them as `candidates`; nothing is written, so ask for a more exact number or the other provider.

A tool that adds something (`add_copies`, `add_stock`, `add_wish`, `take_for_gap`) takes `item` as `{"provider": "bricklink", "kind": "set", "key": "1000-1"}`. `provider` can be left out. In `get_prices` the provider also says whose colour number `color` is, and the colour takes part in the lookup: some BrickLink numbers (legs, for example) name a different item in each colour.

A merged item answers a read with `moved` and its `survivor`. The tool reports it as an error, so look the number up again.

Copies, stock lines, wishes, wishlists, storages, lots, events, jobs and orders keep their ids. Take them from the `list_*` tools, which also filter by number and provider (`list_copies` with `number`, for example).

## Data and privacy

The assistant sees what its token can read: your sets, parts, prices, storage locations and notes. Brick Work itself sends nothing to the assistant's provider. The assistant client does, so choose a client and provider you are comfortable sharing your collection with, and prefer a read-only token.

## Tools and resources

The lists below are generated from the server's own tool table when this site is built, so they always match the release.

A resource is a read-only document an assistant can open by its address, for example `brickwork://summary` or `brickwork://items/bricklink/part/3001`.
