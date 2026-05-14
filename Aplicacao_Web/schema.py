from config import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS modelos (
    id_modelo          INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    nome_modelo        TEXT NOT NULL,
    versao             TEXT,
    parametro_precisao TEXT,
    UNIQUE (nome_modelo, versao)
);

CREATE TABLE IF NOT EXISTS modelos_juiz (
    id_modelo_juiz   INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    nome_exibicao    TEXT NOT NULL,
    id_api           TEXT NOT NULL UNIQUE,
    provedor         TEXT NOT NULL DEFAULT 'google',
    ativo            BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS datasets (
    id_dataset   INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    nome_dataset TEXT NOT NULL UNIQUE,
    dominio      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS perguntas (
    id_pergunta   INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id_dataset    INTEGER NOT NULL REFERENCES datasets(id_dataset),
    enunciado     TEXT    NOT NULL,
    resposta_ouro TEXT    NOT NULL,
    metadados     TEXT,
    UNIQUE (id_dataset, enunciado)
);

CREATE TABLE IF NOT EXISTS respostas_atividade_1 (
    id_resposta         INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id_pergunta         INTEGER NOT NULL REFERENCES perguntas(id_pergunta),
    id_modelo           INTEGER NOT NULL REFERENCES modelos(id_modelo),
    texto_resposta      TEXT    NOT NULL,
    tempo_inferencia_ms REAL    CHECK (tempo_inferencia_ms >= 0),
    data_geracao        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (id_pergunta, id_modelo)
);

CREATE TABLE IF NOT EXISTS avaliacoes_juiz (
    id_avaliacao       INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id_resposta_ativa1 INTEGER NOT NULL REFERENCES respostas_atividade_1(id_resposta),
    id_modelo_juiz     INTEGER NOT NULL REFERENCES modelos_juiz(id_modelo_juiz),
    nota_atribuida     REAL    NOT NULL CHECK (nota_atribuida BETWEEN 1 AND 5),
    nota_humana        INTEGER CHECK (nota_humana BETWEEN 1 AND 5),
    chain_of_thought   TEXT    NOT NULL,
    bert_score_f1      REAL,
    tokens_prompt      INTEGER,
    tokens_completion  INTEGER,
    data_avaliacao     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (id_resposta_ativa1, id_modelo_juiz)
);

CREATE TABLE IF NOT EXISTS rubrica_subcriterios (
    id_subcritério  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    id_avaliacao    INTEGER NOT NULL REFERENCES avaliacoes_juiz(id_avaliacao),
    criterio        TEXT    NOT NULL,
    nota_criterio   INTEGER NOT NULL CHECK (nota_criterio BETWEEN 1 AND 5),
    justificativa   TEXT    NOT NULL,
    peso            REAL    NOT NULL,
    UNIQUE (id_avaliacao, criterio)
);

CREATE INDEX IF NOT EXISTS idx_respostas_pergunta  ON respostas_atividade_1(id_pergunta);
CREATE INDEX IF NOT EXISTS idx_respostas_modelo    ON respostas_atividade_1(id_modelo);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_resposta ON avaliacoes_juiz(id_resposta_ativa1);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_juiz_modelo ON avaliacoes_juiz(id_modelo_juiz);
CREATE INDEX IF NOT EXISTS idx_subcrit_avaliacao   ON rubrica_subcriterios(id_avaliacao);
CREATE INDEX IF NOT EXISTS idx_perguntas_dataset   ON perguntas(id_dataset);
"""

SEED_MODELOS_JUIZ = """
INSERT INTO modelos_juiz (nome_exibicao, id_api) VALUES
  ('Gemini 3 Flash (preview)', 'gemini-3-flash-preview'),
  ('Gemini 3.1 Flash Lite', 'gemini-3.1-flash-lite'),
  ('Gemini 2.5 Flash', 'gemini-2.5-flash')
ON CONFLICT (id_api) DO NOTHING;
"""

VIEW_DDL = """
CREATE OR REPLACE VIEW vw_avaliacoes_completas AS
SELECT
    aj.id_avaliacao,
    d.nome_dataset,
    d.dominio,
    p.enunciado,
    p.resposta_ouro,
    mc.nome_modelo          AS modelo_candidato,
    mc.versao               AS versao_candidato,
    mc.parametro_precisao,
    r.texto_resposta,
    r.tempo_inferencia_ms,
    r.data_geracao          AS data_upload,
    mj.nome_exibicao        AS modelo_juiz,
    mj.id_api               AS id_api_juiz,
    aj.nota_atribuida,
    aj.nota_humana,
    aj.chain_of_thought,
    aj.bert_score_f1,
    aj.tokens_prompt,
    aj.tokens_completion,
    aj.data_avaliacao
FROM avaliacoes_juiz aj
JOIN respostas_atividade_1 r ON r.id_resposta = aj.id_resposta_ativa1
JOIN perguntas p             ON p.id_pergunta  = r.id_pergunta
JOIN datasets d              ON d.id_dataset   = p.id_dataset
JOIN modelos mc              ON mc.id_modelo   = r.id_modelo
JOIN modelos_juiz mj         ON mj.id_modelo_juiz = aj.id_modelo_juiz;
"""


def create_schema():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            for stmt in SEED_MODELOS_JUIZ.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            cur.execute(VIEW_DDL.strip())
        conn.commit()
        print("Schema criado com sucesso.")
    finally:
        conn.close()


if __name__ == "__main__":
    create_schema()
