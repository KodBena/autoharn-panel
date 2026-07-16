// src/router.ts -- the app's ONE vue-router instance (SPEC.md sec 2.2: "every item view is
// deep-linkable (`/item/<row-id>`)"). App.vue stays the single always-mounted root component
// (main.ts's `createApp(App)` is unchanged); this router is installed alongside it
// (`app.use(router)`) and App.vue itself decides, via `useRoute()`, whether to render its
// existing tab UI (any '/ledger', '/profiles', ... tab path) or a `<RouterView />` (path
// '/item/:id') -- so the tab routes below are declared only so vue-router recognizes each path,
// reflects it in the URL bar, and restores it on reload/direct-nav/bookmark (cycle-3 consult
// finding 3); they are never actually rendered through a `<router-view>` (App.vue shows its own
// tab markup for those paths instead), which is why each tab route below still points at an
// inert placeholder rather than the real tab component (that would need App's tab components
// imported here too, duplicating what App.vue already owns, for no rendering benefit -- App.vue
// keeps sole ownership of tab-content rendering; this file only owns path<->tab recognition).
//
// Tab paths/ids themselves come from `./tabs`'s TAB_DEFS (work item tab-architecture-
// consolidation, row:748) -- previously a separately hand-declared `TAB_PATHS` object here that
// had to be kept in sync with App.vue's own tab list by hand; now this file and App.vue both
// derive from the SAME array, so a tab's path is declared in exactly one place. Only the
// `id`/`path` fields are used below (never `.component`) -- importing TAB_DEFS does pull in every
// tab component transitively (they are needed for App.vue's real rendering anyway, from the same
// module), but this file's OWN route table still uses RootPlaceholder for every tab path, per the
// paragraph above.
import { defineComponent, h } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { TAB_DEFS } from './tabs'
import ItemView from './ItemView.vue'
import NotFoundView from './NotFoundView.vue'

const RootPlaceholder = defineComponent({ name: 'RootPlaceholder', render: () => h('div') })

// 'ledger' is the app's default tab (row:557/cycle3-tab-url-routing's acceptance: "redirect `/`
// to whichever tab is the current default", TAB_DEFS[0]), so '/' redirects there rather than
// being its own distinct route.
const routes: RouteRecordRaw[] = [
  { path: '/', redirect: TAB_DEFS[0].path },
  ...TAB_DEFS.map((t) => ({ path: t.path, component: RootPlaceholder })),
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
