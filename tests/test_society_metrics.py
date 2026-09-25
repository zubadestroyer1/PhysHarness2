"""tools/society_metrics.py on synthetic exports: every PLAN §9 metric it reports."""

import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/society_metrics.py"
SPEC = importlib.util.spec_from_file_location("society_metrics_tool", TOOL)
metrics_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics_tool)

START = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
T0 = START.timestamp()
FORMAL = "theorem target : True := trivial"
A, B, C, REFEREE = "branch-a", "branch-b", "branch-c", "branch-referee"


def stamp(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def node(identifier, status, branch, node_type="lemma"):
    return {"id": identifier, "node_type": node_type, "status": status, "branch_id": branch}


def claim(node_id, branch, start, expires, released=False):
    return {
        "node_id": node_id,
        "branch_id": branch,
        "created_at": stamp(start),
        "expires_at": T0 + expires,
        "released": released,
    }


def review(verdict, scope="informal", cross_model=True, stale=False):
    return {"verdict": verdict, "scope": scope, "cross_model": cross_model, "stale": stale}


def event(kind, name=None):
    payload = {"name": name} if name else {"stagnation_state": {}}
    return json.dumps({"kind": kind, "session_id": "s", "payload": payload}).encode()


EVENTS = [
    event("tool_completed", "commons_post"),
    event("tool_completed", "commons_query"),
    event("tool_completed", "inbox"),
    event("tool_completed", "lean_check"),
    event("tool_completed", "lean_check"),
    event("tool_completed", "run_computation"),
    event("tool_completed", "load_skill"),
    event("tool_completed", "post_discussion"),  # a legacy name classifies too
    event("stagnation_warning"),
    event("generation_started"),
]


def society_export(*, accepted=True):
    """A small society run: five nodes, duplicated claims, reviews, fetches and a receipt."""
    problem = {
        "id": "problem",
        "semantic_review": "approved",
        "review_id": "review",
        "target_theorem": "target",
        "formal_statement": FORMAL,
        "target_digest": "t" * 64,
        "environment_digest": "e" * 64,
    }
    candidate = {
        "id": "candidate",
        "experiment_id": "exp",
        "artifact_kind": "lean_source",
        "sha256": "c" * 64,
    }
    receipt = {
        "id": "receipt",
        "status": "verified",
        "assurance": "independent_kernel",
        "experiment_id": "exp",
        "review_id": "review",
        "target_theorem": "target",
        "challenge_sha256": sha(FORMAL.encode()),
        "problem_revision_id": "problem",
        "target_digest": "t" * 64,
        "environment_digest": "e" * 64,
        "artifact_id": "candidate",
        "candidate_sha256": "c" * 64,
        "claim_id": "verified-claim",
        "created_at": stamp(1000),
    }
    runtime_events = [
        {
            "id": f"event-{index}",
            "experiment_id": "exp",
            "artifact_kind": "runtime_event",
            "sha256": sha(content),
        }
        for index, content in enumerate(EVENTS)
    ]
    return {
        "format": "physharness.reproduction.v1",
        "experiment": {
            "id": "exp",
            "sharing": "ideas",
            "society": {"tool_profile": "society"},
            "target_digest": "t" * 64,
            "started_at": stamp(0),
        },
        "problem": problem,
        "records": {
            "branch": [
                {"id": A, "lab": "lab-a"},
                {"id": B, "lab": "lab-a"},
                {"id": C, "lab": "lab-c"},
                {"id": REFEREE, "lab": None, "hat": "referee"},
            ],
            "artifact": [candidate, *runtime_events],
            "verification": [receipt] if accepted else [],
            "claim": [{"id": "verified-claim", "created_at": stamp(1800)}],
            "session": [{"id": "session"}],
            "discussion_post": [
                {"branch_id": B, "cites": ["lemma-a", "goal"]},  # cross-branch; goal is not
                {"branch_id": A, "cites": ["lemma-a"]},  # self-citation
                {"branch_id": C, "cites": ["lemma-b"]},  # cross-branch
                {"branch_id": A, "cites": []},
            ],
            "commons_node": [
                node("goal", "accepted" if accepted else "formally_stated", None, "goal"),
                node("lemma-a", "compiles_locally", A),
                node("lemma-b", "refereed", B),
                node("lemma-c", "informal", C, "conjecture"),
                node("lemma-d", "abandoned", C),
            ],
            "commons_claim": [
                # lemma-a: A and B overlap, so two concurrent claimants.
                claim("lemma-a", A, 0, 900),
                claim("lemma-a", B, 600, 1500, released=True),
                # lemma-b: C starts only after B's claim lapsed.
                claim("lemma-b", B, 0, 900),
                claim("lemma-b", C, 1000, 1900),
                # lemma-c: one branch only.
                claim("lemma-c", C, 0, 5000),
            ],
            "commons_review": [
                review("sound"),
                review("gaps"),
                review("wrong", cross_model=False),
                review("faithful", "fidelity"),
                review("unfaithful", "fidelity", stale=True),
            ],
            "literature_fetch": [
                {"status": "ok", "flagged": False},
                {"status": "withheld_contamination_risk", "flagged": True},
                {"status": "withheld_contamination_risk", "flagged": True},
            ],
        },
        "edges": [
            {"source": "goal", "target": "lemma-a", "relation": "depends_on"},
            {"source": "lemma-a", "target": "lemma-b", "relation": "depends_on"},
            {"source": "lemma-c", "target": "goal", "relation": "motivated_by"},
        ],
        "ledger": {"spent_cost_usd": "12.5", "tokens_spent": 900000},
    }


def write_export(directory, manifest, contents=EVENTS):
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps(manifest))
    for content in contents:
        (directory / sha(content)).write_bytes(content)
    return directory


def test_metrics_over_a_society_export_directory(tmp_path):
    directory = write_export(tmp_path / "export", society_export())
    output = io.StringIO()
    with redirect_stdout(output):
        assert metrics_tool.main([str(directory), "--as-of", str(T0 + 2000)]) == 0
    metrics = json.loads(output.getvalue())
    assert metrics["format"] == "physharness.society-metrics.v1"
    assert metrics["society"] is True
    # Outcomes.
    assert metrics["accepted_root"] is True
    assert metrics["accepted_root_receipt_id"] == "receipt"
    assert metrics["time_to_root_seconds"] == 1800.0  # the verified claim's commit
    assert metrics["accepted_nodes"] == 1
    assert metrics["cost_per_accepted_result_usd"] == "12.500000"
    # Blueprint.
    assert metrics["nodes_by_status"] == {
        "abandoned": 1,
        "accepted": 1,
        "compiles_locally": 1,
        "informal": 1,
        "refereed": 1,
    }
    assert metrics["nodes_by_type"] == {"conjecture": 1, "goal": 1, "lemma": 3}
    assert metrics["edges_by_relation"] == {"depends_on": 2, "motivated_by": 1}
    # Claims: two concurrent claimants on lemma-a only.
    assert metrics["claimed_nodes"] == 3 and metrics["duplicate_claimed_nodes"] == 1
    assert metrics["duplicate_claim_fraction"] == pytest.approx(1 / 3, abs=1e-6)
    # At +2000 s: A (900) and B on lemma-b (900) lapsed unreleased; C's (1900) too;
    # B's released claim is not stale; C on lemma-c (5000) is live.
    assert metrics["stale_claim_count"] == 3 and metrics["live_claim_count"] == 1
    # Knowledge.
    assert metrics["citations"] == 4 and metrics["cross_branch_citations"] == 2
    assert metrics["cross_branch_dependencies"] == 1  # lemma-a (A) depends on lemma-b (B)
    # Reviews.
    assert metrics["reviews_by_verdict"] == {
        "faithful": 1,
        "gaps": 1,
        "sound": 1,
        "unfaithful": 1,
        "wrong": 1,
    }
    assert metrics["reviews_by_scope"] == {"fidelity": 2, "informal": 3}
    assert metrics["cross_model_share"] == 0.8 and metrics["stale_reviews"] == 1
    assert metrics["referee_negative_share"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["fidelity_failure_share"] == 0.5
    assert metrics["branches"] == {"agents": 3, "referees": 1, "labs": 2}
    # Literature.
    assert metrics["literature_fetches"] == 3 and metrics["contamination_flags"] == 2
    assert metrics["literature_by_status"] == {"ok": 1, "withheld_contamination_risk": 2}
    # Tool mix from the runtime events beside the manifest.
    mix = metrics["tool_call_mix"]
    assert mix["available"] is True and mix["total"] == 8
    assert (mix["commons_society"], mix["math_lean_computation"], mix["other"]) == (4, 3, 1)
    assert mix["commons_society_share"] == 0.5
    assert mix["by_tool"]["lean_check"] == 2 and mix["stagnation_warnings"] == 1
    assert mix["runtime_events"] == mix["runtime_events_read"] == len(EVENTS)
    assert metrics["lean_checks_per_accepted_result"] == 2.0
    assert metrics["evidence"] == {"model_sessions": 1, "runtime_event_artifacts": len(EVENTS)}


def test_bare_manifest_reports_the_tool_mix_unavailable(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(society_export(accepted=False)))
    manifest, read_artifact = metrics_tool.load_export(path)
    metrics = metrics_tool.compute_metrics(manifest, read_artifact, as_of=T0)
    assert metrics["tool_call_mix"] == {"available": False}
    assert metrics["lean_checks_per_accepted_result"] is None
    assert metrics["accepted_root"] is False and metrics["time_to_root_seconds"] is None
    assert metrics["cost_per_accepted_result_usd"] is None
    assert metrics["stale_claim_count"] == 0 and metrics["live_claim_count"] == 4


def test_tampered_runtime_event_bytes_are_rejected(tmp_path):
    directory = write_export(tmp_path / "export", society_export())
    (directory / sha(EVENTS[0])).write_bytes(b"forged")
    manifest, read_artifact = metrics_tool.load_export(directory)
    with pytest.raises(ValueError, match="content hash"):
        metrics_tool.compute_metrics(manifest, read_artifact, as_of=T0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_digest", "x" * 64),
        ("assurance", "local_lean"),
        ("candidate_sha256", "d" * 64),
        ("review_id", "another-review"),
    ],
)
def test_legacy_arm_root_needs_an_exact_independent_receipt(field, value):
    """A legacy export has no goal node; only a receipt bound to the target counts."""
    manifest = society_export()
    del manifest["experiment"]["society"], manifest["edges"]
    for kind in ("commons_node", "commons_claim", "commons_review", "literature_fetch"):
        del manifest["records"][kind]
    metrics = metrics_tool.compute_metrics(manifest, as_of=T0)
    assert metrics["society"] is False
    assert metrics["accepted_root"] is True and metrics["accepted_nodes"] == 0
    assert metrics["cost_per_accepted_result_usd"] == "12.500000"
    assert metrics["nodes_by_status"] == {} and metrics["duplicate_claim_fraction"] is None
    assert metrics["cross_model_share"] is None and metrics["literature_fetches"] == 0
    manifest["records"]["verification"][0][field] = value
    assert metrics_tool.compute_metrics(manifest, as_of=T0)["accepted_root"] is False
