const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch (_) {
      /* noop */
    }
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/health'),
  modelosJuiz: () => request('/modelos-juiz'),
  contagens: () => request('/juiz/contagens'),
  filtrosOpcoes: () => request('/juiz/filtros-opcoes'),
  pendentes: (params = {}) => {
    const q = new URLSearchParams()
    if (params.id_modelo_juiz?.length) {
      params.id_modelo_juiz.forEach((id) => q.append('id_modelo_juiz', id))
    }
    if (params.id_resposta?.length) {
      params.id_resposta.forEach((id) => q.append('id_resposta', id))
    }
    if (params.id_questao?.length) {
      params.id_questao.forEach((id) => q.append('id_questao', id))
    }
    if (params.modelo_candidato) q.set('modelo_candidato', params.modelo_candidato)
    q.set('offset', String(params.offset ?? 0))
    q.set('page_size', String(params.page_size ?? 25))
    return request(`/juiz/pendentes?${q.toString()}`)
  },
  avaliadas: (params = {}) => {
    const q = new URLSearchParams()
    if (params.id_modelo_juiz?.length) {
      params.id_modelo_juiz.forEach((id) => q.append('id_modelo_juiz', id))
    }
    if (params.id_resposta?.length) {
      params.id_resposta.forEach((id) => q.append('id_resposta', id))
    }
    if (params.id_questao?.length) {
      params.id_questao.forEach((id) => q.append('id_questao', id))
    }
    if (params.modelo_candidato) q.set('modelo_candidato', params.modelo_candidato)
    q.set('offset', String(params.offset ?? 0))
    q.set('page_size', String(params.page_size ?? 25))
    return request(`/juiz/avaliadas?${q.toString()}`)
  },
  executar: (payload) =>
    request('/juiz/executar', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  historicoAvaliacoes: (params = {}) => {
    const q = new URLSearchParams()
    q.set('offset', String(params.offset ?? 0))
    q.set('page_size', String(params.page_size ?? 25))
    if (params.id_questao?.length) {
      params.id_questao.forEach((id) => q.append('id_questao', id))
    }
    return request(`/juiz/avaliacoes-historico?${q.toString()}`)
  },
  correlacaoHumano: () => request('/juiz/correlacao-humano'),
}

export function openEventos(runId, { onTarefa, onStart, onDone, onError }) {
  const es = new EventSource(`${BASE}/juiz/eventos/${runId}`)
  if (onStart) es.addEventListener('start', (ev) => onStart(JSON.parse(ev.data)))
  if (onTarefa) es.addEventListener('tarefa', (ev) => onTarefa(JSON.parse(ev.data)))
  es.addEventListener('done', (ev) => {
    if (onDone) onDone(JSON.parse(ev.data))
    es.close()
  })
  es.onerror = (err) => {
    if (onError) onError(err)
    es.close()
  }
  return es
}
