#!/usr/bin/env python3
"""seed/author_0714_decomposition.py -- the commission-680 decomposition SEED, ported from the
autoharn PoC (`panel/seed/author_0714_decomposition.py`) into this repo's own layout.

**This is a point-in-time SEED, not a running service.** It carries NO runtime authority: the
panel backend never reads this file, never imports it, and never re-runs it as part of serving
a request. Its one job is to author, ONCE, the `kind='note'` ledger rows that decompose ledger
row 680 ("MAINTAINER EXECUTIVE RESPONSE 2026-07-14") in the AUTOHARN deployment this seed
targets, per the `panel-item:<commission_row>:<item_id>` refs convention the `autoharn`
extension implements. After it runs, the ledger rows ARE the sole source of the decomposition --
a correction is a ledger `--supersedes` on the affected item row, authored by hand via
`LED_BIN`, never a re-run of this script (a re-run is safe -- see Idempotency below -- but is
not how a correction is made). This script is autoharn-specific data (it targets one real
deployment's row 680), kept here as the worked example and re-runnable idempotent seed for
whichever deployment adopts this repo's `autoharn` extension against that same ledger.

This script deliberately does NOT re-derive the `panel-item:` refs grammar. It imports
`extensions.autoharn.ledger_read.parse_item_refs` (the ONE anchored, fail-closed parser of that
grammar in this tree) and `resolve_witness` (the ONE witness resolver), so this write path and
the panel's read path can never diverge on what counts as "item `<iid>` already exists" or
"witness `<ref_kind>:<ref>` resolves".

Connection facts are resolved via `backend.config.load_config` (this repo's own config module,
SPEC.md sec 1) -- no hardcoded host, a loud SystemExit refusal if nothing resolves.

Idempotency: before writing item `<iid>`, this script fetches ALL commission-680 note rows via
the SAME commission-scoped coarse prefetch `fetch_parsed_item_rows` performs (`refs LIKE
'%panel-item:680:%'`, deliberately NOT scoped to `<iid>` itself), then filters by Python string
EQUALITY on `parse_item_refs`'s anchored, fully-delimited `item_id` -- never a substring/LIKE
test on the item id, which would false-match a shorter id against a longer sibling's token
(e.g. `A1` against `A10`).
  - Zero matches -> write the item.
  - Exactly one match -> SKIP (idempotent no-op; safe to re-run this script).
  - Two or more matches -> ABORT that item's write, name every colliding row id loudly, and
    continue to the NEXT item -- never add a third competing claim on top of an already-
    ambiguous pair, and never silently treat a duplicate as "already present."

Witness discipline: every candidate witness token below was independently verified live
against the deployed ledger before being hardcoded here. At RUN TIME this script re-verifies
every candidate witness again via `resolve_witness` and DROPS (never invents) any that fail to
resolve live at run time, so a witness that existed when this script was authored but was later
superseded/deleted does not ship a stale citation. An item whose every candidate witness drops
gets a refs string carrying ONLY its `panel-item:` token and renders OPEN honestly -- never a
fabricated witness.

Usage: `python3 seed/author_0714_decomposition.py` (from anywhere; paths are resolved relative
to this file, not the caller's cwd). Requires `LED_BIN` set (this script's writes go through
it, exactly as the panel's own cosign write path does) -- no direct INSERT, no parallel write
path.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent

sys.path.insert(0, str(_REPO_ROOT / "backend"))  # config.py, extensions/, core/ live here

import config as panel_config  # noqa: E402
from extensions.autoharn.ledger_read import (  # noqa: E402
    fetch_parsed_item_rows,
    parse_item_refs,
    resolve_witness,
)

COMMISSION_ROW = 680


@dataclass(frozen=True)
class SeedItem:
    """One candidate decomposition item, authored by hand against a live re-read of ledger
    row 680 and independently re-verified witness candidates (see module docstring). `witnesses`
    is `tuple[(ref_kind, ref), ...]` -- the CANDIDATE set; `resolve_witness` (run-time) decides
    which of these actually resolve and ship."""
    item_id: str
    label: str
    witnesses: tuple[tuple[str, str], ...]


# The item universe below was enumerated independently from a live `./led show 680` read (not
# trusted from the deleted v1 manifest, though that manifest's own enumeration -- verified
# correct by this re-read -- is the same 39-item universe): Part A1 (A1, A2); the 20 Part A2
# control families (AC, AT, AU, CA, CM, CP, IA, IR, MA, MP, PE, PL, PM, PS, PT, RA, SA, SC, SI,
# SR) plus P1-P7; the B block (B1-B6 plus the wall-clock-prod note); and three Concerns.
ITEMS: tuple[SeedItem, ...] = (
    SeedItem(
        "A1",
        "Part A1 / A1 -- Stage 0 ADOPTED; (b) fact-family engine integration prioritized "
        "(the engine is the project's unique strength, facts feed it natively); (a) derived "
        "RDF/JSON-LD export planned in parallel once fact: stabilizes; the grammar path is "
        "named a BRIDGE, not the destination, with an explicit migration path to richer EDB "
        "facts. DISCHARGED per the kr-titration design-space exploration (closed/shipped) "
        "and its review-done disposition.",
        (("work", "kr-titration-design-exploration"), ("row", "681")),
    ),
    SeedItem(
        "A2",
        "Part A1 / A2 -- pgAudit exercised by a Sonnet agent (not the maintainer directly, "
        "per his explicit instruction), autoharn DB backed up first. DISCHARGED: backup "
        "WITNESSED before the conf read; pgaudit.so preloaded but pgaudit.log='none' (PRESENTLY "
        "INERT) -- the gap exercised live and reported, config-scope choice queued to the "
        "maintainer as a proposal, per the standing config-fragments-need-the-real-file rule.",
        (("work", "pgaudit-exploration"), ("row", "716")),
    ),
    SeedItem(
        "AC",
        "Part A2 control family AC (Access Control) -- posture >= PARTIAL, reasoned from "
        "observed agent attempts to circumvent access control. Posture recorded in the "
        "registry-audit umbrella disposition; the underlying hazard (an automated helper "
        "reaching a powerful DB account) is the still-open credential-separation work item, "
        "so AC's code-side discharge remains honestly open even though its posture is filed.",
        (("row", "683"), ("work", "scaffold-owner-credential-separation")),
    ),
    SeedItem(
        "AT",
        "Part A2 control family AT (Awareness and Training) -- posture EPSILON, nominally "
        "ABSENT (the maintainer's own personal-projects self-provisioning goal not yet "
        "achieved). Posture recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "AU",
        "Part A2 control family AU (Audit and Accountability) -- posture >= PARTIAL, named a "
        "core ('Pillar') project feature. Posture recorded in the registry-audit umbrella "
        "disposition; the pgAudit exploration thread is the concrete audit-logging work this "
        "posture leans on.",
        (("row", "683"), ("work", "pgaudit-exploration")),
    ),
    SeedItem(
        "CA",
        "Part A2 control family CA (Security Assessment and Authorization) -- maintainer "
        "not competent to judge, deferred to the orchestrator (his line ends mid-sentence in "
        "the source; the truncation is preserved, not guessed at, in row 680 and transcribed "
        "verbatim in the registry-audit umbrella disposition).",
        (("row", "683"),),
    ),
    SeedItem(
        "CM",
        "Part A2 control family CM (Configuration Management) -- posture >= PARTIAL, "
        "documented GxP practice with a strictly positive outcome elsewhere. Posture recorded "
        "in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "CP",
        "Part A2 control family CP (Contingency Planning) -- maintainer not competent to "
        "judge the family generally, but operationally worth deliberating (composes with the "
        "P3/P7 backup items). Posture recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "IA",
        "Part A2 control family IA (Identification and Authentication) -- posture >= "
        "PARTIAL, composing with AU and AC. Posture recorded in the registry-audit umbrella "
        "disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "IR",
        "Part A2 control family IR (Incident Response) -- posture >= PARTIAL, tied to "
        "formalizing the 'spy' method as observability-driven development (same work item as "
        "Concern 2). Posture recorded in the registry-audit umbrella disposition; the spy-method "
        "formalization work item remains open, unclaimed.",
        (("row", "683"), ("work", "spy-method-formalization")),
    ),
    SeedItem(
        "MA",
        "Part A2 control family MA (Maintenance) -- maturity-conditional: not yet worth "
        "addressing at the project's current maturity level, could be revisited later. Posture "
        "recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "MP",
        "Part A2 control family MP (Media Protection) -- not within scope, or not tractably "
        "within scope and low ROI. Posture recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "PE",
        "Part A2 control family PE (Physical and Environmental Protection) -- same "
        "disposition as MP (out of tractable scope). Posture recorded in the registry-audit "
        "umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "PL",
        "Part A2 control family PL (Planning) -- apparently not applicable. Posture recorded "
        "in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "PM",
        "Part A2 control family PM (Program Management) -- maintainer not competent to "
        "judge. Posture recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "PS",
        "Part A2 control family PS (Personnel Security) -- never applicable under any "
        "possible circumstances. Posture recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "PT",
        "Part A2 control family PT (PII Processing and Transparency) -- applicable but not "
        "within scope; aspiration explicitly rejected. Posture recorded in the registry-audit "
        "umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "RA",
        "Part A2 control family RA (Risk Assessment) -- may apply. Posture recorded in the "
        "registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "SA",
        "Part A2 control family SA (System and Services Acquisition) -- potential SA-3 "
        "candidacy via the makespan-scheduling guarantee, once airtight; explicitly flagged as "
        "NOT a Fable task (high demotion-to-Opus likelihood). Posture recorded in the "
        "registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "SC",
        "Part A2 control family SC (System and Communications Protection) -- maintainer not "
        "competent to judge. Posture recorded in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "SI",
        "Part A2 control family SI (System and Information Integrity) -- possibly "
        "aspirational, maintainer not competent to judge. Posture recorded in the "
        "registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "SR",
        "Part A2 control family SR (Supply Chain Risk Management) -- never applicable under "
        "any possible circumstances. Posture recorded in the registry-audit umbrella "
        "disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "P1",
        "Part A2, P1 -- scope-adjudication batch: 'maybe.' Substantially discharged IN "
        "WRITING by the full 20-family posture list delivered in row 680 itself and "
        "transcribed by the registry-audit umbrella disposition; an interactive P1 follow-up "
        "remains open if appropriate (named as such by the maintainer's own closing line).",
        (("row", "683"),),
    ),
    SeedItem(
        "P2",
        "Part A2, P2 -- dependency/tooling inventory (python, clingo, psql/pgAudit, OR-Tools; "
        "Gentoo + OpenSUSE + libvirt/qemu + nvim + claude-code). Load-bearing inventory "
        "confirmed in the registry-audit umbrella disposition.",
        (("row", "683"),),
    ),
    SeedItem(
        "P3",
        "Part A2, P3 -- SQL-dump-to-GitHub backup, approved if size permits, explicitly named "
        "incomplete without pgAudit read-log data. Tracker item opened for the mechanism; "
        "honestly still OPEN (not yet built).",
        (("row", "683"), ("work", "registry-audit-sql-dumps-github-incomplete")),
    ),
    SeedItem(
        "P4",
        "Part A2, P4 -- pgAudit provisioned, 'let's see where that takes us.' DISCHARGED via "
        "the pgAudit exploration thread (closed/shipped); registry-audit umbrella disposition "
        "records 'P4 via pgaudit.'",
        (("row", "683"), ("work", "pgaudit-exploration")),
    ),
    SeedItem(
        "P5",
        "Part A2, P5 -- confirmed. Registry-audit umbrella disposition records 'P5 "
        "confirmed.'",
        (("row", "683"),),
    ),
    SeedItem(
        "P6",
        "Part A2, P6 -- accept. Registry-audit umbrella disposition records 'P6 "
        "ABSENT-AND-NAMED accepted' (a law/STANDARDS-REGISTRY.md edit deferred to its "
        "Fable-authored/maintainer-ratified route -- accepted in principle, not yet a law/ "
        "edit).",
        (("row", "683"),),
    ),
    SeedItem(
        "P7",
        "Part A2, P7 -- backup/retention policy, its absence named organizational negligence "
        "by the maintainer. Tracker item opened for the tracker DB's backup/retention policy; "
        "honestly still OPEN (policy not yet written).",
        (("row", "683"), ("work", "registry-audit-backup-retention-policy")),
    ),
    SeedItem(
        "B1",
        "Part B, B1 -- the ADR-0017 'ratification packet' ghost referent: excavate what "
        "happened. DISCHARGED: two-stage causation found (real packet filed 2026-07-11 but "
        "cited as prose not a link -- an ADR-0017 Rule 2(a) violation live from birth, "
        "structurally unexcavatable by the ledger since the ledger's own first row postdates "
        "ratification; the forgivable-if-structural class); fix shipped (bare referent + "
        "attestations).",
        (("work", "adr-0017-ratification-packet-referent"), ("row", "720"), ("row", "729")),
    ),
    SeedItem(
        "B2",
        "Part B, B2 -- automate the bare-P-label detector (the A1.A2-vs-Part-A2 heading "
        "collision named as its own live specimen of the confusion class). DISCHARGED: "
        "detector shipped, gate witnessed clean corpus-wide.",
        (("work", "adr-bare-p-label-detector"), ("row", "729")),
    ),
    SeedItem(
        "B3",
        "Part B, B3 -- fix the three known blind spots in gates/adr_portability_terms.py. "
        "DISCHARGED: shield gaps fixed, gate witnessed clean corpus-wide (residuals "
        "legitimately shielded).",
        (("work", "adr-portability-terms-gate-shield-gaps"), ("row", "729")),
    ),
    SeedItem(
        "B4",
        "Part B, B4 -- structurally prevent an automated helper from self-escalating DB "
        "privileges. Partial progress: scaffold verified to never write owner passwords "
        "(grep-witnessed); host-side pg_hba/.pgpass reachability UNVERIFIED, the classifier "
        "correctly refused credential-store scanning rather than being routed around -- "
        "honestly still OPEN, residual named for the maintainer.",
        (("work", "scaffold-owner-credential-separation"), ("row", "716")),
    ),
    SeedItem(
        "B5",
        "Part B, B5 -- decouple a merge on next from instantly changing live adopter "
        "deployments (git-submodule pinning). DISCHARGED: idiot-proof pinning delivered "
        "(new-project --pin submodule, convert-to-submodule.sh, upgrade-submodule.sh, "
        "live-session guard), 17 both-polarity fixtures registered.",
        (("work", "deployment-live-exec-coupling"), ("row", "761")),
    ),
    SeedItem(
        "B6",
        "Part B, B6 -- the countersign-obligation actor-vs-item scoping bug, constitutional "
        "route. Spec RATIFIED (item-keyed obligations, typed two-constructor close); Sonnet "
        "build DELIVERED on a worktree but NOT YET MERGED into kernel/lineage on next -- the "
        "underlying fix is built, not yet shipped; honestly still OPEN pending the "
        "maintainer's own apply-at-birth act.",
        (("work", "countersign-scoping-actor-not-item"), ("row", "717"), ("row", "735")),
    ),
    SeedItem(
        "wall-clock-prod",
        "Part B, wall-clock A:B:C review-loop dominance -- acknowledged by the maintainer, no "
        "decision taken yet (lower priority than other matters). The disposition IS the "
        "deferral, recorded as such, not a fix.",
        (("row", "686"),),
    ),
    SeedItem(
        "concern-1",
        "Concern 1 -- migration path for the broken real ~/ent deployment: a recovery mode, "
        "a signed root-provisioning ledger entry, a separately signed recovery act. Design "
        "SHIPPED (fails hard keyless by construction, honoring the standing crypto-deferral "
        "ruling -- key generation not yet done); the concrete ~/ent migration itself has Phase "
        "1 rehearsal COMPLETE on real ent data, Phase 2 live apply reserved to the maintainer -- "
        "honestly still OPEN end to end.",
        (
            ("work", "recovery-mode-signed-authority"),
            ("row", "714"),
            ("work", "ent-inplace-migration"),
            ("row", "755"),
        ),
    ),
    SeedItem(
        "concern-2",
        "Concern 2 -- formalize the 'spy' method as observability-driven development of "
        "autoharn itself (composes with the IR control-family posture above). Honestly still "
        "OPEN, unclaimed.",
        (("work", "spy-method-formalization"),),
    ),
    SeedItem(
        "concern-3",
        "Concern 3 -- two random thoughts: 'defeasible epistemic logic' for maintainer "
        "decisions in his absence; a FUSE-mounted virtual filesystem hydrated from a verified "
        "knowledge store. A philosopher-Fable consult was DELIVERED discussing both ideas in "
        "writing (verdicts on the epistemic-logic idea's tenable form; the FUSE idea's "
        "strongest justification named as the read-witness); neither idea is built -- both "
        "remain honestly OPEN, parked.",
        (
            ("work", "defeasible-maintainer-decision-model"),
            ("work", "fuse-vfs-knowledge-hydration"),
            ("row", "697"),
        ),
    ),
)


def _existing_matches(cfg: panel_config.PanelConfig, item_id: str) -> list[int]:
    """The write-side idempotency check (spec sec 9 AMENDED r4/round-3): fetch ALL commission-
    680 note rows via the same commission-scoped coarse prefetch the read side uses, then keep
    only rows whose `parse_item_refs`-parsed `item_id` EQUALS `item_id` by plain string equality
    -- never a substring/LIKE test scoped to the item id itself (that is the exact unanchored-
    substring bug this revision fixes: it would treat 'A10' as a match for a query for 'A1').
    Returns the list of matching row ids, in ascending order (empty if none)."""
    return sorted(r.row_id for r in fetch_parsed_item_rows(cfg, COMMISSION_ROW) if r.item_id == item_id)


def _resolve_candidate_witnesses(
    cfg: panel_config.PanelConfig, item_id: str, candidates: tuple[tuple[str, str], ...]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Re-verify every candidate witness live (never trust the hardcoded list on faith --
    the data can have moved since this script was authored). Returns
    `(kept_tokens, dropped)` where `kept_tokens` are `"row:<id>"`/`"work:<slug>"` strings ready
    to append to the item's refs, and `dropped` is `[(ref_kind, ref), ...]` for the report."""
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for ref_kind, ref in candidates:
        facts, _resolved = resolve_witness(cfg, ref_kind, ref)
        if facts.exists:
            kept.append(f"{ref_kind}:{ref}")
        else:
            dropped.append((ref_kind, ref))
    return kept, dropped


def _write_item(cfg: panel_config.PanelConfig, item: SeedItem) -> None:
    matches = _existing_matches(cfg, item.item_id)
    if len(matches) >= 2:
        print(
            f"[{item.item_id}] ABORTED-duplicate-detected -- {len(matches)} existing rows "
            f"already claim this item id: {matches}. Not writing a third competing claim; "
            f"this collision must be resolved by hand (a ledger --supersedes on the row that "
            f"is wrong), never by this script."
        )
        return
    if len(matches) == 1:
        print(f"[{item.item_id}] SKIPPED -- already present at row {matches[0]} (idempotent no-op).")
        return

    kept_tokens, dropped = _resolve_candidate_witnesses(cfg, item.item_id, item.witnesses)
    for ref_kind, ref in dropped:
        print(f"[{item.item_id}] witness DROPPED (did not resolve live): {ref_kind}:{ref}")
    for tok in kept_tokens:
        print(f"[{item.item_id}] witness WITNESSED (resolves live): {tok}")

    refs_text = " ".join([f"panel-item:{COMMISSION_ROW}:{item.item_id}", *kept_tokens])
    if cfg.led_bin is None:
        print(f"[{item.item_id}] ABORTED -- LED_BIN is not set (this seed writes only through it).")
        return
    env = dict(os.environ)
    env["LED_ACTOR"] = "author"
    result = subprocess.run(
        [str(cfg.led_bin), "--refs", refs_text, "note", item.label],
        cwd=str(cfg.repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[{item.item_id}] WRITE REFUSED (exit {result.returncode}) -- LED_BIN's own teach-text:\n"
            f"{result.stderr.strip()}"
        )
        return

    # Re-fetch to report the row id ./led actually assigned (the wrapper does not hand it back
    # directly; re-reading via the same anchored parse the idempotency check used is the ONE
    # honest way to name it, rather than guessing at a max(id) race).
    post = _existing_matches(cfg, item.item_id)
    if len(post) == 1:
        print(f"[{item.item_id}] WRITTEN -- row {post[0]}, refs=\"{refs_text}\"")
    else:
        print(
            f"[{item.item_id}] WRITTEN but post-write re-read found {len(post)} matching rows "
            f"({post}) instead of exactly one -- report this discrepancy, do not assume success."
        )


def main() -> None:
    cfg = panel_config.load_config(_REPO_ROOT)
    if cfg.led_bin is None:
        print("REFUSED -- LED_BIN is not set; this seed writes only through it. Set LED_BIN and re-run.")
        return

    subprocess.run(
        [str(cfg.led_bin), "register-principal", "author", "model"],
        cwd=str(cfg.repo_root),
        capture_output=True,
        text=True,
    )  # idempotent (ON CONFLICT DO NOTHING); a non-zero exit here is surfaced by the first
    # subsequent write's own refusal, so it is not separately checked.

    print(
        f"Seeding commission {COMMISSION_ROW}'s decomposition against "
        f"schema={cfg.schema} kern={cfg.kern_schema} as LED_ACTOR=author "
        f"({len(ITEMS)} candidate items)."
    )
    for item in ITEMS:
        _write_item(cfg, item)


if __name__ == "__main__":
    main()
