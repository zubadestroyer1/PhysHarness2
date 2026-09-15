"""Canonical records, transactional events/outbox and concurrent resource ledgers."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Float,
    Index,
    Integer,
    String,
    create_engine,
    event,
    literal,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class RecordRow(Base):
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (Index("records_project_kind", "project_id", "kind"),)


def record_json_text(field: str):
    # Constant JSON paths must be in the SQL text for SQLite expression-index matching.
    return RecordRow.payload[
        literal(field, type_=JSON.JSONStrIndexType(), literal_execute=True)
    ].as_string()


Index("records_project_kind_keyset", RecordRow.project_id, RecordRow.kind, RecordRow.id)
Index(
    "records_project_kind_experiment_keyset",
    RecordRow.project_id,
    RecordRow.kind,
    record_json_text("experiment_id"),
    RecordRow.id,
)
Index(
    "records_project_kind_artifact_review",
    RecordRow.project_id,
    RecordRow.kind,
    record_json_text("artifact_id"),
    record_json_text("review_id"),
    record_json_text("status"),
    record_json_text("assurance"),
)


Index(
    "records_project_kind_problem_keyset",
    RecordRow.project_id,
    RecordRow.kind,
    record_json_text("problem_id"),
    RecordRow.id,
)


class CommandRow(Base):
    __tablename__ = "commands"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), index=True)
    operation_id: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class EventRow(Base):
    __tablename__ = "events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    operation_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class OutboxRow(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class BudgetRow(Base):
    __tablename__ = "budgets"
    experiment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    max_cost: Mapped[int] = mapped_column(BigInteger)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    spent: Mapped[int] = mapped_column(BigInteger, default=0)
    active_workers: Mapped[int] = mapped_column(Integer, default=0)
    max_concurrency: Mapped[int] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_spent: Mapped[int] = mapped_column(BigInteger, default=0)


class ReservationRow(Base):
    __tablename__ = "reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    reserved: Mapped[int] = mapped_column(BigInteger)
    workers: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="active")
    actual: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_actual: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class LeaseRow(Base):
    __tablename__ = "leases"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    holder: Mapped[str] = mapped_column(String(200))
    fence: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[float] = mapped_column(Float)


class EdgeRow(Base):
    __tablename__ = "dependencies"
    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    relation: Mapped[str] = mapped_column(String(50), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), index=True)


class Database:
    def __init__(self, url: str):
        self.url = url
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        """Development/bootstrap only; deployed installations use Alembic migrations."""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.sessions.begin() as session:
            if self.engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            yield session

    def command_lock(self, session: Session, key: str) -> None:
        if self.engine.dialect.name == "postgresql":
            value = int(key[:16], 16)
            if value >= 2**63:
                value -= 2**64
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": value})
