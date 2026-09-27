"""A society agent's prompt and compaction anchor (S1 audit #18): the target, the objective,
the constitution and the live frontier, without platform bookkeeping. Legacy prompts are
built in research_worker and never come here."""

from ..domain import canonical_json

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
    return f"{node_id[:8]} [{node_type}] {title[:120]}"


def society_prompt_view(
    service, *, experiment, task, agent, referee, ready, handoff_notes, instructions
):
    """One view for both the first prompt and every compaction anchor, read live.

    A referee's view is its fenced review packet (the objective), the target and the
    referee constitution. A builder's view adds only the non-empty context entries.
    """
    target = service.get_record("problem", experiment["problem_id"], agent)
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
