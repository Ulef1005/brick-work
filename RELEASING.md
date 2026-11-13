# Releasing Brick Work

How a release is made, start to finish. A release is a `vX.Y.Z` tag on `main`, made by the maintainer; the tag builds and publishes the container image. The tag is the last step of the repository work, not the first: everything below up to **Tag** has to be on `main` and green before it is made. The mechanics of the image are in [CONTRIBUTING](CONTRIBUTING.md#releases-and-the-container-image); this page is the checklist.

Use it as a copy-and-tick list in the release pull request.

## 1. Decide the release

- [ ] The version number: a patch (`X.Y.Z+1`) for fixes, a minor (`X.Y+1.0`) for new functions, a major only when something users rely on breaks.
- [ ] The milestone's issues are closed or moved, and its gate issue says the phase is done.
- [ ] **Schema:** does the release change the schema (`SCHEMA_VERSION` in `brickwork/store4/connect.py`)? If so there is an in-place step in `store4.connect.UPGRADES`, a migration test, and the way back is the backup, not an older version.
- [ ] `main` is green (the `check` workflow) and the Codex review of everything since the last tag is done.

## 2. Write the documents

- [ ] **Changelog:** rename `## Unreleased` in `CHANGELOG.md` to `## Brick Work X.Y.Z (schema A.B) · YYYY-MM-DD` and open a fresh empty `## Unreleased` above it. One bullet per change, written for users. `tests/test_changelog_order.py` lists the headings: add the new one.
- [ ] **User docs:** every new function has a how-to guide and, when it is a whole workflow, a tutorial with pictures. A how-to guide says `*Since X.Y.Z.*` under its title (an unreleased one says the release it ships in). The docs index pages link the new pages. `zensical build --strict` must pass (it is part of `scripts/check.sh`).
- [ ] **Upgrade guide:** a row in the table of `docs/how-to/upgrade.md`: from, to, schema, what runs, how to go back.
- [ ] **Reference and contract:** settings, the CLI reference, the API contract (`docs/brickwork/api-v2.md`, `openapi-v2.yaml`) and the ADRs of the decisions in this release are current; the contract checks in `scripts/check.sh` enforce the API part.
- [ ] **README:** the feature text mentions the new functions; the pinned install steps are bumped (next section).

## 3. Update the pictures, the website and the demo

- [ ] **Pictures:** if a screen changed, regenerate the README, Pages and tutorial pictures with `python scripts/site_shots.py` (the README and tutorial pictures are captures of the demo's richer world, the Pages pictures of the real-sets world; none are gate baselines; `python scripts/site_social.py` remakes the social preview) and open each one to check it.
- [ ] **Chrome tests and screen gate:** the pull request check skips every Chrome test and every Node test (`BW_NO_CHROME=1`; the push to `main` runs them), so run `scripts/check.sh` without it on a Linux machine before the release and have it green. **Screen gate:** every changed approved screen has its baselines replaced with the maintainer's written approval recorded in `design/APPROVALS.md`. The screen gate is not part of the `check` workflow any more (2026-11-13): run it by hand before the release (`python -m pytest tests/test_screen_gate.py -q -p no:xdist`, on Linux, which decides) and have it green.
- [ ] **Website:** the Pages site is built from `main` by the `pages` workflow (landing page, workflows, use cases, user docs, API reference, MCP guide, changelog, design pages, `llms.txt`). Edit the sources in `scripts/site/` where the text changed; the landing page carries the version (`scripts/site/landing.html`).
- [ ] **Demo:** the static demo (`scripts/build_demo.py`) is rebuilt by the same workflow from the app on `main`, so it shows the release's screens. Run `scripts/check_demo_pages.py` locally when a screen changed, and open the demo after the deploy.

## 4. The release pull request

One pull request, "Release X.Y.Z", that changes only version pins and release text:

- [ ] `brickwork/version.py` and the image tag in `compose.yaml` (`tests/test_compose_image.py` fails if they differ).
- [ ] The version the install steps pin: the README's and the landing page's `git clone --branch vX.Y.Z`, the `compose.yaml` link in [Install on your computer with Docker Desktop](docs/how-to/install-docker-desktop.md), `docs/reference/cli.md`, `scripts/site/llms.md` (`tests/test_install_docs.py` fails if one is left behind).
- [ ] The changelog heading, the upgrade table row and the `Since` labels of section 2.
- [ ] `scripts/check.sh` green, the pull request green, merged. Note the merge commit: that commit is the release.

## 5. Tag

- [ ] The maintainer tags the merge commit `vX.Y.Z` and pushes the tag. The notes of the GitHub release are the changelog section of the release.
- [ ] The `release` workflow builds the image on amd64 and arm64, runs the fresh-install smoke test, then pushes `ghcr.io/ulef1005/brick-work` tagged `X.Y.Z`, `X.Y` and `X` (and `latest` for a stable release), with a provenance and an SPDX SBOM attestation. Nothing is pushed unless the repository variable `GHCR_PUBLISH` is `true`.
- [ ] **Verify the image:** the tags exist and point at one multi-architecture manifest (`docker buildx imagetools inspect ghcr.io/ulef1005/brick-work:X.Y.Z`), the attestations verify (`gh attestation verify oci://ghcr.io/ulef1005/brick-work:X.Y.Z --owner Ulef1005`), and `latest` and the shorter tags moved only if this is the highest stable release.
- [ ] **Fresh install:** on a clean folder, follow the install steps of the README with the new tag: the container starts, creates its collection, `/api/v2/health` reports the version and the schema.
- [ ] **Upgrade:** open a copy of a real collection from the previous release with the new image; it comes up and `brickwork check` is clean.

## 6. After the tag

- [ ] **Pages:** the `pages` workflow ran on the release pull request's merge. Check the live site: the version on the landing page, the changelog page, the new docs and tutorials, the demo.
- [ ] **Unraid template:** if the template's requirements changed (the minimum version, a new setting or path), update the Community Applications template repository and its README; the image tag it pulls is `latest`.
- [ ] **Announce:** the release notes page, and where the project is discussed, link the changelog section.
- [ ] **Issues:** each issue the release closes has an implemented note: what changed, its tests, the version, screenshots for screens.
- [ ] **The maintainer's own instances:** upgrade through the steps in the upgrade guide. For a release that changes the schema, take and check a backup first; rolling back is restoring it.

## If something is wrong after the tag

Never move or recreate a published tag. Fix on `main` and release the next patch version. The `release` workflow can build an existing tag again by hand (the aliases only ever move to the highest stable release).
