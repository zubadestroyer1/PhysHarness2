import pytest

from physharness.artifacts import LocalArtifactStore
from physharness.domain import Principal
from physharness.service import HarnessService
from physharness.storage import Database


@pytest.fixture
def lab(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'records.db'}")
    db.create_schema()
    service = HarnessService(db, LocalArtifactStore(tmp_path / "artifacts"))
    researcher = Principal(id="researcher", project_id="lab", role="researcher")
    reviewer = Principal(id="reviewer", project_id="lab", role="reviewer")
    return service, researcher, reviewer
