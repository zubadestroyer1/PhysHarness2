"""Branch readers learn nothing about records outside their scope, not even identifiers."""

import base64

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
        cursors.append(cursor)
    pytest.fail("Graph pagination did not terminate")


def assert_opaque(cursors, identifiers):
    """Cursors carry no record ID and no hidden-row count, in any encoding, at any length."""
    assert cursors and len({len(cursor) for cursor in cursors}) == 1
    for cursor in cursors:
        assert "+" not in cursor
        raw = base64.urlsafe_b64decode(cursor.partition(".")[2] + "==")
        for identifier in identifiers:
            assert identifier not in cursor and identifier.encode() not in raw


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
    assert len(expected) == len(set(expected))
    nodes, cursors = page_all(memory, alpha.branch_id, alpha, limit=1)
    assert nodes == expected  # No record is skipped or repeated across cursors.
    assert_opaque(cursors, hidden | set(expected))


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
        assert_opaque(cursors, hidden | set(visible))
    with pytest.raises(HarnessError) as error:
        service.page_records("task", alpha, experiment["id"], 1, "anchor+000000000")
    assert error.value.code == "INVALID_CURSOR"


def _cursor_case(lab, monkeypatch):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "none")
    sequence = iter(range(10_000))
    monkeypatch.setattr(domain, "new_id", lambda: f"zz-{next(sequence):08d}")
    visible = [
        service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="v"), alpha, f"v{i}")[
            "id"
        ]
        for i in range(2)
    ]
    hidden = [
        service.create_task(TaskCreate(branch_id=beta.branch_id, objective="s"), beta, f"h{i}")[
            "id"
        ]
        for i in range(120)
    ]
    visible.append(
        service.create_task(TaskCreate(branch_id=alpha.branch_id, objective="v"), alpha, "v2")["id"]
    )
    return service, experiment, alpha, beta, visible, hidden


def test_crafted_or_foreign_cursors_are_rejected_before_any_scan(lab, monkeypatch):
    service, experiment, alpha, beta, visible, hidden = _cursor_case(lab, monkeypatch)
    memory = PortableMemory(service)
    records = service.page_records("task", alpha, experiment["id"], 1)
    history = memory.history_page(alpha.branch_id, alpha, kind="task", limit=1)
    graph = memory.research_graph_page(alpha.branch_id, alpha, limit=1)
    issued = records["next_cursor"]
    tampered = issued[:-2] + ("AA" if issued[-2:] != "AA" else "BB")
    crafted = [
        "+000000001",  # the re-review's offset probe from the start
        visible[0],
        visible[0] + "+000000001",
        hidden[0],
        hidden[0][:-1],
        hidden[0][:-1] + "\U0010ffff",
        "pc1." + "A" * len(issued[4:]),
        tampered,
        graph["next_cursor"],  # issued for another query
        service.page_records("task", beta, experiment["id"], 1)["next_cursor"],  # another reader
        service.page_records("claim", alpha, experiment["id"], 1)["next_cursor"] or "pc1.x",
    ]
    for cursor in crafted:
        with pytest.raises(HarnessError) as error:
            service.page_records("task", alpha, experiment["id"], 1, cursor)
        assert error.value.code == "INVALID_CURSOR", cursor
        with pytest.raises(HarnessError) as error:
            memory.history_page(alpha.branch_id, alpha, kind="task", limit=1, after=cursor)
        assert error.value.code == "INVALID_CURSOR", cursor
    for cursor in [*crafted[:8], records["next_cursor"], history["next_cursor"]]:
        with pytest.raises(HarnessError) as error:
            memory.research_graph_page(alpha.branch_id, alpha, limit=1, after=cursor)
        assert error.value.code == "CONTEXT_INPUT_INVALID", cursor
    # An issued cursor still works for its own reader and query, and replays exactly.
    first = service.page_records("task", alpha, experiment["id"], 1, issued)
    again = service.page_records("task", alpha, experiment["id"], 1, issued)
    assert first["items"] == again["items"] and first["next_cursor"] != again["next_cursor"]
    assert (
        service.page_records("task", alpha, experiment["id"], 5, first["next_cursor"])["items"]
        == service.page_records("task", alpha, experiment["id"], 5, again["next_cursor"])["items"]
    )
    assert history["next_cursor"]


def test_operator_pages_keep_exact_order_with_opaque_cursors(lab, monkeypatch):
    service, experiment, alpha, beta, visible, hidden = _cursor_case(lab, monkeypatch)
    operator = alpha.model_copy(
        update={"role": "operator", "experiment_id": None, "branch_id": None}
    )
    everything = sorted(visible + hidden)
    items, cursor = [], None
    while True:
        page = service.page_records("task", operator, experiment["id"], 7, cursor)
        items.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert cursor.startswith("pc1.")
    assert items == everything
    assert [row["id"] for row in service.list_records("task", operator, experiment["id"], 7)] == (
        everything
    )


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
