// src/router.ts -- the app's ONE vue-router instance (SPEC.md sec 2.2: "every item view is
// deep-linkable (`/item/<row-id>`)"). App.vue stays the single always-mounted root component
// (main.ts's `createApp(App)` is unchanged); this router is installed alongside it
// (`app.use(router)`) and App.vue itself decides, via `useRoute()`, whether to render its
// existing tab UI (any '/ledger', '/profiles', ... tab path) or a `<RouterView />` (path
// '/item/:id') -- so the tab routes below are declared only so vue-router recognizes each path,
// reflects it in the URL bar, and restores it on reload/direct-nav/bookmark (cycle-3 consult
// finding 3); they are never actually rendered through a `<router-view>` (App.vue shows its own
// tab markup for those paths instead), which is why each tab's component is an inert placeholder
// rather than the real tab component (that would need App's tab components imported here too,
// duplicating what App.vue already owns, for no rendering benefit -- App.vue keeps sole
// ownership of tab-content rendering; this file only owns path<->tab recognition).
import { defineComponent, h } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import ItemView from './ItemView.vue'
import NotFoundView from './NotFoundView.vue'

const RootPlaceholder = defineComponent({ name: 'RootPlaceholder', render: () => h('div') })

// Tab path slugs, one per tab id in App.vue's TabId union. 'ledger' is the app's default tab
// (row:557/cycle3-tab-url-routing's acceptance: "redirect `/` to whichever tab is the current
// default"), so '/' redirects there rather than being its own distinct route.
export const TAB_PATHS = {
  ledger: '/ledger',
  profiles: '/profiles',
  commission: '/commissions',
  work: '/work-items',
  'review-gap': '/review-gap',
  questions: '/questions',
  'work-violations': '/work-violations',
} as const

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: TAB_PATHS.ledger },
  { path: TAB_PATHS.ledger, component: RootPlaceholder },
  { path: TAB_PATHS.profiles, component: RootPlaceholder },
  { path: TAB_PATHS.commission, component: RootPlaceholder },
  { path: TAB_PATHS.work, component: RootPlaceholder },
  { path: TAB_PATHS['review-gap'], component: RootPlaceholder },
  { path: TAB_PATHS.questions, component: RootPlaceholder },
  { path: TAB_PATHS['work-violations'], component: RootPlaceholder },
  { path: '/item/:id', component: ItemView, props: true },
  // Catch-all: any path matching none of the above (cycle3-unknown-path-404 / consult finding
  // 4). Must stay LAST -- vue-router resolves routes in declaration order. App.vue's own
  // isTabRoute gate is what actually decides tab-UI-vs-RouterView; this route just gives the
  // unmatched-path case something distinct to resolve to under RouterView so App.vue can tell
  // it apart from a recognized tab path.
  { path: '/:pathMatch(.*)*', component: NotFoundView },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
