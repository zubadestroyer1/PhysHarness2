"""A society agent's prompt and compaction anchor (S1 audit #18): the target, the objective,
the constitution and the live frontier, without platform bookkeeping. Legacy prompts are
built in research_worker and never come here."""

import copy
import json

from ..commons_discourse import _one_line
from ..domain import canonical_json
from ..errors import HarnessError
from ..storage import RecordRow

TARGET_FIELDS = (
    "title",
    "informal_statement",
    "formal_statement",
    "target_theorem",
    "assumptions",
    "definitions",
)
FRONTIER_ITEMS = 5
FOCUS_ITEMS = 10


def _line(node_id, node_type, title):
    """A platform-format node line. The title is agent text: collapsed to one line and
    JSON-quoted, as in compact updates, so it cannot forge another line."""
    return f"{node_id[:8]} [{node_type}] {json.dumps(_one_line(title)[:120], ensure_ascii=False)}"


def _checked_target(service, experiment, agent):
    """The target, refused unless its identity and canonical review are consistent: the
    checks PortableMemory.working_context makes before a legacy prompt."""
    with service.db.sessions() as session:
        current = service._get(session, "experiment", experiment["id"], agent)
        target = service._get(session, "problem", current.payload["problem_id"], agent)
        if target.payload["target_digest"] != current.payload["target_digest"]:
            raise HarnessError("CONTEXT_TARGET_INVALID", "Experiment and target identities differ.")
        if target.payload.get("review_id"):
            review = session.get(RecordRow, target.payload["review_id"])
            if (
                not review
                or review.kind != "review"
                or review.project_id != agent.project_id
                or review.payload.get("problem_id") != target.id
                or review.payload.get("target_digest") != target.payload["target_digest"]
                or review.payload.get("decision") != target.payload.get("semantic_review")
            ):
                raise HarnessError(
                    "CONTEXT_REVIEW_INVALID", "Target review identity is inconsistent."
                )
        elif target.payload.get("semantic_review") != "pending":
            raise HarnessError(
                "CONTEXT_REVIEW_INVALID", "A reviewed target requires its canonical review."
            )
        return copy.deepcopy(target.payload)


def society_prompt_view(
    service, *, experiment, task, agent, referee, ready, handoff_notes, instructions
):
    """One view for both the first prompt and every compaction anchor, read live.

    A referee's view is its fenced review packet (the objective), the target and the
    referee constitution. A builder's view adds only the non-empty context entries.
    """
    target = _checked_target(service, experiment, agent)
    view = {
        "objective": task["objective"],
        "target": {field: target.get(field) for field in TARGET_FIELDS},
        "instructions": instructions,
    }
    if referee:
        return view  # the fenced review packet is the referee's objective
    frontier = service.query_nodes(experiment["id"], agent, frontier=True, limit=FRONTIER_ITEMS)
    focus = service.branch_claims(experiment["id"], agent, limit=FOCUS_ITEMS)["items"]
    models = experiment["models"]
    joined = [
        item["task_id"] for item in service.joined_task_statuses(task["id"], agent)["children"]
    ]
    optional = {
        "frontier": [_line(i["id"], i["node_type"], i["title"]) for i in frontier["items"]],
        # Where help counts most (S1 audit #14), or how to make it visible.
        "long_pole": [_line(i["id"], i["node_type"], i["title"]) for i in frontier["long_pole"]],
        "long_pole_hint": frontier.get("long_pole_hint"),
        "focus_nodes": [_line(i["node_id"], i["node_type"], i["title"]) for i in focus],
        "strategy": task.get("strategy"),
        "models": [{"index": index, "model": model["model"]} for index, model in enumerate(models)]
        if len({canonical_json(model) for model in models}) > 1
        else None,
        "synthesis": {
            "source_post_ids": task.get("discussion_refs") or [],
            "scope": task.get("synthesis_scope"),
        }
        if task.get("synthesis_scope")
        else None,
        "continuation": {"reason": ready["reason"], "ordinal": ready["ordinal"]} if ready else None,
        "handoff_notes": handoff_notes,
        "joined_results": service.delegated_task_statuses(task["id"], joined, agent)
        if joined
        else None,
    }
    view.update({key: value for key, value in optional.items() if value})
    return view
