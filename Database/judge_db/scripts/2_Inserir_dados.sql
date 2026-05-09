-- Limpar tabelas
truncate datasets restart identity cascade;
truncate modelos restart identity cascade;
truncate perguntas restart identity cascade;
truncate respostas_atividade_1 restart identity cascade;
truncate avaliacoes_juiz restart identity cascade;
truncate rubrica_subcriterios restart identity cascade;

-- Povoar a tabela dataset
insert into datasets(nome_dataset, dominio) values ('OAB_Exams', 'Jurídico');
insert into datasets(nome_dataset, dominio) values ('K-QA', 'Médico');

-- Inserir modelos
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Llama-3.1-8b-instant', '3.1', 'temperature:0.1');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Llama-3.3-70b-versatile', '3.3', 'temperature:0.1');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Llama-4-scout-17b-16e-instruct', '4', 'temperature:0.1');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Gemini-3.1-flash-lite-preview', '3.1', 'temperature:0.1');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Llama-3.3-70B-Groq', '3.3', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Llama-3.1-8B-Groq', '3.1', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Qwen-2.5-7B-Qwen', '2.5', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('GPT-4o Mini', '4', 'temperature:1.0');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('GPT-5.4 Nano', '5.4', 'temperature:1.0');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('GPT-5.4', '5.4', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Gemini-3-flash', '3', 'temperature:0.2');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Gemini-3.1-flash-lite', '3.1', 'temperature:0.2');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Gemini-3.1-pro', '3.1', 'temperature:0.2');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Llama 4 Maverick 17B', '4', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('GPT-5.3', '5.3', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Claude Sonnet 4.6', '4.6', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Gemini modelo rápido', '3', 'N/A');
insert into modelos (nome_modelo, versao, parametro_precisao) values ('Gpt-oss-120b:free', 'v1', 'N/A');

-- Importar Perguntas abertas
Call importar_perguntas_abertas('/opt/judge/open_questions.jsonl');

-- Importtar Perguntas fechadas
Call importar_perguntas_fechadas('/opt/judge/close_questions.jsonl');

-- Inserir respostas das questões abertas
Call importar_respostas('/opt/judge/resultados_open_questions.jsonl', 'Aberta');
Call importar_respostas('/opt/judge/resultados_close_questions.jsonl', 'Fechada');

