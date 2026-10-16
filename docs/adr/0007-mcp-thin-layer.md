# 0007. MCP is a thin layer over the API

- **Status:** accepted
- **Date:** 2026-10-15
- **Decided by:** Ulf (maintainer)

## Context

Part of the standalone goal (ADR 0001) is that outside tools, including AI agents, can use the app through a standard surface.

## Options considered

Not recorded. The plan named an MCP server as a thin layer over the same functions as the API and CLI.

Recommendation at the time: thin layer over the same functions.

## Decision

The MCP server is a thin layer over the API's functions. Write tools are available only when the server runs with `--allow-write` and the caller's token has write scope.

## Consequences

- 27 read tools and 8 resources are always available; 22 write tools only when enabled.
- Transports: stdio, and Streamable HTTP at `/mcp` with a bearer check.
- No separate business logic to keep in step with the API.

## Links

`docs/brickwork/api-v1.md` section 7. Related: ADR 0001, 0003.
