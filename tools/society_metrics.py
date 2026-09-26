"""Research-society run metrics (PLAN §9) from one experiment export; prints JSON.

Usage::

    python tools/society_metrics.py EXPORT [--as-of EPOCH_SECONDS]

``EXPORT`` is either an export directory written by ``phys export`` (``manifest.json`` plus
artifact files named by their SHA-256) or a bare manifest JSON file, the output of
``service.export_experiment``. The manifest must be a bounded regular file whose
``manifest_sha256`` matches its content. Runtime-event artifacts are read from files
beside the manifest when present; they give the tool-call mix. Without them the mix is
reported as unavailable. Every artifact read is hash-checked.

Claims are judged stale or live at ``--as-of``. By default that is the run's end: the
latest activity the export records. A post-run export therefore does not count claims
that simply outlived the run as stale.

The tool reads canonical records only and never contacts a service or model. It works on
all three S1 arms: legacy exports (single agent, independent attempts) have no commons
records, so their commons metrics are zero or null, while outcomes, cost and the tool mix
are comparable. It is standard-library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

FORMAT = "physharness.society-metrics.v1"
ACCEPTED = "accepted"
MAX_MANIFEST_BYTES = 200_000_000  # The bound reproduction.validate_export applies.
MAX_ARTIFACT_BYTES = 20_000_000
DEFAULT_CLAIM_TTL_SECONDS = 900
# Tool-call buckets. Every tool of the society profile and of the 63-tool legacy profile is
# in exactly one of the three documented buckets, so every arm is comparable; a name in
# none of them (a tool added later) is counted as unclassified.
COMMONS_SOCIETY = frozenset(
    {
        # Society profile.
        "commons_query",
        "commons_read",
        "commons_node",
        "commons_post",
        "commons_claim",
        "inbox",
        "recruit",
        "message",
        "wait",
        "return_result",
        "submit_review",
        # Legacy profile.
        "acknowledge_discussion_updates",
        "amend_queued_objective",
        "child_task_status",
        "component_directory",
        "create_discussion",
        "delegate",
        "delegate_detached",
        "discussion_page",
        "discussion_posts",
        "discussion_updates",
        "fork_branch",
        "join_research_team",
        "joined_children",
        "mailbox_page",
        "message_delivery_status",
        "peer_availability",
        "post_discussion",
        "publish_research_profile",
        "read_discussion_post",
        "read_research_message",
        "recruit_researcher",
        "register_component",
        "request_handoff",
        "request_research_capacity",
        "research_capacity",
        "research_directory",
        "send_message",
        "subscribe_discussion",
        "wait_for_peer",
        "wait_for_tasks",
    }
)
MATH_LEAN_COMPUTATION = frozenset(
    {
        # Society profile.
        "shell",
        "read_file",
        "write_file",
        "run_computation",
        "lean_check",
        "lean_sketch",
        "search_library",
        "read_source",
        "submit_for_verification",
        "verification_status",
        # Legacy profile.
        "run_command",
        "run_lean_scratch",
        "check_lean_type",
        "check_matrix_factorization",
        "check_polynomial_identity",
        "lookup_library_declaration",
        "lookup_library_source",
        "search_library_source",
        "read_workspace_file",
        "write_workspace_file",
        "checkpoint_workspace",
        "store_workspace_artifact",
        "submit_candidate",
        "submit_workspace_candidate",
        "verify_candidate",
        "inspect_verification",
        "wait_for_verification",
        "read_accepted_proof_summary",
    }
)
# Memory, knowledge, literature and skills: neither coordination nor mathematics.
OTHER = frozenset(
    {
        # Society profile (read_artifact is in both profiles).
        "search_literature",
        "fetch_source",
        "notebook",
        "load_skill",
        "read_artifact",
        # Legacy profile.
        "checkpoint_context",
        "checkpoint_research_notes",
        "history_page",
        "index_page",
        "read_artifact_chunk",
        "read_dependency_bundle",
        "read_scientific_record",
        "research_graph_page",
        "restart_brief",
        "restore_context",
        "search_knowledge",
        "store_artifact",
        "working_context",
    }
)
BUCKETS = {
    "commons_society": COMMONS_SOCIETY,
    "math_lean_computation": MATH_LEAN_COMPUTATION,
    "other": OTHER,
}
LEAN_CHECKS = frozenset({"lean_check", "lean_sketch", "run_lean_scratch", "check_lean_type"})


def _epoch(stamp):
    return datetime.fromisoformat(stamp).timestamp() if stamp else None


def _share(part, whole):
    return round(part / whole, 6) if whole else None


def _sorted(counter):
    return dict(sorted(counter.items()))


def _read_bounded(path, limit):
    """A regular file's bytes, refusing links, special files and anything over ``limit``."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise ValueError(f"{path.name} must be a readable regular file, not a link.") from error
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"{path.name} must be a readable regular file, not a link.")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{path.name} exceeds {limit:,} bytes.")
    return data


def _canonical_digest(value):
    """``physharness.domain.digest_json``: SHA-256 of the canonical JSON encoding."""
    text = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def load_export(path):
    """The verified manifest and a hash-checked reader for artifact bytes beside it."""
    path = Path(path)
    manifest_path = path / "manifest.json" if path.is_dir() and not path.is_symlink() else path
    manifest = json.loads(_read_bounded(manifest_path, MAX_MANIFEST_BYTES))
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != _canonical_digest(unsigned):
        raise ValueError("The manifest's manifest_sha256 does not match its content.")
    directory = manifest_path.parent

    def read_artifact(sha256):
        candidate = directory / sha256
        if len(sha256) != 64 or candidate.is_symlink() or not candidate.is_file():
            return None
        data = _read_bounded(candidate, MAX_ARTIFACT_BYTES)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError(f"Artifact {sha256} failed its content hash.")
        return data

    return manifest, read_artifact


def run_end(manifest):
    """Epoch seconds of the latest activity the export records, or None when it has none.

    Candidates are every record's ``created_at``, commons nodes' ``last_activity_at``, each
    claim's last claim or renewal (its expiry less the policy TTL, never before it was
    created) and the experiment's start.
    """
    society = manifest["experiment"].get("society") or {}
    ttl = society.get("claim_ttl_seconds", DEFAULT_CLAIM_TTL_SECONDS)
    times = [_epoch(manifest["experiment"].get("started_at"))]
    for kind, rows in manifest["records"].items():
        for row in rows:
            times += [_epoch(row.get("created_at")), _epoch(row.get("last_activity_at"))]
            if kind == "commons_claim" and isinstance(row.get("expires_at"), (int, float)):
                times.append(max(row["expires_at"] - ttl, _epoch(row.get("created_at")) or 0))
    times = [value for value in times if value is not None]
    return max(times) if times else None


def accepted_root_receipt(manifest):
    """The earliest receipt meeting the platform's acceptance predicate for the exact target.

    It mirrors the canonical check on exported fields: a verified independent-kernel
    receipt bound to the reviewed problem revision, target, challenge, environment and the
    exported candidate artifact.
    """
    experiment, problem = manifest["experiment"], manifest["problem"]
    records = manifest["records"]
    if problem.get("semantic_review") != "approved":
        return None
    challenge = hashlib.sha256(problem["formal_statement"].encode("utf-8")).hexdigest()
    artifacts = {artifact["id"]: artifact for artifact in records.get("artifact", [])}
    accepted = []
    for receipt in records.get("verification", []):
        artifact = artifacts.get(receipt.get("artifact_id"))
        if (
            receipt.get("status") == "verified"
            and receipt.get("assurance") == "independent_kernel"
            and receipt.get("experiment_id") == experiment["id"]
            and receipt.get("review_id") == problem.get("review_id")
            and receipt.get("target_theorem") == problem.get("target_theorem", "target")
            and receipt.get("challenge_sha256") == challenge
            and receipt.get("problem_revision_id") == problem["id"]
            and receipt.get("target_digest")
            == problem.get("target_digest")
            == experiment.get("target_digest")
            and receipt.get("environment_digest") == problem.get("environment_digest")
            and artifact is not None
            and artifact.get("experiment_id") == experiment["id"]
            and receipt.get("candidate_sha256") == artifact.get("sha256")
        ):
            accepted.append(receipt)
    if not accepted:
        return None
    claims = {claim["id"]: claim for claim in records.get("claim", [])}

    def accepted_at(receipt):
        # The verified claim is written in the same commit that accepts the receipt.
        claim = claims.get(receipt.get("claim_id"))
        return (claim or receipt)["created_at"]

    first = min(accepted, key=lambda receipt: (accepted_at(receipt), receipt["id"]))
    return {**first, "accepted_at": accepted_at(first)}


def _claims(records, as_of):
    """Claimed nodes, duplicated ones, and stale and live claims at ``as_of``.

    A claim record holds one branch's latest claim on a node: from its first claim
    (``created_at``) to its last expiry (``expires_at``). Two branches whose spans overlap
    are counted as concurrent claimants. A release or re-claim inside a span is not
    recorded, so the duplicate count is an upper bound.
    """
    by_node = {}
    stale = live = 0
    for claim in records.get("commons_claim", []):
        start, end = _epoch(claim.get("created_at")), claim["expires_at"]
        by_node.setdefault(claim["node_id"], []).append((claim["branch_id"], start, end))
        if not claim.get("released"):
            if end <= as_of:
                stale += 1
            else:
                live += 1
    duplicated = 0
    for spans in by_node.values():
        if any(
            first[0] != second[0] and first[1] < second[2] and second[1] < first[2]
            for index, first in enumerate(spans)
            for second in spans[index + 1 :]
        ):
            duplicated += 1
    return {
        "claimed_nodes": len(by_node),
        "duplicate_claimed_nodes": duplicated,
        "duplicate_claim_fraction": _share(duplicated, len(by_node)),
        "stale_claim_count": stale,
        "live_claim_count": live,
    }


def _citations(records, nodes):
    """Citations from node-thread posts; cross-branch when the cited node's author differs."""
    authors = {node["id"]: node.get("branch_id") for node in nodes}
    total = cross = 0
    for post in records.get("discussion_post", []):
        for cited in post.get("cites") or []:
            total += 1
            author = authors.get(cited)
            if author and author != post.get("branch_id"):
                cross += 1
    return total, cross


def _cross_branch_dependencies(edges, nodes):
    authors = {node["id"]: node.get("branch_id") for node in nodes}
    return sum(
        1
        for edge in edges
        if edge["relation"] == "depends_on"
        and authors.get(edge["source"])
        and authors.get(edge["target"])
        and authors[edge["source"]] != authors[edge["target"]]
    )


def _reviews(reviews):
    verdicts = Counter(review["verdict"] for review in reviews)
    informal = [review for review in reviews if review["scope"] == "informal"]
    fidelity = [review for review in reviews if review["scope"] == "fidelity"]
    return {
        "reviews_by_verdict": _sorted(verdicts),
        "reviews_by_scope": _sorted(Counter(review["scope"] for review in reviews)),
        "cross_model_share": _share(sum(1 for r in reviews if r.get("cross_model")), len(reviews)),
        "stale_reviews": sum(1 for review in reviews if review.get("stale")),
        # Negative-verdict shares; a catch rate proper needs ground truth.
        "referee_negative_share": _share(
            sum(1 for review in informal if review["verdict"] in ("gaps", "wrong")), len(informal)
        ),
        "fidelity_failure_share": _share(
            sum(1 for review in fidelity if review["verdict"] == "unfaithful"), len(fidelity)
        ),
    }


def _tool_calls(records, read_artifact):
    """Tool-call counts from ``tool_completed`` runtime events (call counts, not tokens)."""
    events = [
        artifact
        for artifact in records.get("artifact", [])
        if artifact.get("artifact_kind") == "runtime_event"
    ]
    contents = [read_artifact(event["sha256"]) for event in events] if read_artifact else []
    contents = [content for content in contents if content is not None]
    if not contents:
        return {"available": False}, 0
    tools, stagnation = Counter(), 0
    for content in contents:
        event = json.loads(content)
        if event.get("kind") == "tool_completed":
            tools[event.get("payload", {}).get("name", "unknown")] += 1
        elif event.get("kind") == "stagnation_warning":
            stagnation += 1
    total = sum(tools.values())
    groups = Counter()
    for name, count in tools.items():
        bucket = next((key for key, names in BUCKETS.items() if name in names), None)
        groups[bucket or "unclassified"] += count
    mix = {
        "available": True,
        "runtime_events": len(events),
        "runtime_events_read": len(contents),
        "total": total,
        "commons_society": groups["commons_society"],
        "math_lean_computation": groups["math_lean_computation"],
        "other": groups["other"],
        "unclassified": groups["unclassified"],
        "commons_society_share": _share(groups["commons_society"], total),
        "by_tool": _sorted(tools),
        "stagnation_warnings": stagnation,
    }
    return mix, sum(count for name, count in tools.items() if name in LEAN_CHECKS)


def compute_metrics(manifest, read_artifact=None, *, as_of=None):
    """PLAN §9 metrics from one export manifest.

    ``as_of`` (epoch seconds) dates claim staleness; by default it is ``run_end``, and the
    current time only for an export that records no activity at all.
    """
    if as_of is not None:
        source = "argument"
    elif (as_of := run_end(manifest)) is not None:
        source = "run_end"
    else:
        as_of, source = time.time(), "now"
    records = manifest["records"]
    experiment = manifest["experiment"]
    nodes = records.get("commons_node", [])
    edges = manifest.get("edges", [])
    goal = next((node for node in nodes if node["node_type"] == "goal"), None)
    receipt = accepted_root_receipt(manifest)
    accepted_nodes = sum(1 for node in nodes if node["status"] == ACCEPTED)
    accepted_root = receipt is not None or (goal is not None and goal["status"] == ACCEPTED)
    started = experiment.get("started_at")
    spent = Decimal(manifest["ledger"]["spent_cost_usd"])
    # A legacy arm has no nodes; its accepted root is the one accepted result.
    accepted_results = accepted_nodes if nodes else int(accepted_root)
    fetches = records.get("literature_fetch", [])
    citations, cross_citations = _citations(records, nodes)
    branches = records.get("branch", [])
    referees = [branch for branch in branches if branch.get("hat") == "referee"]
    tool_mix, lean_checks = _tool_calls(records, read_artifact)
    return {
        "format": FORMAT,
        "experiment_id": experiment["id"],
        "society": experiment.get("society") is not None,
        "sharing": experiment.get("sharing"),
        # Outcomes.
        "accepted_root": accepted_root,
        "accepted_root_receipt_id": receipt["id"] if receipt else None,
        "time_to_root_seconds": round(_epoch(receipt["accepted_at"]) - _epoch(started), 3)
        if receipt and started
        else None,
        "accepted_nodes": accepted_nodes,
        "spent_cost_usd": str(spent),
        "tokens_spent": manifest["ledger"].get("tokens_spent"),
        "cost_per_accepted_result_usd": str(round(spent / accepted_results, 6))
        if accepted_results
        else None,
        # The blueprint.
        "nodes_by_status": _sorted(Counter(node["status"] for node in nodes)),
        "nodes_by_type": _sorted(Counter(node["node_type"] for node in nodes)),
        "edges_by_relation": _sorted(Counter(edge["relation"] for edge in edges)),
        # Efficiency and knowledge.
        **_claims(records, as_of),
        "claims_as_of": as_of,
        "claims_as_of_source": source,
        "citations": citations,
        "cross_branch_citations": cross_citations,
        "cross_branch_dependencies": _cross_branch_dependencies(edges, nodes),
        # Society health.
        **_reviews(records.get("commons_review", [])),
        "branches": {
            "agents": len(branches) - len(referees),
            "referees": len(referees),
            "labs": len({branch["lab"] for branch in branches if branch.get("lab")}),
        },
        # Literature and tools.
        "literature_fetches": len(fetches),
        "literature_by_status": _sorted(Counter(fetch["status"] for fetch in fetches)),
        "contamination_flags": sum(1 for fetch in fetches if fetch.get("flagged")),
        "tool_call_mix": tool_mix,
        "lean_checks_per_accepted_result": _share(lean_checks, accepted_results)
        if tool_mix["available"]
        else None,
        # Honest separation of evidence: the operator labels live versus mocked providers.
        "evidence": {
            "model_sessions": len(records.get("session", [])),
            "runtime_event_artifacts": sum(
                1
                for artifact in records.get("artifact", [])
                if artifact.get("artifact_kind") == "runtime_event"
            ),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("export", type=Path, help="Export directory or manifest JSON file.")
    parser.add_argument(
        "--as-of",
        type=float,
        default=None,
        help="Epoch seconds at which claims are judged stale (default: the run's end, the "
        "latest activity in the export).",
    )
    arguments = parser.parse_args(argv)
    manifest, read_artifact = load_export(arguments.export)
    metrics = compute_metrics(manifest, read_artifact, as_of=arguments.as_of)
    json.dump(metrics, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
