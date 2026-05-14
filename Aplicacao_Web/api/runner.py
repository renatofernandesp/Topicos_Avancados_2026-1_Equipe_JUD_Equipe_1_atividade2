"""Gerenciador de execuções em memória (run_id -> fila de eventos)."""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any

from judge_gemini_service import executar_juiz_gemini_stream

logger = logging.getLogger(__name__)

_DONE_SENTINEL: dict[str, Any] = {"__done__": True}


@dataclass
class Run:
    run_id: str
    total_estimado: int
    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread | None = None
    finalizado: bool = field(default=False)


_runs: dict[str, Run] = {}
_runs_lock = threading.Lock()


def _put_threadsafe(loop: asyncio.AbstractEventLoop,
                    queue: asyncio.Queue[dict[str, Any]],
                    item: dict[str, Any]) -> None:
    asyncio.run_coroutine_threadsafe(queue.put(item), loop)


def _worker(
    run: Run,
    ids_resposta: list[int] | None,
    ids_modelo_juiz: list[int] | None,
    limite: int | None,
    substituir: bool,
    pares: list[tuple[int, int]] | None,
) -> None:
    try:
        for ev in executar_juiz_gemini_stream(
            ids_resposta=ids_resposta,
            ids_modelo_juiz=ids_modelo_juiz,
            limite=limite,
            substituir=substituir,
            pares=pares,
        ):
            _put_threadsafe(run.loop, run.queue, dict(ev))
    except Exception as e:
        logger.exception(
            "Falha global no worker do juiz (run_id=%s): %s",
            run.run_id,
            e,
        )
        _put_threadsafe(run.loop, run.queue, {
            "total": 0,
            "atual": 0,
            "id": None,
            "juiz": None,
            "nota": None,
            "erro": f"{type(e).__name__}: {e}",
            "erro_tipo": type(e).__name__,
            "erro_detalhe": traceback.format_exc()[:4000],
            "subcrit": {},
        })
    finally:
        run.finalizado = True
        _put_threadsafe(run.loop, run.queue, dict(_DONE_SENTINEL))


def start_run(
    *,
    total_estimado: int,
    ids_resposta: list[int] | None,
    ids_modelo_juiz: list[int] | None,
    limite: int | None,
    substituir: bool = False,
    pares: list[tuple[int, int]] | None = None,
) -> Run:
    loop = asyncio.get_running_loop()
    run = Run(
        run_id=uuid.uuid4().hex,
        total_estimado=total_estimado,
        queue=asyncio.Queue(),
        loop=loop,
    )
    with _runs_lock:
        _runs[run.run_id] = run
    t = threading.Thread(
        target=_worker,
        args=(run, ids_resposta, ids_modelo_juiz, limite, substituir, pares),
        daemon=True,
        name=f"juiz-run-{run.run_id[:8]}",
    )
    run.thread = t
    t.start()
    return run


def get_run(run_id: str) -> Run | None:
    with _runs_lock:
        return _runs.get(run_id)


def drop_run(run_id: str) -> None:
    with _runs_lock:
        _runs.pop(run_id, None)


def is_done_event(ev: dict[str, Any]) -> bool:
    return ev.get("__done__") is True
