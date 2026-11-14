"""Guarantee tests for projection cuts: binding, snapshot reads, mutual
exclusion, and failure hygiene."""

from __future__ import annotations

import threading
import time

import pytest

from app import errors
from app.db import connect
from app.seed import init_db
from app.services import cut_service as cs
from app.services import project_service as ps


@pytest.fixture()
def db(tmp_path, monkeypatch):
    # app.db reads DATA_DIR at import time; point the module constant at a
    # fresh database per test.
    import app.db as dbmod

    db_file = tmp_path / "app.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    init_db()
    return db_file


def _active_ops():
    c = connect()
    try:
        return c.execute(
            "SELECT COUNT(*) c FROM stream_ops WHERE status='active'"
        ).fetchone()["c"]
    finally:
        c.close()


def test_cut_requires_exactly_one_binding(db):
    ps.run_project(1)
    with pytest.raises(ValueError):
        cs.create_cut(stream_id=1)
    with pytest.raises(ValueError):
        cs.create_cut(stream_id=1, watermark_seq=6, batch_no="PB-x")


def test_cut_bound_to_batch_matches_counts(db):
    b = ps.run_project(1)
    cut = cs.create_cut(stream_id=1, batch_no=b["batch_no"])
    assert cut["status"] == "completed"
    assert cut["bind_type"] == "batch"
    assert cut["bound_watermark_seq"] == b["max_seq"]
    assert cut["row_count"] == b["projected_alive"] + b["projected_deleted"]
    assert cut["alive_count"] == b["projected_alive"]
    assert cut["deleted_count"] == b["projected_deleted"]
    assert cs.verify_cut(cut["id"])["ok"] is True


def test_cut_refuses_non_completed_batch(db):
    b = ps.run_project(1)
    c = connect()
    try:
        c.execute(
            "UPDATE project_batches SET status='failed' WHERE id=?", (b["id"],)
        )
        c.commit()
    finally:
        c.close()
    with pytest.raises(ValueError):
        cs.create_cut(stream_id=1, batch_no=b["batch_no"])


def test_cut_rows_carry_required_fields(db):
    ps.run_project(1)
    cut = cs.create_cut(stream_id=1, watermark_seq=6)
    for r in cut["rows"]:
        assert set(["entity_key", "applied_seq", "deleted", "payload_digest"]) <= set(r)
        assert len(r["payload_digest"]) == 64


def test_watermark_beyond_committed_refused_without_cut_record(db):
    ps.run_project(1, up_to_seq=3)
    before = len(cs.list_cuts())
    with pytest.raises(errors.ConflictError):
        cs.create_cut(stream_id=1, watermark_seq=6)
    # Nothing is left behind: no half-created cut, no lingering op marker.
    assert len(cs.list_cuts()) == before
    assert _active_ops() == 0


def test_watermark_advancing_between_phases_fails_the_cut(db, monkeypatch):
    """If the committed watermark regresses after the cut marker is published,
    the cut must fail and leave no usable rows."""
    ps.run_project(1)  # committed at 6
    from app.services import cut_service as csm

    calls = {"n": 0}

    def first_six_then_two(conn, stream_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return 6  # phase-1 validation passes
        # Simulate a rebuild that lowered the committed watermark before the
        # snapshot read could anchor the cut.
        conn.execute(
            "UPDATE project_streams SET watermark_seq=2 WHERE id=?", (stream_id,)
        )
        return 2

    orig = csm.stream_repo.committed_watermark
    monkeypatch.setattr(csm.stream_repo, "committed_watermark", first_six_then_two)
    try:
        with pytest.raises(errors.ConflictError):
            cs.create_cut(stream_id=1, watermark_seq=6)
    finally:
        # Restore only this attribute; monkeypatch.undo() would also undo the
        # fixture's DB_PATH redirect.
        monkeypatch.setattr(csm.stream_repo, "committed_watermark", orig)
    c = connect()
    try:
        row = c.execute(
            "SELECT * FROM snapshot_cuts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        nrows = c.execute(
            "SELECT COUNT(*) c FROM cut_rows WHERE cut_id=?", (row["id"],)
        ).fetchone()["c"]
    finally:
        c.close()
    assert row["status"] == "failed"
    assert row["row_count"] == 0 and row["snapshot_watermark_seq"] is None
    assert nrows == 0
    assert cs.verify_cut(row["id"])["ok"] is False


def test_failed_cut_has_no_rows_and_is_not_verifiable(db, monkeypatch):
    ps.run_project(1)
    from app.repositories import cuts as cr

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cr, "insert_cut_rows", boom)
    with pytest.raises(RuntimeError):
        cs.create_cut(stream_id=1, watermark_seq=6)
    c = connect()
    try:
        row = c.execute(
            "SELECT * FROM snapshot_cuts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        nrows = c.execute(
            "SELECT COUNT(*) c FROM cut_rows WHERE cut_id=?", (row["id"],)
        ).fetchone()["c"]
    finally:
        c.close()
    assert row["status"] == "failed"
    assert row["row_count"] == 0 and row["alive_count"] == 0
    assert row["snapshot_watermark_seq"] is None
    assert nrows == 0
    assert cs.verify_cut(row["id"])["ok"] is False
    assert _active_ops() == 0


def test_reject_apply_blocks_application_during_cut(db):
    ps.run_project(1, up_to_seq=3)
    res = {}

    def cut_thread():
        res["cut"] = cs.create_cut(
            stream_id=1, watermark_seq=3, policy="reject_apply", hold_ms=800
        )

    t = threading.Thread(target=cut_thread)
    t.start()
    time.sleep(0.25)
    with pytest.raises(errors.ConflictError):
        ps.run_project(1)
    t.join()
    assert res["cut"]["status"] == "completed"


def test_snapshot_read_sees_only_committed_state_during_uncommitted_apply(db):
    ps.run_project(1, up_to_seq=3)
    res = {}

    def cut_thread():
        # Cut binds to the committed tip (3) and starts before the apply.
        res["cut"] = cs.create_cut(
            stream_id=1, watermark_seq=3, policy="snapshot_read", hold_ms=800
        )

    t = threading.Thread(target=cut_thread)
    t.start()
    time.sleep(0.25)

    def apply_thread():
        res["apply"] = ps.run_project(1, up_to_seq=6, hold_ms=600)

    t2 = threading.Thread(target=apply_thread)
    t2.start()
    t.join()
    t2.join()

    cut = res["cut"]
    assert cut["status"] == "completed"
    # The cut froze exactly the committed state at watermark 3 (S01+S02 upserts),
    # not the newer build that was in flight.
    assert cut["bound_watermark_seq"] == 3
    assert [(r["entity_key"], r["applied_seq"]) for r in cut["rows"]] == [
        ("M1001", 3),
        ("M1002", 2),
    ]
    assert cs.verify_cut(cut["id"])["ok"] is True
    # The live projection did advance afterwards.
    live = ps.list_projections(stream_id=1)
    assert len(live) == 3


def test_restart_fails_abandoned_running_cuts(db):
    ps.run_project(1)
    c = connect()
    try:
        c.execute(
            """
            INSERT INTO snapshot_cuts(
                cut_no, stream_id, stream_code, status, bind_type,
                bound_watermark_seq, read_mode, policy, row_count,
                alive_count, deleted_count, started_at, finished_at
            ) VALUES ('SC-BOOT-1',1,'member_profile','running','watermark',
                      6,'committed_snapshot','reject_apply',0,0,0,'x','x')
            """
        )
        cid = c.execute("SELECT MAX(id) m FROM snapshot_cuts").fetchone()["m"]
        c.execute(
            "INSERT INTO cut_rows(cut_id, entity_key, applied_seq, deleted, payload_digest)"
            " VALUES (?, 'M1001', 1, 0, 'digest')",
            (cid,),
        )
        c.commit()
    finally:
        c.close()

    init_db()  # simulates a process restart

    c = connect()
    try:
        row = c.execute(
            "SELECT status, failure_reason FROM snapshot_cuts WHERE id=?",
            (cid,),
        ).fetchone()
        nrows = c.execute(
            "SELECT COUNT(*) c FROM cut_rows WHERE cut_id=?", (cid,)
        ).fetchone()["c"]
    finally:
        c.close()
    assert row["status"] == "failed"
    assert nrows == 0


def test_cut_at_older_watermark_becomes_log_replay(db):
    ps.run_project(1, up_to_seq=3)
    cut = cs.create_cut(stream_id=1, watermark_seq=3)
    ps.run_project(1, up_to_seq=6)
    # The live projection has moved on, so a fresh cut at 3 is proven from the
    # log alone and must still reproduce exactly.
    again = cs.create_cut(stream_id=1, watermark_seq=3)
    assert again["verify_method"] == "log_replay"
    assert again["row_count"] == cut["row_count"]
    assert cs.verify_cut(again["id"])["ok"] is True
