# Brick Work

**The workbench for your brick collection.**

> **Status: pre-release (October 2026).** This is a temporary README. The app code is not in this repository yet: it moves here with the first public release, and this file will be replaced by the full README then.

## What Brick Work is

A self-hosted app for private collectors. Every collection app does inventory; Brick Work adds the workflows at the table, so the collection helps you finish what you started: check a copy's parts, pick missing parts from your sorted bulk, see which incomplete sets your loose stock can finish, and count incoming orders.

## Where it stands

| Area | Status |
|---|---|
| App | Built and running on a private test instance; the code moves here at the first release |
| API, CLI and MCP | Built: a versioned REST API with scoped tokens and Undo, an admin CLI, and an MCP server so an AI assistant can query and update the collection |
| Installable app | Works as a PWA from the browser (Home Screen on iPhone and iPad, and desktop); a test on a real Android device is still open |
| Tests | 1,842 passing, plus a standalone smoke test with no keys and no network |
| Design | Reference in [`design/`](design/): open [`design/index.html`](design/index.html) for the frames in light and dark |
| Docs | API and MCP reference planned under `docs/` and GitHub Pages |

## What's next

The public [Brick Work Roadmap](https://github.com/users/Ulef1005/projects/3) shows the order: Now, Next, Later, Shipped. There are no dates; the order is the promise.

- **Now:** import from BrickTracker (#11); import from other apps: Rebrickable CSV, BrickLink XML, Brickset CSV (#12).
- **Next:** one availability model (#22) covering build state per copy (#14) and buildable sets from your loose parts (#9).
- **Later:** collection sync with Rebrickable, Brickset and BrickLink (#10); MOCs as custom sets (#13); barcode scanner for sets (#8).

## Contributing

Not open yet. Issue templates are in place for enhancements and bugs; outside contributions start with the public release.

## Licence

[MIT](LICENSE). Brick Work started from [BrickTracker](https://gitea.baerentsen.space/FrederikBaerentsen/BrickTracker) (MIT) and keeps its notice.

LEGO® is a trademark of the LEGO Group, which does not sponsor, authorise or endorse this project.
