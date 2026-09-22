"""Misconfiguration diagnostics must be useful without exposing credentials."""

import json
import traceback

import pytest

from physharness.config import Settings

TOKEN = "synthetic-bearer-secret-" + "a" * 40
DATABASE = "postgresql+psycopg://user:synthetic-password@localhost/db"


@pytest.mark.parametrize("source", ["argument", "environment", "file"])
def test_malformed_principal_does_not_leak_any_auth_input(tmp_path, monkeypatch, source):
    credentials = {TOKEN: {"id": "researcher", "project_id": "p", "role": "bad-role"}}
    inputs = {"auth_file": tmp_path / "auth.json", "database_url": DATABASE}
    if source == "argument":
        inputs["auth_tokens"] = credentials
    elif source == "environment":
        monkeypatch.setenv("PHYSHARNESS_AUTH_TOKENS", json.dumps(credentials))
    else:
        inputs["auth_file"].write_text(json.dumps(credentials))
    with pytest.raises(ValueError) as caught:
        Settings(**inputs)
    output = "".join(traceback.format_exception(caught.value))
    assert TOKEN not in output
    assert DATABASE not in output
    assert "synthetic-password" not in output
    assert "authentication" in str(caught.value).lower()


def test_other_settings_errors_do_not_echo_secrets(tmp_path):
    with pytest.raises(ValueError) as caught:
        Settings(
            mode="invalid",
            auth_file=tmp_path / "missing",
            database_url=DATABASE,
            auth_tokens={TOKEN: {"id": "r", "project_id": "p", "role": "researcher"}},
        )
    assert TOKEN not in str(caught.value)
    assert "synthetic-password" not in str(caught.value)


def test_malformed_auth_json_is_a_safe_configuration_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYSHARNESS_AUTH_TOKENS", TOKEN)
    with pytest.raises(ValueError) as caught:
        Settings(auth_file=tmp_path / "missing")
    assert TOKEN not in "".join(traceback.format_exception(caught.value))


def test_workspace_policy_errors_cannot_log_accidentally_supplied_credentials(tmp_path):
    sentinel = "SYNTHETIC_WORKSPACE_CREDENTIAL_123456"
    with pytest.raises(ValueError) as caught:
        Settings(
            auth_file=tmp_path / "missing",
            worker_workspace={
                "template_id": "template",
                "environment_digest": "a" * 64,
                "qualification_report_sha256": "b" * 64,
                "timeout_seconds": 60,
                "cost_bound_usd": "1",
                "cost_source": "fixture",
                "api_key": sentinel,
            },
        )
    assert sentinel not in "".join(traceback.format_exception(caught.value))
    assert "worker_workspace" in str(caught.value)
