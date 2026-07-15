-- scratch/core-bare-schema.sql -- the minimal, ledger-generic schema `backend/core/` requires
-- (SPEC.md sec 4's extension boundary test). This is NOT autoharn's kernel lineage (which this
-- standalone repo does not depend on or ship) -- it is the smallest possible schema
-- `backend/core/ledger_read.py` itself needs: a `ledger` table with
-- (id, ts, kind, statement, refs, supersedes, actor) and a `principal(id, name)` table for
-- actor names, no CHECK constraint narrowing `kind` (core imposes no kind vocabulary of its
-- own -- SPEC.md sec 0 "derive, don't duplicate"), no distinct subject role required (`SET
-- ROLE` is skipped by `db.py` when `LEDGER_ROLE` is unset).
--
-- Used by tests/test_core_boundary.py to prove the core API serves against exactly this,
-- nothing more, with the `autoharn` extension disabled.
--
-- Usage: psql -h <host> -d <db> -v schema=<schema> -v kern=<kern> -f scratch/core-bare-schema.sql

\if :{?schema}
\else
  \set schema pcorebndry
\endif
\if :{?kern}
\else
  \set kern pcorebndry_kernel
\endif

CREATE SCHEMA IF NOT EXISTS :"kern";
CREATE SCHEMA IF NOT EXISTS :"schema";

CREATE TABLE IF NOT EXISTS :"kern".principal (
    id   bigserial PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS :"schema".ledger (
    id         bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    kind       text NOT NULL,
    statement  text NOT NULL,
    refs       text,
    supersedes bigint REFERENCES :"schema".ledger(id),
    actor      bigint REFERENCES :"kern".principal(id)
);
