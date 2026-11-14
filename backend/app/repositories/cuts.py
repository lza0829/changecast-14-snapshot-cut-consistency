from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.digest import payload_digest
from app.timeutil import now_iso

# ---------------------------------------------------------------------------
# Stream operation markers: at most one active op per (stream, kind).
# Both an application batch and a cut register here so they can see each
# other and enforce the mutual-exclusion policy.
# ---------------------------------------------------------------------------

OP_APPLY = "apply"
OP_CUT = "cut"

POLICY_REJECT_APPLY = "reject_apply"      # cut running -> application refuses to start
POLICY_SNAPSHOT_READ = "snapshot_read"   # application may run; cut reads one committed snapshot


def active_op(
    conn: sqlite3.Connection,
    stream_id: int,
    kind: str,
    *,
    now: str | None = None,
) -> dict[str, Any] | None:
    now = now or now_iso()
    row = conn.execute(
        """
        SELECT * FROM stream_ops
        WHERE stream_id=? AND kind=? AND status='active' AND expires_at > ?
        ORDER BY id DESC LIMIT 1
        """,
        (stream_id, kind, now),
    ).fetchone()
    return dict(row) if row else None


def begin_op(
    conn: sqlite3.Connection,
    *,
    stream_id: int,
    kind: str,
    token: str,
    policy: str | None,
    ttl_seconds: int,
) -> None:
    from app.timeutil import iso_after

    conn.execute(
        """
        INSERT INTO stream_ops(stream_id, kind, token, policy, status, started_at, expires_at)
        VALUES (?,?,?,?, 'active', ?, ?)
        """,
        (stream_id, kind, token, policy, now_iso(), iso_after(ttl_seconds)),
    )


def finish_op(conn: sqlite3.Connection, token: str) -> None:
    conn.execute(
        "UPDATE stream_ops SET status='finished' WHERE token=? AND status='active'",
        (token,),
    )


def expire_stale_ops(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Mark expired op markers finished (used before evaluating conflicts)."""
    now = now or now_iso()
    cur = conn.execute(
        "UPDATE stream_ops SET status='expired' WHERE status='active' AND expires_at <= ?",
        (now,),
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Cut persistence
# ---------------------------------------------------------------------------


def insert_running_cut(
    conn: sqlite3.Connection,
    *,
    cut_no: str,
    stream: dict[str, Any],
    bind_type: str,
    requested_watermark: int | None,
    bind_batch_id: int | None,
    bind_batch_no: str | None,
    bound_watermark_seq: int,
    read_mode: str,
    policy: str,
    note: str | None,
    started_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO snapshot_cuts(
            cut_no, stream_id, stream_code, status, bind_type,
            requested_watermark, bind_batch_id, bind_batch_no,
            bound_watermark_seq, snapshot_watermark_seq,
            committed_watermark_at_cut, read_mode, policy,
            row_count, alive_count, deleted_count,
            started_at, finished_at, note
        ) VALUES (?,?,?, 'running', ?, ?,?,?, ?, NULL, NULL, ?, ?, 0,0,0, ?, ?, ?)
        """,
        (
            cut_no,
            stream["id"],
            stream["code"],
            bind_type,
            requested_watermark,
            bind_batch_id,
            bind_batch_no,
            bound_watermark_seq,
            read_mode,
            policy,
            started_at,
            started_at,
            note,
        ),
    )
    return int(cur.lastrowid)


def insert_cut_rows(conn: sqlite3.Connection, cut_id: int, rows: list[dict[str, Any]]) -> None:
    conn.executemany(
        """
        INSERT INTO cut_rows(cut_id, entity_key, applied_seq, applied_event_id, deleted, payload_digest)
        VALUES (?,?,?,?,?,?)
        """,
        [
            (
                cut_id,
                r["entity_key"],
                r["applied_seq"],
                r.get("applied_event_id"),
                1 if r["deleted"] else 0,
                payload_digest(r.get("payload")),
            )
            for r in rows
        ],
    )


def complete_cut(
    conn: sqlite3.Connection,
    *,
    cut_id: int,
    snapshot_watermark_seq: int,
    snapshot_batch_id: int | None,
    snapshot_batch_no: str | None,
    committed_watermark_at_cut: int,
    row_count: int,
    alive_count: int,
    deleted_count: int,
    verify_method: str,
    finished_at: str,
) -> None:
    conn.execute(
        """
        UPDATE snapshot_cuts
        SET status='completed', snapshot_watermark_seq=?, snapshot_batch_id=?,
            snapshot_batch_no=?, committed_watermark_at_cut=?,
            row_count=?, alive_count=?, deleted_count=?, verify_method=?,
            failure_reason=NULL, finished_at=?
        WHERE id=? AND status='running'
        """,
        (
            snapshot_watermark_seq,
            snapshot_batch_id,
            snapshot_batch_no,
            committed_watermark_at_cut,
            row_count,
            alive_count,
            deleted_count,
            verify_method,
            finished_at,
            cut_id,
        ),
    )


def fail_cut(conn: sqlite3.Connection, *, cut_id: int, reason: str, finished_at: str) -> None:
    """Mark a cut failed and delete any rows it managed to write.

    A failed cut keeps its identity (so the failure is visible) but can never
    be reported as a usable snapshot: status failed, zero rows, no success
    counts, and no remaining cut_rows.
    """
    conn.execute("DELETE FROM cut_rows WHERE cut_id=?", (cut_id,))
    conn.execute(
        """
        UPDATE snapshot_cuts
        SET status='failed', failure_reason=?, snapshot_watermark_seq=NULL,
            row_count=0, alive_count=0, deleted_count=0, finished_at=?
        WHERE id=? AND status='running'
        """,
        (reason, finished_at, cut_id),
    )


def list_cuts(conn: sqlite3.Connection, *, stream_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = "SELECT * FROM snapshot_cuts WHERE 1=1"
    params: list[Any] = []
    if stream_id is not None:
        sql += " AND stream_id=?"
        params.append(stream_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_cut(conn: sqlite3.Connection, cut_id: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM snapshot_cuts WHERE id=?", (cut_id,)).fetchone()
    return dict(r) if r else None


def get_cut_by_no(conn: sqlite3.Connection, cut_no: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM snapshot_cuts WHERE cut_no=?", (cut_no,)).fetchone()
    return dict(r) if r else None


def list_cut_rows(
    conn: sqlite3.Connection,
    cut_id: int,
    *,
    include_deleted: bool = True,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM cut_rows WHERE cut_id=?"
    if not include_deleted:
        sql += " AND deleted=0"
    sql += " ORDER BY entity_key"
    out: list[dict[str, Any]] = []
    for r in conn.execute(sql, (cut_id,)):
        d = dict(r)
        d["deleted"] = bool(d["deleted"])
        out.append(d)
    return out
