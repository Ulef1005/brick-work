# 0030. Docs site: generated reference pages, and the hand-built /api/, /mcp/ and /design/ pages retired

- **Status:** accepted
- **Date:** 2026-11-13
- **Decided by:** Ulf, in the approved plan of doc-standard-v1 B1b (ai-wiki `projects/doc-standard-v1`, issue #319): the API v2 and MCP pages are written by markdown-exec, a Python code reference comes from mkdocstrings, API v1 and `/design/` leave the site; the page layout and the scope of the code reference are the implementer's choice inside it, for review

## Context

The docs site had two halves. Zensical built the user docs under `/docs/`; `scripts/build_site.py` built its own `/api/`, `/mcp/` and `/design/` pages with Python-Markdown, outside the docs' navigation and search. The App Docs Standard puts user and developer docs in one Zensical site, with the developer docs as a Developers tab (#327), so reference pages belong there. A reference that is written by hand goes stale; one copied from its source at build time does not. Zensical 0.1.1 has no OpenAPI support of its own yet (it is on its roadmap), but it runs MkDocs plugins.

## Options considered

1. **Keep the hand-built pages** and link them from the Developers tab. No new dependency, but two navigations, two searches and two styles.
2. **Write the references by hand in `docs/`.** One site, but every contract or tool change needs a docs edit, and they drift.
3. **Generate them in the docs build**: markdown-exec prints the API v2 operations from `openapi-v2.yaml` and the MCP tools and resources from the server's adapter (`scripts/docs_reference.py`); mkdocstrings renders the Python code reference from the docstrings.

## Decision

Option 3.
- **API v2 reference** (`docs/developer/api-v2-reference.md`) and **MCP tools and resources** (`docs/developer/mcp-reference.md`) are one markdown-exec block each. They read their sources at build time and copy nothing (#328).
- **Code reference** (`docs/developer/code-reference.md`): mkdocstrings renders `brickwork.core`, the services the REST API and the screens call (the MCP server's adapter is part of it), on one page, one section per module, without source listings. Private names and the importer's migrations, copied unchanged from upstream, are filtered out. The web layer, the API routers, the store and the catalogue builder are left out; the HTTP surface is documented by the API reference.
- `build_docs` runs Zensical from the repository root with the root on `PYTHONPATH`, so the blocks can import `scripts` and `brickwork`. To preview the docs alone: `PYTHONPATH=. zensical serve`.
- The old `/api/` and `/mcp/` URLs keep a stub page that sends the browser on; `/api/openapi-v2.yaml` stays for download. API v1 is not on the site. `/design/` is removed: the ADRs and the 4.0 design are read on GitHub, and the 4.0 design pages that readers need are in the Developers tab.
- When Zensical ships its own OpenAPI support, it replaces the markdown-exec step for the API page.

## Consequences

- New pinned docs dependencies in `requirements-dev.txt`: markdown-exec, and mkdocstrings with mkdocstrings-python, which bring MkDocs 1.6 and its own dependencies (only the plugin API is used; Zensical builds the site). They are release-watch entries in rasp-infra's software-updates `repos.json`; Dependabot may propose an upgrade, which is never merged without building the docs strict with the old and the new version and comparing the reference pages.
- A docstring in `brickwork.core` is now published text: a stale or wrong one shows on the site.
- The docs build imports the app's code, so a module that fails to import breaks the docs build, and the docs tests catch it.
