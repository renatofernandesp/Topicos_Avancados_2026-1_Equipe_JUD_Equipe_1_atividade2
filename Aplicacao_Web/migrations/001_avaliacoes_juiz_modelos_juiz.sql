-- Migração: juízes em modelos_juiz, FK em avaliacoes_juiz, BERTScore, view.
-- Executar após backup se houver dados em produção.
-- psql ... -f migrations/001_avaliacoes_juiz_modelos_juiz.sql

BEGIN;

CREATE TABLE IF NOT EXISTS modelos_juiz (
    id_modelo_juiz   INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    nome_exibicao    TEXT NOT NULL,
    id_api           TEXT NOT NULL UNIQUE,
    provedor         TEXT NOT NULL DEFAULT 'google',
    ativo            BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em        TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO modelos_juiz (nome_exibicao, id_api) VALUES
  ('Gemini 3 Flash (preview)', 'gemini-3-flash-preview'),
  ('Gemini 3.1 Flash Lite', 'gemini-3.1-flash-lite'),
  ('Gemini 2.5 Flash', 'gemini-2.5-flash')
ON CONFLICT (id_api) DO NOTHING;

-- Remove avaliações antigas (id_modelo_juiz apontava para modelos, incompatível).
DELETE FROM "rubrica_subcriterios";
DELETE FROM avaliacoes_juiz;

ALTER TABLE avaliacoes_juiz DROP CONSTRAINT IF EXISTS avaliacoes_juiz_id_modelo_juiz_fkey;

ALTER TABLE avaliacoes_juiz
    ADD CONSTRAINT avaliacoes_juiz_id_modelo_juiz_fkey
    FOREIGN KEY (id_modelo_juiz) REFERENCES modelos_juiz(id_modelo_juiz);

ALTER TABLE avaliacoes_juiz ADD COLUMN IF NOT EXISTS bert_score_f1 REAL;

CREATE INDEX IF NOT EXISTS idx_avaliacoes_juiz_modelo ON avaliacoes_juiz(id_modelo_juiz);

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

COMMIT;
