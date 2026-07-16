// src/core/glossary.ts -- lightweight, extensible lookup for internal-vocabulary tokens that
// show up verbatim in rendered ledger statement text (kernel-generation ids like `s28`, ADR
// numbers like `ADR-0005`, work-item slugs, ledger kind names). Consult's vocabulary-leak
// finding: a reader with no ledger-archaeology context hits these tokens with nothing to tell
// them what they mean. This is deliberately a SHORT, hand-maintained starter list, not an
// exhaustive vocabulary -- it ships something real and extensible rather than nothing, per
// this item's own spec. Add an entry here whenever a new recurring token proves worth glossing;
// nothing about the shape below caps the list's size.
//
// Consumed by CitationText.vue, which already owns the ONE text-scanning pass over rendered
// statement strings (splitting on `row:<id>` citations) -- this module only supplies the
// pattern/gloss table and the match function; CitationText does the actual segment-splitting so
// there is exactly one scan over each statement, not a second parallel one.

export interface GlossaryTerm {
  /** Human label for the matched token, e.g. "s28" or "ADR-0005". */
  label: string
  /** One-line gloss shown as the hover title. */
  gloss: string
}

interface GlossaryEntry {
  pattern: RegExp
  gloss: (label: string) => string
}

// Order matters only in that the first matching entry wins for a given substring; patterns here
// don't overlap in practice (kernel-gen ids are `sNN`, ADR refs are `ADR-NNN`).
const GLOSSARY_ENTRIES: GlossaryEntry[] = [
  {
    // Kernel-generation identifiers, e.g. s25, s28, s31 -- two-digit generation number.
    pattern: /\bs(\d{2})\b/g,
    gloss: (label) => `${label}: kernel schema-generation identifier (lineage/${label}-*.sql).`,
  },
  {
    // ADR-<number>, e.g. ADR-0005, ADR-17.
    pattern: /\bADR-0*(\d+)\b/g,
    gloss: (label) => `${label}: an Architecture Decision Record under law/adr/.`,
  },
]

/** One glossary match found in a piece of text, with its position for splitting. */
export interface GlossaryMatch {
  index: number
  length: number
  label: string
  gloss: string
}

/**
 * Find all glossary-term matches in `text`, left to right, non-overlapping. Later entries never
 * re-match a span already claimed by an earlier one.
 */
export function findGlossaryMatches(text: string): GlossaryMatch[] {
  const matches: GlossaryMatch[] = []
  const claimed: Array<[number, number]> = []

  function overlapsClaimed(start: number, end: number): boolean {
    return claimed.some(([s, e]) => start < e && end > s)
  }

  for (const entry of GLOSSARY_ENTRIES) {
    // Fresh regex per call (entries hold a shared `g`-flagged RegExp; matchAll needs its own
    // lastIndex bookkeeping, and re-running matchAll on the same RegExp object across calls
    // would be safe too since matchAll doesn't mutate lastIndex of the source, but a local copy
    // keeps this function obviously side-effect-free on the module-level table).
    const re = new RegExp(entry.pattern.source, entry.pattern.flags)
    for (const m of text.matchAll(re)) {
      const idx = m.index ?? 0
      const label = m[0]
      if (overlapsClaimed(idx, idx + label.length)) continue
      claimed.push([idx, idx + label.length])
      matches.push({ index: idx, length: label.length, label, gloss: entry.gloss(label) })
    }
  }

  matches.sort((a, b) => a.index - b.index)
  return matches
}
