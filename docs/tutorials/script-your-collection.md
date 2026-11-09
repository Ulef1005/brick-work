# Script your collection

Brick Work has a REST API, a command line and an MCP server for AI assistants. They all work with the same data and the same API tokens. In this tutorial you create a token, use it to read and change your collection from a terminal, and then connect an assistant and ask it about your collection.

It takes about 20 minutes. You need a running Brick Work install ([README](https://github.com/Ulef1005/brick-work#standalone-installation-with-docker)) with some sets in it, and a terminal on the computer that runs it. Try it on a test collection first: step 3 changes data, though you will undo the change. The outputs below come from the invented demo collection, so your numbers and names will differ.

In a Docker install, run every `brickwork` command inside the container, like this:

```sh
docker compose exec brickwork brickwork check
```

The commands below are written without the `docker compose exec brickwork` part.

## 1. Create an API token

A token lets a script or an assistant call Brick Work without your login. Each token has its own scopes: **read** reads, **write** changes things.

1. Open **Manage → Tools & Admin → API tokens**.
2. Press **Create token**.
3. Enter a **Name**, for example `tutorial`.
4. Under **Scopes**, tick **read** and **write**.
5. Press **Create token**.
6. Under **Your new token**, press **Copy**, then **Done**. The secret is shown once and cannot be shown again.
7. In your terminal, keep it in a variable for this session:

```sh
export TOKEN=paste-the-secret-here
```

You see the token in the list with its name and its scopes. The [API tokens section of Connect an assistant](../how-to/connect-an-assistant.md#create-a-token) also shows how to create one with `brickwork token create`.

## 2. Check that the token works

Ask the API who you are. A default install listens on port 3333:

```sh
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3333/api/v2/me
```

```json
{"data":{"expires_at":null,"name":"tutorial","scopes":["read","write"]}}
```

The answer names your token and its scopes. Reload **API tokens**: **Last used** now has a time. Every API call carries the token this way. The [API reference](../../api/) lists every endpoint.

## 3. Read and change the collection

The command line reads the same database as the app. Start with a health check:

```sh
brickwork check
```

```text
brickwork:
  integrity_check:
    ok
  foreign_key_check:
    (none)
  row_counts:
    allocation: 7
    api_token: 1
    ...
```

It goes on with a row count for every table, the catalogue check and the checks that the collection and the catalogue belong together. Each reads `ok`.

Now list your wishlists:

```sh
brickwork wishlist list
```

```text
  id: default
  name: Wishlist
  note: None
  sort: 0
  ...
  count: 2
  id: wl-birthday
  name: Birthday ideas
  ...
```

Each list shows its id, name and how many wishes it holds. Add one:

```sh
brickwork wishlist create "Spring orders"
```

```text
id: 58797a95afbd4faf94742e88e0e99f60
event_id: 491
```

The command prints the new list's id and an `event_id`. Every change is one event, and the event is how you take it back. Read the change back through the API with your token:

```sh
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3333/api/v2/wishlists | jq -c '.data[] | {id, name}'
```

```text
{"id":"58797a95afbd4faf94742e88e0e99f60","name":"Spring orders"}
{"id":"default","name":"Wishlist"}
{"id":"wl-birthday","name":"Birthday ideas"}
{"id":"wl-castle","name":"Castle theme"}
{"id":"wl-parts","name":"Parts to buy"}
```

(`jq` only shortens the output; leave it out to see the whole answer.) Then undo the change with the event id you were given:

```sh
brickwork wishlist undo 491
```

```text
message: Undone
```

The list is gone again. Now read something larger, the sets that are not complete:

```sh
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:3333/api/v2/copies?status=incomplete&limit=5" \
  | jq -c '.data[] | {name, missing, damaged, completeness}'
```

```text
{"name":"Fishing Cutter","missing":2,"damaged":3,"completeness":"incomplete"}
{"name":"Coastal Rescue Base","missing":15,"damaged":5,"completeness":"incomplete"}
{"name":"Highway Diner","missing":0,"damaged":1,"completeness":"incomplete"}
{"name":"Lunar Rover Garage","missing":8,"damaged":2,"completeness":"incomplete"}
{"name":"Dragon Keep Gatehouse","missing":17,"damaged":1,"completeness":"incomplete"}
```

The [command line reference](../reference/cli.md) lists every command and option, and [Undo a change](../how-to/undo-a-change.md) covers undoing from the app.

## 4. Connect an assistant

An assistant such as Claude Code reaches Brick Work through the MCP server. The server is a thin layer over the same API, so it uses a token too. Give the assistant its own token with only **read**: create one as in step 1, name it `assistant` and tick only **read**. Save the secret in a file of its own, `data/mcp-token`, with nothing else in it, and restrict it:

```sh
chmod 600 data/mcp-token
```

Then tell Claude Code how to start the server (replace `/path/to/brick-work` with the folder of your install):

```sh
claude mcp add brickwork -- docker compose -f /path/to/brick-work/compose.yaml exec -T brickwork \
  brickwork mcp --in-process --token-file /app/data/mcp-token
```

You don't run `brickwork mcp` yourself; the assistant starts it. It offers read tools only, because you did not add `--allow-write`. Without Docker, the other assistants and the HTTP transport, follow [Connect an assistant](../how-to/connect-an-assistant.md); do not turn on writes for this tutorial.

## 5. Ask the assistant about your collection

Start the assistant and ask it:

> How many of my sets are incomplete?

The assistant chooses a tool itself. One that fits this question is `get_statistics`, which needs no arguments. Called through the server, it returns the counts of your copies by completeness; the first part of the result is:

```json
{
 "completeness": [
  {"count": 9, "label": "Incomplete"},
  {"count": 8, "label": "Not checked"},
  {"count": 5, "label": "Complete"},
  {"count": 3, "label": "Sealed"}
 ],
 ...
}
```

The assistant reads that result and answers in its own words; what it writes is up to the assistant, not Brick Work. Ask a second question, such as *Which of my sets are incomplete, and how many parts is each missing?* A tool that fits is `list_copies` with a `status` of `incomplete`, which returns the same list as the API call in step 3.

Two things to notice. The assistant names sets and parts by number, never by a Brick Work id. And it can only do what its token allows: a read-only token and no `--allow-write` means it cannot change your collection. If it ever did make a change, the change would carry an `event_id` that `undo_event` takes back.

When you are done, press **Revoke** next to the `tutorial` and `assistant` tokens on **API tokens**. Calls with a revoked token fail at once.

## What you did

You created a token, called the API with it, read and changed the collection from the command line, undid the change, and gave an assistant read-only access. From here:

- [API reference](../../api/) for every endpoint.
- [Command line](../reference/cli.md) for every `brickwork` command.
- [Connect an assistant](../how-to/connect-an-assistant.md) for other assistants, the HTTP transport and write access.
