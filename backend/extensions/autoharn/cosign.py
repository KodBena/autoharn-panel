"""extensions.autoharn.cosign -- the ONLY write path this panel has: a subprocess wrapper
around the configured `LED_BIN` (SPEC.md sec 1: absent LED_BIN means read-only, enforced by
`routes.py` refusing to even register this write route when `cfg.read_only`).

No parallel write path is ever authored here: every mutation goes through `<LED_BIN> review`
(co-sign) or `<LED_BIN> register-principal` (startup, idempotent). A kernel refusal is surfaced
VERBATIM (stdout/stderr, exit code) -- this module never interprets a non-zero exit as success,
never retries past a refusal, and never fabricates a `review_id` when the subprocess failed.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from config import PanelConfig
from extensions.autoharn.ports import INDEPENDENCE_VALUES, VERDICTS, AutoharnLedgerPort


class CosignValidationError(Exception):
    """A co-sign request named a verdict/independence value outside the kernel's own closed
    vocabulary -- a 400 naming the allowed values, BEFORE shelling out."""


@dataclass(frozen=True)
class LedResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CosignResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    review_id: int | None


def _run_led(cfg: PanelConfig, args: list[str], actor: str | None) -> LedResult:
    if cfg.led_bin is None or cfg.read_only:
        # cfg.read_only checked directly (not just led_bin is None) so this guard also trips
        # under PANEL_READONLY's lock, where led_bin CAN be a real, resolved path -- see
        # ledger row:70 and the row:58 decision recorded alongside it: app.py's outer route-
        # mount gate (`if not cfg.read_only`) already makes this unreachable in that state, so
        # this inner check was already safe either way, but checking cfg.read_only here too
        # keeps this guard's own message honest instead of silently relying on an assumption
        # about the caller that a future second caller could violate.
        raise RuntimeError(
            "cosign._run_led called while cfg.read_only is True (led_bin="
            f"{cfg.led_bin!r}, read_only_reason={cfg.read_only_reason!r}) -- this is a caller "
            "bug: routes.py must refuse to register any write route at all when cfg.read_only "
            "is True."
        )
    env: dict[str, str] = {}
    env.update(os.environ)
    if actor:
        env["LED_ACTOR"] = actor
    proc = subprocess.run(
        [str(cfg.led_bin), *args],
        cwd=str(cfg.repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return LedResult(ok=proc.returncode == 0, exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def ensure_principal_registered(cfg: PanelConfig, name: str, agent_class: str) -> LedResult:
    return _run_led(cfg, ["register-principal", name, agent_class], actor=None)


def cosign(
    cfg: PanelConfig, reader: AutoharnLedgerPort, row_id: int, verdict: str, independence: str, basis: str,
) -> CosignResult:
    if verdict not in VERDICTS:
        raise CosignValidationError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    if independence not in INDEPENDENCE_VALUES:
        raise CosignValidationError(f"independence must be one of {INDEPENDENCE_VALUES}, got {independence!r}")
    if not basis or not basis.strip():
        raise CosignValidationError("basis (the review statement) must be a non-empty string")

    result = _run_led(cfg, ["review", str(row_id), verdict, independence, basis], actor=cfg.maintainer_principal)
    review_id: int | None = None
    if result.ok:
        review_id = reader.latest_review_id(cfg, regards=row_id, actor_name=cfg.maintainer_principal)
    return CosignResult(
        ok=result.ok,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        review_id=review_id,
    )
