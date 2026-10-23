# Connect an assistant

*Since 0.5.0.*

Do this when you want an AI assistant, such as Claude Desktop or Claude Code, to look things up in your collection or, if you allow it, change it. Brick Work's MCP server gives the assistant tools that call the REST API with a token you create.

## Create a token

Give each assistant its own token with only the scopes it needs.

1. Open **Manage → Tools & Admin → API tokens**.
2. Press **Create token**.
3. Enter a **Name**, for example `assistant`.
4. Under **Scopes**, tick **read**. Tick **write** as well only if the assistant may change things. Assistants never need **admin**.
5. Press **Create token**.
6. Under **Your new token**, press **Copy**. The secret is shown once and cannot be shown again.

Or on the server:

```sh
docker compose exec brickwork brickwork token create --name assistant --scope read
```

Use `--scope read,write` for an assistant that may write, and `--expires 90d` for a token that runs out. The command prints the token as JSON; the secret is in `secret`.

Save the secret in a file of its own, for example `data/mcp-token`, with nothing else in it. Keep it private: `chmod 600 data/mcp-token`, owned like the rest of `data/` (`sudo chown 1000:1000 data/mcp-token` for the container). Inside the container the file is `/app/data/mcp-token`.

To stop an assistant, press **Revoke** next to its token, or run `brickwork token revoke TOKEN_ID`. Calls with it fail at once.

## Run the MCP server read-only

By default the server offers read tools only, whatever the token's scopes:

```sh
docker compose exec -T brickwork brickwork mcp --in-process --token-file /app/data/mcp-token
```

`--in-process` uses the database directly through the same API routes, with no network. To talk to a running instance over HTTP instead, give its API address with `--api-url`, for example `--api-url http://127.0.0.1:3333/api/v1`.

You don't run this command yourself. The assistant starts it, as shown below.

## Allow writes

Write tools appear only when both are true:

- the token has the `write` scope, and
- the server runs with `--allow-write` (or `BW_MCP_WRITE=1`).

```sh
docker compose exec -T brickwork brickwork mcp --in-process --allow-write --token-file /app/data/mcp-token
```

Every write returns an `event_id`, and the `undo_event` tool takes it back. Archive tools archive; nothing is deleted. Settings, source keys, catalogue import, database export and tokens are never available as tools.

## Configure the assistant

### Claude Desktop

Add a server entry to Claude Desktop's `claude_desktop_config.json` and restart Claude Desktop. Use the full path to your Brick Work folder:

```json
{
  "mcpServers": {
    "brickwork": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/brick-work/compose.yaml", "exec", "-T", "brickwork",
               "brickwork", "mcp", "--in-process", "--token-file", "/app/data/mcp-token"]
    }
  }
}
```

### Claude Code

```sh
claude mcp add brickwork -- docker compose -f /path/to/brick-work/compose.yaml exec -T brickwork \
  brickwork mcp --in-process --token-file /app/data/mcp-token
```

Add `--allow-write` at the end of either command to enable write tools.

### Over the network

For an assistant on another machine, serve MCP over HTTP:

```sh
brickwork mcp --transport http --host 127.0.0.1 --port 5000
```

The endpoint is `/mcp`. Each request must carry its own token as `Authorization: Bearer YOUR_TOKEN`; the server never falls back to another token. It refuses to start when no login password is set, unless `BW_ALLOW_NO_LOGIN=1`. Put TLS in front of it before you expose it, and set `BW_TRUSTED_PROXIES` behind a reverse proxy.

## What it shares

The assistant sees whatever its token can read: sets, parts, prices, storage locations and notes. Brick Work sends nothing to the assistant's provider, but the assistant client does. Choose a client you are happy to share your collection with, and prefer a read-only token.

## What next

- The [MCP guide](../../mcp/) lists every tool and resource.
- The [API reference](../../api/) for calling the API directly.
- [Undo a change](undo-a-change.md) an assistant made.
- [Settings](../reference/settings.md) for `BW_MCP_WRITE`, `BW_API_TOKEN` and `BW_TRUSTED_PROXIES`.
- [Commands](../reference/cli.md) for `brickwork mcp` and `brickwork token`.
