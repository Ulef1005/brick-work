# 0025. Containers set up a missing collection before starting the server

- **Status:** accepted
- **Date:** 2026-11-10
- **Decided by:** the maintainer, issues #266 and #265.

## Context

A fresh container on an empty, writable appdata folder answers health checks with `503 not_set_up` until someone runs `brickwork setup`; NAS interfaces have no console setup step. The app resolves its collection path from configuration, including `BW_DB_PATH` in the environment or `data/.env`, so a shell path check would miss some configurations. Gunicorn also logs a control-socket permission error when HOME is unwritable, including when Unraid runs the container as `99:100`.

## Decision

After checking that `/app/data` is writable, the entrypoint runs `brickwork setup --if-missing`. The app's own path rules decide which collection to check. With this flag, any existing path counts as a collection in any format: setup succeeds without opening, migrating, seeding or changing it, so required migration is never bypassed. A missing collection is created and seeded as with plain setup; the first-run page handles the catalogue and nothing is downloaded at startup. Plain `brickwork setup` keeps its existing behavior. Setup failure stops the container before Gunicorn starts.

Gunicorn gets `--no-control-socket` before the user's arguments. The control socket is unused by Brick Work; there is no way to re-enable it by argument after this flag.

## Consequences

- A fresh container can serve the first-run page without a console setup command; existing collections are unchanged by startup setup.
- A crash between creating the file and seeding it (milliseconds, first start only) can leave an unseeded file that the next start treats as existing; running `brickwork setup` by hand seeds it because setup is idempotent.
- Startup no longer logs a control-socket permission error for an unwritable HOME.

## Links

Issues #266 and #265; [CLI reference](../reference/cli.md#setup).
