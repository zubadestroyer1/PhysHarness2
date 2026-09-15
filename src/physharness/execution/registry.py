"""Configuration/qualification status, never a fabricated provider health check."""

from .types import Capabilities


def provider_capabilities() -> dict[str, Capabilities]:
    return {
        "openai_responses": Capabilities(
            available=False,
            reason="Configure API credentials and durable session store",
            hard_token_limit=True,
            portable_checkpoint=True,
        ),
        "codex": Capabilities(
            available=False,
            reason="Requires official SDK and trusted-worker opt-in; no native hard token cap",
        ),
        "claude": Capabilities(
            available=False,
            reason="Requires pinned SDK, trusted worker and explicit native-budget opt-ins",
        ),
        "openhands": Capabilities(
            available=False,
            reason="Requires pinned SDK, external remote-VM qualification and native-budget opt-in",
            isolation="provider_vm",
        ),
        "e2b": Capabilities(
            available=False,
            reason="Requires exact qualified template ID, API key, and optional SDK",
            isolation="provider_vm",
        ),
        "local_shell": Capabilities(
            available=False,
            reason="Development-only explicit opt-in required",
            isolation="development_process",
        ),
        "research_javascript": Capabilities(
            available=False,
            reason="Requires an isolated provider VM with Node and disabled network egress",
        ),
    }
