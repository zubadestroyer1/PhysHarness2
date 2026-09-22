"""Export only reviewed, receipt-backed, administratively licensed canonical records."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from physharness.evaluation.evidence import canonical_digest
from physharness.evaluation.portfolio import Contract, Digest


class DatasetSelection(Contract):
    problem_id: str
    receipt_id: str
    family_id: str = Field(min_length=1)
    split: Literal["train", "development", "holdout"]


class LicenseGrant(Contract):
    """Administrative licensing decision; never inferred from model-written provenance."""

    artifact_sha256: Digest
    license_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    training_allowed: bool


class DatasetRecord(Contract):
    problem_id: str
    target_digest: Digest
    environment_digest: Digest
    family_id: str
    split: Literal["train", "development", "holdout"]
    statement: str
    proof: str
    proof_sha256: Digest
    receipt_id: str
    artifact_id: str
    review_id: str
    license_id: str
    license_approved_by: str
    attribution: str
    checker_versions: dict[str, str]
    assurance: str


class DatasetManifest(Contract):
    schema_version: Literal[1] = 1
    mode: Literal["live", "replay", "synthetic", "unqualified"]
    snapshot_id: str
    snapshot_digest: Digest
    record_count: int
    records_sha256: Digest
    partition_families: dict[str, list[str]]
    license_decisions_digest: Digest
    selection_digest: Digest


class DatasetBundle(Contract):
    manifest: DatasetManifest
    records: list[DatasetRecord]
    output_directory: str


def export_dataset(
    evidence, selections, license_grants, artifact_bytes, output_directory, *, mode="unqualified"
) -> DatasetBundle:
    """Trusted callers supply snapshot records, administrative grants, and artifact bytes.

    Validation is completed before files are written. No receipt or licensing authenticity
    is created by this function; the canonical loader and licensing administrator are trusted.
    """
    grants = {}
    for grant in license_grants:
        if grant.artifact_sha256 in grants:
            raise ValueError("duplicate license decision")
        grants[grant.artifact_sha256] = grant
    families, proofs, targets, identifiers = {}, {}, {}, set()
    records = []
    for selection in selections:
        if selection.problem_id in identifiers:
            raise ValueError("duplicate dataset target")
        identifiers.add(selection.problem_id)
        if selection.family_id in families and families[selection.family_id] != selection.split:
            raise ValueError("family overlap across dataset partitions")
        families[selection.family_id] = selection.split
        checked = evidence.validate(selection.problem_id, selection.receipt_id)
        if not checked.valid:
            raise ValueError(f"invalid canonical receipt: {checked.reason}")
        problem = evidence.record(selection.problem_id)
        receipt = evidence.record(selection.receipt_id)
        grant = grants.get(checked.candidate_sha256)
        if not grant or not grant.training_allowed:
            raise ValueError("approved training license decision is missing")
        source = artifact_bytes.get(checked.candidate_sha256)
        if (
            not isinstance(source, bytes)
            or hashlib.sha256(source).hexdigest() != checked.candidate_sha256
        ):
            raise ValueError("proof content digest mismatch")
        for mapping, key in (
            (proofs, checked.candidate_sha256),
            (targets, problem["target_digest"]),
        ):
            if key in mapping and mapping[key] != selection.split:
                raise ValueError("duplicate target/proof content crosses dataset partitions")
            mapping[key] = selection.split
        records.append(
            DatasetRecord(
                problem_id=selection.problem_id,
                target_digest=problem["target_digest"],
                environment_digest=problem["environment_digest"],
                family_id=selection.family_id,
                split=selection.split,
                statement=problem["formal_statement"],
                proof=source.decode("utf-8"),
                proof_sha256=checked.candidate_sha256,
                receipt_id=selection.receipt_id,
                artifact_id=checked.artifact_id,
                review_id=checked.review_id,
                license_id=grant.license_id,
                license_approved_by=grant.approved_by,
                attribution=grant.attribution,
                checker_versions=receipt["checker_versions"],
                assurance=receipt["assurance"],
            )
        )
    if not records:
        raise ValueError("empty dataset selection")
    records.sort(key=lambda item: item.problem_id)
    raw = b"".join(
        (
            json.dumps(item.model_dump(), sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode()
        for item in records
    )
    manifest = DatasetManifest(
        mode=mode,
        snapshot_id=evidence.snapshot_id,
        snapshot_digest=evidence.snapshot_digest,
        record_count=len(records),
        records_sha256=hashlib.sha256(raw).hexdigest(),
        partition_families={
            split: sorted(family for family, part in families.items() if part == split)
            for split in ("train", "development", "holdout")
        },
        license_decisions_digest=canonical_digest(
            sorted([g.model_dump() for g in license_grants], key=lambda row: row["artifact_sha256"])
        ),
        selection_digest=canonical_digest(
            sorted([s.model_dump() for s in selections], key=lambda row: row["problem_id"])
        ),
    )
    output = Path(output_directory)
    files = {"records.jsonl": raw, "manifest.json": manifest.model_dump_json(indent=2).encode()}
    for name, content in files.items():
        if (output / name).exists() and (output / name).read_bytes() != content:
            raise ValueError("output already contains a different dataset")
    output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = output / name
        path.write_bytes(content)
        path.chmod(0o600)
    return DatasetBundle(manifest=manifest, records=records, output_directory=str(output.resolve()))
