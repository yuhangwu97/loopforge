"""Database layer — SQLite persistence for loops and rounds."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from loopforge.models import Constraints, LoopConfig, LoopState, LoopStatus, TargetSpec


DB_PATH = os.getenv("LOOPFORGE_DB", "loopforge.db")


def _dict_factory(cursor, row):
    """Row factory that returns dicts."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS loops (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                current_round INTEGER DEFAULT 0,
                best_score REAL DEFAULT 0.0,
                rounds_json TEXT DEFAULT '[]',
                total_tokens INTEGER DEFAULT 0,
                errors_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS rounds (
                id TEXT PRIMARY KEY,
                loop_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                plan TEXT DEFAULT '',
                actions_json TEXT DEFAULT '[]',
                score REAL DEFAULT 0.0,
                evaluation_output TEXT DEFAULT '',
                decision TEXT DEFAULT 'continue',
                tokens_used INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT DEFAULT '',
                FOREIGN KEY (loop_id) REFERENCES loops(id)
            );

            CREATE INDEX IF NOT EXISTS idx_rounds_loop ON rounds(loop_id, round_number);
        """)


# ── CRUD Operations ──────────────────────────────────────────────────


def save_loop(state: LoopState):
    """Insert or update a loop."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO loops
                (id, name, config_json, status, current_round, best_score,
                 rounds_json, total_tokens, errors_json, created_at, updated_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.id,
                state.config.name,
                state.config.model_dump_json(),
                state.status.value,
                state.current_round,
                state.best_score,
                json.dumps([r.model_dump() for r in state.rounds]),
                state.total_tokens,
                json.dumps(state.errors),
                state.created_at,
                state.updated_at,
                state.finished_at,
            ),
        )

        # Also save individual rounds
        for r in state.rounds:
            conn.execute(
                """
                INSERT OR REPLACE INTO rounds
                    (id, loop_id, round_number, plan, actions_json, score,
                     evaluation_output, decision, tokens_used, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.id,
                    state.id,
                    r.round_number,
                    r.plan,
                    json.dumps([a.model_dump() for a in r.actions]),
                    r.score,
                    r.evaluation_output,
                    r.decision.value,
                    r.tokens_used,
                    r.started_at,
                    r.finished_at,
                ),
            )


def load_loop(loop_id: str) -> LoopState | None:
    """Load a loop by ID."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM loops WHERE id = ?", (loop_id,)).fetchone()
        if not row:
            return None

        config = LoopConfig.model_validate_json(row["config_json"])
        rounds_data = json.loads(row.get("rounds_json", "[]"))
        errors = json.loads(row.get("errors_json", "[]"))

        from loopforge.models import RoundResult

        rounds = [RoundResult.model_validate(r) for r in rounds_data]

        return LoopState(
            id=row["id"],
            config=config,
            status=LoopStatus(row["status"]),
            current_round=row["current_round"],
            best_score=row["best_score"],
            rounds=rounds,
            total_tokens=row["total_tokens"],
            errors=errors,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row.get("finished_at", ""),
        )


def list_loops(status: str | None = None) -> list[dict[str, Any]]:
    """List loops, optionally filtered by status."""
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT id, name, config_json, status, current_round, best_score, total_tokens, created_at "
                "FROM loops WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, config_json, status, current_round, best_score, total_tokens, created_at "
                "FROM loops ORDER BY created_at DESC"
            ).fetchall()

        return [
            {
                "id": r["id"],
                "name": r["name"],
                "strategy": LoopConfig.model_validate_json(r["config_json"]).strategy,
                "status": r["status"],
                "current_round": r["current_round"],
                "best_score": r["best_score"],
                "total_tokens": r["total_tokens"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def delete_loop(loop_id: str):
    """Delete a loop and its rounds."""
    with get_conn() as conn:
        conn.execute("DELETE FROM rounds WHERE loop_id = ?", (loop_id,))
        conn.execute("DELETE FROM loops WHERE id = ?", (loop_id,))


def load_rounds(loop_id: str) -> list[dict[str, Any]]:
    """Load all rounds for a loop."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rounds WHERE loop_id = ? ORDER BY round_number",
            (loop_id,),
        ).fetchall()

        return [
            {
                "id": r["id"],
                "round_number": r["round_number"],
                "plan": r["plan"],
                "actions": json.loads(r["actions_json"]),
                "score": r["score"],
                "evaluation_output": r["evaluation_output"],
                "decision": r["decision"],
                "tokens_used": r["tokens_used"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
            }
            for r in rows
        ]
