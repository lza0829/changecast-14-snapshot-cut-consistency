from __future__ import annotations

from datetime import datetime, timezone

from app.db import connect

STREAM_SEEDS = [
    {
        "code": "member_profile",
        "title": "会员档案变更",
        "domain": "member",
        "entity_key_name": "member_id",
        "payload_fields": ["display_name", "tier", "region"],
        "fixture": "member_profile.json",
        "enabled": 1,
    },
    {
        "code": "store_archive",
        "title": "门店档案变更",
        "domain": "store",
        "entity_key_name": "store_id",
        "payload_fields": ["name", "status", "city"],
        "fixture": "store_archive.json",
        "enabled": 1,
    },
    {
        "code": "channel_attr",
        "title": "渠道属性变更",
        "domain": "channel",
        "entity_key_name": "channel_code",
        "payload_fields": ["label", "active"],
        "fixture": "channel_attr.json",
        "enabled": 1,
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_db() -> None:
    import json

    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_streams(
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                entity_key_name TEXT NOT NULL,
                payload_fields_json TEXT NOT NULL,
                fixture TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                watermark_seq INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_batches(
                id INTEGER PRIMARY KEY,
                batch_no TEXT NOT NULL UNIQUE,
                stream_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                source_events INTEGER NOT NULL,
                applied_upsert INTEGER NOT NULL,
                applied_delete INTEGER NOT NULL,
                skipped_duplicate INTEGER NOT NULL,
                projected_alive INTEGER NOT NULL,
                projected_deleted INTEGER NOT NULL,
                max_seq INTEGER NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(stream_id) REFERENCES project_streams(id)
            );
            CREATE TABLE IF NOT EXISTS projection_rows(
                id INTEGER PRIMARY KEY,
                stream_id INTEGER NOT NULL,
                entity_key TEXT NOT NULL,
                payload_json TEXT,
                applied_seq INTEGER NOT NULL,
                applied_event_id TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(stream_id, entity_key),
                FOREIGN KEY(stream_id) REFERENCES project_streams(id)
            );
            CREATE TABLE IF NOT EXISTS applied_events(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                stream_id INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                op TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_time TEXT NOT NULL,
                result TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES project_batches(id),
                FOREIGN KEY(stream_id) REFERENCES project_streams(id)
            );
            CREATE TABLE IF NOT EXISTS ooo_buffer(
                id INTEGER PRIMARY KEY,
                stream_id INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                op TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_time TEXT NOT NULL,
                payload_json TEXT,
                buffered_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                FOREIGN KEY(stream_id) REFERENCES project_streams(id)
            );
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stream_ops(
                id INTEGER PRIMARY KEY,
                stream_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                policy TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                started_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                note TEXT,
                FOREIGN KEY(stream_id) REFERENCES project_streams(id)
            );
            CREATE INDEX IF NOT EXISTS idx_stream_ops_stream ON stream_ops(stream_id, kind, status);
            CREATE TABLE IF NOT EXISTS snapshot_cuts(
                id INTEGER PRIMARY KEY,
                cut_no TEXT NOT NULL UNIQUE,
                stream_id INTEGER NOT NULL,
                stream_code TEXT NOT NULL,
                status TEXT NOT NULL,
                bind_type TEXT NOT NULL,
                requested_watermark INTEGER,
                bind_batch_id INTEGER,
                bind_batch_no TEXT,
                bound_watermark_seq INTEGER NOT NULL,
                snapshot_watermark_seq INTEGER,
                snapshot_batch_id INTEGER,
                snapshot_batch_no TEXT,
                committed_watermark_at_cut INTEGER,
                read_mode TEXT NOT NULL,
                policy TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                alive_count INTEGER NOT NULL,
                deleted_count INTEGER NOT NULL,
                verify_method TEXT,
                failure_reason TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                note TEXT,
                FOREIGN KEY(stream_id) REFERENCES project_streams(id),
                FOREIGN KEY(bind_batch_id) REFERENCES project_batches(id)
            );
            CREATE INDEX IF NOT EXISTS idx_snapshot_cuts_stream ON snapshot_cuts(stream_id, id);
            CREATE TABLE IF NOT EXISTS cut_rows(
                id INTEGER PRIMARY KEY,
                cut_id INTEGER NOT NULL,
                entity_key TEXT NOT NULL,
                applied_seq INTEGER NOT NULL,
                applied_event_id TEXT,
                deleted INTEGER NOT NULL,
                payload_digest TEXT NOT NULL,
                UNIQUE(cut_id, entity_key),
                FOREIGN KEY(cut_id) REFERENCES snapshot_cuts(id) ON DELETE CASCADE
            );
            """
        )
        # Lightweight migration: applied_events gained payload_json so a
        # projection can be reconstructed as-of a watermark from the log.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(applied_events)")}
        if "payload_json" not in cols:
            conn.execute("ALTER TABLE applied_events ADD COLUMN payload_json TEXT")

        if conn.execute("SELECT COUNT(*) c FROM project_streams").fetchone()["c"] == 0:
            now = _now()
            for s in STREAM_SEEDS:
                conn.execute(
                    """
                    INSERT INTO project_streams(
                        code, title, domain, entity_key_name, payload_fields_json,
                        fixture, enabled, watermark_seq, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        s["code"],
                        s["title"],
                        s["domain"],
                        s["entity_key_name"],
                        json.dumps(s["payload_fields"], ensure_ascii=False),
                        s["fixture"],
                        s["enabled"],
                        0,
                        now,
                    ),
                )
        if conn.execute("SELECT COUNT(*) c FROM settings").fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("apply_order", "by_seq"),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("duplicate_policy", "skip"),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("tombstone_mode", "soft_delete"),
            )
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            ("cut_policy", "reject_apply"),
        )
        # A cut left 'running' by a previous process can never finish; it must
        # not survive as a half-valid cut.
        for r in conn.execute(
            "SELECT id FROM snapshot_cuts WHERE status='running'"
        ).fetchall():
            conn.execute("DELETE FROM cut_rows WHERE cut_id=?", (r["id"],))
            conn.execute(
                "UPDATE snapshot_cuts SET status='failed', failure_reason=?, finished_at=? WHERE id=?",
                ("进程重启，切面未完成", _now(), r["id"]),
            )
        conn.commit()
    finally:
        conn.close()
