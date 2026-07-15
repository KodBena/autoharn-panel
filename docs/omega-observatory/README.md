# omega observatory sheets

These four sheets were written 2026-07-15 by scout agents reading the maintainer's
private `omega` codebase (a Go/Weiqi study app: Vue 3 + TypeScript frontend, FastAPI
backend), commissioned to find structural/architectural methods worth adopting for
this repo's ledger-panel SPA. `2026-07-15-structural-reap.md` and
`2026-07-15-frontend-architecture-reap.md` survey current-state architecture;
`2026-07-15-frontend-history.md` reconstructs how that architecture was arrived at;
`2026-07-15-frontend-speed-reap.md` is a performance-postmortem reap. The speed
sheet's "Don't do these" list and the architecture sheet's per-rule adopt/adapt/skip
verdicts are BINDING inputs that `SPEC.md` cites directly, not background reading.

`omega` itself is a private repository and was never published; these sheets
underwent a pre-publication privacy sweep before landing here (absolute local
filesystem paths under the maintainer's home directory were redacted to
generic/repo-relative references — see each sheet's opening paragraph for the
`<redacted: ...>` markers). No other private-project specifics (LAN addresses,
credentials, personal contact information, or verbatim source beyond what an
architecture observation needs) were found during the sweep.
