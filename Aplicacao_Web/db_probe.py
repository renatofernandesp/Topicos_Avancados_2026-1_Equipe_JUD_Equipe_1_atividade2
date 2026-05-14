"""
Teste de ligação SSH + PostgreSQL (ping, schema, contagens).

Seguro para executar num thread: apenas dotenv + get_connection(); não usa Streamlit.
"""

from __future__ import annotations

from dotenv import load_dotenv

ProbeResult = tuple[bool, bool, dict | None, str | None]


def probe_db() -> ProbeResult:
    """
    Retorna (db_ok, tabelas_ok, contagens_ou_None, erro_str_ou_None).
    """
    load_dotenv(override=True)
    try:
        from config import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_name IN (
                        'modelos','modelos_juiz','datasets','perguntas',
                        'respostas_atividade_1','avaliacoes_juiz'
                    )
                    """
                )
                tabelas_ok = cur.fetchone()[0] == 6
                counts = None
                if tabelas_ok:
                    cur.execute("SELECT COUNT(*) FROM respostas_atividade_1")
                    respostas = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM avaliacoes_juiz")
                    avaliacoes = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM perguntas")
                    perguntas = cur.fetchone()[0]
                    try:
                        from judge_gemini_service import (
                            contar_respostas_incompletas,
                            contar_tarefas_pendentes,
                        )

                        respostas_gemini_pendentes = contar_respostas_incompletas()
                        tarefas_juiz_pendentes = contar_tarefas_pendentes()
                    except Exception:
                        respostas_gemini_pendentes = None
                        tarefas_juiz_pendentes = None
                    counts = {
                        "respostas": respostas,
                        "avaliacoes": avaliacoes,
                        "perguntas": perguntas,
                        "respostas_gemini_pendentes": respostas_gemini_pendentes,
                        "tarefas_juiz_pendentes": tarefas_juiz_pendentes,
                    }
        return (True, tabelas_ok, counts, None)
    except Exception as e:
        return (False, False, None, f"{type(e).__name__}: {e}")

