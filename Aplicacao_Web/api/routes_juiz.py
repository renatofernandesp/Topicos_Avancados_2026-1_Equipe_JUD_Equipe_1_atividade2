"""Endpoints HTTP para listar pendentes, executar e acompanhar o juiz Gemini."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from analytics import correlacao_juiz_humano
from config import get_connection
from judge_gemini_service import (
    contar_respostas_incompletas,
    contar_tarefas_avaliadas_listagem,
    contar_tarefas_pendentes,
    contar_tarefas_pendentes_listagem,
    contar_tarefas_para_pares,
    listar_tarefas_avaliadas,
    listar_tarefas_pendentes,
    opcoes_filtros_juiz,
)

from .runner import drop_run, get_run, is_done_event, start_run
from .schemas import (
    AvaliacaoHistoricoOut,
    AvaliacoesHistoricoPaginaOut,
    ContagensOut,
    CorrelacaoJuizHumanoOut,
    ExecutarJuizIn,
    ExecutarJuizOut,
    HealthOut,
    ModeloJuizOut,
    OpcoesFiltroJuizOut,
    TarefaPendenteOut,
    TarefasPaginaOut,
)
from .sse import sse_format

router = APIRouter(prefix="/api", tags=["juiz"])


def _historico_sql_fragment_id_questao(id_questao: list[int] | None) -> tuple[str, list[Any]]:
    """Filtro por `perguntas.id_questao` (via resposta da avaliação), sem alterar a view."""
    if not id_questao:
        return "", []
    return (
        """
        WHERE EXISTS (
            SELECT 1
            FROM avaliacoes_juiz aj_f
            JOIN respostas_atividade_1 r_f ON r_f.id_resposta = aj_f.id_resposta_ativa1
            JOIN perguntas p_f ON p_f.id_pergunta = r_f.id_pergunta
            WHERE aj_f.id_avaliacao = v.id_avaliacao
              AND p_f.id_questao = ANY(%s)
        )
        """,
        [list(id_questao)],
    )


def _preview(text: str | None, n: int = 140) -> str:
    if not text:
        return ""
    text = text.strip().replace("\r", " ").replace("\n", " ")
    return text if len(text) <= n else text[:n].rstrip() + "..."


def _texto_completo_api(val: Any) -> str:
    """Garante string UTF-8 para JSON (evita bytes / None inesperados)."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def _tarefas_rows_to_out(rows: list[dict[str, Any]]) -> list[TarefaPendenteOut]:
    return [
        TarefaPendenteOut(
            id_resposta=p["id_resposta"],
            id_modelo_juiz=p["id_modelo_juiz"],
            id_api_juiz=p["id_api_juiz"],
            nome_modelo=p["nome_modelo"],
            versao=p.get("versao"),
            parametro_precisao=p.get("parametro_precisao"),
            enunciado_preview=_preview(p["enunciado"]),
            resposta_preview=_preview(p.get("texto_resposta"), n=280),
            enunciado_completo=_texto_completo_api(p.get("enunciado")),
            texto_resposta_completo=_texto_completo_api(p.get("texto_resposta")),
        )
        for p in rows
    ]


@router.get("/juiz/filtros-opcoes", response_model=OpcoesFiltroJuizOut)
def juiz_filtros_opcoes() -> OpcoesFiltroJuizOut:
    opts = opcoes_filtros_juiz()
    return OpcoesFiltroJuizOut(modelos_candidatos=opts["modelos_candidatos"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(ok=True, has_gemini_key=bool(os.getenv("GEMINI_API_KEY")))


@router.get("/modelos-juiz", response_model=list[ModeloJuizOut])
def modelos_juiz() -> list[ModeloJuizOut]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_modelo_juiz, nome_exibicao, id_api, provedor, ativo "
                "FROM modelos_juiz ORDER BY id_modelo_juiz"
            )
            rows = cur.fetchall()
    return [
        ModeloJuizOut(
            id_modelo_juiz=r[0],
            nome_exibicao=r[1],
            id_api=r[2],
            provedor=r[3],
            ativo=bool(r[4]),
        )
        for r in rows
    ]


@router.get("/juiz/contagens", response_model=ContagensOut)
def contagens() -> ContagensOut:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM perguntas")
            perguntas = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM respostas_atividade_1")
            respostas = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM avaliacoes_juiz")
            avaliacoes = cur.fetchone()[0]
    return ContagensOut(
        perguntas=perguntas,
        respostas=respostas,
        avaliacoes=avaliacoes,
        tarefas_juiz_pendentes=contar_tarefas_pendentes(),
        respostas_gemini_pendentes=contar_respostas_incompletas(),
    )


@router.get("/juiz/correlacao-humano", response_model=CorrelacaoJuizHumanoOut)
def juiz_correlacao_humano() -> CorrelacaoJuizHumanoOut:
    return CorrelacaoJuizHumanoOut(**correlacao_juiz_humano())


@router.get("/juiz/pendentes", response_model=TarefasPaginaOut)
def juiz_pendentes(
    id_modelo_juiz: list[int] | None = Query(default=None),
    id_resposta: list[int] | None = Query(default=None),
    id_questao: list[int] | None = Query(default=None),
    modelo_candidato: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0, le=10_000_000),
    page_size: int = Query(default=25, ge=1, le=500),
) -> TarefasPaginaOut:
    total = contar_tarefas_pendentes_listagem(
        ids_resposta=id_resposta,
        ids_modelo_juiz=id_modelo_juiz,
        ids_questao=id_questao,
        nome_modelo_candidato=modelo_candidato,
    )
    rows = listar_tarefas_pendentes(
        ids_resposta=id_resposta,
        ids_modelo_juiz=id_modelo_juiz,
        ids_questao=id_questao,
        limite=page_size,
        offset=offset,
        nome_modelo_candidato=modelo_candidato,
    )
    return TarefasPaginaOut(total=total, items=_tarefas_rows_to_out(rows))


@router.get("/juiz/avaliadas", response_model=TarefasPaginaOut)
def juiz_avaliadas(
    id_modelo_juiz: list[int] | None = Query(default=None),
    id_resposta: list[int] | None = Query(default=None),
    id_questao: list[int] | None = Query(default=None),
    modelo_candidato: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0, le=10_000_000),
    page_size: int = Query(default=25, ge=1, le=500),
) -> TarefasPaginaOut:
    total = contar_tarefas_avaliadas_listagem(
        ids_resposta=id_resposta,
        ids_modelo_juiz=id_modelo_juiz,
        ids_questao=id_questao,
        nome_modelo_candidato=modelo_candidato,
    )
    rows = listar_tarefas_avaliadas(
        ids_resposta=id_resposta,
        ids_modelo_juiz=id_modelo_juiz,
        ids_questao=id_questao,
        limite=page_size,
        offset=offset,
        nome_modelo_candidato=modelo_candidato,
    )
    return TarefasPaginaOut(total=total, items=_tarefas_rows_to_out(rows))


@router.post("/juiz/executar", response_model=ExecutarJuizOut)
async def juiz_executar(payload: ExecutarJuizIn) -> ExecutarJuizOut:
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY não definida.")

    if payload.substituir:
        if not payload.pares:
            raise HTTPException(
                status_code=400,
                detail="substituir=true exige lista 'pares' não vazia.",
            )
        tuplas = [(p.id_resposta, p.id_modelo_juiz) for p in payload.pares]
        ativos = await asyncio.to_thread(_ids_juizes_ativos)
        for r, j in tuplas:
            if j not in ativos:
                raise HTTPException(
                    status_code=400,
                    detail=f"id_modelo_juiz inativo ou inexistente: {j}",
                )
        total_estimado = await asyncio.to_thread(contar_tarefas_para_pares, tuplas)
        if total_estimado == 0:
            raise HTTPException(
                status_code=400,
                detail="Nenhuma tarefa encontrada para os pares indicados.",
            )
        run = start_run(
            total_estimado=total_estimado,
            ids_resposta=None,
            ids_modelo_juiz=None,
            limite=None,
            substituir=True,
            pares=tuplas,
        )
        return ExecutarJuizOut(run_id=run.run_id, total_estimado=total_estimado)

    total_estimado = await asyncio.to_thread(
        contar_tarefas_pendentes,
        ids_resposta=payload.ids_resposta,
        ids_modelo_juiz=payload.ids_modelo_juiz,
        limite=payload.limite,
    )
    if total_estimado == 0:
        raise HTTPException(status_code=400, detail="Nenhuma tarefa pendente para o filtro.")

    run = start_run(
        total_estimado=total_estimado,
        ids_resposta=payload.ids_resposta,
        ids_modelo_juiz=payload.ids_modelo_juiz,
        limite=payload.limite,
        substituir=False,
        pares=None,
    )
    return ExecutarJuizOut(run_id=run.run_id, total_estimado=total_estimado)


def _ids_juizes_ativos() -> set[int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_modelo_juiz FROM modelos_juiz WHERE ativo = TRUE"
            )
            return {int(r[0]) for r in cur.fetchall()}


@router.get("/juiz/eventos/{run_id}")
async def juiz_eventos(run_id: str) -> StreamingResponse:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id desconhecido.")

    async def gen():
        try:
            yield sse_format({"run_id": run_id, "total_estimado": run.total_estimado},
                             event="start")
            while True:
                try:
                    ev = await asyncio.wait_for(run.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if is_done_event(ev):
                    yield sse_format({"run_id": run_id}, event="done")
                    break
                payload: dict[str, Any] = dict(ev)
                payload["run_id"] = run_id
                yield sse_format(payload, event="tarefa")
        finally:
            drop_run(run_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/juiz/avaliacoes-historico", response_model=AvaliacoesHistoricoPaginaOut)
def juiz_avaliacoes_historico(
    offset: int = Query(default=0, ge=0, le=10_000_000),
    page_size: int = Query(default=25, ge=1, le=500),
    id_questao: list[int] | None = Query(default=None),
) -> AvaliacoesHistoricoPaginaOut:
    frag, frag_params = _historico_sql_fragment_id_questao(id_questao)
    count_sql = f"SELECT COUNT(*)::bigint FROM vw_avaliacoes_completas v{frag}"
    select_sql = f"""
                SELECT
                    v.id_avaliacao,
                    v.modelo_candidato,
                    v.modelo_juiz,
                    v.enunciado,
                    v.nota_atribuida,
                    v.nota_humana,
                    v.chain_of_thought
                FROM vw_avaliacoes_completas v
                {frag}
                ORDER BY v.data_avaliacao DESC NULLS LAST, v.id_avaliacao DESC
                LIMIT %s OFFSET %s
                """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(count_sql, tuple(frag_params) if frag_params else None)
            total = int(cur.fetchone()[0] or 0)
            sel_params = tuple(frag_params) + (page_size, offset) if frag_params else (page_size, offset)
            cur.execute(select_sql, sel_params)
            rows = cur.fetchall()
    items = [
        AvaliacaoHistoricoOut(
            id_avaliacao=r[0],
            modelo_candidato=r[1],
            modelo_juiz=r[2],
            enunciado_preview=_preview(r[3]),
            enunciado_completo=_texto_completo_api(r[3]),
            nota_atribuida=float(r[4]) if r[4] is not None else None,
            nota_humana=int(r[5]) if r[5] is not None else None,
            chain_of_thought_preview=_preview(r[6], n=180),
            chain_of_thought_completo=_texto_completo_api(r[6]),
        )
        for r in rows
    ]
    return AvaliacoesHistoricoPaginaOut(total=total, items=items)
