// src/extensions/autoharn/utils/obligationTreeLayout.ts -- hand-rolled layered-DAG layout for
// the obligation tree (obligation-tree-view, row:846 acceptance criteria; row:909's decision:
// "a reasonably simple hand-rolled layered layout is fine and explicitly sanctioned by this
// item's own scope -- no need for a heavy graph library"). Pure, framework-free geometry: given
// the recursive `ObligationNode` tree `GET /api/obligation-tree/{slug}` returns, computes one
// {x, y} pixel position per node INSTANCE (a DAG diamond renders as more than one instance of
// the same slug, per that endpoint's own doc comment -- each instance gets its own position and
// its own synthetic numeric id, assigned per visit, never slug-keyed) plus the parent->child
// edge list the SVG renderer draws connecting lines along.
//
// Algorithm -- a classic, simplified tree layout (no contour/Reingold-Tilford collision
// handling, which this item's scope does not require at the stated 500-node target): a
// post-order walk assigns each LEAF the next available integer column in left-to-right
// visitation order; each INTERNAL node's column is the midpoint of its own children's MIN/MAX
// column (so a parent centers over the full span of its subtree, not skewed by an unbalanced
// child count). Depth (root = 0) is the row/layer index. O(n) total time and node count, well
// within the 500-node scale target -- no per-node work depends on tree size elsewhere in the
// tree.
import type { ObligationNode } from '../services/types'

export const NODE_WIDTH = 176
export const NODE_HEIGHT = 46
const COLUMN_GAP = 24
const ROW_GAP = 68
// Half a node's own footprint -- left/top canvas padding so a node's stroke/hover outline is
// never clipped by the SVG's own edge at column/row 0.
const PAD = 12

export interface LayoutNode {
  /** Synthetic per-instance id (NOT the slug -- a DAG diamond can visit the same slug more than
   * once; each visit is its own row/column/hover/click target, per the backend's own doc on
   * `obligation_tree()`). */
  id: number
  node: ObligationNode
  depth: number
  x: number // pixel, left edge
  y: number // pixel, top edge
}

export interface LayoutEdge {
  from: LayoutNode
  to: LayoutNode
}

export interface ObligationTreeLayout {
  nodes: LayoutNode[]
  edges: LayoutEdge[]
  width: number
  height: number
}

export function layoutObligationTree(root: ObligationNode): ObligationTreeLayout {
  const nodes: LayoutNode[] = []
  const byId = new Map<number, LayoutNode>()
  const parentOf = new Map<number, number>()
  let nextId = 0
  let nextColumn = 0

  function visit(node: ObligationNode, depth: number): { id: number; column: number } {
    const id = nextId++
    const childColumns: number[] = []
    for (const child of node.children) {
      const result = visit(child, depth + 1)
      parentOf.set(result.id, id)
      childColumns.push(result.column)
    }
    const column =
      childColumns.length > 0
        ? (Math.min(...childColumns) + Math.max(...childColumns)) / 2
        : nextColumn++
    const x = PAD + column * (NODE_WIDTH + COLUMN_GAP)
    const y = PAD + depth * (NODE_HEIGHT + ROW_GAP)
    const layoutNode: LayoutNode = { id, node, depth, x, y }
    nodes.push(layoutNode)
    byId.set(id, layoutNode)
    return { id, column }
  }

  visit(root, 0)

  const edges: LayoutEdge[] = []
  for (const [childId, parentId] of parentOf) {
    const from = byId.get(parentId)
    const to = byId.get(childId)
    if (from && to) edges.push({ from, to })
  }

  const maxX = nodes.reduce((m, n) => Math.max(m, n.x + NODE_WIDTH), 0)
  const maxY = nodes.reduce((m, n) => Math.max(m, n.y + NODE_HEIGHT), 0)

  return { nodes, edges, width: maxX + PAD, height: maxY + PAD }
}
