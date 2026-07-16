# makespan-scheduler backflow — functionality wanted, not yet built

This file records functionality this project has wanted from
[`makespan-scheduler`](/home/bork/w/vdc/1/experience/makespan-scheduler) (the sibling
checkout declared as a blessed resource, ledger row 38) while actually using it, so a real
gap doesn't just live in a session transcript and get re-discovered from scratch next time.
Mirrors `AUTOHARN_BACKFLOW.md`'s own pattern (feedback about a dependency, recorded in the
consuming repo, not the dependency's own tree) — kept here rather than there because this
project stays fixed in one repository at a time rather than working across several.

Each entry: what was wanted, why the tool couldn't do it, and what's blocked without it.
An entry is removed (or marked done, with the commit/PR that closed it) once the maintainer
merges a fix — this file tracks *wanted-but-not-yet-built*, not a permanent complaint log.

## Currently in progress, not a backlog entry

Native directed-precedence support (job A must finish before job B starts — today the
scheduler only has undirected resource conflicts and a global concurrency cap) is **already
being patched**, not merely wished for here — see ledger row 289 and the
`add-precedence-constraints` branch in the makespan-scheduler checkout once that workflow
lands. It isn't listed as an open entry below because it's actioned, not pending.

## Open entries

(none yet — this file is a stub, ready for the next real gap)
