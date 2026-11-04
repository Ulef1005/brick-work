# Brick Work brand guide

Brick Work has its own design, outside Toni's World (Ulf, 2026-11-03; ADR 0022). This guide follows the App Design Standard's order (P1). It is being filled in during the roll-out (#158 D1 → #161 D4): until a section is approved under the standard, it names where the current, previously approved design lives and reads **Not yet approved under the standard**. Approvals are recorded in [APPROVALS.md](APPROVALS.md). The rules for building with it are the `brickwork-design` skill (`.claude/skills/brickwork-design/SKILL.md`).

## SUCCESS

Hichert's SUCCESS governs this design. The per-rule lines are written when the brand guide is approved (workflow step 7). Not yet approved under the standard.

## 1. Logo

The cross-stitch mark, wordmark and lockups, light and dark: today in `static/brickwork/` (`mark.svg`, `mark-dark.svg`, `mark-line.svg`, the lockups). They move to `logo/` in #159. Not yet approved under the standard.

## 2. App logo

PWA icons, splash screens, favicons and the manifest: today in `static/brickwork/` (`icons/`, `splash/`, `favicon*`, `manifest.webmanifest`). They move to `app-icon/` in #159, generated from `logo/`. Not yet approved under the standard.

## 3. Colour

Roles and tokens, light and dark: `tokens/brickwork-tokens.css` and the generated `tokens/brickwork-tokens.json`, loaded after the pinned neutral base `tokens/tokens.css` (`scripts/tokens_base.py`; the served stylesheet is generated from the two). The values are the ones Brick Work served before the roll-out, unchanged. Not yet approved under the standard.

## 4. Type

Inter (text), Geist Mono (numbers and codes), Patrick Hand (brand surfaces only), as set in `tokens/brickwork-tokens.css`. The font files and licences are in `static/fonts/` today. Not yet approved under the standard.

## 5. Layout

Spacing, safe areas, 44 px targets and the bars, as set in `tokens/brickwork-tokens.css`. Not yet approved under the standard.

## 6. Components

The built components, as the design kit v1.3 frames show them (`frames.json`, `sections/`). Not yet approved under the standard.

## 7. Screens

The v1.3 frames: 57 sections in `frames.json`, PNGs in `frames/` (light and dark, 1440 / 1024 / 390). They move to `screens/NN-<screen>/` with `screens/manifest.json` in #159; the screenshot gate (#160) compares the built app with approved captures per screen. Not yet approved under the standard.

## 8. Icons

The UI icons (1.6 px stroke, 24 px grid) in `static/brickwork/icons-ui/`. Not yet approved under the standard.

## 9. Wording

Sentence case, empty states that say what is empty, what still works and one way out; errors in words. Not yet approved under the standard.

## 10. Data and charts

The IBCS notation of the design builder's `base/charts.md`, on Brick Work's colours. Not yet approved under the standard.

## 11. Approvals

See [APPROVALS.md](APPROVALS.md).
