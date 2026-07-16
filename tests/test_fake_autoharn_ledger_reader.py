"""tests/test_fake_autoharn_ledger_reader.py -- proof that `FakeAutoharnLedgerReader`
(`tests/fakes/fake_autoharn_ledger_reader.py`, work item autoharn-ledger-fake / ledger row 937)
is a genuinely faithful in-memory `AutoharnLedgerPort`, not a set of hardcoded per-scenario
returns. Three scenarios get dedicated, non-trivial coverage because the work item's own brief
names them as the highest-risk parts to get wrong: a real multi-level obligation tree
(`test_obligation_tree_multi_node_tree`), a real `item_id` collision across two ledger rows
(`test_decomposition_items_ambiguous_collision`), and a real multi-hop witness resolution
(`test_resolve_witness_work_ref_multi_hop`). Every other Protocol method also gets at least one
real, seeded-data test below -- nothing here is mocked; every assertion is computed by the fake
from plain dicts/sets it was seeded with, the same shape of computation the real
`extensions/autoharn/ledger_read.py` performs from SQL.

Structural conformance itself (`reader: AutoharnLedgerPort = FakeAutoharnLedgerReader()`) is a
STATIC claim -- Python does not check variable annotations at runtime, so the real proof is
`venv/bin/mypy` reporting no error on that assignment, not this file's own test run. The
assignment is still exercised below (module scope) so a change that breaks the shape fails
loudly under mypy the next time this file is linted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "tests"))

from config import ConnectionFacts, PanelConfig  # noqa: E402
from extensions.autoharn.ports import AmbiguousItem, AutoharnLedgerPort, ResolvedItem  # noqa: E402
from fakes.fake_autoharn_ledger_reader import FakeAutoharnLedgerReader  # noqa: E402


def build_cfg(*, maintainer_principal: str = "maintainer") -> PanelConfig:
    """Same placeholder-field shape as tests/test_commission_trust.py's own `build_cfg` --
    `PanelConfig` is a frozen dataclass and every field is required, but the fake only ever
    reads `maintainer_principal` off it (`maintainer_cosigned`); every other field is inert for
    this file's purposes."""
    connection = ConnectionFacts(pg_uri=None, pg_host="127.0.0.1", pg_port=None, pg_db="toy",
                                  pg_user=None, pg_password=None, source="test-scratch")
    return PanelConfig(
        repo_root=Path("/nonexistent"), connection=connection, schema="s", kern_schema="k", role=None,
        led_bin=None, read_only_locked=True, bind_host="127.0.0.1", bind_port=8421,
        poll_interval=2.0, extensions=("autoharn",), config_source="test-scratch",
        maintainer_principal=maintainer_principal, active_profile=None, available_profiles=(),
    )


# ---------------------------------------------------------------------------------------------
# Structural conformance.
# ---------------------------------------------------------------------------------------------

def test_structural_conformance() -> None:
    reader: AutoharnLedgerPort = FakeAutoharnLedgerReader()
    assert reader is not None


# ---------------------------------------------------------------------------------------------
# HARD PART 1 -- obligation_tree's recursive conjunction-discharge walk: a genuine multi-node,
# multi-level tree (composite parent, 2+ levels of nested children), not a single trivial node.
# ---------------------------------------------------------------------------------------------

def test_obligation_tree_multi_node_tree() -> None:
    """root (composite) -> [child-a (leaf, closed/discharged) -> [child-a-note (leaf,
    superseded)], child-b (composite, discharged-by-obligations) -> [grandchild-1 (leaf, open/
    undischarged), grandchild-2 (leaf, closed but review-deferred -> ambiguous-partial)]].
    Three levels deep, mixed composite/leaf kind, and all four DISCHARGE_STATES values appear
    across the tree -- proves both the recursive walk and the classification function, not just
    one node's happy path."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()

    fake.open_work_item("root", "Root composite", composite=True, state="open", effective_state="open")
    fake.open_work_item("child-a", "Child A", state="closed", effective_state="closed")
    fake.open_work_item("child-b", "Child B", composite=True, state="open",
                         effective_state="discharged-by-obligations")
    fake.open_work_item("grandchild-1", "Grandchild 1", state="open", effective_state="open")
    fake.open_work_item("grandchild-2", "Grandchild 2", state="closed", effective_state="closed")
    fake.mark_deferred_undischarged("grandchild-2")
    fake.open_work_item("child-a-note", "Superseded leaf", state="closed", effective_state="closed",
                         resolution="superseded")

    fake.add_obligation_edge("root", "child-a")
    fake.add_obligation_edge("root", "child-b")
    fake.add_obligation_edge("child-a", "child-a-note")
    fake.add_obligation_edge("child-b", "grandchild-1")
    fake.add_obligation_edge("child-b", "grandchild-2")

    tree = fake.obligation_tree(cfg, "root")
    assert tree is not None
    assert tree.slug == "root"
    assert tree.kind == "composite"
    assert tree.discharge_state == "undischarged"
    assert {c.slug for c in tree.children} == {"child-a", "child-b"}

    child_a = next(c for c in tree.children if c.slug == "child-a")
    assert child_a.kind == "leaf"
    assert child_a.discharge_state == "discharged"
    assert len(child_a.children) == 1
    assert child_a.children[0].slug == "child-a-note"
    assert child_a.children[0].discharge_state == "superseded"

    child_b = next(c for c in tree.children if c.slug == "child-b")
    assert child_b.kind == "composite"
    assert child_b.discharge_state == "discharged"
    assert {c.slug for c in child_b.children} == {"grandchild-1", "grandchild-2"}

    gc1 = next(c for c in child_b.children if c.slug == "grandchild-1")
    assert gc1.discharge_state == "undischarged"
    assert gc1.children == ()
    gc2 = next(c for c in child_b.children if c.slug == "grandchild-2")
    assert gc2.discharge_state == "ambiguous-partial"

    # This is a REAL recursive tree, not a flat list -- three levels deep from root.
    assert tree.children and child_b.children


def test_obligation_tree_missing_root_returns_none() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    assert fake.obligation_tree(cfg, "never-opened") is None


def test_obligation_tree_diamond_renders_shared_node_twice() -> None:
    """A DAG diamond (two composites both depending on the same antecedent) renders as more than
    one node -- the real function's own documented behavior -- and the `visiting` guard exists
    for a genuine cycle without ever needing to fire here."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    fake.open_work_item("top", "Top", composite=True, state="open", effective_state="open")
    fake.open_work_item("left", "Left", composite=True, state="open", effective_state="open")
    fake.open_work_item("right", "Right", composite=True, state="open", effective_state="open")
    fake.open_work_item("shared", "Shared antecedent", state="closed", effective_state="closed")
    fake.add_obligation_edge("top", "left")
    fake.add_obligation_edge("top", "right")
    fake.add_obligation_edge("left", "shared")
    fake.add_obligation_edge("right", "shared")

    tree = fake.obligation_tree(cfg, "top")
    assert tree is not None
    left = next(c for c in tree.children if c.slug == "left")
    right = next(c for c in tree.children if c.slug == "right")
    assert left.children[0].slug == "shared" and left.children[0].discharge_state == "discharged"
    assert right.children[0].slug == "shared" and right.children[0].discharge_state == "discharged"


# ---------------------------------------------------------------------------------------------
# HARD PART 2 -- decomposition_items' ambiguous-item grouping: 2+ rows genuinely sharing one
# item_id, plus the full derive_status ladder on a genuinely-resolved item.
# ---------------------------------------------------------------------------------------------

def test_decomposition_items_ambiguous_collision() -> None:
    """Two DIFFERENT ledger rows, same commission, same item_id 'A1' (the legacy `panel-item:`
    note convention, which carries no slug-uniqueness constraint) -- the genuine identity-
    collision `decomposition_items` must carry as data, never silently resolve to a winner."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    commission_row = fake.add_commission("commission: decompose the thing")
    row1 = fake.add_panel_item_note(commission_row, "A1", "first claimant of A1")
    row2 = fake.add_panel_item_note(commission_row, "A1", "second, colliding claimant of A1")
    row3 = fake.add_panel_item_note(commission_row, "A2", "the well-behaved item")

    groups = fake.item_id_groups(cfg, commission_row)
    assert groups["A1"] == (row1, row2)
    assert groups["A2"] == (row3,)

    result = fake.decomposition_items(cfg, commission_row)
    by_id = {item.item_id: item for item in result.items}
    assert isinstance(by_id["A1"], AmbiguousItem)
    assert by_id["A1"].candidate_row_ids == (row1, row2)
    assert isinstance(by_id["A2"], ResolvedItem)
    assert by_id["A2"].status == "OPEN"


def test_decomposition_items_resolved_status_ladder() -> None:
    """OPEN -> WITNESSED -> PARTIAL -> COSIGNED, driven by two independently-evolving witnesses
    (the item's own self-witness plus a second `work:` witness) -- proves `derive_status` is fed
    genuinely-computed, evolving `WitnessFacts`, not injected labels."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    commission_row = fake.add_commission("commission: build the widget")
    fake.open_work_item("helper-item", "A helper obligation")
    fake.open_work_item("widget-item", "Build the widget",
                         refs=f"row:{commission_row} work:helper-item")

    def only_item(commission_row: int) -> ResolvedItem:
        items = fake.decomposition_items(cfg, commission_row).items
        assert len(items) == 1 and isinstance(items[0], ResolvedItem)
        return items[0]

    assert only_item(commission_row).status == "OPEN"

    widget_closed = fake.close_work_item("widget-item", id=500)
    assert only_item(commission_row).status == "WITNESSED"

    helper_closed = fake.close_work_item("helper-item", id=501)
    assert only_item(commission_row).status == "WITNESSED"

    fake.add_review(widget_closed, verdict="attest", actor_name="maintainer", id=600)
    item = only_item(commission_row)
    assert item.status == "PARTIAL"
    assert item.item_cosign["cosigned"] is False  # the ITEM's own row, not the witness's, is checked here

    fake.add_review(helper_closed, verdict="attest", actor_name="maintainer", id=601)
    item = only_item(commission_row)
    assert item.status == "COSIGNED"


def test_decomposition_items_item_row_fast_path_cosign() -> None:
    """derive_status rule 0: the item's OWN ledger row maintainer-cosigned -> COSIGNED
    regardless of witness state (its self-witness here is still open/not substantive)."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    commission_row = fake.add_commission("commission: fast path test")
    item_row_id = fake.open_work_item("fast-path-item", "Fast path item", refs=f"row:{commission_row}")
    fake.add_review(item_row_id, verdict="attest", actor_name="maintainer")

    items = fake.decomposition_items(cfg, commission_row).items
    assert len(items) == 1 and isinstance(items[0], ResolvedItem)
    item = items[0]
    assert item.status == "COSIGNED"
    assert item.item_cosign["cosigned"] is True


# ---------------------------------------------------------------------------------------------
# HARD PART 3 -- resolve_witness's multi-hop resolution.
# ---------------------------------------------------------------------------------------------

def test_resolve_witness_work_ref_multi_hop() -> None:
    """A 'work' witness ref chains: work_item(slug) -> its closed_row_id -> maintainer_cosigned
    against that closed row. Asserts the INTERMEDIATE facts (closed_row_id, the cosign flag) at
    each hop, not just the final label -- proving the chain itself, not merely its end state."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    fake.open_work_item("hoppy-item", "Some obligation", state="open", effective_state="open")

    # Hop 0: not yet closed -> not substantive, no cosign target at all.
    facts, _resolved = fake.resolve_witness(cfg, "work", "hoppy-item")
    assert facts.exists is True
    assert facts.substantive is False
    assert facts.cosign_target_row is None
    assert facts.maintainer_cosigned is False

    # Hop 1: close it -- now substantive, cosign target is the closing row, not yet cosigned.
    closed_row_id = fake.close_work_item("hoppy-item", id=777)
    facts, resolved = fake.resolve_witness(cfg, "work", "hoppy-item")
    assert facts.substantive is True
    assert facts.cosign_target_row == closed_row_id == 777
    assert facts.maintainer_cosigned is False
    assert resolved is not None and resolved["closed_row_id"] == 777

    # Hop 2, not yet satisfied: a NON-maintainer attest does not complete the chain.
    fake.add_review(closed_row_id, verdict="attest", actor_name="someone-else", id=900)
    facts, _resolved = fake.resolve_witness(cfg, "work", "hoppy-item")
    assert facts.maintainer_cosigned is False

    # Hop 2, satisfied: the configured maintainer principal attests against the closing row.
    fake.add_review(closed_row_id, verdict="attest", actor_name="maintainer", id=901)
    facts, _resolved = fake.resolve_witness(cfg, "work", "hoppy-item")
    assert facts.maintainer_cosigned is True
    assert facts.cosign_target_row == 777


def test_resolve_witness_row_ref_single_hop_for_contrast() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    row_id = fake.add_row("decision", "some decision")
    facts, resolved = fake.resolve_witness(cfg, "row", str(row_id))
    assert facts.exists is True
    assert facts.substantive is True  # a 'row' witness is substantive as soon as it resolves
    assert facts.cosign_target_row == row_id
    assert resolved is not None and resolved["id"] == row_id


def test_resolve_witness_nonexistent_and_bad_ref_kind() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    facts, resolved = fake.resolve_witness(cfg, "work", "never-opened-slug")
    assert facts.exists is False and resolved is None

    facts, resolved = fake.resolve_witness(cfg, "row", "not-an-int")
    assert facts.exists is False and resolved is None

    with pytest.raises(ValueError):
        fake.resolve_witness(cfg, "bogus-kind", "x")


# ---------------------------------------------------------------------------------------------
# Every remaining Protocol method, each against real seeded data.
# ---------------------------------------------------------------------------------------------

def test_autoharn_health() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    fake.set_stamp_secret_armed(False)
    health = fake.autoharn_health(cfg)
    assert health["stamp_secret_armed"] is False
    assert "attest" in health["verdicts"]
    assert "self-review" in health["independence_values"]


def test_recent_ledger_ordering_and_limit() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    for i in range(5):
        fake.add_row("note", f"row {i}")
    recent = fake.recent_ledger(cfg, 3)
    assert [r["id"] for r in recent] == [5, 4, 3]

    with pytest.raises(ValueError):
        fake.recent_ledger(cfg, 0)


def test_work_items_blocked_by() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    fake.open_work_item("a", "A", claimant_name="alice")
    fake.open_work_item("b", "B")
    fake.add_blocks_close_edge("a", "b")
    items = {i["slug"]: i for i in fake.work_items(cfg)}
    assert items["a"]["blocked_by"] == ["b"]
    assert items["b"]["blocked_by"] == []
    assert items["a"]["claimant_name"] == "alice"


def test_view_passthroughs_sort_by_their_own_key() -> None:
    """review_gap/work_violations/question_status/standing_decisions mirror kernel views this
    fake does not re-derive (not this work item's hard parts) -- seeded directly, but still
    proven to sort the same way their real SQL's ORDER BY does."""
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    fake.seed_review_gap([
        {"id": 2, "actor": 1, "actor_name": "a", "scope": "s", "assigned_by": None, "assigned_by_name": None},
        {"id": 1, "actor": 1, "actor_name": "a", "scope": "s", "assigned_by": None, "assigned_by_name": None},
    ])
    assert [r["id"] for r in fake.review_gap(cfg)] == [1, 2]

    fake.seed_work_violations([
        {"violation": "v2", "slug": "s", "detail": "d", "target_id": 9},
        {"violation": "v1", "slug": "s", "detail": "d", "target_id": 1},
    ])
    assert [r["target_id"] for r in fake.work_violations(cfg)] == [1, 9]

    fake.seed_question_status([
        {"question_id": 2, "statement": "q2"}, {"question_id": 1, "statement": "q1"},
    ])
    assert [r["question_id"] for r in fake.question_status(cfg)] == [1, 2]

    fake.seed_standing_decisions([
        {"id": 2, "grade": "durable", "statement": "d2"}, {"id": 1, "grade": "durable", "statement": "d1"},
    ])
    assert [r["id"] for r in fake.standing_decisions(cfg)] == [1, 2]


def test_findings_and_snags() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    fake.add_row("finding", "a finding", id=1)
    fake.add_row("note", "not this one", id=2)
    fake.add_row("snag", "a snag", id=3)
    kinds = [(r["id"], r["kind"]) for r in fake.findings_and_snags(cfg)]
    assert kinds == [(3, "snag"), (1, "finding")]


def test_ledger_row_and_row_refs_text() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    rid = fake.add_row("decision", "a decision", refs="row:1 work:foo")
    assert fake.ledger_row(cfg, rid) == {
        "id": rid, "kind": "decision", "statement": "a decision",
        "ts": "2026-01-01T00:00:00+00:00", "actor_name": None,
    }
    assert fake.ledger_row(cfg, 99999) is None
    assert fake.row_refs_text(cfg, rid) == "row:1 work:foo"
    assert fake.row_refs_text(cfg, 99999) is None


def test_item_witnesses_generic_refs_parsing() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    target = fake.add_row("decision", "target")
    holder = fake.add_row("work_closed", "closing act", refs=f"row:{target} work:some-slug")
    witnesses = fake.item_witnesses(cfg, holder)
    assert {(w.ref_kind, w.ref) for w in witnesses} == {("row", str(target)), ("work", "some-slug")}


def test_reviews_for_row_and_maintainer_cosigned_and_latest_review_id() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    target = fake.add_row("decision", "target")
    fake.add_review(target, verdict="attest_with_reservations", actor_name="reviewer",
                     independence="technical", discharge_grade="distinct-session", id=10)
    fake.add_review(target, verdict="attest", actor_name="maintainer",
                     independence="managerial", discharge_grade="same-session", id=11)

    reviews = fake.reviews_for_row(cfg, target)
    assert [r["review_id"] for r in reviews] == [10, 11]
    assert reviews[1]["discharge_grade"] == "same-session"

    cosign = fake.maintainer_cosigned(cfg, target)
    assert cosign is not None and cosign["review_id"] == 11
    assert fake.cosign_fact(cfg, target) == {
        "cosigned": True, "by": "maintainer", "review_id": 11, "verdict": "attest",
    }
    assert fake.latest_review_id(cfg, target, "reviewer") == 10
    assert fake.latest_review_id(cfg, target, "nobody") is None


def test_fetch_parsed_item_rows_both_conventions() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    commission_row = fake.add_commission("commission: mixed convention test")
    legacy_row = fake.add_panel_item_note(commission_row, "legacy-A", "legacy item", extra_refs="row:1")
    current_row = fake.open_work_item("current-slug", "Current item",
                                       refs=f"row:{commission_row} work:extra-witness")

    parsed = fake.fetch_parsed_item_rows(cfg, commission_row)
    by_row = {p.row_id: p for p in parsed}
    assert by_row[legacy_row].item_id == "legacy-A"
    assert by_row[legacy_row].witness_refs == (("row", "1"),)
    assert by_row[current_row].item_id == "current-slug"
    assert by_row[current_row].witness_refs == (("work", "current-slug"), ("work", "extra-witness"))


def test_commission_trust_ladder() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()

    lazy_statement = ("(vicarious transcription by the implementer; carries no commissioner "
                       "guarantee) ask")
    lazy_row = fake.add_commission(lazy_statement, actor_name="author")
    assert fake.commission_trust_for_row(cfg, lazy_row, "author", lazy_statement)["trust_level"] == "lazy"

    full_row = fake.add_commission("plain ask", actor_name="commissioner", stamp_agent=None)
    assert fake.commission_trust_for_row(cfg, full_row, "commissioner", "plain ask")["trust_level"] == "full"

    signed_row = fake.add_commission("plain ask, signed", actor_name="commissioner")
    fake.bank_signature(signed_row, "VERIFIED", detail="ok")
    assert fake.commission_trust_for_row(
        cfg, signed_row, "commissioner", "plain ask, signed",
    )["trust_level"] == "signed"

    forged_row = fake.add_commission("plain ask, forged", actor_name="commissioner")
    fake.bank_signature(forged_row, "FORGED-OR-CORRUPT", detail="bad sig")
    assert fake.commission_trust_for_row(
        cfg, forged_row, "commissioner", "plain ask, forged",
    )["trust_level"] == "forged"

    unverifiable_row = fake.add_commission("plain ask, unverifiable", actor_name="commissioner")
    fake.bank_signature(unverifiable_row, "NO-COMMITTED-KEY")
    assert fake.commission_trust_for_row(
        cfg, unverifiable_row, "commissioner", "plain ask, unverifiable",
    )["trust_level"] == "unverifiable"


def test_commissions_listing() -> None:
    cfg = build_cfg()
    fake = FakeAutoharnLedgerReader()
    commission_row = fake.add_commission("commission: the ask", actor_name="author")
    fake.open_work_item("item-one", "Item one", refs=f"row:{commission_row}")
    fake.open_work_item("item-two", "Item two", refs=f"row:{commission_row}")

    commissions = fake.commissions(cfg)
    assert len(commissions) == 1
    assert commissions[0]["row_id"] == commission_row
    assert commissions[0]["item_count"] == 2
    assert commissions[0]["trust_level"] == "lazy"
