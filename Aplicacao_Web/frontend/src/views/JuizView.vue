<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import MultiSelect from 'primevue/multiselect'
import Select from 'primevue/select'
import InputNumber from 'primevue/inputnumber'
import ProgressBar from 'primevue/progressbar'
import Tag from 'primevue/tag'
import Card from 'primevue/card'
import Dialog from 'primevue/dialog'
import Message from 'primevue/message'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import Chart from 'primevue/chart'

import { api, openEventos } from '../api.js'

const toast = useToast()
const route = useRoute()

const carregando = ref(false)
const executando = ref(false)
/** Secção sincronizada com a rota (`App.vue` sidebar). */
const secaoJuiz = computed(() => {
  if (route.name === 'juiz-historico') return 'historico'
  if (route.name === 'juiz-correlacao') return 'correlacao'
  return 'tarefas'
})
const tituloSecaoCard = computed(() => {
  if (secaoJuiz.value === 'historico') return 'Histórico de avaliações'
  if (secaoJuiz.value === 'correlacao') return 'Correlação juiz × humano'
  return 'Tarefas do juiz'
})
const tabJuiz = ref(0)
const tarefas = ref([])
const tarefasAvaliadas = ref([])
const selecao = ref([])
const selecaoAvaliadas = ref([])
const confirmSubstituir = ref(false)
const juizes = ref([])
const historicoAvaliacoes = ref([])
const totalHistorico = ref(0)
const pageHistorico = reactive({ first: 0, rows: 25 })
const loadingHistorico = ref(false)
const correlacaoResult = ref(null)
const loadingCorrelacao = ref(false)
/** Tab interna: dispersão vs matriz de confusão (secção Correlação). */
const tabCorrelacaoGraficos = ref(0)

function jitterCorrelacao(i) {
  const s = Math.sin((i + 1) * 12.9898) * 43758.5453
  const r = s - Math.floor(s)
  return (r - 0.5) * 0.22
}

const scatterChartData = computed(() => {
  const r = correlacaoResult.value
  const pts = r?.scatter_pontos
  if (!pts?.length) return null
  return {
    datasets: [
      {
        label: 'Pares',
        data: pts.map((p, i) => ({
          x: p.nota_humana + jitterCorrelacao(i * 2),
          y: p.nota_juiz + jitterCorrelacao(i * 2 + 1),
        })),
        backgroundColor: 'rgba(59, 130, 246, 0.42)',
        borderColor: 'rgba(37, 99, 235, 0.9)',
        pointRadius: 6,
        pointHoverRadius: 8,
      },
    ],
  }
})

const scatterChartOptions = computed(() => {
  const e = correlacaoResult.value?.eixos_notas
  let min = 0.5
  let max = 5.5
  if (e?.length) {
    min = Math.min(...e) - 0.5
    max = Math.max(...e) + 0.5
  }
  return {
    responsive: true,
    maintainAspectRatio: true,
    aspectRatio: 1,
    layout: {
      padding: { top: 6, right: 10, bottom: 6, left: 6 },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label(ctx) {
            const p = correlacaoResult.value?.scatter_pontos?.[ctx.dataIndex]
            if (!p) return ''
            return `Humano ${p.nota_humana} × Juiz ${p.nota_juiz}`
          },
        },
      },
    },
    scales: {
      x: {
        type: 'linear',
        min,
        max,
        ticks: { stepSize: 1 },
        title: { display: true, text: 'Nota humana' },
      },
      y: {
        type: 'linear',
        min,
        max,
        ticks: { stepSize: 1 },
        title: { display: true, text: 'Nota juiz (ROUND)' },
      },
    },
  }
})

function estiloCelulaConfusao(celula, matriz) {
  const flat = (matriz || []).flat()
  const vmax = Math.max(1, ...flat)
  const t = vmax > 0 ? celula / vmax : 0
  const a = 0.1 + t * 0.78
  return {
    backgroundColor: `rgba(37, 99, 235, ${a})`,
    color: t > 0.52 ? '#fff' : 'inherit',
    fontWeight: celula > 0 ? '600' : '400',
  }
}

const contagens = ref(null)
const health = ref({ ok: false, has_gemini_key: false })

/** Textos do tooltip dos KPIs (visão geral). */
const kpiTooltips = {
  perguntas:
    'Número de linhas na tabela perguntas (enunciados e gabaritos cadastrados por dataset).',
  respostas:
    'Número de linhas em respostas_atividade_1 (respostas dos modelos candidatos já importadas e guardadas).',
  avaliacoes:
    'Número de linhas em avaliacoes_juiz — cada avaliação é um juiz avaliando uma resposta. Com três juízes ativos, uma mesma resposta “completa” costuma contribuir com até 3 linhas aqui.',
  respostasIncompletas:
    'Quantas respostas distintas (id_resposta) ainda não têm avaliação de todos os juízes ativos em modelos_juiz (falta pelo menos um par resposta × juiz).',
  tarefasPendentes:
    'Total de pares (resposta × juiz) que ainda faltam avaliar',
}

const tooltipKpi = (value) => ({
  value,
  showDelay: 350,
  hideDelay: 150,
  class: 'juiz-kpi-tooltip',
})

const filtrosOpcoes = ref({ modelos_candidatos: [] })

const filtros = reactive({
  id_modelo_juiz: [],
  idResposta: null,
  idQuestao: null,
  modelo_candidato: null,
  /** Teto de tarefas no lote «Executar todas (filtro)» (API). */
  limiteExecucao: 300,
})

const pagePendentes = reactive({ first: 0, rows: 25 })
const pageAvaliadas = reactive({ first: 0, rows: 25 })
const totalPendentes = ref(0)
const totalAvaliadas = ref(0)
const loadingPendentes = ref(false)
const loadingAvaliadas = ref(false)

const modelosCandidatos = computed(() =>
  filtrosOpcoes.value.modelos_candidatos.map((m) => ({ label: m, value: m })),
)

function idsRespostaParaApi() {
  const v = filtros.idResposta
  if (v === null || v === undefined) return undefined
  const n = Number(v)
  if (!Number.isInteger(n) || n < 1) return undefined
  return [n]
}

function idsQuestaoParaApi() {
  const v = filtros.idQuestao
  if (v === null || v === undefined) return undefined
  const n = Number(v)
  if (!Number.isInteger(n) || n < 1) return undefined
  return [n]
}

const progresso = reactive({
  total: 0,
  atual: 0,
  runId: null,
  log: [],
  erros: 0,
  sucesso: 0,
})

let eventSource = null

function logLinha(item) {
  progresso.log.unshift(item)
  if (progresso.log.length > 200) progresso.log.length = 200
}

async function carregarBase() {
  carregando.value = true
  try {
    const [h, mj, c, fo] = await Promise.all([
      api.health(),
      api.modelosJuiz(),
      api.contagens(),
      api.filtrosOpcoes().catch(() => ({ modelos_candidatos: [] })),
    ])
    health.value = h
    juizes.value = mj
    contagens.value = c
    filtrosOpcoes.value = fo
    if (filtros.id_modelo_juiz.length === 0) {
      filtros.id_modelo_juiz = mj.filter((j) => j.ativo).map((j) => j.id_modelo_juiz)
    }
    pagePendentes.first = 0
    pageAvaliadas.first = 0
    pageHistorico.first = 0
    await Promise.all([carregarTarefas(), carregarAvaliadas()])
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Falha ao carregar', detail: e.message, life: 5000 })
  } finally {
    carregando.value = false
  }
}

function onFiltrosJuizChange() {
  pagePendentes.first = 0
  pageAvaliadas.first = 0
  recarregarTabelasJuiz()
}

async function carregarTarefas() {
  loadingPendentes.value = true
  try {
    const data = await api.pendentes({
      id_modelo_juiz: filtros.id_modelo_juiz,
      id_resposta: idsRespostaParaApi(),
      id_questao: idsQuestaoParaApi(),
      offset: pagePendentes.first,
      page_size: pagePendentes.rows,
      modelo_candidato: filtros.modelo_candidato || undefined,
    })
    totalPendentes.value = data.total ?? 0
    tarefas.value = (data.items || []).map((t) => ({
      ...t,
      _key: `${t.id_resposta}-${t.id_modelo_juiz}`,
    }))
    selecao.value = []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Erro nas tarefas', detail: e.message, life: 5000 })
  } finally {
    loadingPendentes.value = false
  }
}

async function carregarAvaliadas() {
  loadingAvaliadas.value = true
  try {
    const data = await api.avaliadas({
      id_modelo_juiz: filtros.id_modelo_juiz,
      id_resposta: idsRespostaParaApi(),
      id_questao: idsQuestaoParaApi(),
      offset: pageAvaliadas.first,
      page_size: pageAvaliadas.rows,
      modelo_candidato: filtros.modelo_candidato || undefined,
    })
    totalAvaliadas.value = data.total ?? 0
    tarefasAvaliadas.value = (data.items || []).map((t) => ({
      ...t,
      _key: `${t.id_resposta}-${t.id_modelo_juiz}`,
    }))
    selecaoAvaliadas.value = []
  } catch (e) {
    toast.add({
      severity: 'error',
      summary: 'Erro nas tarefas avaliadas',
      detail: e.message,
      life: 5000,
    })
  } finally {
    loadingAvaliadas.value = false
  }
}

function onPagePendentes(ev) {
  pagePendentes.first = ev.first
  pagePendentes.rows = ev.rows
  carregarTarefas()
}

function onPageAvaliadas(ev) {
  pageAvaliadas.first = ev.first
  pageAvaliadas.rows = ev.rows
  carregarAvaliadas()
}

async function recarregarTabelasJuiz() {
  pagePendentes.first = 0
  pageAvaliadas.first = 0
  carregando.value = true
  try {
    const extras = []
    if (secaoJuiz.value === 'historico') extras.push(carregarHistoricoAvaliacoes())
    if (secaoJuiz.value === 'correlacao') extras.push(carregarCorrelacao())
    await Promise.all([carregarTarefas(), carregarAvaliadas(), ...extras])
  } finally {
    carregando.value = false
  }
}

async function carregarHistoricoAvaliacoes() {
  loadingHistorico.value = true
  try {
    const data = await api.historicoAvaliacoes({
      offset: pageHistorico.first,
      page_size: pageHistorico.rows,
      id_questao: idsQuestaoParaApi(),
    })
    totalHistorico.value = data.total ?? 0
    historicoAvaliacoes.value = (data.items || []).map((row) => ({
      ...row,
      _key: `av-${row.id_avaliacao}`,
    }))
  } catch (e) {
    toast.add({
      severity: 'error',
      summary: 'Erro no histórico de avaliações',
      detail: e.message,
      life: 5000,
    })
  } finally {
    loadingHistorico.value = false
  }
}

function onPageHistorico(ev) {
  pageHistorico.first = ev.first
  pageHistorico.rows = ev.rows
  carregarHistoricoAvaliacoes()
}

function onFiltrosHistoricoChange() {
  pageHistorico.first = 0
  carregarHistoricoAvaliacoes()
}

async function carregarCorrelacao() {
  loadingCorrelacao.value = true
  try {
    correlacaoResult.value = await api.correlacaoHumano()
  } catch (e) {
    correlacaoResult.value = { erro: e.message || String(e) }
  } finally {
    loadingCorrelacao.value = false
  }
}

watch(
  () => route.name,
  (name) => {
    if (name === 'juiz-historico') {
      carregarHistoricoAvaliacoes()
    }
    if (name === 'juiz-correlacao') {
      carregarCorrelacao()
    }
  },
  { immediate: true },
)

function fechado() {
  return eventSource && eventSource.readyState === EventSource.CLOSED
}

async function iniciarRun(payload) {
  try {
    executando.value = true
    progresso.log = []
    progresso.atual = 0
    progresso.total = 0
    progresso.erros = 0
    progresso.sucesso = 0
    const resp = await api.executar(payload)
    progresso.total = resp.total_estimado
    progresso.runId = resp.run_id
    eventSource = openEventos(resp.run_id, {
      onStart: (data) => {
        progresso.total = data.total_estimado
      },
      onTarefa: (ev) => {
        progresso.atual = ev.atual
        progresso.total = ev.total
        const rid = ev.id_resposta ?? ev.id
        if (ev.erro) {
          progresso.erros += 1
          const tipo = ev.erro_tipo ? ` (${ev.erro_tipo})` : ''
          let text = `[${ev.juiz || '?'}] resposta ${rid ?? '?'}: ${ev.erro}${tipo}`
          if (ev.erro_detalhe) {
            text += `\n--- detalhe ---\n${ev.erro_detalhe}`
          }
          logLinha({ tipo: 'erro', text })
        } else {
          progresso.sucesso += 1
          const sc = ev.subcrit || {}
          logLinha({
            tipo: 'ok',
            text: `[${ev.juiz}] resposta ${rid} → ${ev.nota} (CF=${sc.correcao_factual ?? '-'} CO=${sc.completude ?? '-'} CL=${sc.clareza ?? '-'} COE=${sc.coerencia ?? '-'} RE=${sc.relevancia ?? '-'})`,
          })
        }
      },
      onDone: async () => {
        executando.value = false
        toast.add({ severity: 'success', summary: 'Execução concluída', detail: `${progresso.sucesso} ok, ${progresso.erros} erro(s)`, life: 4000 })
        pageHistorico.first = 0
        await Promise.all([
          recarregarTabelasJuiz(),
          carregarHistoricoAvaliacoes(),
          api.contagens().then((c) => (contagens.value = c)),
        ])
      },
      onError: () => {
        executando.value = false
        toast.add({ severity: 'error', summary: 'Conexão SSE perdida', detail: 'Verifique o backend.', life: 5000 })
      },
    })
  } catch (e) {
    executando.value = false
    toast.add({ severity: 'error', summary: 'Falha ao iniciar', detail: e.message, life: 5000 })
  }
}

async function executar(modo) {
  if (!health.value.has_gemini_key) {
    toast.add({ severity: 'warn', summary: 'Chave ausente', detail: 'GEMINI_API_KEY não configurada no backend.', life: 5000 })
    return
  }
  let payload
  if (modo === 'selecionadas') {
    if (!selecao.value.length) {
      toast.add({ severity: 'info', summary: 'Sem seleção', detail: 'Marque ao menos uma tarefa.', life: 3500 })
      return
    }
    const idsResposta = Array.from(new Set(selecao.value.map((t) => t.id_resposta)))
    const idsJuiz = Array.from(new Set(selecao.value.map((t) => t.id_modelo_juiz)))
    payload = { ids_resposta: idsResposta, ids_modelo_juiz: idsJuiz }
  } else {
    payload = {
      ids_modelo_juiz: filtros.id_modelo_juiz.length ? filtros.id_modelo_juiz : null,
      limite: filtros.limiteExecucao || null,
    }
  }
  await iniciarRun(payload)
}

async function executarReavaliarSubstituir() {
  if (!health.value.has_gemini_key) {
    toast.add({ severity: 'warn', summary: 'Chave ausente', detail: 'GEMINI_API_KEY não configurada no backend.', life: 5000 })
    return
  }
  if (!confirmSubstituir.value) {
    toast.add({
      severity: 'warn',
      summary: 'Confirmação necessária',
      detail: 'Marque a confirmação para apagar a avaliação e a rubrica existentes antes de reexecutar o juiz.',
      life: 5000,
    })
    return
  }
  if (!selecaoAvaliadas.value.length) {
    toast.add({
      severity: 'info',
      summary: 'Sem seleção',
      detail: 'Na lista “Já avaliadas”, selecione ao menos um par resposta × juiz.',
      life: 4000,
    })
    return
  }
  const payload = {
    substituir: true,
    pares: selecaoAvaliadas.value.map((t) => ({
      id_resposta: t.id_resposta,
      id_modelo_juiz: t.id_modelo_juiz,
    })),
  }
  await iniciarRun(payload)
}

function fmtNotaHumana(v) {
  if (v === null || v === undefined) return '-'
  return String(v)
}

const dialogoTexto = reactive({
  visivel: false,
  titulo: '',
  corpo: '',
})

function abrirTextoCompleto(titulo, texto) {
  const t = texto != null ? String(texto) : ''
  dialogoTexto.titulo = titulo
  dialogoTexto.corpo = t.length ? t : '(vazio)'
  dialogoTexto.visivel = true
}

onMounted(carregarBase)
onBeforeUnmount(() => {
  if (eventSource && !fechado()) eventSource.close()
})
</script>

<template>
  <section class="juiz-page">
    <Card>
      <template #title>Visão geral</template>
      <template #content>
        <div class="kpis">
          <div
            class="kpi"
            v-tooltip.bottom.focus="tooltipKpi(kpiTooltips.perguntas)"
            tabindex="0"
            role="group"
            :aria-label="`Perguntas: ${contagens?.perguntas ?? '—'}. ${kpiTooltips.perguntas}`"
          >
            <i class="pi pi-question-circle kpi-icon" aria-hidden="true" />
            <div class="kpi-body">
              <span>Perguntas</span>
              <strong>{{ contagens?.perguntas ?? '-' }}</strong>
            </div>
          </div>
          <div
            class="kpi"
            v-tooltip.bottom.focus="tooltipKpi(kpiTooltips.respostas)"
            tabindex="0"
            role="group"
            :aria-label="`Respostas: ${contagens?.respostas ?? '—'}. ${kpiTooltips.respostas}`"
          >
            <i class="pi pi-comments kpi-icon" aria-hidden="true" />
            <div class="kpi-body">
              <span>Respostas</span>
              <strong>{{ contagens?.respostas ?? '-' }}</strong>
            </div>
          </div>
          <div
            class="kpi"
            v-tooltip.bottom.focus="tooltipKpi(kpiTooltips.avaliacoes)"
            tabindex="0"
            role="group"
            :aria-label="`Avaliações: ${contagens?.avaliacoes ?? '—'}. ${kpiTooltips.avaliacoes}`"
          >
            <i class="pi pi-star kpi-icon" aria-hidden="true" />
            <div class="kpi-body">
              <span>Avaliações</span>
              <strong>{{ contagens?.avaliacoes ?? '-' }}</strong>
            </div>
          </div>
          <div
            class="kpi"
            v-tooltip.bottom.focus="tooltipKpi(kpiTooltips.respostasIncompletas)"
            tabindex="0"
            role="group"
            :aria-label="`Respostas incompletas: ${contagens?.respostas_gemini_pendentes ?? '—'}. ${kpiTooltips.respostasIncompletas}`"
          >
            <i class="pi pi-hourglass kpi-icon" aria-hidden="true" />
            <div class="kpi-body">
              <span>Respostas incompletas</span>
              <strong>{{ contagens?.respostas_gemini_pendentes ?? '-' }}</strong>
            </div>
          </div>
          <div
            class="kpi"
            v-tooltip.bottom.focus="tooltipKpi(kpiTooltips.tarefasPendentes)"
            tabindex="0"
            role="group"
            :aria-label="`Tarefas pendentes: ${contagens?.tarefas_juiz_pendentes ?? '—'}. ${kpiTooltips.tarefasPendentes}`"
          >
            <i class="pi pi-inbox kpi-icon" aria-hidden="true" />
            <div class="kpi-body">
              <span>Tarefas pendentes</span>
              <strong>{{ contagens?.tarefas_juiz_pendentes ?? '-' }}</strong>
            </div>
          </div>
        </div>
        <Message v-if="!health.has_gemini_key" severity="warn" :closable="false">
          GEMINI_API_KEY não configurada no backend; execução está desativada.
        </Message>
      </template>
    </Card>

    <Card class="mt-3">
      <template #title>{{ tituloSecaoCard }}</template>
      <template #content>
            <div v-show="secaoJuiz === 'tarefas'" class="juiz-pane">
            <div class="filtros-wrap mb-3">
              <div class="filtros-campos">
                <MultiSelect
                  v-model="filtros.id_modelo_juiz"
                  :options="juizes"
                  option-label="nome_exibicao"
                  option-value="id_modelo_juiz"
                  placeholder="Juízes"
                  display="chip"
                  fluid
                  class="filtro-item"
                  @update:model-value="onFiltrosJuizChange"
                />
                <div class="filtro-item filtro-limite">
                  <label class="filtro-label" for="filtro-id-resposta">ID da resposta</label>
                  <InputNumber
                    id="filtro-id-resposta"
                    v-model="filtros.idResposta"
                    :min="1"
                    :use-grouping="false"
                    placeholder="Todos"
                    fluid
                    show-clear
                    input-class="w-full"
                    @update:model-value="onFiltrosJuizChange"
                  />
                </div>
                <div class="filtro-item filtro-limite">
                  <label class="filtro-label" for="filtro-id-questao">ID da questão</label>
                  <InputNumber
                    id="filtro-id-questao"
                    v-model="filtros.idQuestao"
                    :min="1"
                    :use-grouping="false"
                    placeholder="Todos"
                    fluid
                    show-clear
                    input-class="w-full"
                    @update:model-value="onFiltrosJuizChange"
                  />
                </div>
                <Select
                  v-model="filtros.modelo_candidato"
                  :options="modelosCandidatos"
                  option-label="label"
                  option-value="value"
                  placeholder="Modelo candidato"
                  show-clear
                  fluid
                  class="filtro-item"
                  @update:model-value="onFiltrosJuizChange"
                />
                <div class="filtro-item filtro-limite">
                  <label class="filtro-label" for="limite-exec-input">Máx. tarefas (executar todas)</label>
                  <InputNumber
                    id="limite-exec-input"
                    v-model="filtros.limiteExecucao"
                    :min="1"
                    :max="50000"
                    show-buttons
                    :step="50"
                    fluid
                    input-class="w-full"
                    placeholder="Limite do lote"
                  />
                </div>
                <Button
                  icon="pi pi-refresh"
                  label="Recarregar listas"
                  severity="secondary"
                  class="filtro-recarregar"
                  :loading="carregando"
                  @click="recarregarTabelasJuiz"
                />
              </div>
            </div>

            <TabView
              v-if="secaoJuiz === 'tarefas'"
              v-model:activeIndex="tabJuiz"
              class="juiz-tab-filho"
            >
          <TabPanel header="Pendentes">
            <div class="filtros-acoes mb-3">
              <Button
                icon="pi pi-play"
                :label="`Executar selecionadas (${selecao.length})`"
                severity="primary"
                :disabled="executando || !selecao.length || !health.has_gemini_key"
                :loading="executando"
                @click="executar('selecionadas')"
              />
              <Button
                icon="pi pi-bolt"
                label="Executar todas (filtro)"
                severity="warning"
                :disabled="executando || !totalPendentes || !health.has_gemini_key"
                @click="executar('todas')"
              />
            </div>

            <p class="tab-total-hint">
              {{ totalPendentes }} tarefa(s) pendente(s) com o filtro atual (navegue pelas páginas).
            </p>

            <DataTable
              v-model:selection="selecao"
              lazy
              paginator
              :first="pagePendentes.first"
              :rows="pagePendentes.rows"
              :total-records="totalPendentes"
              :value="tarefas"
              data-key="_key"
              row-hover
              striped-rows
              :rows-per-page-options="[10, 25, 50, 100, 200, 500]"
              :loading="loadingPendentes || carregando"
              empty-message="Sem tarefas pendentes para o filtro atual."
              @page="onPagePendentes($event)"
            >
              <Column selection-mode="multiple" header-style="width:3rem" />
              <Column field="id_resposta" header="ID resposta" style="width: 6rem" />
              <Column field="nome_modelo" header="Modelo candidato" />
              <Column field="id_api_juiz" header="Juiz">
                <template #body="{ data }">
                  <Tag :value="data.id_api_juiz" severity="info" />
                </template>
              </Column>
              <Column header="Enunciado">
                <template #body="{ data }">
                  <span
                    class="celula-texto-clicavel"
                    role="button"
                    tabindex="0"
                    title="Clique para ver o texto completo"
                    @click.stop="abrirTextoCompleto('Enunciado', data.enunciado_completo)"
                    @keydown.enter.stop="
                      abrirTextoCompleto('Enunciado', data.enunciado_completo)
                    "
                  >{{ data.enunciado_preview }}</span>
                </template>
              </Column>
              <Column header="Resposta">
                <template #body="{ data }">
                  <span
                    class="celula-texto-clicavel"
                    role="button"
                    tabindex="0"
                    title="Clique para ver o texto completo"
                    @click.stop="abrirTextoCompleto('Resposta', data.texto_resposta_completo)"
                    @keydown.enter.stop="
                      abrirTextoCompleto('Resposta', data.texto_resposta_completo)
                    "
                  >{{ data.resposta_preview }}</span>
                </template>
              </Column>
            </DataTable>
          </TabPanel>

          <TabPanel header="Já avaliadas">
            <Message severity="warn" :closable="false" class="mb-3">
              Reavaliar apaga as avaliações já realizadas.
            </Message>

            <div class="substituir-ux mb-3">
              <Checkbox v-model="confirmSubstituir" binary input-id="chk-subst-juiz" />
              <label for="chk-subst-juiz" class="substituir-label">
                Confirmo apagar a avaliação e a rubrica existentes nos pares selecionados.
              </label>
            </div>

            <div class="filtros-acoes mb-3">
              <Button
                icon="pi pi-refresh"
                :label="`Reavaliar (substituir) — ${selecaoAvaliadas.length} par(es)`"
                :disabled="
                  executando ||
                  !selecaoAvaliadas.length ||
                  !confirmSubstituir ||
                  !health.has_gemini_key
                "
                :loading="executando"
                @click="executarReavaliarSubstituir"
              />
            </div>

            <p class="tab-total-hint">
              {{ totalAvaliadas }} par(es) já avaliado(s) com o filtro atual (navegue pelas páginas).
            </p>

            <DataTable
              v-model:selection="selecaoAvaliadas"
              lazy
              paginator
              :first="pageAvaliadas.first"
              :rows="pageAvaliadas.rows"
              :total-records="totalAvaliadas"
              :value="tarefasAvaliadas"
              data-key="_key"
              row-hover
              striped-rows
              :rows-per-page-options="[10, 25, 50, 100, 200, 500]"
              :loading="loadingAvaliadas || carregando"
              empty-message="Sem pares já avaliados para o filtro atual."
              @page="onPageAvaliadas($event)"
            >
              <Column selection-mode="multiple" header-style="width:3rem" />
              <Column field="id_resposta" header="ID resposta" style="width: 6rem" />
              <Column field="nome_modelo" header="Modelo candidato" />
              <Column field="id_api_juiz" header="Juiz">
                <template #body="{ data }">
                  <Tag :value="data.id_api_juiz" severity="info" />
                </template>
              </Column>
              <Column header="Enunciado">
                <template #body="{ data }">
                  <span
                    class="celula-texto-clicavel"
                    role="button"
                    tabindex="0"
                    title="Clique para ver o texto completo"
                    @click.stop="abrirTextoCompleto('Enunciado', data.enunciado_completo)"
                    @keydown.enter.stop="
                      abrirTextoCompleto('Enunciado', data.enunciado_completo)
                    "
                  >{{ data.enunciado_preview }}</span>
                </template>
              </Column>
              <Column header="Resposta">
                <template #body="{ data }">
                  <span
                    class="celula-texto-clicavel"
                    role="button"
                    tabindex="0"
                    title="Clique para ver o texto completo"
                    @click.stop="abrirTextoCompleto('Resposta', data.texto_resposta_completo)"
                    @keydown.enter.stop="
                      abrirTextoCompleto('Resposta', data.texto_resposta_completo)
                    "
                  >{{ data.resposta_preview }}</span>
                </template>
              </Column>
            </DataTable>
          </TabPanel>
        </TabView>
            </div>

            <div v-show="secaoJuiz === 'historico'" class="juiz-pane">
            <div class="filtros-wrap mb-3">
              <div class="filtros-campos">
                <div class="filtro-item filtro-limite">
                  <label class="filtro-label" for="hist-filtro-id-questao">ID da questão</label>
                  <InputNumber
                    id="hist-filtro-id-questao"
                    v-model="filtros.idQuestao"
                    :min="1"
                    :use-grouping="false"
                    placeholder="Todos"
                    fluid
                    show-clear
                    input-class="w-full"
                    @update:model-value="onFiltrosHistoricoChange"
                  />
                </div>
              </div>
            </div>
            <DataTable
              :value="historicoAvaliacoes"
              lazy
              paginator
              :first="pageHistorico.first"
              :rows="pageHistorico.rows"
              :total-records="totalHistorico"
              data-key="_key"
              striped-rows
              row-hover
              :rows-per-page-options="[10, 25, 50, 100, 200, 500]"
              :loading="loadingHistorico"
              empty-message="Sem avaliações ainda."
              @page="onPageHistorico($event)"
            >
              <Column field="modelo_candidato" header="Modelo" />
              <Column field="modelo_juiz" header="Juiz" />
              <Column header="Pergunta">
                <template #body="{ data }">
                  <span
                    class="celula-texto-clicavel"
                    role="button"
                    tabindex="0"
                    title="Clique para ver o texto completo"
                    @click.stop="abrirTextoCompleto('Pergunta', data.enunciado_completo)"
                    @keydown.enter.stop="abrirTextoCompleto('Pergunta', data.enunciado_completo)"
                  >{{ data.enunciado_preview }}</span>
                </template>
              </Column>
              <Column field="nota_atribuida" header="Nota" style="width: 5rem" />
              <Column field="nota_humana" header="Nota Humana" style="width: 6rem">
                <template #body="{ data }">{{ fmtNotaHumana(data.nota_humana) }}</template>
              </Column>
              <Column header="Raciocínio">
                <template #body="{ data }">
                  <span
                    class="celula-texto-clicavel"
                    role="button"
                    tabindex="0"
                    title="Clique para ver o texto completo"
                    @click.stop="abrirTextoCompleto('Raciocínio', data.chain_of_thought_completo)"
                    @keydown.enter.stop="
                      abrirTextoCompleto('Raciocínio', data.chain_of_thought_completo)
                    "
                  >{{ data.chain_of_thought_preview || '—' }}</span>
                </template>
              </Column>
            </DataTable>
            </div>

            <div v-show="secaoJuiz === 'correlacao'" class="juiz-pane">
              <p class="correlacao-intro mb-3">
                Cada linha da tabela <code>avaliacoes_juiz</code> com <code>nota_humana</code> preenchida
                contribui com um par: nota dada pelo anotador humano (<code>nota_humana</code>) e nota do juiz
                LLM (<code>ROUND(nota_atribuida)</code>). Os gráficos agregam
                <strong>todos</strong> esses pares (vários modelos de juiz e várias respostas entram na mesma
                contagem; não é filtro por pessoa nem por um único modelo de juiz).
              </p>
              <div class="mb-3">
                <Button
                  icon="pi pi-refresh"
                  label="Atualizar métricas"
                  severity="secondary"
                  :loading="loadingCorrelacao"
                  @click="carregarCorrelacao"
                />
              </div>
              <ProgressBar
                v-if="loadingCorrelacao && correlacaoResult === null"
                mode="indeterminate"
                class="mb-3"
              />
              <Message
                v-if="correlacaoResult?.erro"
                severity="warn"
                :closable="false"
                class="mb-3"
              >
                {{ correlacaoResult.erro }}
              </Message>
              <template v-else-if="correlacaoResult && correlacaoResult.n_amostras != null">
                <div class="correlacao-metricas mb-3">
                  <div class="correlacao-metrica">
                    <span class="correlacao-metrica-label">Amostras (pares)</span>
                    <strong>{{ correlacaoResult.n_amostras }}</strong>
                  </div>
                  <div class="correlacao-metrica">
                    <span class="correlacao-metrica-label">Spearman ρ</span>
                    <strong>{{ correlacaoResult.spearman_rho }}</strong>
                    <span class="correlacao-metrica-sub">p = {{ correlacaoResult.spearman_p }}</span>
                  </div>
                </div>
                <Message v-if="correlacaoResult.interpretacao" severity="info" :closable="false" class="mb-3">
                  {{ correlacaoResult.interpretacao }}
                </Message>
                <TabView
                  v-model:activeIndex="tabCorrelacaoGraficos"
                  class="correlacao-graficos-tabs"
                >
                  <TabPanel header="Dispersão">
                    <div class="correlacao-tab-panel-inner">
                      <Message
                        v-if="correlacaoResult.scatter_amostrado"
                        severity="secondary"
                        :closable="false"
                        class="mb-3 correlacao-tab-msg"
                      >
                        O gráfico usa amostra aleatória de
                        {{ correlacaoResult.scatter_n_plot }} de {{ correlacaoResult.scatter_n_total }} pares
                        (limite do servidor para desempenho).
                      </Message>
                      <div v-if="scatterChartData" class="chart-scatter-wrap">
                        <Chart type="scatter" :data="scatterChartData" :options="scatterChartOptions" />
                      </div>
                    </div>
                  </TabPanel>
                  <TabPanel header="Matriz de confusão">
                    <div class="correlacao-tab-panel-inner">
                      <p class="correlacao-legenda-sm mb-3 correlacao-tab-msg">
                        Contagem de <strong>linhas de avaliação</strong>: linha = valor de
                        <code>nota_humana</code>; coluna = valor de <code>ROUND(nota_atribuida)</code> (nota do
                        LLM na mesma linha).
                      </p>
                      <div
                        v-if="correlacaoResult.eixos_notas?.length && correlacaoResult.matriz_confusao?.length"
                        class="conf-matrix-scroll"
                      >
                        <table
                          class="conf-matrix-table"
                          aria-label="Matriz de confusão: nota humana por nota do juiz LLM"
                        >
                          <thead>
                            <tr>
                              <th class="conf-matrix-corner" scope="col" />
                              <th
                                v-for="j in correlacaoResult.eixos_notas"
                                :key="'cj-' + j"
                                class="conf-matrix-head"
                                scope="col"
                              >
                                LLM = {{ j }}
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr
                              v-for="(row, ri) in correlacaoResult.matriz_confusao"
                              :key="'r-' + ri"
                            >
                              <th class="conf-matrix-rowhead" scope="row">
                                Humano = {{ correlacaoResult.eixos_notas[ri] }}
                              </th>
                              <td
                                v-for="(cell, ci) in row"
                                :key="'c-' + ri + '-' + ci"
                                class="conf-matrix-cell"
                                :style="estiloCelulaConfusao(cell, correlacaoResult.matriz_confusao)"
                              >
                                {{ cell }}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </TabPanel>
                </TabView>
              </template>
            </div>
      </template>
    </Card>

    <Card v-if="executando || progresso.log.length" class="mt-3">
      <template #title>Progresso</template>
      <template #content>
        <ProgressBar
          :value="progresso.total ? Math.round((progresso.atual / progresso.total) * 100) : 0"
          :show-value="true"
        />
        <div class="progress-stats">
          {{ progresso.atual }}/{{ progresso.total }}
          — sucesso {{ progresso.sucesso }} / erros {{ progresso.erros }}
          <span v-if="progresso.runId"> — run {{ progresso.runId.slice(0, 8) }}…</span>
        </div>
        <div class="log">
          <div
            v-for="(item, idx) in progresso.log"
            :key="idx"
            :class="['log-line', item.tipo]"
          >
            <i :class="item.tipo === 'erro' ? 'pi pi-times-circle' : 'pi pi-check-circle'" />
            <span>{{ item.text }}</span>
          </div>
        </div>
      </template>
    </Card>

    <Dialog
      v-model:visible="dialogoTexto.visivel"
      :header="dialogoTexto.titulo"
      modal
      dismissable-mask
      :style="{ width: 'min(760px, 96vw)' }"
      :breakpoints="{ '960px': '96vw' }"
    >
      <div class="dialogo-texto-scroll">
        <pre class="texto-completo-pre">{{ dialogoTexto.corpo }}</pre>
      </div>
      <template #footer>
        <Button label="Fechar" severity="secondary" @click="dialogoTexto.visivel = false" />
      </template>
    </Dialog>
  </section>
</template>

<style scoped>
.juiz-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.mt-3 {
  margin-top: 0.5rem;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.kpi {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--p-content-border-color, #e5e7eb);
  background: var(--p-content-background, #fff);
  cursor: help;
  outline-offset: 2px;
}

.kpi-icon {
  flex-shrink: 0;
  font-size: 1.35rem;
  line-height: 1;
  margin-top: 0.1rem;
  color: var(--p-primary-color, #3b82f6);
  opacity: 0.85;
}

.kpi-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.kpi span {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  opacity: 0.65;
}

.kpi strong {
  font-size: 1.5rem;
  margin-top: 0.25rem;
}

.progress-stats {
  margin: 0.5rem 0 0.75rem;
  font-size: 0.9rem;
}

.log {
  max-height: 280px;
  overflow-y: auto;
  padding: 0.5rem;
  border: 1px solid var(--p-content-border-color, #e5e7eb);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, 'Cascadia Mono', monospace;
  font-size: 0.85rem;
}

.log-line {
  display: flex;
  gap: 0.5rem;
  padding: 0.15rem 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.log-line.erro {
  color: var(--p-red-500, #ef4444);
}

.log-line.ok {
  color: var(--p-green-600, #16a34a);
}

.mb-3 {
  margin-bottom: 0.75rem;
}

.correlacao-intro {
  font-size: 0.9rem;
  line-height: 1.45;
  color: var(--p-text-muted-color, #71717a);
  margin: 0;
}

.correlacao-intro code {
  font-size: 0.85em;
}

.correlacao-metricas {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: 0.75rem;
}

.correlacao-metrica {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--p-content-border-color, #e5e7eb);
  background: var(--p-content-background, #fff);
}

.correlacao-metrica-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  opacity: 0.65;
}

.correlacao-metrica strong {
  font-size: 1.25rem;
  font-weight: 600;
}

.correlacao-metrica-sub {
  font-size: 0.8rem;
  opacity: 0.75;
}

.correlacao-graficos-tabs {
  width: 100%;
  max-width: 58rem;
  margin-left: auto;
  margin-right: auto;
}

.correlacao-tab-panel-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding: 0.5rem 0.25rem 1rem;
  box-sizing: border-box;
}

.correlacao-tab-msg {
  width: 100%;
  max-width: 48rem;
}

.correlacao-legenda-sm {
  font-size: 0.85rem;
  color: var(--p-text-muted-color, #71717a);
  margin: 0;
  line-height: 1.4;
}

.correlacao-legenda-sm code {
  font-size: 0.82em;
}

.chart-scatter-wrap {
  width: 100%;
  max-width: min(52rem, 94vw);
  margin: 0 auto;
  min-height: 0;
  position: relative;
}

.conf-matrix-scroll {
  overflow-x: auto;
  width: 100%;
  max-width: 48rem;
  margin: 0 auto;
  display: flex;
  justify-content: center;
}

.conf-matrix-table {
  border-collapse: collapse;
  font-size: 1.05rem;
}

.conf-matrix-corner,
.conf-matrix-head,
.conf-matrix-rowhead,
.conf-matrix-cell {
  border: 1px solid var(--p-content-border-color, #e5e7eb);
  padding: 0.55rem 0.75rem;
  text-align: center;
}

.conf-matrix-corner {
  background: transparent;
  border-top: none;
  border-left: none;
}

.conf-matrix-head {
  font-weight: 600;
  background: var(--p-surface-ground, #f4f4f5);
}

.conf-matrix-rowhead {
  font-weight: 600;
  text-align: right;
  background: var(--p-surface-ground, #f4f4f5);
  white-space: nowrap;
}

.conf-matrix-cell {
  min-width: 4.5rem;
  padding: 0.7rem 0.95rem;
}

/* Filtros: quebra de linha dentro do Card (evita overflow do Toolbar) */
.filtros-wrap {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.filtros-campos {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.75rem;
  width: 100%;
  max-width: 100%;
}

.filtro-item {
  flex: 1 1 200px;
  min-width: min(100%, 12rem);
  max-width: 100%;
}

.filtro-item :deep(.p-multiselect),
.filtro-item :deep(.p-select),
.filtro-item :deep(.p-inputnumber) {
  width: 100%;
}

.filtro-limite {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 0 1 10rem;
  min-width: min(100%, 10rem);
}

.filtro-label {
  font-size: 0.75rem;
  font-weight: 600;
  opacity: 0.75;
}

.filtro-recarregar {
  flex: 0 0 auto;
  align-self: flex-end;
}

.filtros-acoes {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  width: 100%;
}

.filtros-acoes :deep(.p-button) {
  flex: 1 1 auto;
  min-width: min(100%, 12rem);
}

.tab-total-hint {
  font-size: 0.85rem;
  opacity: 0.8;
  margin: 0 0 0.75rem;
}

.juiz-pane {
  width: 100%;
}

.juiz-tab-filho {
  margin-top: 0.25rem;
}

/* Tema Aura estiliza .p-highlight; TabView usa .p-tabview-tablist-item-active. */
.juiz-tab-filho :deep(.p-tabview-tablist-item-active > .p-tabview-tab-header) {
  color: var(--p-primary-color);
}

.substituir-ux {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.substituir-label {
  font-size: 0.9rem;
  line-height: 1.4;
  cursor: pointer;
  user-select: none;
}

.celula-texto-clicavel {
  cursor: pointer;
  color: var(--p-primary-color, #2563eb);
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
  white-space: pre-wrap;
  word-break: break-word;
  display: inline-block;
  max-width: 100%;
}

.celula-texto-clicavel:hover {
  text-decoration-style: solid;
}

.dialogo-texto-scroll {
  max-height: min(60vh, 520px);
  overflow: auto;
  margin: 0;
  padding-right: 0.25rem;
}

.texto-completo-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0;
}
</style>
