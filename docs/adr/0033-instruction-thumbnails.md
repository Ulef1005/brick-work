# 0033. Instruction thumbnails use PDFium in bounded jobs

- **Status:** accepted
- **Date:** 2026-11-16
- **Decided by:** Ulf, issue #25

## Context

Sets with multiple instruction files need page previews. A native PDF parser must never block a browser request.

## Decision

Pin pypdfium2 5.15.2. Installed metadata and licence files were checked locally on 16 November 2026.
The bindings offer BSD-3-Clause or Apache-2.0. PDFium uses BSD-3-Clause; bundled library notices include permissive licences such as Apache-2.0 for abseil.
The session checked OSV for the PyPI package on 16 November 2026 and found no known vulnerabilities. No network check ran in this worktree.
Python requires at least 3.6; this installation runs 3.14.

Use the existing durable job queue. Render only page one, at 240 pixels wide, to PNG beside the PDF.
A child process isolates native parser failures and enforces a 10 second deadline. Files larger than 20 MB fail without parsing.
Do not initialise JavaScript or execute document actions. Paths are argument values, never shell commands.
Schema 4.6 adds nullable thumbnail path and state columns to instruction files. Existing merge handling moves these with their file.

## Consequences

Failed previews leave PDFs available. Pending previews show a neutral loading tile. One file retains the existing row.
Thumbnails are derived data. Exclude `data/instructions/*.thumb.png` from Borg; startup queues missing previews after a restore.
This extends ADR 0032 without changing its pending decision about backing up original PDFs. No backup configuration is changed here.
