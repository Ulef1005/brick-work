# Upstream BrickTracker migrations (vendored)

SQL migrations `0001`–`0030` and the two Python context steps (`0007`, `0027`) of the upstream
BrickTracker project, copied unchanged from its `release/1.5` branch (commit `ca6c9f6`, 2026-08-09),
MIT licence (`LICENSE-upstream`; the Brick Work `LICENSE` keeps the upstream notice).

They are used only by the BrickTracker import (`brickwork/core/importer/bricktracker.py`) to upgrade a
**copy** of a user's `app.db` to the newest upstream schema it knows before mapping it. The user's
file is never written. A database newer than `0030` is refused with a clear message.
