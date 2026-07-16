"""extensions.autoharn.parsers -- the three PURE, no-I/O statement/token parsers that used to
live inline in `extensions/autoharn/ledger_adapter.py` (work item autoharn-god-module-split,
ledger row 935/1094): `parse_item_refs`, `parse_witness_refs`, `parse_resource_fields`, plus
their supporting regexes and two private helpers (`_resource_tier_kind`, `_row_token_matches`).
Bodies are VERBATIM (ADR-0004 minimal-touch) -- only their module moved.

Deliberately their OWN module, not folded into any of the four internal-collaborator files that
split out alongside this one (`decomposition_reader.py`, `work_obligation_reader.py`,
`queue_views_reader.py`) or left in `ledger_adapter.py` itself: `decomposition_reader.py`'s
`fetch_parsed_item_rows` needs `parse_item_refs`/`parse_witness_refs`/`_row_token_matches`, and
`ledger_adapter.py`'s facade needs to re-export `parse_item_refs`/`parse_witness_refs`/
`parse_resource_fields` for existing test back-compat (`tests/test_item_view.py`,
`tests/test_disposition.py` import them from `extensions.autoharn.ledger_adapter`) -- giving
these functions their own dependency-free module lets both sides import FROM here with no
import cycle between `ledger_adapter.py` (which constructs `DecompositionReader`) and
`decomposition_reader.py` (which would otherwise need something back from `ledger_adapter.py`).

Zero I/O, zero `db`/`psycopg` import, deliberately NOT `AutoharnLedgerPort` methods (`ports.py`'s
own docstring: forcing well-factored pure code onto a DB-swapping interface buys nothing) --
callable directly by whatever adapter, collaborator, or test needs them, with no fake required.
"""
from __future__ import annotations

import re
from typing import Any

_PANEL_ITEM_TOKEN_RE = re.compile(r"^panel-item:(?P<cid>\d+):(?P<iid>[A-Za-z0-9_-]+)$")
_ROW_TOKEN_RE = re.compile(r"^row:(?P<id>\d+)$")
_WORK_TOKEN_RE = re.compile(r"^work:(?P<slug>[A-Za-z0-9_.-]+)$")


def parse_witness_refs(refs_text: str | None) -> list[tuple[str, str]]:
    """Generic `row:<id>` / `work:<slug>` witness-token extraction from ANY row's `refs` text --
    unlike `parse_item_refs`, this does NOT require a wrapping `panel-item:<commission>:...` token.
    Used by the item view (SPEC.md sec 2.2's "disposition/witness edges") to show witness/co-sign
    edges for an arbitrary ledger row, not just a decomposition item row."""
    out: list[tuple[str, str]] = []
    for tok in (refs_text or "").split():
        m = _ROW_TOKEN_RE.match(tok)
        if m:
            out.append(("row", m.group("id")))
            continue
        m = _WORK_TOKEN_RE.match(tok)
        if m:
            out.append(("work", m.group("slug")))
    return out


# The six fields a `resource:`-prefixed decision statement carries, in order (design/USER-
# BLESSED-TABLE-TEMPLATE.md's "statement grammars" section -- the ONE documented home of this
# grammar, also transcribed by autoharn's own `./pickup` RESOURCES section,
# `bootstrap/templates/pickup.tmpl`'s `_RESOURCE_FIELDS`/`resources()`). `parse_resource_fields`
# below is a SECOND reader of the same convention (the item view's per-row enrichment, not
# session-hydration display), so it is deliberately kept field-for-field consistent with that one
# rather than inventing its own shape.
_RESOURCE_STATEMENT_RE = re.compile(r"^\s*resource:")


def _resource_tier_kind(tier: str) -> str:
    """Normalizes a TIER field's leading word to one of the four fixed tier classes a frontend
    badge keys off of -- same `startswith` precedence pickup.tmpl's `_resource_tier_rank` sorts by
    (forbidden outranks mandated outranks blessed, design/ORCH-SPEC-RESOURCE-ACCOUNTING.md §3), just
    returning a class name here instead of a sort rank. An unrecognized tier string (or a bare
    `available`) maps to 'available', matching that function's own catch-all -- sorting/badging
    degrades gracefully, it never errors on a tier word this module doesn't happen to recognize."""
    t = tier.strip().lower()
    if t.startswith("forbidden"):
        return "forbidden"
    if t.startswith("mandated"):
        return "mandated"
    if t.startswith("blessed"):
        return "blessed"
    return "available"


def parse_resource_fields(statement: str) -> dict[str, Any] | None:
    """Parses a `resource:`-prefixed decision statement into its six pipe-delimited fields
    (NAME | CLASS | REACH | WHAT-IT-PROVES | GUIDANCE | TIER) for the item view's structured display
    (cycle-4 audit finding 6, SERIOUS: the item detail view rendered the whole statement as one
    undifferentiated prose blob, no parsed tier badge or labeled fields). Returns `None` for
    anything that isn't a `resource:` statement, or is one but doesn't carry exactly six
    '|'-separated fields (a malformed row) -- the caller's job in either case is to fall back to the
    plain-prose rendering core's own item view already does unconditionally, never to hide or
    replace the original statement text.

    Mirrors `bootstrap/templates/pickup.tmpl`'s `resources()` byte-for-byte in the two respects that
    matter for staying the SAME parser as that one (design/USER-BLESSED-TABLE-TEMPLATE.md's
    "statement grammars" section: "these are NOT the same parser" is a hazard only when two parsers
    of the same grammar silently diverge, not when the grammar is genuinely mirrored): an embedded
    newline (a paste reflowed by a terminal's line wrap) is collapsed to a single space BEFORE the
    field split, the run12 witness fix that section documents; and the prefix is stripped by
    splitting on the FIRST colon in the (now newline-normalized) statement, not a literal
    `len("resource:")` slice, so `resource:` arriving with no space before the first field still
    splits correctly."""
    normalized = re.sub(r"[\n\r]+[ \t]*", " ", statement).lstrip()
    if not _RESOURCE_STATEMENT_RE.match(normalized):
        return None
    body = normalized.split(":", 1)[1] if ":" in normalized else ""
    fields = [f.strip() for f in body.split("|")]
    if len(fields) != 6:
        return None
    name, cls, reach, proves, guidance, tier = fields
    return {
        "name": name,
        "class_": cls,
        "reach": reach,
        "what_it_proves": proves,
        "guidance": guidance,
        "tier": tier,
        "tier_kind": _resource_tier_kind(tier),
    }


def parse_item_refs(refs_text: str | None, commission_row: int) -> tuple[str | None, list[tuple[str, str]]]:
    """PURE, anchored, fail-closed parser (see disposition.py's module docstring for the full
    rationale, ported unchanged from the autoharn PoC): a `refs` string that does not carry EXACTLY
    ONE well-formed `panel-item:<commission_row>:...` token returns `(None, [])`."""
    tokens = (refs_text or "").split()
    matching_item_ids: list[str] = []
    witness_refs: list[tuple[str, str]] = []
    wanted_cid = str(commission_row)
    for tok in tokens:
        m = _PANEL_ITEM_TOKEN_RE.match(tok)
        if m:
            if m.group("cid") == wanted_cid:
                matching_item_ids.append(m.group("iid"))
            continue
        m = _ROW_TOKEN_RE.match(tok)
        if m:
            witness_refs.append(("row", m.group("id")))
            continue
        m = _WORK_TOKEN_RE.match(tok)
        if m:
            witness_refs.append(("work", m.group("slug")))
            continue
    if len(matching_item_ids) != 1:
        return None, []
    return matching_item_ids[0], witness_refs


def _row_token_matches(refs_text: str | None, commission_row: int) -> bool:
    """True iff `refs_text` carries a well-formed, EXACT `row:<commission_row>` token -- the same
    anchored-token discipline `_PANEL_ITEM_TOKEN_RE`/`_ROW_TOKEN_RE` use elsewhere in this module,
    so a LIKE prefilter (`row:24` matching `row:247`) never survives into the returned set."""
    wanted = str(commission_row)
    for tok in (refs_text or "").split():
        m = _ROW_TOKEN_RE.match(tok)
        if m and m.group("id") == wanted:
            return True
    return False
