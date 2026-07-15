"""backend.core.profiles_write -- write-capable profile management (SPEC row:142, ledger row
row:143's work item). Core (not extensions/autoharn/), per SPEC.md sec 4's extension boundary:
profiles are generic to this app's own config, not autoharn-specific.

`backend/config.py` READS panel.toml's `[profiles.<name>]` tables via stdlib `tomllib`
(read-only -- `tomllib` has no writer). This module is the WRITE path, using the `tomlkit`
library instead: `tomlkit` preserves comments/formatting/other-tables on a read-modify-write
round trip, which matters here because a hand-maintained panel.toml commonly also carries a
`[ledger]` table (and possibly other tables/comments) that a write must leave byte-for-byte
untouched apart from the `[profiles]` table itself.

Every write (`upsert_profile`, `delete_profile`) follows the same shape: read the whole
document with `tomlkit.parse` (or start a fresh empty `tomlkit.document()` if the file doesn't
exist yet), mutate ONLY the `[profiles]` table, then write back ATOMICALLY -- to a temp file in
the same directory, then `os.replace` -- so a crash mid-write never leaves a partial/truncated
panel.toml on disk.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

REQUIRED_FIELDS = ("host", "db", "schema", "kern")
OPTIONAL_FIELDS = ("role",)


class ProfileValidationError(ValueError):
    """Raised when a profile name or its fields fail validation -- the caller (routes.py) turns
    this into an HTTP 400, never a 500."""


def _panel_toml_path(repo_root: Path) -> Path:
    """Mirrors `config._panel_toml_path` exactly (same env override, same default) -- this
    module does not import `config.py` to avoid a write-module depending on the read module's
    internals, but the path-resolution RULE must stay identical or a write here could silently
    target a different file than the one `load_config` reads at startup."""
    path_str = os.environ.get("PANEL_CONFIG_FILE")
    return Path(path_str) if path_str else (repo_root / "panel.toml")


def _load_document(path: Path) -> tomlkit.TOMLDocument:
    if not path.is_file():
        return tomlkit.document()
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except ParseError as e:
        raise ProfileValidationError(
            f"{path} exists but does not parse as TOML ({e.__class__.__name__}: {e}) -- "
            f"fix it before writing profiles."
        ) from e


def _write_document_atomically(path: Path, doc: tomlkit.TOMLDocument) -> None:
    """Write `doc` to `path` atomically: a temp file in the SAME directory (so `os.replace` is
    guaranteed to be an atomic rename on the same filesystem, never a cross-device copy), then
    `os.replace` over the target -- never a partial/interrupted write left behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ProfileValidationError("profile name must be a non-empty string")
    # Safe as a bare TOML key (dotted-key/quoting concerns never arise): restrict to the
    # characters a bare TOML key already allows unquoted (letters, digits, '-', '_'), so the
    # written-back document never needs quoted-key escaping and stays trivially re-parseable.
    if not all(c.isalnum() or c in "-_" for c in name):
        raise ProfileValidationError(
            f"profile name {name!r} must contain only letters, digits, '-' or '_' "
            f"(so it is safe as a bare TOML key)"
        )
    return name


def _validate_fields(fields: dict[str, Any]) -> dict[str, str]:
    validated: dict[str, str] = {}
    missing = [k for k in REQUIRED_FIELDS if not fields.get(k) or not isinstance(fields.get(k), str)]
    if missing:
        raise ProfileValidationError(
            f"missing or empty/non-string value for: {', '.join(missing)} "
            f"(needs all of {REQUIRED_FIELDS})"
        )
    for k in REQUIRED_FIELDS:
        validated[k] = fields[k]
    role = fields.get("role")
    if role is not None:
        if not isinstance(role, str) or not role.strip():
            raise ProfileValidationError("role must be a non-empty string if present")
        validated["role"] = role
    return validated


def list_profiles(repo_root: Path) -> list[dict[str, Any]]:
    """Returns every declared profile (name + host/db/schema/kern/role) from panel.toml, in
    sorted-by-name order -- the read-only view GET /api/profiles serves, and the same shape
    `config.py`'s own `_profiles_table` reads from (this function re-parses the same file via
    tomlkit rather than importing `config.py`, since tomlkit's parse result is a strict superset
    of what tomllib returns -- plain dict-like access works identically for reading)."""
    path = _panel_toml_path(repo_root)
    doc = _load_document(path)
    profiles = doc.get("profiles", {})
    out: list[dict[str, Any]] = []
    for name in sorted(profiles):
        sub = profiles[name]
        out.append({
            "name": name,
            "host": sub.get("host"),
            "db": sub.get("db"),
            "schema": sub.get("schema"),
            "kern": sub.get("kern"),
            "role": sub.get("role"),
        })
    return out


def upsert_profile(repo_root: Path, name: str, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Create or overwrite the named profile. Validates `name` (non-empty, safe as a bare TOML
    key) and `fields` (host/db/schema/kern all non-empty strings, role optional) BEFORE touching
    the file. Mutates ONLY the `[profiles]` table -- `[ledger]` and any other table/comment in
    the document is left untouched. Returns the full updated profile list (same shape as
    `list_profiles`)."""
    valid_name = _validate_name(name)
    valid_fields = _validate_fields(fields)

    path = _panel_toml_path(repo_root)
    doc = _load_document(path)
    if "profiles" not in doc:
        doc["profiles"] = tomlkit.table(is_super_table=True)
    profiles = doc["profiles"]

    sub = tomlkit.table()
    for k in REQUIRED_FIELDS:
        sub[k] = valid_fields[k]
    if "role" in valid_fields:
        sub["role"] = valid_fields["role"]
    profiles[valid_name] = sub

    _write_document_atomically(path, doc)
    return list_profiles(repo_root)


def delete_profile(repo_root: Path, name: str) -> list[dict[str, Any]]:
    """Delete the named profile. Raises `KeyError` if it does not exist (the caller turns this
    into an HTTP 404). Mutates ONLY the `[profiles]` table."""
    path = _panel_toml_path(repo_root)
    doc = _load_document(path)
    profiles = doc.get("profiles", {})
    if name not in profiles:
        raise KeyError(name)
    del profiles[name]
    _write_document_atomically(path, doc)
    return list_profiles(repo_root)
