"""Lossless text ingestion. Source material is data and is never executed."""

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from physharness.errors import HarnessError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceDocument(Record):
    uri: str = Field(min_length=1, max_length=4096)
    revision: str = Field(min_length=1, max_length=256)
    format: Literal["markdown", "latex"]
    text: str = Field(min_length=1, max_length=2_000_000)
    content_sha256: Digest

    @model_validator(mode="after")
    def check_content(self):
        if sha(self.text) != self.content_sha256:
            raise ValueError("source document digest mismatch")
        return self


class SourceSpan(Record):
    source_uri: str
    source_revision: str
    document_sha256: Digest
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: str = Field(min_length=1)
    text_sha256: Digest

    @model_validator(mode="after")
    def check_span(self):
        if self.end - self.start != len(self.text) or self.end_line < self.start_line:
            raise ValueError("invalid source span offsets")
        if sha(self.text) != self.text_sha256:
            raise ValueError("source span text digest mismatch")
        return self


class IngestedSource(Record):
    document: SourceDocument
    spans: list[SourceSpan]

    @model_validator(mode="after")
    def bind_spans(self):
        position = 0
        line = 1
        for span in self.spans:
            doc = self.document
            if (
                span.start != position
                or span.document_sha256 != doc.content_sha256
                or span.source_uri != doc.uri
                or span.source_revision != doc.revision
                or span.text != doc.text[span.start : span.end]
                or span.start_line != line
                or span.end_line != line + span.text[:-1].count("\n")
            ):
                raise ValueError("span does not bind to the original source")
            position = span.end
            line += span.text.count("\n")
        if position != len(self.document.text):
            raise ValueError("source spans must cover the original text exactly")
        return self


def ingest_text(
    text: str, *, format: str, uri: str, revision: str, chunk_chars: int = 2000
) -> IngestedSource:
    if format not in {"markdown", "latex"}:
        raise HarnessError(
            "unsupported_source_format",
            "Only Markdown and LaTeX text are supported.",
            remediation="Submit UTF-8 Markdown or LaTeX text.",
        )
    if not isinstance(text, str) or not text or len(text) > 2_000_000:
        raise HarnessError("source_limit", "Source must contain 1–2000000 characters.")
    if type(chunk_chars) is not int or not 1 <= chunk_chars <= 100_000:
        raise HarnessError("source_limit", "chunk_chars must be an integer from 1 to 100000.")
    if (len(text) + chunk_chars - 1) // chunk_chars > 20_000:
        raise HarnessError(
            "source_limit",
            "Source would produce more than 20000 spans.",
            remediation="Increase chunk_chars or split the source document.",
        )
    try:
        content_sha = sha(text)
    except UnicodeEncodeError as exc:
        raise HarnessError(
            "invalid_source_encoding",
            "Source contains invalid Unicode.",
            remediation="Submit valid UTF-8 source text.",
        ) from exc
    doc = SourceDocument(
        uri=uri, revision=revision, format=format, text=text, content_sha256=content_sha
    )
    spans = []
    line = 1
    for start in range(0, len(text), chunk_chars):
        end = min(len(text), start + chunk_chars)
        part = text[start:end]
        spans.append(
            SourceSpan(
                source_uri=uri,
                source_revision=revision,
                document_sha256=content_sha,
                start=start,
                end=end,
                start_line=line,
                end_line=line + part[:-1].count("\n"),
                text=part,
                text_sha256=sha(part),
            )
        )
        line += part.count("\n")
    return IngestedSource(document=doc, spans=spans)


def ingest_bytes(
    content: bytes, *, format: str, uri: str, revision: str, chunk_chars: int = 2000
) -> IngestedSource:
    if format == "pdf":
        raise HarnessError(
            "pdf_ingestion_unavailable",
            "PDF extraction is not provisioned.",
            remediation="Extract UTF-8 text with a reviewed PDF tool; "
            "retain the PDF digest and pages.",
        )
    if len(content) > 8_000_000:
        raise HarnessError("source_limit", "Encoded source exceeds 8000000 bytes.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessError(
            "invalid_source_encoding",
            "Source is not UTF-8.",
            remediation="Decode the original source and submit valid UTF-8.",
        ) from exc
    return ingest_text(text, format=format, uri=uri, revision=revision, chunk_chars=chunk_chars)


class SourceCorrespondence(Record):
    problem_revision_id: str = Field(min_length=1)
    target_digest: Digest
    source_span: SourceSpan
    interpretation: str = Field(min_length=1, max_length=100_000)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    review_status: Literal["pending"] = "pending"


class FailedApproach(Record):
    problem_revision_id: str = Field(min_length=1)
    environment_digest: Digest
    method: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    artifact_sha256: Digest
    evidence_kind: Literal["failed_approach"] = "failed_approach"
