import pytest

from physharness.errors import HarnessError
from physharness.orchestration.research_worker import _validate_worker_preflight


def test_worker_allows_launch_only_daemon_check_when_verifier_is_running():
    _validate_worker_preflight(
        {
            "checks": [
                {"code": "WORKBENCH_DAEMON_NOT_DEDICATED", "status": "blocked"},
                {"code": "WORKSPACE_CAPACITY", "status": "ready"},
                {"code": "WORKBENCH_MEMORY_INSUFFICIENT", "status": "ready"},
            ]
        }
    )


@pytest.mark.parametrize("code", ["WORKSPACE_CAPACITY", "WORKBENCH_MEMORY_INSUFFICIENT"])
def test_worker_stops_on_resource_preflight_block(code):
    with pytest.raises(HarnessError) as error:
        _validate_worker_preflight({"checks": [{"code": code, "status": "blocked"}]})
    assert error.value.code == code
