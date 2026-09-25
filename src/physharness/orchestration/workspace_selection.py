"""Select the configured worker provider without implicit host execution fallback."""

from ..errors import HarnessError
from .workspace_tools import e2b_workspace_factory, local_docker_workspace_factory


def configured_workspace_factory(settings):
    policy = getattr(settings, "worker_workspace", None)
    provider = getattr(settings, "worker_workspace_provider", None)
    if policy is None:
        if provider is not None:
            raise HarnessError(
                "WORKSPACE_POLICY_REQUIRED", "Worker provider needs a workspace policy."
            )
        return None
    if provider is None or provider == "e2b":
        return e2b_workspace_factory(policy)
    if provider == "local_docker":
        docker_host = getattr(settings, "worker_docker_host", None)
        image_digest = getattr(settings, "worker_image_digest", None)
        if not docker_host or not image_digest:
            raise HarnessError(
                "WORKSPACE_CONFIG_REQUIRED", "Local Docker needs a dedicated host and pinned image."
            )
        return local_docker_workspace_factory(
            policy,
            docker_host=docker_host,
            image_digest=image_digest,
            workspace_quota_bytes=getattr(
                settings, "worker_workspace_quota_bytes", 256 * 1024 * 1024
            ),
            max_workspaces=getattr(settings, "worker_max_active_workspaces", 1),
        )
    raise HarnessError("WORKSPACE_PROVIDER_INVALID", "Unknown worker workspace provider.")
