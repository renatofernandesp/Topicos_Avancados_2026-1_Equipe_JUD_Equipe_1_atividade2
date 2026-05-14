<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Toast from 'primevue/toast'

const route = useRoute()

const sidebarJuiz = computed(() => route.path.startsWith('/juiz'))
</script>

<template>
  <div class="app-root">
    <header class="app-header">
      <div class="brand">
        <i class="pi pi-balance-scale" />
        <span>LLM-as-a-Judge</span>
      </div>
    </header>
    <div class="app-body">
      <aside v-if="sidebarJuiz" class="app-sidebar" aria-label="Navegação do juiz">
        <p class="app-sidebar-heading">Juiz</p>
        <nav class="app-sidebar-nav">
          <router-link
            to="/juiz/tarefas"
            class="app-nav-link"
            active-class="app-nav-link--active"
          >
            <i class="pi pi-list" aria-hidden="true" />
            <span>Tarefas</span>
          </router-link>
          <router-link
            to="/juiz/historico"
            class="app-nav-link"
            active-class="app-nav-link--active"
          >
            <i class="pi pi-history" aria-hidden="true" />
            <span>Histórico</span>
          </router-link>
          <router-link
            to="/juiz/correlacao"
            class="app-nav-link"
            active-class="app-nav-link--active"
          >
            <i class="pi pi-chart-line" aria-hidden="true" />
            <span>Correlação</span>
          </router-link>
        </nav>
      </aside>
      <main class="app-main" :class="{ 'app-main--sidebar': sidebarJuiz }">
        <router-view />
      </main>
    </div>
    <Toast position="bottom-right" />
  </div>
</template>

<style>
:root {
  font-family: 'Segoe UI', Roboto, system-ui, sans-serif;
  color-scheme: light dark;
}

body {
  margin: 0;
}

.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--p-content-border-color, #e5e7eb);
  flex-shrink: 0;
}

.app-header .brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  font-size: 1.1rem;
}

.app-body {
  flex: 1;
  display: flex;
  align-items: stretch;
  min-height: 0;
  width: 100%;
  box-sizing: border-box;
}

.app-sidebar {
  flex: 0 0 13.5rem;
  padding: 0.75rem 0;
  border-right: 1px solid var(--p-content-border-color, #e5e7eb);
  background: var(--p-surface-ground, #f4f4f5);
}

.app-sidebar-heading {
  margin: 0;
  padding: 0.35rem 1rem 0.65rem;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--p-text-muted-color, #71717a);
}

.app-sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.app-nav-link {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 1rem 0.5rem calc(1rem - 3px);
  margin: 0 0.5rem;
  border-radius: 6px;
  border-left: 3px solid transparent;
  font-size: 0.9375rem;
  line-height: 1.35;
  color: var(--p-text-color, #18181b);
  text-decoration: none;
  transition: background 0.12s ease;
}

.app-nav-link .pi {
  font-size: 1rem;
  opacity: 0.55;
  width: 1.1rem;
  text-align: center;
  flex-shrink: 0;
}

.app-nav-link:hover {
  background: rgba(0, 0, 0, 0.055);
}

.app-nav-link--active {
  background: var(--p-content-background, #fff);
  border-left-color: var(--p-primary-color, #2563eb);
  font-weight: 500;
  color: var(--p-primary-color, #2563eb);
}

.app-nav-link--active .pi {
  opacity: 1;
}

.app-main {
  flex: 1;
  min-width: 0;
  padding: 1.25rem;
  box-sizing: border-box;
}

.app-main:not(.app-main--sidebar) {
  max-width: 1280px;
  margin: 0 auto;
  width: 100%;
}

@media (max-width: 720px) {
  .app-body {
    flex-direction: column;
    max-width: 100%;
  }

  .app-sidebar {
    flex: none;
    width: 100%;
    padding: 0.5rem 0.75rem;
    border-right: none;
    border-bottom: 1px solid var(--p-content-border-color, #e5e7eb);
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.75rem;
  }

  .app-sidebar-heading {
    padding: 0 0.25rem 0 0;
    flex-shrink: 0;
  }

  .app-sidebar-nav {
    flex-direction: row;
    flex: 1;
    gap: 0.35rem;
  }

  .app-nav-link {
    flex: 1 1 auto;
    justify-content: center;
    margin: 0;
    padding: 0.45rem 0.65rem;
    border-left: none;
    border-bottom: 2px solid transparent;
    border-radius: 6px;
  }

  .app-nav-link--active {
    border-left: none;
    border-bottom-color: var(--p-primary-color, #2563eb);
    box-shadow: none;
  }
}

/* Tooltips dos KPIs (Juiz): overlay portado ao body */
.p-tooltip.juiz-kpi-tooltip .p-tooltip-text {
  max-width: min(26rem, 92vw);
  line-height: 1.45;
  white-space: normal;
  text-align: left;
}
</style>
