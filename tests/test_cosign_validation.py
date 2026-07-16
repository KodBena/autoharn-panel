"""tests/test_cosign_validation.py -- unit tests for `extensions.autoharn.cosign.cosign`'s pure
validation-error branches (out-of-vocabulary `verdict`, out-of-vocabulary `independence`,
empty/whitespace-only `basis`). Work item cosign-validation-tests (ledger row 930), acceptance
criteria row 967.

These three checks run BEFORE `cosign()` ever calls `_run_led` (the subprocess/DB-touching write
path) -- ported here as their own no-infrastructure proof, in the same spirit as
tests/test_disposition.py (pure logic needs no Postgres, no LED_BIN, no pytest.mark.skipif gate)
and mirroring tests/test_commission_trust.py's monkeypatched-subprocess pattern (a minimal,
placeholder-valued PanelConfig; the one external dependency replaced with a controlled fake).

Every RED-shaped case below monkeypatches `cosign._run_led` to explode if called at all, so a
regression that let an invalid verdict/independence/basis slip past validation and reach the
subprocess layer fails the test loudly (an AssertionError from the trap) instead of silently
passing, hanging on a real subprocess call, or needing a live LED_BIN to even notice. One
GREEN-shaped negative control (test_valid_input_reaches_run_led) proves the trap is a meaningful
signal and not a fixture that never fires: valid input DOES reach `_run_led`, and its stub
returns `ok=False` so cosign() short-circuits before the ok-branch's reader-typed
`latest_review_id` call -- keeping that test DB-free too. Pure Python: no database, no live
subprocess, runs to completion with both PGHOST and LED_BIN unset.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from config import ConnectionFacts, PanelConfig  # noqa: E402
from extensions.autoharn import cosign  # noqa: E402
from extensions.autoharn.ledger_adapter import PostgresAutoharnLedgerReader  # noqa: E402
from extensions.autoharn.ports import INDEPENDENCE_VALUES, VERDICTS  # noqa: E402

# A real reader instance, never touched by any test in this file: every case here either raises
# CosignValidationError before cosign() ever calls _run_led (which is what would eventually reach
# the reader), or the ok=False stub short-circuits before the reader is used -- see
# test_valid_input_reaches_run_led's own comment. Passing the real, stateless, no-constructor-
# argument class (rather than a mock) keeps this file's own DB-free guarantee (module docstring)
# intact: constructing PostgresAutoharnLedgerReader() does no I/O.
_READER = PostgresAutoharnLedgerReader()


def build_cfg() -> PanelConfig:
    """A syntactically-valid PanelConfig, never actually connected to or shelled out to in this
    file -- every test here either raises before `_run_led` runs, or replaces `_run_led` outright
    with a call-recording stub. Placeholder values in the same shape test_commission_trust.py's
    build_cfg() uses (PanelConfig is a frozen dataclass; every field is required). led_bin is a
    non-existent path on purpose: if any test here ever DID reach the real subprocess.run call,
    that would itself be the failure this file exists to catch, and a bogus path fails fast
    rather than accidentally finding a real `led` binary on the runner's PATH.
    """
    connection = ConnectionFacts(
        pg_uri=None, pg_host="unused.invalid", pg_port=None, pg_db="unused",
        pg_user=None, pg_password=None, source="test-no-db",
    )
    return PanelConfig(
        repo_root=REPO, connection=connection, schema="unused_schema", kern_schema="unused_kernel",
        role=None, led_bin=Path("/nonexistent/led-binary-never-invoked"), read_only_locked=False,
        bind_host="127.0.0.1", bind_port=8420, poll_interval=2.0, extensions=("autoharn",),
        config_source="test-no-db", maintainer_principal="maintainer",
        active_profile=None, available_profiles=(),
    )


def trap_run_led(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces cosign._run_led with a stub that fails the test loudly if called at all -- the
    regression trap every RED-shaped case below installs before calling cosign()."""

    def _boom(cfg: PanelConfig, args: list[str], actor: str | None) -> cosign.LedResult:
        raise AssertionError(
            f"cosign._run_led was called with args={args!r} actor={actor!r} -- a validation-error "
            "branch let invalid input reach the subprocess/DB layer"
        )

    monkeypatch.setattr(cosign, "_run_led", _boom)


# ---------------------------------------------------------------------------
# RED-shaped: each named validation branch raises CosignValidationError, and
# never reaches _run_led (trap_run_led would fail the test if it did).
# ---------------------------------------------------------------------------

def test_bad_verdict_raises_before_run_led(monkeypatch: pytest.MonkeyPatch) -> None:
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError):
        cosign.cosign(build_cfg(), _READER, 1, "not-a-real-verdict", "self-review", "a basis")


def test_bad_independence_raises_before_run_led(monkeypatch: pytest.MonkeyPatch) -> None:
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError):
        cosign.cosign(build_cfg(), _READER, 1, "attest", "not-a-real-independence", "a basis")


def test_empty_basis_raises_before_run_led(monkeypatch: pytest.MonkeyPatch) -> None:
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError):
        cosign.cosign(build_cfg(), _READER, 1, "attest", "self-review", "")


def test_whitespace_only_basis_raises_before_run_led(monkeypatch: pytest.MonkeyPatch) -> None:
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError):
        cosign.cosign(build_cfg(), _READER, 1, "attest", "self-review", "   \t\n  ")


# ---------------------------------------------------------------------------
# Message content: the offending value AND the allowed vocabulary are both
# named in the verdict/independence branches (the two vocabulary checks --
# the basis check has no vocabulary to name, only "must be non-empty").
# ---------------------------------------------------------------------------

def test_bad_verdict_message_names_value_and_vocabulary(monkeypatch: pytest.MonkeyPatch) -> None:
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError) as exc_info:
        cosign.cosign(build_cfg(), _READER, 1, "not-a-real-verdict", "self-review", "a basis")
    message = str(exc_info.value)
    assert "not-a-real-verdict" in message
    for value in VERDICTS:
        assert value in message


def test_bad_independence_message_names_value_and_vocabulary(monkeypatch: pytest.MonkeyPatch) -> None:
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError) as exc_info:
        cosign.cosign(build_cfg(), _READER, 1, "attest", "not-a-real-independence", "a basis")
    message = str(exc_info.value)
    assert "not-a-real-independence" in message
    for value in INDEPENDENCE_VALUES:
        assert value in message


# ---------------------------------------------------------------------------
# Ordering: verdict is checked before independence before basis (cosign.py's
# own source order) -- proven by making two checks fail at once and asserting
# WHICH error surfaces.
# ---------------------------------------------------------------------------

def test_order_verdict_checked_before_independence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verdict AND independence are both invalid, and basis is also empty -- only the verdict
    error (checked first in cosign.py) may surface."""
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError) as exc_info:
        cosign.cosign(build_cfg(), _READER, 1, "not-a-real-verdict", "not-a-real-independence", "")
    assert str(exc_info.value).startswith("verdict must be one of")


def test_order_independence_checked_before_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verdict is valid, but independence is invalid AND basis is empty -- only the independence
    error (checked second) may surface, never the basis error."""
    trap_run_led(monkeypatch)
    with pytest.raises(cosign.CosignValidationError) as exc_info:
        cosign.cosign(build_cfg(), _READER, 1, "attest", "not-a-real-independence", "")
    assert str(exc_info.value).startswith("independence must be one of")


# ---------------------------------------------------------------------------
# GREEN-shaped negative control: valid input DOES reach _run_led, proving the
# AssertionError trap above is a meaningful signal, not a fixture that never
# fires.
# ---------------------------------------------------------------------------

def test_valid_input_reaches_run_led(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def _record(cfg: PanelConfig, args: list[str], actor: str | None) -> cosign.LedResult:
        calls.append((args, actor))
        return cosign.LedResult(ok=False, exit_code=1, stdout="", stderr="stub: never actually run")

    monkeypatch.setattr(cosign, "_run_led", _record)

    result = cosign.cosign(build_cfg(), _READER, 42, "attest", "self-review", "a genuine review basis")

    assert len(calls) == 1
    args, actor = calls[0]
    assert args == ["review", "42", "attest", "self-review", "a genuine review basis"]
    assert actor == "maintainer"
    # the stub's ok=False means cosign() must short-circuit before the ok-branch's
    # reader-typed latest_review_id call -- this test stays DB-free too.
    assert result.ok is False
    assert result.review_id is None
