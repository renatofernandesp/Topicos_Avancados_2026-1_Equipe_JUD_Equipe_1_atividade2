-- 1. Tabela de Metadados dos Modelos
CREATE TABLE modelos (
	id_modelo SERIAL PRIMARY KEY,
	nome_modelo VARCHAR(100) NOT NULL,
	versao VARCHAR(50),
	parametro_precisao VARCHAR(20),
	CONSTRAINT modelos_nome_modelo_versao_key UNIQUE (nome_modelo, versao)
);
-- 2. Tabela de Datasets
CREATE TABLE datasets (
	id_dataset SERIAL PRIMARY KEY,
	nome_dataset VARCHAR(100) NOT NULL,
	dominio VARCHAR(50) NOT NULL
);
-- 3. Tabela de Perguntas
CREATE TABLE perguntas (
	id_pergunta SERIAL PRIMARY KEY,
	id_dataset INTEGER REFERENCES datasets(id_dataset),
	enunciado TEXT NOT NULL,
	resposta_ouro TEXT NOT NULL,
	metadados JSONB,
	CONSTRAINT perguntas_id_dataset_enunciado_key UNIQUE (id_dataset, enunciado)
);
CREATE INDEX IF NOT EXISTS idx_perguntas_dataset
    ON public.perguntas USING btree
    (id_dataset ASC NULLS LAST)
    TABLESPACE pg_default;

-- 4. Tabela de Respostas da Atividade 1 (Modelos Candidatos)
CREATE TABLE respostas_atividade_1 (
	id_resposta SERIAL PRIMARY KEY,
	id_pergunta INTEGER REFERENCES perguntas(id_pergunta),
	id_modelo INTEGER REFERENCES modelos(id_modelo),
	texto_resposta TEXT NOT NULL,
	tempo_inferencia_ms FLOAT,
	data_geracao TIMESTAMP with time zone DEFAULT now()
	CONSTRAINT respostas_atividade_1_tempo_inferencia_ms_check CHECK (tempo_inferencia_ms >= 0::double precision)
);

CREATE INDEX IF NOT EXISTS idx_respostas_modelo
    ON public.respostas_atividade_1 USING btree
    (id_modelo ASC NULLS LAST)
    TABLESPACE pg_default;
	
-- 5. Tabela de Avaliações da Atividade 2 (O Juiz)
CREATE TABLE avaliacoes_juiz (
	id_avaliacao SERIAL PRIMARY KEY,
	id_resposta_ativa1 INTEGER REFERENCES respostas_atividade_1(id_resposta),
	id_modelo_juiz INTEGER REFERENCES modelos(id_modelo),
	nota_atribuida INTEGER CHECK (nota_atribuida BETWEEN 1 AND 5),
	chain_of_thought TEXT NOT NULL,
	data_avaliacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_resposta
    ON public.avaliacoes_juiz USING btree
    (id_resposta_ativa1 ASC NULLS LAST)
    TABLESPACE pg_default;

CREATE TABLE IF NOT EXISTS public.rubrica_subcriterios
(
    id_subcriterio integer NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 ),
    id_avaliacao integer NOT NULL,
    criterio text COLLATE pg_catalog."default" NOT NULL,
    nota_criterio integer NOT NULL,
    justificativa text COLLATE pg_catalog."default" NOT NULL,
    peso real NOT NULL,
    CONSTRAINT rubrica_subcriterios_pkey PRIMARY KEY (id_subcriterio),
    CONSTRAINT rubrica_subcriterios_id_avaliacao_criterio_keye UNIQUE (id_avaliacao, criterio),
    CONSTRAINT rubrica_subcriterios_nota_criterio_checke CHECK (nota_criterio >= 1 AND nota_criterio <= 5)
);
CREATE INDEX IF NOT EXISTS idx_subcrit_avaliacao
    ON public.rubrica_subcriterios USING btree
    (id_avaliacao ASC NULLS LAST)
    TABLESPACE pg_default;


-- DROP PROCEDURE IF EXISTS public.importar_perguntas_abertas(text);
CREATE OR REPLACE PROCEDURE public.importar_perguntas_abertas(
	IN p_caminho_arquivo text)
LANGUAGE 'plpgsql'
AS $BODY$
BEGIN
    -- 1. Criar/Limpar tabela temporária
    -- (Nota: Tabelas temporárias em procedures duram a sessão, 
    -- mas aqui garantimos que esteja limpa)
    CREATE TEMP TABLE IF NOT EXISTS tmp_import_jsonl (linha text);
    TRUNCATE tmp_import_jsonl;

    -- 2. Importa o arquivo dinamicamente usando EXECUTE
    -- O EXECUTE é necessário para concatenar o parâmetro do caminho
    EXECUTE format('COPY tmp_import_jsonl (linha) FROM %L WITH (FORMAT csv, quote e''\x01'', delimiter e''\x02'')', p_caminho_arquivo);

    -- 3. Inserção dos dados
    INSERT INTO perguntas (id_dataset, enunciado, resposta_ouro, metadados)
    SELECT 
        (SELECT id_dataset FROM datasets WHERE nome_dataset = 'OAB_Exams' LIMIT 1),
        COALESCE(linha::jsonb->>'statement', '') || E'\n\n' || COALESCE(linha::jsonb->>'turns', ''),
        (linha::jsonb->>'choices'),
        jsonb_build_object(
            'id_questao', (linha::jsonb->>'num')::int,
            'tipo', linha::jsonb->>'type',
            'edicao', linha::jsonb->>'edition',
            'ano', linha::jsonb->>'year',
            'especialidade', linha::jsonb->>'category',
            'dificuldade', linha::jsonb->>'level',
            'pessoa', linha::jsonb->>'system'
        )
    FROM tmp_import_jsonl
    WHERE linha LIKE '{%}';

    -- 3: Excluir a tabela temporária ao final para liberar memória
    DROP TABLE tmp_import_jsonl;

    RAISE NOTICE 'Importação concluída com sucesso a partir de %', p_caminho_arquivo;
END;
$BODY$;
ALTER PROCEDURE public.importar_perguntas_abertas(text)
    OWNER TO postgres;

-- DROP PROCEDURE IF EXISTS public.importar_perguntas_fechadas(text);
CREATE OR REPLACE PROCEDURE public.importar_perguntas_fechadas(
	IN p_caminho_arquivo text)
LANGUAGE 'plpgsql'
AS $BODY$
BEGIN
    -- 1. Criar/Limpar tabela temporária
    -- Nota: Tabelas temporárias duram apenas a sessão, mas o IF NOT EXISTS garante segurança
    CREATE TEMP TABLE IF NOT EXISTS tmp_import_jsonl (linha text);
    TRUNCATE tmp_import_jsonl;

    -- 2. Importa o arquivo usando SQL Dinâmico para aceitar o parâmetro
    EXECUTE format(
        'COPY tmp_import_jsonl (linha) FROM %L WITH (FORMAT csv, quote e''\x01'', delimiter e''\x02'')', 
        p_caminho_arquivo
    );

    -- 3. Inserção dos dados
    INSERT INTO perguntas (id_dataset, enunciado, resposta_ouro, metadados)
    SELECT 
        (SELECT id_dataset FROM datasets WHERE nome_dataset = 'OAB_Exams' LIMIT 1),
        -- Composição do enunciado
        COALESCE(linha::jsonb->>'question', ''),
        linha::jsonb->>'answer',
        jsonb_build_object(
            'id_questao', (linha::jsonb->>'num')::int,
            'tipo', linha::jsonb->>'type',
            'edicao', linha::jsonb->>'edition',
            'ano', (linha::jsonb->>'year')::int, -- Cast para int se necessário
            'especialidade', linha::jsonb->>'category',
			'dificuldade', linha::jsonb->>'level',
            'alternativas', linha::jsonb->'choices' -- Removido aspas para manter como objeto/array jsonb
        )
    FROM tmp_import_jsonl
    WHERE linha LIKE '{%}';

    -- Excluir tabela temporária
    DROP TABLE tmp_import_jsonl;
    
    RAISE NOTICE 'Importação do arquivo % concluída com sucesso.', p_caminho_arquivo;
END;
$BODY$;
ALTER PROCEDURE public.importar_perguntas_fechadas(text)
    OWNER TO postgres;




CREATE OR REPLACE PROCEDURE importar_respostas(
    p_caminho_arquivo TEXT,
    p_tipo_pergunta TEXT -- 'Aberta' ou 'Fechada'
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_linhas_processadas INTEGER;
BEGIN
    -- 1. Validação básica de parâmetro
    IF UPPER(p_tipo_pergunta) NOT IN ('ABERTA', 'FECHADA') THEN
        RAISE EXCEPTION 'Tipo inválido: %. Use "Aberta" ou "Fechada".', p_tipo_pergunta;
    END IF;

    -- 2. Preparação da tabela temporária
    CREATE TEMP TABLE IF NOT EXISTS tmp_import_jsonl (linha text);
    TRUNCATE tmp_import_jsonl;

    -- 3. Carga dinâmica do arquivo
    EXECUTE format(
        'COPY tmp_import_jsonl (linha) FROM %L WITH (FORMAT csv, quote e''\x01'', delimiter e''\x02'')', 
        p_caminho_arquivo
    );

    -- 4. Inserção com a lógica de alternância (ID ou Nome)
    INSERT INTO respostas_atividade_1 (
        id_pergunta, 
        id_modelo, 
        texto_resposta, 
        tempo_inferencia_ms, 
        data_geracao
    )
    SELECT 
        pergs.id_pergunta,
        COALESCE(
            NULLIF(j.dados->>'id_modelo', '')::INTEGER, 
            mods.id_modelo
        ),
        (j.dados->>'texto_resposta')::TEXT,
        (j.dados->>'tempo_inferencia_ms')::FLOAT,
        to_timestamp(j.dados->>'data_geracao', 'DD/MM/YYYY HH24:MI:SS')
    FROM (
        SELECT linha::jsonb AS dados FROM tmp_import_jsonl
    ) j
    INNER JOIN perguntas pergs ON 
        (pergs.metadados->>'id_questao') = (j.dados->>'id_questao')
        AND UPPER(pergs.metadados->>'tipo') = UPPER(p_tipo_pergunta)
    LEFT JOIN modelos mods ON 
        UPPER(TRIM(mods.nome_modelo)) = UPPER(TRIM(j.dados->>'nome_modelo'));

    -- 5. Feedback de execução
    GET DIAGNOSTICS v_linhas_processadas = ROW_COUNT;
    
    IF v_linhas_processadas = 0 THEN
        RAISE WARNING 'Nenhum registro inserido para o tipo %. Verifique IDs e nomes no arquivo.', p_tipo_pergunta;
    ELSE
        RAISE NOTICE 'Sucesso: % registros processados para o tipo %.', v_linhas_processadas, p_tipo_pergunta;
    END IF;

    -- Limpeza
    DROP TABLE tmp_import_jsonl;

EXCEPTION
    WHEN OTHERS THEN
        RAISE EXCEPTION 'Erro ao processar importação: % (SQLSTATE: %)', SQLERRM, SQLSTATE;
END;
$$;