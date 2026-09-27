import pytest

from physharness.artifacts import LocalArtifactStore
from physharness.domain import Principal
from physharness.service import HarnessService
from physharness.storage import Database


@pytest.fixture(autouse=True)
def _fresh_checker_self_test_cache(monkeypatch):
    """Each test starts with no workbench image judged to have a working statement checker."""
    monkeypatch.setattr("physharness.orchestration.workspace_tools._CHECKER_SELF_TESTS", {})


@pytest.fixture
def lab(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'records.db'}")
    db.create_schema()
    service = HarnessService(db, LocalArtifactStore(tmp_path / "artifacts"))
    researcher = Principal(id="researcher", project_id="lab", role="researcher")
    reviewer = Principal(id="reviewer", project_id="lab", role="reviewer")
    return service, researcher, reviewer
