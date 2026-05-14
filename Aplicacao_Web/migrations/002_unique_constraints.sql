-- Migração: garante as UNIQUE constraints exigidas pelos ON CONFLICT do serviço Gemini.
-- Idempotente: usa DO ... IF NOT EXISTS via catálogo do pg_constraint.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'avaliacoes_juiz'::regclass
          AND contype = 'u'
          AND conname = 'avaliacoes_juiz_resp_juiz_unique'
    ) THEN
        ALTER TABLE avaliacoes_juiz
            ADD CONSTRAINT avaliacoes_juiz_resp_juiz_unique
            UNIQUE (id_resposta_ativa1, id_modelo_juiz);
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'rubrica_subcriterios'::regclass
          AND contype = 'u'
          AND conname = 'rubrica_subcriterios_aval_crit_unique'
    ) THEN
        ALTER TABLE rubrica_subcriterios
            ADD CONSTRAINT rubrica_subcriterios_aval_crit_unique
            UNIQUE (id_avaliacao, criterio);
    END IF;
END$$;

COMMIT;
