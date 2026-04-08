from __future__ import annotations

import json
import math
import time
from pathlib import Path


def now_ms() -> int:
    return int(time.time() * 1000)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def signed_bps(lhs: float | None, rhs: float | None) -> float | None:
    if lhs is None or rhs in (None, 0):
        return None
    return ((lhs - rhs) / rhs) * 10_000


def safe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        return None
    return None


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def write_json(path: str | Path, payload: object) -> None:
    ensure_parent(path)
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: str | Path, payload: object) -> None:
    ensure_parent(path)
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def parse_jsonish_list(raw: object) -> list[object]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []
    return []


def short_slug(value: str | None, width: int = 34) -> str:
    text = (value or "-").strip()
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."
