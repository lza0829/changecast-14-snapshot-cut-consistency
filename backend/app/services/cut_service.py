from __future__ import annotations

import time
from typing import Any

from app import errors
from app.db import connect, immediate_txn, snapshot_txn
from app.engines.cut import counts_of, project_events_at
from app.repositories import batches as batch_repo
from app.repositories import cuts as cut_repo
from app.repositories import streams as stream_repo
from app.timeutil import now_iso

POLICY_REJECT_APPLY = cut_repo.POLICY_REJECT_APPLY
POLICY_SNAPSHOT_READ = cut_repo.POLICY_SNAPSHOT_READ
VALID_POLICIES = {POLICY_REJECT_APPLY, POLICY_SNAPSHOT_READ}

# A cut marker outlives the cut by a wide margin so an application started
# during a long cut still sees it; stale markers are reaped on write.
_OP_TTL_SECONDS = 120


def _policy(conn, requested: str | None) -> str:
    if requested is not None:
        if requested not in VALID_POLICIES:
            raise ValueError(f"未知互斥策略: {requested}")
        return requested
    row = conn.execute("SELECT value FROM settings WHERE key='cut_policy'").fetchone()
    value = row["value"] if row else POLICY_REJECT_APPLY
    return value if value in VALID_POLICIES else POLICY_REJECT_APPLY


def _next_cut_no(conn) -> str:
    seq = conn.execute("SELECT COUNT(*) c FROM snapshot_cuts").fetchone()["c"] + 1
    day = now_iso()[:10].replace("-", "")
    return f"SC-{day}-{seq:04d}"


def _resolve_binding(conn, stream_id: int, requested_watermark: int | None, batch_no: str | None) -> dict[str, Any]:
    """Resolve the cut's explicit binding to (bind_type, watermark, batch)."""
    if (requested_watermark is None) == (batch_no is None):
        raise ValueError("切面必须且只能绑定一个明确水位或一个已成功批次号")

    if batch_no is not None:
        batch = batch_repo.get_batch_by_no(conn, batch_no)
        if batch is None:
            raise ValueError(f"批次 {batch_no} 不存在")
        if batch["stream_id"] != stream_id:
            raise ValueError("批次不属于该投影流")
        if batch["status"] != "completed":
            raise ValueError(f"批次 {batch_no} 状态为 {batch['status']}，不能作为切面绑定")
        # The batch is a point-in-time snapshot of the stream: bind to its own
        # recorded maximum seq, which need not be the latest committed one.
        return {
            "bind_type": "batch",
            "requested_watermark": None,
            "bind_batch_id": batch["id"],
            "bind_batch_no": batch["batch_no"],
            "watermark": int(batch["max_seq"]),
            "batch": batch,
        }

    wm = int(requested_watermark)  # type: ignore[arg-type]
    if wm < 0:
        raise ValueError("水位不能为负")
    return {
        "bind_type": "watermark",
        "requested_watermark": wm,
        "bind_batch_id": None,
        "bind_batch_no": None,
        "watermark": wm,
        "batch": None,
    }


def _replay_at(conn, stream_id: int, watermark: int) -> list[dict[str, Any]]:
    events = batch_repo.list_events_up_to(conn, stream_id, watermark)
    return project_events_at(events)


def _verify_against_batch(rows: list[dict[str, Any]], batch: dict[str, Any]) -> None:
    c = counts_of(rows)
    if c["alive_count"] != batch["projected_alive"] or c["deleted_count"] != batch["projected_deleted"]:
        raise errors.ConflictError(
            "切面重放计数与绑定批次的记录不一致："
            f"重放 存活{c['alive_count']}/已删{c['deleted_count']}，"
            f"批次记录 存活{batch['projected_alive']}/已删{batch['projected_deleted']}"
        )


def create_cut(
    *,
    stream_id: int,
    watermark_seq: int | None = None,
    batch_no: str | None = None,
    policy: str | None = None,
    hold_ms: int = 0,
    note: str | None = None,
) -> dict[str, Any]:
    """Freeze a projection cut bound to an explicit watermark or batch no.

    Phase 1 (write txn): validate the stream/binding, publish a 'running' cut
    marker plus a stream op marker so concurrent applications can see the cut.
    Phase 2: optionally hold (test/demo), then read one committed snapshot and
    stage the rows.
    Phase 3 (write txn): atomically write cut_rows and mark the cut completed.
    Any failure marks the cut failed, removes its rows, and leaves no usable
    snapshot behind.
    """
    if hold_ms < 0 or hold_ms > 10_000:
        raise ValueError("hold_ms 需在 0..10000 之间")

    conn = connect()
    cut_id: int | None = None
    token: str | None = None
    try:
        # Phase 1: publish the marker (BEGIN IMMEDIATE waits for any in-flight
        # application transaction to commit, so we never observe a half batch).
        with immediate_txn(conn) as tx:
            cut_repo.expire_stale_ops(tx)
            stream = stream_repo.get_stream(tx, stream_id)
            if not stream:
                raise ValueError("投影流不存在")
            binding = _resolve_binding(tx, stream_id, watermark_seq, batch_no)
            chosen_policy = _policy(tx, policy)

            committed_now = stream_repo.committed_watermark(tx, stream_id)
            if binding["watermark"] > committed_now:
                # Reject before creating any cut record: there is simply no
                # committed projection at that watermark to bind to.
                raise errors.ConflictError(
                    f"绑定水位 {binding['watermark']} 超过当前已提交水位 {committed_now}"
                )

            now = now_iso()
            cut_no = _next_cut_no(tx)
            cut_id = cut_repo.insert_running_cut(
                tx,
                cut_no=cut_no,
                stream=stream,
                bind_type=binding["bind_type"],
                requested_watermark=binding["requested_watermark"],
                bind_batch_id=binding["bind_batch_id"],
                bind_batch_no=binding["bind_batch_no"],
                bound_watermark_seq=binding["watermark"],
                read_mode="committed_snapshot",
                policy=chosen_policy,
                note=note,
                started_at=now,
            )
            token = f"cut-{cut_no}"
            cut_repo.begin_op(
                tx,
                stream_id=stream_id,
                kind=cut_repo.OP_CUT,
                token=token,
                policy=chosen_policy,
                ttl_seconds=_OP_TTL_SECONDS,
            )

        if hold_ms:
            time.sleep(hold_ms / 1000.0)

        # Phase 2: one read transaction = one committed snapshot. Rows written
        # by an application that has not committed are invisible here.
        with snapshot_txn(conn) as snap:
            committed = stream_repo.committed_watermark(snap, stream_id)
            if binding["watermark"] > committed:
                raise errors.ConflictError(
                    f"绑定水位 {binding['watermark']} 超过已提交水位 {committed}，"
                    "无法证明该时刻的投影"
                )
            # The batch that anchors this cut's content: the one whose max seq
            # equals the bound watermark (a batch-bound cut names the very batch
            # it was bound to).
            anchor_batch = binding["batch"]
            if anchor_batch is None:
                anchor_batch = next(
                    (
                        b
                        for b in batch_repo.list_batches(snap, limit=200)
                        if b["stream_id"] == stream_id
                        and b["status"] == "completed"
                        and b["max_seq"] == binding["watermark"]
                    ),
                    None,
                )
            rows = _replay_at(snap, stream_id, binding["watermark"])
            if binding["batch"] is not None:
                _verify_against_batch(rows, binding["batch"])
            counts = counts_of(rows)
            snapshot_point = committed
            live_rows = _live_projection_rows(snap, stream_id)
            live_matches: bool | None
            if binding["watermark"] == snapshot_point:
                # The cut is bound to the very tip of committed history, so its
                # rows must equal the live projection exactly. Any drift is a
                # real inconsistency, not a concurrency artefact.
                if live_rows != _row_signature(rows):
                    raise errors.ConflictError(
                        "切面行集合与当前投影快照不一致，拒绝固化"
                    )
                live_matches = True
                verify_method = (
                    "batch_counts+live_snapshot"
                    if binding["batch"] is not None
                    else "live_snapshot"
                )
            else:
                # A concurrent (or later) application advanced the committed
                # watermark. The cut proves its bound watermark from the log.
                live_matches = None
                verify_method = (
                    "batch_counts"
                    if binding["batch"] is not None
                    else "log_replay"
                )

        # Phase 3: publish rows + success atomically.
        with immediate_txn(conn) as tx:
            cut_repo.insert_cut_rows(tx, cut_id, rows)
            cut_repo.complete_cut(
                tx,
                cut_id=cut_id,
                snapshot_watermark_seq=snapshot_point,
                snapshot_batch_id=anchor_batch["id"] if anchor_batch else None,
                snapshot_batch_no=anchor_batch["batch_no"] if anchor_batch else None,
                committed_watermark_at_cut=snapshot_point,
                row_count=counts["row_count"],
                alive_count=counts["alive_count"],
                deleted_count=counts["deleted_count"],
                verify_method=verify_method,
                finished_at=now_iso(),
            )
            cut_repo.finish_op(tx, token)
            cut = cut_repo.get_cut(tx, cut_id)
            assert cut is not None
            cut["rows"] = cut_repo.list_cut_rows(tx, cut_id)
            cut["verification"] = {
                "bound_watermark_seq": binding["watermark"],
                "snapshot_watermark_seq": snapshot_point,
                "row_count": counts["row_count"],
                "alive_count": counts["alive_count"],
                "deleted_count": counts["deleted_count"],
                "live_matches_bound": live_matches,
                "verify_method": verify_method,
            }
            return cut
    except errors.ConflictError as e:
        _abandon(conn, cut_id, token, str(e))
        raise
    except Exception as e:  # noqa: BLE001 - any failure must leave no usable cut
        _abandon(conn, cut_id, token, str(e) or "切面固化失败")
        raise
    finally:
        conn.close()


def _abandon(conn, cut_id: int | None, token: str | None, reason: str) -> None:
    """Mark a failed cut failed, drop its rows, and release the op marker."""
    try:
        with immediate_txn(conn) as tx:
            if cut_id is not None:
                cut_repo.fail_cut(tx, cut_id=cut_id, reason=reason, finished_at=now_iso())
            if token is not None:
                cut_repo.finish_op(tx, token)
    except Exception:
        # Never let cleanup mask the original failure.
        pass


def _row_signature(rows: list[dict[str, Any]]) -> list[tuple]:
    return sorted(
        (r["entity_key"], int(r["applied_seq"]), bool(r["deleted"]), r.get("payload"))
        for r in rows
    )


def _live_projection_rows(conn, stream_id: int) -> list[tuple]:
    """Signature of the stream's current projection rows."""
    from app.repositories import projections as proj_repo

    rows = proj_repo.list_projections(conn, stream_id=stream_id, include_deleted=True)
    return sorted(
        (r["entity_key"], int(r["applied_seq"]), bool(r["deleted"]), r["payload"])
        for r in rows
    )


def list_cuts(stream_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return cut_repo.list_cuts(conn, stream_id=stream_id, limit=limit)
    finally:
        conn.close()


def get_cut(cut_id: int, include_deleted: bool = True) -> dict[str, Any] | None:
    conn = connect()
    try:
        cut = cut_repo.get_cut(conn, cut_id)
        if cut is None:
            return None
        rows = cut_repo.list_cut_rows(conn, cut_id, include_deleted=include_deleted)
        cut["rows"] = rows
        alive = sum(1 for r in rows if not r["deleted"]) if include_deleted else len(rows)
        cut["returned_rows"] = len(rows)
        cut["returned_alive"] = alive
        return cut
    finally:
        conn.close()


def verify_cut(cut_id: int) -> dict[str, Any]:
    """Re-prove a completed cut against the committed event log.

    Reads one committed snapshot, replays the log up to the cut's bound
    watermark, and compares row-by-row with what the cut recorded. A completed
    cut whose row set no longer reproduces is reported as a mismatch — the
    cut is never silently trusted.
    """
    from app.digest import payload_digest

    conn = connect()
    try:
        with snapshot_txn(conn) as snap:
            cut = cut_repo.get_cut(snap, cut_id)
            if cut is None:
                raise ValueError("切面不存在")
            if cut["status"] != "completed":
                return {
                    "cut": cut,
                    "ok": False,
                    "reason": f"切面状态为 {cut['status']}，不是可核验的已完成切面",
                }
            stored = cut_repo.list_cut_rows(snap, cut_id)
            rows = _replay_at(snap, cut["stream_id"], cut["bound_watermark_seq"])
            counts = counts_of(rows)
            replay_sig = sorted(
                (r["entity_key"], int(r["applied_seq"]), bool(r["deleted"]), payload_digest(r.get("payload")))
                for r in rows
            )
            stored_sig = sorted(
                (r["entity_key"], int(r["applied_seq"]), bool(r["deleted"]), r["payload_digest"])
                for r in stored
            )
            committed = stream_repo.committed_watermark(snap, cut["stream_id"])
            mismatched = sorted(
                {a[0] for a in set(replay_sig) ^ set(stored_sig)}
            )
            ok = (
                replay_sig == stored_sig
                and cut["row_count"] == counts["row_count"]
                and cut["alive_count"] == counts["alive_count"]
                and cut["deleted_count"] == counts["deleted_count"]
            )
            return {
                "cut": cut,
                "ok": ok,
                "replay": {
                    "watermark_seq": cut["bound_watermark_seq"],
                    "row_count": counts["row_count"],
                    "alive_count": counts["alive_count"],
                    "deleted_count": counts["deleted_count"],
                },
                "recorded": {
                    "row_count": cut["row_count"],
                    "alive_count": cut["alive_count"],
                    "deleted_count": cut["deleted_count"],
                },
                "committed_watermark_now": committed,
                "mismatched_entity_keys": mismatched,
                "reason": None if ok else "重放行集合与切面记录不一致",
            }
    finally:
        conn.close()
