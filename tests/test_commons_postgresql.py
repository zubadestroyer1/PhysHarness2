"""Commons on PostgreSQL: an opt-in smoke of the society's JSON queries, locks and export.

The smoke body runs on SQLite in the unit suite and, when PHYSHARNESS_TEST_DATABASE_URL
names a dedicated PostgreSQL endpoint, on PostgreSQL in a throwaway schema. CI's postgres
job selects it with ``-k postgresql``.
"""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from commons_helpers import society_lab
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql

from physharness.artifacts import LocalArtifactStore
from physharness.commons import CommonsMixin
from physharness.commons_discourse import CommonsDiscourseMixin
from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.commons_review import CommonsReviewMixin
from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.service import HarnessService
from physharness.storage import Database
from physharness.workforce_models import RecruitResearcherRequest


def _lab(db, tmp_path):
    db.create_schema()
    service = HarnessService(db, LocalArtifactStore(tmp_path / "artifacts"))
    researcher = Principal(id="researcher", project_id="lab", role="researcher")
    reviewer = Principal(id="reviewer", project_id="lab", role="reviewer")
    return service, researcher, reviewer


@pytest.fixture(params=["sqlite", "postgresql"])
def backend_lab(request, tmp_path):
    if request.param == "sqlite":
        yield _lab(Database(f"sqlite:///{tmp_path / 'records.db'}"), tmp_path)
        return
    url = os.environ.get("PHYSHARNESS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No dedicated PostgreSQL endpoint for the commons smoke")
    schema = "commons_" + uuid4().hex
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
        yield _lab(db, tmp_path)
    finally:
        db.engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def rejected(call):
    with pytest.raises(HarnessError) as caught:
        call()
    return caught.value.code


def test_commons_smoke(backend_lab):
    service, author, exp, branches, (alpha, beta) = society_lab(backend_lab, lab_size_max=1)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    lemma = service.create_node(
        exp["id"],
        NodeCreate(
            node_type="lemma",
            title="Trace lemma",
            statement="The trace is additive.",
            edges=[{"relation": "motivated_by", "target_id": goal["id"]}],
        ),
        alpha,
        "lemma",
    )
    helper = service.create_node(
        exp["id"],
        NodeCreate(node_type="lemma", title="Helper", statement="A helper holds."),
        beta,
        "helper",
    )
    # Links: a dependency, then the cycle check over the experiment's dependency edges.
    linked = service.link_nodes(exp["id"], lemma["id"], "depends_on", helper["id"], alpha, "link")
    assert linked["created"] is True
    assert (
        rejected(
            lambda: service.link_nodes(
                exp["id"], helper["id"], "depends_on", lemma["id"], beta, "cycle"
            )
        )
        == "DEPENDENCY_CYCLE"
    )
    # Claims compare JSON numbers; the frontier counts live claims and edges.
    service.claim_node(lemma["id"], "claim", beta, "claim")
    claimants = service.read_node(lemma["id"], alpha)["claimants"]
    assert [claim["branch_id"] for claim in claimants] == [beta.branch_id]
    frontier = service.query_nodes(exp["id"], alpha, frontier=True)["items"]
    assert lemma["id"] in {item["id"] for item in frontier}
    # An objection to the author's node is delivered to the author first, as urgent.
    objection = service.post_on_node(
        lemma["id"], NodePostCreate(kind="objection", abstract="Step 2 fails."), beta, "post"
    )
    batch = service.discussion_updates(exp["id"], alpha)
    assert batch["items"][0]["id"] == objection["id"] and batch["items"][0]["urgent"] is True
    service.acknowledge_discussion_updates(exp["id"], batch["delivery_id"], alpha, "ack")
    # Review requests deduplicate on an open, unsubmitted referee task (NOT EXISTS).
    first = service.request_review(lemma["id"], "informal", beta, "review-1")
    again = service.request_review(lemma["id"], "informal", alpha, "review-2")
    assert again["deduplicated"] is True and again["review_task_id"] == first["review_task_id"]
    referee = Principal(
        id="referee",
        role="agent",
        project_id=author.project_id,
        experiment_id=exp["id"],
        branch_id=first["branch_id"],
    )
    service.submit_review(
        first["review_task_id"], "gaps", "Step 2 is missing.", ["Step 2."], referee, "gaps"
    )
    fresh = service.request_review(lemma["id"], "informal", beta, "review-3")
    assert fresh["deduplicated"] is False and fresh["review_task_id"] != first["review_task_id"]
    # The lab cap holds under the lab lock: alpha's one-member lab is full.
    recruit = RecruitResearcherRequest(
        parent_branch_id=branches[0]["id"], title="Helper", objective="Help."
    )
    assert rejected(lambda: service.recruit_researcher(exp["id"], recruit, author, "r")) == (
        "LAB_FULL"
    )
    # The export carries the commons records and the edges between visible nodes.
    manifest = service.export_experiment(exp["id"], author)
    records = manifest["records"]
    assert {node["id"] for node in records["commons_node"]} == {
        goal["id"],
        lemma["id"],
        helper["id"],
    }
    assert [claim["node_id"] for claim in records["commons_claim"]] == [lemma["id"]]
    assert [review["verdict"] for review in records["commons_review"]] == ["gaps"]
    assert sorted(
        (edge["relation"], edge["source"], edge["target"]) for edge in manifest["edges"]
    ) == [
        ("depends_on", lemma["id"], helper["id"]),
        ("motivated_by", lemma["id"], goal["id"]),
    ]


class _Capture:
    """A session stand-in that records the statements the commons queries build."""

    def __init__(self):
        self.statements = []

    def scalar(self, statement):
        self.statements.append(statement)

    def scalars(self, statement):
        self.statements.append(statement)
        return []

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [])


def test_commons_queries_compile_for_postgresql():
    """Runs without a server: the JSON paths and NOT EXISTS compile on PostgreSQL."""
    session, experiment = _Capture(), SimpleNamespace(project_id="p", id="e")
    assignment = {
        "node_id": "n",
        "scope": "fidelity",
        "statement_sha256": "s",
        "lean_statement_sha256": "l",
    }
    CommonsReviewMixin._open_review_task(session, experiment, assignment)
    list(CommonsDiscourseMixin._live_claim_rows(session, "p", "e", 1.0, node_id="n"))
    CommonsMixin._experiment_dependencies(session, experiment)
    CommonsMixin._commons_edges(session, "p", "e", {"n"})
    compiled = [
        str(statement.compile(dialect=postgresql.dialect())) for statement in session.statements
    ]
    assert len(compiled) == 4
    assert "NOT (EXISTS" in compiled[0]
