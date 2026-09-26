"""Portable compaction against real canonical services; no model calls."""

import json

import pytest
from test_research_services import accepted_fixture
from test_sharing import approaches, artifact

from physharness.domain import ArtifactCreate, Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.memory import PortableMemory
from physharness.storage import RecordRow


def capture(memory, branch, actor, key="checkpoint", **kwargs):
    return memory.checkpoint(
        branch,
        actor,
        key,
        approach="Try a spectral decomposition",
        unresolved_obligations=["Justify convergence"],
        **kwargs,
    )


def test_checkpoint_preserves_exact_science_failed_attempts_and_attributed_summary(lab):
    service, author, exp, branches, (alpha, _) = approaches(lab, "none")
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Do not assume compactness"), alpha, "task"
    )
    candidate = artifact(service, alpha, "failed candidate")
    receipt = service.verify_candidate(exp["id"], candidate["id"], False, alpha, "verify")
    controller = Principal(id="controller", project_id=author.project_id, role="operator")
    failed = service.process_verification(receipt["id"], controller)
    memory = PortableMemory(service)
    saved = capture(memory, alpha.branch_id, alpha, summary="I proved everything")
    restored = memory.restore(saved["id"], alpha)
    target = service.get_record("problem", exp["problem_id"], author)
    core = restored["scientific_core"]
    assert core["target"] == target
    assert core["review"]["id"] == target["review_id"]
    assert core["open_tasks"][0]["objective"] == "Do not assume compactness"
    assert core["open_tasks"][0]["reference"]["id"] == task["id"]
    assert core["failed_attempts"][0]["id"] == failed["id"]
    assert core["failed_attempts"][0]["evidence_status"]["status"] == "blocked"
    assert restored["summary"] == {
        "text": "I proved everything",
        "attributed_to": alpha.id,
        "evidence_status": "unverified",
    }
    assert service.list_records("claim", author) == []
    assert restored["native_continuation"] == "not_included"
    assert restored["portable"] is True
    assert service.artifact_content(candidate["id"], alpha) == b"failed candidate"


@pytest.mark.parametrize("envelope", [{"max_bytes": 20}, {"max_estimated_tokens": 2}])
def test_mandatory_scientific_core_overflow_fails_without_truncation(lab, envelope):
    service, _, _, _, (alpha, _) = approaches(lab, "none")
    with pytest.raises(HarnessError) as exc:
        capture(PortableMemory(service), alpha.branch_id, alpha, **envelope)
    assert exc.value.code == "SCIENTIFIC_CORE_TOO_LARGE"
    assert service.list_records("artifact", alpha) == []


def test_selected_history_is_hash_bound_paginated_and_budgeted(lab):
    service, _, _, _, (alpha, beta) = approaches(lab, "none")
    own = [artifact(service, alpha, f"attempt {i}") for i in range(3)]
    secret = artifact(service, beta, "private branch")
    memory = PortableMemory(service)
    page = memory.history_page(alpha.branch_id, alpha, kind="artifact", limit=1)
    assert len(page["items"]) == 1 and page["next_cursor"]
    second = memory.history_page(
        alpha.branch_id, alpha, kind="artifact", limit=2, after=page["next_cursor"]
    )
    assert {r["id"] for r in page["items"] + second["items"]} == {r["id"] for r in own}
    saved = capture(memory, alpha.branch_id, alpha, evidence_ids=[own[0]["id"]])
    restored = memory.restore(saved["id"], alpha)
    assert [r["id"] for r in restored["history"]["references"]] == [own[0]["id"]]
    assert restored["history"]["complete"] is False
    assert restored["history"]["retained"] is True
    with pytest.raises(HarnessError):
        capture(memory, alpha.branch_id, alpha, "leak", evidence_ids=[secret["id"]])
    with pytest.raises(HarnessError) as exc:
        capture(memory, alpha.branch_id, alpha, "huge-summary", summary="a" * 100000)
    assert exc.value.code == "CONTEXT_ENVELOPE_EXCEEDED"


def test_own_kernel_acceptance_is_portable_but_not_shared(lab):
    service, _, _, branches, (other, owner), accepted = accepted_fixture(
        lab, "verified", assurance="kernel"
    )
    memory = PortableMemory(service)
    claim_id = accepted["claim_id"]
    page = memory.history_page(branches[1]["id"], owner, kind="claim")
    assert [item["id"] for item in page["items"]] == [claim_id]
    saved = capture(memory, branches[1]["id"], owner, evidence_ids=[claim_id, accepted["id"]])
    assert [item["id"] for item in memory.restore(saved["id"], owner)["history"]["references"]] == [
        claim_id,
        accepted["id"],
    ]
    with pytest.raises(HarnessError):
        service.get_record("claim", claim_id, other)


def test_checkpoint_lineage_and_idempotency_preserve_immutable_prior_context(lab):
    service, _, _, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    first = capture(memory, alpha.branch_id, alpha)
    assert capture(memory, alpha.branch_id, alpha) == first
    second = capture(memory, alpha.branch_id, alpha, "next", previous_checkpoint_id=first["id"])
    restored = memory.restore(second["id"], alpha)
    assert restored["lineage"]["previous_checkpoint_id"] == first["id"]
    assert restored["lineage"]["previous_sha256"] == first["sha256"]
    assert restored["lineage"]["generation"] == 2
    assert memory.restore(first["id"], alpha)["lineage"]["generation"] == 1
    with pytest.raises(HarnessError) as exc:
        capture(memory, alpha.branch_id, alpha, summary="changed")
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_restoration_rejects_changed_review_and_new_unresolved_failures(lab):
    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    first = capture(memory, alpha.branch_id, alpha)
    service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="New unfulfilled obligation"),
        alpha,
        "new-task",
    )
    with pytest.raises(HarnessError) as exc:
        memory.restore(first["id"], alpha)
    assert exc.value.code == "CONTEXT_STALE"
    second = capture(memory, alpha.branch_id, alpha, "next", previous_checkpoint_id=first["id"])
    reviewer = lab[2]
    service.review_problem(
        exp["problem_id"], "rejected", "Assumption missing", reviewer, "new-review"
    )
    with pytest.raises(HarnessError) as exc:
        memory.restore(second["id"], alpha)
    assert exc.value.code == "CONTEXT_STALE"


def test_restoration_rejects_corrupt_bytes_forged_status_and_unissued_checkpoint(lab):
    service, author, _, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    saved = capture(memory, alpha.branch_id, alpha)
    payload = memory.restore(saved["id"], alpha)
    # Generic creation of this kind is controller-only; an unissued record still fails.
    forged = service.create_artifact(
        ArtifactCreate(
            experiment_id=alpha.experiment_id,
            branch_id=alpha.branch_id,
            kind="checkpoint",
            content=json.dumps(payload),
        ),
        author.model_copy(update={"role": "operator"}),
        "forged",
    )
    with pytest.raises(HarnessError) as exc:
        memory.restore(forged["id"], alpha)
    assert exc.value.code == "CONTEXT_NOT_ISSUED"
    path = service.artifacts.path_for(saved["sha256"])
    path.write_bytes(b"tampered")
    with pytest.raises(HarnessError) as exc:
        memory.restore(saved["id"], alpha)
    assert exc.value.code == "ARTIFACT_INTEGRITY_ERROR"


def test_status_change_is_not_laundered_by_compaction(lab):
    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    source = artifact(service, alpha, "evidence")
    claim = service.create_claim(
        exp["id"], "Proposed statement", [], "conjecture", source["id"], alpha, "claim"
    )
    saved = capture(memory, alpha.branch_id, alpha, evidence_ids=[claim["id"]])
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, claim["id"]), {"proof_status": "verified"})
    with pytest.raises(HarnessError) as exc:
        memory.restore(saved["id"], alpha)
    assert exc.value.code == "CONTEXT_STALE"


def test_cross_branch_lineage_or_restore_denied_even_under_ideas(lab):
    service, _, _, _, (alpha, beta) = approaches(lab, "ideas")
    memory = PortableMemory(service)
    saved = capture(memory, alpha.branch_id, alpha)
    with pytest.raises(HarnessError):
        memory.restore(saved["id"], beta)
    with pytest.raises(HarnessError):
        capture(memory, beta.branch_id, beta, previous_checkpoint_id=saved["id"])
    with pytest.raises(HarnessError):
        memory.restore(saved["id"], alpha, expected_branch_id=beta.branch_id)


def test_task_checkpoint_requires_complete_current_fence(lab):
    service, author, _, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="work"), alpha, "task"
    )
    controller = Principal(id="controller", project_id=author.project_id, role="operator")
    lease = service.acquire_task(task["id"], alpha.id, 60, controller, "lease")
    saved = capture(
        memory, alpha.branch_id, alpha, task_id=task["id"], holder=alpha.id, fence=lease["fence"]
    )
    assert saved["branch_id"] == alpha.branch_id
    with pytest.raises(HarnessError) as exc:
        capture(
            memory,
            alpha.branch_id,
            alpha,
            "stale-fence",
            task_id=task["id"],
            holder=alpha.id,
            fence=lease["fence"] + 1,
        )
    assert exc.value.code == "STALE_LEASE"
    with pytest.raises(HarnessError):
        capture(memory, alpha.branch_id, alpha, "partial-fence", task_id=task["id"])


def test_unproved_claim_is_mandatory_even_when_history_selection_is_empty(lab):
    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    claim = service.create_claim(
        exp["id"],
        "A limiting argument is still unproved",
        ["Uniform bound required"],
        "conditional",
        None,
        alpha,
        "claim",
    )
    memory = PortableMemory(service)
    saved = capture(memory, alpha.branch_id, alpha, evidence_ids=[])
    open_claim = memory.restore(saved["id"], alpha)["scientific_core"]["open_claims"][0]
    assert open_claim["reference"]["id"] == claim["id"]
    assert open_claim["statement"] == "A limiting argument is still unproved"
    assert open_claim["assumptions"] == ["Uniform bound required"]


def test_rehashed_fake_status_and_changed_lineage_are_rejected(lab):
    from physharness.domain import canonical_json, digest_json

    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    source = artifact(service, alpha, "source")
    claim = service.create_claim(
        exp["id"], "Conjecture", [], "conjecture", source["id"], alpha, "claim"
    )
    memory = PortableMemory(service)
    first = capture(memory, alpha.branch_id, alpha, evidence_ids=[claim["id"]])
    second = capture(memory, alpha.branch_id, alpha, "second", previous_checkpoint_id=first["id"])
    data = json.loads(service.artifact_content(first["id"], alpha))
    data["history"]["references"][0]["evidence_status"]["proof_status"] = "verified"
    # Privileged test-only corruption rehashes bytes and canonical metadata, beyond
    # what an agent can submit; authoritative evidence still rejects invented status.
    content = canonical_json(data).encode()
    tampered_hash = service.artifacts.put(content)
    with service.db.transaction() as session:
        service._replace(
            session,
            session.get(RecordRow, first["id"]),
            {
                "sha256": tampered_hash,
                "context_sha256": digest_json(data),
                "size_bytes": len(content),
            },
        )
    with pytest.raises(HarnessError) as exc:
        memory.restore(first["id"], alpha)
    assert exc.value.code == "CONTEXT_STALE"
    with pytest.raises(HarnessError) as exc:
        memory.restore(second["id"], alpha)
    assert exc.value.code == "CONTEXT_LINEAGE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment_digest", "b" * 64),
        ("assumptions", ["changed assumption"]),
        ("definitions", {"limit": "changed"}),
    ],
)
def test_restoration_binds_exact_environment_assumptions_and_definitions(lab, field, value):
    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    saved = capture(memory, alpha.branch_id, alpha)
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, exp["problem_id"]), {field: value})
    with pytest.raises(HarnessError) as exc:
        memory.restore(saved["id"], alpha)
    assert exc.value.code == "CONTEXT_STALE"


def test_native_checkpoint_cannot_enter_portable_history(lab):
    service, author, _, _, (alpha, _) = approaches(lab, "none")
    native = service.create_artifact(
        ArtifactCreate(
            experiment_id=alpha.experiment_id,
            branch_id=alpha.branch_id,
            kind="native_checkpoint",
            content='{"provider_session_id":"opaque"}',
        ),
        author.model_copy(update={"role": "operator"}),
        "native",
    )
    memory = PortableMemory(service)
    assert memory.history_page(alpha.branch_id, alpha, kind="artifact")["items"] == []
    with pytest.raises(HarnessError) as exc:
        capture(memory, alpha.branch_id, alpha, evidence_ids=[native["id"]])
    # Native state is unreadable to agents, so it is indistinguishable from a missing ID.
    assert exc.value.code == "NOT_FOUND"
    with pytest.raises(HarnessError) as exc:
        capture(memory, alpha.branch_id, alpha, "own-branch", evidence_ids=[alpha.branch_id])
    assert exc.value.code == "CONTEXT_EVIDENCE_KIND"


def test_rehashed_summary_cannot_claim_authority(lab):
    from physharness.domain import canonical_json, digest_json

    service, _, _, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    saved = capture(memory, alpha.branch_id, alpha, summary="A model opinion")
    data = json.loads(service.artifact_content(saved["id"], alpha))
    data["summary"]["evidence_status"] = "verified"
    raw = canonical_json(data).encode()
    with service.db.transaction() as session:
        service._replace(
            session,
            session.get(RecordRow, saved["id"]),
            {
                "sha256": service.artifacts.put(raw),
                "context_sha256": digest_json(data),
                "size_bytes": len(raw),
                "estimated_tokens": (len(raw) + 3) // 4,
            },
        )
    with pytest.raises(HarnessError) as exc:
        memory.restore(saved["id"], alpha)
    assert exc.value.code == "CONTEXT_INTEGRITY"


def test_checkpoint_does_not_issue_after_artifact_upload_outlives_task_lease(lab, monkeypatch):
    import time

    from test_workspace_service import setup

    from physharness.storage import LeaseRow

    broker, service, experiment, _, _, _ = setup(lab)
    task = service.get_record("task", broker.task_id, broker.actor)
    with service.db.transaction() as session:
        session.get(LeaseRow, broker.task_id).expires_at = time.time() + 0.06
    original = service.artifacts.put

    def delayed(data):
        time.sleep(0.1)
        return original(data)

    monkeypatch.setattr(service.artifacts, "put", delayed)
    with pytest.raises(HarnessError) as error:
        PortableMemory(service).checkpoint(
            task["branch_id"],
            broker.actor,
            "slow-upload",
            approach="Retain assumptions",
            unresolved_obligations=["Target"],
            task_id=broker.task_id,
            holder=broker.holder,
            fence=broker.fence,
        )
    assert error.value.code == "STALE_LEASE"
    assert not [
        a for a in service.list_records("artifact", broker.actor) if a.get("context_format")
    ]
