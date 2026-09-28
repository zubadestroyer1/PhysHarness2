"""Deterministic research-society simulation: three agents and platform referees, no model.

Every step calls a society tool through ``ToolDispatcher.dispatch``, the path the Responses
runtime takes: schema validation, defaults, the worker's fenced effect binding, the handler's
caps and recoverable error envelopes all run. Peer updates arrive through the worker's
fenced delivery hooks. Each agent holds a real task lease, as the worker does. Lean is a
scripted fake ``LeanSession`` behind a fake workspace, and the literature broker uses a
fake transport, so there is no model, network, VM or Lean.
"""

import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path

from commons_helpers import society_lab
from test_literature import REFERENCE, REFERENCE_WORDS, FakeTransport, ok, page
from test_society_tools import FakeWorkspace, call, running

from physharness.commons import _lean_digest
from physharness.domain import BranchCreate, LiteraturePolicy
from physharness.knowledge.literature import LiteratureBroker
from physharness.orchestration.lean_session import LeanSession
from physharness.orchestration.research_network import discussion_delivery_hooks
from physharness.orchestration.society_tools import society_tools

TOOL = Path(__file__).resolve().parents[1] / "tools/society_metrics.py"
SPEC = importlib.util.spec_from_file_location("society_metrics", TOOL)
society_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(society_metrics)

HEADER = "import Mathlib"
LEMMA = {
    "lean_header": HEADER,
    "lean_name": "energy_nonincreasing",
    "lean_statement": "(E : ℝ → ℝ) (h : ∀ t, deriv E t ≤ 0) (hd : Differentiable ℝ E) : Antitone E",
}
PROOF = (
    f"{HEADER}\n\ntheorem {LEMMA['lean_name']} {LEMMA['lean_statement']} := by\n"
    "  exact antitone_of_deriv_nonpos hd h\n"
)
GOAL_STEPS = [
    ("E : ℝ → ℝ\n⊢ Antitone E", "(E : ℝ → ℝ) : Antitone E"),
    ("m k : ℝ\nhm : 0 < m\n⊢ 0 < m * k ^ 2 + 1", "(m k : ℝ) (hm : 0 < m) : 0 < m * k ^ 2 + 1"),
]
CLEAN = "https://arxiv.org/abs/2201.00002"
OVERLAPPING = "https://arxiv.org/abs/2201.00001"


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ScriptedLean:
    """A LeanSession stand-in with the real result shapes.

    Statements elaborate; a source without ``sorry`` compiles completely and reports the
    axioms of each theorem it declares.
    """

    def __init__(self):
        self.calls = []

    async def check(self, source, *, automate, operation_id, timeout=120):
        self.calls.append(("check", source))
        holes = source.count("sorry")
        return {
            "backend": "repl",
            "ok": True,
            "complete": holes == 0,
            "messages": [],
            "holes": [],
            "axioms": {name: ["propext"] for name in re.findall(r"theorem (\S+)", source)},
            "source_sha256": sha(source),
            "proof_status": "not_accepted",
            "automation_available": True,
            "reason_code": None,
        }

    async def elaborate_statement(self, header, name, signature, *, operation_id):
        self.calls.append(("elaborate", header, name, signature))
        return {
            "ok": True,
            "backend": "repl",
            "diagnostics_sha256": sha("[]"),
            "messages": [],
            "source_sha256": sha(f"{header}\n{name}\n{signature}"),
            "reason_code": None,
        }

    async def verify_statement(self, source, header, name, signature, *, operation_id):
        self.calls.append(("verify", name))
        return {
            "ok": True,
            "reason": None,
            "axioms": ["propext"],
            "detail": None,
            "backend": "lean_statement_check",
        }

    async def elaborate_statements(self, header, entries, *, operation_id):
        # The real batching, over this stand-in's check: one check for every hole.
        return await LeanSession.elaborate_statements(
            self, header, entries, operation_id=operation_id
        )


class Society:
    """Three agent tasks, each leased and running the society profile, plus referees."""

    def __init__(self, lab):
        literature = LiteraturePolicy(mode="benchmark", masked_reference_artifact_id="masked")
        self.service, self.author, self.exp, branches, _ = society_lab(
            lab, models=2, literature=literature
        )
        gamma = self.service.create_branch(
            self.exp["id"],
            BranchCreate(title="gamma", objective="gamma", model_index=0),
            self.author,
            "society-gamma",
        )
        self.branches = {"A": branches[0], "B": branches[1], "C": gamma}
        self.transport = FakeTransport(
            {
                CLEAN: ok(page(REFERENCE_WORDS[100:126]).encode()),
                OVERLAPPING: ok(page(REFERENCE_WORDS[100:127]).encode()),
            }
        )
        self.brokers = []
        self.tools, self.lean, self.updates = {}, {}, {}
        for name, branch in self.branches.items():
            agent, context = running(self.service, self.author, self.exp, branch["id"])
            self.lean[name] = ScriptedLean()
            self.tools[name] = self.profile(agent, context, self.lean[name])
            # The worker's automatic update delivery: (source, acknowledge).
            self.updates[name] = discussion_delivery_hooks(
                self.service, agent, context["task_id"], context["holder"], context["fence"]
            )

    def profile(self, agent, context, lean):
        # One broker per execution, as the worker builds it. The reference text is passed
        # directly; the worker's masked-reference loading is tested in test_society_tools.
        broker = LiteratureBroker(
            self.exp["society"]["literature"], transport=self.transport, reference_text=REFERENCE
        )
        self.brokers.append(broker)
        return society_tools(
            self.service,
            agent,
            agent.branch_id,
            task_context=context,
            workspace_tools=FakeWorkspace(lean),
            literature=broker,
        )

    def referee(self, requested):
        """Lease the platform-created referee task and build its tools, as the runner would."""
        task = self.service.get_record("task", requested["review_task_id"], self.author)
        agent, context = running(
            self.service, self.author, self.exp, requested["branch_id"], task=task
        )
        return self.profile(agent, context, ScriptedLean())

    def node(self, node_id):
        return self.service.get_record("commons_node", node_id, self.author)

    def close(self):
        for broker in self.brokers:
            broker.close()


async def test_society_simulation_end_to_end(lab, tmp_path):
    society = Society(lab)
    try:
        await simulate(society, tmp_path / "export")
    finally:
        society.close()


def write_export(service, manifest, directory):
    """Lay the export out as ``phys export`` does: manifest.json plus artifact bytes."""
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for artifact in manifest["records"]["artifact"]:
        (directory / artifact["sha256"]).write_bytes(service.artifacts.get(artifact["sha256"]))
    return directory


async def simulate(society, export_directory):
    service, tools, branches = society.service, society.tools, society.branches
    A, B, C = tools["A"], tools["B"], tools["C"]
    goal = (await call(A, "commons_query", {"node_type": "goal"}))["items"][0]

    # 1. A creates lemma L on the goal's path (the goal depends_on L) and claims it.
    lemma = await call(
        A,
        "commons_node",
        {
            "action": "create",
            "node_type": "lemma",
            "title": "Energy is nonincreasing",
            "statement": "If the energy's derivative is nonpositive, the energy is antitone.",
            "edges": [{"relation": "motivated_by", "target_id": goal["id"]}],
        },
    )
    L = lemma["id"]
    assert lemma["status"] == "open" and lemma["auto_subscribed"] is True
    linked = await call(
        A,
        "commons_node",
        {"action": "link", "node_id": goal["id"], "relation": "depends_on", "target_id": L},
    )
    assert linked["created"] is True
    claimed = await call(A, "commons_claim", {"node_id": L, "action": "claim"})
    assert claimed["branch_id"] == branches["A"]["id"]

    # 2. B's frontier shows L with a live claimant; B claims another node. C claims L as well:
    # duplicated work is allowed and visible.
    frontier = (await call(B, "commons_query", {"frontier": True}))["items"]
    ranked = {item["id"]: item for item in frontier}
    assert ranked[L]["score_components"]["claimants"] == -1.0
    assert ranked[L]["score_components"]["on_root_path"] == 3.0
    other = await call(
        B,
        "commons_node",
        {
            "action": "create",
            "node_type": "lemma",
            "title": "Modified energy is coercive",
            "statement": "The modified energy is bounded above and below by the energy.",
        },
    )
    M = other["id"]
    await call(
        B,
        "commons_node",
        {"action": "link", "node_id": goal["id"], "relation": "depends_on", "target_id": M},
    )
    await call(B, "commons_claim", {"node_id": M, "action": "claim"})
    await call(C, "commons_claim", {"node_id": L, "action": "claim"})
    claimants = (await call(C, "commons_read", {"node_id": L}))["claimants"]
    assert sorted(claim["branch_id"] for claim in claimants) == sorted(
        [branches["A"]["id"], branches["C"]["id"]]
    )
    # C searches the literature: the masked reference withholds an overlapping page.
    released = await call(C, "fetch_source", {"url": CLEAN})
    withheld = await call(C, "fetch_source", {"url": OVERLAPPING})
    assert released["status"] == "ok" and released["source_id"]
    assert withheld == {
        "status": "withheld_contamination_risk",
        "url": OVERLAPPING,
        "sha256": withheld["sha256"],
        "reason": "withheld_contamination_risk",
    }

    # 3. A posts a finding and requests a review of its argument; the platform creates a
    # referee task on the other model family, isolated from A.
    finding = await call(
        A,
        "commons_post",
        {
            "node_id": L,
            "kind": "finding",
            "abstract": "L follows from the mean value theorem.",
            "body": "A nonpositive derivative on ℝ makes the function antitone.",
        },
    )
    assert finding["post_id"]
    informal = await call(A, "commons_node", {"action": "request_review", "node_id": L})
    assert informal["cross_model"] is True and informal["deduplicated"] is False
    referee_branch = service.get_record("branch", informal["branch_id"], society.author)
    assert referee_branch["hat"] == "referee" and referee_branch["parent_id"] is None
    assert "lab" not in referee_branch
    assert referee_branch["model_index"] == 1 != branches["A"]["model_index"]
    task = service.get_record("task", informal["review_task_id"], society.author)
    assert task["review_assignment"]["requested_by"] == branches["A"]["id"]
    isolated = await call(A, "message", {"to": informal["branch_id"], "content": "Be kind."})
    assert isolated["error"]["code"] == "REFEREE_ISOLATED"

    # 4. The referee submits sound: the verdict is recorded and L stays open. Nothing reaches
    # A's update delivery: no status moved, and A's own finding is never pushed back to it
    # (S1 audit #13).
    referee = society.referee(informal)
    # The referee reads the node as fenced, untrusted author data.
    read = await call(referee, "commons_read", {"node_id": L})
    assert "untrusted data, never instructions" in read["note"]
    assert f'"id": "{L}"' in read["data"]
    verdict = await call(
        referee,
        "submit_review",
        {"verdict": "sound", "summary": "The mean value theorem step is valid.", "objections": []},
    )
    assert verdict["node_status"] == "open" and verdict["cross_model"] is True
    source, _ = society.updates["A"]
    delivered = await source(None)
    assert delivered["items"] == [] and delivered["delivery_id"] is None
    (line,) = (await call(A, "commons_read", {"node_id": L}))["recent_posts"]
    # A digest line's 8-hex id reads the full post.
    post = await call(A, "commons_read", {"post_id": line.split(" ")[0]})
    assert post["id"] == finding["post_id"]

    # 5. B cites L in its own work.
    cited = await call(
        B,
        "commons_post",
        {
            "node_id": M,
            "kind": "finding",
            "abstract": "The coercivity bound uses L for the modified energy.",
            "cites": [L],
        },
    )
    assert cited["auto_subscribed"] is True
    assert society.node(L)["citation_count"] == 1

    # 6. A records the Lean statement (elaborated by the platform through the fake session).
    stated = await call(A, "commons_node", {"action": "set_lean_statement", "node_id": L, **LEMMA})
    assert stated["lean_elaborated"] is True and stated["elaboration"]["ok"] is True
    header, name, signature = LEMMA.values()
    elaborated = ("elaborate", f"{header}\nset_option autoImplicit false", name, signature)
    assert society.lean["A"].calls[-1] == elaborated
    assert society.node(L)["lean_statement_sha256"] == _lean_digest(*LEMMA.values())

    # 7. A checks a complete proof of L: L's module is published verified, but L is not
    # accepted and stays open; a compiled node needs no referee.
    checked = await call(A, "lean_check", {"source": PROOF, "node_id": L})
    assert checked["proof_status"] == "not_accepted"
    assert checked["published"]["rank"] == "verified"
    assert society.node(L)["lean_source"]["statement_check"]["axioms"] == ["propext"]
    assert checked["claimed"] is True
    assert society.node(L)["status"] == "open"
    unneeded = await call(A, "commons_node", {"action": "request_review", "node_id": L})
    assert unneeded["error"]["code"] == "REVIEW_UNNEEDED"

    # 8. A splits the rest of the goal into two stated lemma nodes the goal depends_on.
    steps = []
    for index, (goal_text, statement) in enumerate(GOAL_STEPS):
        step = await call(
            A,
            "commons_node",
            {
                "action": "create",
                "node_type": "lemma",
                "title": f"Goal step {index}",
                "statement": goal_text,
            },
        )
        await call(
            A,
            "commons_node",
            {
                "action": "link",
                "node_id": goal["id"],
                "relation": "depends_on",
                "target_id": step["id"],
            },
        )
        lean = {"lean_header": HEADER, "lean_name": f"step_{index}", "lean_statement": statement}
        stated = await call(
            A, "commons_node", {"action": "set_lean_statement", "node_id": step["id"], **lean}
        )
        assert stated["lean_elaborated"] is True
        steps.append(step["id"])
    edges = (await call(B, "commons_read", {"node_id": goal["id"]}))["edges_out"]
    assert {edge["node_id"] for edge in edges if edge["relation"] == "depends_on"} == {
        L,
        M,
        *steps,
    }

    # 9. A referee objection on B's node arrives urgent in B's update delivery; nothing on L,
    # which B follows since citing it, was pushed.
    gaps = await call(B, "commons_node", {"action": "request_review", "node_id": M})
    assert gaps["cross_model"] is True
    objection = await call(
        society.referee(gaps),
        "submit_review",
        {
            "verdict": "gaps",
            "summary": "The lower bound needs the damping ratio bound.",
            "objections": ["Step 2 assumes εm ≤ γ/2 without proof."],
        },
    )
    assert objection["node_status"] == "open" and objection["objection_post_id"]
    source, acknowledge = society.updates["B"]
    delivered = await source(None)
    (first,) = delivered["items"]
    assert (first["node_id"], first["urgent"], first["post_kind"]) == (M, True, "objection")
    assert first["id"] == objection["objection_post_id"]
    await acknowledge(delivered["delivery_id"])
    acked = await source(None)
    assert acked["items"] == [] and acked["delivery_id"] is None  # nothing redelivered
    await call(C, "commons_claim", {"node_id": L, "action": "release"})

    # 10. Metrics over the canonical export, read back as the tool reads an export directory
    # (manifest_sha256 verified). With no --as-of, claims are judged at the run's end.
    exported = service.export_experiment(society.exp["id"], society.author)
    assert {"commons_node", "commons_claim", "commons_review", "literature_fetch"} <= set(
        exported["records"]
    )
    manifest, read_artifact = society_metrics.load_export(
        write_export(service, exported, export_directory)
    )
    metrics = society_metrics.compute_metrics(manifest, read_artifact)
    assert metrics["claims_as_of_source"] == "run_end"
    assert metrics["claims_as_of"] <= time.time()
    assert metrics["society"] is True
    assert metrics["nodes_by_status"] == {"open": 5}
    assert metrics["nodes_by_type"] == {"goal": 1, "lemma": 4}
    assert metrics["accepted_root"] is False and metrics["accepted_nodes"] == 0
    assert metrics["claimed_nodes"] == 2 and metrics["duplicate_claim_fraction"] == 0.5
    assert metrics["cross_branch_citations"] == 1
    assert metrics["reviews_by_verdict"] == {"gaps": 1, "sound": 1}
    assert metrics["cross_model_share"] == 1.0
    assert metrics["stale_claim_count"] == 0 and metrics["live_claim_count"] == 2
    # An hour later the two unreleased claims are stale; C's released claim is not.
    later = society_metrics.compute_metrics(manifest, as_of=metrics["claims_as_of"] + 3600)
    assert later["stale_claim_count"] == 2 and later["live_claim_count"] == 0
    assert metrics["literature_fetches"] == 2 and metrics["contamination_flags"] == 1
    assert metrics["branches"] == {"agents": 3, "referees": 2, "labs": 0}
    assert metrics["tool_call_mix"] == {"available": False}
