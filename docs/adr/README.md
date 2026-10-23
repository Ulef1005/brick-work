# Architecture Decision Records

One file per decision that binds future work: the API contract, the data model, licence, scope, a dependency or a security rule. UI details and bug fixes do not get an ADR.

- **Write one** when a decision issue (label `decision`) is answered: copy [`0000-template.md`](0000-template.md) to `NNNN-kebab-title.md` with the next number, link the issue, then close the issue with a link to the ADR.
- **Never edit an accepted ADR's decision.** To change it, write a new ADR and set the old one's status to "superseded by NNNN".

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-standalone-app.md) | Standalone app | accepted | 2026-10-15 |
| [0002](0002-one-name.md) | One name: brickwork | accepted | 2026-10-15 |
| [0003](0003-api-authentication.md) | API v1 authentication | accepted | 2026-10-15 |
| [0004](0004-api-writes-and-audit.md) | API v1 writes and audit | accepted | 2026-10-15 |
| [0005](0005-source-keys-stored-encrypted.md) | Source keys stored encrypted in the app | accepted | 2026-10-15 |
| [0006](0006-api-scope-and-conventions.md) | API v1 scope and conventions | accepted | 2026-10-15 |
| [0007](0007-mcp-thin-layer.md) | MCP is a thin layer over the API | accepted | 2026-10-15 |
| [0008](0008-legacy-removed.md) | Legacy screens and stores removed | accepted | 2026-10-15 |
| [0009](0009-login-on-every-page.md) | With a password set, every web page requires login | accepted | 2026-10-16 |
| [0010](0010-import-progress-polls.md) | Live import progress polls over HTTP | accepted | 2026-10-16 |
| [0011](0011-part-list-rule.md) | Part-list rule | accepted | 2026-10-15 |
| [0012](0012-licence-mit.md) | Licence: MIT | accepted | 2026-10-16 |
| [0013](0013-item-detail-pages.md) | Item detail pages | accepted | 2026-10-16 |
| [0014](0014-github-canonical.md) | GitHub is the canonical repository, starting from a snapshot | accepted | 2026-10-18 |
| [0015](0015-post-go-live-plan-on-github.md) | The post-go-live plan lives in GitHub milestones | accepted | 2026-10-22 |
| [0016](0016-data-model-4.md) | Data model 4.0: Brick Work ids, a catalogue from the Rebrickable dump, one migration | accepted | 2026-10-23 |
