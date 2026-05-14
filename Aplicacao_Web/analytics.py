import pandas as pd
from scipy.stats import spearmanr, kendalltau
from sklearn.metrics import cohen_kappa_score
from config import get_connection


def _query(sql: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn)


def media_notas_por_modelo() -> pd.DataFrame:
    return _query("""
        SELECT
            modelo_candidato                     AS modelo,
            versao_candidato                     AS versao,
            parametro_precisao,
            ROUND(AVG(nota_atribuida), 3)        AS media_juiz,
            ROUND(AVG(nota_humana), 3)           AS media_humana,
            COUNT(*)                             AS n
        FROM vw_avaliacoes_completas
        GROUP BY modelo_candidato, versao_candidato, parametro_precisao
        ORDER BY media_juiz DESC
    """)


def distribuicao_notas() -> pd.DataFrame:
    return _query("""
        SELECT
            ROUND(nota_atribuida) AS nota,
            COUNT(*)              AS quantidade
        FROM avaliacoes_juiz
        GROUP BY ROUND(nota_atribuida)
        ORDER BY nota
    """)


def resumo_por_dataset() -> pd.DataFrame:
    return _query("""
        SELECT
            nome_dataset,
            dominio,
            modelo_candidato              AS modelo,
            ROUND(AVG(nota_atribuida), 3) AS media_juiz,
            COUNT(*)                      AS n
        FROM vw_avaliacoes_completas
        GROUP BY nome_dataset, dominio, modelo_candidato
        ORDER BY nome_dataset, media_juiz DESC
    """)


def analise_subcritérios() -> pd.DataFrame:
    return _query("""
        SELECT
            mc.nome_modelo                        AS modelo,
            rs.criterio,
            ROUND(AVG(rs.nota_criterio), 3)       AS media,
            MIN(rs.nota_criterio)                 AS minimo,
            MAX(rs.nota_criterio)                 AS maximo,
            COUNT(*)                              AS n
        FROM rubrica_subcriterios rs
        JOIN avaliacoes_juiz aj      ON aj.id_avaliacao  = rs.id_avaliacao
        JOIN respostas_atividade_1 r ON r.id_resposta    = aj.id_resposta_ativa1
        JOIN modelos mc              ON mc.id_modelo     = r.id_modelo
        GROUP BY mc.nome_modelo, rs.criterio
        ORDER BY mc.nome_modelo, rs.criterio
    """)


MAX_PONTOS_SCATTER_API = 8000


def correlacao_juiz_humano() -> dict:
    df = _query("""
        SELECT ROUND(nota_atribuida) AS nota_juiz, nota_humana
        FROM avaliacoes_juiz
        WHERE nota_humana IS NOT NULL
    """)

    if len(df) < 3:
        return {"erro": "Dados insuficientes (mínimo 3 pares com nota_humana preenchida)."}

    df = df.assign(
        nota_juiz=df["nota_juiz"].astype(int),
        nota_humana=df["nota_humana"].astype(int),
    )

    juiz   = df["nota_juiz"].tolist()
    humano = df["nota_humana"].tolist()

    rho,  p_sp = spearmanr(juiz, humano)
    tau,  p_kt = kendalltau(juiz, humano)
    kappa      = cohen_kappa_score(juiz, humano, weights="quadratic")

    labels = sorted(set(humano) | set(juiz))
    ct = pd.crosstab(df["nota_humana"], df["nota_juiz"])
    ct = ct.reindex(index=labels, columns=labels, fill_value=0).astype(int)
    matriz_confusao = ct.values.tolist()

    n_total = len(df)
    if n_total > MAX_PONTOS_SCATTER_API:
        plot_df = df.sample(n=MAX_PONTOS_SCATTER_API, random_state=42)
        scatter_amostrado = True
    else:
        plot_df = df
        scatter_amostrado = False
    scatter_pontos = [
        {"nota_humana": int(r.nota_humana), "nota_juiz": int(r.nota_juiz)}
        for r in plot_df.itertuples(index=False)
    ]

    return {
        "n_amostras":             n_total,
        "spearman_rho":           round(float(rho),   4),
        "spearman_p":             round(float(p_sp),  6),
        "kendall_tau":            round(float(tau),   4),
        "kendall_p":              round(float(p_kt),  6),
        "cohen_kappa_quadratico": round(float(kappa), 4),
        "interpretacao":          _interpretar(rho, p_sp),
        "eixos_notas":            labels,
        "matriz_confusao":        matriz_confusao,
        "scatter_pontos":         scatter_pontos,
        "scatter_n_total":        n_total,
        "scatter_n_plot":         len(scatter_pontos),
        "scatter_amostrado":      scatter_amostrado,
    }


def _interpretar(rho, p):
    sig   = "significativa (p<0.05)" if p < 0.05 else "não significativa (p≥0.05)"
    forca = "forte" if abs(rho) >= 0.7 else ("moderada" if abs(rho) >= 0.4 else "fraca")
    return (
        f"Correlação de Spearman {forca} — {sig}. "
        f"ρ = {rho:.3f}, p = {p:.4g}."
    )


def custo_tokens() -> pd.DataFrame:
    return _query("""
        SELECT
            mj.nome_exibicao                            AS juiz,
            mj.id_api                                   AS id_api_juiz,
            SUM(tokens_prompt)                          AS total_prompt,
            SUM(tokens_completion)                      AS total_completion,
            SUM(COALESCE(tokens_prompt, 0) + COALESCE(tokens_completion, 0)) AS total_geral,
            COUNT(*)                                    AS avaliacoes
        FROM avaliacoes_juiz aj
        JOIN modelos_juiz mj ON mj.id_modelo_juiz = aj.id_modelo_juiz
        GROUP BY mj.nome_exibicao, mj.id_api
    """)


def exibir_relatorio():
    sep = "=" * 60
    print(f"\n{sep}\n  RANKING DOS MODELOS\n{sep}")
    print(media_notas_por_modelo().to_string(index=False))
    print(f"\n{sep}\n  DISTRIBUIÇÃO DAS NOTAS\n{sep}")
    print(distribuicao_notas().to_string(index=False))
    print(f"\n{sep}\n  RESUMO POR DATASET\n{sep}")
    print(resumo_por_dataset().to_string(index=False))
    print(f"\n{sep}\n  SUB-CRITÉRIOS\n{sep}")
    print(analise_subcritérios().to_string(index=False))
    print(f"\n{sep}\n  CORRELAÇÃO JUIZ × HUMANO\n{sep}")
    for k, v in correlacao_juiz_humano().items():
        print(f"  {k:<35}: {v}")
    print(f"\n{sep}\n  TOKENS\n{sep}")
    print(custo_tokens().to_string(index=False))


if __name__ == "__main__":
    exibir_relatorio()
