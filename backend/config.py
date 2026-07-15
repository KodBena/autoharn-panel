"""backend.config -- the ONE place this standalone SPA resolves where its ledger lives and how
it is configured (SPEC.md sec 1).

This module replaces autoharn's `filing/pghost_resolve.py` + `filing/deployment_record.py` for
this repo: the SPA is standalone (SPEC.md sec 4 "Repo layout" -- backend + frontend version
together, in their own repo), so it does not import autoharn's `filing/` package at all. The
autoharn `deployment.json` shape becomes ONE of three config sources this module recognizes
(the third, used only when this repo runs as autoharn's own submodule, e.g. under
`tools/panel/`) -- never the only source, and never imported as code from the autoharn tree
(this module re-parses that JSON shape itself, so a checkout of this repo alone, with no
autoharn checkout beside it, still has two working config sources).

Precedence (spec sec 1, "environment-first, file-fallback", documented here exactly):

  1. `LEDGER_PG_URI` -- a full libpq connection URI. Wins outright over every discrete field.
  2. Discrete fields -- `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` (the standard libpq
     env var names, so this also composes with an operator's existing psql environment).
  3. `panel.toml` (or the path named by `PANEL_CONFIG_FILE`) -- a `[ledger]` table with the same
     keys, lowercase (`pg_uri`, `pghost`, `pgport`, `pgdatabase`, `pguser`, `pgpassword`,
     `schema`, `kernel_schema`, `role`, `led_bin`, `bind`, `port`, `poll_interval`,
     `extensions`) -- read only for whichever of the above three keys env did not already
     supply, never silently overriding an env value that IS set.
  4. The autoharn `deployment.json` shape (`LEDGER_DEPLOYMENT` env, else
     `<repo_root>/deployment.json`, else `<repo_root>/../deployment.json` -- the second lets
     this module find autoharn's own record when this repo sits at `tools/panel/` inside an
     autoharn checkout) -- used ONLY if steps 1-3 resolved nothing at all for the connection
     facts. Supplies `db`/`host`/`schema`/`kern`/`role` together, as one unit (this module does
     not mix-and-match a `deployment.json`'s `host` with an env `PGDATABASE`, say -- a caller
     naming ANY discrete/URI connection fact opts fully out of the deployment.json source for
     the connection facts, though `LEDGER_SCHEMA`/`LEDGER_KERNEL_SCHEMA` may still independently
     override its `schema`/`kern` -- see `load_config`'s body for the exact rule).

Startup is fail-loud (spec sec 1's own words): unresolvable DB/config prints the exact missing
key and exits nonzero. No silent defaults to anybody's host -- there is no hardcoded host
anywhere in this module, unlike its autoharn-side predecessor's one-time 192.168.122.1 lesson,
which is the reason this project has this rule at all.

Lazy imports are banned (this project's engineering register, mirrored here on principle even
though this is a standalone repo): every import below executes at module load.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8420
DEFAULT_EXTENSIONS: tuple[str, ...] = ("autoharn",)


class ConfigError(SystemExit):
    """Raised (as a SystemExit subclass, so an uncaught instance exits the process with a
    nonzero code and this message, never a traceback-only failure) when startup cannot resolve
    a required config fact. Every message names the EXACT missing key and how to supply it --
    spec sec 1's fail-loud contract."""

    def __init__(self, message: str) -> None:
        super().__init__(f"REFUSED: {message}")


@dataclass(frozen=True)
class ConnectionFacts:
    """Where the ledger physically lives -- either a full URI, or enough discrete fields to
    build one. Exactly one of `pg_uri` / (`pg_host` present) is populated; `resolve()` below
    enforces that invariant before a `ConnectionFacts` is ever constructed."""
    pg_uri: str | None
    pg_host: str | None
    pg_port: str | None
    pg_db: str | None
    pg_user: str | None
    pg_password: str | None
    source: str  # "uri" | "discrete" | "autoharn-deployment.json"

    def conninfo(self) -> str:
        """A libpq conninfo string (or URI) suitable for `psycopg.connect(conninfo=...)`."""
        if self.pg_uri:
            return self.pg_uri
        parts: list[str] = []
        if self.pg_host:
            parts.append(f"host={self.pg_host}")
        if self.pg_port:
            parts.append(f"port={self.pg_port}")
        if self.pg_db:
            parts.append(f"dbname={self.pg_db}")
        if self.pg_user:
            parts.append(f"user={self.pg_user}")
        if self.pg_password:
            parts.append(f"password={self.pg_password}")
        return " ".join(parts)


@dataclass(frozen=True)
class PanelConfig:
    """Everything the backend needs to connect, poll, and (if `led_bin` is set) shell out --
    resolved ONCE at startup, threaded through every route/read/write rather than re-resolved
    per request."""
    repo_root: Path
    connection: ConnectionFacts
    schema: str
    kern_schema: str
    role: str | None          # None => no `SET ROLE` issued (a bare/self-owned schema)
    led_bin: Path | None       # None => read-only mode (spec sec 1)
    bind_host: str
    bind_port: int
    poll_interval: float
    extensions: tuple[str, ...]
    config_source: str         # human-readable summary of which source(s) resolved this config
    maintainer_principal: str  # extension-only concept (the identity a write-capable extension
                                # co-signs/writes as); core itself never reads this field.

    @property
    def read_only(self) -> bool:
        return self.led_bin is None

    def extension_enabled(self, name: str) -> bool:
        return name in self.extensions


def _read_toml_ledger_table(repo_root: Path) -> dict[str, Any]:
    path_str = os.environ.get("PANEL_CONFIG_FILE")
    path = Path(path_str) if path_str else (repo_root / "panel.toml")
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(
            f"{path} exists but does not parse as TOML ({e.__class__.__name__}: {e}) -- "
            f"fix it or remove it; this file is optional, but if present it must parse."
        ) from e
    table = data.get("ledger", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}'s [ledger] table must be a TOML table, got {type(table).__name__}")
    return table


def _load_autoharn_deployment_json(repo_root: Path) -> dict[str, str] | None:
    """Re-parse the autoharn `deployment.json` SHAPE directly (db/host/schema/kern/role, all
    non-empty strings) -- this function does NOT import anything from an autoharn checkout; it
    only knows the on-disk JSON shape, so this repo works standalone (no autoharn checkout
    required) while still reading autoharn's own record when this repo sits inside one (spec
    sec 4's "used when running as autoharn's submodule"). Returns None if no candidate path
    exists at all (not an error by itself -- the caller decides whether that is fatal, since
    this is only ONE of three config sources)."""
    candidates: list[Path] = []
    env_path = os.environ.get("LEDGER_DEPLOYMENT")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(repo_root / "deployment.json")
    candidates.append(repo_root.parent / "deployment.json")  # tools/panel/ inside an autoharn checkout
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(
            f"{path} exists but does not parse as a deployment record "
            f"({e.__class__.__name__}: {e}) -- fix it, or configure LEDGER_PG_URI/discrete "
            f"PG* fields instead."
        ) from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a JSON object, got {type(raw).__name__}")
    required = ("db", "host", "schema", "kern", "role")
    missing = [k for k in required if not raw.get(k) or not isinstance(raw.get(k), str)]
    if missing:
        raise ConfigError(
            f"{path} is missing or has an empty/non-string value for: {', '.join(missing)} "
            f"(needs all of {required})"
        )
    return {k: raw[k] for k in required}


def _resolve_connection(repo_root: Path, toml_table: dict[str, Any]) -> ConnectionFacts | None:
    """Steps 1-2 of the precedence (env), falling back to step 3 (panel.toml) per-key. Returns
    None (never raises) if nothing at all was named -- the caller then tries step 4
    (deployment.json) before giving up."""
    uri = os.environ.get("LEDGER_PG_URI") or toml_table.get("pg_uri")
    if uri:
        return ConnectionFacts(pg_uri=uri, pg_host=None, pg_port=None, pg_db=None,
                                pg_user=None, pg_password=None, source="uri")
    host = os.environ.get("PGHOST") or toml_table.get("pghost")
    port = os.environ.get("PGPORT") or toml_table.get("pgport")
    db = os.environ.get("PGDATABASE") or toml_table.get("pgdatabase")
    user = os.environ.get("PGUSER") or toml_table.get("pguser")
    password = os.environ.get("PGPASSWORD") or toml_table.get("pgpassword")
    if host or db:
        return ConnectionFacts(pg_uri=None, pg_host=host, pg_port=str(port) if port else None,
                                pg_db=db, pg_user=user, pg_password=password, source="discrete")
    return None


def load_config(repo_root: Path | None = None) -> PanelConfig:
    root = (repo_root or _REPO_ROOT).resolve()
    toml_table = _read_toml_ledger_table(root)

    connection = _resolve_connection(root, toml_table)
    schema = os.environ.get("LEDGER_SCHEMA") or toml_table.get("schema")
    kern_schema = os.environ.get("LEDGER_KERNEL_SCHEMA") or toml_table.get("kernel_schema")
    role = os.environ.get("LEDGER_ROLE") or toml_table.get("role")
    config_source_parts: list[str] = []

    if connection is not None:
        config_source_parts.append(f"connection={connection.source}")
    else:
        dep = _load_autoharn_deployment_json(root)
        if dep is None:
            raise ConfigError(
                "no ledger connection configured -- set LEDGER_PG_URI, or PGHOST (with "
                "PGDATABASE), or provide panel.toml's [ledger] pg_uri/pghost, or place an "
                "autoharn deployment.json at <repo_root>/deployment.json. Never defaulting to "
                "any host."
            )
        connection = ConnectionFacts(pg_uri=None, pg_host=dep["host"], pg_port=None,
                                      pg_db=dep["db"], pg_user=None, pg_password=None,
                                      source="autoharn-deployment.json")
        # LEDGER_SCHEMA/LEDGER_KERNEL_SCHEMA/LEDGER_ROLE may still independently override the
        # deployment record's own schema/kern/role (spec sec 1 lists them as their own knobs);
        # only fall back to the record's values for whichever of the three was not separately set.
        schema = schema or dep["schema"]
        kern_schema = kern_schema or dep["kern"]
        role = role or dep["role"]
        config_source_parts.append("connection=autoharn-deployment.json")

    if not schema:
        raise ConfigError(
            "LEDGER_SCHEMA is not set (and no deployment.json supplied one) -- name the ledger "
            "schema explicitly; this module never guesses one."
        )
    if not kern_schema:
        raise ConfigError(
            "LEDGER_KERNEL_SCHEMA is not set (and no deployment.json supplied one) -- name the "
            "kernel/principal schema explicitly; this module never guesses one."
        )

    led_bin_str = os.environ.get("LED_BIN") or toml_table.get("led_bin")
    led_bin = Path(led_bin_str) if led_bin_str else None

    bind_host = os.environ.get("PANEL_BIND") or toml_table.get("bind") or DEFAULT_BIND_HOST
    bind_port = int(os.environ.get("PANEL_PORT") or toml_table.get("port") or DEFAULT_BIND_PORT)
    poll_interval = float(
        os.environ.get("PANEL_POLL_INTERVAL") or toml_table.get("poll_interval")
        or DEFAULT_POLL_INTERVAL_SECONDS
    )
    ext_raw = os.environ.get("PANEL_EXTENSIONS")
    if ext_raw is None:
        ext_raw = toml_table.get("extensions")
    if ext_raw is None:
        extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    elif isinstance(ext_raw, str):
        extensions = tuple(x.strip() for x in ext_raw.split(",") if x.strip())
    else:
        extensions = tuple(ext_raw)

    maintainer_principal = os.environ.get("PANEL_MAINTAINER_PRINCIPAL") or toml_table.get(
        "maintainer_principal"
    ) or "maintainer"

    config_source_parts.append(f"schema={schema}/{kern_schema}")
    config_source_parts.append("read_only" if led_bin is None else f"led_bin={led_bin}")

    return PanelConfig(
        repo_root=root,
        connection=connection,
        schema=schema,
        kern_schema=kern_schema,
        role=role,
        led_bin=led_bin,
        bind_host=bind_host,
        bind_port=bind_port,
        poll_interval=poll_interval,
        extensions=extensions,
        config_source=", ".join(config_source_parts),
        maintainer_principal=maintainer_principal,
    )
