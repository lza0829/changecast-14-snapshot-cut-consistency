from __future__ import annotations

import json
from typing import Any

import sqlite3


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["payload_fields"] = json.loads(d.pop("payload_fields_json"))
    d["enabled"] = bool(d["enabled"])
    return d


def list_streams(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM project_streams ORDER BY id").fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_stream(conn: sqlite3.Connection, stream_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM project_streams WHERE id=?", (stream_id,)).fetchone())


def set_watermark(conn: sqlite3.Connection, stream_id: int, watermark_seq: int) -> None:
    conn.execute(
        "UPDATE project_streams SET watermark_seq=? WHERE id=?",
        (watermark_seq, stream_id),
    )


def committed_watermark(conn: sqlite3.Connection, stream_id: int) -> int:
    """The watermark committed together with the live projection.

    project_streams.watermark_seq is written in the same transaction as the
    projection replacement, so it is the position the current projection has
    actually reached — never a partially-applied position.
    """
    r = conn.execute(
        "SELECT watermark_seq FROM project_streams WHERE id=?", (stream_id,)
    ).fetchone()
    return int(r["watermark_seq"]) if r else 0
