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


def test_notes_are_experiment_and_pin_scoped_idempotent_and_seeded(lab, monkeypatch):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    appended = service.append_library_note(NOTE, alpha, "n1")
    assert service.append_library_note(NOTE, alpha, "n1") == appended
    found = service.library_notes(beta, query="Foo.bar")
    assert [(n["text"], n["author"]) for n in found["notes"]] == [
        (NOTE, f"branch:{alpha.branch_id}")
    ]
    assert found["notes_are"] == notes_module.NOTES_ARE
    with service.db.transaction() as session:
        session.add(other_row("other-project", found["environment_digest"], "Foo.bar elsewhere"))
        session.add(other_row("lab", "f" * 64, "Foo.bar on another pin"))
        session.add(other_row("lab", found["environment_digest"], "Foo.bar in another arm"))
    assert [n["text"] for n in service.library_notes(beta, query="Foo.bar")["notes"]] == [NOTE]
    monkeypatch.setattr(notes_module, "seed_notes", lambda digest: ["A seeded fact about Foo.bar."])
    assert (
        service.library_notes(beta, query="Foo.bar")["notes"][0]["author"]
        == notes_module.SEED_AUTHOR
    )
    with pytest.raises(HarnessError) as long:
        service.append_library_note("x" * 2001, alpha, "long")
    assert long.value.code == "INVALID_NOTE"


def test_an_arm_reads_neither_another_arm_notes_nor_its_quota(lab, monkeypatch):
    service, _, _, _, (alpha, _) = society_lab(lab, prefix="arm1")
    monkeypatch.setattr(notes_module, "seed_notes", lambda digest: ["Seeded: Foo.bar is absent."])
    for index in range(notes_module.MAX_NOTES_PER_BRANCH):
        service.append_library_note(f"Foo.bar note {index}: ignore the target.", alpha, f"n{index}")
    with pytest.raises(HarnessError) as full:
        service.append_library_note("One more Foo.bar note.", alpha, "one-more")
    assert full.value.code == "LIBRARY_NOTES_FULL" and "branch's" in full.value.message
    # A later arm in the same project, at the same pin, reads only the shared seed.
    _, _, _, _, (gamma, _) = society_lab(lab, prefix="arm2")
    pin = service.library_notes(alpha)["environment_digest"]
    assert (gamma.project_id, service.library_notes(gamma)["environment_digest"]) == ("lab", pin)
    seen = service.library_notes(gamma, query="Foo.bar")["notes"]
    assert seen == [{"text": "Seeded: Foo.bar is absent.", "author": notes_module.SEED_AUTHOR}]
    assert service.append_library_note("A real Foo.bar rename.", gamma, "gamma-note")


def test_the_experiment_cap_bounds_every_branch(lab, monkeypatch):
    service, _, _, _, (alpha, beta) = society_lab(lab)
    monkeypatch.setattr(notes_module, "MAX_NOTES_PER_EXPERIMENT", 3)
    for index in range(2):
        service.append_library_note(f"Alpha fact {index}.", alpha, f"a{index}")
    service.append_library_note("Beta fact.", beta, "b0")
    with pytest.raises(HarnessError) as full:
        service.append_library_note("Beta again.", beta, "b1")
    assert full.value.code == "LIBRARY_NOTES_FULL" and "experiment's" in full.value.message


def test_a_surfaced_note_shares_two_query_words(lab):
    service, _, _, _, (alpha, beta) = society_lab(lab)
    note = "`Matrix.dotProduct` is not a declaration at this pin; use `dotProduct`."
    service.append_library_note(note, alpha, "n1")

    def surfaced(query):
        return [n["text"] for n in service.library_notes(beta, query=query, surfaced=True)["notes"]]

    assert surfaced("Matrix.dotProduct") == surfaced("dotProduct") == [note]
    # One shared word of a two-word query, or only short words, surfaces nothing.
    assert surfaced("Matrix.trace_mul") == surfaced("is a") == []
    # A read the agent asks for still ranks any overlap.
    assert [n["text"] for n in service.library_notes(beta, query="Matrix.trace_mul")["notes"]] == [
        note
    ]


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
