"""Read-only trophy report for the launcher.

The game writes two local sources:

* ``<user>/trophy_cache/metadata.json`` - trophy names, descriptions, grades and
  icon filenames extracted from the player's own TRP.
* ``<user>/trophies.txt`` - local unlock history as ``<id> <unix timestamp>``.

The launcher must never invent names, dates, rarity or completion.  A v1 cache
contains only placeholder names and is reported as unavailable for details.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

GRADES = ("B", "S", "G", "P")
GRADE_ORDER = {"P": 0, "G": 1, "S": 2, "B": 3, "?": 4}
PLACEHOLDER_NAME = re.compile(r"^Trophy #\d+$")


@dataclass(frozen=True)
class TrophyEntry:
    id: int
    name: str
    description: str
    grade: str
    hidden: bool
    icon: Path | None
    earned: bool
    unlocked_at: int | None
    name_available: bool


@dataclass(frozen=True)
class TrophyReport:
    entries: tuple[TrophyEntry, ...]
    set_title: str
    set_description: str
    metadata_available: bool
    metadata_complete: bool
    reason: str | None
    earned: int
    total: int | None
    completion: int | None
    grade_counts: dict[str, int]
    local_unlocks: int
    orphan_unlocks: tuple[int, ...]
    stale: bool


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, "missing"
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None, "malformed"
    if not isinstance(data, dict):
        return None, "malformed"
    return data, None


def _read_unlocks(path: Path) -> dict[int, int]:
    """Strictly parse local history; malformed lines are ignored, last duplicate wins."""
    unlocks: dict[int, int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return unlocks
    for line in lines:
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        trophy_id, timestamp = int(parts[0]), int(parts[1])
        if 0 <= trophy_id < 128 and timestamp > 0:
            unlocks[trophy_id] = timestamp
    return unlocks


def _safe_icon(icons: Path, name: Any, trophy_id: int) -> Path | None:
    if not isinstance(name, str) or not name.strip():
        name = f"TROP{trophy_id:03d}.PNG"
    # The metadata is external input: never allow a path outside the icon folder.
    candidate_name = Path(name).name
    if candidate_name in ("", ".", ".."):
        return None
    candidate = icons / candidate_name
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _pack_size(game_dir: Path | None) -> int | None:
    if game_dir is None:
        return None
    folder = game_dir / "sce_sys" / "trophy"
    for name in ("trophy00.trp", "TROPHY.TRP"):
        candidate = folder / name
        try:
            if candidate.is_file():
                return candidate.stat().st_size
        except OSError:
            pass
    return None


def load_trophy_report(user_dir: str | Path, game_dir: str | Path | None = None) -> TrophyReport:
    """Load the local trophy cache without modifying it or the game files."""
    user = Path(user_dir).expanduser()
    game = Path(game_dir).expanduser() if game_dir else None
    cache = user / "trophy_cache" / "metadata.json"
    icons = user / "trophy_cache" / "icons"
    unlocks = _read_unlocks(user / "trophies.txt")

    data, problem = _read_json(cache)
    if data is None:
        reason = ("No trophy cache yet. Import keys.json in Settings -> Game & Data, "
                  "then launch the game once." if problem == "missing"
                  else "Trophy metadata is malformed.")
        return TrophyReport((), "Bloodborne", "", False, False, reason, 0, None, None, {},
                            len(unlocks), tuple(sorted(unlocks)), False)

    version = data.get("version")
    complete = data.get("complete") is True
    raw_entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    entries: list[TrophyEntry] = []
    seen: set[int] = set()
    all_names_available = bool(raw_entries)

    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        try:
            trophy_id = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        if not 0 <= trophy_id < 128 or trophy_id in seen:
            continue
        seen.add(trophy_id)
        name = raw.get("name") if isinstance(raw.get("name"), str) else ""
        description = raw.get("description") if isinstance(raw.get("description"), str) else ""
        grade = str(raw.get("grade") or "?").upper()
        if grade not in GRADES:
            grade = "?"
        name_available = bool(name) and not PLACEHOLDER_NAME.fullmatch(name) and grade in GRADES
        all_names_available = all_names_available and name_available
        icon = _safe_icon(icons, raw.get("icon"), trophy_id)
        entries.append(TrophyEntry(
            id=trophy_id,
            name=name,
            description=description,
            grade=grade,
            hidden=raw.get("hidden") is True,
            icon=icon,
            earned=trophy_id in unlocks,
            unlocked_at=unlocks.get(trophy_id),
            name_available=name_available,
        ))

    metadata_complete = bool(complete and version == 2 and entries)
    metadata_available = bool(metadata_complete and all_names_available)
    if not metadata_available:
        if version != 2:
            reason = "Trophy metadata uses an older format."
        elif not complete:
            reason = "The game has not decrypted the trophy pack yet."
        else:
            reason = "Trophy metadata is incomplete."
    else:
        reason = None

    entry_ids = {entry.id for entry in entries}
    orphan_unlocks = tuple(sorted(set(unlocks) - entry_ids))
    total = len(entries) if metadata_available else None
    earned = sum(1 for entry in entries if entry.earned) if metadata_available else 0
    completion = (earned * 100 // total) if total else None
    grade_counts = {grade: 0 for grade in GRADES}
    if metadata_available:
        for entry in entries:
            grade_counts[entry.grade] += 1

    pack_size = _pack_size(game)
    source_size = data.get("source_size")
    stale = bool(isinstance(source_size, int) and pack_size is not None and source_size != pack_size)

    title = data.get("title") if isinstance(data.get("title"), str) and data.get("title") else "Bloodborne"
    description = data.get("description") if isinstance(data.get("description"), str) else ""
    return TrophyReport(
        entries=tuple(entries),
        set_title=title,
        set_description=description,
        metadata_available=metadata_available,
        metadata_complete=metadata_complete,
        reason=reason,
        earned=earned,
        total=total,
        completion=completion,
        grade_counts=grade_counts,
        local_unlocks=len(unlocks),
        orphan_unlocks=orphan_unlocks,
        stale=stale,
    )
