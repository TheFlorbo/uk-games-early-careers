"""Listing history: how long has this been open, and has it been reposted?

This is the thing no major job board will show you. Employers rarely publish a
posting date, and aggregators happily surface a role that has been sitting open
for six months as though it appeared this morning. We can do better simply by
remembering what we saw yesterday.

Two failure modes matter, and both are handled here:

1. A transient network blip makes every job look like it vanished, then
   reappear -- inflating repost counts. Fixed by requiring a job to be gone for
   REPOST_GRACE_DAYS before its return counts as a repost.

2. One company's board 404s, so all its jobs look closed. Fixed by only ageing
   jobs whose board was successfully fetched this run.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

STATE_PATH = Path("state/seen.json")
REPOST_GRACE_DAYS = 3


def _today() -> date:
    return datetime.utcnow().date()


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def load(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupted state file should cost us history, not the whole run.
        return {}


def save(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def board_key(uid: str) -> str:
    """'greenhouse:hutch:12345' -> 'greenhouse:hutch'"""
    return ":".join(uid.split(":")[:2])


def update(state: dict, records: list[dict], healthy_boards: set[str]) -> list[dict]:
    """Merge this run's results into the stored history and enrich each record.

    Adds to every record:
      first_seen   -- when we first observed it
      days_open    -- how long it has been listed
      repost_count -- times it vanished and came back
      is_new       -- first observed on this run
    """
    today = _today()
    today_s = today.isoformat()
    present = {r["uid"] for r in records}

    for rec in records:
        uid = rec["uid"]
        entry = state.get(uid)

        if entry is None:
            # Prefer the employer's own posted date when the ATS gives us one;
            # otherwise today is the best evidence we have.
            first = _parse(rec.get("posted_at")) or today
            if first > today:
                first = today
            entry = {"first_seen": first.isoformat(), "last_seen": today_s,
                     "repost_count": 0, "gone_since": None}
            rec["is_new"] = True
        else:
            rec["is_new"] = False
            gone = _parse(entry.get("gone_since"))
            if gone and (today - gone).days >= REPOST_GRACE_DAYS:
                entry["repost_count"] = int(entry.get("repost_count", 0)) + 1
            entry["gone_since"] = None
            entry["last_seen"] = today_s

        state[uid] = entry
        first_seen = _parse(entry["first_seen"]) or today
        rec["first_seen"] = entry["first_seen"]
        rec["days_open"] = max((today - first_seen).days, 0)
        rec["repost_count"] = int(entry.get("repost_count", 0))

    # Age out anything absent -- but only for boards we actually reached, so a
    # broken source doesn't silently mark all its jobs closed.
    for uid, entry in state.items():
        if uid in present:
            continue
        if board_key(uid) not in healthy_boards:
            continue
        if not entry.get("gone_since"):
            entry["gone_since"] = today_s

    return records


def prune(state: dict, drop_after_days: int) -> dict:
    """Forget listings that closed long ago, so the state file stays small."""
    cutoff = _today() - timedelta(days=max(drop_after_days, 30) + 30)
    kept = {}
    for uid, entry in state.items():
        gone = _parse(entry.get("gone_since"))
        last = _parse(entry.get("last_seen"))
        if gone and gone < cutoff:
            continue
        if last and last < cutoff:
            continue
        kept[uid] = entry
    return kept
