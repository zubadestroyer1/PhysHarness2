"""Audit metrics must reflect canonical delivery and deduplicated settled usage."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from physharness.domain import digest_json

PATH = Path(__file__).with_name("audit_export.py")
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("exponential_audit_export", PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_summary_counts_acknowledged_delivery_and_deduplicates_usage():
    usage_1 = {
        "kind": "usage",
        "payload": {
            "response_id": "r1",
            "native_usage": {
                "input_tokens": 10,
                "output_tokens": 3,
            },
        },
    }
    usage_2 = {
        "kind": "usage",
        "payload": {
            "response_id": "r2",
            "native_usage": {
                "input_tokens": 20,
                "output_tokens": 4,
            },
        },
    }
    artifacts = {
        "a1": json.dumps(usage_1).encode(),
        "a1dup": json.dumps(usage_1).encode(),
        "a2": json.dumps(usage_2).encode(),
        "secret": b"PROOF_SECRET",
    }
    manifest = {
        "experiment": {"id": "exp1"},
        "ledger": {"tokens_spent": 37},
        "records": {
            "discussion_post": [{"id": "p1"}],
            "discussion_delivery": [
                {
                    "id": "d1",
                    "status": "acknowledged",
                    "items": [{"source_kind": "discussion_post"}],
                },
                {"id": "d2", "status": "pending", "items": [{"source_kind": "message"}]},
            ],
            "message": [{"id": "m1"}],
            "session": [{"id": "s1", "status": "completed"}, {"id": "s2", "status": "failed"}],
            "task": [{"id": "t1", "status": "completed"}, {"id": "t2", "status": "failed"}],
            "artifact": [
                {
                    "id": key,
                    "artifact_kind": "runtime_event" if key != "secret" else "native_checkpoint",
                }
                for key in artifacts
            ],
        },
    }
    events = [
        {"kind": "task.handoff-issue", "aggregate_id": "t1", "payload": {}},
        {"kind": "task.handoff-consume", "aggregate_id": "t1", "payload": {}},
        {"kind": "session.saved", "aggregate_id": "s1", "payload": {}},
        {"kind": "context.checkpointed", "aggregate_id": "secret", "payload": {"branch_id": "b1"}},
        {"kind": "task.handoff-issue", "aggregate_id": "unrelated", "payload": {}},
    ]
    result = audit.summarize(manifest, events, artifacts)
    assert result["discussion"]["post_count"] == 1
    assert result["discussion"]["delivery_status_counts"] == {"acknowledged": 1, "pending": 1}
    assert result["communication"]["direct_message_count"] == 1
    assert result["tasks"]["terminal_status_counts"] == {"completed": 1, "failed": 1}
    assert result["sessions"]["status_counts"] == {"completed": 1, "failed": 1}
    assert result["events"]["task.handoff-issue"] == 1
    assert result["events"]["task.handoff-consume"] == 1
    assert result["events"]["context.checkpointed"] == 1
    assert result["usage"] == {
        "settled_native_response_count": 2,
        "input_tokens": 30,
        "output_tokens": 7,
        "input_plus_output_matches_ledger": True,
    }
    assert "PROOF_SECRET" not in json.dumps(result)


def test_conflicting_duplicate_native_response_is_rejected():
    base = {
        "experiment": {"id": "exp1"},
        "ledger": {"tokens_spent": 0},
        "records": {
            "artifact": [
                {"id": "a", "artifact_kind": "runtime_event"},
                {"id": "b", "artifact_kind": "runtime_event"},
            ],
        },
    }

    def usage(n):
        return json.dumps(
            {
                "kind": "usage",
                "payload": {
                    "response_id": "r1",
                    "native_usage": {
                        "input_tokens": n,
                        "output_tokens": 0,
                    },
                },
            }
        ).encode()

    with pytest.raises(ValueError, match="conflicting native usage"):
        audit.summarize(base, [], {"a": usage(1), "b": usage(2)})


def test_write_export_checks_every_artifact_hash(tmp_path):
    import hashlib

    from physharness.reproduction import validate_export

    data = b"PRIVATE_PROOF_BYTES"
    sha = hashlib.sha256(data).hexdigest()
    unsigned = {
        "format": "physharness.reproduction.v1",
        "records": {"artifact": [{"id": "a", "sha256": sha}]},
    }
    manifest = {**unsigned, "manifest_sha256": digest_json(unsigned)}
    destination = tmp_path / "export"
    result = audit.write_export(destination, manifest, {"a": data})
    assert result["unique_artifacts_checked"] == 1
    assert validate_export(destination)["status"] == "artifact_integrity_checked"
    with pytest.raises(FileExistsError):
        audit.write_export(destination, manifest, {"a": data})
