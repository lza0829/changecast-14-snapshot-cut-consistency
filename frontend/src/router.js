import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './pages/Dashboard.vue'
import Streams from './pages/Streams.vue'
import Run from './pages/Run.vue'
import Projections from './pages/Projections.vue'
import Batches from './pages/Batches.vue'
import Events from './pages/Events.vue'
import Buffer from './pages/Buffer.vue'
import Settings from './pages/Settings.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/streams', component: Streams },
    { path: '/run', component: Run },
    { path: '/projections', component: Projections },
    { path: '/batches', component: Batches },
    { path: '/events', component: Events },
    { path: '/buffer', component: Buffer },
    { path: '/settings', component: Settings },
  ],
})
