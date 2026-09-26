"""Opt-in PostgreSQL races for task admission and durable reader delivery."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event

from physharness.artifacts import LocalArtifactStore
from physharness.domain import (
    BranchCreate,
    CampaignCreate,
    ExperimentCreate,
    Principal,
    ProblemCreate,
    TaskCreate,
)
from physharness.service import HarnessService
from physharness.storage import Database, EventRow
from physharness.worker_authority import worker_effects
from physharness.workforce_models import ConfigureWorkforceRequest, SeedPortfolioRequest


@pytest.fixture
def pg_lab(tmp_path):
    url = os.environ.get("PHYSHARNESS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No dedicated PostgreSQL endpoint for research-network races")
    schema = "research_network_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    db = Database(url)

    @event.listens_for(db.engine, "connect")
    def use_schema(connection, record):
        previous = connection.autocommit
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
        finally:
            connection.autocommit = previous

    try:
        db.create_schema()
        service = HarnessService(db, LocalArtifactStore(tmp_path / "artifacts"))
        researcher = Principal(id="researcher", project_id="network-pg", role="researcher")
        reviewer = Principal(id="reviewer", project_id="network-pg", role="reviewer")
        operator = Principal(id="operator", project_id="network-pg", role="operator")
        campaign = service.create_campaign(
            CampaignCreate(title="Network", objective="Synthetic", programs=["quantum"]),
            researcher,
            "campaign",
        )
        problem = service.create_problem(
            ProblemCreate(
                campaign_id=campaign["id"],
                title="Target",
                program="quantum",
                informal_statement="Synthetic target",
                formal_statement="theorem target : (1 : Nat) = 1 := by rfl",
                environment_digest="a" * 64,
            ),
            researcher,
            "problem",
        )
        service.review_problem(problem["id"], "approved", "Fixture", reviewer, "review")
        experiment = service.create_experiment(
            ExperimentCreate(
                campaign_id=campaign["id"],
                problem_id=problem["id"],
                models=[{"runtime": "responses", "model": "explicit-test-model"}],
                budget={"max_cost_usd": "1", "max_concurrency": 2, "max_runtime_seconds": 600},
                sharing="ideas",
                mode="replay",
            ),
            researcher,
            "experiment",
        )
        service.transition_experiment(experiment["id"], "start", 1, researcher, "start")
        service.configure_workforce(
            experiment["id"],
            ConfigureWorkforceRequest(max_total_tasks=2, max_pending_tasks=2),
            operator,
            "workforce",
        )
        yield service, operator, experiment
    finally:
        db.engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@pytest.mark.integration
def test_postgres_same_key_concurrent_portfolio_is_atomic(pg_lab):
    service, operator, experiment = pg_lab
    request = SeedPortfolioRequest(
        roots=[{"title": "A", "objective": "A"}, {"title": "B", "objective": "B"}]
    )

    def seed():
        return service.seed_portfolio(experiment["id"], request, operator, "same-seed")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: seed(), range(2)))
    assert first == second
    assert len(service.list_records("branch", operator, experiment["id"])) == 2
    assert len(service.list_records("task", operator, experiment["id"])) == 2
    assert service.research_capacity(experiment["id"], operator)["queued_tasks"] == 2


@pytest.mark.integration
def test_postgres_concurrent_reader_poll_reuses_one_delivery_and_ack_cursor(pg_lab):
    service, operator, experiment = pg_lab
    roots = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[{"title": "A", "objective": "A"}, {"title": "B", "objective": "B"}]
        ),
        operator,
        "seed",
    )["roots"]
    agents = [
        Principal(
            id=root["branch"]["execution_identity"],
            project_id=operator.project_id,
            role="agent",
            experiment_id=experiment["id"],
            branch_id=root["branch"]["id"],
        )
        for root in roots
    ]
    source, reader = agents
    sent = service.send_message(
        source.branch_id, reader.branch_id, "Addressed evidence", [], source, "message"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(
            pool.map(lambda _: service.discussion_updates(experiment["id"], reader), range(2))
        )
    assert first["delivery_id"] == second["delivery_id"]
    assert [item["retrieval_id"] for item in first["items"]] == [sent["id"]]
    assert service.read_research_message(sent["id"], reader)["content"] == "Addressed evidence"
    with ThreadPoolExecutor(max_workers=2) as pool:
        ack, duplicate_ack = list(
            pool.map(
                lambda _: service.acknowledge_discussion_updates(
                    experiment["id"], first["delivery_id"], reader, "ack"
                ),
                range(2),
            )
        )
    assert duplicate_ack == ack
    assert ack["next_cursor"] >= first["items"][0]["sequence"]
    assert service.discussion_updates(experiment["id"], reader)["items"] == []


@pytest.mark.integration
def test_postgres_lower_sequence_committing_late_is_still_delivered(pg_lab):
    # SERIAL values are allocated at insert. A writer that allocates first and
    # commits last must not be skipped by an ack taken over a later sequence.
    service, operator, experiment = pg_lab
    roots = service.seed_portfolio(
        experiment["id"],
        SeedPortfolioRequest(
            roots=[{"title": "A", "objective": "A"}, {"title": "B", "objective": "B"}]
        ),
        operator,
        "seed",
    )["roots"]
    source, reader = (
        Principal(
            id=root["branch"]["execution_identity"],
            project_id=operator.project_id,
            role="agent",
            experiment_id=experiment["id"],
            branch_id=root["branch"]["id"],
        )
        for root in roots
    )
    allocated, release = threading.Event(), threading.Event()

    def pause_late_writer(session, flush_context):
        if threading.current_thread().name == "late-writer" and any(
            isinstance(row, EventRow) and row.kind == "message.created" for row in session.new
        ):
            allocated.set()
            assert release.wait(30)

    def send(content, key):
        message = service.send_message(source.branch_id, reader.branch_id, content, [], source, key)
        return message["id"]

    sent = {}
    late = threading.Thread(
        target=lambda: sent.setdefault("late", send("allocated first", "late")),
        name="late-writer",
    )
    early = threading.Thread(target=lambda: sent.setdefault("early", send("second", "early")))
    event.listen(service.db.sessions, "after_flush", pause_late_writer)
    delivered = []
    try:
        late.start()
        assert allocated.wait(30)
        early.start()
        early.join(1)
        batch = service.discussion_updates(experiment["id"], reader)
        if batch["items"]:
            delivered.extend(item["retrieval_id"] for item in batch["items"])
            service.acknowledge_discussion_updates(
                experiment["id"], batch["delivery_id"], reader, "ack-during-race"
            )
    finally:
        release.set()
        for thread in (late, early):
            if thread.ident:
                thread.join(30)
        event.remove(service.db.sessions, "after_flush", pause_late_writer)
    for attempt in range(3):
        batch = service.discussion_updates(experiment["id"], reader)
        if not batch["items"]:
            break
        delivered.extend(item["retrieval_id"] for item in batch["items"])
        service.acknowledge_discussion_updates(
            experiment["id"], batch["delivery_id"], reader, f"ack-{attempt}"
        )
    assert sorted(delivered) == sorted([sent["late"], sent["early"]])


@pytest.mark.integration
def test_postgres_peer_wait_wakes_on_reply_sent_before_registration(pg_lab):
    service, operator, experiment = pg_lab
    researcher = Principal(id="researcher", project_id="network-pg", role="researcher")
    agents = []
    for name in ("alpha", "beta"):
        branch = service.create_branch(
            experiment["id"], BranchCreate(title=name, objective=name), researcher, name
        )
        agents.append(
            Principal(
                id=f"worker-{name}",
                role="agent",
                project_id="network-pg",
                experiment_id=experiment["id"],
                branch_id=branch["id"],
            )
        )
    alpha, beta = agents
    a_task = service.create_task(
        TaskCreate(branch_id=alpha.branch_id, objective="A"), researcher, "a"
    )
    b_task = service.create_task(
        TaskCreate(branch_id=beta.branch_id, objective="B"), researcher, "b"
    )
    lease_a = service.acquire_task(a_task["id"], "ha", 60, operator, "lease-a")
    lease_b = service.acquire_task(b_task["id"], "hb", 60, operator, "lease-b")
    with worker_effects(alpha, a_task["id"], "ha", lease_a["fence"]):
        service.send_message(alpha.branch_id, beta.branch_id, "Question?", [], alpha, "q")
    with worker_effects(beta, b_task["id"], "hb", lease_b["fence"]):
        reply = service.send_message(beta.branch_id, alpha.branch_id, "Answer", [], beta, "r")
    with worker_effects(alpha, a_task["id"], "ha", lease_a["fence"]):
        wait = service.request_peer_wait(a_task["id"], beta.branch_id, 3600, alpha, "wait")
    # The JSON-payload join between message events and records must match on PostgreSQL.
    assert service.peer_wait_status(wait["intent"]["peer_wait"], alpha) == {
        "ready": True,
        "reason": "message_received",
        "message_id": reply["id"],
    }
