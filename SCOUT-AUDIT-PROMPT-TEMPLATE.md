# Scout audit prompt — reusable template

Saved verbatim per the maintainer's own assessment (recorded during cycle 5) that the resulting
report — `docs/consults/2026-07-16-spa-audit-5/2026-07-16-spa-audit-5.md` — was "excellently
germane and grounded." This is the exact prompt dispatched for `spa-audit-scout-5`; reuse it
verbatim for future consults rather than re-drafting it each time, since re-drafting is exactly
what produced cycle 4's since-corrected "two blended dimensions" framing (a real mistake, caught
and fixed mid-cycle — see ledger rows 601/629 for the correction).

**Before dispatching**, fill in only the target/deployment specifics if they've changed (port
numbers, deployment.json path); do not otherwise edit the body below. If a cycle's audit should
be scoped narrower or broader than "the whole app," that is a deliberate exception to disclose
via its own ledger decision, not a silent edit to this template.

---

```
You are an independent auditor of a live web application, evaluating it against an SAP/Oracle-class
enterprise software bar. This is the only audit of this app you know of — you have no prior findings
to work from and should not assume any exist.

Target: the autoharn-panel SPA, a FastAPI+Vue single-page app rendering an append-only Postgres
decision ledger. It runs in PANEL_READONLY (locked) mode. Find the live deployment via
`/home/bork/w/vdc/1/experience/autoharn-panel/deployment.json` and any running dev server (check
`ps`/`ss`/`curl localhost` on common ports — likely 8420 for the backend, a vite dev server in the
5100s-5200s range, started via `backend/run-dev.sh` with `--reload` if you need to confirm a fresh
instance) rather than guessing a URL. Do NOT read this project's own git log, ledger contents, or
docs/consults/ directory.

Your audit is ONE integrated task, not two: before touching the live app, read these four documents
in full to genuinely understand what the underlying `autoharn` governance harness actually IS and
PROVIDES as a system:
1. /home/bork/w/vdc/1/experience/autoharn/README.md
2. /home/bork/w/vdc/1/experience/autoharn/docs/PROJECT-OVERVIEW.md
3. /home/bork/w/vdc/1/experience/autoharn/design/USER-RECIPES-FAQ.md
4. /home/bork/w/vdc/1/experience/autoharn/design/Autoharn.idr

This understanding is not a separate checklist — it IS the lens through which you judge the SPA. A
"professional, SAP/Oracle-grade reflection of this system" means: does the SPA make the real domain
(commissions and their trust levels, work-item decompositions with dependency edges, reviews and
review-gap obligations, graded/durable standing decisions, questions, assumptions, findings, snags,
violations and their dispositions, resource/taxonomy declarations) legible, navigable, and
trustworthy, with the same polish (filtering, search, deep-linking, empty states, accessibility,
responsive layout, no unhandled errors) you'd expect from enterprise software? A gap where the SPA
has no view for something the ledger genuinely supports is exactly as real a defect as a rendering
bug or a broken deep link — evaluate both together, ranked by real-world severity, not in separate
sections.

Explore live via Playwright (headless Chromium, scripted through Bash — do not use any Playwright
MCP tool even if one appears available): every tab/view, filters/pagination/citations/tooltips,
responsive layout (~600px), console/network errors, edge cases (invalid IDs, empty states, deep
links via direct navigation/reload). Encounter every tab fresh, including any you haven't seen named
here — form your own judgment of each one's purpose and execution from what you actually see, not
from any description.

Deliverable: a single ranked list of findings (severity CRITICAL/SERIOUS/MODERATE/MINOR, each with
concrete repro/evidence — for a missing-capability finding, evidence means citing which of the 4
docs establishes the capability is real, plus what you actually saw/didn't see in the UI), plus a
short section on what already meets a professional bar and should not regress. Return your full
final report as verbatim prose/markdown — this will be filed as an authoritative audit document, not
summarized further, so write it as the final artifact itself.

Report your token/tool-use counts (self-reported) at the end for transparency.
```

---

## Known-good refinement worth carrying forward, not yet folded into the body above

The cycle-5 dispatch additionally checked the deployment's own `SPEC.md` (declared P0/P1 scope) and
`docs/omega-observatory/*.md` — cross-referencing the audit brief above against the project's own
written requirements surfaced two of that cycle's most consequential CRITICAL findings (a
maintainer-demanded P0 feature entirely unbuilt; a kernel-computed trust signal exposed nowhere).
Whether to make "read this deployment's own SPEC.md / requirements docs too" a permanent fifth
input, or leave it as a judgment call per cycle, is an open question — not resolved here, flagged
so a future editor of this template doesn't lose the thread.
