"""Small persistent stores. Production callers may inject database-backed RuntimeStore."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .types import ExecutionError, RuntimeCheckpoint, digest


class SQLiteRuntimeStore:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runtime_sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        self.db.commit()

    async def save(self, checkpoint: RuntimeCheckpoint) -> None:
        checkpoint.verify()
        self.db.execute(
            "INSERT INTO runtime_sessions VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (checkpoint.session.id, checkpoint.model_dump_json()),
        )
        self.db.commit()

    async def load(self, session_id: str) -> RuntimeCheckpoint:
        row = self.db.execute(
            "SELECT data FROM runtime_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            raise ExecutionError("SESSION_NOT_FOUND", "Runtime session does not exist")
        checkpoint = RuntimeCheckpoint.model_validate_json(row[0])
        checkpoint.verify()
        return checkpoint

    def close(self) -> None:
        self.db.close()


class CommandJournal:
    """At-most-once dispatch journal; in-flight operations require reconciliation after crash.

    A crash between side effect and result commit is uncertain, never automatically rerun.
    Callers must serialize program execution; SQLite unique operation keys arbitrate dispatch.
    """

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS research_commands (
            program_id TEXT NOT NULL, operation_id TEXT NOT NULL, identity TEXT NOT NULL,
            command TEXT NOT NULL, arguments TEXT NOT NULL, status TEXT NOT NULL,
            result TEXT, PRIMARY KEY(program_id, operation_id))""")

    def __enter__(self) -> CommandJournal:
        return self

    def __exit__(self, *args: object) -> None:
        self.db.close()

    def begin(
        self, program_id: str, operation_id: str, command: str, arguments: dict[str, Any]
    ) -> Any:
        identity = digest({"command": command, "arguments": arguments})
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT identity,status,result FROM research_commands "
                "WHERE program_id=? AND operation_id=?",
                (program_id, operation_id),
            ).fetchone()
            if row:
                if row[0] != identity:
                    raise ExecutionError(
                        "COMMAND_MISMATCH",
                        "Replayed operation changed command or arguments",
                        operation_id=operation_id,
                    )
                if row[1] != "completed":
                    raise ExecutionError(
                        "OPERATION_UNCERTAIN",
                        "Operation has no committed result; reconcile before retry",
                        operation_id=operation_id,
                    )
                return json.loads(row[2])
            self.db.execute(
                "INSERT INTO research_commands VALUES (?,?,?,?,?,'pending',NULL)",
                (
                    program_id,
                    operation_id,
                    identity,
                    command,
                    json.dumps(arguments, allow_nan=False),
                ),
            )
            return None
        finally:
            self.db.execute("COMMIT")

    def observe(self, program_id: str, operation_id: str, observation: dict[str, Any]) -> None:
        """Persist recovery evidence without making a pending operation replayable."""
        if not isinstance(observation, dict):
            raise ExecutionError("INVALID_TOOL_RESULT", "Journal observations must be JSON objects")
        encoded = json.dumps(observation, sort_keys=True, allow_nan=False)
        cursor = self.db.execute(
            "UPDATE research_commands SET result=? "
            "WHERE program_id=? AND operation_id=? AND status='pending'",
            (encoded, program_id, operation_id),
        )
        if cursor.rowcount != 1:
            raise ExecutionError(
                "OPERATION_CONFLICT",
                "Only a pending operation can receive observations",
                operation_id=operation_id,
            )

    def complete(self, program_id: str, operation_id: str, result: Any) -> None:
        if not isinstance(result, dict):
            raise ExecutionError("INVALID_TOOL_RESULT", "Journal results must be JSON objects")
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        cursor = self.db.execute(
            "UPDATE research_commands SET status='completed',result=? "
            "WHERE program_id=? AND operation_id=? AND status='pending'",
            (encoded, program_id, operation_id),
        )
        if cursor.rowcount != 1:
            raise ExecutionError(
                "OPERATION_CONFLICT",
                "Only a pending operation can be completed",
                operation_id=operation_id,
            )

    def export(self, program_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT operation_id,identity,command,arguments,status,result "
            "FROM research_commands WHERE program_id=? ORDER BY rowid",
            (program_id,),
        ).fetchall()
        return [
            {
                "operation_id": r[0],
                "identity": r[1],
                "command": r[2],
                "arguments": json.loads(r[3]),
                "status": r[4],
                "result": json.loads(r[5]) if r[5] is not None else None,
            }
            for r in rows
        ]
