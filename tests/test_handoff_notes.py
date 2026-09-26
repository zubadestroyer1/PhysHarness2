"""Attributed portable notes survive ordinary successor obligation changes."""

import pytest
from test_sharing import approaches, artifact

from physharness.domain import Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.memory import PortableMemory
from physharness.storage import RecordRow


def test_latest_task_notes_survive_completed_obligation_without_promoting_evidence(lab):
    service, owner, _, _, (alpha, beta) = approaches(lab, "none")
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Investigate"), alpha, "task"
    )
    candidate = artifact(service, alpha, "candidate")
    controller = Principal(id="controller", project_id=owner.project_id, role="operator")
    lease = service.acquire_task(task["id"], alpha.id, 60, controller, "lease")
    memory = PortableMemory(service)
    saved = memory.checkpoint(
        alpha.branch_id,
        alpha,
        "first-notes",
        approach="Try symmetry",
        unresolved_obligations=["Prove convergence"],
        summary="Unverified pattern",
        evidence_ids=[candidate["id"]],
        task_id=task["id"],
        holder=alpha.id,
        fence=lease["fence"],
    )
    current = memory.handoff_notes(alpha.branch_id, alpha, task_id=task["id"])
    assert current["checkpoint_id"] == saved["id"]
    assert current["source_stale"] is False
    assert current["approach"]["evidence_status"] == "unverified"
    assert current["evidence_references"][0]["id"] == candidate["id"]
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, task["id"]), {"status": "completed"})
    stale = memory.handoff_notes(alpha.branch_id, alpha, task_id=task["id"])
    assert stale["source_stale"] is True
    assert stale["approach"] == current["approach"]
    assert stale["summary"] == current["summary"]
    assert stale["unresolved_obligations"]["evidence_status"] == "unverified"
    assert stale["evidence_references"] == current["evidence_references"]
    assert memory.handoff_notes(beta.branch_id, beta) is None
    with pytest.raises(HarnessError):
        memory.handoff_notes(beta.branch_id, beta, task_id=task["id"])


def test_handoff_notes_revalidate_evidence_target_and_size(lab):
    service, owner, experiment, _, (alpha, _) = approaches(lab, "none")
    candidate = artifact(service, alpha, "candidate")
    memory = PortableMemory(service)
    memory.checkpoint(
        alpha.branch_id,
        alpha,
        "notes",
        approach="Try cases",
        unresolved_obligations=["Close gap"],
        evidence_ids=[candidate["id"]],
    )
    with pytest.raises(HarnessError) as too_small:
        memory.handoff_notes(alpha.branch_id, alpha, max_bytes=100)
    assert too_small.value.code == "CONTEXT_ENVELOPE_EXCEEDED"
    with service.db.transaction() as session:
        service._replace(
            session, session.get(RecordRow, candidate["id"]), {"provenance": {"changed": True}}
        )
    notes = memory.handoff_notes(alpha.branch_id, alpha)
    assert notes["source_stale"] is True
    assert notes["evidence_references"] == []
    assert notes["stale_reference_ids"] == [candidate["id"]]
    with service.db.transaction() as session:
        service._replace(
            session, session.get(RecordRow, experiment["problem_id"]), {"target_digest": "0" * 64}
        )
    with pytest.raises(HarnessError) as changed:
        memory.handoff_notes(alpha.branch_id, alpha)
    assert changed.value.code == "CONTEXT_STALE_TARGET"


def test_small_research_notes_roundtrip_with_large_history(lab):
    service, owner, experiment, _, (alpha, _) = approaches(lab, "none")
    tasks = [
        service.create_task(
            TaskCreate(branch_id=alpha.branch_id, objective=f"Attempt {index}"),
            alpha,
            f"attempt-{index}",
        )
        for index in range(160)
    ]
    memory = PortableMemory(service)
    controller = Principal(id="controller", project_id=owner.project_id, role="operator")
    lease = service.acquire_task(tasks[0]["id"], alpha.id, 60, controller, "large-lease")
    with pytest.raises(HarnessError) as old:
        memory.checkpoint(
            alpha.branch_id,
            alpha,
            "large-v1",
            approach="Try induction",
            unresolved_obligations=["Resolve branch"],
            max_bytes=8192,
            task_id=tasks[0]["id"],
            holder=alpha.id,
            fence=lease["fence"],
        )
    assert old.value.code == "SCIENTIFIC_CORE_TOO_LARGE"
    issued = memory.checkpoint_research_notes(
        alpha.branch_id,
        alpha,
        "small-v1",
        approach="Try induction",
        unresolved_obligations=["Resolve branch"],
        summary="Still unproved",
        task_id=tasks[0]["id"],
        holder=alpha.id,
        fence=lease["fence"],
        max_bytes=8192,
    )
    assert issued["context_format"] == "physharness.research-notes.v1"
    assert issued["size_bytes"] < 8192
    notes = memory.handoff_notes(alpha.branch_id, alpha, task_id=tasks[0]["id"])
    assert notes["checkpoint_id"] == issued["id"]
    assert notes["source_stale"] is False
    assert notes["approach"]["text"] == "Try induction"
    assert notes["approach"]["evidence_status"] == "unverified"
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, tasks[1]["id"]), {"status": "completed"})
    successor = memory.handoff_notes(alpha.branch_id, alpha, task_id=tasks[0]["id"])
    assert successor["source_stale"] is True
    assert successor["approach"] == notes["approach"]
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, tasks[1]["id"]), {"status": "queued"})
        service._replace(session, session.get(RecordRow, tasks[2]["id"]), {"status": "completed"})
    same_count = memory.handoff_notes(alpha.branch_id, alpha, task_id=tasks[0]["id"])
    assert same_count["source_stale"] is True
    assert service.get_record("experiment", experiment["id"], owner)["status"] == "queued"


def test_memory_pages_enforce_output_envelope(lab):
    service, _, _, _, (alpha, _) = approaches(lab, "none")
    service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="One"), alpha, "page")
    memory = PortableMemory(service)
    with pytest.raises(HarnessError) as history:
        memory.history_page(alpha.branch_id, alpha, kind="task", max_bytes=1)
    assert history.value.code == "CONTEXT_ENVELOPE_EXCEEDED"
    with pytest.raises(HarnessError) as index:
        memory.index_page(alpha.branch_id, alpha, index="open_tasks", max_bytes=1)
    assert index.value.code == "CONTEXT_ENVELOPE_EXCEEDED"
