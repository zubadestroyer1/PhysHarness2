"""Workflow sandbox configuration; provider SDKs remain activity-only imports."""

from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions


def workflow_runner() -> SandboxedWorkflowRunner:
    """Preserve Temporal isolation while sharing process-owned import machinery.

    OpenHands -> FastMCP -> key_value.aio installs Beartype's global path hook.
    That loader consults beartype.claw state on *every* source import, including
    modules outside its checked packages. Re-importing its state inside Temporal
    recursively invokes the same loader before that state exists. Pass through
    this import infrastructure only; retain workflow reloads, member restrictions,
    and the dependency's type checks. Do not mutate Temporal's global defaults.
    """
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules("beartype")
    )
