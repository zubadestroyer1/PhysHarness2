"""Referee and fidelity reviews, Lean-statement evidence and local-compile evidence."""

import pytest
from commons_helpers import set_status, society_lab
from test_commons_discourse import Clock, drain
from test_research_services import accepted_fixture
from test_sharing import approaches, artifact

from physharness import commons_discourse
from physharness.commons import PLATFORM
from physharness.commons_models import NodeCreate
from physharness.commons_review import REFEREE_OBJECTIVE, REVIEW_VERDICTS, statement_digest
from physharness.domain import Principal, TaskCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow
from physharness.verification import VerificationOutcome
from physharness.worker_authority import worker_effects
from physharness.workforce_models import ConfigureWorkforceRequest, RecruitResearcherRequest

ELABORATED = {"ok": True, "backend": "lean-repl", "diagnostics_sha256": "e" * 64}
COMPILED = {
    "complete": True,
    "backend": "lake-env-lean",
    "statement_found": True,
    "axioms": {"trace_add": ["propext", "Classical.choice", "Quot.sound"]},
}
CLOSING_LINE = "Call submit_review exactly once. Your verdict is recorded; it is not a proof."
# Recorded from the pre-change code (legacy recruitment and verification commit).
LEGACY_TASK_KEYS = [
    "branch_id",
    "objective",
    "dependency_ids",
    "detached",
    "experiment_id",
    "status",
    "evidence_ids",
    "created_by",
    "reply_to_parent_task_id",
    "delegated_from_task_id",
    "discussion_refs",
    "synthesis",
    "synthesis_scope",
    "origin_actor_id",
    "id",
    "kind",
    "project_id",
    "revision",
    "created_at",
]
LEGACY_RECEIPT_KEYS = [
    "experiment_id",
    "problem_revision_id",
    "target_digest",
    "challenge_sha256",
    "review_id",
    "target_theorem",
    "artifact_id",
    "candidate_sha256",
    "environment_digest",
    "publication",
    "status",
    "assurance",
    "submitted_by",
    "checker_versions",
    "axioms",
    "origin_actor_id",
    "branch_id",
    "id",
    "kind",
    "project_id",
    "revision",
    "created_at",
    "code",
    "message",
    "remediation",
    "diagnostics",
    "claim_id",
]
LEGACY_CLAIM_KEYS = [
    "experiment_id",
    "problem_revision_id",
    "target_digest",
    "challenge_sha256",
    "review_id",
    "target_theorem",
    "statement",
    "assumptions",
    "evidence",
    "proof_status",
    "semantic_review",
    "novelty_status",
    "verification_id",
    "artifact_id",
    "assurance",
    "origin_actor_id",
    "branch_id",
    "id",
    "kind",
    "project_id",
    "revision",
    "created_at",
]


@pytest.fixture
def clock(monkeypatch):
    fixed = Clock()
    monkeypatch.setattr(commons_discourse, "_now", fixed)
    return fixed


def lemma(title="Trace lemma", statement="The trace is additive.", **extra):
    return NodeCreate(node_type="lemma", title=title, statement=statement, **extra)


def rejected(call):
    with pytest.raises(HarnessError) as err:
        call()
    return err.value


def events(service, actor, kind):
    return [e for e in service.events(actor, limit=1000) if e["kind"] == kind]


def referee(requested, experiment):
    """The agent principal a worker runs as on the platform-assigned referee branch."""
    return Principal(
        id=f"referee-{requested['branch_id'][:8]}",
        role="agent",
        project_id="lab",
        experiment_id=experiment["id"],
        branch_id=requested["branch_id"],
    )


def submit(service, requested, experiment, verdict, summary="Checked each step.", **extra):
    return service.submit_review(
        requested["review_task_id"],
        verdict,
        summary,
        list(extra.pop("objections", [])),
        extra.pop("actor", None) or referee(requested, experiment),
        extra.pop("key", f"submit-{requested['review_task_id']}"),
    )


def formalize(service, node, actor, statement="∀ n : Nat, n + 0 = n", ok=True, key=None):
    return service.set_lean_statement(
        node["id"],
        "import Mathlib",
        "trace_add",
        statement,
        {**ELABORATED, "ok": ok},
        actor,
        key or f"lean-{statement}-{ok}",
    )


def finish(service, task_id, status="completed"):
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, task_id), {"status": status})


def refereed_quorum(service, experiment, node, requester, count=1):
    for index in range(count):
        requested = service.request_review(node["id"], "informal", requester, f"inf-{index}")
        submit(service, requested, experiment, "sound")


# Requests ------------------------------------------------------------------


def test_request_informal_review_creates_detached_referee_task_cross_model(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab, models=2, lab_size_max=1)
    node = service.create_node(
        exp["id"], lemma(assumptions=["Finite dimension", "Real scalars"]), beta, "node"
    )
    requested = service.request_review(node["id"], "informal", alpha, "review")
    # The author (beta) runs model 1, so the referee runs model (1 + 1) % 2 = 0.
    assert requested == {
        "review_task_id": requested["review_task_id"],
        "branch_id": requested["branch_id"],
        "model_index": 0,
        "cross_model": True,
        "deduplicated": False,
    }
    task = service.get_record("task", requested["review_task_id"], author)
    branch = service.get_record("branch", requested["branch_id"], author)
    assert task["branch_id"] == branch["id"]
    assert task["detached"] is True and task["reply_to_parent_task_id"] is None
    assert task["status"] == "queued" and task["hat"] == "referee"
    assert task["review_assignment"] == {
        "node_id": node["id"],
        "scope": "informal",
        "statement_sha256": statement_digest(node),
        "lean_statement_sha256": None,
    }
    assert branch["relation"] == "helper" and branch["parent_id"] == alpha.branch_id
    assert branch["title"] == "Referee informal: Trace lemma"
    assert branch["model_index"] == 0 and branch["model_configuration"] == exp["models"][0]
    # Independent reviewers join no lab, so the full author lab does not block them.
    assert branch["lab"] is None
    objective = task["objective"]
    assert objective == branch["objective"]
    for text in ("Trace lemma", "The trace is additive.", "Finite dimension", "Real scalars"):
        assert text in objective
    assert "sound, gaps or wrong" in objective and objective.endswith(CLOSING_LINE)
    assert set(REFEREE_OBJECTIVE) == {"informal", "fidelity"}
    assert {e["aggregate_id"] for e in events(service, author, "task.queued")} == {task["id"]}


def test_single_model_review_not_cross_model(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    requested = service.request_review(node["id"], "informal", beta, "review")
    assert requested["cross_model"] is False and requested["model_index"] is None
    branch = service.get_record("branch", requested["branch_id"], author)
    assert branch["model_index"] is None
    assert branch["model_configuration"] == exp["models"][0]


def test_referee_model_follows_an_inherited_author_model(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab, models=3)
    # A recruit without a model index inherits its parent's model (index 1 here).
    child = service.recruit_researcher(
        exp["id"],
        RecruitResearcherRequest(
            parent_branch_id=beta.branch_id, title="child", objective="child", detached=True
        ),
        beta,
        "recruit",
    )["branch"]
    assert child["model_index"] is None and child["model_configuration"] == exp["models"][1]
    worker = Principal(
        id="child",
        role="agent",
        project_id="lab",
        experiment_id=exp["id"],
        branch_id=child["id"],
    )
    node = service.create_node(exp["id"], lemma(), worker, "node")
    requested = service.request_review(node["id"], "informal", alpha, "review")
    assert requested["model_index"] == 2 and requested["cross_model"] is True


def test_request_review_deduplicates_open_request(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    first = service.request_review(node["id"], "informal", alpha, "first")
    again = service.request_review(node["id"], "informal", beta, "again")
    assert again == {**first, "deduplicated": True}
    assert service.request_review(node["id"], "informal", alpha, "first") == first
    referee_tasks = [
        t for t in service.list_records("task", author, exp["id"]) if t.get("hat") == "referee"
    ]
    assert [t["id"] for t in referee_tasks] == [first["review_task_id"]]
    # A finished task is not an open request.
    finish(service, first["review_task_id"])
    fresh = service.request_review(node["id"], "informal", beta, "fresh")
    assert fresh["deduplicated"] is False
    assert fresh["review_task_id"] != first["review_task_id"]
    # A submitted review is finished even while its task still runs.
    submit(service, fresh, exp, "gaps", objections=["Step 2 is unjustified."])
    after = service.request_review(node["id"], "informal", beta, "after")
    assert after["deduplicated"] is False
    assert after["review_task_id"] not in {first["review_task_id"], fresh["review_task_id"]}
    # Fidelity requests are keyed by the Lean statement digest.
    formalize(service, node, alpha)
    fidelity = service.request_review(node["id"], "fidelity", beta, "fidelity")
    assert fidelity["deduplicated"] is False
    assert service.request_review(node["id"], "fidelity", alpha, "fid-2")["deduplicated"] is True
    formalize(service, node, alpha, statement="∀ n : Nat, 0 + n = n")
    changed = service.request_review(node["id"], "fidelity", alpha, "fid-3")
    assert changed["deduplicated"] is False
    assert changed["review_task_id"] != fidelity["review_task_id"]


def test_request_review_is_admitted_like_recruitment(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    operator = Principal(id="operator", project_id="lab", role="operator")
    service.configure_workforce(
        exp["id"],
        ConfigureWorkforceRequest(max_total_tasks=1, max_pending_tasks=1),
        operator,
        "configure",
    )
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    first = service.request_review(node["id"], "informal", beta, "first")
    # Deduplication returns the open request without admitting another task.
    assert service.request_review(node["id"], "informal", alpha, "dup")["deduplicated"] is True
    submit(service, first, exp, "gaps")
    error = rejected(lambda: service.request_review(node["id"], "informal", alpha, "second"))
    assert error.code == "TASK_TOTAL_CAP"


def test_fidelity_requires_elaborated_lean_statement(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    error = rejected(lambda: service.request_review(node["id"], "fidelity", beta, "none"))
    assert (error.code, error.status) == ("LEAN_STATEMENT_REQUIRED", 409)
    unelaborated = formalize(service, node, alpha, ok=False)
    assert unelaborated["lean_elaborated"] is False
    error = rejected(lambda: service.request_review(node["id"], "fidelity", beta, "bad"))
    assert error.code == "LEAN_STATEMENT_REQUIRED"
    formalize(service, node, alpha)
    requested = service.request_review(node["id"], "fidelity", beta, "ok")
    task = service.get_record("task", requested["review_task_id"], author)
    stored = service.get_record("commons_node", node["id"], alpha)
    assert task["review_assignment"]["lean_statement_sha256"] == stored["lean_statement_sha256"]
    for text in ("import Mathlib", "trace_add", "∀ n : Nat, n + 0 = n", "faithful or unfaithful"):
        assert text in task["objective"]
    assert "vacu" in task["objective"] and task["objective"].endswith(CLOSING_LINE)
    # At or above formally_stated the fidelity review has nothing left to decide.
    set_status(service, node["id"], "formally_stated")
    error = rejected(lambda: service.request_review(node["id"], "fidelity", beta, "late"))
    assert error.code == "REVIEW_PRECONDITION"
    # Informal review needs an informal node; unknown scopes are rejected.
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    set_status(service, other["id"], "refereed")
    error = rejected(lambda: service.request_review(other["id"], "informal", beta, "inf"))
    assert error.code == "REVIEW_PRECONDITION"
    error = rejected(lambda: service.request_review(other["id"], "novelty", beta, "scope"))
    assert (error.code, error.status) == ("INVALID_REVIEW_SCOPE", 422)


def test_referee_objective_stays_within_the_task_bound(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(
        exp["id"],
        lemma(statement="S" * 8000, assumptions=["A" * 512] * 32),
        alpha,
        "node",
    )
    service.set_lean_statement(
        node["id"], "H" * 2000, "big", "L" * 20000, ELABORATED, alpha, "lean"
    )
    for scope in ("informal", "fidelity"):
        requested = service.request_review(node["id"], scope, beta, scope)
        objective = service.get_record("task", requested["review_task_id"], author)["objective"]
        assert len(objective) <= 20000 and "S" * 8000 in objective
        assert f"read node {node['id']} for the exact text" in objective
        assert objective.endswith(CLOSING_LINE)


# Submissions ---------------------------------------------------------------


def test_submit_by_non_referee_rejected(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    requested = service.request_review(node["id"], "informal", beta, "review")
    ordinary = service.create_task(
        TaskCreate(branch_id=branches[1]["id"], objective="Prove it"), author, "ordinary"
    )
    impostor = Principal(
        id="impostor",
        role="agent",
        project_id="lab",
        experiment_id=exp["id"],
        branch_id=beta.branch_id,
    )
    operator = Principal(id="operator", project_id="lab", role="operator")
    for actor, task_id in (
        (alpha, requested["review_task_id"]),  # the author
        (beta, requested["review_task_id"]),  # the requester
        (impostor, requested["review_task_id"]),
        (author, requested["review_task_id"]),  # a researcher, not an agent
        (operator, requested["review_task_id"]),
        (beta, ordinary["id"]),  # its own task, but no review assignment
        (referee(requested, exp), "missing-task"),
    ):
        error = rejected(
            lambda actor=actor, task_id=task_id: service.submit_review(
                task_id, "sound", "Fine.", [], actor, f"forge-{actor.id}-{task_id}"
            )
        )
        assert (error.code, error.status) == ("REVIEW_NOT_ASSIGNED", 403)
    # A bound worker may only submit for the task it is bound to.
    agent = referee(requested, exp)
    other = service.create_task(
        TaskCreate(branch_id=requested["branch_id"], objective="Other work"), author, "other"
    )
    lease = service.acquire_task(other["id"], "holder", 60, operator, "lease-other")
    with worker_effects(agent, other["id"], "holder", lease["fence"]):
        error = rejected(lambda: submit(service, requested, exp, "sound", actor=agent))
    assert (error.code, error.status) == ("REVIEW_NOT_ASSIGNED", 403)
    finish(service, other["id"])
    lease = service.acquire_task(requested["review_task_id"], "holder", 60, operator, "lease")
    with worker_effects(agent, requested["review_task_id"], "holder", lease["fence"]):
        review = submit(service, requested, exp, "sound", actor=agent)
    assert review["referee_branch_id"] == requested["branch_id"]
    assert service.get_record("commons_node", node["id"], alpha)["status"] == "refereed"


def test_invalid_verdict_rejected(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    requested = service.request_review(node["id"], "informal", beta, "review")
    assert REVIEW_VERDICTS == {
        "informal": ("sound", "gaps", "wrong"),
        "fidelity": ("faithful", "unfaithful"),
    }
    for verdict in ("faithful", "SOUND", "", None):
        error = rejected(lambda verdict=verdict: submit(service, requested, exp, verdict))
        assert (error.code, error.status) == ("INVALID_VERDICT", 422)
    for summary, objections in (
        ("", []),
        ("   ", []),
        ("x" * 4001, []),
        (None, []),
        ("Fine.", ["o"] * 11),
        ("Fine.", ["o" * 1001]),
        ("Fine.", [""]),
        ("Fine.", "not a list"),
    ):
        error = rejected(
            lambda summary=summary, objections=objections: service.submit_review(
                requested["review_task_id"],
                "gaps",
                summary,
                objections,
                referee(requested, exp),
                "invalid",
            )
        )
        assert (error.code, error.status) == ("INVALID_REVIEW", 422)
    # Nothing was recorded, so a valid submission still succeeds.
    assert submit(service, requested, exp, "gaps", summary="x" * 4000)["verdict"] == "gaps"


def test_sound_review_referees_node_and_posts_status(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab, models=2)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    drain(service, exp["id"], alpha)
    requested = service.request_review(node["id"], "informal", beta, "review")
    review = submit(service, requested, exp, "sound", summary="Every step checks.")
    assert review["node_status"] == "refereed"
    stored = service.get_record("commons_review", review["id"], beta)
    assert {k: stored[k] for k in stored if k in review} == {
        k: review[k] for k in review if k != "node_status"
    }
    assert {
        k: stored[k]
        for k in (
            "experiment_id",
            "node_id",
            "scope",
            "verdict",
            "summary",
            "objections",
            "task_id",
            "referee_branch_id",
            "model_index",
            "cross_model",
            "statement_sha256",
            "lean_statement_sha256",
            "stale",
        )
    } == {
        "experiment_id": exp["id"],
        "node_id": node["id"],
        "scope": "informal",
        "verdict": "sound",
        "summary": "Every step checks.",
        "objections": [],
        "task_id": requested["review_task_id"],
        "referee_branch_id": requested["branch_id"],
        "model_index": 1,
        "cross_model": True,
        "statement_sha256": statement_digest(node),
        "lean_statement_sha256": None,
        "stale": False,
    }
    assert stored["branch_id"] == requested["branch_id"]
    updated = service.get_record("commons_node", node["id"], alpha)
    assert updated["status"] == "refereed"
    assert updated["status_evidence"]["review_ids"] == [review["id"]]
    assert updated["status_evidence"]["counts"] == {"sound": 1, "gaps": 0, "wrong": 0}
    (item,) = drain(service, exp["id"], alpha)["items"]
    assert item["attributed_to"] == PLATFORM and item["post_kind"] == "update"
    assert item["excerpt"].startswith("Status informal → refereed")
    (submitted,) = events(service, author, "commons.review_submitted")
    assert submitted["aggregate_id"] == review["id"]
    assert submitted["payload"] == {
        "experiment_id": exp["id"],
        "node_id": node["id"],
        "review_id": review["id"],
        "task_id": requested["review_task_id"],
        "scope": "informal",
        "verdict": "sound",
        "stale": False,
    }


def test_quorum_two_requires_two_sound_reviews(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab, referee_quorum=2)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    first = service.request_review(node["id"], "informal", beta, "first")
    assert submit(service, first, exp, "sound")["node_status"] == "informal"
    second = service.request_review(node["id"], "informal", beta, "second")
    assert second["deduplicated"] is False
    assert submit(service, second, exp, "sound")["node_status"] == "refereed"
    evidence = service.get_record("commons_node", node["id"], alpha)["status_evidence"]
    assert len(evidence["review_ids"]) == 2
    # A standing "wrong" verdict blocks the quorum.
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    for index, verdict in enumerate(("wrong", "sound", "sound")):
        requested = service.request_review(other["id"], "informal", beta, f"o-{index}")
        assert submit(service, requested, exp, verdict)["node_status"] == "informal"


def rewrite_statement(service, node_id, statement):
    """Stand-in for a revised informal statement (no API edits statements yet)."""
    with service.db.transaction() as session:
        service._replace(session, session.get(RecordRow, node_id), {"statement": statement})


def verdicts(service, experiment, node, requester, scope, *answers):
    """Request and submit one review per answer; return the node status after each."""
    statuses = []
    for answer in answers:
        requested = service.request_review(
            node["id"], scope, requester, f"{scope}-{node['id']}-{len(statuses)}-{answer}"
        )
        statuses.append(submit(service, requested, experiment, answer)["node_status"])
    return statuses


def test_sound_reviews_must_outnumber_negative_reviews(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)  # referee_quorum = 1
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    assert verdicts(service, exp, node, beta, "informal", "gaps", "sound") == [
        "informal",
        "informal",
    ]
    # A second sound verdict outweighs the gap report.
    assert verdicts(service, exp, node, beta, "informal", "sound") == ["refereed"]
    evidence = service.get_record("commons_node", node["id"], alpha)["status_evidence"]
    assert evidence["counts"] == {"sound": 2, "gaps": 1, "wrong": 0}
    assert len(evidence["review_ids"]) == 2
    # Fidelity follows the same rule: faithful verdicts must outnumber unfaithful ones.
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    formalize(service, other, alpha, key="lean-other")
    assert verdicts(service, exp, other, beta, "fidelity", "unfaithful", "faithful") == [
        "informal",
        "informal",
    ]
    assert verdicts(service, exp, other, beta, "fidelity", "faithful") == ["formally_stated"]
    evidence = service.get_record("commons_node", other["id"], alpha)["status_evidence"]
    assert evidence["counts"] == {"faithful": 2, "unfaithful": 1}


def test_statement_change_resets_review_counts(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    assert verdicts(service, exp, node, beta, "informal", "wrong") == ["informal"]
    rewrite_statement(service, node["id"], "The trace is additive on finite sums.")
    # The standing "wrong" judged the old statement, so it no longer counts.
    assert verdicts(service, exp, node, beta, "informal", "sound") == ["refereed"]
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    formalize(service, other, alpha, key="lean-other")
    assert verdicts(service, exp, other, beta, "fidelity", "unfaithful") == ["informal"]
    formalize(service, other, alpha, statement="∀ n : Nat, 0 + n = n", key="lean-other-2")
    assert verdicts(service, exp, other, beta, "fidelity", "faithful") == ["formally_stated"]


def test_negative_review_posts_objection_keeps_status(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    drain(service, exp["id"], alpha)
    requested = service.request_review(node["id"], "informal", beta, "review")
    agent = referee(requested, exp)
    review = submit(
        service,
        requested,
        exp,
        "gaps",
        summary="The additivity step assumes linearity.",
        objections=["Linearity of the trace is used without proof.", "Step 3 skips a case."],
    )
    assert review["node_status"] == "informal" and review["objection_post_id"]
    assert service.get_record("commons_node", node["id"], alpha)["status"] == "informal"
    (item,) = drain(service, exp["id"], alpha)["items"]
    assert item["id"] == review["objection_post_id"]
    assert item["post_kind"] == "objection" and item["urgent"] is True
    assert item["attributed_to"] == agent.id and item["branch_id"] == agent.branch_id
    assert item["excerpt"] == "Referee (informal): gaps: The additivity step assumes linearity."
    post = service.read_discussion_post(item["id"], alpha)
    assert post["topic_id"] == node["topic_id"] and post["node_id"] == node["id"]
    assert "1. Linearity of the trace is used without proof." in post["content"]
    assert "2. Step 3 skips a case." in post["content"]
    assert review["id"] in post["content"]
    # The abstract is clipped to the post bound.
    again = service.request_review(node["id"], "informal", beta, "again")
    long = submit(service, again, exp, "wrong", summary="w" * 4000)
    post = service.read_discussion_post(long["objection_post_id"], alpha)
    assert len(post["abstract"]) == 600 and post["abstract"].startswith("Referee (informal): wrong")


def test_stale_review_does_not_transition(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    formalize(service, node, alpha)
    requested = service.request_review(node["id"], "fidelity", beta, "review")
    formalize(service, node, alpha, statement="∀ n : Nat, 0 + n = n")
    review = submit(service, requested, exp, "faithful")
    assert review["stale"] is True and review["node_status"] == "informal"
    assert service.get_record("commons_node", node["id"], alpha)["status"] == "informal"
    # A stale negative review still reaches the thread, marked as stale.
    again = service.request_review(node["id"], "fidelity", beta, "again")
    formalize(service, node, alpha, statement="∀ n : Nat, n * 1 = n")
    negative = submit(service, again, exp, "unfaithful", objections=["Wrong operator."])
    assert negative["stale"] is True and negative["node_status"] == "informal"
    post = service.read_discussion_post(negative["objection_post_id"], alpha)
    assert "Stale" in post["content"]


def test_faithful_review_formally_states(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    lean = formalize(service, node, alpha)
    requested = service.request_review(node["id"], "fidelity", beta, "review")
    review = submit(service, requested, exp, "faithful")
    assert review["stale"] is False and review["node_status"] == "formally_stated"
    assert review["lean_statement_sha256"] == lean["lean_statement_sha256"]
    stored = service.get_record("commons_node", node["id"], alpha)
    assert stored["status"] == "formally_stated"
    assert stored["status_evidence"] == {
        "review_ids": [review["id"]],
        "counts": {"faithful": 1, "unfaithful": 0},
        "lean_statement_sha256": lean["lean_statement_sha256"],
    }
    # A faithful verdict needs a statement that still elaborates.
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    formalize(service, other, alpha, key="other-ok")
    pending = service.request_review(other["id"], "fidelity", beta, "pending")
    formalize(service, other, alpha, ok=False, key="other-bad")
    unelaborated = submit(service, pending, exp, "faithful")
    assert unelaborated["stale"] is False and unelaborated["node_status"] == "informal"
    # Unfaithful objects on the thread and moves nothing.
    third = service.create_node(exp["id"], lemma("Third"), alpha, "third")
    formalize(service, third, alpha, key="lean-third")
    requested = service.request_review(third["id"], "fidelity", beta, "third-review")
    review = submit(service, requested, exp, "unfaithful", summary="Vacuous: n < 0 on Nat.")
    assert review["node_status"] == "informal"
    post = service.read_discussion_post(review["objection_post_id"], alpha)
    assert post["abstract"] == "Referee (fidelity): unfaithful: Vacuous: n < 0 on Nat."


def test_review_on_closed_node_is_recorded_without_effects(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    requested = service.request_review(node["id"], "informal", beta, "review")
    again = service.request_review(node["id"], "informal", beta, "again")
    assert again["deduplicated"] is True
    service.abandon_node(node["id"], "Superseded", alpha, "abandon")
    review = submit(service, requested, exp, "wrong", objections=["Moot."])
    assert review["node_status"] == "abandoned" and review["objection_post_id"] is None


def test_second_submit_rejected(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    requested = service.request_review(node["id"], "informal", beta, "review")
    first = submit(service, requested, exp, "gaps")
    # The same command replays; a second review for the task is rejected.
    assert submit(service, requested, exp, "gaps") == first
    error = rejected(lambda: submit(service, requested, exp, "sound", key="second"))
    assert (error.code, error.status) == ("REVIEW_ALREADY_SUBMITTED", 409)
    assert service.get_record("commons_node", node["id"], alpha)["status"] == "informal"


# Lean statements -----------------------------------------------------------


def test_changing_lean_statement_demotes_formally_stated(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    refereed_quorum(service, exp, node, beta)
    lean = formalize(service, node, alpha)
    faithful = service.request_review(node["id"], "fidelity", beta, "fidelity")
    submit(service, faithful, exp, "faithful")
    assert service.get_record("commons_node", node["id"], alpha)["status"] == "formally_stated"
    changed = formalize(service, node, alpha, statement="∀ n : Nat, 0 + n = n")
    # The informal quorum still stands, so the node falls back to refereed.
    assert changed["status"] == "refereed"
    assert changed["status_reason"] == "Lean statement changed"
    assert changed["lean_statement"] == "∀ n : Nat, 0 + n = n"
    assert changed["lean_header"] == "import Mathlib" and changed["lean_name"] == "trace_add"
    assert changed["lean_elaborated"] is True
    assert changed["lean_statement_sha256"] != lean["lean_statement_sha256"]
    (event,) = events(service, author, "commons.lean_statement_set")[-1:]
    assert event["payload"]["lean_statement_sha256"] == changed["lean_statement_sha256"]
    assert event["payload"]["backend"] == "lean-repl"
    # Without an informal quorum a formally stated (or compiled) node falls to informal.
    other = service.create_node(exp["id"], lemma("Other"), alpha, "other")
    formalize(service, other, alpha, key="lean-other")
    set_status(service, other["id"], "formally_stated", "compiles_locally")
    demoted = formalize(service, other, alpha, statement="True", key="other-2")
    assert demoted["status"] == "informal"
    # Re-recording the same, still elaborating statement moves nothing.
    third = service.create_node(exp["id"], lemma("Third"), alpha, "third")
    formalize(service, third, alpha, key="lean-third")
    set_status(service, third["id"], "formally_stated")
    assert formalize(service, third, alpha, key="third-again")["status"] == "formally_stated"
    # A statement that no longer elaborates cannot stay formally stated.
    broken = formalize(service, third, alpha, ok=False, key="third-broken")
    assert broken["status"] == "informal" and broken["lean_elaborated"] is False


def test_set_lean_statement_authority_and_bounds(lab, clock):
    service, author, exp, _, (alpha, beta) = society_lab(lab, claim_ttl_seconds=120)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    before = service.get_record("commons_node", node["id"], alpha)["last_activity_at"]
    error = rejected(lambda: formalize(service, node, beta))
    assert (error.code, error.status) == ("NODE_AUTHORITY", 403)
    service.claim_node(node["id"], "claim", beta, "claim")
    clock.now += 60
    by_claimant = formalize(service, node, beta, key="by-claimant")
    assert by_claimant["lean_statement_sha256"]
    assert by_claimant["last_activity_at"] > before
    # Setting the statement is activity: it extends the claimant's claim.
    (claim,) = service.read_node(node["id"], alpha)["claimants"]
    assert claim["expires_at"] == clock.now + 120
    clock.now += 121
    error = rejected(lambda: formalize(service, node, beta, statement="True", key="expired"))
    assert error.code == "NODE_AUTHORITY"
    assert formalize(service, node, alpha, statement="True", key="author")["lean_statement"] == (
        "True"
    )
    for header, name, statement, elaboration in (
        (None, "bad name", "True", ELABORATED),
        (None, "ok", "", ELABORATED),
        (None, "ok", "   ", ELABORATED),
        (None, "ok", "L" * 20001, ELABORATED),
        ("H" * 2001, "ok", "True", ELABORATED),
        (None, "ok", "True", {"ok": "yes", "backend": "b", "diagnostics_sha256": "e" * 64}),
        (None, "ok", "True", {"ok": True, "backend": "b", "diagnostics_sha256": "short"}),
        (None, "ok", "True", {"ok": True, "backend": "b"}),
        (None, "ok", "True", {**ELABORATED, "extra": 1}),
    ):
        error = rejected(
            lambda h=header, n=name, s=statement, e=elaboration: service.set_lean_statement(
                node["id"], h, n, s, e, alpha, "invalid"
            )
        )
        assert (error.code, error.status) == ("INVALID_LEAN_STATEMENT", 422)
    goal = service.ensure_goal_node(exp["id"], author)
    service.claim_node(goal["id"], "claim", beta, "claim-goal")
    error = rejected(
        lambda: service.set_lean_statement(goal["id"], None, "g", "True", ELABORATED, beta, "g")
    )
    assert (error.code, error.status) == ("GOAL_NODE_RESERVED", 403)
    service.abandon_node(node["id"], "Superseded", alpha, "abandon")
    error = rejected(lambda: formalize(service, node, alpha, statement="False", key="closed"))
    assert error.code == "NODE_CLOSED"


# Local compiles ------------------------------------------------------------


def test_record_local_compile_requires_formal_statement_and_completion(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    lean = formalize(service, node, alpha)
    built = {**COMPILED, "lean_statement_sha256": lean["lean_statement_sha256"]}
    early = service.record_local_compile(node["id"], "c" * 64, built, beta, "early")
    assert early["recorded"] is False and "formally_stated" in early["reason"]
    set_status(service, node["id"], "formally_stated")
    for key, result in (
        ("incomplete", {**built, "complete": False}),
        ("missing", {**built, "statement_found": False}),
    ):
        outcome = service.record_local_compile(node["id"], "c" * 64, result, beta, key)
        assert outcome["recorded"] is False and outcome["reason"]
        assert service.get_record("commons_node", node["id"], alpha)["status"] == (
            "formally_stated"
        )
    for source, result in (
        ("short", built),
        ("c" * 64, {**built, "complete": "yes"}),
        ("c" * 64, {**built, "extra": 1}),
        ("c" * 64, {k: v for k, v in built.items() if k != "axioms"}),
        ("c" * 64, {**built, "axioms": {"x": "a" * 9000}}),
        ("c" * 64, COMPILED),  # no statement digest
        ("c" * 64, {**built, "lean_statement_sha256": "short"}),
    ):
        error = rejected(
            lambda s=source, r=result: service.record_local_compile(node["id"], s, r, beta, "bad")
        )
        assert (error.code, error.status) == ("INVALID_COMPILE_RESULT", 422)
    drain(service, exp["id"], alpha)
    compiled = service.record_local_compile(node["id"], "c" * 64, built, beta, "done")
    assert compiled["recorded"] is True and compiled["status"] == "compiles_locally"
    stored = service.get_record("commons_node", node["id"], alpha)
    assert stored["status"] == "compiles_locally"
    assert stored["status_evidence"] == {
        "source_sha256": "c" * 64,
        "backend": "lake-env-lean",
        "axioms": COMPILED["axioms"],
    }
    (item,) = drain(service, exp["id"], alpha)["items"]
    assert item["excerpt"].startswith("Status formally_stated → compiles_locally")
    # A second compile of a compiled node records nothing.
    again = service.record_local_compile(node["id"], "d" * 64, built, beta, "again")
    assert again["recorded"] is False
    # The goal has no node Lean statement, so no compile can bind to it.
    goal = service.ensure_goal_node(exp["id"], author)
    unbound = service.record_local_compile(goal["id"], "c" * 64, built, beta, "goal")
    assert unbound["recorded"] is False


def test_local_compile_after_statement_change_not_recorded(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "node")
    compiled_statement = formalize(service, node, alpha)["lean_statement_sha256"]
    set_status(service, node["id"], "formally_stated")
    # The platform compiled the old statement; meanwhile the author replaced it and the
    # new statement was formally stated again.
    current = formalize(service, node, alpha, statement="∀ n : Nat, 0 + n = n")
    assert current["status"] == "informal"
    set_status(service, node["id"], "formally_stated")
    stale = {**COMPILED, "lean_statement_sha256": compiled_statement}
    outcome = service.record_local_compile(node["id"], "c" * 64, stale, beta, "stale")
    assert outcome == {"recorded": False, "reason": "statement_changed"}
    assert service.get_record("commons_node", node["id"], alpha)["status"] == "formally_stated"
    fresh = {**COMPILED, "lean_statement_sha256": current["lean_statement_sha256"]}
    assert service.record_local_compile(node["id"], "c" * 64, fresh, beta, "fresh")["recorded"]


# Workforce -----------------------------------------------------------------


def test_new_branch_task_without_extra_unchanged(lab):
    service, author, exp, _, (alpha, _) = approaches(lab, "ideas")
    legacy = service.recruit_researcher(
        exp["id"],
        RecruitResearcherRequest(
            parent_branch_id=alpha.branch_id, title="t", objective="o", detached=True
        ),
        alpha,
        "recruit",
    )
    assert list(legacy["task"]) == LEGACY_TASK_KEYS
    assert list(service.get_record("task", legacy["task"]["id"], author)) == LEGACY_TASK_KEYS
    service, author, exp, _, (alpha, _) = society_lab(lab, prefix="society")
    society = service.recruit_researcher(
        exp["id"],
        RecruitResearcherRequest(
            parent_branch_id=alpha.branch_id, title="t", objective="o", detached=True
        ),
        alpha,
        "society-recruit",
    )
    assert list(society["task"]) == LEGACY_TASK_KEYS


# Goal acceptance -----------------------------------------------------------


class Checker:
    def __init__(self, assurance="independent_kernel"):
        self.assurance = assurance

    def verify(self, request):
        return VerificationOutcome(
            status="verified",
            assurance=self.assurance,
            code="test_fixture",
            message="Synthetic test evidence only",
            remediation="",
            target_digest=request.target_digest,
            challenge_sha256=request.challenge_sha256,
            environment_digest=request.environment_digest,
            candidate_sha256=request.candidate_sha256,
            checker_versions={
                k: "synthetic-not-a-kernel" for k in ("lean", "comparator", "nanoda")
            },
            axioms=[],
        )


def verify(service, agent, source, *, assurance="independent_kernel"):
    service.verifier = Checker(assurance)
    candidate = artifact(service, agent, source)
    receipt = service.verify_candidate(
        agent.experiment_id, candidate["id"], False, agent, f"verify-{source}"
    )
    operator = Principal(id="test-checker", project_id="lab", role="operator")
    return service.process_verification(receipt["id"], operator)


def test_goal_accepted_hook_on_verified_target_receipt(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.ensure_goal_node(exp["id"], author)
    service.claim_node(goal["id"], "claim", beta, "follow-goal")
    # A kernel-only receipt is not independent acceptance.
    kernel = verify(service, alpha, "kernel proof", assurance="kernel")
    assert kernel["status"] == "verified" and kernel["assurance"] == "kernel"
    assert service.get_record("commons_node", goal["id"], author)["status"] == "formally_stated"
    receipt = verify(service, alpha, "synthetic proof")
    assert receipt["status"] == "verified" and receipt["claim_id"]
    stored = service.get_record("commons_node", goal["id"], author)
    assert stored["status"] == "accepted"
    assert stored["status_reason"] == "independent kernel receipt"
    assert stored["status_evidence"] == {"receipt_id": receipt["id"]}
    (moved,) = events(service, author, "commons.node_status")
    assert moved["payload"]["to"] == "accepted" and moved["aggregate_id"] == goal["id"]
    # The platform status post reaches the goal thread's subscribers as urgent news.
    (item,) = drain(service, exp["id"], beta)["items"]
    assert item["excerpt"] == "Status formally_stated → accepted: independent kernel receipt"
    assert item["urgent"] is True and item["attributed_to"] == PLATFORM
    # A later receipt leaves the accepted goal alone.
    later = verify(service, alpha, "another proof")
    assert later["status"] == "verified"
    stored = service.get_record("commons_node", goal["id"], author)
    assert stored["status_evidence"] == {"receipt_id": receipt["id"]}
    assert len(events(service, author, "commons.node_status")) == 1
    assert service.read_node(goal["id"], alpha)["node"].get("status_derived") is None


def test_goal_accepted_hook_creates_missing_goal(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    receipt = verify(service, alpha, "synthetic proof")
    with service.db.sessions() as session:
        goal = service._goal_row(session, session.get(RecordRow, exp["id"]))
        assert goal.payload["status"] == "accepted"
        assert goal.payload["status_evidence"] == {"receipt_id": receipt["id"]}


def test_legacy_verification_commit_unchanged(lab, monkeypatch):
    service = lab[0]

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy experiments never reach the commons hook")

    monkeypatch.setattr(service, "_commons_goal_accepted", forbidden)
    service, author, exp, _, _, checked = accepted_fixture(lab, sharing="ideas")
    assert checked["status"] == "verified" and checked["assurance"] == "independent_kernel"
    assert list(checked) == LEGACY_RECEIPT_KEYS
    assert list(service.get_record("claim", checked["claim_id"], author)) == LEGACY_CLAIM_KEYS
    (verified,) = events(service, author, "verification.verified")
    same_operation = [
        e["kind"]
        for e in service.events(author, limit=1000)
        if e["operation_id"] == verified["operation_id"]
    ]
    assert same_operation == ["verification.verified"]
    assert service.list_records("commons_node", author, exp["id"]) == []
