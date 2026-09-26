"""Operator-only export and private, content-free metrics for one completed attempt.

The export contains private proof and transcript bytes. Only the small audit summary is
printed; never publish the export directory or its manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from collections import Counter
from pathlib import Path

from operator_handoffs import HandoffAuditError, terminal_sessions

from physharness.bootstrap import build_service
from physharness.config import Settings
from physharness.reproduction import validate_export

EVENT_PREFIXES = ("discussion.", "message.", "session.", "context.")
TASK_EVENT_NAMES = {
    "task.handoff_requested",
    "task.handoff-issue",
    "task.handoff-consume",
    "task.handoff-restore-unstarted",
    "task.workspace-handoff",
}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}


def summarize(manifest: dict, events: list[dict], artifact_bytes: dict[str, bytes]) -> dict:
    """Count only canonical identities and native usage, never source or text fields."""
    records = manifest["records"]
    experiment_id = manifest["experiment"]["id"]
    posts = records.get("discussion_post", [])
    deliveries = records.get("discussion_delivery", [])
    messages = records.get("message", [])
    tasks = records.get("task", [])
    sessions = records.get("session", [])
    artifacts = records.get("artifact", [])
    scoped_ids = {experiment_id}
    for kind in (
        "discussion_topic",
        "discussion_delivery",
        "message",
        "task",
        "session",
        "branch",
        "artifact",
    ):
        scoped_ids.update(record["id"] for record in records.get(kind, []))

    event_counts = Counter()
    for event in events:
        kind = event["kind"]
        if not (kind.startswith(EVENT_PREFIXES) or kind in TASK_EVENT_NAMES):
            continue
        if (
            event.get("aggregate_id") in scoped_ids
            or event.get("payload", {}).get("experiment_id") == experiment_id
        ):
            event_counts[kind] += 1

    usages: dict[str, dict] = {}
    artifact_kinds = Counter(artifact.get("artifact_kind") for artifact in artifacts)
    for artifact in artifacts:
        if artifact.get("artifact_kind") != "runtime_event":
            continue
        content = json.loads(artifact_bytes[artifact["id"]])
        if content.get("kind") != "usage":
            continue
        payload = content["payload"]
        response_id = payload["response_id"]
        usage = payload["native_usage"]
        if not isinstance(response_id, str) or not response_id:
            raise ValueError("invalid native response ID")
        if response_id in usages and usages[response_id] != usage:
            raise ValueError("conflicting native usage for response ID")
        for field in ("input_tokens", "output_tokens"):
            if type(usage.get(field)) is not int or usage[field] < 0:
                raise ValueError("invalid native token count")
        usages[response_id] = usage
    input_tokens = sum(usage["input_tokens"] for usage in usages.values())
    output_tokens = sum(usage["output_tokens"] for usage in usages.values())
    ledger_tokens = manifest["ledger"].get("tokens_spent")

    acknowledged = [d for d in deliveries if d.get("status") == "acknowledged"]
    acknowledged_items = Counter(
        item.get("source_kind", "unknown")
        for delivery in acknowledged
        for item in delivery.get("items", [])
    )
    return {
        "protocol": "exponential-operator-audit-v1",
        "experiment_id": experiment_id,
        "discussion": {
            "post_count": len(posts),
            "delivery_status_counts": dict(
                sorted(Counter(d.get("status", "unknown") for d in deliveries).items())
            ),
            "acknowledged_item_source_kinds": dict(sorted(acknowledged_items.items())),
        },
        "communication": {"direct_message_count": len(messages)},
        "tasks": {
            "terminal_status_counts": dict(
                sorted(
                    Counter(
                        t.get("status") for t in tasks if t.get("status") in TERMINAL_TASK_STATUSES
                    ).items()
                )
            ),
            "status_by_id": [{"id": t["id"], "status": t.get("status")} for t in tasks],
        },
        "sessions": {
            "status_counts": dict(
                sorted(Counter(s.get("status", "unknown") for s in sessions).items())
            ),
            "status_by_id": [{"id": s["id"], "status": s.get("status")} for s in sessions],
            "native_checkpoint_artifact_count": artifact_kinds["native_checkpoint"],
            "native_archive_artifact_count": artifact_kinds["native_archive"],
        },
        "events": dict(sorted(event_counts.items())),
        "usage": {
            "settled_native_response_count": len(usages),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_plus_output_matches_ledger": input_tokens + output_tokens == ledger_tokens,
        },
    }


def write_export(directory: Path, manifest: dict, artifact_bytes: dict[str, bytes]) -> dict:
    """Write a new private export and verify every immutable artifact byte."""
    directory = Path(directory)
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(directory)
    temporary = directory.with_name("." + directory.name + "-" + uuid.uuid4().hex)
    temporary.mkdir(mode=0o700)
    try:

        def private_file(path: Path, data: bytes) -> None:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

        private_file(
            temporary / "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            ),
        )
        written = set()
        for artifact in manifest["records"]["artifact"]:
            sha = artifact["sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("invalid artifact SHA")
            data = artifact_bytes[artifact["id"]]
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("artifact hash mismatch")
            if sha not in written:
                private_file(temporary / sha, data)
                written.add(sha)
        result = validate_export(temporary)
        os.replace(temporary, directory)
        return result
    except BaseException:
        shutil.rmtree(temporary)
        raise


def read_events(database_url: str) -> list[dict]:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("expected a local SQLite attempt")
    path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        return [
            {"kind": kind, "aggregate_id": aggregate_id, "payload": json.loads(payload)}
            for kind, aggregate_id, payload in connection.execute(
                "SELECT kind,aggregate_id,payload FROM events ORDER BY sequence"
            )
        ]


def audit_one(attempt: dict) -> dict:
    private = Path(attempt["private_directory"]).resolve()
    if not private.is_dir():
        raise ValueError("attempt directory missing")
    token = (private / "operator.token").read_text().strip()
    settings = Settings(
        _env_prefix="EXPONENTIAL_AUDIT_CONFIG_ONLY_",
        mode="local",
        database_url=attempt["database_url"],
        artifact_root=Path(attempt["artifact_root"]),
        auth_file=private / "auth.json",
        auto_create_schema=False,
    )
    actor = settings.auth_tokens.get(token)
    if actor is None or actor.role != "operator" or actor.project_id != attempt["project_id"]:
        raise ValueError("operator identity required")
    service = build_service(settings)
    manifest = service.export_experiment(attempt["experiment_id"], actor)
    ledger = manifest["ledger"]
    tasks = manifest["records"]["task"]
    sessions = manifest["records"]["session"]
    links = manifest["records"].get("continuation_link", [])
    scope = {
        "target_digest": manifest["experiment"]["target_digest"],
        "review_id": manifest["problem"].get("review_id"),
        "environment_digest": manifest["problem"]["environment_digest"],
    }
    artifacts = {artifact["id"]: artifact for artifact in manifest["records"]["artifact"]}
    try:
        sessions_drained = terminal_sessions(
            tasks,
            sessions,
            artifacts,
            lambda artifact_id: service.artifact_content(artifact_id, actor),
            attempt["experiment_id"],
            links=links,
            scope=scope,
        )
    except HandoffAuditError as exc:
        raise ValueError(f"attempt session lineage unresolved: {exc}") from exc
    if (
        not tasks
        or any(t.get("status") not in TERMINAL_TASK_STATUSES for t in tasks)
        or not sessions_drained
        or ledger["active_workers"]
        or float(ledger["reserved_cost_usd"]) != 0
        or ledger["tokens_reserved"]
        or ledger["uncertain_operations"]
    ):
        raise ValueError("attempt is not fully drained")
    artifact_bytes = {
        artifact["id"]: service.artifact_content(artifact["id"], actor)
        for artifact in manifest["records"]["artifact"]
    }
    events = read_events(attempt["database_url"])
    summary = summarize(manifest, events, artifact_bytes)
    summary["integrity"] = write_export(private / "export", manifest, artifact_bytes)
    summary_path = private / "audit-summary.json"
    fd = os.open(summary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(summary, stream, sort_keys=True, separators=(",", ":"))
    return {
        "status": "audited",
        "label": attempt["label"],
        "summary_file": str(summary_path),
        "export_directory": str(private / "export"),
        "audit": summary,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    attempts = [a for a in manifest["attempts"] if a["label"] == args.label]
    if len(attempts) != 1:
        parser.error("one known attempt label required")
    print(json.dumps(audit_one(attempts[0]), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
