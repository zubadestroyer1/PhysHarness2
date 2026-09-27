"""The lemma store: each commons node's Lean module and its ranked published source.

A node's Lean module is ``Commons.N<hex>`` (8 hex of its id, lengthened on a collision). A
clean ``lean_check`` against the node publishes the checked file as the node's source,
ranked ``verified`` (the statement check passed on standard axioms), ``complete`` (no
``sorry``, but the check could not judge) or ``partial``. A higher rank replaces a lower
one; a verified source of the node's current statement is replaced only by its publisher or
the node's author (S1 audit #12).
"""

import re

from .commons_models import CLOSED_STATUSES
from .domain import utcnow
from .errors import HarnessError
from .worker_authority import current_worker_effects

RANKS = {"partial": 1, "complete": 2, "verified": 3}
COMPLETE_RANKS = frozenset({"complete", "verified"})
SOURCE_STATES = ("verified", "complete", "partial", "stub", "none")
MODULE = re.compile(r"Commons\.N([0-9a-f]{8}|[0-9a-f]{12}|[0-9a-f]{16})")
SKIPPED_IMPORT_EDGES = frozenset({"DEPENDENCY_CYCLE", "SELF_EDGE"})


def node_module(node: dict) -> str:
    """The node's module name; nodes recorded before modules existed use 8 hex of the id."""
    return node.get("lean_module") or "Commons.N" + node["id"][:8]


def module_prefix(module: str) -> str | None:
    """The dashed record-id prefix a module name encodes, or None for another name."""
    match = MODULE.fullmatch(module) if isinstance(module, str) else None
    if match is None:
        return None
    hexid = match.group(1)
    return hexid[:8] + "".join("-" + hexid[i : i + 4] for i in range(8, len(hexid), 4))


def _statement_digest(node):
    from .commons import _lean_digest  # commons imports this module for its node views

    return _lean_digest(node.get("lean_header"), node.get("lean_name"), node.get("lean_statement"))


def _effective_rank(source, digest):
    """A verified source of an older statement counts as complete."""
    if source["rank"] == "verified" and source.get("lean_statement_sha256") != digest:
        return "complete"
    return source["rank"]


def node_refusal(node: dict) -> str | None:
    """Why a node takes no published source (the goal, or a closed node), or None."""
    if node["node_type"] == "goal":
        return "goal_node"
    if node["status"] in CLOSED_STATUSES:
        return "node_closed"
    return None


def blocking_rank(node: dict, rank: str, branch_id: str | None) -> str | None:
    """The effective rank of the node's source when it keeps its place against a new source
    of ``rank`` from ``branch_id``, else None. At equal rank the newer source wins, except
    that a verified source of the current statement answers only to its publisher and the
    node's author."""
    current = node.get("lean_source")
    if current is None:
        return None
    held = _effective_rank(current, _statement_digest(node))
    if RANKS[rank] < RANKS[held] or (
        rank == held == "verified"
        and branch_id not in (current.get("branch_id"), node.get("branch_id"))
    ):
        return held
    return None


def source_state(node: dict) -> str:
    """The node's effective source rank; ``stub`` for an elaborated Lean statement with no
    source (it imports as a ``sorry`` stub), else ``none``."""
    source = node.get("lean_source")
    if source:
        return _effective_rank(source, _statement_digest(node))
    if node.get("lean_statement") is not None and node.get("lean_elaborated"):
        return "stub"
    return "none"


class CommonsSourceMixin:
    def _module_node(self, session, module, actor, experiment_id):
        """The experiment's node whose module is ``module``."""
        prefix = module_prefix(module)
        if prefix is not None:
            for row in self._prefix_candidates(session, prefix, actor, ("commons_node",)):
                if (
                    row.payload.get("experiment_id") == experiment_id
                    and node_module(row.payload) == module
                ):
                    return row
        raise HarnessError(
            "COMMONS_MODULE_NOT_FOUND",
            f"No commons node has the module {str(module)[:100]}.",
            status=404,
            details={"module": module},
            remediation="Import a module name a node reports (commons_read, commons_query).",
        )

    def record_lean_source(self, node_id, artifact_id, record, actor, key) -> dict:
        """Publish a checked ``lean_source`` artifact as the node's source, by the rank rule.

        ``record`` is platform evidence assembled by ``lean_check``: ``rank``, ``bytes``,
        ``statement_check``, ``lean_statement_sha256`` (the statement the file was checked
        against) and ``imports`` (``[{module, node_id, sha256}]``, each a depends_on edge).
        """
        self._research_role(actor)
        if not isinstance(record, dict) or record.get("rank") not in RANKS:
            raise HarnessError(
                "INVALID_SOURCE_RECORD", f"A source rank is one of: {', '.join(RANKS)}.", status=422
            )
        inputs = {"node_id": node_id, "artifact_id": artifact_id, "record": record}

        def action(session, op):
            row, experiment = self._review_node(session, node_id, actor)
            node = row.payload
            module = node_module(node)
            refusal = node_refusal(node)
            if refusal is not None:
                return {"recorded": False, "module": module, "reason": refusal}
            artifact = self._get(session, "artifact", artifact_id, actor)
            if (
                artifact.payload.get("artifact_kind") != "lean_source"
                or artifact.payload.get("experiment_id") != experiment.id
                or artifact.payload.get("branch_id") != actor.branch_id
            ):
                raise HarnessError(
                    "SOURCE_ARTIFACT_SCOPE",
                    "A published source is a lean_source artifact of the publisher's branch in "
                    "the node's experiment.",
                    status=403,
                )
            digest = _statement_digest(node)
            if digest is not None and record["lean_statement_sha256"] != digest:
                return {"recorded": False, "module": module, "reason": "statement_changed"}
            rank, current = record["rank"], node.get("lean_source")
            held = blocking_rank(node, rank, actor.branch_id)
            if held is not None:
                return {"recorded": False, "module": module, "reason": "lower_rank", "rank": held}
            binding = current_worker_effects.get()
            source = {
                "artifact_id": artifact.id,
                "sha256": artifact.payload["sha256"],
                "bytes": record["bytes"],
                "branch_id": actor.branch_id,
                "task_id": binding.task_id if binding is not None else None,
                "rank": rank,
                "statement_check": record["statement_check"],
                "lean_statement_sha256": record["lean_statement_sha256"],
                "imports": record["imports"],
                "recorded_at": utcnow().isoformat(),
            }
            self._replace(session, row, {"lean_source": source})
            for entry in record["imports"]:
                try:
                    self._add_edge(
                        session, op, experiment, row.id, "depends_on", entry["node_id"], actor
                    )
                except HarnessError as error:
                    if error.code not in SKIPPED_IMPORT_EDGES:
                        raise
            self._touch_node(session, row, actor, op)
            replaced = current is not None
            self._event(
                session,
                actor,
                op,
                "commons.source_published",
                row.id,
                {
                    "experiment_id": experiment.id,
                    "node_id": row.id,
                    "branch_id": actor.branch_id,
                    "artifact_id": artifact.id,
                    "sha256": source["sha256"],
                    "rank": rank,
                    "replaced": replaced,
                },
            )
            return {"recorded": True, "module": module, "rank": rank, "replaced": replaced}

        return self._execute(actor, key, "commons.source_publish", inputs, action)
