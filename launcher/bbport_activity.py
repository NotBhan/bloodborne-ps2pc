"""Small, real activity journal for the launcher's Game Details screen.

Only events that actually happened are recorded.  The journal is capped and
stored next to the launcher settings, so reopening the launcher does not
invent a timeline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

EVENT_LIMIT = 20


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_events(path: str | Path, limit: int = EVENT_LIMIT) -> list[dict[str, Any]]:
    data = _load_payload(Path(path))
    raw = data.get("events")
    if not isinstance(raw, list):
        return []
    events: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        when = item.get("time")
        kind = item.get("kind")
        text = item.get("text")
        if isinstance(when, (int, float)) and isinstance(kind, str) and isinstance(text, str):
            events.append({"time": int(when), "kind": kind, "text": text})
    events.sort(key=lambda item: item["time"], reverse=True)
    return events[:max(0, limit)]


def _write_payload(destination: Path, events: list[dict[str, Any]], playtime: int) -> None:
    payload = json.dumps({"events": events, "playtime_seconds": max(0, int(playtime))},
                         indent=2, ensure_ascii=False) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.",
                                     suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_playtime(path: str | Path) -> int:
    value = _load_payload(Path(path)).get("playtime_seconds", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def add_playtime(path: str | Path, seconds: int | float) -> int:
    """Add a real session duration and persist it with the journal."""
    destination = Path(path)
    total = load_playtime(destination) + max(0, int(seconds))
    _write_payload(destination, load_events(destination, limit=EVENT_LIMIT), total)
    return total


def record_event(path: str | Path, kind: str, text: str, timestamp: float | None = None) -> dict[str, Any]:
    """Prepend a real event and persist the capped journal atomically."""
    destination = Path(path)
    event = {"time": int(timestamp if timestamp is not None else time.time()),
             "kind": str(kind), "text": str(text)}
    events = [event, *load_events(destination, limit=EVENT_LIMIT - 1)]
    _write_payload(destination, events[:EVENT_LIMIT], load_playtime(destination))
    return event
