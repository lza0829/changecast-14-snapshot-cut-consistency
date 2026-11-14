"""Reconstruct a projection as it stood at a given watermark.

The applied-event log is the source of truth: replay events with seq <=
watermark in (seq, id) order and fold each into the projection. This is what
lets a cut prove its content matches its bound watermark even if the live
projection has since moved on.
"""

from __future__ import annotations

from typing import Any

from app.engines.project import apply_events


def project_events_at(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return projection rows produced by replaying the given applied events."""
    replay = [
        {
            "event_id": e["event_id"],
            "entity_key": e["entity_key"],
            "op": e.get("op", "upsert"),
            "seq": e["seq"],
            "event_time": e.get("event_time", ""),
            "payload": e.get("payload"),
        }
        for e in events
    ]
    result = apply_events(replay)
    return result["projection"]


def counts_of(rows: list[dict[str, Any]]) -> dict[str, int]:
    alive = sum(1 for r in rows if not r["deleted"])
    deleted = sum(1 for r in rows if r["deleted"])
    return {"row_count": len(rows), "alive_count": alive, "deleted_count": deleted}
