"""Server-Sent Events helpers (sem dependências externas)."""

from __future__ import annotations

import json
from typing import Any


def sse_format(data: Any, event: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"
