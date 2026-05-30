import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

VOTES_FILE = Path(os.getenv("VOTES_PATH", "data/votes.json"))

TIER_WEIGHTS = {"gold": 3, "silver": 2, "bronze": 1}
TIER_ICONS   = {"gold": "🥇", "silver": "🥈", "bronze": "🥉"}


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
    has changed.  Closes the previous session when rotating.

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
        "votes": {},
        "notes": {n: [] for n in current_items},
        "started_at": _now_iso(),
        "ended_at": None,
    }
    data["sessions"].append(session)
    return session, True


def compute_scores(votes: dict) -> dict[str, dict]:
    """
    Derive per-drink scores from the per-user ballot structure.

    Returns {drink: {"score": int, "gold": [names], "silver": [names], "bronze": [names]}}
    Only drinks that received at least one vote are included.
    """
    scores: dict[str, dict] = {}
    for ballot in votes.values():
        if not isinstance(ballot, dict) or "user_name" not in ballot:
            continue
        name = ballot["user_name"]
        for tier in ("gold", "silver", "bronze"):
            drink = ballot.get(tier)
            if not drink:
                continue
            if drink not in scores:
                scores[drink] = {"score": 0, "gold": [], "silver": [], "bronze": []}
            scores[drink]["score"] += TIER_WEIGHTS[tier]
            scores[drink][tier].append(name)
    return scores


def cast_vote(
    item_name: str,
    current_items: list[str],
    user_id: str,
    user_name: str,
    tier: str,
) -> tuple[str | None, bool]:
    """
    Assign tier ("gold", "silver", or "bronze") to item_name for user_id.

    If the user already had that tier on a different drink, it is displaced.
    Returns (displaced_drink_or_None, new_session_started).
    """
    data = _load()
    active, new_session = _get_or_create_session(data, current_items)

    ballot = active["votes"].setdefault(user_id, {
        "user_name": user_name,
        "gold": None,
        "silver": None,
        "bronze": None,
    })
    ballot["user_name"] = user_name  # refresh display name in case it changed

    displaced = ballot.get(tier)          # drink previously holding this tier
    ballot[tier] = item_name
    _save(data)
    return displaced if displaced != item_name else None, new_session


def add_note(
    item_name: str,
    current_items: list[str],
    user_id: str,
    user_name: str,
    text: str,
) -> bool:
    """
    Append a note to item_name for the current session.
    Returns True if a new session was started (menu changed).
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
