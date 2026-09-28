"""A society agent's prompt and compaction anchor (S1 audit #18): the target, the objective,
the constitution and the live frontier, without platform bookkeeping. Legacy prompts are
built in research_worker and never come here."""

import copy
import json
from datetime import UTC, datetime

from ..commons_discourse import _one_line
from ..domain import canonical_json
from ..memory import checked_target

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


def _focus_line(claim):
    """A focus node's line, then the branch's own claim: its route, agent text quoted like
    a title, and when its time box ends."""
    line = _line(claim["node_id"], claim["node_type"], claim["title"])
    if claim.get("route"):
        line += f" route {json.dumps(_one_line(claim['route']), ensure_ascii=False)}"
    if claim.get("time_box_until"):
        until = datetime.fromtimestamp(claim["time_box_until"], UTC)
        line += f" box until {until:%Y-%m-%dT%H:%MZ}"
    return line


def _checked_target(service, experiment, agent):
    """The target, refused unless its identity and canonical review are consistent: the
    check PortableMemory.working_context makes before a legacy prompt."""
    with service.db.sessions() as session:
        current = service._get(session, "experiment", experiment["id"], agent)
        target, _ = checked_target(service, session, current, agent)
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
        "focus_nodes": [_focus_line(claim) for claim in focus],
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
