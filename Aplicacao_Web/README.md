# LLM-as-a-Judge — Atividade 2

Pipeline completo de avaliação automática de respostas de LLMs usando **GPT-5.3 Codex** como juiz, com armazenamento em **PostgreSQL** e análise estatística de concordância.

---

## Arquitetura

```
Excel (.xlsx)
     │
     ▼
importer.py ──► PostgreSQL
                 ├── modelos
                 ├── datasets
                 ├── perguntas
                 ├── respostas_atividade_1
                 ├── avaliacoes_juiz          ◄── judge.py (GPT-5.3 Codex)
                 ├── rubrica_subcritérios     ◄── judge.py (sub-critérios)
                 └── vw_avaliacoes_completas  ◄── VIEW analítica
                          │
                          ▼
                    analytics.py
                    (Spearman · Kendall · Kappa)
```

---

## Estrutura de Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | Conexão PostgreSQL via variáveis de ambiente |
| `schema.py` | DDL completo: tabelas, índices, constraints, VIEW |
| `importer.py` | Importação do Excel para o banco |
| `judge.py` | Pipeline LLM-as-a-Judge (rubrica multidimensional) |
| `analytics.py` | Queries SQL + métricas de concordância |
| `db_utils.py` | Dump, restore e reset do banco |
| `main.py` | Orquestrador do pipeline completo |

---

## Configuração

### 1. Variáveis de ambiente (`.env`)

```
# PostgreSQL (lado cliente do túnel: em geral localhost e porta local livre)
DB_HOST=localhost
DB_PORT=5433
DB_NAME=atv2_db
DB_USER=<usuario>
DB_PASSWORD=<senha>
PG_CONNECT_TIMEOUT=10

# SSH — servidor Jump; credenciais podem ser omitidas se já existirem nos defaults do config.py
SSH_HOST=177.10.120.254
SSH_PORT=1989
SSH_USER=<usuario_ssh>
SSH_PASSWORD=<senha_ssh>

# Postgres no host remoto (visto a partir do servidor SSH)
REMOTE_DB_HOST=127.0.0.1
REMOTE_DB_PORT=5432

# Timeouts em segundos (evitam bloqueio indefinido na abertura SSH/túnel)
SSH_SOCKET_TIMEOUT=20
SSH_TUNNEL_OPEN_TIMEOUT=20

AZURE_OPENAI_KEY=<chave>
AZURE_OPENAI_ENDPOINT=https://ai-grc-group.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2025-01-01-preview
```

### 2. Instalar dependências

```bash
pip install -r requirements.txt
```

### 3. Criar banco

```sql
CREATE DATABASE atv2_db;
```

---

## Uso

```bash
# Pipeline completo (schema + import + juiz + relatório)
python main.py planilha.xlsx

# Apenas avaliar respostas pendentes
python main.py --only-judge

# Apenas exibir relatório
python main.py --only-analytics

# Backup do banco
python db_utils.py dump backup_atv2.sql

# Restore
python db_utils.py restore backup_atv2.sql

# Reset completo (drop + recria)
python db_utils.py reset
```

---

## Frontend Vue/PrimeVue (alternativo)

Há uma SPA opcional em [`frontend/`](frontend/README.md) que cobre apenas a aba do
juiz, com filtros, multi-seleção e execução parcial. O Streamlit (`app.py`)
continua funcionando sem alterações.

```bash
# 1) Backend FastAPI (requer requirements.txt + GEMINI_API_KEY no .env)
python -m uvicorn api.main:app --reload --port 8000

# 2) Frontend (Node 18+; veja frontend/README.md)
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxy /api -> :8000)

# Build de produção: o backend serve a SPA junto da API
cd frontend && npm run build && cd ..
python -m uvicorn api.main:app --port 8000  # http://localhost:8000
```

Endpoints principais (ver `/docs`):

- `GET /api/juiz/pendentes` — pares (resposta × juiz) ainda não avaliados.
- `GET /api/juiz/contagens` — KPIs gerais.
- `GET /api/modelos-juiz` — catálogo de juízes Gemini ativos.
- `POST /api/juiz/executar` — dispara avaliação parcial (corpo: `ids_resposta`,
  `ids_modelo_juiz`, `limite`).
- `GET /api/juiz/eventos/{run_id}` — Server-Sent Events com progresso por tarefa.
- `GET /api/juiz/avaliacoes-recentes` — últimas linhas de
  `vw_avaliacoes_completas`.

---

## Formato do Excel

| Coluna | Obrigatória | Descrição |
|---|---|---|
| `dataset` | ✅ | Nome do dataset (ex: `OAB_Exams`) |
| `dominio` | ✅ | Domínio (ex: `Jurídico`, `Médico`) |
| `enunciado` | ✅ | Texto da pergunta |
| `resposta_ouro` | ✅ | Gabarito oficial |
| `modelo` | ✅ | Nome do modelo candidato |
| `versao` | ✅ | Versão do modelo |
| `precisao` | ✅ | Precisão numérica (ex: `INT4`, `FP16`) |
| `texto_resposta` | ✅ | Resposta gerada pelo modelo |
| `tempo_inferencia_ms` | ➖ | Tempo de inferência em ms |
| `nota_humana` | ➖ | Nota humana 1–5 (para correlação de Spearman) |
| outras colunas | ➖ | Armazenadas como JSONB em `perguntas.metadados` |

---

## Rubrica de Avaliação (Juiz)

| Sub-critério | Descrição | Peso |
|---|---|---|
| `correcao_factual` | Alinhamento com fatos e gabarito oficial | 30% |
| `completude` | Cobre todos os pontos relevantes | 25% |
| `clareza` | Linguagem precisa, sem ambiguidade | 20% |
| `coerencia` | Argumentação lógica e consistente | 15% |
| `relevancia` | Responde diretamente ao que foi perguntado | 10% |

**Nota final** = Σ(nota_critério × peso) → escala [1.0, 5.0]

Cada sub-critério é armazenado individualmente em `rubrica_subcritérios` com sua justificativa.

---

## Métricas de Concordância (Juiz × Humano)

| Métrica | Interpretação |
|---|---|
| **Spearman ρ** | Correlação de ranking — robusta a outliers |
| **Kendall τ** | Concordância de pares — mais conservadora |
| **Cohen's κ (quadrático)** | Acordo ponderado — penaliza discordâncias maiores |

Referência de interpretação do κ:
- κ ≥ 0.80 → quase perfeito
- κ ≥ 0.60 → substancial
- κ ≥ 0.40 → moderado
- κ < 0.40 → fraco

---

## Schema do Banco

```
modelos ──────────────────────────────────────────────────────┐
    id_modelo, nome_modelo, versao, parametro_precisao         │
                                                               │
datasets                                                       │
    id_dataset, nome_dataset, dominio                          │
         │                                                     │
         ▼                                                     │
perguntas                                                      │
    id_pergunta, id_dataset, enunciado, resposta_ouro,         │
    metadados (JSONB)                                          │
         │                                                     │
         ▼                                                     │
respostas_atividade_1 ◄────────────────────────────────────────┘
    id_resposta, id_pergunta, id_modelo,
    texto_resposta, tempo_inferencia_ms
         │
         ▼
avaliacoes_juiz ◄── modelos (juiz)
    id_avaliacao, id_resposta_ativa1, id_modelo_juiz,
    nota_atribuida (NUMERIC), nota_humana,
    chain_of_thought, tokens_prompt, tokens_completion
         │
         ▼
rubrica_subcritérios
    id_subcritério, id_ava