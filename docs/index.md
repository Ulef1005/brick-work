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

Installation is in the [README](https://github.com/Ulef1005/brick-work#standalone-installation-with-docker). The REST API and the MCP server have their own pages: [API v2 reference](developer/api-v2-reference.md) and [MCP server](brickwork/mcp.md), under Developers.

## Use with AI assistants

An assistant that should know Brick Work can read [llms.txt](https://brick-work.app/llms.txt), the short facts about the app with links to the key pages, or [llms-full.txt](https://brick-work.app/llms-full.txt), the same facts and those pages in one file. To let an assistant work with a collection, connect it through the [MCP server](brickwork/mcp.md), or script it against the [API v2 reference](developer/api-v2-reference.md) and its [OpenAPI contract](https://github.com/Ulef1005/brick-work/blob/main/docs/brickwork/openapi-v2.yaml).
