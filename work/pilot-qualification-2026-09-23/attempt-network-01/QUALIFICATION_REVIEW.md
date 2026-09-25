# Scoped verifier deployment review

Deployment approval: pending

Production qualified: false

Mechanical checks: satisfied

The packet identifies observations and remaining gaps. Hash agreement does not authenticate their collector or approve a deployment or scientific target.

```json
{
  "protocol": "physharness-deployment-review-packet-v1",
  "purpose": "deployment_review_packet",
  "scope_sha256": "665d5178f9bcc726135a5912c855b3708d2e1cc9136554367b4989cb311da6db",
  "scope": {
    "protocol": "physharness-qualification-scope-v1",
    "image_metadata": {
      "path": "work/pilot-qualification-2026-09-23/attempt-network-01/image-metadata.json",
      "sha256": "fe7095a9c8a4fdd864925654af0edd03dac7106314bc2bf80c81e26b2a3c9442"
    },
    "runtime_identity": {
      "path": "work/pilot-qualification-2026-09-23/attempt-network-01/runtime-identity.json",
      "sha256": "d521edb22c12100799712b41dfe42e01dfa39c201a1a7c9b2caac398b4e4ff7b"
    },
    "resource_profile_file": {
      "path": "formal/verifier-resources.json",
      "sha256": "c85c68cc4329b1c622c2909b9fd99ea5c029fe04cbed120036d15893d5afc6d4"
    },
    "resources": {
      "protocol": "physharness-verifier-resources-v1",
      "memory_bytes": 8589934592,
      "cpus": 4,
      "comparator_timeout_seconds": 600,
      "comparator_output_limit_bytes": 256000,
      "checker_slots": 1
    },
    "resource_profile_sha256": "c85c68cc4329b1c622c2909b9fd99ea5c029fe04cbed120036d15893d5afc6d4",
    "image_digest": "sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67",
    "launcher_sha256": "16f2800d8ea861adb169dbd9cdc6cf207024d231f1f64d762bef7a2837cb1572",
    "driver_sha256": "cb1b6852f4fbd89f528fed384afcc275c27fbe7f7584c3e74927e151bff8b58f",
    "seccomp_sha256": "23d9ee5086efd262ed745ba824380a76e5a4513fbd3617cd4fac4923a9b04710",
    "checker_versions": {
      "lean": "Lean (version 4.33.0, aarch64-unknown-linux-gnu, commit d8b18978322de05a8f3dba51ef03cf5461676c17, Release)",
      "comparator": "3927ad383f208ae977c340a91c48ac9b497d2097",
      "lean4export": "15f6055e299ad5b89345e533cc2192f4cc00f659",
      "landrun": "811cfff51ceaf3d9843708aa6d22e9b84ccac8b4",
      "nanoda": "4c544ed4099c8227f07d5de77ad1e69fb0740a27"
    },
    "binaries": {
      "lean": "79fb1d26fa5a39385d59fdc48a711a14b0710ca6480271acce99b4d177cea085",
      "lake": "8229bc302b0b7d0e7679e28cc2b830c5aec995ffe5714833503360252f1490ba",
      "comparator": "227f482d9fd760fb7b19646d6f6e1abbed3b1a2b62fc77e4a6bb69d2d7693cab",
      "lean4export": "4bac3563125b296123283eecc7a49dc91a1c30bc41c199113c41c9258b42ef28",
      "landrun": "ff652d627fc822fd5ece4c939446e789cec4ba30814446dabd93234f9bf1615f",
      "nanoda": "9fe6d27927d156dd2f053b644f2665521ef42db71d1db8ddd856d9c238482196"
    },
    "inputs": {
      "formal/Dockerfile": "41b0cdd6b094c55b4b8c58ad7877645a641f897a89fd25926645902e7d8671b6",
      "formal/adversarial/Challenge.lean": "7f006a37e257540de43c94f871aaf25abcdf10bea925aba95c5b82abe71414a2",
      "formal/adversarial/ChangedDependency.lean": "9666a74d27bc06fb9991626b9595908cfe5da46b5d9588004440291bb88c8f90",
      "formal/adversarial/ConfigOverwrite.lean": "d4522f4dc790e31093fe61695093cc74b6c60554b4075ce028655dcce5cdb665",
      "formal/adversarial/DependencyChallenge.lean": "b89f123dd16c1ff8093bb9d37109d1e54cfbd079af93ab4d8e9593215aeec747",
      "formal/adversarial/ExtraAxiom.lean": "2cbf645decd6282725fa417be347ab63284152d0e4a8bc59cbb59e818e4027cf",
      "formal/adversarial/ForgedReceipt.lean": "ad988b0da62e9d2b549f9683f1f175a8386c8393bb1cfe1f50e8004095bba724",
      "formal/adversarial/NativeChallenge.lean": "6b53e795ec932817d7c00ea6f9272c3c7d0cfd9cbdfcad66938b033fef9c5d2a",
      "formal/adversarial/NativeDecide.lean": "c43697602bba926564b7495daff5952498f045ae8d3c851cd0199e078db65ccc",
      "formal/adversarial/Sorry.lean": "7f006a37e257540de43c94f871aaf25abcdf10bea925aba95c5b82abe71414a2",
      "formal/adversarial/TargetOverwrite.lean": "140e7da3ccc03802949f467dbd4926b08bcadae88cfd594548326074996f7e0a",
      "formal/adversarial/cases.json": "d317cbbc7cf16d57c50c63a839b0b50c60ec8a74a7458cf333605f5ebf71754a",
      "formal/adversarial/classical/Challenge.lean": "1b206be36da6d259a7657f8a84df800295ff2f3979beed585c134dce8a30bee0",
      "formal/adversarial/classical/Solution.lean": "bda7c502df00a4f8a99ede6fa04f7ec09cbd3a218048703c02b483b63bea6856",
      "formal/adversarial/lakefile.toml": "2c78e0ccd39805b3336234717f9682bde2359863261858f18f08cf6433c43d16",
      "formal/adversarial/lean-toolchain": "302cd63c54178885b89e669f33b38f12f4dd7ae7e5cac537b3203e3768d8fb2b",
      "formal/adversarial/quantum/Challenge.lean": "3acabdcd3b91a336d513367975589a98b21c53328053f24ef0afc6bbabab4ba9",
      "formal/adversarial/quantum/Solution.lean": "cecd83e75f1baa95f6825a021f7a1cd8bee9a8ab1de11c366972f6cae79bb225",
      "formal/environment.lock.json": "c5615b4f818bb8dfefc0281f116d2ece500597a488eb4ee244b330d41c9235c5",
      "formal/lake-manifest.physics.json": "d57958f7fdca5622cc6dfc82a2920f8714fdc8608149477d9b32831a8e7dfd38",
      "formal/lakefile.physics.toml": "e3557e21d4bd9d2923997d206e44459786a19d348946ad6a833bc668545e7593",
      "formal/lean-toolchain": "302cd63c54178885b89e669f33b38f12f4dd7ae7e5cac537b3203e3768d8fb2b",
      "formal/library-cases.json": "948a6ebb1a7ded60fd4b139bfd2af2f923fa35d4684031ca738e95a443b363e0",
      "formal/prepare_lake.py": "4aff00dfabebcf860e25fa84543356a32be09d8e610276d0d3e4b554eb44c572",
      "formal/qualification-matrix.json": "6ea243a945d2e6b80789874357c19f97d66c8bbd2bdb4ef8e22de8d2878158d8",
      "formal/record_build.py": "0f579a352b1891d6c9ee54f04c063290332da1ca5084d56953a21595fc9c0866",
      "formal/smoke/library-classical/Challenge.lean": "8d48b54c1c79ee3e3190d3f964b25fdacec4fc7d5f83e218d6ad371496fe7c35",
      "formal/smoke/library-classical/Solution.lean": "776ca7e864d14c1148c9aec36d2736dea769ab470acb5ba5f5f94c519a579968",
      "formal/smoke/library-quantum/Challenge.lean": "30f6b8687af64fcec66a1bebc71e2a1671636877af5edaba81f683e934a5c4d4",
      "formal/smoke/library-quantum/Solution.lean": "e9a3089ef19ee93f60504cd91485b60420ac4cab893a7cd476bf8aec9d858b5b",
      "formal/smoke/library-quantum/Sorry.lean": "30f6b8687af64fcec66a1bebc71e2a1671636877af5edaba81f683e934a5c4d4",
      "formal/verifier-resources.json": "c85c68cc4329b1c622c2909b9fd99ea5c029fe04cbed120036d15893d5afc6d4",
      "infra/probe_verifier_boundary.py": "a75e17d30276f818ae724a191cee80c522b0e3125f73c5bc2bfaa75e6e4e723a",
      "infra/run_qualified_lean.py": "bbb512fe4a6f61ee6ed2148c1700a7276ae3101a78ba8095c171813fc909ec22",
      "pyproject.toml": "8a550ace9c68290539f403a255d934032a4d7fdca94b15b9f17027f0d73f54a9",
      "src/physharness/acceptance.py": "521c2ed0672a76389bfab37b2f537af93721ed6a6f3d111b7cc891ac1a733dbb",
      "src/physharness/bootstrap.py": "0b46274b97d17754012800f279166acd618c9fb4aa0c287b1283499c11a590f4",
      "src/physharness/config.py": "37f6c7d6d67c6e74b17e8be6a68e5600a4d324e0a30d3491ec6bb727448df7e4",
      "src/physharness/domain.py": "b2cb2bf480efc3a3cfc22a9b57f9e76dcc049f9dca827f69a6b58871b499b236",
      "src/physharness/evaluation/evidence.py": "8d16ce3e23ca96b0e075499e52ead1b7a84e0d9f8c95673e465972f6e0fc7009",
      "src/physharness/service.py": "1ce8393baa103b7e208c12351b538bf168641ff0325d2f3bd858ab574f92e688",
      "src/physharness/verification/boundary.py": "16f2800d8ea861adb169dbd9cdc6cf207024d231f1f64d762bef7a2837cb1572",
      "src/physharness/verification/bundles.py": "63c18e38940f9a3bddd46f1b663cfa071e1ad503acaf90fab47811a85c54f264",
      "src/physharness/verification/container_driver.py": "cb1b6852f4fbd89f528fed384afcc275c27fbe7f7584c3e74927e151bff8b58f",
      "src/physharness/verification/preparation.py": "c4fae22c5bdb5d060e67b0133b3326fde288edbca923c2e19b0ec84eca4e3488",
      "src/physharness/verification/qualification.py": "17785f5c81149953b8645cefb6e0b39d28b3eb1739eabc873a30fd6927225d70",
      "src/physharness/verification/registry.py": "0663d45118c9d30899da31ab046101a2ae4b99840725bdccb37a4fd203557bd9",
      "src/physharness/verification/resource_policy.py": "10f33fbd312fc8dbdbcdd508f88720a5ead8ec96720645178aaa8946745a02bd",
      "tests/conftest.py": "a65b3fe9e61a134fdcb150c220ee998e8e404f25bc0798ea651d110031ccba3f",
      "tests/test_acceptance_corrections.py": "e2beefa88f5b0bda090544c7d50f9e9c49ebf502eab3d08e8c9ff34adf8f0741",
      "tests/test_acceptance_integration.py": "5ee17f565446e052612f8efddfc48d6574853d9e3f426fe215ca54af32be0f53",
      "tests/test_authority.py": "573f327bbc532b2a6e880a83287a2ddc9e4383225c1da2939eb337ea83b9adc2",
      "tests/test_qualification_diagnostics.py": "bfac292c91d7542a8f6476db41d6226c8d29a6c24151d30ad5be4da66666ae9f",
      "tests/test_research_services.py": "91f5ab9abafeb7e3bbdd04072efab8a7f9be62393e402df585e2931a45647dbb",
      "tests/test_verification.py": "70b749b8d30c20e37929fd976690430aaa2c248d899edcb711bb415778ae1ff8",
      "tests/test_verifier_boundary_probe.py": "659c98aec335f0535dcf7a42ef7cea9c833681ec12544ee6b320d531df84f71d",
      "tests/test_verifier_qualification.py": "f627d3025b59ef5a209a2789b3fa7f490b37286c52b1eee312a8cec8d6ac6a5f",
      "tests/test_verifier_registry.py": "b06942ec251d7d4ccc6feee6c2eec0a153983bcbcc954251560a06ed1bbc1a7e",
      "tests/test_verifier_resource_bootstrap.py": "5b3f0d9d8da7c9096ffbb57eab96d33f74bde8c11b6966029563f79a660089cc",
      "tests/test_verifier_resources.py": "d5f93718c946ba2baacf60c5c4698fc619241ba39f2c44758e6c06a4e72ad2bc",
      "uv.lock": "40decab91eb2895c8ac8cd567569d7fe4ee5f1d0ba1ecab32aabaac54d5801fd"
    }
  },
  "mechanical_status": "satisfied",
  "checks": [
    {
      "id": "current-inputs",
      "status": "observed",
      "detail": "All scoped current input hashes match.",
      "evidence_sha256": null
    },
    {
      "id": "core/kernel",
      "status": "observed",
      "detail": "Exact fixed cases, modes, sources, causal outcomes and cleanup match.",
      "evidence_sha256": "6435c19ce7909e00c74cdb819c681f56829bc0064a55045778b27b3c8c901e97"
    },
    {
      "id": "core/independent_kernel",
      "status": "observed",
      "detail": "Exact fixed cases, modes, sources, causal outcomes and cleanup match.",
      "evidence_sha256": "f2fe732574d6d82e43f325411db581ddcf8ecdc619435448baee53d865e662eb"
    },
    {
      "id": "library/kernel",
      "status": "observed",
      "detail": "Exact fixed cases, modes, sources, causal outcomes and cleanup match.",
      "evidence_sha256": "49e14c4cf5e5e9a54e92df8346f3fe69098dd3a935c3c5c054f7478184aa3609"
    },
    {
      "id": "library/independent_kernel",
      "status": "observed",
      "detail": "Exact fixed cases, modes, sources, causal outcomes and cleanup match.",
      "evidence_sha256": "0d5b4b233b14aa33d7acaa62e5f467cc6ab2f823af58275bec7b4f98b50a9fbe"
    },
    {
      "id": "fixed-boundary",
      "status": "observed",
      "detail": "Fixed process, syscall, canary, writable control, inspected configuration and cleanup observations match.",
      "evidence_sha256": "03f203f8d2091ab1f9599bf7f38ad0dbe10a80efc6fd604c3f504433d71c1aa0"
    },
    {
      "id": "transport-and-isolation",
      "status": "observed",
      "detail": "Required host regressions passed; synthetic transport tests remain distinct from real isolation.",
      "evidence_sha256": "5d4410f78ed4e9dfbd4783dee1a8f8d5d5c2793cf254823dd36791265f296224"
    },
    {
      "id": "authority-and-atomicity",
      "status": "observed",
      "detail": "Required host regressions passed; synthetic transport tests remain distinct from real isolation.",
      "evidence_sha256": "5d4410f78ed4e9dfbd4783dee1a8f8d5d5c2793cf254823dd36791265f296224"
    },
    {
      "id": "evidence-reporting",
      "status": "observed",
      "detail": "Required host regressions passed; synthetic transport tests remain distinct from real isolation.",
      "evidence_sha256": "5d4410f78ed4e9dfbd4783dee1a8f8d5d5c2793cf254823dd36791265f296224"
    },
    {
      "id": "resource-controls",
      "status": "observed",
      "detail": "Required host regressions passed; synthetic transport tests remain distinct from real isolation.",
      "evidence_sha256": "5d4410f78ed4e9dfbd4783dee1a8f8d5d5c2793cf254823dd36791265f296224"
    }
  ],
  "coverage_gaps": [
    {
      "id": "process-exit",
      "reason": "Optional process-exit probe was stopped after a security filter; initializer failed syntax before execution. Remains incomplete and must not be retried in this task."
    },
    {
      "id": "host-containment",
      "reason": "Fixed fixtures and host protocol regressions do not establish complete Landlock/seccomp/kernel isolation or cover every syscall or host resource interaction."
    },
    {
      "id": "runtime-resource-stress",
      "reason": "Host timeout/output-limit regressions do not establish actual cgroup memory, PID, CPU, filesystem exhaustion or all cancellation behavior inside this deployment."
    },
    {
      "id": "database-review-race",
      "reason": "Prior real PostgreSQL locking evidence is historical; this scoped host matrix does not rerun a current deployment database concurrency check."
    },
    {
      "id": "resource-capacity",
      "reason": "Historical 2GiB physics runs had confirmed cgroup OOM kills. New8GiB/4CPU/600s profile requires fresh evidence. One service-UID/shared-tempdir lock is not fleet or VM-wide admission control; root schedules one checker on the12GiB VM."
    }
  ],
  "review_gates": [
    {
      "id": "deployment-authority",
      "reason": "An authorized human must assess the actual runtime, evidence provenance and deployment controls; this module cannot issue approval."
    },
    {
      "id": "scientific-semantics",
      "reason": "Scientific target interpretation and assumptions need their own authorized review; kernel and fixture reports supply no such review."
    },
    {
      "id": "consolidated-rebuild",
      "reason": "Reviewer must verify the consolidated recipe was built and recovered in a fresh environment; old recovery-layer evidence cannot establish this."
    }
  ],
  "production_qualified": false,
  "deployment_approval": "pending",
  "scientific_review": "not_provided",
  "provenance_limit": "Input hashes cannot authenticate reports or grant authority; an authorized human must review their provenance."
}
```
