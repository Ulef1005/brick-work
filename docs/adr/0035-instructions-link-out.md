# 0035. Find instructions links out instead of fetching

- **Status:** accepted; amends [0032](0032-instruction-downloads.md) (its discovery and download design is no longer the way instructions arrive)
- **Date:** 2026-11-19
- **Decided by:** Ulf, issue #465 ("Link out (Recommended)", 18 November 2026; split into M and U, 19 November 2026)

## Context

ADR 0032 built Find instructions on discovery: a page renderer fetches the set's LEGO instructions page, and Rebrickable and Peeron adapters add candidates, which the user ticks and Brick Work downloads. No page renderer ships. Official reports "Official needs a page renderer: not set up", and Rebrickable and Peeron were dropped on 16 November 2026. So the feature finds nothing in a normal install. A renderer would also scrape a page and raise the terms-of-use question that issue #25 left open.

## Decision

Find instructions links out. For a set it offers the set's instructions page on LEGO, by region, and its page on Rebrickable. The user downloads the PDF there and the existing Upload a PDF takes the file. Brick Work fetches nothing and scrapes nothing, so no renderer and no terms-of-use issue arise.

- `instruction_links(set_no, region)` in `brickwork/core/instruction_links.py` is a pure function that returns `[{source, label, url}]`, LEGO first. The LEGO URL comes from `official_instructions.page_url`, the one place that builds it (the locales are not duplicated). The region defaults to the retail country setting, and to `DE` when that country has no LEGO locale. A malformed set number or an unsupported region is a `ValueError`. A booklet shares its set's number; an item with no born number uses its confirmed BrickLink set or booklet link.
- The links are read-only in API v2 (`GET /items/{id}/instruction-links`) and in the assistant tools (`get_instruction_links`).
- The Official source, the adapter registry, the discovery and download operations and the `find_instructions` and `download_instructions` tools stay as they are. Removing them is a separate decision.

## Consequences

- The Find instructions screen and the three controls that become dead ends move to #484: Add's Fetch instructions switch, the Largest instruction download setting, and the bulk fetch of missing booklets. Until #484 they still exist and do nothing useful.
- The user tutorial and how-to wording is changed by #486, not here.
- **Unverified:** the Rebrickable link `https://rebrickable.com/sets/<number>-<n>/` is a pattern, not checked against the live site, which refuses scripted requests. Ulf is to confirm it in a browser before the screen (#484) shows it. A number without a suffix gets `-1`. Alphanumeric (promotional) numbers such as `COMCON034-1` get this link only, because the LEGO page takes numeric numbers; `links` holds one or two entries.
- The LEGO page is `https://www.lego.com/<locale>/service/building-instructions/<number>?age-gate=grown_up`, the URL the finder already used; it is likewise not re-verified here, and no network check ran in this worktree.
