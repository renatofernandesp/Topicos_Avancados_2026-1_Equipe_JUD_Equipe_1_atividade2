import concurrent.futures
import os
from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from streamlit.runtime.scriptrunner import get_script_run_ctx

import db_probe

load_dotenv()

st.set_page_config(
    page_title="LLM-as-a-Judge",
    page_icon="⚖️",
    layout="wide",
)

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_PENDING: dict[str, tuple[int, concurrent.futures.Future]] = {}


def _session_id() -> str:
    ctx = get_script_run_ctx()
    if ctx is None:
        return "default"
    return str(ctx.session_id)


def _init_db_probe_session():
    if "db_probe_inited" not in st.session_state:
        st.session_state.db_probe_inited = True
        st.session_state.db_status = None
        st.session_state._probe_gen = 0
        st.session_state._need_schedule = True


def _apply_probe_result(result: db_probe.ProbeResult) -> bool:
    ok, tabelas_ok, counts, err = result
    if "db_error" not in st.session_state:
        st.session_state.db_error = None
    st.session_state.db_error = RuntimeError(err) if err else None
    st.session_state["_app_tabelas_ok"] = tabelas_ok
    st.session_state["_app_contagens"] = counts if tabelas_ok else None
    st.session_state.db_status = ok
    return ok


def _schedule_probe():
    sid = _session_id()
    st.session_state._probe_gen = int(st.session_state._probe_gen) + 1
    gen = st.session_state._probe_gen
    fut = _EXECUTOR.submit(db_probe.probe_db)
    _PENDING[sid] = (gen, fut)
    st.session_state._need_schedule = False


def _tick_probe():
    """Consome futures completos e inicia novo probe se _need_schedule (sem bloquear a UI)."""
    sid = _session_id()
    if sid in _PENDING:
        gen, fut = _PENDING[sid]
        if fut.done():
            try:
                res = fut.result(timeout=0)
            except Exception as e:
                res = (False, False, None, f"{type(e).__name__}: {e}")
            del _PENDING[sid]
            if gen == st.session_state._probe_gen:
                _apply_probe_result(res)
    if st.session_state.get("_need_schedule") and sid not in _PENDING:
        _schedule_probe()


def _request_db_refresh():
    st.session_state._need_schedule = True


def _invalidate_db_snapshot():
    """Após mudanças no schema/dados: novo probe em segundo plano."""
    sid = _session_id()
    if sid in _PENDING:
        del _PENDING[sid]
    _request_db_refresh()


@st.fragment(run_every=timedelta(seconds=5))
def _sidebar_connection_fragment():
    was_running = st.session_state.get("_probe_was_running", False)
    _tick_probe()
    sid = _session_id()
    running = sid in _PENDING and not _PENDING[sid][1].done()
    st.session_state["_probe_was_running"] = running
    db_status = st.session_state.get("db_status")

    if running:
        st.info("A ligar ao PostgreSQL (SSH + banco)…")
        return

    if was_running:
        # Probe acabou de terminar: actualiza as abas com o novo db_status
        st.session_state["_probe_was_running"] = False
        st.rerun()

    if db_status is None:
        st.caption("A preparar verificação da ligação…")
    elif db_status is True:
        st.success("PostgreSQL conectado", icon="🟢")
        if _tabelas_existem():
            c = _contagens()
            st.metric("Perguntas", c["perguntas"])
            st.metric("Respostas", c["respostas"])
            st.metric("Linhas em avaliacoes_juiz", c["avaliacoes"])
            rg = c.get("respostas_gemini_pendentes")
            if rg is not None:
                if rg > 0:
                    st.warning(f"{rg} resposta(s) sem os 3 juízes", icon="⏳")
            else:
                pendentes = max(0, c["respostas"] * 3 - c["avaliacoes"])
                if pendentes > 0 and c["respostas"] > 0:
                    st.caption("Atualize o probe (aguarde) para métrica exata de pendentes.")
        else:
            st.warning("Schema não criado", icon="⚠️")
    elif db_status is False:
        st.error("Sem conexão com o banco", icon="🔴")
        if st.session_state.get("db_error"):
            st.expander("Detalhes do Erro").exception(st.session_state.db_error)


def _tabelas_existem() -> bool:
    if "_app_tabelas_ok" in st.session_state:
        return bool(st.session_state["_app_tabelas_ok"])
    # Durante o probe async ou sem ligação: não abrir SSH/Postgres na thread principal
    if st.session_state.get("db_status") is not True:
        return False
    try:
        from config import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_name IN (
                        'modelos','modelos_juiz','datasets','perguntas',
                        'respostas_atividade_1','avaliacoes_juiz'
                    )
                    """
                )
                return cur.fetchone()[0] == 6
    except Exception:
        return False


def _contagens() -> dict:
    c = st.session_state.get("_app_contagens")
    if c is not None:
        return {
            "respostas": c.get("respostas", 0),
            "avaliacoes": c.get("avaliacoes", 0),
            "perguntas": c.get("perguntas", 0),
            "respostas_gemini_pendentes": c.get("respostas_gemini_pendentes"),
            "tarefas_juiz_pendentes": c.get("tarefas_juiz_pendentes"),
        }
    if st.session_state.get("db_status") is not True:
        return {
            "respostas": 0,
            "avaliacoes": 0,
            "perguntas": 0,
            "respostas_gemini_pendentes": None,
            "tarefas_juiz_pendentes": None,
        }
    from config import get_connection

    respostas_gemini_pendentes = None
    tarefas_juiz_pendentes = None
    try:
        from judge_gemini_service import (
            contar_respostas_incompletas,
            contar_tarefas_pendentes,
        )

        respostas_gemini_pendentes = contar_respostas_incompletas()
        tarefas_juiz_pendentes = contar_tarefas_pendentes()
    except Exception:
        pass

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM respostas_atividade_1")
            respostas = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM avaliacoes_juiz")
            avaliacoes = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM perguntas")
            perguntas = cur.fetchone()[0]
    return {
        "respostas": respostas,
        "avaliacoes": avaliacoes,
        "perguntas": perguntas,
        "respostas_gemini_pendentes": respostas_gemini_pendentes,
        "tarefas_juiz_pendentes": tarefas_juiz_pendentes,
    }


_init_db_probe_session()
db_status = st.session_state.get("db_status")

# ── header ─────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <div style='text-align: center;'>
        <h1>⚖️ LLM-as-a-Judge</h1>
        <h3><b>Atividade 2 — Avaliação automática (Gemini + rubrica + BERTScore)</b></h3>
    </div>
    <br>
    """,
    unsafe_allow_html=True
)

# ── abas ──────────────────────────────────────────────────────────────────────

aba_setup, aba_import, aba_juiz, aba_analise, aba_dados, aba_modelos = st.tabs([
    "🛠️ Setup do Banco",
    "📥 Importar Arquivo",
    "🤖 Executar Juiz",
    "📊 Análise",
    "👀 Visualizar Dados",
    "🗄️ Modelos",
])

if db_status is None:
    st.info(
        "A verificar ligação ao PostgreSQL (SSH + banco). Consulte o estado na barra lateral."
    )

# ════════════════════════════════════════════════════════════════════════════
# ABA 1 — SETUP
# ════════════════════════════════════════════════════════════════════════════

with aba_setup:
    st.header("Configuração do Banco de Dados")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Variáveis de Conexão")
        with st.form("form_env"):
            db_host = st.text_input("DB_HOST", value=os.getenv("DB_HOST", "localhost"))
            db_port = st.text_input("DB_PORT", value=os.getenv("DB_PORT", "5433"))
            db_name = st.text_input("DB_NAME", value=os.getenv("DB_NAME", "judge_db"))
            db_user = st.text_input("DB_USER", value=os.getenv("DB_USER", "postgres"))
            db_pass = st.text_input("DB_PASSWORD", value=os.getenv("DB_PASSWORD", "Procc2026ufs-_"), type="password")
            salvar = st.form_submit_button("💾 Salvar e Testar Conexão", use_container_width=True)

        if salvar:
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            lines = []
            if os.path.exists(env_path):
                with open(env_path) as f:
                    lines = f.readlines()

            def _set(lines, key, val):
                for i, l in enumerate(lines):
                    if l.startswith(key + "="):
                        lines[i] = f"{key}={val}\n"
                        return lines
                lines.append(f"{key}={val}\n")
                return lines

            for k, v in [("DB_HOST", db_host), ("DB_PORT", db_port),
                         ("DB_NAME", db_name), ("DB_USER", db_user),
                         ("DB_PASSWORD", db_pass)]:
                lines = _set(lines, k, v)

            with open(env_path, "w") as f:
                f.writelines(lines)

            os.environ.update({
                "DB_HOST": db_host, "DB_PORT": db_port,
                "DB_NAME": db_name, "DB_USER": db_user, "DB_PASSWORD": db_pass,
            })
            load_dotenv(override=True)
            _invalidate_db_snapshot()
            st.success("Credenciais gravadas. A testar ligação em segundo plano na sidebar…")
            st.rerun()

    with col2:
        st.subheader("Schema do Banco")
        st.markdown("""
O schema cria as seguintes tabelas:
- `modelos` — modelos candidatos (respostas)
- `modelos_juiz` — juízes LLM (ex.: 3 variantes Gemini)
- `datasets` — conjuntos de dados
- `perguntas` — enunciados e gabaritos
- `respostas_atividade_1` — respostas dos modelos
- `avaliacoes_juiz` — notas e Chain-of-Thought
- `rubrica_subcriterios` — notas por critério
- `vw_avaliacoes_completas` — VIEW analítica
""")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("✅ Criar Schema", use_container_width=True, disabled=(db_status is not True)):
                try:
                    from schema import create_schema
                    create_schema()
                    st.success("Schema criado com sucesso!")
                    _invalidate_db_snapshot()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

        with col_b:
            if st.button("🗑️ Reset Completo", use_container_width=True,
                         disabled=(db_status is not True), type="secondary"):
                try:
                    from db_utils import reset
                    reset()
                    st.success("Banco resetado e schema recriado!")
                    _invalidate_db_snapshot()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

        st.divider()
        st.subheader("Backup / Restore")
        col_c, col_d = st.columns(2)
        with col_c:
            nome_dump = st.text_input("Nome do arquivo", value="backup_atv2.sql")
            if st.button("📦 Gerar Dump", use_container_width=True, disabled=(db_status is not True)):
                try:
                    from db_utils import dump
                    dump(nome_dump)
                    st.success(f"Dump salvo: {nome_dump}")
                except Exception as e:
                    st.error(f"Erro: {e}")

        with col_d:
            arquivo_restore = st.file_uploader("Arquivo .sql para restore", type=["sql"])
            if st.button("♻️ Restaurar", use_container_width=True,
                         disabled=not (db_status is True and arquivo_restore)):
                try:
                    import tempfile
                    from db_utils import restore
                    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
                        tmp.write(arquivo_restore.read())
                        tmp_path = tmp.name
                    restore(tmp_path)
                    os.unlink(tmp_path)
                    st.success("Restore concluído!")
                    _invalidate_db_snapshot()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

# ════════════════════════════════════════════════════════════════════════════
# ABA 2 — IMPORTAR
# ════════════════════════════════════════════════════════════════════════════

with aba_import:
    st.header("Importar Arquivo")

    if db_status is not True or not _tabelas_existem():
        st.warning("Configure e crie o schema na aba **🛠️ Setup do Banco** primeiro.")
    else:
        st.markdown("""
**Colunas obrigatórias:** `dataset`, `dominio`, `enunciado`, `resposta_ouro`,
`modelo`, `versao`, `precisao`, `texto_resposta`

**Colunas opcionais:** `tempo_inferencia_ms`, `nota_humana` *(necessária para Spearman/Kappa)*

Qualquer outra coluna extra é armazenada como metadados JSONB.
""")

        arquivo = st.file_uploader("Selecione o arquivo", type=["xlsx", "xls", "txt", "json"])

        if arquivo:
            df_preview = pd.read_excel(arquivo)
            df_preview.columns = [c.strip().lower() for c in df_preview.columns]

            st.subheader(f"Pré-visualização — {len(df_preview)} linhas")
            st.dataframe(df_preview.head(10), use_container_width=True)

            obrigatorias = {"dataset", "dominio", "enunciado", "resposta_ouro",
                            "modelo", "versao", "precisao", "texto_resposta"}
            faltando = obrigatorias - set(df_preview.columns)

            if faltando:
                st.error(f"Colunas obrigatórias ausentes: {', '.join(sorted(faltando))}")
            else:
                st.success(f"Todas as colunas obrigatórias encontradas.")
                if "nota_humana" in df_preview.columns:
                    st.info("Coluna `nota_humana` detectada — correlação Spearman/Kappa disponível.")

                if st.button("📥 Importar para o PostgreSQL", type="primary", use_container_width=True):
                    arquivo.seek(0)
                    with st.spinner("Importando..."):
                        try:
                            # Executa a importação garantindo que o bloco try tenha o except correspondente
                            from importer import importar_excel
                            importar_excel(arquivo)
                            st.success(f"{len(df_preview)} linhas importadas com sucesso!")
                            _invalidate_db_snapshot()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro na importação: {e}")

# ════════════════════════════════════════════════════════════════════════════
# ABA 3 — EXECUTAR JUIZ
# ════════════════════════════════════════════════════════════════════════════

with aba_juiz:
    st.header("Executar Juiz-IA (Google Gemini)")

    if db_status is not True or not _tabelas_existem():
        st.warning("Configure e crie o schema na aba **🛠️ Setup do Banco** primeiro.")
    else:
        c = _contagens()
        t_pend = c.get("tarefas_juiz_pendentes")
        r_inc = c.get("respostas_gemini_pendentes")
        if t_pend is None:
            t_pend = 0
        if r_inc is None:
            r_inc = 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Respostas no banco", c["respostas"])
        col2.metric("Linhas avaliacoes_juiz", c["avaliacoes"])
        col3.metric("Respostas incompletas", r_inc)
        col4.metric("Tarefas pendentes", t_pend)

        st.caption(
            "Cada resposta é avaliada por **todos** os juízes ativos em `modelos_juiz` "
            "(por omissão: 3 modelos Gemini). Requer `GEMINI_API_KEY` no `.env`."
        )
        if not os.getenv("GEMINI_API_KEY"):
            st.error("Defina `GEMINI_API_KEY` no ficheiro `.env` para chamar a API Google.")

        st.divider()
        st.markdown("""
**Rubrica multidimensional (STF + técnica):**

| Sub-critério | Descrição | Peso |
|---|---|---|
| Correção factual | Alinhamento com fatos e gabarito | 30% |
| Completude | Cobre todos os pontos relevantes | 25% |
| Clareza | Linguagem precisa, sem ambiguidade | 20% |
| Coerência | Argumentação lógica e consistente | 15% |
| Relevância | Responde diretamente ao perguntado | 10% |

A nota final gravada é a média ponderada (1.0–5.0). **BERTScore F1** (candidato vs gabarito) é calculada uma vez por resposta e replicada nas linhas dos juízes. Use `SKIP_BERT=1` para pular o cálculo (ex.: desenvolvimento).
""")

        substituir = st.checkbox(
            "Substituir avaliações já existentes (apaga rubrica + avaliação antes de reexecutar o juiz)",
            value=False,
            help="Requer escolher pares na lista abaixo. A nota humana, quando existia, é reposta após a nova avaliação.",
        )

        if substituir:
            from judge_gemini_service import listar_tarefas_avaliadas

            opts = listar_tarefas_avaliadas(limite=500)
            if not opts:
                st.info("Não há pares já avaliados para listar (ou limite 500 sem resultados).")
            else:
                labels = [
                    f"{o['id_resposta']} × juiz {o['id_modelo_juiz']} ({o['id_api_juiz']}) — {o['nome_dataset']}"
                    for o in opts
                ]
                label_to_par = {labels[i]: (opts[i]["id_resposta"], opts[i]["id_modelo_juiz"]) for i in range(len(labels))}
                picked = st.multiselect(
                    "Pares (resposta × modelo_juiz) a substituir e reavaliar",
                    options=labels,
                    help="Cada linha corresponde a um par exatamente como na base de dados.",
                )
                if st.button(
                    f"▶️ Reavaliar {len(picked)} par(es) selecionado(s) (substituição)",
                    type="primary",
                    use_container_width=True,
                    disabled=not os.getenv("GEMINI_API_KEY") or not picked,
                ):
                    from judge_gemini_service import executar_juiz_gemini_stream

                    pares = [label_to_par[L] for L in picked]
                    progresso = st.progress(0, text="Iniciando reavaliação…")
                    log_area = st.empty()
                    logs = []
                    erros = 0

                    for ev in executar_juiz_gemini_stream(substituir=True, pares=pares):
                        if ev["total"] == 0:
                            progresso.progress(1.0, text="Nenhuma tarefa.")
                            break

                        pct = ev["atual"] / max(ev["total"], 1)
                        txt = f"Reavaliando {ev['atual']}/{ev['total']}…"
                        progresso.progress(min(pct, 1.0), text=txt)

                        if ev["erro"]:
                            erros += 1
                            logs.append(
                                f"❌ Resposta {ev['id']} [{ev.get('juiz', '?')}]: {ev['erro']}"
                            )
                        else:
                            sc = ev["subcrit"]
                            logs.append(
                                f"✅ Resposta {ev['id']} [{ev.get('juiz', '?')}] → **{ev['nota']}** "
                                f"(CF={sc.get('correcao_factual', '-')} "
                                f"CO={sc.get('completude', '-')} "
                                f"CL={sc.get('clareza', '-')} "
                                f"COE={sc.get('coerencia', '-')} "
                                f"RE={sc.get('relevancia', '-')})"
                            )

                        log_area.markdown("\n".join(logs[-15:]))

                    progresso.progress(1.0, text="Concluído!")
                    if erros:
                        st.warning(f"Reavaliação concluída com {erros} erro(s).")
                    else:
                        st.success("Pares selecionados foram reprocessados.")
                    _invalidate_db_snapshot()
                    st.rerun()

        if not substituir and t_pend == 0:
            st.success("Não há tarefas pendentes (todos os pares resposta×juiz já avaliados).")
        elif not substituir:
            if st.button(
                f"▶️ Avaliar {t_pend} tarefa(s) pendente(s) (chamadas Gemini)",
                type="primary",
                use_container_width=True,
                disabled=not os.getenv("GEMINI_API_KEY"),
            ):
                from judge_gemini_service import executar_juiz_gemini_stream

                progresso = st.progress(0, text="Iniciando avaliação...")
                log_area = st.empty()
                logs = []
                erros = 0

                for ev in executar_juiz_gemini_stream():
                    if ev["total"] == 0:
                        progresso.progress(1.0, text="Nenhuma tarefa pendente.")
                        break

                    pct = ev["atual"] / ev["total"]
                    txt = f"Avaliando {ev['atual']}/{ev['total']}…"
                    progresso.progress(min(pct, 1.0), text=txt)

                    if ev["erro"]:
                        erros += 1
                        logs.append(
                            f"❌ Resposta {ev['id']} [{ev.get('juiz', '?')}]: {ev['erro']}"
                        )
                    else:
                        sc = ev["subcrit"]
                        logs.append(
                            f"✅ Resposta {ev['id']} [{ev.get('juiz', '?')}] → **{ev['nota']}** "
                            f"(CF={sc.get('correcao_factual', '-')} "
                            f"CO={sc.get('completude', '-')} "
                            f"CL={sc.get('clareza', '-')} "
                            f"COE={sc.get('coerencia', '-')} "
                            f"RE={sc.get('relevancia', '-')})"
                        )

                    log_area.markdown("\n".join(logs[-15:]))

                progresso.progress(1.0, text="Concluído!")
                if erros:
                    st.warning(f"Avaliação concluída com {erros} erro(s).")
                else:
                    st.success("Todas as tarefas pendentes foram processadas.")
                _invalidate_db_snapshot()
                st.rerun()

        if c["avaliacoes"] > 0:
            st.divider()
            st.subheader("Últimas Avaliações")
            from analytics import _query

            df_ult = _query("""
                SELECT
                    v.modelo_candidato AS modelo,
                    v.modelo_juiz      AS juiz,
                    LEFT(v.enunciado, 60) || '...' AS pergunta,
                    v.nota_atribuida               AS nota,
                    v.bert_score_f1                AS bert_f1,
                    LEFT(v.chain_of_thought, 120) || '...' AS cot,
                    v.data_avaliacao::DATE         AS data
                FROM vw_avaliacoes_completas v
                ORDER BY v.data_avaliacao DESC
                LIMIT 15
            """)
            st.dataframe(df_ult, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# ABA 4 — ANÁLISE
# ════════════════════════════════════════════════════════════════════════════

with aba_analise:
    st.header("Análise de Resultados")

    if db_status is not True or not _tabelas_existem():
        st.warning("Configure e crie o schema na aba **🛠️ Setup do Banco** primeiro.")
    elif _contagens()["avaliacoes"] == 0:
        st.info("Nenhuma avaliação encontrada. Execute o Juiz primeiro.")
    else:
        from analytics import (
            media_notas_por_modelo, distribuicao_notas,
            resumo_por_dataset, analise_subcritérios,
            correlacao_juiz_humano, custo_tokens,
        )

        # ── KPIs ──────────────────────────────────────────────────────────
        df_rank = media_notas_por_modelo()
        df_dist = distribuicao_notas()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Modelos avaliados",   len(df_rank))
        k2.metric("Total de avaliações", int(df_dist["quantidade"].sum()))
        k3.metric("Nota média geral",    f"{df_rank['media_juiz'].mean():.2f}")
        melhor = df_rank.iloc[0]
        k4.metric("Melhor modelo", melhor["modelo"], f"nota {melhor['media_juiz']:.2f}")

        st.divider()

        # ── Ranking + Distribuição ─────────────────────────────────────────
        col_l, col_r = st.columns(2)

        with col_l:
            st.subheader("Ranking dos Modelos")
            fig_rank = px.bar(
                df_rank, x="media_juiz", y="modelo", orientation="h",
                color="media_juiz", color_continuous_scale="RdYlGn",
                range_color=[1, 5], text="media_juiz",
                labels={"media_juiz": "Nota Média", "modelo": "Modelo"},
            )
            fig_rank.update_traces(texttemplate="%{text:.2f}", textposition="outside")
            fig_rank.update_layout(showlegend=False, coloraxis_showscale=False,
                                   yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig_rank, use_container_width=True)

        with col_r:
            st.subheader("Distribuição das Notas")
            fig_dist = px.bar(
                df_dist, x="nota", y="quantidade",
                color="nota", color_continuous_scale="RdYlGn",
                range_color=[1, 5], text="pct",
                labels={"nota": "Nota", "quantidade": "Quantidade"},
            )
            fig_dist.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_dist.update_layout(showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_dist, use_container_width=True)

        # ── Sub-critérios ──────────────────────────────────────────────────
        st.divider()
        st.subheader("Análise por Sub-critério da Rubrica")
        df_sub = analise_subcritérios()
        if not df_sub.empty:
            fig_sub = px.bar(
                df_sub, x="criterio", y="media", color="modelo",
                barmode="group", text="media",
                labels={"criterio": "Critério", "media": "Nota Média", "modelo": "Modelo"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_sub.update_traces(texttemplate="%{text:.2f}", textposition="outside")
            fig_sub.update_yaxes(range=[0, 5.5])
            st.plotly_chart(fig_sub, use_container_width=True)

            with st.expander("Ver tabela detalhada"):
                st.dataframe(df_sub, use_container_width=True)

        # ── Resumo por Dataset ─────────────────────────────────────────────
        st.divider()
        st.subheader("Desempenho por Dataset")
        df_ds = resumo_por_dataset()
        if not df_ds.empty:
            fig_ds = px.bar(
                df_ds, x="nome_dataset", y="media_juiz", color="modelo",
                barmode="group", text="media_juiz",
                labels={"nome_dataset": "Dataset", "media_juiz": "Nota Média", "modelo": "Modelo"},
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_ds.update_traces(texttemplate="%{text:.2f}", textposition="outside")
            fig_ds.update_yaxes(range=[0, 5.5])
            st.plotly_chart(fig_ds, use_container_width=True)

        # ── Correlação Juiz × Humano ───────────────────────────────────────
        st.divider()
        st.subheader("Correlação Juiz × Avaliador Humano")
        corr = correlacao_juiz_humano()

        if "erro" in corr:
            st.info(f"ℹ️ {corr['erro']}")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Spearman ρ",  corr["spearman_rho"],
                      help=f"p-value: {corr['spearman_p']}")
            c2.metric("Kendall τ",   corr["kendall_tau"],
                      help=f"p-value: {corr['kendall_p']}")
            c3.metric("Cohen's κ",   corr["cohen_kappa_quadratico"],
                      help="Ponderado quadrático")

            st.info(f"📌 {corr['interpretacao']}")

            from analytics import _query as _q
            df_scatter = _q("""
                SELECT ROUND(nota_atribuida)::INTEGER AS nota_juiz, nota_humana
                FROM avaliacoes_juiz WHERE nota_humana IS NOT NULL
            """)
            if not df_scatter.empty:
                fig_sc = px.scatter(
                    df_scatter, x="nota_humana", y="nota_juiz",
                    trendline="ols",
                    labels={"nota_humana": "Nota Humana", "nota_juiz": "Nota do Juiz"},
                    title="Dispersão: Juiz vs. Humano",
                    color_discrete_sequence=["#636EFA"],
                )
                fig_sc.update_layout(xaxis=dict(range=[0.5, 5.5]),
                                     yaxis=dict(range=[0.5, 5.5]))
                st.plotly_chart(fig_sc, use_container_width=True)

        # ── Tokens ────────────────────────────────────────────────────────
        st.divider()
        st.subheader("Consumo de Tokens do Juiz")
        df_tok = custo_tokens()
        if not df_tok.empty:
            col_tok, col_tab = st.columns([1, 2])
            with col_tok:
                fig_tok = px.pie(
                    df_tok.melt(
                        id_vars=["juiz", "id_api_juiz"],
                        value_vars=["total_prompt", "total_completion"],
                        var_name="tipo",
                        value_name="tokens",
                    ),
                    values="tokens", names="tipo",
                    color_discrete_sequence=["#636EFA", "#EF553B"],
                    title="Prompt vs. Completion",
                )
                st.plotly_chart(fig_tok, use_container_width=True)
            with col_tab:
                st.dataframe(df_tok, use_container_width=True)

        # ── Tabela completa ────────────────────────────────────────────────
        st.divider()
        with st.expander("📋 Ver todas as avaliações"):
            from analytics import _query as _q2
            df_all = _q2("""
                SELECT
                    v.modelo_candidato, v.nome_dataset, v.dominio,
                    LEFT(v.enunciado, 80) AS enunciado,
                    v.nota_atribuida, v.nota_humana,
                    LEFT(v.chain_of_thought, 200) AS chain_of_thought,
                    v.tokens_prompt, v.tokens_completion,
                    v.data_avaliacao::DATE AS data
                FROM vw_avaliacoes_completas v
                ORDER BY v.data_avaliacao DESC
            """)
            st.dataframe(df_all, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════
# ABA 5 — VISUALIZAR DADOS
# ════════════════════════════════════════════════════════════════════════════

with aba_dados:
    st.header("Visualizar Perguntas, Respostas e Avaliações")

    if db_status is not True or not _tabelas_existem():
        st.warning("Configure e crie o schema na aba **🛠️ Setup do Banco** primeiro.")
    else:
        from analytics import _query

        # ── Filtros ───────────────────────────────────────────────────────
        datasets_disponiveis = _query("SELECT DISTINCT nome_dataset FROM datasets ORDER BY nome_dataset")
        modelos_disponiveis  = _query("SELECT DISTINCT nome_modelo FROM modelos ORDER BY nome_modelo")

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filtro_dataset = st.selectbox("Dataset", ["Todos"] + datasets_disponiveis["nome_dataset"].tolist())
        with col_f2:
            filtro_modelo = st.selectbox("Modelo", ["Todos"] + modelos_disponiveis["nome_modelo"].tolist())
        with col_f3:
            filtro_tipo = st.selectbox("Exibir", ["Todas as perguntas", "Com resposta", "Sem resposta"])

        where = []
        if filtro_dataset != "Todos":
            where.append(f"d.nome_dataset = '{filtro_dataset}'")
        if filtro_modelo != "Todos":
            where.append(f"mc.nome_modelo = '{filtro_modelo}'")
        if filtro_tipo == "Com resposta":
            where.append("r.id_resposta IS NOT NULL")
        elif filtro_tipo == "Sem resposta":
            where.append("r.id_resposta IS NULL")

        where_sql = "WHERE " + " AND ".join(where) if where else ""

        df_dados = _query(f"""
            SELECT
                d.nome_dataset                          AS dataset,
                LEFT(p.enunciado, 120)                  AS pergunta,
                LEFT(p.resposta_ouro, 120)              AS gabarito,
                COALESCE(mc.nome_modelo, '—')           AS modelo,
                LEFT(COALESCE(r.texto_resposta, '—'), 120) AS resposta,
                aj.nota_atribuida                       AS nota,
                LEFT(COALESCE(aj.chain_of_thought, '—'), 150) AS justificativa
            FROM perguntas p
            JOIN datasets d ON d.id_dataset = p.id_dataset
            LEFT JOIN respostas_atividade_1 r  ON r.id_pergunta = p.id_pergunta
            LEFT JOIN modelos mc               ON mc.id_modelo  = r.id_modelo
            LEFT JOIN avaliacoes_juiz aj       ON aj.id_resposta_ativa1 = r.id_resposta
            {where_sql}
            ORDER BY d.nome_dataset, p.id_pergunta
        """)

        st.caption(f"{len(df_dados)} registro(s) encontrado(s)")

        if df_dados.empty:
            st.info("Nenhum registro encontrado com os filtros selecionados.")
        else:
            st.dataframe(df_dados, use_container_width=True, height=600)

# ════════════════════════════════════════════════════════════════════════════
# ABA 6 — MODELOS (diagnóstico de conexão)
# ════════════════════════════════════════════════════════════════════════════

with aba_modelos:
    st.header("Modelos candidatos e juízes")

    if db_status is not True:
        st.warning("Banco de dados não conectado. Aguarde a verificação na barra lateral.")
    else:
        try:
            from config import get_connection

            with get_connection() as conn:
                df_modelos = pd.read_sql(
                    "SELECT * FROM public.modelos ORDER BY id_modelo", conn
                )
                df_juiz = pd.read_sql(
                    "SELECT * FROM public.modelos_juiz ORDER BY id_modelo_juiz", conn
                )
            st.subheader("public.modelos (candidatos)")
            st.success(f"{len(df_modelos)} registro(s)")
            st.dataframe(df_modelos, use_container_width=True)
            st.subheader("public.modelos_juiz (API Gemini)")
            st.success(f"{len(df_juiz)} registro(s)")
            st.dataframe(df_juiz, use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao consultar tabelas de modelos: {e}")

# ── sidebar ────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚖️ LLM-as-a-Judge")
    st.caption("Atividade 2 — Avaliação automática com GPT-5.3 Codex")
    st.divider()

    if st.button(
        "🔄 Atualizar ligação ao banco",
        use_container_width=True,
        help="Interrompe a verificação anterior e volta a testar SSH + PostgreSQL.",
    ):
        sid_btn = _session_id()
        if sid_btn in _PENDING:
            del _PENDING[sid_btn]
        _request_db_refresh()
        st.rerun()

    _sidebar_connection_fragment()

    st.divider()
    st.caption("Rubrica do Juiz")
    st.markdown("""
| Critério | Peso |
|---|---|
| Correção Factual | 30% |
| Completude | 25% |
| Clareza | 20% |
| Coerência | 15% |
| Relevância | 10% |
""")
