"""Pure retry gates; these tests never prepare a run or call a model."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from physharness.domain import CampaignCreate, ProblemCreate
from physharness.verification.boundary import ResourceProfile

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "work/hardening-final-2026-09-24"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location("pilot_retry", SCRIPT_DIR / "pilot_retry.py")
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


def test_exact_source_amendment_rejects_unreviewed_change_and_added_source():
    old = {"src/physharness/one.py": "a", "formal/lean-toolchain": "b"}
    current = {**old, "src/physharness/two.py": "c"}
    amendment = {
        "protocol": "hardening-retry-amendment-v1",
        "old_freeze_sha256": "0" * 64,
        "changed": {},
        "added": {"src/physharness/two.py": "c"},
        "deleted": {},
    }
    retry.check_source_amendment(old, current, amendment, "0" * 64)
    current["src/physharness/one.py"] = "changed"
    with pytest.raises(retry.RetryError, match="SOURCE_AMENDMENT"):
        retry.check_source_amendment(old, current, amendment, "0" * 64)
    current["src/physharness/one.py"] = "a"
    current["src/physharness/three.py"] = "new"
    with pytest.raises(retry.RetryError, match="SOURCE_AMENDMENT"):
        retry.check_source_amendment(old, current, amendment, "0" * 64)


def test_remaining_ceiling_counts_every_settled_attempt():
    assert retry.remaining_ceiling([Decimal("1.470130"), Decimal("3.000000")]) == Decimal(
        "47.529870"
    )
    with pytest.raises(retry.RetryError, match="AGGREGATE_BUDGET"):
        retry.remaining_ceiling([Decimal("1.470130"), Decimal("50.529870")])
    with pytest.raises(retry.RetryError, match="AGGREGATE_BUDGET"):
        retry.remaining_ceiling([Decimal("1.470130"), Decimal("NaN")])


def test_failed_predispatch_certificate_requires_exact_pending_call():
    source = {
        "session_id": "session-1",
        "checkpoint_sha256": "a" * 64,
        "pending_operation": "session-1:call-1",
        "call_id": "call-1",
        "tool_name": "run_command",
        "arguments": {"argv": ["lake"], "cwd": "/work", "timeout_seconds": 30},
    }
    retry.check_predispatch_call(source)
    source["pending_operation"] = "session-1:other"
    with pytest.raises(retry.RetryError, match="ABANDONED_CALL"):
        retry.check_predispatch_call(source)
    source["pending_operation"] = "session-1:call-1"
    source["arguments"]["cwd"] = "."
    with pytest.raises(retry.RetryError, match="ABANDONED_CALL"):
        retry.check_predispatch_call(source)


def test_canonical_uncertainty_blocks_prior_retirement(monkeypatch):
    attempt = {"experiment_id": "experiment-1"}

    class Service:
        def get_record(self, kind, identifier, actor):
            return {"status": "cancelled", "problem_id": "problem", "target_digest": "target"}

        def ledger(self, identifier, actor):
            return {
                "uncertain_operations": 1,
                "active_workers": 0,
                "reserved_cost_usd": "0",
                "tokens_reserved": 0,
                "spent_cost_usd": "1",
            }

        def list_records(self, kind, actor, identifier):
            return []

    monkeypatch.setattr(retry.pilot_runner, "operator_settings", lambda *_: (object(), object()))
    monkeypatch.setattr(retry, "build_service", lambda _: Service())
    with pytest.raises(retry.RetryError, match="PRIOR_NOT_DRAINED"):
        retry._prior_attempt_spend({}, attempt, None)


def test_locked_admission_rechecks_manifest_and_spend(monkeypatch):
    expected = {"attempt": {"ceiling_usd": "47"}}
    monkeypatch.setattr(retry, "check_freeze", lambda: {"attempt": {"ceiling_usd": "46"}})
    with pytest.raises(retry.RetryError, match="MANIFEST_CHANGED"):
        retry._locked_admission(expected)
    monkeypatch.setattr(retry, "check_freeze", lambda: expected)
    monkeypatch.setattr(retry, "audit_prior", lambda: ({}, Decimal("46")))
    with pytest.raises(retry.RetryError, match="AGGREGATE_BUDGET"):
        retry._locked_admission(expected)
    monkeypatch.setattr(retry, "audit_prior", lambda: ({}, Decimal("47")))
    assert retry._locked_admission(expected) is expected


def test_abandoned_read_requires_matching_retired_operation():
    item = {
        "task_id": "task",
        "session_id": "session",
        "workspace_id": "workspace",
        "operation_id": "operation",
        "operation_inputs": {"path": "/work/proof.lean", "offset": 0, "length": 10},
    }
    records = {
        "task": [{"id": "task", "status": "failed", "error_code": "WORKSPACE_RECOVERY_ABORTED"}],
        "session": [{"id": "session", "task_id": "task", "status": "completed"}],
        "workspace": [
            {
                "id": "workspace",
                "task_id": "task",
                "status": "destroyed",
                "destruction_confirmed": True,
            }
        ],
        "workspace_operation": [
            {
                "id": "operation",
                "workspace_id": "workspace",
                "task_id": "task",
                "command": "read_range",
                "status": "reconciliation_required",
                "inputs": item["operation_inputs"],
            }
        ],
        "continuation_link": [],
    }
    with pytest.raises(retry.RetryError, match="ABANDONED_READ"):
        retry._check_abandoned_read(item, records, None, None, "experiment")


def test_vm_absence_binds_every_canonical_workspace_identity():
    original = {"docker_host": "unix:///private/pilot.sock"}
    records = {"workspace": [{"id": "workspace-1", "execution_id": "container-1"}]}
    observation = {
        "protocol": "hardening-container-absence-v1",
        "docker_host": original["docker_host"],
        "observed_at": "2026-09-24T12:00:00+00:00",
        "all_containers_absent": True,
        "workspaces": [
            {
                "workspace_id": "workspace-1",
                "execution_id": "container-1",
                "container_absent": True,
            }
        ],
    }
    retry._check_vm_absence(observation, original, records)
    observation["workspaces"][0]["container_absent"] = False
    with pytest.raises(retry.RetryError, match="VM_ABSENCE_EVIDENCE"):
        retry._check_vm_absence(observation, original, records)
    observation["workspaces"][0]["container_absent"] = True
    observation["workspaces"][0]["execution_id"] = "another-container"
    with pytest.raises(retry.RetryError, match="VM_ABSENCE_EVIDENCE"):
        retry._check_vm_absence(observation, original, records)


def test_fresh_campaign_digest_changes_while_scientific_target_stays_identical(lab):
    service, researcher, _ = lab
    campaigns = [
        service.create_campaign(
            CampaignCreate(title="Pilot", objective="Same target", programs=["classical"]),
            researcher,
            f"campaign-{index}",
        )
        for index in (1, 2)
    ]
    common = {
        "title": "Network energy",
        "program": "classical",
        "informal_statement": "A finite network obeys a bound.",
        "formal_statement": "theorem identity (n : Nat) : n = n := by rfl",
        "assumptions": ["positive masses"],
        "definitions": {"energy": "quadratic plus quartic"},
        "source": "Private reviewed target",
        "environment_digest": "a" * 64,
        "target_theorem": "identity",
        "definition_holes": False,
    }
    problems = [
        service.create_problem(
            ProblemCreate(campaign_id=campaign["id"], **common),
            researcher,
            f"problem-{index}",
        )
        for index, campaign in enumerate(campaigns)
    ]
    assert retry.scientific_payload(problems[0]) == retry.scientific_payload(problems[1])
    assert problems[0]["target_digest"] != problems[1]["target_digest"]
    changed = dict(problems[1], source="changed provenance")
    assert retry.scientific_payload(changed) != retry.scientific_payload(problems[0])


def test_prepare_keeps_fresh_problem_pending_until_separate_review(tmp_path, monkeypatch):
    state = tmp_path / "retry"
    state.mkdir()
    monkeypatch.setattr(retry, "RETRY_STATE", state)
    monkeypatch.setattr(retry, "RETRY_MANIFEST", state / "manifest-retry.json")
    monkeypatch.setattr(retry, "OLD_MANIFEST", tmp_path / "old-manifest.json")
    monkeypatch.setattr(retry, "OLD_FREEZE", tmp_path / "old-freeze.json")
    monkeypatch.setattr(retry, "RETIREMENT_REVIEW", tmp_path / "retirement.json")
    monkeypatch.setattr(retry, "RETIREMENT_DECISION", tmp_path / "decision.json")
    monkeypatch.setattr(retry, "AMENDMENT", tmp_path / "amendment.json")
    monkeypatch.setattr(retry, "digest", lambda _: "d" * 64)
    monkeypatch.setattr(retry, "checked_source", lambda: {})
    monkeypatch.setattr(retry, "_source_qualification", lambda *_: None)
    challenge = tmp_path / "Challenge.lean"
    challenge.write_text("theorem identity : True := by trivial")
    scientific = {field: "fixed" for field in retry.SCIENTIFIC_FIELDS}
    scientific["definition_holes"] = False
    original = {
        "attempts": [{"label": "old"}],
        "retired_attempts": [],
        "challenge_sha256": "a" * 64,
        "challenge_file": str(challenge),
        "environment_digest": "b" * 64,
        "worker_image_digest": "sha256:" + "c" * 64,
        "verifier_image_digest": "sha256:" + "e" * 64,
        "docker_host": "unix:///tmp/pilot.sock",
        "model_prices_file": str(tmp_path / "prices.json"),
        "worker_qualification_file": str(tmp_path / "worker.json"),
        "global_lock_file": str(tmp_path / "launcher.lock"),
    }
    monkeypatch.setattr(retry, "audit_prior", lambda: (original, Decimal("8.796745")))
    monkeypatch.setattr(retry, "_exact_target", lambda *_: (b"challenge", b"environment"))
    review = {"semantic_review": "pending", "review_id": None}
    monkeypatch.setattr(retry, "_old_problem", lambda _: scientific)
    monkeypatch.setattr(
        retry,
        "_new_problem",
        lambda *_: {**scientific, **review, "target_digest": "f" * 64},
    )
    record = {
        "label": "hardening-cooperative-retry-1",
        "experiment_id": "fresh-experiment",
        "problem_revision_id": "fresh-problem",
        "target_digest": "f" * 64,
        "challenge_sha256": original["challenge_sha256"],
        "environment_digest": original["environment_digest"],
        "model_calls": 0,
    }
    monkeypatch.setattr(retry.pilot_prepare, "_prepare_attempt", lambda *_: record)
    monkeypatch.setattr(retry.pilot_runner, "load_manifest", lambda _: original)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"target": {}, "project_directory": str(tmp_path)}))
    qualification = tmp_path / "qualification.json"
    qualification.write_text(json.dumps({"scope_sha256": "g" * 64}))

    assert retry.prepare(spec, qualification)["status"] == "prepared_pending_review"
    assert review["semantic_review"] == "pending" and review["review_id"] is None
    prepared = json.loads((state / "prepared-retry.json").read_text())
    assert prepared["target_digest"] == "f" * 64
    original["attempts"][-1] = {
        **json.loads((state / "manifest-retry.json").read_text())["attempt"],
        "label": "old",
        "project_id": "old",
        "experiment_id": "old-experiment",
        "database_url": "sqlite:////tmp/old.db",
        "artifact_root": "/tmp/old-artifacts",
    }
    with pytest.raises(retry.RetryError, match="TARGET_DRIFT"):
        retry.load_retry_manifest()
    review.update(semantic_review="approved", review_id="fresh-review")
    assert retry.load_retry_manifest()["attempt"]["experiment_id"] == "fresh-experiment"


def test_source_qualification_rechecks_current_scoped_input_bytes(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("approved source\n")

    def sha(data):
        return hashlib.sha256(data).hexdigest()

    profile = ResourceProfile()
    scope = retry.DeploymentScope(
        image_metadata={"path": "image.json", "sha256": "a" * 64},
        runtime_identity={"path": "runtime.json", "sha256": "b" * 64},
        resource_profile_file={"path": "resources.json", "sha256": "c" * 64},
        resources=profile,
        resource_profile_sha256=profile.sha256,
        image_digest="sha256:" + "d" * 64,
        launcher_sha256="e" * 64,
        driver_sha256="f" * 64,
        seccomp_sha256="0" * 64,
        checker_versions={},
        binaries={},
        inputs={"source.py": sha(source.read_bytes())},
    )
    (tmp_path / "scope.json").write_text(json.dumps(scope.model_dump(mode="json")))
    qualification = tmp_path / "qualification.json"
    qualification.write_text(
        json.dumps(
            {
                "mechanical_status": "satisfied",
                "production_qualified": False,
                "scope_sha256": scope.sha256,
                "scope": scope.model_dump(mode="json"),
            }
        )
    )
    monkeypatch.setattr(retry, "ROOT", tmp_path)

    def current_scope(repository, *, image_metadata, runtime_identity, resource_profile):
        assert repository == tmp_path
        assert image_metadata == scope.image_metadata
        assert runtime_identity == scope.runtime_identity
        assert resource_profile == scope.resource_profile_file
        return scope.model_copy(update={"inputs": {"source.py": sha(source.read_bytes())}})

    monkeypatch.setattr(retry, "capture_scope", current_scope)
    retry._source_qualification(qualification, scope.sha256, scope.image_digest)
    source.write_text("tampered source\n")
    with pytest.raises(retry.RetryError, match="SOURCE_QUALIFICATION"):
        retry._source_qualification(qualification, scope.sha256, scope.image_digest)
