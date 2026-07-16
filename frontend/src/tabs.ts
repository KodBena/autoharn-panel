// src/tabs.ts -- the ONE source of truth for "what tabs exist" (work item
// tab-architecture-consolidation, row:748, countersigned finding row:745/747 #3/#4): before this
// file, the same information (tab id, its label, its component, its route path) was hand-
// maintained in 3 parallel spots inside App.vue (a `TabId` union, an `autoharnTabs`/`coreTabs`
// array, and a template `v-if` chain) plus router.ts's own separately hand-declared `TAB_PATHS`
// -- 4 spots really, each of the 3 tab-adding commits in spa-audit-cycle-4-fixes touched all of
// them. Adding, removing, or reordering a tab now means editing exactly ONE array, here.
//
// This is a top-level ("app" layer, per scripts/lint-boundaries.mjs's layer-order rule) file
// specifically because it is allowed to import BOTH core and extensions/autoharn components --
// same boundary-crossing role App.vue itself already has as the app's composition root. Neither
// `core/` nor `extensions/` may import this file back (that would invert the boundary); only
// App.vue and router.ts (both top-level, both already crossing this boundary) import it.
//
// router.ts imports this array too (for the `path`/`id` fields only, building its own route
// list) -- NOT so it can render the real components (it deliberately still doesn't; see its own
// header comment for why), but so a tab's path is declared in exactly one place rather than
// needing to stay hand-synced between here and a separate `TAB_PATHS` object.
import type { Component } from 'vue'
import LedgerTab from './core/components/LedgerTab.vue'
import ProfilesPanel from './core/components/ProfilesPanel.vue'
import BackendSurfaceTab from './core/components/BackendSurfaceTab.vue'
import CommissionTab from './extensions/autoharn/components/CommissionTab.vue'
import WorkItemsTab from './extensions/autoharn/components/WorkItemsTab.vue'
import ReviewGapTab from './extensions/autoharn/components/ReviewGapTab.vue'
import QuestionsTab from './extensions/autoharn/components/QuestionsTab.vue'
import WorkViolationsTab from './extensions/autoharn/components/WorkViolationsTab.vue'
import FindingsSnagsTab from './extensions/autoharn/components/FindingsSnagsTab.vue'
import StandingDecisionsTab from './extensions/autoharn/components/StandingDecisionsTab.vue'

export interface TabDef {
  id: string
  path: string
  label: string
  component: Component
  /** true = always visible (core); false = shown only when the autoharn extension is enabled.
   * 'Profiles' is core (row:141's commission: profile configuration from within the SPA is not
   * autoharn-specific), unlike the 7 autoharn-gated tabs below. */
  core: boolean
}

// Order here is display order in the tab bar -- unchanged from the previous coreTabs+autoharnTabs
// concatenation ('ledger' stays the app's default tab, so '/' redirects to TAB_DEFS[0].path).
export const TAB_DEFS = [
  { id: 'ledger', path: '/ledger', label: 'Recent ledger', component: LedgerTab, core: true },
  { id: 'profiles', path: '/profiles', label: 'Profiles', component: ProfilesPanel, core: true },
  { id: 'backend-surface', path: '/backend-surface', label: 'Backend surface', component: BackendSurfaceTab, core: true },
  { id: 'commission', path: '/commissions', label: 'Commission decomposition', component: CommissionTab, core: false },
  { id: 'work', path: '/work-items', label: 'Work items', component: WorkItemsTab, core: false },
  { id: 'review-gap', path: '/review-gap', label: 'Review gap', component: ReviewGapTab, core: false },
  { id: 'questions', path: '/questions', label: 'Questions', component: QuestionsTab, core: false },
  { id: 'work-violations', path: '/work-violations', label: 'Violations', component: WorkViolationsTab, core: false },
  { id: 'findings-snags', path: '/findings-snags', label: 'Findings & snags', component: FindingsSnagsTab, core: false },
  { id: 'standing-decisions', path: '/standing-decisions', label: 'Standing decisions', component: StandingDecisionsTab, core: false },
] as const satisfies readonly TabDef[]

// Derived, not hand-written -- was App.vue's own separately-maintained `TabId` union.
export type TabId = (typeof TAB_DEFS)[number]['id']
