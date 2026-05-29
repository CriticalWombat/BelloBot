import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

VOTES_FILE = Path(os.getenv("VOTES_PATH", "data/votes.json"))


def _hash_items(items: list[str]) -> str:
    key = "\n".join(sorted(items))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not VOTES_FILE.exists():
        return {"sessions": []}
    with VOTES_FILE.open() as f:
        return json.load(f)


def _save(data: dict):
    VOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with VOTES_FILE.open("w") as f:
        json.dump(data, f, indent=2)


def _active_session(data: dict) -> dict | None:
    for s in data["sessions"]:
        if s["ended_at"] is None:
            return s
    return None


def _ensure_notes(session: dict):
    """Backfill the notes field for sessions created before notes were introduced."""
    if "notes" not in session:
        session["notes"] = {n: [] for n in session["items"]}


def _get_or_create_session(data: dict, current_items: list[str]) -> tuple[dict, bool]:
    """
    Return the active session, creating a new one if none exists or the menu
    has changed.  Also closes the previous session when rotating.

    Returns (session, new_session_started).
    """
    current_hash = _hash_items(current_items)
    active = _active_session(data)

    if active is not None and active["menu_hash"] == current_hash:
        _ensure_notes(active)
        return active, False

    if active is not None:
        active["ended_at"] = _now_iso()

    new_id = len(data["sessions"]) + 1
    session = {
        "id": new_id,
        "menu_hash": current_hash,
        "items": current_items,
        "votes": {n: {} for n in current_items},
        "notes": {n: [] for n in current_items},
        "started_at": _now_iso(),
        "ended_at": None,
    }
    data["sessions"].append(session)
    return session, True


def cast_vote(
    item_name: str,
    current_items: list[str],
    user_id: str,
    user_name: str,
) -> tuple[int | None, bool]:
    """
    Record a vote for item_name by user_id.

    Returns (new_count, new_session_started).
    Returns (None, False) if the user has already voted this session.
    """
    data = _load()
    active, new_session = _get_or_create_session(data, current_items)

    already_voted = any(user_id in voters for voters in active["votes"].values())
    if already_voted:
        return None, False

    active["votes"].setdefault(item_name, {})[user_id] = user_name
    _save(data)
    return len(active["votes"][item_name]), new_session


def add_note(
    item_name: str,
    current_items: list[str],
    user_id: str,
    user_name: str,
    text: str,
) -> bool:
    """
    Append a note to item_name for the current session.
    Returns True if a new session was started (menu changed), False otherwise.
    """
    data = _load()
    active, new_session = _get_or_create_session(data, current_items)

    active["notes"].setdefault(item_name, []).append({
        "user_id": user_id,
        "user_name": user_name,
        "text": text,
        "timestamp": _now_iso(),
    })
    _save(data)
    return new_session


def get_active_results() -> dict | None:
    """Return the active session dict, or None if no activity yet."""
    data = _load()
    active = _active_session(data)
    if active:
        _ensure_notes(active)
    return active


def get_archived_sessions() -> list[dict]:
    """Return all completed sessions oldest-first, with notes backfilled."""
    data = _load()
    sessions = [s for s in data["sessions"] if s["ended_at"] is not None]
    for s in sessions:
        _ensure_notes(s)
    return sessions


def get_active_items() -> list[str]:
    """Return item names from the active session for cache seeding on restart."""
    active = _active_session(_load())
    return active["items"] if active else []
