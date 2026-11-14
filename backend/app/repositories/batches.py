from __future__ import annotations

import json
from typing import Any

import sqlite3


def insert_batch(
    conn: sqlite3.Connection,
    *,
    batch_no: str,
    stream_id: int,
    status: str,
    counts: dict[str, int],
    note: str | None,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO project_batches(
            batch_no, stream_id, status, source_events, applied_upsert, applied_delete,
            skipped_duplicate, projected_alive, projected_deleted, max_seq, note, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            batch_no,
            stream_id,
            status,
            counts["source_events"],
            counts["applied_upsert"],
            counts["applied_delete"],
            counts["skipped_duplicate"],
            counts["projected_alive"],
            counts["projected_deleted"],
            counts["max_seq"],
            note,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_batches(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM project_batches ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM project_batches WHERE id=?", (batch_id,)).fetchone()
    return dict(r) if r else None


def insert_applied_event(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    stream_id: int,
    event: dict[str, Any],
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO applied_events(
            batch_id, stream_id, event_id, entity_key, op, seq, event_time,
            result, payload_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            batch_id,
            stream_id,
            event["event_id"],
            event["entity_key"],
            event["op"],
            event["seq"],
            event["event_time"],
            event["result"],
            json.dumps(event.get("payload"), ensure_ascii=False)
            if event.get("payload") is not None
            else None,
            created_at,
        ),
    )


def list_applied_events(
    conn: sqlite3.Connection,
    *,
    batch_id: int | None = None,
    stream_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM applied_events WHERE 1=1"
    params: list[Any] = []
    if batch_id is not None:
        sql += " AND batch_id=?"
        params.append(batch_id)
    if stream_id is not None:
        sql += " AND stream_id=?"
        params.append(stream_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    out: list[dict[str, Any]] = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        raw = d.pop("payload_json", None)
        d["payload"] = json.loads(raw) if raw else None
        out.append(d)
    return out


def get_batch_by_no(conn: sqlite3.Connection, batch_no: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM project_batches WHERE batch_no=?", (batch_no,)).fetchone()
    return dict(r) if r else None


def list_events_up_to(
    conn: sqlite3.Connection, stream_id: int, watermark_seq: int
) -> list[dict[str, Any]]:
    """Applied events at seq <= watermark, oldest first.

    Rows are ordered by (seq, id) so replaying them reproduces the projection
    exactly as it stood once watermark_seq had been applied.
    """
    rows = conn.execute(
        """
        SELECT * FROM applied_events
        WHERE stream_id=? AND seq<=? AND result IN ('applied_upsert','applied_delete')
        ORDER BY seq ASC, id ASC
        """,
        (stream_id, watermark_seq),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.pop("payload_json", None)
        d["payload"] = json.loads(raw) if raw else None
        out.append(d)
    return out

