# 0009. With a password set, every web page requires login

- **Status:** accepted
- **Date:** 2026-10-16
- **Decided by:** Ulf (maintainer)

## Context

During the legacy removal, a review found that the collection jump and other read pages had no login check, so they were readable anonymously even with a password set.

## Options considered

Other options: not recorded.

Recommendation at the time: not recorded; the change was listed as a behaviour change for Ulf's approval.

## Decision

With a password set, every web page requires login, including the collection and planning pages. Only an explicit public list is exempt.

## Consequences

- A route-walk test requires login on every web route except the public list, so new pages are protected by default.
- Anyone who relied on anonymous read access now has to log in.

## Links

Related: ADR 0008.
