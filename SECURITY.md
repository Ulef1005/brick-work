# Security policy

## Reporting a vulnerability

Please report security problems privately: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue.

Include what you found, how to reproduce it, and the version or commit you tested. You will get a first answer within 14 days. Once a fix is released, the report is published as an advisory with credit to you, unless you prefer otherwise.

## Supported versions

Only the latest release is supported. Fixes are not backported.

## Scope and deployment notes

Brick Work is a self-hosted app meant for a home network or a VPN. Reports are welcome for the app's own code: authentication, the API and its tokens, the stored-key encryption, file handling, imports and exports.

Before exposing an install:

- Set `BW_AUTHENTICATION_PASSWORD`; the server refuses to start without one unless `BW_ALLOW_NO_LOGIN=1` is set on purpose. Keep `data/session.key` (or your `BW_AUTHENTICATION_KEY`) private.
- Keep the app behind a VPN or a reverse proxy; the login back-off counters live in the app process. Behind HTTPS, set `BW_SECURE_COOKIES=1`. Changing the password ends every open session; going back to an earlier password revives sessions opened with it, so to end every session for good, also change `BW_AUTHENTICATION_KEY` (or delete `data/session.key`).
- Set `BW_SECRET_KEY` only if you store source keys in the app, and keep it out of backups of the database.

A problem in BrickLink, Rebrickable, Brickset or Brickognize themselves belongs to those services.
