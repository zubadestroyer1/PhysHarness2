import json

import pytest
from test_core import setup_experiment

from physharness.domain import ArtifactCreate, digest_json
from physharness.errors import HarnessError
from physharness.reproduction import validate_export


def export_fixture(lab, directory):
    service, actor, _ = lab
    experiment, _ = setup_experiment(lab)
    artifact = service.create_artifact(
        ArtifactCreate(experiment_id=experiment["id"], kind="finding", content="Unresolved"),
        actor,
        "result",
    )
    manifest = service.export_experiment(experiment["id"], actor)
    directory.mkdir()
    (directory / artifact["sha256"]).write_bytes(b"Unresolved")
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest, artifact


def test_export_has_review_and_consistent_snapshot_identity(lab, tmp_path):
    manifest, _ = export_fixture(lab, tmp_path / "export")
    assert manifest["records"]["review"][0]["id"] == manifest["problem"]["review_id"]
    assert manifest["snapshot"]["isolation"] in {"sqlite_immediate", "postgresql_repeatable_read"}
    assert manifest["snapshot"]["last_project_event_sequence"] > 0
    result = validate_export(tmp_path / "export")
    assert result["status"] == "artifact_integrity_checked"
    assert result["kernel_replay"] == "not_performed"
    assert result["publication_approved"] is False


@pytest.mark.parametrize("tamper", ["manifest", "artifact", "symlink", "missing"])
def test_export_validation_rejects_tampering_and_missing_bytes(lab, tmp_path, tamper):
    directory = tmp_path / "export"
    manifest, artifact = export_fixture(lab, directory)
    if tamper == "manifest":
        manifest["qualification"]["live_fleet"] = "qualified"
        (directory / "manifest.json").write_text(json.dumps(manifest))
    else:
        target = directory / artifact["sha256"]
        target.unlink()
        if tamper == "artifact":
            target.write_bytes(b"forged")
        elif tamper == "symlink":
            other = tmp_path / "other"
            other.write_bytes(b"Unresolved")
            target.symlink_to(other)
    with pytest.raises(HarnessError):
        validate_export(directory)


def test_hash_checked_export_does_not_trust_claimed_qualification(lab, tmp_path):
    directory = tmp_path / "export"
    manifest, _ = export_fixture(lab, directory)
    manifest["qualification"] = {"scientific_novelty": "approved", "live_fleet": "qualified"}
    manifest["manifest_sha256"] = digest_json(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    )
    (directory / "manifest.json").write_text(json.dumps(manifest))
    result = validate_export(directory)
    assert result["publication_approved"] is False
    assert result["kernel_replay"] == "not_performed"


def test_worker_can_export_current_target_review_without_browsing_other_reviews(lab):
    from test_sharing import approaches

    service, _, exp, _, (alpha, _) = approaches(lab, "none")
    manifest = service.export_experiment(exp["id"], alpha)
    assert manifest["records"]["review"][0]["id"] == manifest["problem"]["review_id"]
    assert len(service.list_records("review", alpha)) == 1


def test_fifo_manifest_is_rejected_without_blocking(tmp_path):
    import os
    from concurrent.futures import ThreadPoolExecutor

    os.mkfifo(tmp_path / "manifest.json")
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(validate_export, tmp_path)
        with pytest.raises(HarnessError):
            attempt.result(timeout=1)


def test_cli_export_is_private_independently_of_umask(lab, tmp_path, monkeypatch):
    import os
    import stat

    from physharness import cli

    source = tmp_path / "source"
    manifest, _ = export_fixture(lab, source)

    class TestTransport:
        def request(self, method, path):
            if path.endswith("/export"):
                return manifest
            return {"content": "Unresolved"}

        def close(self):
            pass

    monkeypatch.setattr(cli, "client", lambda: TestTransport())
    target = tmp_path / "private-export"
    previous = os.umask(0o022)
    try:
        cli.export(manifest["experiment"]["id"], target)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in target.iterdir())


# Society records in exports -----------------------------------------------------------------

LEGACY_RECORD_KINDS = [
    "branch",
    "task",
    "claim",
    "artifact",
    "session",
    "continuation_link",
    "verification",
    "program",
    "message",
    "source",
    "workspace",
    "workspace_operation",
    "review",
    "discussion_topic",
    "discussion_post",
    "discussion_reader",
    "discussion_subscription",
    "discussion_delivery",
    "discussion_withdrawal",
    "workforce_policy",
    "workforce_profile",
    "workforce_team",
    "workforce_capacity_request",
]
# Recorded from the pre-change export (before society records were exported).
LEGACY_EXPORT_DIGEST = "0efaa7e4b41ee8516078a376b687996ea43d24e3655a17d576e26273d6d6317f"


def normalized_export(manifest):
    """Digest with ids, times and hashes masked, and each record list in a stable order."""
    from test_society_tools import HEX64, STAMP, UUID

    text = json.dumps(manifest, sort_keys=True)
    masked = json.loads(HEX64.sub("<sha256>", STAMP.sub("<time>", UUID.sub("<id>", text))))
    masked["records"] = {
        kind: sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
        for kind, rows in masked["records"].items()
    }
    return digest_json(masked)


def legacy_export(lab):
    """A legacy ideas-sharing experiment with a task, an artifact, a message and a post."""
    from test_sharing import approaches

    from physharness.discussion_models import DiscussionCreate
    from physharness.domain import TaskCreate

    service, author, exp, branches, (alpha, beta) = approaches(lab, "ideas")
    service.create_task(TaskCreate(branch_id=branches[0]["id"], objective="Work"), author, "t")
    service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], kind="finding", content="Idea"), alpha, "a"
    )
    service.send_message(branches[0]["id"], branches[1]["id"], "Hello.", [], alpha, "m")
    service.create_discussion(
        exp["id"], DiscussionCreate(title="Trace", summary="Opening summary."), alpha, "d"
    )
    return service.export_experiment(exp["id"], author)


def test_legacy_export_is_byte_identical(lab):
    manifest = legacy_export(lab)
    assert list(manifest["records"]) == LEGACY_RECORD_KINDS
    assert list(manifest) == [
        "format",
        "experiment",
        "problem",
        "records",
        "ledger",
        "snapshot",
        "qualification",
        "manifest_sha256",
    ]
    assert normalized_export(manifest) == LEGACY_EXPORT_DIGEST


SOCIETY_RECORD_KINDS = ["commons_node", "commons_claim", "commons_review", "literature_fetch"]


def test_society_export_adds_commons_records_edges_and_fetches(lab):
    from commons_helpers import society_lab

    from physharness.commons_models import NodeCreate
    from physharness.domain import Principal

    service, author, exp, branches, (alpha, beta) = society_lab(lab, models=2)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    lemma = service.create_node(
        exp["id"],
        NodeCreate(
            node_type="lemma",
            title="Trace lemma",
            statement="The trace is additive.",
            edges=[{"relation": "motivated_by", "target_id": goal["id"]}],
        ),
        alpha,
        "lemma",
    )
    service.link_nodes(exp["id"], goal["id"], "depends_on", lemma["id"], alpha, "link")
    service.claim_node(lemma["id"], "claim", beta, "claim")
    requested = service.request_review(lemma["id"], "informal", alpha, "review")
    referee = Principal(
        id="referee",
        role="agent",
        project_id="lab",
        experiment_id=exp["id"],
        branch_id=requested["branch_id"],
    )
    service.submit_review(requested["review_task_id"], "sound", "Checked.", [], referee, "sound")
    service.record_literature_fetch(
        exp["id"],
        {
            "status": "withheld_contamination_risk",
            "url": "https://arxiv.org/abs/2201.00001",
            "sha256": "b" * 64,
            "flag": {"reason": "reference_overlap", "shared": 9, "ratio": 0.3},
        },
        alpha,
        "fetch",
    )
    manifest = service.export_experiment(exp["id"], author)
    records = manifest["records"]
    assert list(records) == LEGACY_RECORD_KINDS + SOCIETY_RECORD_KINDS
    assert {node["id"] for node in records["commons_node"]} == {goal["id"], lemma["id"]}
    assert [(claim["node_id"], claim["branch_id"]) for claim in records["commons_claim"]] == [
        (lemma["id"], branches[1]["id"])
    ]
    [review] = records["commons_review"]
    assert (review["verdict"], review["cross_model"]) == ("sound", True)
    [fetch] = records["literature_fetch"]
    assert fetch["flagged"] is True and fetch["status"] == "withheld_contamination_risk"
    assert sorted(manifest["edges"], key=lambda edge: edge["relation"]) == [
        {"source": goal["id"], "target": lemma["id"], "relation": "depends_on"},
        {"source": lemma["id"], "target": goal["id"], "relation": "motivated_by"},
    ]
    assert list(manifest).index("edges") == list(manifest).index("records") + 1
    assert all(branch.get("lab") for branch in records["branch"] if branch.get("hat") is None)
    # An agent's export shows the commons of its ideas-sharing experiment, and only edges
    # between nodes it can see.
    agent_view = service.export_experiment(exp["id"], alpha)
    assert {node["id"] for node in agent_view["records"]["commons_node"]} == {
        goal["id"],
        lemma["id"],
    }
    assert len(agent_view["edges"]) == 2
