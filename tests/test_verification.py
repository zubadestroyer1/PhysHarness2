"""Protocol adversaries; synthetic transports do NOT qualify any Lean kernel."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def api():
    from physharness import verification

    assert hasattr(verification, "ComparatorVerifier"), "verification boundary is not implemented"
    return verification


def request(**changes):
    values = dict(
        problem_revision_id="revision-1",
        target_digest=sha(b"target"),
        challenge_sha256=sha(b"target"),
        environment_digest=sha(b"environment"),
        candidate_sha256=sha(b"proof"),
        candidate_source="proof",
        semantic_reviewed=True,
        target_theorem="identity",
    )
    values.update(changes)
    return api().VerificationRequest(**values)


def configured(tmp_path):
    v = api()
    target = b"theorem identity (n : Nat) : n = n := by rfl\n"
    env = json.dumps(
        {
            "image": "sha256:" + "a" * 64,
            "checker_versions": {
                "lean": "v4.34.0",
                "comparator": "v4.34.0",
                "nanoda": "qualified-pin",
            },
            "binaries": {
                name: "e" * 64
                for name in ("lean", "lake", "comparator", "lean4export", "landrun", "nanoda")
            },
            "files": {"lakefile.toml": sha(b'name = "check"\n')},
        }
    ).encode()
    (tmp_path / "Challenge.lean").write_bytes(target)
    (tmp_path / "environment.json").write_bytes(env)
    (tmp_path / "lakefile.toml").write_text('name = "check"\n')
    manifest = json.dumps(
        {
            "protocol": "physharness-comparator-v2",
            "problem_revision_id": "revision-1",
            "challenge_sha256": sha(target),
            "target_digest": sha(target),
            "environment_digest": sha(env),
            "theorem_names": ["identity"],
        }
    ).encode()
    (tmp_path / "manifest.json").write_bytes(manifest)
    config = v.ComparatorConfig(
        bundle_directory=tmp_path,
        manifest_sha256=sha(manifest),
        qualification=v.LinuxQualification(
            image_digest="sha256:" + "a" * 64,
            qualification_report_sha256="b" * 64,
            driver_sha256=v.driver_digest(),
            launcher_sha256=v.launcher_digest(),
            seccomp_sha256=v.seccomp_digest(),
            linux_boundary="docker-landlock-seccomp-v1",
            independent_kernel=True,
        ),
    )
    req = request(
        target_digest=sha(target), challenge_sha256=sha(target), environment_digest=sha(env)
    )
    return v.ComparatorVerifier(config), req


def fake_result(req, **changes):
    result = dict(
        protocol="physharness-comparator-v2",
        status="verified",
        code="kernel_checked",
        target_digest=req.target_digest,
        challenge_sha256=req.challenge_sha256,
        environment_digest=req.environment_digest,
        candidate_sha256=req.candidate_sha256,
        independent_kernel=False,
        axioms=["propext", "Quot.sound", "Classical.choice"],
        checker_versions={"lean": "v4.34.0", "comparator": "v4.34.0", "nanoda": "qualified-pin"},
        diagnostics={"axioms_are_policy_upper_bound": True},
    )
    result.update(changes)
    return result


def test_unavailable_toolchain_is_blocked():
    out = api().UnavailableVerifier().verify(request())
    assert (out.status, out.assurance) == ("blocked", "none")
    assert out.remediation


def test_forged_candidate_digest_rejected():
    out = api().ComparatorVerifier().verify(request(candidate_sha256="0" * 64))
    assert out.code == "candidate_digest_mismatch"
    assert out.status == "rejected"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"semantic_reviewed": False}, "semantic_review_required"),
        ({"definition_holes": True}, "definition_review_required"),
    ],
)
def test_review_is_required(changes, code):
    out = api().ComparatorVerifier().verify(request(**changes))
    assert out.status == "blocked" and out.code == code


def test_missing_configuration_blocks():
    assert api().ComparatorVerifier().verify(request()).code == "verifier_unconfigured"


def test_manifest_or_environment_tamper_blocks(tmp_path):
    verifier, req = configured(tmp_path)
    (tmp_path / "lakefile.toml").write_text("attacker build config")
    assert verifier.verify(req).code == "trusted_bundle_invalid"


def test_wrong_target_revision_blocks(tmp_path):
    verifier, req = configured(tmp_path)
    assert (
        verifier.verify(req.model_copy(update={"problem_revision_id": "another"})).code
        == "trusted_bundle_invalid"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"axioms": ["sorryAx"]},
        {"axioms": ["FalseAxiom"]},
        {"candidate_sha256": "f" * 64},
        {"target_digest": "f" * 64},
        {"challenge_sha256": "f" * 64},
        {"environment_digest": "f" * 64},
        {"status": "banana"},
        {"checker_versions": {"comparator": "worker-says-okay"}},
        {"surprise": True},
    ],
)
def test_adversarial_transport_outcome_fails_closed(tmp_path, monkeypatch, changes):
    verifier, req = configured(tmp_path)
    monkeypatch.setattr(verifier, "_run_container", lambda *args: fake_result(req, **changes))
    out = verifier.verify(req)
    assert out.status in {"blocked", "rejected"} and out.assurance == "none"


def test_publication_requires_independent_kernel(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    req = req.model_copy(update={"publication": True})
    monkeypatch.setattr(verifier, "_run_container", lambda *args: fake_result(req))
    assert verifier.verify(req).code == "independent_kernel_required"


def test_protocol_acceptance_is_explicitly_synthetic(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    monkeypatch.setattr(verifier, "_run_container", lambda *args: fake_result(req))
    out = verifier.verify(req)
    assert out.status == "verified" and out.assurance == "kernel"


def test_incomplete_proof_rejected_by_controlled_checker(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    source = "theorem identity (n : Nat) : n = n := by sorry"
    req = req.model_copy(
        update={"candidate_source": source, "candidate_sha256": sha(source.encode())}
    )
    monkeypatch.setattr(
        verifier,
        "_run_container",
        lambda *args: fake_result(req, status="rejected", code="comparator_failed"),
    )
    assert verifier.verify(req).status == "rejected"


def test_generated_source_never_executes_on_host(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    sentinel = tmp_path / "host-compromised"
    source = f'#eval IO.FS.writeFile "{sentinel}" "owned"'
    req = req.model_copy(
        update={"candidate_source": source, "candidate_sha256": sha(source.encode())}
    )
    from physharness.verification import boundary

    monkeypatch.setattr(boundary.shutil, "which", lambda path: None)
    assert verifier.verify(req).status == "blocked"
    assert not sentinel.exists()


def test_symlink_bundle_file_rejected(tmp_path):
    verifier, req = configured(tmp_path)
    (tmp_path / "lakefile.toml").unlink()
    (tmp_path / "lakefile.toml").symlink_to("/etc/passwd")
    assert verifier.verify(req).code == "trusted_bundle_invalid"


def test_inconsistent_outcome_contract_rejected():
    with pytest.raises(ValidationError):
        api().VerificationOutcome(
            status="blocked",
            assurance="kernel",
            code="bad",
            message="bad",
            remediation="fix",
            target_digest="a" * 64,
            environment_digest="b" * 64,
            candidate_sha256="c" * 64,
        )


def test_trusted_environment_requires_binary_hashes(tmp_path):
    verifier, req = configured(tmp_path)
    env = json.loads((tmp_path / "environment.json").read_bytes())
    env.pop("binaries", None)
    raw = json.dumps(env).encode()
    (tmp_path / "environment.json").write_bytes(raw)
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest["environment_digest"] = sha(raw)
    raw_manifest = json.dumps(manifest).encode()
    (tmp_path / "manifest.json").write_bytes(raw_manifest)
    verifier.config = verifier.config.model_copy(update={"manifest_sha256": sha(raw_manifest)})
    req = req.model_copy(update={"environment_digest": sha(raw)})
    assert verifier.verify(req).code == "trusted_bundle_invalid"


def test_bounded_process_times_out_and_limits_output():
    import sys

    from physharness.verification.boundary import ExecutionFailure, bounded_process

    with pytest.raises(ExecutionFailure, match="checker_timeout"):
        bounded_process([sys.executable, "-c", "import time; time.sleep(3)"], 1, 1024)
    with pytest.raises(ExecutionFailure, match="checker_output_limit"):
        bounded_process([sys.executable, "-c", "print('x' * 8192)"], 2, 1024)


def test_container_flags_and_cleanup_are_enforced(tmp_path, monkeypatch):
    from physharness.verification import boundary

    verifier, req = configured(tmp_path)
    calls = []

    def process(argv, timeout, limit):
        calls.append(argv)
        if "run" in argv:
            assert "--read-only" in argv
            assert "--network=none" in argv
            assert "--cap-drop=ALL" in argv
            assert "--user=65532:65532" in argv
            assert "--pull=never" in argv
            assert "--entrypoint=/usr/bin/python3" in argv
            assert sum("readonly" in item for item in argv) == 2
            return 0, json.dumps(fake_result(req)).encode()
        return 0, b""

    monkeypatch.setattr(boundary.shutil, "which", lambda path: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    assert verifier.verify(req).status == "verified"
    assert calls[-1][1:3] == ["rm", "--force"]


def test_arbitrary_configurable_launcher_is_forbidden():
    with pytest.raises(ValidationError):
        api().ComparatorConfig(
            bundle_directory=Path("/tmp"),
            manifest_sha256="a" * 64,
            qualification=api().LinuxQualification(
                image_digest="sha256:" + "b" * 64,
                qualification_report_sha256="c" * 64,
                driver_sha256="d" * 64,
                launcher_sha256=api().launcher_digest(),
                seccomp_sha256=api().seccomp_digest(),
                linux_boundary="docker-landlock-seccomp-v1",
            ),
            docker_executable="/tmp/fake-success",
        )


def test_seccomp_denies_io_uring_socket_bypass(tmp_path, monkeypatch):
    from physharness.verification import boundary

    verifier, req = configured(tmp_path)

    def process(argv, timeout, limit):
        if "run" in argv:
            profile_path = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("seccomp="))
            policy = json.loads(Path(profile_path).read_bytes())
            denied = {
                name
                for rule in policy["syscalls"]
                if rule["action"] == "SCMP_ACT_ERRNO"
                for name in rule["names"]
            }
            assert {"io_uring_setup", "io_uring_enter", "io_uring_register"} <= denied
            assert "--rm" not in argv
            return 0, json.dumps(fake_result(req)).encode()
        return 0, b""

    monkeypatch.setattr(boundary.shutil, "which", lambda path: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    assert verifier.verify(req).status == "verified"


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_cleanup_failure_blocks_even_after_kernel_success(tmp_path, monkeypatch, failure):
    from physharness.verification import boundary

    verifier, req = configured(tmp_path)

    def process(argv, timeout, limit):
        if "run" in argv:
            return 0, json.dumps(fake_result(req)).encode()
        if failure == "exit":
            return 1, b"daemon unavailable"
        raise boundary.ExecutionFailure("checker_timeout", {"operation": "cleanup"})

    monkeypatch.setattr(boundary.shutil, "which", lambda path: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    result = verifier.verify(req)
    assert result.status == "blocked" and result.code == "container_cleanup_failed"
    assert result.diagnostics["container_name"].startswith("physharness-check-")
    assert result.diagnostics["cleanup"]


@pytest.mark.parametrize("field", ["launcher_sha256", "seccomp_sha256"])
def test_qualification_binds_launcher_and_policy(tmp_path, field):
    verifier, req = configured(tmp_path)
    qualification = verifier.config.qualification.model_copy(update={field: "0" * 64})
    verifier.config = verifier.config.model_copy(update={"qualification": qualification})
    assert verifier.verify(req).code == "trusted_bundle_invalid"


@pytest.mark.parametrize("code", [-9, -15, 137, 143])
def test_signal_terminated_checker_is_blocked(code):
    from physharness.verification import container_driver

    assert hasattr(container_driver, "classify_comparator_exit")
    assert container_driver.classify_comparator_exit(code) == ("blocked", "comparator_terminated")


def test_io_uring_preflight_requires_eperm():
    from physharness.verification import container_driver

    assert hasattr(container_driver, "check_io_uring_denied")

    class UnrestrictedSyscalls:
        def syscall(self, *args):
            return -1

    with pytest.raises(RuntimeError, match="io_uring"):
        container_driver.check_io_uring_denied(UnrestrictedSyscalls())


def test_private_umask_still_allows_nonroot_container_to_read_inputs(tmp_path, monkeypatch):
    import os

    from physharness.verification import boundary

    verifier, req = configured(tmp_path)

    def process(argv, timeout, limit):
        if "run" in argv:
            mounts = [arg for arg in argv if arg.startswith("type=bind,")]
            for mount in mounts:
                root = Path(
                    next(part[7:] for part in mount.split(",") if part.startswith("source="))
                )
                assert root.stat().st_mode & 0o005 == 0o005
                for item in root.rglob("*"):
                    if item.is_dir():
                        assert item.stat().st_mode & 0o005 == 0o005
                    else:
                        assert item.stat().st_mode & 0o004
                assert root.parent.stat().st_mode & 0o077 == 0
            return 0, json.dumps(fake_result(req)).encode()
        return 0, b""

    monkeypatch.setattr(boundary.shutil, "which", lambda path: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    previous = os.umask(0o077)
    try:
        assert verifier.verify(req).status == "verified"
    finally:
        os.umask(previous)


def test_io_uring_preflight_checks_all_three_denials():
    import ctypes
    import errno

    from physharness.verification import container_driver

    assert hasattr(container_driver, "check_io_uring_denied")
    calls = []

    class DeniedSyscalls:
        def syscall(self, number, *args):
            calls.append(number)
            ctypes.set_errno(errno.EPERM)
            return -1

    container_driver.check_io_uring_denied(DeniedSyscalls())
    assert calls == [425, 426, 427]


def test_ambiguous_positive_checker_exit_is_not_mathematical_rejection():
    from physharness.verification import container_driver

    assert hasattr(container_driver, "classify_comparator_exit")
    assert container_driver.classify_comparator_exit(1) == ("blocked", "comparator_failed")


@pytest.mark.parametrize("run_code", [0, 125])
def test_confirmed_absence_is_successful_cleanup(tmp_path, monkeypatch, run_code):
    from physharness.verification import boundary

    verifier, req = configured(tmp_path)

    def process(argv, timeout, limit):
        if "run" in argv:
            return run_code, json.dumps(fake_result(req)).encode()
        if "rm" in argv:
            return 1, b"already removed"
        if "ls" in argv:
            return 0, b""
        raise AssertionError(argv)

    monkeypatch.setattr(boundary.shutil, "which", lambda path: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    result = verifier.verify(req)
    assert result.code == ("kernel_checked" if run_code == 0 else "container_failed")


def test_cleanup_failure_retains_original_timeout(tmp_path, monkeypatch):
    from physharness.verification import boundary

    verifier, req = configured(tmp_path)

    def process(argv, timeout, limit):
        if "run" in argv:
            raise boundary.ExecutionFailure("checker_timeout", {"timeout_seconds": 120})
        return 1, b"daemon unavailable"

    monkeypatch.setattr(boundary.shutil, "which", lambda path: "/usr/bin/docker")
    monkeypatch.setattr(boundary, "bounded_process", process)
    result = verifier.verify(req)
    assert result.code == "container_cleanup_failed"
    assert result.diagnostics["prior_failure"]["code"] == "checker_timeout"


def test_canonical_revision_digest_is_separate_from_lean_source_pin(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    canonical = sha(b'{"semantic_revision":"approved physics target"}')
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest.update(
        protocol="physharness-comparator-v2",
        target_digest=canonical,
        challenge_sha256=sha((tmp_path / "Challenge.lean").read_bytes()),
    )
    raw = json.dumps(manifest).encode()
    (tmp_path / "manifest.json").write_bytes(raw)
    verifier.config = verifier.config.model_copy(update={"manifest_sha256": sha(raw)})
    req = req.model_copy(
        update={"target_digest": canonical, "challenge_sha256": manifest["challenge_sha256"]}
    )
    monkeypatch.setattr(
        verifier,
        "_run_container",
        lambda *args: fake_result(
            req, protocol="physharness-comparator-v2", challenge_sha256=req.challenge_sha256
        ),
    )
    result = verifier.verify(req)
    assert result.status == "verified"
    assert result.target_digest == canonical
    assert result.challenge_sha256 == manifest["challenge_sha256"]


def test_bundle_builder_preserves_scientific_revision_and_independent_source_identity(tmp_path):
    v = api()
    assert hasattr(v, "create_bundle"), "trusted bundle builder missing"
    source = "theorem identity (n : Nat) : n = n := by rfl\n"
    destination = tmp_path / "bundle"
    manifest_sha = v.create_bundle(
        destination,
        problem_revision_id="reviewed-revision",
        target_digest="c" * 64,
        challenge_source=source,
        theorem_names=["identity"],
        image_digest="sha256:" + "a" * 64,
        checker_versions={"lean": "pinned", "comparator": "pinned"},
        binaries={
            name: "e" * 64 for name in ("lean", "lake", "comparator", "lean4export", "landrun")
        },
        project_files={"lakefile.toml": b'name = "check"\n'},
    )
    manifest = json.loads((destination / "manifest.json").read_bytes())
    assert sha((destination / "manifest.json").read_bytes()) == manifest_sha
    assert manifest["target_digest"] == "c" * 64
    assert manifest["challenge_sha256"] == sha(source.encode())
    assert "semantic_reviewed" not in manifest
    with pytest.raises(FileExistsError):
        v.create_bundle(
            destination,
            problem_revision_id="revision",
            target_digest="c" * 64,
            challenge_source=source,
            theorem_names=["identity"],
            image_digest="sha256:" + "a" * 64,
            checker_versions={},
            binaries={},
            project_files={},
        )


def test_engineering_check_does_not_require_or_manufacture_a_review(tmp_path, monkeypatch):
    v = api()
    assert hasattr(v, "EngineeringVerifier"), "engineering observations need a separate API"
    production, req = configured(tmp_path)
    engineering = v.EngineeringVerifier(
        v.EngineeringConfig(
            bundle_directory=tmp_path,
            manifest_sha256=production.config.manifest_sha256,
            execution=v.ExecutionPins.model_validate(
                production.config.qualification.model_dump(exclude={"qualification_report_sha256"})
            ),
        )
    )
    engineering_req = v.EngineeringRequest.model_validate(
        req.model_dump(exclude={"semantic_reviewed", "definition_holes", "target_theorem"})
    )
    monkeypatch.setattr(engineering, "_run_container", lambda *args: fake_result(req))
    result = engineering.run(engineering_req)
    assert result.purpose == "engineering_smoke"
    assert result.outcome.status == "verified"
    assert not hasattr(engineering, "verify")
    with pytest.raises(ValidationError):
        v.VerificationOutcome.model_validate(result.model_dump())
    with pytest.raises(TypeError):
        v.ComparatorVerifier(engineering.config)


def test_preflight_inspects_real_bundle_without_running_candidate(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    assert hasattr(verifier, "preflight"), "deployment preflight missing"

    def forbidden(*args):
        raise AssertionError("Preflight must not run any candidate")

    monkeypatch.setattr(verifier, "_run_container", forbidden)
    result = verifier.preflight(req)
    assert (result.status, result.assurance, result.code) == (
        "blocked",
        "none",
        "configured_unprobed",
    )
    (tmp_path / "Challenge.lean").write_text("changed")
    assert verifier.preflight(req).code == "trusted_bundle_invalid"


@pytest.mark.parametrize("name", ["../outside", ".lake/cache", "config.json", "nested/../escape"])
def test_bundle_builder_rejects_paths_before_writing_anything(tmp_path, name):
    v = api()
    destination = tmp_path / "bundle"
    with pytest.raises(ValueError):
        v.create_bundle(
            destination,
            problem_revision_id="revision",
            target_digest="c" * 64,
            challenge_source="theorem good : True := by trivial",
            theorem_names=["good"],
            image_digest="sha256:" + "a" * 64,
            checker_versions={"lean": "pinned", "comparator": "pinned"},
            binaries={
                n: "e" * 64 for n in ("lean", "lake", "comparator", "lean4export", "landrun")
            },
            project_files={"lakefile.toml": b'name = "check"', name: b"bad"},
        )
    assert not destination.exists()


def test_old_manifest_cannot_be_silently_reinterpreted(tmp_path):
    verifier, req = configured(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest.pop("protocol")
    manifest.pop("challenge_sha256")
    raw = json.dumps(manifest).encode()
    (tmp_path / "manifest.json").write_bytes(raw)
    verifier.config = verifier.config.model_copy(update={"manifest_sha256": sha(raw)})
    result = verifier.verify(req)
    assert result.code == "trusted_bundle_invalid"
    assert "protocol" in result.diagnostics["error"]


def test_reviewed_theorem_selector_cannot_be_replaced_by_bundle_operator(tmp_path, monkeypatch):
    verifier, req = configured(tmp_path)
    req = req.model_copy(update={"target_theorem": "important_unproved_theorem"})
    monkeypatch.setattr(verifier, "_run_container", lambda *args: fake_result(req))
    result = verifier.verify(req)
    assert result.code == "trusted_bundle_invalid"
    assert "theorem" in result.diagnostics["error"]


def test_publication_preflight_blocks_missing_independent_replay_configuration(tmp_path):
    verifier, req = configured(tmp_path)
    verifier.config = verifier.config.model_copy(
        update={
            "qualification": verifier.config.qualification.model_copy(
                update={"independent_kernel": False}
            )
        }
    )
    result = verifier.preflight(req.model_copy(update={"publication": True}))
    assert (result.status, result.code) == ("blocked", "independent_kernel_required")
