-- Atribui id_modelo às respostas com id_modelo NULL, por id_pergunta:
--   - maior tempo_inferencia_ms  -> id_modelo = 13
--   - menor tempo_inferencia_ms  -> id_modelo = 11
--
-- Antes de correr, confirme que existem linhas em modelos com id_modelo 11 e 13:
--   SELECT id_modelo, nome_modelo, versao FROM modelos WHERE id_modelo IN (11, 13);
--
-- Regras de desempate (empate no tempo):
--   máximo: id_resposta DESC (fica o id maior com 13)
--   mínimo: id_resposta ASC  (fica o id menor com 11)
--   Isto favorece escolher duas linhas distintas quando há empate e existem
--   pelo menos duas linhas com o mesmo tempo.
--
-- Limitação: se existirem MAIS de duas linhas NULL por id_pergunta, só duas
-- são atualizadas (uma com 13, uma com 11); as restantes continuam NULL.
--
-- Se já existir outra resposta à mesma pergunta com id_modelo 13 (ou 11), o
-- UPDATE correspondente é ignorado para essa linha (UNIQUE id_pergunta + id_modelo).
--
-- Uso (recomendado: envolver em transação no psql):
--   BEGIN;
--   \i scripts/atualizar_id_modelo_por_tempo.sql
--   ROLLBACK;  -- ou COMMIT;

-- 1) Linha com maior tempo (por pergunta) -> modelo 13
UPDATE respostas_atividade_1 r
SET id_modelo = 13
FROM (
    SELECT DISTINCT ON (id_pergunta)
        id_resposta,
        id_pergunta,
        tempo_inferencia_ms
    FROM respostas_atividade_1
    WHERE id_modelo IS NULL
    ORDER BY
        id_pergunta,
        tempo_inferencia_ms DESC NULLS LAST,
        id_resposta DESC
) x
WHERE r.id_resposta = x.id_resposta
  AND r.id_modelo IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM respostas_atividade_1 o
      WHERE o.id_pergunta = r.id_pergunta
        AND o.id_modelo = 13
        AND o.id_resposta <> r.id_resposta
  );

-- 2) Linha com menor tempo (ainda NULL) -> modelo 11
UPDATE respostas_atividade_1 r
SET id_modelo = 11
FROM (
    SELECT DISTINCT ON (id_pergunta)
        id_resposta,
        id_pergunta,
        tempo_inferencia_ms
    FROM respostas_atividade_1
    WHERE id_modelo IS NULL
    ORDER BY
        id_pergunta,
        tempo_inferencia_ms ASC NULLS LAST,
        id_resposta ASC
) y
WHERE r.id_resposta = y.id_resposta
  AND r.id_modelo IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM respostas_atividade_1 o
      WHERE o.id_pergunta = r.id_pergunta
        AND o.id_modelo = 11
        AND o.id_resposta <> r.id_resposta
  );

-- Verificação rápida após os UPDATEs (opcional)
SELECT
    'ainda_null' AS tipo,
    COUNT(*) AS qtd
FROM respostas_atividade_1
WHERE id_modelo IS NULL
UNION ALL
SELECT
    'com_modelo_11' AS tipo,
    COUNT(*) AS qtd
FROM respostas_atividade_1
WHERE id_modelo = 11
UNION ALL
SELECT
    'com_modelo_13' AS tipo,
    COUNT(*) AS qtd
FROM respostas_atividade_1
WHERE id_modelo = 13;
