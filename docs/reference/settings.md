# Settings

*Since 0.5.0.*

Every setting is an environment variable. Brick Work reads `data/.env` (or, if that file does not exist, a `.env` in the app folder) at start; a variable set in the environment wins over the file. Change a setting, then restart the app.

On/off settings take `1` for on. Where a setting accepts more spellings, the table says so.

## Login and security

| Variable | Default | What it does |
|---|---|---|
| `BW_AUTHENTICATION_PASSWORD` | none | The browser login password. Without it the server refuses to start, unless `BW_ALLOW_NO_LOGIN=1`. |
| `BW_ALLOW_NO_LOGIN` | off | `1` (or `true`, `yes`) runs without a password on purpose: anyone who can reach the app can edit the collection, export the database and create API tokens. |
| `BW_AUTHENTICATION_KEY` | generated | Signs browser sessions. When empty, a key is generated into `session.key` beside the database. Changing it ends every session. |
| `BW_SECURE_COOKIES` | off | `1` sends the session cookie only over HTTPS. Set it when the app is served over HTTPS. |
| `BW_TRUSTED_PROXIES` | `0` | How many reverse proxies in front of the app are trusted for their `X-Forwarded-*` headers (client address, scheme, host). Usually `1` behind a proxy; `0` trusts none, which is right when clients reach the app directly. |
| `BW_LOGIN_MAX_FAILURES` | `5` | Failed logins or API token checks per client address before the back-off starts. A value that is not a positive whole number falls back to the default. |
| `BW_LOGIN_MAX_DELAY` | `300` | Longest back-off, in seconds. The wait starts at 1 s and doubles up to this; a successful login resets it. |
| `BW_SECRET_KEY` | none | Fernet key that encrypts the source keys you enter in **Tools & Admin → Catalogues & keys**. Without it key entry is disabled and keys come from the environment only. Keep it safe: stored keys cannot be read without it. |
| `BW_API_TOKEN` | none | A bootstrap API token with admin scope, also used by `brickwork mcp` when no `--token-file` is given. Optional: stored tokens are created in the app or with `brickwork token create`. It cannot be revoked through the API. |
| `BW_MCP_WRITE` | off | `1` turns on the MCP server's write tools, as `brickwork mcp --allow-write` does. Only `1` counts. |

## Serving

| Variable | Default | What it does |
|---|---|---|
| `BW_HOST` | `0.0.0.0` | Address the server listens on (inside the container). |
| `BW_PORT` | `3333` | Port the server listens on. |
| `BW_READ_ONLY` | off | `1` (or `true`, `yes`, `on`) refuses changes in the browser and the API. In the CLI it covers the `token` and `wishlist` commands and the database export; other CLI commands, such as `settings set`, still write. |
| `BW_DEBUG` | off | `1` shows the exception and traceback on error pages and logs at debug level. Never on a reachable install. |
| `BW_DARK_MODE` | off | `1` makes dark the default theme; each browser can still choose. |
| `BW_IMPORT_MAX_MB` | `200` | Largest database import upload, in MB. It is also the cap for any request body; smaller per-upload limits (photos, PDFs, order files) stay as they are. |
| `BW_HIDE_ADD_SET` | off | `1` hides **Add** from the navigation and the header. |
| `BW_HIDE_ALL_SETS` | off | `1` hides **Sets** and **Check Set Parts** from the navigation. |
| `BW_HIDE_ALL_MINIFIGURES` | off | `1` hides **Minifigures** from the navigation. |
| `BW_HIDE_ALL_PARTS` | off | `1` hides **Parts** from the navigation. |
| `BW_HIDE_ALL_PROBLEMS_PARTS` | off | `1` hides **Complete sets** from the navigation. |
| `BW_HIDE_ALL_STORAGES` | off | `1` hides **Storage** from the navigation. |
| `BW_HIDE_WISHES` | off | `1` hides **Wishlist** from the navigation. |

The `BW_HIDE_*` settings only remove the entry; the pages still open from a link.

## Storage and media

| Variable | Default | What it does |
|---|---|---|
| `BW_DB_PATH` | `data/brickwork.db` | The database file. The BrickLink catalogue (`bricklink-catalog.db`), the session key, import and sync plans live in the same folder. |
| `BW_MEDIA_PATH` | the database folder | Where pictures, thumbnails, your own photos, identification thumbnails and instruction PDFs live, under its `data/` folder. Moving media means moving `data/images`, `data/thumbs`, `data/instructions` and `data/identifications` there; nothing in the database changes. |

## Sources and budgets

| Variable | Default | What it does |
|---|---|---|
| `BW_BRICKLINK_CONSUMER_KEY` | none | BrickLink API consumer key. |
| `BW_BRICKLINK_CONSUMER_SECRET` | none | BrickLink API consumer secret. |
| `BW_BRICKLINK_TOKEN_VALUE` | none | BrickLink API access token. |
| `BW_BRICKLINK_TOKEN_SECRET` | none | BrickLink API token secret. All four together override the BrickLink key stored in the app. |
| `BW_REBRICKABLE_API_KEY` | none | Rebrickable API key; overrides the stored one. |
| `BW_BRICKSET_API_KEY` | none | Brickset API key; overrides the stored one. |
| `BW_REBRICKABLE_USER_TOKEN` | none | Your Rebrickable account token for collection sync, instead of connecting it in the app. |
| `BW_BRICKSET_USER_HASH` | none | Your Brickset account hash for collection sync, instead of connecting it in the app. |
| `BW_BRICKLINK_DAILY_BUDGET` | `4400` | BrickLink API calls per day. BrickLink allows 5,000; the rest is a margin for other tools on the same key. Must be a positive whole number. |
| `BW_REBRICKABLE_DAILY_BUDGET` | `1000` | Rebrickable API calls per day. Must be a positive whole number. |
| `BW_BRICKOGNIZE_DAILY_BUDGET` | `100` | Photo identifications per day. |
| `BW_PRICE_SETTINGS_LOCK` | on | Refuses changes to the BrickLink region and currency, which every stored price depends on. Only `0` unlocks them. |

## Workers

| Variable | Default | What it does |
|---|---|---|
| `BW_EMBEDDED_WORKER` | on | The app works through queued imports itself. `0` (or `false`, `no`, `off`) leaves them to `brickwork worker`, for headless installs. |

## Development only

| Variable | Default | What it does |
|---|---|---|
| `BW_PRIVATE_PATTERNS_FILE` | none | A file of extra regular expressions, one per line, that the private-material scans of the source tree, the demo and the documentation site also reject, such as your own host names. |

See also: [Command line](cli.md).
