"""Project-scoped facts about one pinned Mathlib/Physlib environment (S1 audit #24).

Shared across a project's experiments, keyed by ``environment_digest``: renamed
declarations, known absences and working recipes an agent has checked in Lean, so a later
agent at the same pin stops rediscovering them. Notes are agents' unverified reports, never
platform evidence.
"""

import functools
import json
from importlib import resources

from sqlalchemy import func, select

from .domain import Principal, new_id, utcnow
from .errors import HarnessError
from .knowledge.index import tokens
from .storage import LibraryNoteRow

MAX_NOTE_CHARS = 2000
MAX_NOTES_PER_ENVIRONMENT = 200
SEED_AUTHOR = "seed:S1 audit 2026-09-26"


@functools.cache
def _seed() -> dict:
    raw = resources.files("physharness.knowledge").joinpath("library_notes_seed.json").read_text()
    return json.loads(raw)


def seed_notes(environment_digest: str) -> list[str]:
    return _seed().get(environment_digest, [])


class LibraryNotesMixin:
    def _library_environment(self, session, actor: Principal) -> str:
        experiment = self._get(session, "experiment", actor.experiment_id, actor)
        problem = self._get(session, "problem", experiment.payload["problem_id"], actor)
        return problem.payload["environment_digest"]

    def library_notes(self, actor: Principal, *, query: str | None = None, limit: int = 20) -> dict:
        with self.db.sessions() as session:
            digest = self._library_environment(session, actor)
            rows = session.scalars(
                select(LibraryNoteRow)
                .where(
                    LibraryNoteRow.project_id == actor.project_id,
                    LibraryNoteRow.environment_digest == digest,
                )
                .order_by(LibraryNoteRow.created_at.desc())
                .limit(MAX_NOTES_PER_ENVIRONMENT)
            )
            appended = [
                {"id": row.id, "text": row.text, "author": row.author, "created_at": row.created_at}
                for row in rows
            ]
        notes = [{"text": text, "author": SEED_AUTHOR} for text in seed_notes(digest)] + appended
        if query:
            wanted = tokens(query)
            # Rank by shared-token overlap, seeds first on ties (their lower original position).
            scored = [
                (-len(wanted & tokens(note["text"])), position, note)
                for position, note in enumerate(notes)
                if wanted & tokens(note["text"])
            ]
            notes = [note for _, _, note in sorted(scored)]
        return {"environment_digest": digest, "notes": notes[:limit]}

    def append_library_note(self, text: str, actor: Principal, key: str) -> dict:
        if not actor.branch_id:
            raise HarnessError(
                "BRANCH_AUTHORITY",
                "A branch identity is required to append a library note.",
                status=403,
            )
        stripped = text.strip()
        if not 1 <= len(stripped) <= MAX_NOTE_CHARS:
            raise HarnessError(
                "INVALID_NOTE",
                f"A library note is 1-{MAX_NOTE_CHARS} characters after trimming; "
                f"got {len(stripped)}.",
                status=422,
            )

        def action(session, op):
            digest = self._library_environment(session, actor)
            self.db.command_lock(session, self._digest(["library-notes", actor.project_id, digest]))
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(LibraryNoteRow)
                    .where(
                        LibraryNoteRow.project_id == actor.project_id,
                        LibraryNoteRow.environment_digest == digest,
                    )
                )
                or 0
            )
            if count >= MAX_NOTES_PER_ENVIRONMENT:
                raise HarnessError(
                    "LIBRARY_NOTES_FULL",
                    "Library notes are full (budget, not input: limit "
                    f"{MAX_NOTES_PER_ENVIRONMENT}, used {count}).",
                    remediation="Read the existing notes; an operator prunes them.",
                )
            row = LibraryNoteRow(
                id=new_id(),
                project_id=actor.project_id,
                environment_digest=digest,
                experiment_id=actor.experiment_id,
                author=f"branch:{actor.branch_id}",
                text=stripped,
                created_at=utcnow().isoformat(),
            )
            session.add(row)
            self._event(
                session,
                actor,
                op,
                "library_note.appended",
                actor.experiment_id,
                {"experiment_id": actor.experiment_id, "environment_digest": digest},
            )
            return {"id": row.id, "environment_digest": digest, "text": stripped}

        return self._execute(actor, key, "library_notes.append", {"text": stripped}, action)
