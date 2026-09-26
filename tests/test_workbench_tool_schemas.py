"""Provider strict-schema contract for the complete live research dispatcher."""

from types import SimpleNamespace

from physharness.domain import Principal
from physharness.orchestration.research_worker import research_tools
from physharness.orchestration.workspace_tools import WorkspacePolicy, WorkspaceTools


def _workspace_tools():
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.policy = WorkspacePolicy(
        template_id="sha256:" + "a" * 64,
        environment_digest="b" * 64,
        qualification_report_sha256="c" * 64,
        timeout_seconds=120,
        cost_bound_usd="0",
        cost_source="local_no_external_invoice",
    )
    return tools


def _assert_strict(schema):
    """Check every object arm, including nullable unions and combinator arms."""
    types = schema.get("type", [])
    types = {types} if isinstance(types, str) else set(types)
    if "object" in types:
        assert schema.get("additionalProperties") is False
        properties = schema.get("properties")
        assert isinstance(properties, dict)
        assert set(schema.get("required", [])) == set(properties)
        for child in properties.values():
            _assert_strict(child)
    if "array" in types:
        assert "items" in schema
        _assert_strict(schema["items"])
    for combinator in ("anyOf", "oneOf", "allOf"):
        for arm in schema.get(combinator, []):
            _assert_strict(arm)
    if "$defs" in schema:
        for definition in schema["$defs"].values():
            _assert_strict(definition)


def test_every_workbench_tool_has_recursive_strict_parameter_schema():
    registered = []
    _workspace_tools().register(
        lambda name, props, handler, description: registered.append((name, props))
    )
    assert registered
    for _, properties in registered:
        _assert_strict(
            {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            }
        )


def test_complete_research_and_workbench_dispatcher_is_recursively_strict():
    agent = Principal(
        id="worker", project_id="lab", role="agent", experiment_id="experiment", branch_id="branch"
    )
    # Construction reads the immutable task contract to expose only valid tools.
    service = SimpleNamespace(
        get_record=lambda kind, identifier, actor: (
            {"sharing": "ideas"}
            if kind == "experiment"
            else {"id": "task", "reply_to_parent_task_id": "parent"}
        )
    )
    dispatcher = research_tools(
        service,
        agent,
        "branch",
        task_context={"task_id": "task", "holder": "worker", "fence": 1},
        workspace_tools=_workspace_tools(),
    )
    assert any(definition["name"] == "return_result" for definition in dispatcher.definitions)
    assert any(definition["name"] == "run_command" for definition in dispatcher.definitions)
    for definition in dispatcher.definitions:
        assert definition["type"] == "function" and definition["strict"] is True
        _assert_strict(definition["parameters"])
    failure = next(item for item in dispatcher.definitions if item["name"] == "return_result")
    schema = failure["parameters"]["properties"]["execution_failure"]
    assert set(schema["type"]) == {"object", "null"}
    assert schema["properties"] == {"code": {"type": "string"}, "message": {"type": "string"}}
    assert set(schema["required"]) == {"code", "message"}
    assert schema["additionalProperties"] is False


def test_nullable_union_object_must_be_closed():
    valid = {
        "type": ["object", "null"],
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    }
    _assert_strict(valid)
    invalid = {"type": ["object", "null"]}
    try:
        _assert_strict(invalid)
    except AssertionError:
        pass
    else:
        raise AssertionError("Nullable object without closed properties escaped validation")
