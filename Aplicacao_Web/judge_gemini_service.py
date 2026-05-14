"""
Juiz multi-modelo (Google Gemini) com saída estruturada, BERTScore e rubrica.

Variáveis de ambiente:
  GEMINI_API_KEY — obrigatória para chamar a API.
  JUDGE_MAX_WORKERS — paralelismo (default 20).
  SKIP_BERT — se 1/true, não calcula BERTScore (bert_score_f1 fica NULL).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterator

from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from config import get_connection
from rubrica import PESOS, CRITERIOS, calcular_nota_final

_tls = threading.local()
logger = logging.getLogger(__name__)


def _client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Defina GEMINI_API_KEY no ambiente.")
    if not hasattr(_tls, "client"):
        _tls.client = genai.Client(api_key=key)
    return _tls.client


class CriterioAvaliacao(BaseModel):
    """Sub-nota de um critério (tolerante a JSON do Gemini: floats, espaços)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    nota: int = Field(ge=1, le=5)
    justificativa: str = Field(min_length=1)

    @field_validator("nota", mode="before")
    @classmethod
    def _coerce_nota(cls, v: Any) -> int:
        if isinstance(v, bool):
            raise ValueError("nota não pode ser booleano")
        if isinstance(v, float):
            if abs(v - round(v)) > 1e-6:
                raise ValueError(f"nota fracionária inválida: {v}")
            return int(round(v))
        if isinstance(v, str):
            s = v.strip().replace(",", ".")
            try:
                fv = float(s)
                if abs(fv - round(fv)) > 1e-6:
                    raise ValueError(f"nota não inteira: {v!r}")
                return int(round(fv))
            except ValueError:
                pass
        return v  # type: ignore[return-value]

    @field_validator("justificativa", mode="before")
    @classmethod
    def _strip_justificativa(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()


class JudgeGeminiOutput(BaseModel):
    """Resposta estruturada do juiz Gemini."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    correcao_factual: CriterioAvaliacao
    completude: CriterioAvaliacao
    clareza: CriterioAvaliacao
    coerencia: CriterioAvaliacao
    relevancia: CriterioAvaliacao
    chain_of_thought: str = Field(min_length=1)

    @field_validator("chain_of_thought", mode="before")
    @classmethod
    def _strip_cot(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()


SYSTEM_INSTRUCTION = """[PERSONA]
Você é um Ministro do Supremo Tribunal Federal e Professor Doutor em Direito. Sua análise é técnica, erudita e implacável com erros normativos.

[AÇÃO E REGRAS DE RIGOR]
1. Rigor Igualitário: Mantenha o mesmo nível de exigência para todos os modelos candidatos.
2. Superação do Gabarito: Se a resposta do candidato superar o gabarito em atualização jurídica ou clareza, registre no raciocínio e mantenha nota alta nos critérios pertinentes.
3. Alucinação: Se o candidato citar leis, artigos ou súmulas inexistentes, atribua nota 1 em correcao_factual e explique em chain_of_thought.
4. Avalie em 5 critérios independentes (nota 1–5 e justificativa cada). A nota final será calculada no servidor; seja consistente.

[LIMITES DE TAMANHO — OBRIGATÓRIOS]
- Cada "justificativa" deve ter no máximo 3 frases curtas e objetivas (idealmente até 280 caracteres).
- "chain_of_thought" deve ter no máximo 8 linhas (até ~900 caracteres no total).
- Não inclua citações longas, listas extensas, repetições ou trechos do gabarito.
- A resposta inteira deve caber em um JSON enxuto; PRIORIZE concisão sobre exaustividade.

Critérios e pesos (referência — não inclua pesos no JSON):
- correcao_factual: alinhamento com fatos e gabarito (30%%)
- completude: cobre pontos relevantes (25%%)
- clareza: linguagem precisa (20%%)
- coerencia: argumentação lógica (15%%)
- relevancia: responde ao perguntado (10%%)
"""


def _user_prompt(
    *,
    nome_modelo: str,
    versao: str | None,
    parametro_precisao: str | None,
    nome_dataset: str,
    dominio: str,
    enunciado: str,
    resposta_ouro: str,
    texto_resposta: str,
) -> str:
    return f"""[CONTEXTO DO MODELO CANDIDATO]
Nome: {nome_modelo} (Versão: {versao or "—"})
Parâmetros de Execução: {parametro_precisao or "—"}
Dataset: {nome_dataset} (Domínio: {dominio})

[ENTRADAS]
ENUNCIADO:
{enunciado}

RESPOSTA OURO (Gabarito):
{resposta_ouro}

RESPOSTA DA IA CANDIDATA:
{texto_resposta}

Preencha o JSON conforme o schema (5 critérios + chain_of_thought)."""


def _parse_response(response: Any) -> dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if hasattr(parsed, "model_dump"):
            return parsed.model_dump()
        return dict(parsed)
    text = getattr(response, "text", None) or ""
    if not text.strip():
        raise ValueError("Resposta vazia do modelo.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(
            "JSON inválido na resposta do Gemini (primeiros 800 chars): %r",
            text[:800],
        )
        raise ValueError(f"JSON inválido do modelo: {e}") from e


class JudgeTruncatedError(RuntimeError):
    """Resposta do Gemini truncada por MAX_TOKENS (não vale a pena retry sem aumentar)."""


def _finish_reason(response: Any) -> str | None:
    try:
        cand = response.candidates[0]
        fr = getattr(cand, "finish_reason", None)
        if fr is None:
            return None
        name = getattr(fr, "name", None)
        return name or str(fr)
    except Exception:
        return None


def _chamar_gemini(
    *,
    id_api: str,
    user_text: str,
    max_retries: int = 4,
) -> tuple[dict[str, Any], int | None, int | None]:
    client = _client()
    max_output_tokens = int(os.getenv("JUDGE_MAX_OUTPUT_TOKENS", "8192"))
    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=max_output_tokens,
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=JudgeGeminiOutput,
    )
    last_err: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=id_api,
                contents=user_text,
                config=config,
            )
            finish_reason = _finish_reason(response)
            if finish_reason and "MAX_TOKENS" in finish_reason.upper():
                raise JudgeTruncatedError(
                    f"Resposta truncada por MAX_TOKENS (modelo={id_api}, "
                    f"limite={max_output_tokens}). Aumente JUDGE_MAX_OUTPUT_TOKENS."
                )
            raw = _parse_response(response)
            try:
                validated = JudgeGeminiOutput.model_validate(raw)
            except ValidationError as ve:
                logger.warning(
                    "Validação Pydantic falhou (modelo=%s): erros=%s raw_keys=%s",
                    id_api,
                    ve.errors(),
                    list(raw.keys()) if isinstance(raw, dict) else type(raw),
                )
                raise
            data = validated.model_dump()
            tok_p = tok_c = None
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                tok_p = getattr(usage, "prompt_token_count", None)
                tok_c = getattr(usage, "candidates_token_count", None)
                if tok_p is None:
                    tok_p = getattr(usage, "prompt_tokens", None)
                if tok_c is None:
                    tok_c = getattr(usage, "candidates_tokens", None)
            return data, tok_p, tok_c
        except JudgeTruncatedError as e:
            logger.error("Truncamento confirmado (modelo=%s): %s", id_api, e)
            raise
        except Exception as e:
            last_err = e
            logger.warning(
                "Chamada Gemini falhou (modelo=%s, tentativa=%s/%s): %s: %s",
                id_api,
                tentativa,
                max_retries,
                type(e).__name__,
                e,
                exc_info=tentativa == max_retries,
            )
            if tentativa == max_retries:
                break
            time.sleep(min(2 ** tentativa, 30))
    assert last_err is not None
    raise last_err


def _compute_bert_f1(candidato: str, referencia: str) -> float | None:
    if os.getenv("SKIP_BERT", "").lower() in ("1", "true", "yes"):
        return None
    try:
        from bert_score import score as bert_score_fn
    except ImportError as e:
        raise RuntimeError("Instale bert-score e torch (requirements.txt).") from e
    cands = [candidato if candidato else " "]
    refs = [referencia if referencia else " "]
    _p, _r, f1 = bert_score_fn(
        cands,
        refs,
        model_type="bert-base-multilingual-cased",
        verbose=False,
    )
    return float(f1[0])


_QUERY_TAREFAS_BASE = """
SELECT
    r.id_resposta,
    mj.id_modelo_juiz,
    mj.id_api,
    p.enunciado,
    p.resposta_ouro,
    r.texto_resposta,
    mc.nome_modelo,
    mc.versao,
    mc.parametro_precisao,
    d.nome_dataset,
    d.dominio
FROM respostas_atividade_1 r
JOIN perguntas p ON p.id_pergunta = r.id_pergunta
JOIN datasets d ON d.id_dataset = p.id_dataset
JOIN modelos mc ON mc.id_modelo = r.id_modelo
CROSS JOIN modelos_juiz mj
WHERE mj.ativo = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM avaliacoes_juiz aj
    WHERE aj.id_resposta_ativa1 = r.id_resposta
      AND aj.id_modelo_juiz = mj.id_modelo_juiz
  )
"""

_QUERY_TAREFAS_ORDER = "ORDER BY r.id_resposta, mj.id_modelo_juiz"


def _append_filtros_listagem_pendentes(
    sql: str,
    params: list[Any],
    *,
    ids_resposta: list[int] | None,
    ids_modelo_juiz: list[int] | None,
    ids_questao: list[int] | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> tuple[str, list[Any]]:
    if ids_resposta:
        sql += " AND r.id_resposta = ANY(%s)"
        params.append(list(ids_resposta))
    if ids_modelo_juiz:
        sql += " AND mj.id_modelo_juiz = ANY(%s)"
        params.append(list(ids_modelo_juiz))
    if ids_questao:
        sql += " AND p.id_questao = ANY(%s)"
        params.append(list(ids_questao))
    if nome_dataset:
        sql += " AND d.nome_dataset = %s"
        params.append(nome_dataset)
    if nome_modelo_candidato:
        sql += " AND mc.nome_modelo = %s"
        params.append(nome_modelo_candidato)
    return sql, params


def _build_tarefas_sql(
    *,
    ids_resposta: list[int] | None,
    ids_modelo_juiz: list[int] | None,
    ids_questao: list[int] | None = None,
    limite: int | None,
    offset: int | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> tuple[str, list[Any]]:
    sql = _QUERY_TAREFAS_BASE
    params: list[Any] = []
    sql, params = _append_filtros_listagem_pendentes(
        sql,
        params,
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    sql += " " + _QUERY_TAREFAS_ORDER
    off = int(offset or 0)
    if limite is not None and limite > 0:
        sql += " LIMIT %s"
        params.append(int(limite))
        if off > 0:
            sql += " OFFSET %s"
            params.append(off)
    elif off > 0:
        sql += " OFFSET %s"
        params.append(off)
    return sql, params


# Mantido por compatibilidade com chamadores externos.
QUERY_TAREFAS = _QUERY_TAREFAS_BASE + " " + _QUERY_TAREFAS_ORDER


def _carregar_tarefas(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    ids_questao: list[int] | None = None,
    limite: int | None = None,
    offset: int | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> list[tuple[Any, ...]]:
    sql, params = _build_tarefas_sql(
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        limite=limite,
        offset=offset,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params if params else None)
            return cur.fetchall()


def contar_tarefas_pendentes_listagem(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    ids_questao: list[int] | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> int:
    """Total de pares pendentes com os mesmos filtros da listagem (sem LIMIT)."""
    sql = f"SELECT COUNT(*)::bigint FROM ({_QUERY_TAREFAS_BASE}"
    params: list[Any] = []
    sql, params = _append_filtros_listagem_pendentes(
        sql,
        params,
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    sql += ") _cnt"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params if params else None)
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


def listar_tarefas_pendentes(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    ids_questao: list[int] | None = None,
    limite: int | None = None,
    offset: int | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> list[dict[str, Any]]:
    """Mesmas tarefas que o stream usaria, em formato de dicionário (para a API)."""
    rows = _carregar_tarefas(
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        limite=limite,
        offset=offset,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    return [_row_tarefa_dict(row) for row in rows]


def opcoes_filtros_juiz() -> dict[str, list[str]]:
    """Listas para dropdowns (sem depender da página carregada)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome_modelo FROM modelos ORDER BY nome_modelo")
            modelos = [str(r[0]) for r in cur.fetchall() if r[0] is not None]
    return {"modelos_candidatos": modelos}


def _row_tarefa_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id_resposta": row[0],
        "id_modelo_juiz": row[1],
        "id_api_juiz": row[2],
        "enunciado": row[3],
        "resposta_ouro": row[4],
        "texto_resposta": row[5],
        "nome_modelo": row[6],
        "versao": row[7],
        "parametro_precisao": row[8],
        "nome_dataset": row[9],
        "dominio": row[10],
    }


def _dedupe_pares(pares: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return list(dict.fromkeys(pares))


def _pares_para_arrays(pares: list[tuple[int, int]]) -> tuple[list[int], list[int]]:
    rs = [p[0] for p in pares]
    js = [p[1] for p in pares]
    return rs, js


def _preservar_notas_humanas(id_respostas: list[int]) -> dict[int, int]:
    """Uma nota humana por id_resposta (replica-se a todas as linhas de juiz)."""
    if not id_respostas:
        return {}
    uniq = list(dict.fromkeys(id_respostas))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (id_resposta_ativa1)
                    id_resposta_ativa1, nota_humana
                FROM avaliacoes_juiz
                WHERE id_resposta_ativa1 = ANY(%s)
                  AND nota_humana IS NOT NULL
                ORDER BY id_resposta_ativa1, id_avaliacao
                """,
                (uniq,),
            )
            rows = cur.fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _restaurar_notas_humanas(mapa: dict[int, int]) -> None:
    if not mapa:
        return
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                for rid, nh in mapa.items():
                    cur.execute(
                        """
                        UPDATE avaliacoes_juiz
                        SET nota_humana = %s
                        WHERE id_resposta_ativa1 = %s
                        """,
                        (nh, rid),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Falha ao restaurar nota_humana para respostas %s", list(mapa))


def apagar_avaliacoes_para_pares(pares: list[tuple[int, int]]) -> None:
    """Remove rubrica e avaliações para os pares (resposta, juiz). Ordem respeita FK."""
    pares = _dedupe_pares(pares)
    if not pares:
        return
    rs, js = _pares_para_arrays(pares)
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM rubrica_subcriterios rs
                    USING avaliacoes_juiz aj,
                          unnest(%s::int[], %s::int[]) AS t(id_resposta, id_modelo_juiz)
                    WHERE rs.id_avaliacao = aj.id_avaliacao
                      AND aj.id_resposta_ativa1 = t.id_resposta
                      AND aj.id_modelo_juiz = t.id_modelo_juiz
                    """,
                    (rs, js),
                )
                cur.execute(
                    """
                    DELETE FROM avaliacoes_juiz aj
                    USING unnest(%s::int[], %s::int[]) AS t(id_resposta, id_modelo_juiz)
                    WHERE aj.id_resposta_ativa1 = t.id_resposta
                      AND aj.id_modelo_juiz = t.id_modelo_juiz
                    """,
                    (rs, js),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Falha ao apagar avaliações para pares")
            raise


_QUERY_TAREFAS_POR_PARES = """
SELECT
    r.id_resposta,
    mj.id_modelo_juiz,
    mj.id_api,
    p.enunciado,
    p.resposta_ouro,
    r.texto_resposta,
    mc.nome_modelo,
    mc.versao,
    mc.parametro_precisao,
    d.nome_dataset,
    d.dominio
FROM respostas_atividade_1 r
JOIN perguntas p ON p.id_pergunta = r.id_pergunta
JOIN datasets d ON d.id_dataset = p.id_dataset
JOIN modelos mc ON mc.id_modelo = r.id_modelo
CROSS JOIN modelos_juiz mj
WHERE mj.ativo = TRUE
  AND (r.id_resposta, mj.id_modelo_juiz) IN (
    SELECT x.id_resposta, x.id_modelo_juiz
    FROM unnest(%s::int[], %s::int[]) AS x(id_resposta, id_modelo_juiz)
  )
"""


def _carregar_tarefas_por_pares(pares: list[tuple[int, int]]) -> list[tuple[Any, ...]]:
    pares = _dedupe_pares(pares)
    if not pares:
        return []
    rs, js = _pares_para_arrays(pares)
    sql = _QUERY_TAREFAS_POR_PARES + " " + _QUERY_TAREFAS_ORDER
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (rs, js))
            return cur.fetchall()


_QUERY_TAREFAS_AVALIADAS_BASE = """
SELECT
    r.id_resposta,
    mj.id_modelo_juiz,
    mj.id_api,
    p.enunciado,
    p.resposta_ouro,
    r.texto_resposta,
    mc.nome_modelo,
    mc.versao,
    mc.parametro_precisao,
    d.nome_dataset,
    d.dominio
FROM respostas_atividade_1 r
JOIN perguntas p ON p.id_pergunta = r.id_pergunta
JOIN datasets d ON d.id_dataset = p.id_dataset
JOIN modelos mc ON mc.id_modelo = r.id_modelo
CROSS JOIN modelos_juiz mj
WHERE mj.ativo = TRUE
  AND EXISTS (
    SELECT 1 FROM avaliacoes_juiz aj
    WHERE aj.id_resposta_ativa1 = r.id_resposta
      AND aj.id_modelo_juiz = mj.id_modelo_juiz
  )
"""


def _build_tarefas_avaliadas_sql(
    *,
    ids_resposta: list[int] | None,
    ids_modelo_juiz: list[int] | None,
    ids_questao: list[int] | None = None,
    limite: int | None,
    offset: int | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> tuple[str, list[Any]]:
    sql = _QUERY_TAREFAS_AVALIADAS_BASE
    params: list[Any] = []
    sql, params = _append_filtros_listagem_pendentes(
        sql,
        params,
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    sql += " " + _QUERY_TAREFAS_ORDER
    off = int(offset or 0)
    if limite is not None and limite > 0:
        sql += " LIMIT %s"
        params.append(int(limite))
        if off > 0:
            sql += " OFFSET %s"
            params.append(off)
    elif off > 0:
        sql += " OFFSET %s"
        params.append(off)
    return sql, params


def _carregar_tarefas_avaliadas(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    ids_questao: list[int] | None = None,
    limite: int | None = None,
    offset: int | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> list[tuple[Any, ...]]:
    sql, params = _build_tarefas_avaliadas_sql(
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        limite=limite,
        offset=offset,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params if params else None)
            return cur.fetchall()


def contar_tarefas_avaliadas_listagem(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    ids_questao: list[int] | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> int:
    sql = f"SELECT COUNT(*)::bigint FROM ({_QUERY_TAREFAS_AVALIADAS_BASE}"
    params: list[Any] = []
    sql, params = _append_filtros_listagem_pendentes(
        sql,
        params,
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    sql += ") _cnt"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params if params else None)
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


def listar_tarefas_avaliadas(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    ids_questao: list[int] | None = None,
    limite: int | None = None,
    offset: int | None = None,
    nome_dataset: str | None = None,
    nome_modelo_candidato: str | None = None,
) -> list[dict[str, Any]]:
    rows = _carregar_tarefas_avaliadas(
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        ids_questao=ids_questao,
        limite=limite,
        offset=offset,
        nome_dataset=nome_dataset,
        nome_modelo_candidato=nome_modelo_candidato,
    )
    return [_row_tarefa_dict(row) for row in rows]


def contar_tarefas_para_pares(pares: list[tuple[int, int]]) -> int:
    return len(_carregar_tarefas_por_pares(pares))


def _bert_por_resposta(tarefas: list[tuple[Any, ...]]) -> dict[int, float | None]:
    por_id: dict[int, tuple[str, str]] = {}
    for row in tarefas:
        rid = row[0]
        ouro = row[4]
        texto = row[5]
        por_id[rid] = (ouro, texto)
    out: dict[int, float | None] = {}
    for rid, (ouro, texto) in por_id.items():
        out[rid] = _compute_bert_f1(texto, ouro)
    return out


def _persistir_avaliacao(
    *,
    id_resposta: int,
    id_modelo_juiz: int,
    resultado: dict[str, Any],
    nota_final: float,
    bert_f1: float | None,
    tok_p: int | None,
    tok_c: int | None,
) -> bool:
    """Insere avaliação + rubrica. Retorna True se inseriu nova linha."""
    cot = resultado["chain_of_thought"]
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO avaliacoes_juiz
                           (id_resposta_ativa1, id_modelo_juiz, nota_atribuida,
                            chain_of_thought, bert_score_f1, tokens_prompt, tokens_completion)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id_resposta_ativa1, id_modelo_juiz) DO NOTHING
                       RETURNING id_avaliacao""",
                    (id_resposta, id_modelo_juiz, nota_final, cot, bert_f1, tok_p, tok_c),
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return False
                id_avaliacao = row[0]
                for criterio, peso in PESOS.items():
                    cur.execute(
                        """INSERT INTO rubrica_subcriterios
                               (id_avaliacao, criterio, nota_criterio, justificativa, peso)
                           VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT (id_avaliacao, criterio) DO NOTHING""",
                        (
                            id_avaliacao,
                            criterio,
                            resultado[criterio]["nota"],
                            resultado[criterio]["justificativa"],
                            peso,
                        ),
                    )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            logger.exception(
                "Falha ao persistir avaliação id_resposta=%s id_modelo_juiz=%s",
                id_resposta,
                id_modelo_juiz,
            )
            raise


def _processar_tarefa(
    row: tuple[Any, ...],
    bert_map: dict[int, float | None],
) -> dict[str, Any]:
    (
        id_resposta,
        id_modelo_juiz,
        id_api,
        enunciado,
        resposta_ouro,
        texto_resposta,
        nome_modelo,
        versao,
        parametro_precisao,
        nome_dataset,
        dominio,
    ) = row
    user = _user_prompt(
        nome_modelo=nome_modelo,
        versao=versao,
        parametro_precisao=parametro_precisao,
        nome_dataset=nome_dataset,
        dominio=dominio,
        enunciado=enunciado,
        resposta_ouro=resposta_ouro,
        texto_resposta=texto_resposta,
    )
    resultado, tok_p, tok_c = _chamar_gemini(id_api=id_api, user_text=user)
    nota_final = calcular_nota_final(resultado)
    bert_f1 = bert_map.get(id_resposta)
    _persistir_avaliacao(
        id_resposta=id_resposta,
        id_modelo_juiz=id_modelo_juiz,
        resultado=resultado,
        nota_final=nota_final,
        bert_f1=bert_f1,
        tok_p=tok_p,
        tok_c=tok_c,
    )
    return {
        "id": id_resposta,
        "juiz": id_api,
        "nota": nota_final,
        "subcrit": {c: resultado[c]["nota"] for c in CRITERIOS},
    }


def executar_juiz_gemini(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    limite: int | None = None,
    substituir: bool = False,
    pares: list[tuple[int, int]] | None = None,
) -> None:
    for _ in executar_juiz_gemini_stream(
        ids_resposta=ids_resposta,
        ids_modelo_juiz=ids_modelo_juiz,
        limite=limite,
        substituir=substituir,
        pares=pares,
    ):
        pass


def executar_juiz_gemini_stream(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    limite: int | None = None,
    substituir: bool = False,
    pares: list[tuple[int, int]] | None = None,
) -> Iterator[dict[str, Any]]:
    if not os.getenv("GEMINI_API_KEY"):
        yield {
            "total": 1,
            "atual": 1,
            "id": None,
            "juiz": None,
            "nota": None,
            "erro": "GEMINI_API_KEY não definida no ambiente.",
            "subcrit": {},
        }
        return

    mapa_humano: dict[int, int] = {}
    tarefas: list[tuple[Any, ...]] = []

    try:
        if substituir:
            if not pares:
                yield {
                    "total": 1,
                    "atual": 1,
                    "id": None,
                    "juiz": None,
                    "nota": None,
                    "erro": "substituir=True exige lista de pares (id_resposta, id_modelo_juiz) não vazia.",
                    "subcrit": {},
                }
                return
            pares_dedup = _dedupe_pares(pares)
            tarefas = _carregar_tarefas_por_pares(pares_dedup)
            if not tarefas:
                yield {
                    "total": 1,
                    "atual": 1,
                    "id": None,
                    "juiz": None,
                    "nota": None,
                    "erro": "Nenhuma tarefa encontrada para os pares indicados (resposta ou juiz inválido?).",
                    "subcrit": {},
                }
                return
            respostas_afetadas = list({row[0] for row in tarefas})
            mapa_humano = _preservar_notas_humanas(respostas_afetadas)
            apagar_avaliacoes_para_pares(pares_dedup)
        else:
            tarefas = _carregar_tarefas(
                ids_resposta=ids_resposta,
                ids_modelo_juiz=ids_modelo_juiz,
                limite=limite,
            )
        if not tarefas:
            yield {
                "total": 0,
                "atual": 0,
                "id": None,
                "juiz": None,
                "nota": None,
                "erro": None,
                "subcrit": {},
            }
            return

        workers = max(1, int(os.getenv("JUDGE_MAX_WORKERS", "20")))
        bert_map = _bert_por_resposta(tarefas)
        total = len(tarefas)
        atual = 0
        _ = _client()

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_processar_tarefa, row, bert_map): row for row in tarefas}
            for fut in as_completed(futures):
                atual += 1
                row = futures[fut]
                id_resposta = row[0]
                id_api = row[2]
                try:
                    info = fut.result()
                    yield {
                        "total": total,
                        "atual": atual,
                        "id": info["id"],
                        "juiz": info["juiz"],
                        "nota": info["nota"],
                        "erro": None,
                        "subcrit": info["subcrit"],
                    }
                except Exception as e:
                    tb = traceback.format_exc()
                    logger.exception(
                        "Tarefa falhou id_resposta=%s juiz=%s",
                        id_resposta,
                        id_api,
                    )
                    yield {
                        "total": total,
                        "atual": atual,
                        "id": id_resposta,
                        "juiz": id_api,
                        "nota": None,
                        "erro": str(e),
                        "erro_tipo": type(e).__name__,
                        "erro_detalhe": tb[:4000] if os.getenv("JUDGE_SSE_TRACEBACK", "").lower() in ("1", "true", "yes") else None,
                        "subcrit": {},
                    }
    finally:
        if mapa_humano:
            _restaurar_notas_humanas(mapa_humano)


def contar_tarefas_pendentes(
    *,
    ids_resposta: list[int] | None = None,
    ids_modelo_juiz: list[int] | None = None,
    limite: int | None = None,
) -> int:
    return len(
        _carregar_tarefas(
            ids_resposta=ids_resposta,
            ids_modelo_juiz=ids_modelo_juiz,
            limite=limite,
        )
    )


def contar_respostas_incompletas() -> int:
    """Quantidade de id_resposta distintos que ainda não têm os N juízes ativos."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ativos AS (
                    SELECT COUNT(*)::INT AS n FROM modelos_juiz WHERE ativo = TRUE
                ),
                por_resposta AS (
                    SELECT r.id_resposta, COUNT(DISTINCT aj.id_modelo_juiz)::INT AS feitos
                    FROM respostas_atividade_1 r
                    LEFT JOIN avaliacoes_juiz aj ON aj.id_resposta_ativa1 = r.id_resposta
                    GROUP BY r.id_resposta
                )
                SELECT COUNT(*) FROM por_resposta pr, ativos a
                WHERE COALESCE(pr.feitos, 0) < a.n
                """
            )
            return cur.fetchone()[0]


if __name__ == "__main__":
    executar_juiz_gemini()
