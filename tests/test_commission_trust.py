"""tests/test_commission_trust.py -- real test coverage for `commission_trust()`'s
signed/forged/unverifiable branches (backend/extensions/autoharn/ledger_read.py, added by
a389445 as part of spa-audit-cycle-4-fixes), closing the gap row:745's compliance review
found and row:747 countersigned: "no .claude/commission-*.asc banked anywhere in the repo
(asc_path.exists() is always False), and no test file mocks subprocess.run against
commission_trust's signed/forged/unverifiable branches." Filed as work item
commission-trust-branch-tests.

`commission_trust()` only ever exercises the trivial LAZY/FULL fast path (zero subprocess
calls) UNLESS a `.claude/commission-<id>.asc` file is banked for the row -- which no commission
in this deployment has. This module gives each of the other branches (subprocess.run's stdout
parsed into VERIFIED/FORGED-OR-CORRUPT/a refusal/an unrecognized shape, plus the subprocess
invocation itself raising) a real, committed test, by monkeypatching `subprocess.run` to return
controlled fake `./verify-commission --id <id> --json` output -- the exact mechanism finding
745's own text recommends ("a unit test with a monkeypatched subprocess.run") rather than
standing up a real GPG keyring + signed statement end-to-end (heavier, environment-dependent,
and duplicative of verify-commission's OWN test surface, which is autoharn's concern, not this
repo's -- this repo's concern is only that `commission_trust` calls out correctly and maps every
documented verdict/refusal shape to the right trust_level/trust_detail). Pure Python, no
database, no live subprocess -- mirrors tests/test_profiles_write.py's "Layer 1" pattern
(tmp_path as a scratch repo_root, monkeypatch for the one external dependency) rather than
tests/test_commission_decomposition.py's live-Postgres pattern, since nothing here touches the
ledger DB at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from config import ConnectionFacts, PanelConfig  # noqa: E402
from extensions.autoharn import ledger_read  # noqa: E402


def build_cfg(repo_root: Path) -> PanelConfig:
    """A minimal PanelConfig whose only field commission_trust() actually reads is repo_root
    (it locates .claude/commission-<id>.asc and the verify-commission binary off it) -- the rest
    are placeholder values in the same shape test_commission_decomposition.py's build_cfg()
    uses, since PanelConfig is a frozen dataclass and every field is required."""
    connection = ConnectionFacts(pg_uri=None, pg_host="127.0.0.1", pg_port=None, pg_db="toy",
                                  pg_user=None, pg_password=None, source="test-scratch")
    return PanelConfig(
        repo_root=repo_root, connection=connection, schema="s", kern_schema="k", role=None,
        led_bin=None, read_only_locked=True, bind_host="127.0.0.1", bind_port=8421,
        poll_interval=2.0, extensions=("autoharn",), config_source="test-scratch",
        maintainer_principal="maintainer", active_profile=None, available_profiles=(),
    )


def bank_asc(repo_root: Path, row_id: int) -> None:
    """Creates the one file commission_trust() actually checks for (asc_path.exists()) -- its
    contents are never read by commission_trust itself (only by the real verify-commission
    binary, which these tests never invoke), so a placeholder body is enough."""
    claude_dir = repo_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / f"commission-{row_id}.asc").write_text(
        "-----BEGIN PGP SIGNATURE-----\nfake, never parsed by commission_trust itself\n"
        "-----END PGP SIGNATURE-----\n",
        encoding="utf-8",
    )


class FakeCompletedProcess:
    """Just enough of subprocess.CompletedProcess's shape for commission_trust's own read of
    it (proc.stdout, parsed as JSON if non-blank)."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def patch_subprocess_run(monkeypatch: pytest.MonkeyPatch, *, payload: dict[str, Any] | None = None,
                          raises: Exception | None = None, expected_row_id: int | None = None,
                          expected_verify_bin: Path | None = None) -> list[list[str]]:
    """Replaces subprocess.run (the SAME module object ledger_read imported at its own top level,
    so patching it here reaches commission_trust's call site) with a fake that either raises
    `raises` or returns a FakeCompletedProcess whose stdout is `json.dumps(payload)`. Returns the
    list of calls made (each call's argv), so a test can also assert the invocation shape
    (verify-commission --id <row_id> --json) commission_trust's own docstring promises, not only
    the return-value mapping."""
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if expected_row_id is not None:
            assert args == [str(expected_verify_bin), "--id", str(expected_row_id), "--json"]
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        assert "timeout" in kwargs
        if raises is not None:
            raise raises
        return FakeCompletedProcess(json.dumps(payload) if payload is not None else "")

    monkeypatch.setattr(ledger_read.subprocess, "run", fake_run)
    return calls


# ---------------------------------------------------------------------------
# Fast path: no banked .asc -> zero subprocess calls (regression guard for the
# claim commission_trust's own docstring makes: "costs zero subprocess calls").
# ---------------------------------------------------------------------------

def test_no_banked_asc_never_shells_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_a, **_kw):
        raise AssertionError("subprocess.run must not be called when no .asc is banked")

    monkeypatch.setattr(ledger_read.subprocess, "run", explode)
    cfg = build_cfg(tmp_path)
    result = ledger_read.commission_trust(cfg, 1, "someone", "abc123", "did the thing")
    assert result == {"trust_level": "lazy", "trust_detail": None}


# ---------------------------------------------------------------------------
# Signed branch: verify-commission returns verdict=VERIFIED.
# ---------------------------------------------------------------------------

def test_banked_asc_verified_maps_to_signed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row_id = 42
    bank_asc(tmp_path, row_id)
    cfg = build_cfg(tmp_path)
    calls = patch_subprocess_run(
        monkeypatch,
        payload={"id": row_id, "actor": "commissioner", "signing_mode": "FULL",
                  "verdict": "VERIFIED", "detail": "statement sha256=abc. Good signature"},
        expected_row_id=row_id, expected_verify_bin=cfg.repo_root / "verify-commission",
    )

    result = ledger_read.commission_trust(cfg, row_id, "commissioner", None, "signed commission text")

    assert result == {"trust_level": "signed", "trust_detail": "statement sha256=abc. Good signature"}
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Forged branch: verify-commission returns verdict=FORGED-OR-CORRUPT.
# ---------------------------------------------------------------------------

def test_banked_asc_forged_or_corrupt_maps_to_forged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row_id = 43
    bank_asc(tmp_path, row_id)
    cfg = build_cfg(tmp_path)
    patch_subprocess_run(
        monkeypatch,
        payload={"id": row_id, "actor": "commissioner", "signing_mode": "FULL",
                  "verdict": "FORGED-OR-CORRUPT", "detail": "statement sha256=abc. BAD signature"},
        expected_row_id=row_id, expected_verify_bin=cfg.repo_root / "verify-commission",
    )

    result = ledger_read.commission_trust(cfg, row_id, "commissioner", None, "tampered commission text")

    assert result == {"trust_level": "forged", "trust_detail": "statement sha256=abc. BAD signature"}


# ---------------------------------------------------------------------------
# Unverifiable branch, case 1: verify-commission's two typed REFUSALS
# (NO-COMMITTED-KEY / GPG-UNAVAILABLE), surfaced as payload["refusal"].
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("refusal", ["NO-COMMITTED-KEY", "GPG-UNAVAILABLE"])
def test_banked_asc_refusal_maps_to_unverifiable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str) -> None:
    row_id = 44
    bank_asc(tmp_path, row_id)
    cfg = build_cfg(tmp_path)
    patch_subprocess_run(
        monkeypatch,
        payload={"id": row_id, "actor": "commissioner", "signing_mode": "FULL",
                  "refusal": refusal, "detail": f"{refusal} detail text"},
        expected_row_id=row_id, expected_verify_bin=cfg.repo_root / "verify-commission",
    )

    result = ledger_read.commission_trust(cfg, row_id, "commissioner", None, "commission text")

    assert result == {"trust_level": "unverifiable", "trust_detail": f"{refusal} detail text"}


# ---------------------------------------------------------------------------
# Unverifiable branch, case 2: the subprocess invocation itself fails (binary
# missing, timeout, non-JSON stdout, etc.) -- the `except Exception` path.
# ---------------------------------------------------------------------------

def test_subprocess_invocation_failure_maps_to_unverifiable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row_id = 45
    bank_asc(tmp_path, row_id)
    cfg = build_cfg(tmp_path)
    patch_subprocess_run(monkeypatch, raises=FileNotFoundError("verify-commission binary not found"))

    result = ledger_read.commission_trust(cfg, row_id, "commissioner", None, "commission text")

    assert result["trust_level"] == "unverifiable"
    assert "verify-commission invocation failed" in result["trust_detail"]
    assert "verify-commission binary not found" in result["trust_detail"]


def test_subprocess_non_json_stdout_maps_to_unverifiable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed/non-JSON stdout is a different failure shape than a raised exception (json.loads
    itself raises inside the try/except commission_trust wraps around the whole subprocess call),
    but must land in the same honest 'can't tell' tier, never crash the caller."""
    row_id = 46
    bank_asc(tmp_path, row_id)
    cfg = build_cfg(tmp_path)

    def fake_run(args, **kwargs):
        return FakeCompletedProcess("not valid json {{{")

    monkeypatch.setattr(ledger_read.subprocess, "run", fake_run)

    result = ledger_read.commission_trust(cfg, row_id, "commissioner", None, "commission text")

    assert result["trust_level"] == "unverifiable"
    assert "verify-commission invocation failed" in result["trust_detail"]


# ---------------------------------------------------------------------------
# Defensive fallback: a well-formed JSON payload whose verdict/refusal string
# this backend does not recognize (a future verify-commission addition) must
# degrade to the ledger-only signing-mode signal, never guess a trust_level.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "actor_name,stamp_agent,expected_mode",
    [("commissioner", None, "full"), ("someone-else", "stamp-abc", "lazy")],
)
def test_unrecognized_verdict_falls_back_to_signing_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, actor_name: str, stamp_agent: str | None,
    expected_mode: str,
) -> None:
    row_id = 47
    bank_asc(tmp_path, row_id)
    cfg = build_cfg(tmp_path)
    patch_subprocess_run(
        monkeypatch,
        payload={"id": row_id, "actor": actor_name, "verdict": "SOME-FUTURE-VERDICT",
                  "detail": "unrecognized shape"},
    )

    result = ledger_read.commission_trust(cfg, row_id, actor_name, stamp_agent, "commission text")

    assert result == {"trust_level": expected_mode, "trust_detail": "unrecognized shape"}
