"""extensions.autoharn.disposition — the PURE derivation of a decomposition item's live status
(SPEC.md sec 2.4/2.7, ported unchanged from the autoharn PoC's `panel/backend/disposition.py`).

This is the pairing-RCA-safe module in this build: status is NEVER computed once and stored,
it is recomputed from freshly-read ledger facts on EVERY request (ledger_read.py does the
reads; app.py/ledger_read.py call `derive_status`/`group_item_rows` with what was read). The
lesson this design is built against (ledger row 8f1cd25's own RCA, cited in this session's
CLAUDE.md context) is that a computed pairing/discharge VERDICT stored on a row can go stale or
be wrong-by-construction the moment the join it was derived from changes -- so this module
stores nothing, computes from its arguments alone, and is trivially unit-testable with no
database (seen-red/panel-disposition/).

`derive_status` takes already-read `WitnessFacts` (ledger_read.py's job is turning a
decomposition item row's declared `--refs` witness tokens into these) plus one bool -- whether
the item's OWN ledger row has itself been maintainer-cosigned -- and returns one of the four
non-AMBIGUOUS labels in `config.STATUS_VALUES`. It knows nothing about SQL, HTTP, or the
`./led` grammar: a witness that could not be resolved at read time (a bad ref) arrives here
simply as `exists=False`.

`group_item_rows` is the second pure function this module owns: it groups parsed
`(item_id, row_id)` pairs and hands back the FULL tuple of row ids per item id, never narrowed
to one -- a caller (`ledger_read.decomposition_items`/`item_id_groups`) branches on group size to
decide a normal `ResolvedItem` (size 1) from a `AmbiguousItem` (size >=2, spec sec 3); this
module has no way to pick a winner and does not try.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WitnessFacts:
    """The live ledger facts for ONE decomposition-item witness, already resolved by
    `ledger_read.py`. Carries no SQL/connection state -- a plain data record so this module's
    derivation is a pure function testable with hand-built values (seen-red/panel-disposition/'s
    RED/GREEN specimens).

    ref_kind / ref: the item row's own witness identity (a work slug, or a ledger row id as text).
    exists: the ref resolved to a real work item or ledger row at all. False for a dangling/
        invalid ref -- such a witness contributes nothing (never fabricate a witness to make an
        item look complete, spec sec 9's hack-rationalization warning).
    substantive: the resolved fact is strong enough to WITNESS the item -- a work item in state
        'closed' (an open/unclaimed work item is NOT substantive: an item still being worked is
        not yet witnessed), or any resolved ledger row (a 'row' witness is substantive as soon
        as it resolves -- it names a concrete act already on the ledger).
    cosign_target_row: the ledger row id a co-sign against this witness would `regards` -- the
        work item's `work_closed` row id, or the row id itself for a 'row' witness. None when
        there is nothing a co-sign could target yet (e.g. an open work item).
    maintainer_cosigned: a live, unsuperseded `review` row exists with `regards=cosign_target_row`,
        `verdict='attest'`, actor = the configured maintainer principal -- the SAME join
        `review_gap` uses (verdict + distinct actor), read fresh, never a stored flag.
    """
    ref_kind: str
    ref: str
    exists: bool
    substantive: bool
    cosign_target_row: int | None
    maintainer_cosigned: bool


def group_item_rows(pairs: tuple[tuple[str, int], ...]) -> dict[str, tuple[int, ...]]:
    """Group parsed `(item_id, row_id)` pairs by `item_id`. PURE, and deliberately does not
    narrow a multi-row group to one: a value tuple of length >= 2 IS the identity-collision
    signal (spec sec 3's duplicate-item-identity hazard) -- it is carried as data in full so the
    caller (never this function) decides whether to build a `ResolvedItem` (length 1) or an
    `AmbiguousItem` (length >= 2). Preserves each item_id's row ids in the order they were seen."""
    groups: dict[str, list[int]] = {}
    for item_id, row_id in pairs:
        groups.setdefault(item_id, []).append(row_id)
    return {item_id: tuple(row_ids) for item_id, row_ids in groups.items()}


def derive_status(item_row_cosigned: bool, witnesses: list[WitnessFacts]) -> str:
    """Pure. Rules (spec sec 5, restated exactly):

    0. The item's OWN ledger row has been maintainer-cosigned (`item_row_cosigned`) -> COSIGNED,
       regardless of witnesses -- the item-row fast path: "I co-signed item A1" as one atomic
       act, made possible by decomposition items now being ledger rows in their own right.
    - No witnesses, or every witness resolves to something not-yet-substantive (e.g. an open/
      unclaimed work item) -> OPEN.
    - >=1 substantive witness, none co-signed by the maintainer -> WITNESSED.
    - Some but not all substantive witnesses co-signed -> PARTIAL.
    - Every substantive witness co-signed -> COSIGNED (an equivalent completion to the item-row
      fast path, not a different state).

    A non-existent (dangling) witness ref is dropped from consideration entirely -- it is
    neither substantive nor co-signed, so it behaves exactly like "no witness" for the purpose
    of this function; an item whose ONLY witnesses are dangling reads OPEN, same as an item
    with an empty witness list (unless the item-row fast path already applies).

    `AMBIGUOUS` is never produced here -- it is a property of the group (spec's `AmbiguousItem`),
    decided by the caller before `derive_status` is ever invoked for that item_id; a
    `ResolvedItem` is always exactly one of this function's four possible return values.
    """
    if item_row_cosigned:
        return "COSIGNED"
    substantive = [w for w in witnesses if w.exists and w.substantive]
    if not substantive:
        return "OPEN"
    cosigned = [w for w in substantive if w.maintainer_cosigned]
    if len(cosigned) == len(substantive):
        return "COSIGNED"
    if cosigned:
        return "PARTIAL"
    return "WITNESSED"
