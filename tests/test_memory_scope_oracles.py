"""Branch readers learn nothing about records outside their scope, not even identifiers."""

import pytest
from test_core import setup_experiment
from test_sharing import approaches

import physharness.domain as domain
from physharness.domain import ArtifactCreate, BranchCreate, ExperimentCreate, TaskCreate
from physharness.errors import HarnessError
from physharness.memory import PortableMemory


def page_all(memory, branch_id, reader, *, limit):
    nodes, cursors = [], []
    cursor = None
    for _ in range(1000):
        page = memory.research_graph_page(branch_id, reader, limit=limit, after=cursor)
        nodes.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            assert page["complete"] is True
            return nodes, cursors
        assert not cursors or cursor > cursors[-1]  # Cursors still only move forward.
        cursors.append(cursor)
    pytest.fail("Graph pagination did not terminate")


@pytest.mark.parametrize("sharing", ["none", "verified"])
def test_graph_cursor_never_names_hidden_records_and_pages_exactly(lab, monkeypatch, sharing):
    service, author, _, _, (alpha, beta) = approaches(lab, sharing)
    memory = PortableMemory(service)
    sequence = iter(range(10_000))
    # Ordered IDs after every fixture UUID: long hidden runs force blank scan windows.
    monkeypatch.setattr(domain, "new_id", lambda: f"zz-{next(sequence):08d}")
    hidden, visible = set(), []

    def task(agent, name):
        record = service.create_task(
            TaskCreate(branch_id=agent.branch_id, objective=name), agent, name
        )
        if agent is alpha:
            visible.append(record["id"])
        else:
            hidden.add(record["id"])

    task(alpha, "first")
    for i in range(150):
        task(beta, f"hidden-{i}")
    task(alpha, "second")
    for i in range(3):
        task(beta, f"late-hidden-{i}")
    task(alpha, "third")
    for i in range(120):
        task(beta, f"tail-hidden-{i}")

    expected, _ = page_all(memory, alpha.branch_id, alpha, limit=100)
    assert set(visible) <= set(expected) and not set(expected) & hidden
    nodes, cursors = page_all(memory, alpha.branch_id, alpha, limit=1)
    assert nodes == expected  # No record is skipped or repeated across cursors.
    assert cursors and not any(identifier in cursor for cursor in cursors for identifier in hidden)


def test_record_and_history_page_cursors_never_name_hidden_records(lab, monkeypatch):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "none")
    memory = PortableMemory(service)
    sequence = iter(range(10_000))
    monkeypatch.setattr(domain, "new_id", lambda: f"zz-{next(sequence):08d}")
    hidden, visible = set(), []
    for block, (agent, count) in enumerate(
        ((alpha, 1), (beta, 130), (alpha, 1), (beta, 101), (alpha, 1))
    ):
        for i in range(count):
            record = service.create_task(
                TaskCreate(branch_id=agent.branch_id, objective="t"), agent, f"t{block}-{i}"
            )
            if agent is alpha:
                visible.append(record["id"])
            else:
                hidden.add(record["id"])

    def pages(read):
        items, cursors, cursor = [], [], None
        for _ in range(1000):
            page = read(cursor)
            items.extend(item.get("id") for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items, cursors
            assert not cursors or cursor > cursors[-1]
            cursors.append(cursor)
        pytest.fail("Pagination did not terminate")

    for read in (
        lambda after: service.page_records("task", alpha, experiment["id"], 1, after),
        lambda after: memory.history_page(
            alpha.branch_id, alpha, kind="task", limit=1, after=after
        ),
    ):
        items, cursors = pages(read)
        assert items == visible
        assert not any(identifier in cursor for cursor in cursors for identifier in hidden)
    with pytest.raises(HarnessError) as error:
        service.page_records("task", alpha, experiment["id"], 1, "anchor+000000000")
    assert error.value.code == "INVALID_CURSOR"


def test_hidden_and_missing_evidence_ids_are_indistinguishable(lab):
    service, author, _ = lab
    operator = author.model_copy(update={"role": "operator"})
    first, _ = setup_experiment(lab)
    service.transition_experiment(first["id"], "start", 1, operator, "start-first")
    own = service.create_branch(
        first["id"], BranchCreate(title="A", objective="A"), operator, "own"
    )
    sibling = service.create_branch(
        first["id"], BranchCreate(title="S", objective="S"), operator, "sibling"
    )
    private = service.create_experiment(
        ExperimentCreate(
            campaign_id=first["campaign_id"],
            problem_id=first["problem_id"],
            models=first["models"],
            budget=first["budget"],
            sharing="none",
        ),
        operator,
        "private-experiment",
    )
    service.transition_experiment(private["id"], "start", 1, operator, "start-private")
    other = service.create_branch(
        private["id"], BranchCreate(title="B", objective="B"), operator, "other"
    )

    def artifact(experiment, branch, kind, key):
        return service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"], branch_id=branch["id"], kind=kind, content=key
            ),
            operator,
            key,
        )["id"]

    agent = domain.Principal(
        id="agent-a",
        project_id=author.project_id,
        role="agent",
        experiment_id=first["id"],
        branch_id=own["id"],
    )
    probes = {
        "other experiment": private["id"],
        "other branch": other["id"],
        "other native checkpoint": artifact(private, other, "native_checkpoint", "n1"),
        "other lean source": artifact(private, other, "lean_source", "l1"),
        "own native checkpoint": artifact(first, own, "native_checkpoint", "n2"),
        "sibling task": service.create_task(
            TaskCreate(branch_id=sibling["id"], objective="private"), operator, "sibling-task"
        )["id"],
        "missing": "00000000-0000-0000-0000-000000000000",
    }
    memory = PortableMemory(service)

    def attempts(identifier):
        yield lambda: memory.working_context(own["id"], agent, selected_ids=[identifier])
        yield lambda: memory.checkpoint(
            own["id"],
            agent,
            f"checkpoint-{identifier}",
            approach="Probe",
            unresolved_obligations=["Probe"],
            evidence_ids=[identifier],
        )
        yield lambda: memory.checkpoint_research_notes(
            own["id"],
            agent,
            f"notes-{identifier}",
            approach="Probe",
            unresolved_obligations=["Probe"],
            evidence_ids=[identifier],
        )

    observed = {}
    for label, identifier in probes.items():
        for index, attempt in enumerate(attempts(identifier)):
            with pytest.raises(HarnessError) as error:
                attempt()
            envelope = error.value.envelope()["error"]
            envelope.pop("operation_id")
            observed[label, index] = (envelope, error.value.status)
    for index in range(3):
        assert len({repr(observed[label, index]) for label in probes}) == 1
    assert observed["missing", 0][0]["code"] == "NOT_FOUND"
