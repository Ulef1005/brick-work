---
audience: developer
verified: 1.0
---

# Developers

For anyone who programs against Brick Work (its REST API, command line and MCP server) or works on it: builds it, contributes, releases it, or runs it from a checkout. Using Brick Work through its screens is in the User guide.

- **Tutorials:** the [Script your collection](../tutorials/script-your-collection.md) tutorial, from an API token to reading and changing the collection.
- **Concepts:** [the data model](../concepts/data-model.md) and its [4.0 design](../data-model-4.0/data-model-design.md), the [import pipeline](../brickwork/pipeline.md), the [source layer](../brickwork/sources.md), [collection sync](../brickwork/sync.md), and [wishlists and portable files](../brickwork/wishlists.md).
- **Reference:** the [API v2 contract](../brickwork/api-v2.md) and the [API v2 reference](api-v2-reference.md) of every operation, the [MCP server](../brickwork/mcp.md) and its [tools and resources](mcp-reference.md), the [command line](../reference/cli.md) and the [code reference](code-reference.md) of `brickwork.core`. The API, MCP and code references are generated from the contract, the server and the docstrings when the site is built.

## The project

These live at the root of the repository on GitHub:

- [Contributing](https://github.com/Ulef1005/brick-work/blob/main/CONTRIBUTING.md): set-up, tests, and how a change lands.
- [Releasing](https://github.com/Ulef1005/brick-work/blob/main/RELEASING.md): how a release is cut.
- [Security](https://github.com/Ulef1005/brick-work/blob/main/SECURITY.md): how to report a vulnerability.
- [Changelog](https://github.com/Ulef1005/brick-work/blob/main/CHANGELOG.md): what changed in each release.
- [Licence](https://github.com/Ulef1005/brick-work/blob/main/LICENSE): the MIT licence.

## Development checks

Run the tests, then the whole gate:

```sh
.venv/bin/python -m pytest tests -q
APP_VENV=.venv bash scripts/check.sh
```

The check script includes the naming gate, a standalone smoke test with sockets blocked, the full Python suite, available JavaScript runtime harnesses, and contract consistency checks. The upgrade from a 0.5.0-shaped collection through every schema step is tested in `tests/test_upgrade_path.py`, which `scripts/check.sh` runs.

Decisions that bind future work are recorded as ADRs in [`docs/adr/`](https://github.com/Ulef1005/brick-work/tree/main/docs/adr) in the repository.

## Instruction previews

Schema 4.6 adds nullable thumbnail path and state columns to `instruction_file` through an additive upgrade.
The file row owns the derived preview, so the existing file merge transfers it without another item keyed table.

Attachment queues an `instruction_thumbnail` job. The embedded drainer and worker run it through the existing pipeline ownership and recovery rules.
Each job invokes a child process with argument values, a 10 second deadline, and a 20 MB input limit.
Only the child opens the PDF. Exceptions, native crashes and deadlines mark the preview failed while preserving the original PDF.
Worker startup queues absent previews, including derived files excluded from Borg using `data/instructions/*.thumb.png`.

Preview columns are derived state. Receipt and merge comparisons preserve their current values so rendering never invalidates Undo.

Pending tiles poll the page for one minute. Updates replace preview tiles. The selected tab stays active. Rename forms stay open.
