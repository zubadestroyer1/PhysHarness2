"""Benchmark literature screen: blocklist parsing, work identities, title matching, the
probing oracle, bounded transport and politeness. Mocked transports only; no network."""

import gzip
import json
import logging
import threading
import zlib

import httpx
import pytest
from commons_helpers import society_lab
from test_literature import REFERENCE, FakeTransport, ok, openalex_work, policy

from physharness.domain import LiteraturePolicy, Principal
from physharness.errors import HarnessError
from physharness.knowledge import literature
from physharness.knowledge.literature import (
    ARXIV_API,
    MAX_FETCH_BYTES,
    OPENALEX_API,
    HostLimiter,
    LiteratureBroker,
    classify_blocked_source,
    normalize_title,
    usable_reference,
)

EMPTY_FEED = b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
PDF = "https://arxiv.org/pdf/2101.00001v2"
HTML = "https://arxiv.org/html/2101.00001v2"
CITING_ARXIV = "https://mathoverflow.net/questions/1/q"
CITING_DOI = "https://math.stackexchange.com/questions/2/q"
JOURNAL_DOI = "10.1103/PhysRevX.11.011001"


def code_of(call):
    with pytest.raises(HarnessError) as caught:
        call()
    return caught.value.code


def atom(*entries):
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">'
        + "".join(entries)
        + "</feed>"
    ).encode()


def entry(arxiv_id, title, abstract="We prove it.", extra=""):
    return (
        f"<entry><id>http://arxiv.org/abs/{arxiv_id}</id><title>{title}</title>"
        f"<summary>{abstract}</summary><published>2021-01-01T00:00:00Z</published>"
        f"<author><name>A. Author</name></author>{extra}</entry>"
    )


def search_transport(arxiv=EMPTY_FEED, works=(), pages=None):
    routes = {
        ARXIV_API: ok(arxiv, "application/atom+xml"),
        OPENALEX_API: ok(json.dumps({"results": list(works)}).encode(), "application/json"),
    }
    for url, text in (pages or {}).items():
        routes[url] = ok(text.encode())
    return FakeTransport(routes)


def benchmark(blocked, transport):
    return LiteratureBroker(
        policy("benchmark", blocked), transport=transport, reference_text=REFERENCE
    )


def ids(result):
    return [item["id"] for item in result["items"]]


# Defect 1: every common spelling of an identifier blocks the work ---------------------------

ARXIV_SPELLINGS = [
    "2101.00001",
    "arXiv:2101.00001",
    "arXiv: 2101.00001",
    "arxiv 2101.00001",
    "arXiv:2101.00001v2 [math-ph]",
    "2101.00001v3",
    "arxiv.org/abs/2101.00001",
    "https://arxiv.org/abs/2101.00001v1",
    "http://arxiv.org/pdf/2101.00001v2.pdf",
    "https://arxiv.org/html/2101.00001v2/",
    "https://export.arxiv.org/abs/2101.00001",
    "10.48550/arXiv.2101.00001",
    "https://doi.org/10.48550/arXiv.2101.00001",
    "oai:arXiv.org:2101.00001",
]


@pytest.mark.parametrize("entry_text", ARXIV_SPELLINGS)
def test_every_arxiv_spelling_blocks_the_paper_and_citing_pages(entry_text):
    pages = {CITING_ARXIV: "<p>See arXiv:2101.00001 for the answer.</p>"}
    transport = search_transport(pages=pages)
    broker = benchmark([entry_text], transport)
    assert classify_blocked_source(entry_text) == ("arxiv", "2101.00001")
    for url in (PDF, HTML, "https://arxiv.org/abs/2101.00001"):
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url
    assert transport.calls == []
    assert broker.fetch(CITING_ARXIV)["status"] == "withheld_contamination_risk"


DOI_SPELLINGS = [
    JOURNAL_DOI,
    "10.1103/physrevx.11.011001",
    "DOI: 10.1103/PhysRevX.11.011001",
    "doi:10.1103/PhysRevX.11.011001",
    "doi 10.1103/PhysRevX.11.011001",
    "doi.org/10.1103/PhysRevX.11.011001",
    "https://doi.org/10.1103/PhysRevX.11.011001",
    "http://dx.doi.org/10.1103/PhysRevX.11.011001",
    "https://www.doi.org/10.1103%2FPhysRevX.11.011001",
]


@pytest.mark.parametrize("entry_text", DOI_SPELLINGS)
def test_every_doi_spelling_blocks_citing_pages_and_search_results(entry_text):
    pages = {CITING_DOI: "<p>Published as doi 10.1103/physrevx.11.011001, see there.</p>"}
    works = [openalex_work("W1", "Journal version", doi=f"https://doi.org/{JOURNAL_DOI}")]
    broker = benchmark([entry_text], search_transport(works=works, pages=pages))
    assert classify_blocked_source(entry_text) == ("doi", JOURNAL_DOI.lower())
    assert broker.fetch(CITING_DOI)["status"] == "withheld_contamination_risk"
    assert broker.search("gap")["items"] == []


def test_old_style_arxiv_ids_ignore_subject_class_and_version():
    for text in ("math-ph/0601001", "arXiv:math-ph/0601001v2", "arxiv.org/abs/math-ph/0601001"):
        assert classify_blocked_source(text) == ("arxiv", "math-ph/0601001"), text
    assert classify_blocked_source("math.AP/0601001") == ("arxiv", "math/0601001")
    pages = {
        CITING_ARXIV: "<p>Compare math-ph/0601001v3.</p>",
        CITING_DOI: "<p>Compare hep-th/0601001 and math-ph/06010012.</p>",
    }
    transport = search_transport(pages=pages)
    broker = benchmark(["arXiv:math-ph/0601001"], transport)
    url = "https://arxiv.org/pdf/math-ph/0601001v1"
    assert code_of(lambda: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED"
    assert broker.fetch(CITING_ARXIV)["status"] == "withheld_contamination_risk"
    assert broker.fetch(CITING_DOI)["status"] == "ok"


def test_openalex_ids_url_and_domain_entries_are_classified():
    for text in ("W3120000001", "openalex:W3120000001", "https://openalex.org/W3120000001"):
        assert classify_blocked_source(text) == ("openalex", "w3120000001"), text
    assert classify_blocked_source("https://en.wikipedia.org/wiki/Mass_gap") == (
        "url",
        "en.wikipedia.org/wiki/mass_gap",
    )
    assert classify_blocked_source("journals.aps.org") == ("domain", "journals.aps.org")
    assert classify_blocked_source("  Yang–Mills existence and mass gap ") == (
        "title",
        "yang mills existence and mass gap",
    )


JUNK = [
    "",
    "   ",
    "TODO",
    "x",
    "arXiv:21O1.00001",
    "arXiv: see paper",
    "doi: nonsense",
    "10.1103",
    "PhysRevX.11.011001",
    "https://",
    "openalex:",
    "ftp://arxiv.org/abs/2101.00001",
]


@pytest.mark.parametrize("junk", JUNK)
def test_unclassifiable_blocklist_entries_are_rejected(junk):
    with pytest.raises(ValueError):
        classify_blocked_source(junk)
    assert code_of(lambda: benchmark(["2101.00001", junk], FakeTransport({}))) == (
        "LITERATURE_POLICY_INVALID"
    )


def test_run_plan_rejects_unclassifiable_blocklist_entries():
    from pydantic import ValidationError
    from test_run_control import SOCIETY, society_plan

    from physharness.run_control import RunPlan

    literature = {"mode": "open", "blocked_sources": ["arXiv:2101.00001", "doi: nonsense"]}
    with pytest.raises(ValidationError, match=r"blocked_sources\[1\]"):
        RunPlan.model_validate(society_plan(society={**SOCIETY, "literature": literature}))
    literature["blocked_sources"] = ["arXiv: 2101.00001", "DOI: 10.1103/PhysRevX.11.011001"]
    RunPlan.model_validate(society_plan(society={**SOCIETY, "literature": literature}))


# Defect 2: every identity of a work -------------------------------------------------------


def merged_work(**extra):
    """The published version: journal DOI and landing page first, the arXiv copy elsewhere."""
    return {
        **openalex_work(
            "W3120000001",
            "Journal version",
            doi=f"https://doi.org/{JOURNAL_DOI}",
            landing="https://journals.aps.org/prx/abstract/10.1103/PhysRevX.11.011001",
            index={"the": [0], "answer": [1], "is": [2], "known": [3]},
        ),
        **extra,
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"locations": [{"landing_page_url": "https://arxiv.org/abs/2101.00001v2"}]},
        {"best_oa_location": {"pdf_url": "https://arxiv.org/pdf/2101.00001v2"}},
        {"locations": [{"id": "pmh:oai:arXiv.org:2101.00001", "landing_page_url": None}]},
        {"ids": {"doi": "https://doi.org/10.48550/arXiv.2101.00001"}},
    ],
)
def test_arxiv_blocklist_drops_published_version_found_through_any_location(extra):
    broker = benchmark(["arXiv:2101.00001"], search_transport(works=[merged_work(**extra)]))
    assert broker.search("gap")["items"] == []


def test_openalex_id_blocklist_drops_the_work():
    for text in ("W3120000001", "https://openalex.org/W3120000001"):
        broker = benchmark([text], search_transport(works=[merged_work()]))
        assert broker.search("gap")["items"] == [], text
    broker = benchmark(["W3120000001"], search_transport(works=[merged_work()]))
    assert code_of(lambda: broker.fetch("https://openalex.org/W3120000001")) == (
        "LITERATURE_SOURCE_BLOCKED"
    )


def test_doi_blocklist_drops_arxiv_entries_naming_the_doi():
    feeds = [
        atom(entry("2101.00001v2", "Preprint", extra=f"<arxiv:doi>{JOURNAL_DOI}</arxiv:doi>")),
        atom(
            entry(
                "2101.00001v2",
                "Preprint",
                extra=f'<link title="doi" href="http://dx.doi.org/{JOURNAL_DOI}" rel="related"/>',
            )
        ),
    ]
    for feed in feeds:
        broker = benchmark([JOURNAL_DOI], search_transport(arxiv=feed))
        assert broker.search("gap")["items"] == []


def test_journal_ref_is_screened_by_title_fragments():
    feed = atom(
        entry(
            "2101.00001v2",
            "Preprint",
            extra="<arxiv:journal_ref>Phys. Rev. X 11, 011001 (2021)</arxiv:journal_ref>",
        )
    )
    broker = benchmark(["Phys. Rev. X 11, 011001"], search_transport(arxiv=feed))
    assert broker.search("gap")["items"] == []


def test_identities_learned_from_search_block_later_fetches():
    """A DOI-only blocklist learns the arXiv copy from the published version's locations."""
    work = merged_work(locations=[{"landing_page_url": "https://arxiv.org/abs/2101.00001v2"}])
    pages = {CITING_ARXIV: "<p>See arXiv:2101.00001.</p>"}
    transport = search_transport(works=[work], pages=pages)
    broker = benchmark([JOURNAL_DOI], transport)
    assert broker.search("gap")["items"] == []
    assert code_of(lambda: broker.fetch(HTML)) == "LITERATURE_SOURCE_BLOCKED"
    assert broker.fetch(CITING_ARXIV)["status"] == "withheld_contamination_risk"
    assert [call["url"] for call in transport.calls] == [ARXIV_API, OPENALEX_API, CITING_ARXIV]


def test_unrelated_works_sharing_a_host_are_not_merged():
    works = [
        openalex_work("W1", "First", landing="https://journals.aps.org/prx/abstract/1"),
        openalex_work("W2", "Second", landing="https://journals.aps.org/prx/abstract/2"),
    ]
    result = LiteratureBroker(policy(), transport=search_transport(works=works)).search("gap")
    assert ids(result) == ["W1", "W2"]
    assert set(result["items"][0]) == {
        "source",
        "id",
        "title",
        "authors",
        "year",
        "url",
        "doi",
        "abstract",
    }


# Defect 3: title fragments are normalized and applied to titles, abstracts and text ------

TITLE_CASES = [
    ("Schrödinger operators with a gap", 'Schr\\"odinger operators with a gap'),
    ("Schrödinger operators with a gap", 'Schr\\"{o}dinger operators with a gap'),
    ("Tsirelson's bound is tight", "Tsirelson’s bound is tight"),
    ("sum-of-squares proof of X", "Sum–of–squares proof of X"),
    ("ground  state energy", "Ground state energy of the model"),
    ("Z_2 topological order", "$\\mathbb{Z}_2$ topological order"),
    ("Z_2 topological order", "ℤ₂ topological order"),
    ("the <i>XY</i> model", "the XY model"),
    ("the XY model", "the <i>XY</i> model"),
    ("efficient quantum algorithms", "Efﬁcient quantum algorithms"),
    ("alpha particles scatter", "$\\alpha$ particles scatter"),
    ("α particles scatter", "\\alpha particles scatter"),
    ("gauge &amp; gravity duality", "Gauge & gravity duality"),
]


@pytest.mark.parametrize(("needle", "title"), TITLE_CASES)
def test_title_fragments_match_across_renderings(needle, title):
    assert normalize_title(needle) in normalize_title(title)
    works = [openalex_work("W1", title), openalex_work("W5", "Clean monopole paper")]
    broker = benchmark([needle], search_transport(works=works))
    assert ids(broker.search("gap")) == ["W5"]


def test_title_fragment_screens_abstracts_and_fetched_text():
    words = "Building on the known solution title of Smith the answer is two".split()
    other = openalex_work("W2", "A follow-up paper", index={w: [i] for i, w in enumerate(words)})
    pages = {
        CITING_ARXIV: "<p>As shown in ‘Known Solution  Title’ (Smith 2021), the answer is 2.</p>",
        CITING_DOI: "<p>Known solutions entitled otherwise.</p>",
    }
    broker = benchmark(["known solution title"], search_transport(works=[other], pages=pages))
    assert broker.search("gap")["items"] == []
    withheld = broker.fetch(CITING_ARXIV)
    assert withheld["status"] == "withheld_contamination_risk"
    assert withheld["flag"]["reason"] == "blocked_source_title"
    assert broker.fetch(CITING_DOI)["status"] == "ok"


def test_title_fragments_match_whole_words_only():
    pages = {CITING_ARXIV: "<p>Spin chainsaw massacre.</p>"}
    broker = benchmark(["spin chains"], search_transport(pages=pages))
    assert broker.fetch(CITING_ARXIV)["status"] == "ok"


# Defect 4: no probing oracle ---------------------------------------------------------------


def test_prefetch_check_uses_only_identifiers_not_title_fragments():
    guesses = [
        "https://en.wikipedia.org/wiki/Counterexample_to_the_foo_conjecture",
        "https://en.wikipedia.org/wiki/2101.00000_2101.00001_2101.00002",
        "https://en.wikipedia.org/wiki/Foo?ref=10.1103/PhysRevX.11.011001",
    ]
    transport = FakeTransport({url: ok(b"<p>An unrelated page.</p>") for url in guesses})
    broker = benchmark(
        ["counterexample to the foo conjecture", "2101.00001", JOURNAL_DOI], transport
    )
    for url in guesses:
        assert broker.fetch(url)["status"] == "ok", url
    assert [call["url"] for call in transport.calls] == guesses


def test_search_exposes_no_blocked_count_but_logs_it(caplog):
    works = [
        openalex_work("W9", "A counterexample to the Foo conjecture"),
        openalex_work("W5", "Clean monopole paper"),
    ]
    broker = benchmark(["counterexample to the foo conjecture"], search_transport(works=works))
    with caplog.at_level(logging.INFO, logger="physharness.knowledge.literature"):
        result = broker.search("foo conjecture")
    assert set(result) == {"query", "items", "errors", "authority"}
    assert ids(result) == ["W5"]
    assert "withheld 1 of 2" in caplog.text


async def test_search_literature_tool_returns_only_public_fields(lab):
    from test_society_tools import call, profile, running

    literature_policy = LiteraturePolicy(mode="open")
    service, author, exp, branches, _ = society_lab(lab, literature=literature_policy)
    alpha, context = running(service, author, exp, branches[0]["id"])

    class Leaky:
        def search(self, query):
            return {"query": query, "items": [], "errors": [], "authority": "x", "secret": 3}

    result = await call(
        profile(service, alpha, context, literature=Leaky()), "search_literature", {"query": "gap"}
    )
    assert set(result) == {"query", "items", "errors", "authority"}


# Defect 5: preflight uses the broker's own reference check ---------------------------------


def test_usable_reference_matches_the_broker():
    words = [f"w{i}" for i in range(40)]
    for text, usable in (
        (None, False),
        ("   ", False),
        ("TODO", False),
        ("Masked reference text.", False),
        (" ".join(words[:26]), False),  # 19 eight-grams: the overlap floor of 20 is unreachable
        (" ".join(words[:27]), True),
        (REFERENCE, True),
    ):
        assert usable_reference(text) is usable, text
        broker = LiteratureBroker(
            policy("benchmark"), transport=FakeTransport({}), reference_text=text
        )
        expected = "LITERATURE_PROVIDER_UNAVAILABLE" if usable else "LITERATURE_SCREEN_UNAVAILABLE"
        if usable:
            assert broker.search("gap")["errors"][0]["code"] == expected
        else:
            assert code_of(lambda broker=broker: broker.search("gap")) == expected


@pytest.mark.parametrize(
    ("content", "ready"),
    [("Masked reference text.", False), ("   ", False), ("TODO", False), (REFERENCE, True)],
    ids=["sentence", "blank", "todo", "reference"],
)
def test_preflight_refuses_a_reference_the_broker_cannot_use(lab, tmp_path, content, ready):
    from test_run_control import SOCIETY, society_plan, source_files

    from physharness.domain import ArtifactCreate
    from physharness.run_control import RunPlan, prepare_run, run_preflight

    service, actor, _ = lab
    source_files(tmp_path)
    reference = service.create_artifact(
        ArtifactCreate(kind="masked_reference", content=content), actor, "reference"
    )["id"]
    literature_policy = {"mode": "benchmark", "masked_reference_artifact_id": reference}
    plan = society_plan(society={**SOCIETY, "literature": literature_policy})
    prepared = prepare_run(service, actor, RunPlan.model_validate(plan), tmp_path)
    operator = Principal(id="controller", project_id="lab", role="operator")
    report = run_preflight(service, operator, prepared["experiment_id"], prices={}, environment={})
    codes = {blocker["code"] for blocker in report["blockers"]}
    assert ("MASKED_REFERENCE_REQUIRED" in codes) is (not ready)


def test_preflight_blocks_junk_blocklists_and_notes_single_form_entries(lab):
    from physharness.run_control import run_preflight

    operator = Principal(id="controller", project_id="lab", role="operator")
    junk = LiteraturePolicy(mode="open", blocked_sources=["arXiv:2101.00001", "TODO"])
    service, _, exp, _, _ = society_lab(lab, literature=junk)
    report = run_preflight(service, operator, exp["id"], prices={}, environment={})
    assert "LITERATURE_BLOCKLIST_INVALID" in {b["code"] for b in report["blockers"]}
    single = LiteraturePolicy(
        mode="benchmark", masked_reference_artifact_id="ref", blocked_sources=["arXiv:2101.00001"]
    )
    service, _, exp, _, _ = society_lab(lab, literature=single, prefix="single")
    report = run_preflight(service, operator, exp["id"], prices={}, environment={})
    codes = {b["code"] for b in report["blockers"]}
    assert "LITERATURE_BLOCKLIST_INVALID" not in codes
    notes = [o for o in report["observations"] if o.get("component") == "literature"]
    assert [note["code"] for note in notes] == ["LITERATURE_BLOCKLIST_ONE_FORM"]


# Defect 6: bounded transport -----------------------------------------------------------------


class Counted(httpx.SyncByteStream):
    """A response body that records how many raw chunks were pulled from the wire."""

    def __init__(self, data, chunk=65536):
        self.data, self.chunk, self.pulled = data, chunk, 0

    def __iter__(self):
        for start in range(0, len(self.data), self.chunk):
            self.pulled += 1
            yield self.data[start : start + self.chunk]


class FakeClock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 6))
        self.now += seconds


def quiet_limiter(clock=None):
    clock = clock or FakeClock()
    return HostLimiter(clock=clock, sleep=clock.sleep)


def transport_for(handler, limiter=None):
    client = literature.http_client(transport=httpx.MockTransport(handler))
    return literature.http_transport(client, limiter=limiter or quiet_limiter())


BOMB = gzip.compress(b"\0" * (64 * 1024 * 1024), compresslevel=9)


def test_redirect_bodies_are_never_read():
    body = Counted(BOMB)

    def handler(request):
        if request.url.path == "/wiki/A":
            headers = {"Location": "/wiki/B", "Content-Encoding": "gzip"}
            return httpx.Response(302, headers=headers, stream=body)
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"small")

    status, _headers, content, final = transport_for(handler)(
        "GET", "https://en.wikipedia.org/wiki/A"
    )
    assert (status, content, final) == (200, b"small", "https://en.wikipedia.org/wiki/B")
    assert body.pulled == 0


def test_decoded_size_is_bounded_while_decompressing():
    body = Counted(BOMB)

    def handler(request):
        headers = {"Content-Type": "text/plain", "Content-Encoding": "gzip"}
        return httpx.Response(200, headers=headers, stream=body)

    broker = LiteratureBroker(policy(), transport=transport_for(handler))
    assert code_of(lambda: broker.fetch("https://en.wikipedia.org/wiki/X")) == (
        "LITERATURE_FETCH_TOO_LARGE"
    )
    status, _, content, _ = transport_for(handler)("GET", "https://en.wikipedia.org/wiki/X")
    assert status == 200 and len(content) == MAX_FETCH_BYTES + 1
    assert body.pulled <= 4  # a few 64 KiB raw chunks, never the whole 64 MiB stream


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "raw-deflate"])
def test_compressed_bodies_decode(encoding):
    text = b"Wilson loops confine quarks. " * 100
    if encoding == "gzip":
        data = gzip.compress(text)
    elif encoding == "deflate":
        data = zlib.compress(text)
    else:
        packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        data = packer.compress(text) + packer.flush()
    name = "deflate" if encoding.endswith("deflate") else "gzip"

    def handler(request):
        headers = {"Content-Type": "text/plain", "Content-Encoding": name}
        return httpx.Response(200, headers=headers, stream=Counted(data, chunk=100))

    assert transport_for(handler)("GET", "https://ncatlab.org/nlab/show/x")[2] == text


def test_unknown_content_encoding_is_refused():
    def handler(request):
        headers = {"Content-Type": "text/plain", "Content-Encoding": "br"}
        return httpx.Response(200, headers=headers, content=b"??")

    broker = LiteratureBroker(policy(), transport=transport_for(handler))
    assert code_of(lambda: broker.fetch("https://ncatlab.org/nlab/show/x")) == (
        "LITERATURE_CONTENT_UNSUPPORTED"
    )


def test_redirect_hops_are_bounded_and_each_is_checked():
    seen = []

    def loop(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://en.wikipedia.org/wiki/Loop"})

    broker = LiteratureBroker(policy(), transport=transport_for(loop))
    assert code_of(lambda: broker.fetch("https://en.wikipedia.org/wiki/Loop")) == (
        "LITERATURE_FETCH_FAILED"
    )
    assert len(seen) == literature.MAX_REDIRECTS + 1

    def downgrade(request):
        return httpx.Response(301, headers={"Location": "http://export.arxiv.org/abs/1"})

    broker = LiteratureBroker(policy(), transport=transport_for(downgrade))
    assert code_of(lambda: broker.fetch("https://arxiv.org/abs/1")) == ("LITERATURE_DOMAIN_BLOCKED")


# Defect 7: politeness ----------------------------------------------------------------------


def test_arxiv_api_is_https_only():
    assert ARXIV_API.startswith("https://")
    assert code_of(lambda: literature.check_url("http://export.arxiv.org/api/query")) == (
        "LITERATURE_DOMAIN_BLOCKED"
    )


def test_limiter_spaces_arxiv_requests_process_wide():
    clock = FakeClock()
    limiter = quiet_limiter(clock)

    def handler(request):
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"x")

    first, second = transport_for(handler, limiter), transport_for(handler, limiter)
    first("GET", "https://export.arxiv.org/api/query")
    second("GET", "https://arxiv.org/abs/2101.00002")
    first("GET", "https://api.openalex.org/works")
    second("GET", "https://api.openalex.org/works")
    assert clock.slept == [3.0, literature.HOST_INTERVALS["api.openalex.org"]]


def test_brokers_built_per_execution_share_the_process_limiter(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(literature, "LIMITER", quiet_limiter(clock))
    real = literature.http_client

    def handler(request):
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"x")

    monkeypatch.setattr(
        literature, "http_client", lambda: real(transport=httpx.MockTransport(handler))
    )
    # The worker builds one broker per execution; a run team runs many at once.
    first, second = LiteratureBroker(policy()), LiteratureBroker(policy())
    first.fetch("https://arxiv.org/abs/2101.00001")
    second.fetch("https://arxiv.org/abs/2101.00002")
    assert clock.slept == [3.0]
    first.close()
    second.close()


def test_limiter_keeps_one_arxiv_request_in_flight():
    limiter = HostLimiter(sleep=lambda seconds: None)
    active, peak, lock = [0], [0], threading.Lock()
    release = threading.Event()

    def handler(request):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        release.wait(0.05)
        with lock:
            active[0] -= 1
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"x")

    transport = transport_for(handler, limiter)
    threads = [
        threading.Thread(target=transport, args=("GET", "https://arxiv.org/abs/1"))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 1


def test_retry_after_is_honoured_for_everyone():
    clock = FakeClock()
    limiter = quiet_limiter(clock)
    replies = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"ok"),
    ]

    def handler(request):
        return replies.pop(0)

    status, _, body, _ = transport_for(handler, limiter)("GET", "https://api.openalex.org/works")
    assert (status, body) == (200, b"ok")
    assert clock.slept == [7.0, literature.BACKOFF_SECONDS * 2]


def test_long_retry_after_fails_fast_and_holds_back_the_host():
    clock = FakeClock()
    limiter = quiet_limiter(clock)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "3600"})

    broker = LiteratureBroker(policy(), transport=transport_for(handler, limiter))
    assert code_of(lambda: broker.fetch("https://en.wikipedia.org/wiki/A")) == (
        "LITERATURE_FETCH_FAILED"
    )
    assert code_of(lambda: broker.fetch("https://en.wikipedia.org/wiki/B")) == (
        "LITERATURE_RATE_LIMITED"
    )
    assert calls == ["https://en.wikipedia.org/wiki/A"]


def test_contact_is_sent_only_when_configured(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{}")

    def run():
        seen.clear()
        broker = LiteratureBroker(policy(), transport=transport_for(handler))
        broker.search("gap")
        openalex = next(r for r in seen if r.url.host == "api.openalex.org")
        return openalex.url.params.get("mailto"), openalex.headers["user-agent"]

    monkeypatch.delenv(literature.CONTACT_ENV, raising=False)
    assert run() == (None, literature.USER_AGENT)
    monkeypatch.setenv(literature.CONTACT_ENV, "not an email")
    assert run() == (None, literature.USER_AGENT)
    monkeypatch.setenv(literature.CONTACT_ENV, "ops@lab.example")
    assert run() == ("ops@lab.example", f"{literature.USER_AGENT} (mailto:ops@lab.example)")


# Defect 8: search and listing pages --------------------------------------------------------

LISTINGS = [
    "https://arxiv.org/./search/?query=foo",
    "https://arxiv.org/x/../search?query=foo",
    "https://arxiv.org/%2e/search?query=foo",
    "https://arxiv.org/%252e/search?query=foo",
    "https://arxiv.org/search%2F?query=foo",
    "https://arxiv.org/search;x?query=foo",
    "https://arxiv.org/catchup/math-ph/2021-01-04",
    "https://arxiv.org/year/math-ph/2021",
    "https://en.wikipedia.org/w/index.php?title=Special:Search/foo+conjecture",
    "https://en.wikipedia.org/w/index.php?title=Special:Search&fulltext=1&Search=x",
    "https://en.wikipedia.org/w/index.php?title=special%3Aallpages",
    "https://en.wikipedia.org/wiki/Special:WhatLinksHere/Mass_gap",
    "https://en.wikipedia.org/api/rest_v1/page/related/Mass_gap",
    "https://mathoverflow.net/questions/tagged/quantum-information?sort=votes",
    "https://math.stackexchange.com/questions/tagged/inequality",
    "https://mathoverflow.net/questions?tab=Newest",
    "https://mathoverflow.net/",
    "https://mathoverflow.net/unanswered",
    "https://ncatlab.org/nlab/all_pages",
    "https://ncatlab.org/nlab/recently_revised",
    "https://ncatlab.org/nlab/list/foo",
    "https://ncatlab.org/nforum/search/?q=foo",
]


def test_benchmark_fetch_refuses_normalized_listing_pages():
    transport = FakeTransport({})
    broker = benchmark([], transport)
    for url in LISTINGS:
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url
    assert transport.calls == []
    articles = [
        "https://mathoverflow.net/questions/12345/why-is-the-gap-open",
        "https://ncatlab.org/nlab/show/gauge+theory",
        "https://en.wikipedia.org/wiki/Mass_gap",
        "https://arxiv.org/abs/2201.00002",
    ]
    broker = benchmark([], FakeTransport({url: ok(b"<p>article</p>") for url in articles}))
    assert [broker.fetch(url)["status"] for url in articles] == ["ok"] * 4


def test_url_entries_match_equivalent_page_urls():
    broker = benchmark(
        ["https://en.wikipedia.org/wiki/Mass_gap", "mathoverflow.net/questions/12345/why"],
        FakeTransport({}),
    )
    for url in (
        "https://en.wikipedia.org/wiki/Mass%20gap",
        "https://en.wikipedia.org/wiki/mass_gap#Proof",
        "https://en.wikipedia.org/w/index.php?title=Mass_gap&action=raw",
        "https://mathoverflow.net/questions/12345",
        "https://mathoverflow.net/q/12345",
        "https://mathoverflow.net/questions/12345/other-slug",
    ):
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url


def test_recorded_source_keeps_the_final_url(lab):
    from test_literature import fetched
    from test_sharing import approaches

    service, _author, exp, _branches, (alpha, _beta) = approaches(lab, "ideas")
    result = fetched()
    record = service.record_literature_fetch(exp["id"], result, alpha, "fetch-final")
    assert record["url"] == result["url"] and record["final_url"] == result["final_url"]
    source = service.get_record("source", record["source_id"], alpha)
    assert source["uri"] == result["final_url"]
