// src/router.ts -- the app's ONE vue-router instance (SPEC.md sec 2.2: "every item view is
// deep-linkable (`/item/<row-id>`)"). App.vue stays the single always-mounted root component
// (main.ts's `createApp(App)` is unchanged); this router is installed alongside it
// (`app.use(router)`) and App.vue itself decides, via `useRoute()`, whether to render its
// existing tab UI (path '/') or a `<RouterView />` (path '/item/:id') -- so the '/' route below
// is declared only so vue-router recognizes the path at all; it is never actually rendered
// through a `<router-view>` (App.vue shows its own tab markup for that path instead), which is
// why its component is an inert placeholder rather than App itself (that would need App to
// import this file, which imports App.vue's sibling ItemView -- no cycle, but no purpose either).
import { defineComponent, h } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import ItemView from './ItemView.vue'

const RootPlaceholder = defineComponent({ name: 'RootPlaceholder', render: () => h('div') })

const routes: RouteRecordRaw[] = [
  { path: '/', component: RootPlaceholder },
  { path: '/item/:id', component: ItemView, props: true },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
