# 0022. Brick Work leaves Toni's World and takes the App Design Standard layout; the screenshot gate compares the built app with approved captures

- **Status:** accepted
- **Date:** 2026-11-04
- **Decided by:** the maintainer, 4 Nov 2026 via the wiki-agent ("brick work should plan it in milestone B"; the four questions answered with the session's recommendations). Supersedes the launch-kit decision of 2026-10-15 that Brick Work stays inside Toni's World

## Context

The App Design Standard (ai-wiki `app-design-standard.md`, phase 4.3) asks every app for its own neutral base and tokens, the P2 layout under `design/`, and a gate: every approved screen covered by a screenshot test, a token drift check, every moved path still served, and rendered tests that never skip silently. Brick Work still had the old layout: a Toni's World sub-brand skill, two token copies that have diverged, 770 flat frames, no screenshot tests and no drift check. Its `check.sh` skipped the Node harnesses silently.

## Options considered

1. **Screenshots against the design frames** (pixel-equal). The build was never pixel-equal to the frames, and a frame for a shipped feature lists its differences (#136).
2. **Screenshots against approved captures of the built app** per screen state, with the frames kept as the design record.
3. **Token values from the design copy** (`design/tokens-v2.css`) or **from the served copy** (`static/web/toni/tokens-v2.css`).

## Decision

- Option 2 for the screenshot gate. The frames stay the design record.
- The tokens take today's **served** look: no visual change in the roll-out. The design copy's differences go to the maintainer as a list.
- Rendering runs in CI too (Chrome installed in `check.yml`), and a rendered test that can't run fails unless `BW_SKIP_RENDERED=1` is set and named.
- `CLAUDE.md`'s rule "do not edit files in `design/`" becomes "`design/sources/` is the design project's export; `design/` is organised per P2 by scripts".
- Planned as #158–#161 (D1–D4) in milestone B, with a line in gate #96.

## Consequences

- The neutral base (design builder `base/tokens.css`) loads before Brick Work's layer. It only adds custom properties Brick Work doesn't use yet (checked 4 Nov), so no computed value changes.
- Served `/static/brickwork/...` files become generated from `design/`, and old URLs keep answering.
- B's close-out moves after D3/D4.
