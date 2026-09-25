"""A retired pilot attempt remains in the cost and isolation audit."""

from copy import deepcopy

import pytest
from test_exponential_pilot import manifest, runner, write_manifest


def with_retired(tmp_path):
    config = manifest(tmp_path)
    retired = deepcopy(config["attempts"][2])
    fresh = deepcopy(retired)
    fresh["label"] = "run-2-replacement"
    fresh["project_id"] = "project-2-replacement"
    fresh["experiment_id"] = "experiment-2-replacement"
    fresh["private_directory"] = str(tmp_path / "run-2-replacement")
    fresh["database_url"] = f"sqlite:///{tmp_path / 'run-2-replacement' / 'harness.db'}"
    for key, name in (
        ("artifact_root", "artifacts"),
        ("status_file", "status.json"),
        ("result_file", "result.json"),
    ):
        fresh[key] = str(tmp_path / "run-2-replacement" / name)
    config["attempts"][2] = fresh
    config["retired_attempts"] = [retired]
    return config, retired


class Ledgers:
    def __init__(self, retired):
        self.retired = retired
        self.retired_status = "cancelled"
        self.retired_spent = "0"
        self.retired_reserved = "0"
        self.retired_uncertain = 0
        self.retired_reconciliation = False
        self.retired_active_workers = 0
        self.retired_tasks = []
        self.retired_sessions = []
        self.retired_verifications = []

    def get_record(self, kind, identifier, actor):
        assert kind == "experiment"
        if identifier == self.retired["experiment_id"]:
            return {
                "status": self.retired_status,
                "budget_reconciliation_required": self.retired_reconciliation,
            }
        return {"status": "created", "budget_reconciliation_required": False}

    def ledger(self, identifier, actor):
        is_retired = identifier == self.retired["experiment_id"]
        return {
            "spent_cost_usd": self.retired_spent if is_retired else "0",
            "reserved_cost_usd": self.retired_reserved if is_retired else "0",
            "active_workers": self.retired_active_workers if is_retired else 0,
            "tokens_reserved": 0,
            "uncertain_operations": self.retired_uncertain if is_retired else 0,
        }

    def list_records(self, kind, actor, identifier):
        if identifier != self.retired["experiment_id"]:
            return []
        return {
            "task": self.retired_tasks,
            "session": self.retired_sessions,
            "verification": self.retired_verifications,
        }[kind]


def test_retired_attempt_keeps_spend_in_92_new_and_100_aggregate_caps(tmp_path):
    config, retired = with_retired(tmp_path)
    assert runner.load_manifest(write_manifest(tmp_path, config))["retired_attempts"] == [retired]
    service = Ledgers(retired)
    service.retired_spent = "80"
    selected = config["attempts"][0]
    runner.audit_sequence(config, selected, lambda attempt: (service, None))
    service.retired_spent = "80.000001"
    with pytest.raises(runner.PilotFailure, match="AGGREGATE_BUDGET"):
        runner.audit_sequence(config, selected, lambda attempt: (service, None))


@pytest.mark.parametrize(
    ("attribute", "value", "code"),
    [
        ("retired_uncertain", 1, "UNSETTLED_PRIOR_COST"),
        ("retired_reconciliation", True, "UNSETTLED_PRIOR_COST"),
        ("retired_status", "running", "RETIRED_ATTEMPT_NOT_DRAINED"),
        ("retired_active_workers", 1, "RETIRED_ATTEMPT_NOT_DRAINED"),
        ("retired_reserved", "0.01", "RETIRED_ATTEMPT_NOT_DRAINED"),
        ("retired_tasks", [{"status": "running"}], "RETIRED_ATTEMPT_NOT_DRAINED"),
        ("retired_sessions", [{"status": "running"}], "RETIRED_ATTEMPT_NOT_DRAINED"),
        ("retired_verifications", [{"status": "queued"}], "RETIRED_ATTEMPT_NOT_DRAINED"),
    ],
)
def test_retired_uncertain_or_live_state_prevents_launch(tmp_path, attribute, value, code):
    config, retired = with_retired(tmp_path)
    service = Ledgers(retired)
    setattr(service, attribute, value)
    with pytest.raises(runner.PilotFailure, match=code):
        runner.audit_sequence(config, config["attempts"][0], lambda attempt: (service, None))


def test_retired_and_active_identity_or_database_cannot_overlap(tmp_path):
    config, retired = with_retired(tmp_path)
    config["retired_attempts"][0]["experiment_id"] = config["attempts"][0]["experiment_id"]
    with pytest.raises(runner.PilotFailure, match="RUN_ISOLATION"):
        runner.load_manifest(write_manifest(tmp_path, config))
    config, retired = with_retired(tmp_path)
    config["retired_attempts"][0]["database_url"] = config["attempts"][0]["database_url"]
    with pytest.raises(runner.PilotFailure, match="RUN_ISOLATION"):
        runner.load_manifest(write_manifest(tmp_path, config))
    with pytest.raises(runner.PilotFailure, match="RUN_ISOLATION"):
        runner.audit_sequence(
            config, config["attempts"][0], lambda attempt: (Ledgers(retired), None)
        )


def test_old_manifest_defaults_to_no_retirements(tmp_path):
    config = manifest(tmp_path)
    loaded = runner.load_manifest(write_manifest(tmp_path, config))
    assert loaded["retired_attempts"] == []


def test_replacement_preparation_reuses_reviewed_bytes_and_fresh_identity(tmp_path, monkeypatch):
    import hashlib

    from test_exponential_pilot import prepare

    config, retired = with_retired(tmp_path)
    original = deepcopy(retired)
    challenge = b"reviewed challenge"
    environment = b"reviewed environment"
    calls = []

    def fake_prepare(attempt, spec, environment_bytes, challenge_bytes, project_directory):
        calls.append((deepcopy(attempt), environment_bytes, challenge_bytes))
        return {"experiment_id": "fresh-experiment", "target_digest": "f" * 64}

    monkeypatch.setattr(prepare, "prepare_attempt", fake_prepare)
    args = {
        "label": "replacement-three",
        "private_directory": tmp_path / "replacement-three",
        "spec": {"title": "reviewed"},
        "environment_bytes": environment,
        "challenge": challenge,
        "project_directory": tmp_path / "project",
        "challenge_sha256": hashlib.sha256(challenge).hexdigest(),
        "environment_digest": hashlib.sha256(environment).hexdigest(),
    }
    with pytest.raises(ValueError, match="reviewed target"):
        prepare.prepare_replacement(retired, **{**args, "challenge": b"changed"})
    assert calls == []
    result = prepare.prepare_replacement(retired, **args)
    fresh = result["attempt"]
    assert retired == original
    assert fresh["experiment_id"] == "fresh-experiment"
    assert fresh["target_digest"] == "f" * 64
    assert fresh["phase"] == retired["phase"]
    assert fresh["sharing"] == retired["sharing"]
    assert fresh["ceiling_usd"] == retired["ceiling_usd"]
    assert fresh["database_url"] != retired["database_url"]
    assert fresh["private_directory"] != retired["private_directory"]
    assert calls[0][1:] == (environment, challenge)
