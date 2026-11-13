"""Apply CDC events onto an in-memory projection by seq order.

Base behavior: sort by seq ascending; upsert/delete into projection;
skip duplicate event_id. Out-of-order buffering is left for later topics.
"""

from __future__ import annotations

from typing import Any


def apply_events(
    events: list[dict[str, Any]],
    *,
    known_event_ids: set[str] | None = None,
) -> dict[str, Any]:
    known = set(known_event_ids or ())
    projection: dict[str, dict[str, Any]] = {}
    applied_log: list[dict[str, Any]] = []
    counts = {
        "source_events": len(events),
        "applied_upsert": 0,
        "applied_delete": 0,
        "skipped_duplicate": 0,
        "max_seq": 0,
    }

    ordered = sorted(events, key=lambda e: (int(e.get("seq", 0)), str(e.get("event_id", ""))))

    for ev in ordered:
        event_id = str(ev["event_id"])
        entity_key = str(ev["entity_key"])
        op = str(ev.get("op", "upsert"))
        seq = int(ev.get("seq", 0))
        event_time = str(ev.get("event_time", ""))
        counts["max_seq"] = max(counts["max_seq"], seq)

        if event_id in known:
            counts["skipped_duplicate"] += 1
            applied_log.append(
                {
                    "event_id": event_id,
                    "entity_key": entity_key,
                    "op": op,
                    "seq": seq,
                    "event_time": event_time,
                    "result": "skipped_duplicate",
                    "payload": ev.get("payload"),
                }
            )
            continue

        known.add(event_id)
        if op == "delete":
            projection[entity_key] = {
                "entity_key": entity_key,
                "payload": None,
                "applied_seq": seq,
                "applied_event_id": event_id,
                "deleted": True,
            }
            counts["applied_delete"] += 1
            result = "applied_delete"
        else:
            projection[entity_key] = {
                "entity_key": entity_key,
                "payload": ev.get("payload") or {},
                "applied_seq": seq,
                "applied_event_id": event_id,
                "deleted": False,
            }
            counts["applied_upsert"] += 1
            result = "applied_upsert"

        applied_log.append(
            {
                "event_id": event_id,
                "entity_key": entity_key,
                "op": op,
                "seq": seq,
                "event_time": event_time,
                "result": result,
                "payload": ev.get("payload"),
            }
        )

    alive = [r for r in projection.values() if not r["deleted"]]
    deleted = [r for r in projection.values() if r["deleted"]]
    counts["projected_alive"] = len(alive)
    counts["projected_deleted"] = len(deleted)
    return {
        "counts": counts,
        "projection": list(projection.values()),
        "applied_log": applied_log,
    }
