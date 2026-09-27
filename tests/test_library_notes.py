import pytest
from commons_helpers import society_lab

from physharness import library_notes as notes_module
from physharness.domain import new_id
from physharness.errors import HarnessError
from physharness.storage import LibraryNoteRow

S1_DIGEST = "0c46de2450bd5a9b2584d513d3ad02a963a300c3b0e3510a3a22efbc5a11341f"
NOTE = "`Foo.bar` was renamed `Foo.baz` at this pin."


def other_row(project_id, digest, text):
    return LibraryNoteRow(
        id=new_id(),
        project_id=project_id,
        environment_digest=digest,
        experiment_id="x",
        author="branch:x",
        text=text,
        created_at="2026-09-26T00:00:00+00:00",
    )


def test_notes_are_project_and_pin_scoped_idempotent_and_seeded(lab, monkeypatch):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    appended = service.append_library_note(NOTE, alpha, "n1")
    assert service.append_library_note(NOTE, alpha, "n1") == appended
    found = service.library_notes(beta, query="Foo.bar")
    assert [(n["text"], n["author"]) for n in found["notes"]] == [
        (NOTE, f"branch:{alpha.branch_id}")
    ]
    with service.db.transaction() as session:
        session.add(other_row("other-project", found["environment_digest"], "Foo.bar elsewhere"))
        session.add(other_row("lab", "f" * 64, "Foo.bar on another pin"))
    assert [n["text"] for n in service.library_notes(beta, query="Foo.bar")["notes"]] == [NOTE]
    monkeypatch.setattr(notes_module, "seed_notes", lambda digest: ["A seeded fact about Foo.bar."])
    assert (
        service.library_notes(beta, query="Foo.bar")["notes"][0]["author"]
        == notes_module.SEED_AUTHOR
    )
    with pytest.raises(HarnessError) as long:
        service.append_library_note("x" * 2001, alpha, "long")
    assert long.value.code == "INVALID_NOTE"


def test_the_checked_in_seed_covers_the_s1_audit_findings():
    seeded = " ".join(notes_module.seed_notes(S1_DIGEST))
    assert "Matrix.dotProduct" in seeded and "Perron" in seeded and len(seeded) < 3 * 2000


def test_the_seed_holds_library_facts_never_proof_routes():
    """Every project at the pin reads the seed, benchmark arms included, so it must not
    carry an S1 target's proof method (the S1 aperiodic and Doeblin routes)."""
    routes = ("what worked", "coin theorem", "contractingwith")
    for notes in notes_module._seed().values():
        for note in notes:
            assert not [route for route in routes if route in note.casefold()], note
