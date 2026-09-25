"""Bounded working entry points over exact canonical science."""

import pytest
from test_sharing import approaches, artifact

from physharness.domain import ArtifactCreate, Principal, TaskCreate, canonical_json
from physharness.errors import HarnessError
from physharness.memory import PortableMemory
from physharness.storage import RecordRow


def test_large_history_keeps_exact_target_and_paged_obligations(lab):
    service, owner, experiment, _, (alpha, _) = approaches(lab, "none")
    tasks = [
        service.create_task(
            TaskCreate(branch_id=alpha.branch_id, objective=f"Attempt {index}"),
            alpha,
            f"attempt-{index}",
        )
        for index in range(80)
    ]
    memory = PortableMemory(service)
    context = memory.working_context(
        alpha.branch_id, alpha, task_id=tasks[0]["id"], max_bytes=12000, page_size=3
    )
    assert context["format"] == "physharness.working-context.v1"
    assert context["target"] == service.get_record("problem", experiment["problem_id"], owner)
    assert context["current_task"] == tasks[0]
    assert len(context["indices"]["open_tasks"]["items"]) == 3
    assert context["indices"]["open_tasks"]["complete"] is False
    assert context["indices"]["open_tasks"]["next_cursor"]
    assert context["indices"]["open_tasks"]["retrieval"]["filter"] == "status!=completed"
    assert context["indices"]["open_tasks"]["retrieval"]["branch_id"] == alpha.branch_id
    page = memory.index_page(
        alpha.branch_id,
        alpha,
        index="open_tasks",
        limit=3,
        after=context["indices"]["open_tasks"]["next_cursor"],
    )
    assert page["items"]
    assert not (
        {item["id"] for item in page["items"]}
        & {item["id"] for item in context["indices"]["open_tasks"]["items"]}
    )
    assert context["history_retained"] is True
    assert len(service.list_records("task", owner, experiment["id"])) == 80


def test_working_context_envelope_and_scoped_record_read(lab):
    service, _, _, _, (alpha, beta) = approaches(lab, "none")
    own = artifact(service, alpha, "exact evidence")
    private = artifact(service, beta, "private evidence")
    memory = PortableMemory(service)
    context = memory.working_context(
        alpha.branch_id, alpha, selected_ids=[own["id"]], max_bytes=12000, page_size=0
    )
    assert context["selected_references"][0]["artifact_sha256"] == own["sha256"]
    assert (
        memory.read_record(alpha.branch_id, alpha, kind="artifact", identifier=own["id"])["record"]
        == own
    )
    with pytest.raises(HarnessError):
        memory.read_record(alpha.branch_id, alpha, kind="artifact", identifier=private["id"])
    with pytest.raises(HarnessError):
        memory.working_context(alpha.branch_id, alpha, selected_ids=[private["id"]])
    with pytest.raises(HarnessError) as exc:
        memory.working_context(alpha.branch_id, alpha, max_bytes=40)
    assert exc.value.code == "SCIENTIFIC_CORE_TOO_LARGE"


def test_working_context_keeps_exact_source_obligations_and_diagnostics_readable(lab):
    service, owner, experiment, _, (alpha, _) = approaches(lab, "none")
    source_text = "theorem candidate : True := by trivial"
    source = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="lean_source", content=source_text),
        alpha,
        "current-source",
    )
    task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Discharge the exact target"),
        alpha,
        "current-obligation",
    )
    receipt = service.verify_candidate(
        experiment["id"], source["id"], False, alpha, "check-current-source"
    )
    view = PortableMemory(service).working_context(
        alpha.branch_id, alpha, task_id=task["id"], max_bytes=32000, page_size=0
    )
    work = view["readable_work"]
    assert work["active_source"]["content"] == source_text
    assert work["active_source"]["reference"]["artifact_sha256"] == source["sha256"]
    assert work["last_diagnostics"]["record"]["id"] == receipt["id"]
    assert task["id"] in {item["record"]["id"] for item in work["open_obligations"]}
    assert (
        view["target"]["assumptions"]
        == service.get_record("problem", experiment["problem_id"], owner)["assumptions"]
    )


def test_readable_work_uses_limited_scoped_queries(lab, monkeypatch):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "none")
    for index in range(20):
        service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"], kind="lean_source", content=f"source {index}"
            ),
            alpha,
            f"source-{index}",
        )
    hidden = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="lean_source", content="hidden"),
        beta,
        "hidden-source",
    )
    memory = PortableMemory(service)

    def no_full_history_scan(*_args, **_kwargs):
        raise AssertionError("working view must not materialize experiment history")

    monkeypatch.setattr(memory, "_records", no_full_history_scan)
    view = memory.working_context(alpha.branch_id, alpha, max_bytes=32000, page_size=0)
    assert view["readable_work"]["active_source"]["content"] == "source 19"
    assert view["readable_work"]["active_source"]["reference"]["id"] != hidden["id"]


def test_graph_page_links_exact_visible_task_dependencies(lab):
    service, _, _, _, (alpha, beta) = approaches(lab, "none")
    prerequisite = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Lemma"), alpha, "prerequisite"
    )
    successor = service.create_task(
        TaskCreate(
            branch_id=alpha.branch_id, objective="Main", dependency_ids=[prerequisite["id"]]
        ),
        alpha,
        "successor",
    )
    hidden = service.create_task(
        TaskCreate(branch_id=beta.branch_id, objective="Private"), beta, "hidden"
    )
    memory = PortableMemory(service)
    cursor, nodes, edges = None, [], []
    while True:
        page = memory.research_graph_page(alpha.branch_id, alpha, limit=1, after=cursor)
        nodes.extend(page["items"])
        edges.extend(page["edges"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert successor["id"] in {item["id"] for item in nodes}
    assert hidden["id"] not in {item["id"] for item in nodes}
    assert {
        "source_id": successor["id"],
        "target_id": prerequisite["id"],
        "relation": "requires",
        "source_revision": successor["revision"],
    } in edges


def test_failed_attempts_accepted_claims_and_status_refresh(lab):
    service, owner, experiment, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    for index in range(25):
        candidate = artifact(service, alpha, f"candidate-{index}")
        receipt = service.verify_candidate(
            experiment["id"], candidate["id"], False, alpha, f"verify-{index}"
        )
        service.process_verification(
            receipt["id"], Principal(id="checker", project_id=owner.project_id, role="operator")
        )
    context = memory.working_context(alpha.branch_id, alpha, page_size=2, max_bytes=16000)
    failed = context["indices"]["failed_attempts"]
    assert len(failed["items"]) == 2 and failed["complete"] is False
    assert failed["retrieval"]["kind"] == "verification"
    assert (
        len(memory.index_page(alpha.branch_id, alpha, index="failed_attempts", limit=50)["items"])
        == 25
    )
    assert context["indices"]["accepted_claims"]["complete"] is True

    claim = service.create_claim(
        experiment["id"], "Claim under review", [], "conjecture", None, alpha, "claim-under-review"
    )
    assert claim["id"] in {
        r["id"] for r in memory.index_page(alpha.branch_id, alpha, index="open_claims")["items"]
    }
    # A forged verified label is never silently omitted from the working context.
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, claim["id"]), {"proof_status": "verified"})
    with pytest.raises(HarnessError) as exc:
        memory.working_context(alpha.branch_id, alpha, page_size=2)
    assert exc.value.code == "CONTEXT_EVIDENCE_INVALID"


def test_chunk_read_is_byte_exact_bounded_and_excludes_native(lab):
    service, _, experiment, _, (alpha, beta) = approaches(lab, "none")
    content = "é🚀" * 8
    own = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="text", content=content),
        alpha,
        "unicode-artifact",
    )
    native = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="native_checkpoint", content="private"),
        alpha,
        "native-artifact",
    )
    memory = PortableMemory(service)
    import base64

    chunks, offset = [], 0
    while True:
        result = memory.read_artifact_chunk(
            alpha.branch_id, alpha, artifact_id=own["id"], offset=offset, max_bytes=3
        )
        chunks.append(base64.b64decode(result["content_base64"]))
        offset = result["next_offset"]
        if result["complete"]:
            break
    assert b"".join(chunks) == content.encode()
    assert result["reference"]["artifact_sha256"] == own["sha256"]
    whole = memory.read_artifact_chunk(alpha.branch_id, alpha, artifact_id=own["id"])
    assert whole["content_utf8"] == content
    assert whole["next_offset"] == len(content.encode("utf-8"))
    indexed = memory.index_page(alpha.branch_id, alpha, index="artifacts")["items"]
    assert own["id"] in {item["id"] for item in indexed}
    assert native["id"] not in {item["id"] for item in indexed}
    with pytest.raises(HarnessError):
        memory.read_artifact_chunk(alpha.branch_id, alpha, artifact_id=native["id"])
    with pytest.raises(HarnessError):
        memory.read_artifact_chunk(beta.branch_id, beta, artifact_id=own["id"])


def test_readable_lean_chunk_preserves_708_exact_bytes(lab):
    service, _, experiment, _, (alpha, _) = approaches(lab, "none")
    source = "theorem example : True := by trivial\n" + "-- algebra\n" * 67
    source = source[:708].ljust(708, " ")
    artifact = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="lean_source", content=source),
        alpha,
        "readable-source",
    )
    chunk = PortableMemory(service).read_artifact_chunk(
        alpha.branch_id, alpha, artifact_id=artifact["id"]
    )
    assert chunk["content_utf8"] == source
    assert chunk["total_bytes"] == chunk["next_offset"] == 708
    assert chunk["complete"] is True


def test_working_context_reserves_all_index_manifests_and_rechecks_review(lab):
    service, owner, experiment, _, (alpha, _) = approaches(lab, "none")
    for index in range(20):
        artifact(service, alpha, f"artifact-{index}")
    memory = PortableMemory(service)
    shell = memory.working_context(alpha.branch_id, alpha, page_size=0)
    size = len(canonical_json(shell).encode())
    context = memory.working_context(alpha.branch_id, alpha, page_size=20, max_bytes=size + 20)
    assert len(canonical_json(context).encode()) <= size + 20
    assert set(context["indices"]) == {
        "open_tasks",
        "open_claims",
        "accepted_claims",
        "failed_attempts",
        "artifacts",
    }
    assert context["indices"]["artifacts"]["complete"] is False
    with service.db.transaction() as session:
        review_id = service.get_record("problem", experiment["problem_id"], owner)["review_id"]
        service._replace(session, session.get(RecordRow, review_id), {"decision": "rejected"})
    with pytest.raises(HarnessError) as exc:
        memory.working_context(alpha.branch_id, alpha)
    assert exc.value.code == "CONTEXT_REVIEW_INVALID"


def test_working_context_rejects_stale_target_binding(lab):
    service, _, experiment, _, (alpha, _) = approaches(lab, "none")
    memory = PortableMemory(service)
    assert (
        memory.working_context(alpha.branch_id, alpha)["target"]["target_digest"]
        == (experiment["target_digest"])
    )
    with service.db.transaction() as session:
        service._replace(
            session, session.get(RecordRow, experiment["problem_id"]), {"target_digest": "0" * 64}
        )
    with pytest.raises(HarnessError) as exc:
        memory.working_context(alpha.branch_id, alpha)
    assert exc.value.code == "CONTEXT_TARGET_INVALID"


def test_graph_rejects_unbounded_single_node_and_pages_hidden_scan(lab, monkeypatch):
    service, _, _, branches, (alpha, beta) = approaches(lab, "none")
    memory = PortableMemory(service)
    dependencies = [
        service.create_task(
            TaskCreate(branch_id=alpha.branch_id, objective=str(i)), alpha, f"dependency-{i}"
        )
        for i in range(12)
    ]
    high_fanout = service.create_task(
        TaskCreate(
            branch_id=alpha.branch_id,
            objective="Combine",
            dependency_ids=[task["id"] for task in dependencies],
        ),
        alpha,
        "high-fanout",
    )
    cursor = None
    for _ in range(30):
        try:
            page = memory.research_graph_page(
                alpha.branch_id, alpha, limit=1, after=cursor, max_edges=3
            )
        except HarnessError as exc:
            assert exc.code == "GRAPH_NODE_TOO_LARGE"
            break
        cursor = page["next_cursor"]
    else:
        pytest.fail("High-fanout node was not rejected")

    import physharness.domain as domain

    sequence = iter(range(200))
    monkeypatch.setattr(domain, "new_id", lambda: f"zz-{next(sequence):032d}")
    hidden = [
        service.create_task(
            TaskCreate(branch_id=beta.branch_id, objective=f"Hidden {i}"), beta, f"hidden-{i}"
        )
        for i in range(105)
    ]
    visible = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="Later"), alpha, "later-visible"
    )
    cursor = max(
        [
            high_fanout["id"],
            *[task["id"] for task in dependencies],
            *[branch["id"] for branch in branches],
        ]
    )
    seen = []
    blank_page = False
    for _ in range(4):
        page = memory.research_graph_page(alpha.branch_id, alpha, limit=1, after=cursor)
        seen.extend(page["items"])
        blank_page = blank_page or bool(not page["items"] and page["next_cursor"])
        if not page["next_cursor"]:
            break
        cursor = page["next_cursor"]
    assert visible["id"] in {node["id"] for node in seen}
    assert blank_page
    assert not ({node["id"] for node in seen} & {task["id"] for task in hidden})
