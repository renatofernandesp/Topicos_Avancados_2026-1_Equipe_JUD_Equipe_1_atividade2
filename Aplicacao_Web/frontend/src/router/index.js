import { createRouter, createWebHistory } from 'vue-router'

const JuizView = () => import('../views/JuizView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/juiz/tarefas' },
    { path: '/juiz', redirect: '/juiz/tarefas' },
    { path: '/juiz/tarefas', name: 'juiz-tarefas', component: JuizView },
    { path: '/juiz/historico', name: 'juiz-historico', component: JuizView },
    { path: '/juiz/correlacao', name: 'juiz-correlacao', component: JuizView },
  ],
})

export default router
