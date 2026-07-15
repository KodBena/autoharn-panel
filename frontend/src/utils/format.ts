// src/utils/format.ts -- tiny formatting helpers shared across tabs. `truncate` is used ONLY
// for the commission `<select>` picker's option label (a navigation aid, not load-bearing
// content -- SPEC.md sec 0 permits ellipsis on "genuinely decorative columns" only); every
// other place a statement/refusal/witness text is rendered, the full string is used, wrapped.
export function fmtTs(ts: string | null | undefined): string {
  if (!ts) return ''
  return String(ts).replace('T', ' ').replace(/\.\d+Z?$/, '').replace('Z', '')
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
