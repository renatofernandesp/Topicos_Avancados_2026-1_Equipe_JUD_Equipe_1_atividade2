import json
import sys
import pandas as pd
from config import get_connection

COLUNAS_FIXAS = {
    "dataset", "dominio", "enunciado", "resposta_ouro",
    "modelo", "versao", "precisao", "texto_resposta",
    "tempo_inferencia_ms", "nota_humana",
}


def _ler_arquivo(caminho):
    """Lê XLSX, XLS, TXT (csv/tsv) ou JSON e retorna um DataFrame."""
    nome = caminho if isinstance(caminho, str) else getattr(caminho, "name", "")
    ext = nome.rsplit(".", 1)[-1].lower()

    if ext in ("xlsx", "xls"):
        return pd.read_excel(caminho)
    elif ext == "json":
        dados = json.load(caminho) if hasattr(caminho, "read") else json.loads(open(caminho).read())
        return pd.DataFrame(dados if isinstance(dados, list) else [dados])
    elif ext == "txt":
        sep = "\t" if ext == "txt" else ","
        return pd.read_csv(caminho, sep=sep)
    else:
        # tenta CSV genérico
        return pd.read_csv(caminho)


def _upsert_modelo(cur, nome, versao, precisao):
    cur.execute(
        """INSERT INTO modelos (nome_modelo, versao, parametro_precisao)
           VALUES (%s,%s,%s) ON CONFLICT (nome_modelo, versao) DO NOTHING""",
        (nome, versao, precisao),
    )
    cur.execute(
        "SELECT id_modelo FROM modelos WHERE nome_modelo=%s AND versao=%s", (nome, versao)
    )
    return cur.fetchone()[0]


def _upsert_dataset(cur, nome, dominio):
    cur.execute(
        "INSERT INTO datasets (nome_dataset, dominio) VALUES (%s,%s) ON CONFLICT (nome_dataset) DO NOTHING",
        (nome, dominio),
    )
    cur.execute("SELECT id_dataset FROM datasets WHERE nome_dataset=%s", (nome,))
    return cur.fetchone()[0]


def _upsert_pergunta(cur, id_dataset, enunciado, resposta_ouro, metadados):
    cur.execute(
        """INSERT INTO perguntas (id_dataset, enunciado, resposta_ouro, metadados)
           VALUES (%s,%s,%s,%s) ON CONFLICT (id_dataset, enunciado) DO NOTHING""",
        (id_dataset, enunciado, resposta_ouro, json.dumps(metadados) if metadados else None),
    )
    cur.execute(
        "SELECT id_pergunta FROM perguntas WHERE id_dataset=%s AND enunciado=%s",
        (id_dataset, enunciado),
    )
    return cur.fetchone()[0]


def _insert_resposta(cur, id_pergunta, id_modelo, texto, tempo, nota_humana):
    cur.execute(
        """INSERT INTO respostas_atividade_1 (id_pergunta, id_modelo, texto_resposta, tempo_inferencia_ms)
           VALUES (%s,%s,%s,%s) ON CONFLICT (id_pergunta, id_modelo) DO NOTHING""",
        (id_pergunta, id_modelo, texto, tempo if pd.notna(tempo) else None),
    )
    cur.execute(
        "SELECT id_resposta FROM respostas_atividade_1 WHERE id_pergunta=%s AND id_modelo=%s",
        (id_pergunta, id_modelo),
    )
    id_resposta = cur.fetchone()[0]

    if nota_humana and pd.notna(nota_humana):
        cur.execute(
            "UPDATE avaliacoes_juiz SET nota_humana=%s WHERE id_resposta_ativa1=%s",
            (int(nota_humana), id_resposta),
        )
    return id_resposta


def importar_excel(caminho):
    """Aceita XLSX, XLS, TXT ou JSON — caminho (str) ou file-like (Streamlit)."""
    df = _ler_arquivo(caminho)
    df.columns = [c.strip().lower() for c in df.columns]
    colunas_meta = [c for c in df.columns if c not in COLUNAS_FIXAS]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                id_dataset  = _upsert_dataset(cur, row["dataset"], row["dominio"])
                id_modelo   = _upsert_modelo(cur, row["modelo"], row.get("versao"), row.get("precisao"))
                metadados   = {c: row[c] for c in colunas_meta if pd.notna(row.get(c))}
                id_pergunta = _upsert_pergunta(cur, id_dataset, row["enunciado"],
                                               row["resposta_ouro"], metadados)
                _insert_resposta(
                    cur, id_pergunta, id_modelo,
                    row["texto_resposta"],
                    row.get("tempo_inferencia_ms"),
                    row.get("nota_humana")
                )
        conn.commit()
    finally:
        conn.close()

    print(f"{len(df)} linhas importadas com sucesso.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python importer.py <arquivo.xlsx|.json|.txt>")
        sys.exit(1)
    importar_excel(sys.argv[1])
