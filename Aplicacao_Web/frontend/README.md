# Frontend (Vue 3 + PrimeVue)

UI alternativa para a aba "Juiz" do projeto. O Streamlit (`app.py`) continua funcionando em paralelo.

## Pré-requisitos

- Node.js 18+ (recomendado 20+).
- API FastAPI rodando em `http://localhost:8000` (ver raiz do projeto).
- `GEMINI_API_KEY` definida no backend para habilitar a execução.

## Desenvolvimento

```bash
# 1) backend (na raiz do projeto, com .venv ativa)
python -m uvicorn api.main:app --reload --port 8000

# 2) frontend (nesta pasta)
npm install
npm run dev
```

Vite sobe em `http://localhost:5173` e faz proxy de `/api` para `:8000`.

## Build de produção

```bash
npm run build
```

Gera `frontend/dist/`. O FastAPI (`api/main.py`) detecta a pasta automaticamente e
serve a SPA junto com a API em `http://localhost:8000`.
