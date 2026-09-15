import pytest

from physharness.execution import (
    CodexRuntime,
    E2BSandboxProvider,
    ExecutionError,
    ModelConfig,
    RuntimeLimits,
    SQLiteRuntimeStore,
    provider_capabilities,
)


async def test_e2b_requires_exact_template_and_key():
    for provider in [E2BSandboxProvider(), E2BSandboxProvider(api_key="test")]:
        assert not provider.capabilities.available
        with pytest.raises(ExecutionError) as error:
            await provider.create()
        assert error.value.code == "PROVIDER_UNAVAILABLE"
    with pytest.raises(ExecutionError, match="fork"):
        await E2BSandboxProvider().fork()


async def test_codex_refuses_unenforceable_hard_limits(tmp_path):
    runtime = CodexRuntime(
        store=SQLiteRuntimeStore(tmp_path / "s.db"), cwd=tmp_path, allow_local_execution=True
    )
    assert not runtime.capabilities.hard_token_limit
    with pytest.raises(ExecutionError) as error:
        await runtime.start("x", ModelConfig(model="exact"), RuntimeLimits())
    assert error.value.code == "CAPABILITY_UNAVAILABLE"


def test_unqualified_providers_report_unavailable():
    registry = provider_capabilities()
    assert not registry["claude"].available
    assert not registry["openhands"].available
    assert not registry["codex"].controlled_spawning


def test_optional_sdk_signatures_are_real():
    import inspect

    sdk = pytest.importorskip("openai_codex")
    assert "model" in inspect.signature(sdk.AsyncCodex.thread_start).parameters
    assert "config" in inspect.signature(sdk.AsyncCodex.thread_start).parameters
    assert "thread_id" in inspect.signature(sdk.AsyncCodex.thread_resume).parameters
    assert "input" in inspect.signature(sdk.AsyncThread.turn).parameters
    e2b = pytest.importorskip("e2b")
    assert "template" in inspect.signature(e2b.AsyncSandbox.create).parameters
    assert "allow_internet_access" in inspect.signature(e2b.AsyncSandbox.create).parameters
