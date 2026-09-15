import importlib.util
from collections import Counter
from pathlib import Path

import pytest


def registry():
    assert importlib.util.find_spec("physharness.science"), "science is not implemented"
    from physharness.science import load_benchmarks

    return load_benchmarks(Path(__file__).resolve().parents[1] / "benchmarks" / "registry.json")


def test_registry_has_honest_complete_candidate_and_attack_coverage():
    r = registry()
    counts = Counter((t.program, t.kind) for t in r.tasks)
    assert counts == {
        ("quantum", "candidate"): 20,
        ("classical", "candidate"): 20,
        ("quantum", "altered"): 10,
        ("classical", "altered"): 10,
    }
    assert len({t.id for t in r.tasks}) == 60
    assert all(t.review_status == "pending" and t.compiler_status == "not_run" for t in r.tasks)
    assert all(t.provenance_uri and t.reference_rationale and t.target_source for t in r.tasks)


def test_family_split_keeps_variants_and_attacks_out_of_other_split():
    r = registry()
    families = {}
    for task in r.tasks:
        families.setdefault(task.family, set()).add(task.split)
    assert all(len(splits) == 1 for splits in families.values())
    assert {t.split for t in r.tasks} == {"development", "holdout"}
    by_id = {t.id: t for t in r.tasks}
    for task in r.tasks:
        if task.kind == "altered":
            assert by_id[task.altered_from].family == task.family


def test_unreviewed_uncompiled_registry_cannot_qualify():
    r = registry()
    with pytest.raises(Exception) as err:
        r.require_qualified()
    assert err.value.code == "benchmark_qualification_pending"
    assert err.value.details["pending_count"] == 60


def test_discovery_export_omits_reference_solutions_and_outcomes():
    tasks = registry().discovery_tasks("holdout")
    assert tasks
    assert all(
        "candidate_source" not in task and "reference_expectation" not in task for task in tasks
    )
    assert all(task["split"] == "holdout" for task in tasks)


def test_registry_rejects_family_leakage_and_fake_qualification_without_evidence():
    r = registry()
    cls = type(r)
    data = r.model_dump()
    data["tasks"][0]["split"] = "holdout"
    with pytest.raises(ValueError):
        cls.model_validate(data)
    data = r.model_dump()
    for task in data["tasks"]:
        task.update(review_status="approved", compiler_status="passed")
    with pytest.raises(Exception) as err:
        cls.model_validate(data).require_qualified()
    assert err.value.code == "benchmark_qualification_pending"


def test_provenance_digest_matches_the_original_local_source():
    import hashlib

    r = registry()
    root = Path(__file__).resolve().parents[1]
    for task in r.tasks:
        content = (root / task.provenance_uri).read_bytes()
        assert hashlib.sha256(content).hexdigest() == task.provenance_sha256
        assert task.provenance_end_line <= len(content.decode().splitlines())
