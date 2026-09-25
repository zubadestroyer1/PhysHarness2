"""Opt-in PostgreSQL races for task admission and durable reader delivery."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event

from physharness.artifacts import LocalArtifactStore
from physharness.domain import CampaignCreate, ExperimentCreate, Principal, ProblemCreate
from physharness.service import HarnessService
from physharness.storage import Database
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
