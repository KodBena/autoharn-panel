#!/usr/bin/env node
// frontend/scripts/lint-boundaries.mjs -- deny-by-default import-boundary lint, wired into
// `npm run build` (package.json) so a boundary violation fails the build rather than sitting as
// an unenforced convention (omega structural-reap sheet's adopt verdicts: "directory-structural
// seams over enumerated exceptions", "deny-by-default import boundary with a mechanical lint",
// "wire shapes confined to the ACL/services layer with a lint", "every repo rule names its
// enforcement register" -- this file IS that register for the rules below).
//
// Two independent rules, both fail-loud (nonzero exit, one line per violation naming the file,
// the import, and the rule broken -- no silent pass-through):
//
// RULE 1 -- layer order (bottom to top: services < state < composables < components). A file's
// own layer is the deepest of these four directory-name literals appearing in its path; files
// outside all four (App.vue, main.ts, utils/*, tokens/*) are the top "app" layer and may import
// anything. An importer may import a dependency whose layer rank is <= its own -- an upward
// import (state importing composables, services importing state, composables importing
// components, etc.) is denied. Same-layer imports are allowed.
//
// RULE 2 -- extension boundary (SPEC.md sec 4): nothing under `src/core/` may import anything
// under `src/extensions/` (core must build against a bare ledger schema with every extension
// disabled -- it cannot depend on autoharn-semantic code to do so).
//
// RULE 3 -- wire-shape confinement: only a file under a `services/` directory may import the
// generated schema (`./schema`, `.../schema`) or the `openapi-fetch` package. Everything else
// gets wire types by importing the hand-authored `types.ts` (also inside `services/`, so
// already legal under this rule) or by calling through the one client alias
// (`core/services/api-client.ts`'s `api` export).
//
// Implementation note: this is a regex-based import scan, not a full TS/ESM resolver -- correct
// for this codebase's import style (relative imports, no barrel re-exports, no dynamic
// `import()`), and cheap enough to run with zero dependencies on every build. If the codebase
// ever grows barrel files or path aliases, this script's import extraction is the first thing
// to revisit.

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, extname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(__dirname, '..', 'src')

const LAYER_RANK = { services: 0, state: 1, composables: 2, components: 3 }
const LAYER_NAMES = Object.keys(LAYER_RANK)

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const st = statSync(full)
    if (st.isDirectory()) walk(full, out)
    else if (['.ts', '.vue'].includes(extname(entry))) out.push(full)
  }
  return out
}

function layerOf(path) {
  const parts = relative(SRC, path).split('/')
  for (const seg of parts) {
    if (seg in LAYER_RANK) return seg
  }
  return 'app'
}

function rankOf(layer) {
  return layer === 'app' ? Infinity : LAYER_RANK[layer]
}

function isUnderCore(path) {
  return relative(SRC, path).split('/')[0] === 'core'
}

function isUnderExtensions(path) {
  return relative(SRC, path).split('/')[0] === 'extensions'
}

// Pull import specifiers out of a .ts or .vue file's <script> block. Handles
// `import ... from '...'`, `import type ... from '...'`, and side-effect `import '...'`.
function extractImports(text) {
  const specifiers = []
  const re = /import\s+(?:type\s+)?(?:[\s\S]*?from\s+)?['"]([^'"]+)['"]/g
  let m
  while ((m = re.exec(text)) !== null) {
    specifiers.push({ spec: m[1], index: m.index })
  }
  return specifiers
}

function lineOf(text, index) {
  return text.slice(0, index).split('\n').length
}

function resolveRelative(fromFile, spec) {
  if (!spec.startsWith('.')) return null // bare package specifier (vue, openapi-fetch, ...)
  return resolve(dirname(fromFile), spec)
}

const files = walk(SRC)
const violations = []

for (const file of files) {
  const text = readFileSync(file, 'utf8')
  const importerLayer = layerOf(file)
  const importerRank = rankOf(importerLayer)
  const importerUnderCore = isUnderCore(file)

  for (const { spec, index } of extractImports(text)) {
    const line = lineOf(text, index)
    const relFile = relative(SRC, file)

    // RULE 3: wire-shape confinement. Bare-package check first (openapi-fetch), then relative
    // path check (anything resolving to a file literally named schema.d.ts / schema.ts).
    const importsGeneratedSchema =
      /(^|\/)schema(\.d)?$/.test(spec) || spec === 'openapi-fetch'
    if (importsGeneratedSchema && importerLayer !== 'services') {
      violations.push(
        `${relFile}:${line}: RULE 3 (wire-shape confinement) -- '${spec}' reaches the ` +
          `generated schema/client directly from outside a services/ directory (importer ` +
          `layer: ${importerLayer}). Import the hand-authored types from a services/types.ts ` +
          `or call through core/services/api-client.ts's 'api' export instead.`,
      )
    }

    const resolved = resolveRelative(file, spec)
    if (resolved === null) continue

    // RULE 2: extension boundary.
    if (importerUnderCore && isUnderExtensions(resolved)) {
      violations.push(
        `${relFile}:${line}: RULE 2 (extension boundary) -- src/core/ may not import from ` +
          `'${spec}' (resolves under src/extensions/). Core must build with every extension ` +
          `disabled (SPEC.md sec 4).`,
      )
    }

    // RULE 1: layer order. Only meaningful when BOTH sides are inside a recognized layer
    // (files at the "app" layer, e.g. App.vue, may import any layer; a recognized-layer file
    // importing an "app"-layer file, e.g. a shared util, is likewise unconstrained by this rule).
    const depLayer = layerOf(resolved)
    if (importerLayer !== 'app' && depLayer !== 'app') {
      const depRank = rankOf(depLayer)
      if (depRank > importerRank) {
        violations.push(
          `${relFile}:${line}: RULE 1 (layer order) -- '${importerLayer}' (rank ${importerRank}) ` +
            `may not import '${spec}' which resolves into '${depLayer}' (rank ${depRank}). ` +
            `Allowed order: services(0) <- state(1) <- composables(2) <- components(3).`,
        )
      }
    }
  }
}

if (violations.length > 0) {
  console.error(`lint-boundaries: ${violations.length} violation(s):\n`)
  for (const v of violations) console.error('  ' + v)
  console.error(`\nlint-boundaries: FAILED (${LAYER_NAMES.join(' < ')} order + extension boundary + wire-shape confinement).`)
  process.exit(1)
}

console.log(`lint-boundaries: OK -- ${files.length} files scanned, 0 violations.`)
