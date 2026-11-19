# 0032. Confirmed instruction downloads use the existing job queue

- **Status:** accepted; backup proposal to be confirmed before prod; amended by [0035](0035-instructions-link-out.md) (Find instructions links out)
- **Date:** 2026-11-16
- **Decided by:** Ulf, issue #25 approved brief

## Decision

Discovery is user triggered and stores candidates without downloading PDFs. Downloads require a confirmed ticked list and use existing jobs with HTTP polling.
Official is the first registered adapter. Rebrickable and Peeron retain injectable source interfaces until verified adapters exist.
Page content is untrusted. Parse only verified cards and accept only HTTPS PDF addresses under the approved product assets path.

Official has a separate download size setting, initially 500 MB. Uploads and other downloads retain 20 MB.
Show file sizes and ticked totals. Untouched defaults never exceed the limit in total; oversized files cannot be ticked.
Unknown sizes start unticked. Validate Content-Length before streaming, bound actual bytes, and verify the PDF header.

Downloads allow 50 files per run, identify Brick Work, space host requests by one second, and honour Retry-After.
The injected rendered page fetcher must enforce these same transport rules, identify Brick Work, and respect robots.txt.
It must fetch only the selected set page, with no unrelated link traversal or browser interaction.

No production page renderer exists in the app. Keep Official registered with its renderer setup notice.
Production needs an injected headless browser service or dependency that returns rendered HTML through this interface. No browser dependency is added here.

## Backup proposal: to be confirmed before prod

Official PDFs can be downloaded again. Propose excluding downloaded files under `data/instructions/` from the Borg unit while retaining their database list.
A restore brings back the list, not the files. Review the shared upload storage before applying this exclusion because uploads also use this path.
Check the rasp disk and Borg size budget before the first bulk download. This decision changes no backup configuration.
