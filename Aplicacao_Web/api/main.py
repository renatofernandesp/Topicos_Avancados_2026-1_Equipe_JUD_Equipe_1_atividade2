"""FastAPI: API HTTP para o frontend Vue/PrimeVue do juiz Gemini.

Dev:
  python -m uvicorn api.main:app --reload --port 8000

Prod (com SPA buildada):
  npm run build  # em frontend/
  python -m uvicorn api.main:app --port 8000
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes_juiz import router as juiz_router

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG if os.getenv("JUDGE_DEBUG_LOG", "").lower() in ("1", "true", "yes") else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="LLM-as-a-Judge API", version="0.1.0")

_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(juiz_router)


_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST.exists():
    assets_dir = _DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_DIST / "index.html"))
