"""The canonical SQLite database commits through a write-ahead log with full fsync."""

from sqlalchemy import text

from physharness.storage import Database


def test_sqlite_database_uses_wal_and_full_sync(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'records.db'}")
    with db.engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar() == 2
