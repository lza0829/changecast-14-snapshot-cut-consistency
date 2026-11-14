from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app import errors
from app.config import FIXTURES_DIR
from app.db import connect, immediate_txn
from app.engines.project import apply_events
from app.repositories import batches as batch_repo
from app.repositories import cuts as cut_repo
from app.repositories import projections as proj_repo
from app.repositories import streams as stream_repo
from app.timeutil import now_iso

_APPLY_TTL_SECONDS = 120


def _load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"fixture {name} must be a JSON array")
    return data


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "stream_count": conn.execute("SELECT COUNT(*) c FROM project_streams").fetchone()["c"],
            "enabled_streams": conn.execute(
                "SELECT COUNT(*) c FROM project_streams WHERE enabled=1"
            ).fetchone()["c"],
            "batch_count": conn.execute("SELECT COUNT(*) c FROM project_batches").fetchone()["c"],
            "cut_count": conn.execute("SELECT COUNT(*) c FROM snapshot_cuts").fetchone()["c"],
            "completed_cuts": conn.execute(
                "SELECT COUNT(*) c FROM snapshot_cuts WHERE status='completed'"
            ).fetchone()["c"],
            "failed_cuts": conn.execute(
                "SELECT COUNT(*) c FROM snapshot_cuts WHERE status='failed'"
            ).fetchone()["c"],
            "running_cuts": conn.execute(
                "SELECT COUNT(*) c FROM snapshot_cuts WHERE status='running'"
            ).fetchone()["c"],
            "projection_alive": conn.execute(
                "SELECT COUNT(*) c FROM projection_rows WHERE deleted=0"
            ).fetchone()["c"],
            "projection_deleted": conn.execute(
                "SELECT COUNT(*) c FROM projection_rows WHERE deleted=1"
            ).fetchone()["c"],
            "ooo_buffered": conn.execute("SELECT COUNT(*) c FROM ooo_buffer").fetchone()["c"],
            "apply_order": conn.execute(
                "SELECT value FROM settings WHERE key='apply_order'"
            ).fetchone()["value"],
            "cut_policy": conn.execute(
                "SELECT value FROM settings WHERE key='cut_policy'"
            ).fetchone()["value"],
        }
    finally:
        conn.close()


def list_streams() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return stream_repo.list_streams(conn)
    finally:
        conn.close()


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = batch_repo.list_batches(conn, limit=limit)
        streams = {s["id"]: s for s in stream_repo.list_streams(conn)}
        for r in rows:
            s = streams.get(r["stream_id"])
            r["stream_code"] = s["code"] if s else None
            r["stream_title"] = s["title"] if s else None
        return rows
    finally:
        conn.close()


def list_projections(stream_id: int | None = None, include_deleted: bool = True) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = proj_repo.list_projections(
            conn, stream_id=stream_id, include_deleted=include_deleted
        )
        streams = {s["id"]: s for s in stream_repo.list_streams(conn)}
        for r in rows:
            s = streams.get(r["stream_id"])
            r["stream_code"] = s["code"] if s else None
            r["stream_title"] = s["title"] if s else None
        return rows
    finally:
        conn.close()


def list_events(batch_id: int | None = None, stream_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_applied_events(conn, batch_id=batch_id, stream_id=stream_id)
    finally:
        conn.close()


def list_ooo_buffer(stream_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return proj_repo.list_ooo_buffer(conn, stream_id=stream_id)
    finally:
        conn.close()


def list_settings() -> dict[str, str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()


def active_conflicts(stream_id: int | None = None) -> dict[str, Any]:
    """What is currently holding a stream, for the UI to show before acting."""
    conn = connect()
    try:
        out: dict[str, Any] = {"cut": None, "apply": None}
        ids = [stream_id] if stream_id is not None else [s["id"] for s in stream_repo.list_streams(conn)]
        for sid in ids:
            cut = cut_repo.active_op(conn, sid, cut_repo.OP_CUT)
            if cut:
                out["cut"] = cut
            apply_op = cut_repo.active_op(conn, sid, cut_repo.OP_APPLY)
            if apply_op:
                out["apply"] = apply_op
        return out
    finally:
        conn.close()


def run_project(
    stream_id: int,
    note: str | None = None,
    hold_ms: int = 0,
    up_to_seq: int | None = None,
) -> dict[str, Any]:
    """Load CDC fixture, apply by seq, replace projection for the stream.

    up_to_seq bounds the replay (apply only events with seq <= N), which lets
    the workbench build distinct committed states and exercise watermark
    binding. Omitted -> the whole fixture is applied.

    Mutual exclusion with cuts is enforced under the same serialized write
    transaction that reads the stream state, so there is no window between
    "check for a cut" and "start applying".
    """
    import time

    if hold_ms < 0 or hold_ms > 10_000:
        raise ValueError("hold_ms 需在 0..10000 之间")
    if up_to_seq is not None and up_to_seq < 0:
        raise ValueError("up_to_seq 不能为负")

    conn = connect()
    token = f"apply-{uuid4().hex}"
    try:
        with immediate_txn(conn) as tx:
            cut_repo.expire_stale_ops(tx)
            stream = stream_repo.get_stream(tx, stream_id)
            if not stream:
                raise ValueError("stream not found")
            if not stream["enabled"]:
                raise ValueError("stream disabled")

            running_cut = cut_repo.active_op(tx, stream_id, cut_repo.OP_CUT)
            if running_cut:
                if running_cut["policy"] == cut_repo.POLICY_REJECT_APPLY:
                    raise errors.ConflictError(
                        "切面固化进行中，按「拒绝开跑直至切面完成」策略拒绝本次应用"
                    )
                # snapshot_read: allowed. The cut reads its own committed
                # snapshot; uncommitted rows from this batch stay invisible to
                # it because it reads in a WAL snapshot transaction.
            existing_apply = cut_repo.active_op(tx, stream_id, cut_repo.OP_APPLY)
            if existing_apply:
                raise errors.ConflictError("该流已有应用批次进行中")

            events = _load_fixture(stream["fixture"])
            if up_to_seq is not None:
                events = [e for e in events if int(e.get("seq", 0)) <= up_to_seq]
            # Base 0-1: each run rebuilds projection from the selected events
            # by seq. Cross-run idempotency is left for later topics.
            result = apply_events(events, known_event_ids=set())

            now = now_iso()
            seq = tx.execute("SELECT COUNT(*) c FROM project_batches").fetchone()["c"] + 1
            batch_no = f"PB-{now[:10].replace('-', '')}-{seq:04d}"
            cut_repo.begin_op(
                tx,
                stream_id=stream_id,
                kind=cut_repo.OP_APPLY,
                token=token,
                policy=None,
                ttl_seconds=_APPLY_TTL_SECONDS,
            )
            batch_id = batch_repo.insert_batch(
                tx,
                batch_no=batch_no,
                stream_id=stream_id,
                status="completed",
                counts=result["counts"],
                note=note,
                created_at=now,
            )
            proj_repo.replace_stream_projection(
                tx, stream_id=stream_id, rows=result["projection"], updated_at=now
            )
            for ev in result["applied_log"]:
                batch_repo.insert_applied_event(
                    tx, batch_id=batch_id, stream_id=stream_id, event=ev, created_at=now
                )
            stream_repo.set_watermark(tx, stream_id, result["counts"]["max_seq"])

            if hold_ms:
                # Hold with the whole batch written but still uncommitted. A
                # concurrent cut reading in its own snapshot must see the
                # previous committed projection, never these half rows.
                time.sleep(hold_ms / 1000.0)

            cut_repo.finish_op(tx, token)

        batch = batch_repo.get_batch(conn, batch_id)
        assert batch is not None
        batch["stream_code"] = stream["code"]
        batch["stream_title"] = stream["title"]
        batch["apply_order"] = "by_seq"
        batch["counts"] = result["counts"]
        batch["projection_preview"] = proj_repo.list_projections(conn, stream_id=stream_id)[:20]
        batch["event_preview"] = batch_repo.list_applied_events(conn, batch_id=batch_id, limit=20)
        return batch
    except Exception:
        try:
            with immediate_txn(conn) as tx:
                cut_repo.finish_op(tx, token)
        except Exception:
            pass
        raise
    finally:
        conn.close()
