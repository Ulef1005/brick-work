# 0019. The first run is one resumable flow; a step is done only when its data says so

- **Status:** accepted
- **Date:** 2026-11-03
- **Decided by:** the maintainer approved the milestone A re-plan (3 Nov 2026), including the step order and building on the existing frames. He reviewed the guide texts. The flow's design was set by the brick-work session (#83–#87)

## Context

Before milestone A, the first run was a panel on the empty Sets page (12j): keys first, then the catalogue, then Add or the import of an existing collection file, each step linking out. Nothing remembered how far a user had got once Sets was no longer empty. Since 4.0 the catalogue comes from Rebrickable's public dump and needs no key, so asking for keys first held a new user up for nothing.

## Options considered

1. **Keep 12j's order and add the missing steps.** This matches the design, but keeps an optional step in front of the one everything needs.
2. **Catalogue first, then keys (optional), then bring the collection in, then a short guide.** One flow that can be skipped and resumed, its progress stored as a state machine with its own "done" flags.
3. **The same order as 2, but each step's done state read from the install:** a catalogue build is active, a key is stored, the collection holds a copy or loose stock. Only the user's own choices (skipped steps, the guide read) are stored.

Recommendation: 3.

## Decision

- **Four steps, in order:** **Load the catalogue**, **Set up your keys** (optional), **Bring your collection in**, **See how the inventory works**. Bringing the collection in waits for the catalogue; the keys never wait.
- **Done comes from the data,** so the flow can never claim a step that did not happen, and work done elsewhere (a sync, an import, a key stored on Catalogues & keys) counts. Only **Skip for now** and the guide's **Got it** are stored, in `onboarding.json` beside the collection file. That file works before the collection file exists and travels with the data folder.
- **The flow resumes at the first open step,** on the empty Sets page and on **Tools & Admin › Get started**, which stays available after the first run.
- **Each step runs the existing screen's code:** the catalogue job, the key cards of Catalogues & keys (one shared macro), Add, Collection sync and the import. Step 3's choice screen sends you there, and those pages offer the way back.
- **Design:** built on 12j's step cards and 12b's import hub with the existing tokens. The gaps were reported, not drawn: 12j has keys first and no skip control, and there are no frames for the choice screen or the guide.

## Consequences

- A fresh install on test ran the flow end to end without the docs: catalogue in 50 s, a known set added with no API call except its picture (#88).
- The file holds no secret and no collection data. An unreadable file counts as nothing skipped.
- The gate run found two follow-ups, filed for the maintainer's priority: a keyless step shows "failed" (#139), and BrickLink XML part colours need matching on a keyless install (#140).
- When the design is redrawn for the App Design Standard roll-out, the frames should follow this order.
