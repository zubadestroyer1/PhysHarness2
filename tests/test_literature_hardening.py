"""Benchmark literature screen, second hardening pass: TeX and Unicode title spellings,
identifier-bearing entries, alternate page views, over-broad fragments, gzip members,
bounded queueing and the dedicated literature pool. Mocked transports only; no network."""

import asyncio
import contextvars
import gzip
import threading
import time

import httpx
import pytest
from commons_helpers import society_lab
from test_literature import FakeTransport, ok, openalex_work, policy
from test_literature_screen import (
    Counted,
    benchmark,
    code_of,
    ids,
    search_transport,
    transport_for,
)

from physharness.domain import LiteraturePolicy, Principal
from physharness.errors import HarnessError
from physharness.knowledge import literature
from physharness.knowledge.literature import (
    MAX_FETCH_BYTES,
    HostLimiter,
    blocklist_notes,
    broad_title_entries,
    classify_blocked_source,
    normalize_title,
)

CITING = "https://en.wikipedia.org/wiki/Citing_page"
CLEAN = openalex_work("W5", "Clean monopole paper")


# Defect 1: both sides of the title screen read TeX and Unicode spellings alike ------------

SPELLINGS = [
    ("Poincaré duality for twisted sheaves", r"Poincar\'e duality for twisted sheaves"),
    ("Poincaré duality for twisted sheaves", r"Poincar{\'e} duality for twisted sheaves"),
    ("Poincaré duality for twisted sheaves", r"Poincar\'{e} duality for twisted sheaves"),
    ("Painlevé transcendents and isomonodromy", r"Painlev\'e transcendents and isomonodromy"),
    ("Erdős–Rényi random graphs", r"Erd{\H o}s-R{\'e}nyi random graphs"),
    ("Erdős–Rényi random graphs", r"Erd\H{o}s--R\'{e}nyi random graphs"),
    ("Martínez inequality for traces", r"Mart\'{\i}nez inequality for traces"),
    ("Martínez inequality for traces", r"Mart\'\i nez inequality for traces"),
    ("Łojasiewicz gradient inequality", r"{\L}ojasiewicz gradient inequality"),
    ("Søren's lattice fermions", r"S{\o}ren's lattice fermions"),
    ("φ^4 theory in three dimensions", r"$\varphi^4$ theory in three dimensions"),
    ("ε-expansion of critical exponents", r"$\varepsilon$-expansion of critical exponents"),
    ("ϑ functions of even lattices", r"$\vartheta$ functions of even lattices"),
    ("renormalization of gauge theories", "renor­malization of gauge theories"),
    ("renormalization of gauge theories", "renor​malization of gauge theories"),
    ("renormalization of gauge theories", "renorma⁠lization of gauge﻿ theories"),
    ("renormalization of gauge theories", "renormaliza-\ntion of gauge theories"),
    ("Kähler manifolds with torsion", "K&amp;auml;hler manifolds with torsion"),
    ("Kähler manifolds with torsion", "K&amp;amp;auml;hler manifolds with torsion"),
]


@pytest.mark.parametrize(("needle", "title"), SPELLINGS)
def test_tex_and_unicode_spellings_normalize_to_one_token_stream(needle, title):
    assert normalize_title(title) == normalize_title(needle)
    works = [openalex_work("W1", title), CLEAN]
    assert ids(benchmark([needle], search_transport(works=works)).search("gap")) == ["W5"]
    # And the other way round: an operator may paste the TeX spelling.
    works = [openalex_work("W1", needle), CLEAN]
    assert ids(benchmark([title], search_transport(works=works)).search("gap")) == ["W5"]


def test_poincare_accent_before_a_space_is_screened_end_to_end():
    feed = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        b"<id>http://arxiv.org/abs/2105.09999v1</id><published>2021-05-01</published>"
        b"<title>Poincar\\'e duality for twisted sheaves</title>"
        b"<summary>We prove the statement.</summary><author><name>A</name></author>"
        b"</entry></feed>"
    )
    broker = benchmark(["Poincaré duality for twisted sheaves"], search_transport(arxiv=feed))
    assert broker.search("duality")["items"] == []


@pytest.mark.parametrize(
    "text",
    [
        "Proved in renormaliza-\ntion of gauge theories by Smith.",
        "Proved in renormaliza-\r\n  tion of gauge theories by Smith.",
        "Proved in renormaliza- tion of gauge theories by Smith.",
        "Proved in renormaliza­\ntion of gauge theories by Smith.",
    ],
)
def test_line_break_hyphenation_in_fetched_text_is_screened(text):
    transport = FakeTransport({CITING: ok(text.encode(), "text/plain")})
    broker = benchmark(["renormalization of gauge theories"], transport)
    result = broker.fetch(CITING)
    assert result["status"] == "withheld_contamination_risk"
    assert result["flag"]["reason"] == "blocked_source_title"


def test_a_real_hyphen_broken_across_lines_still_matches():
    """A compound broken at its own hyphen keeps matching the hyphenated fragment."""
    for text in ("Yang-\nMills existence and mass gap", "Yang- Mills existence and mass gap"):
        transport = FakeTransport({CITING: ok(text.encode(), "text/plain")})
        broker = benchmark(["Yang-Mills existence and mass gap"], transport)
        assert broker.fetch(CITING)["status"] == "withheld_contamination_risk", text


def test_braces_and_hidden_characters_never_lose_an_existing_match():
    """Soft boundaries match joined or split, so a spaced reading still hits."""
    for text in ("the {foo} bar conjecture", "foo​bar conjecture"):
        transport = FakeTransport({CITING: ok(text.encode(), "text/plain")})
        broker = benchmark(["foo bar conjecture"], transport)
        assert broker.fetch(CITING)["status"] == "withheld_contamination_risk", text


def test_soft_boundaries_do_not_match_across_real_words():
    pages = {CITING: "<p>renormaliza tion of gauge theories; spin chain-\nsaw.</p>"}
    broker = benchmark(
        ["renormalization of gauge theories", "spin chainsaw massacre"],
        search_transport(pages=pages),
    )
    assert broker.fetch(CITING)["status"] == "ok"


KEY_SPELLINGS = [
    ("text/plain", "See arXiv:２１０１．０００01 for the proof."),
    ("text/plain", "See 2101.​00001 for the proof."),
    ("application/json", '{"doi": "10.1103\\/PhysRevLett.1.1"}'),
    ("text/plain", "Published as 10.1103&#x2F;PhysRevLett.1.1."),
    ("text/html", "<p>Published as 10.1103&amp;#x2F;PhysRevLett.1.1.</p>"),
    ("text/plain", "Published as １０．１１０３／PhysRevLett.1.1."),
]


@pytest.mark.parametrize(("media", "text"), KEY_SPELLINGS)
def test_escaped_and_fullwidth_identifiers_in_fetched_text_are_screened(media, text):
    transport = FakeTransport({CITING: ok(text.encode(), media)})
    broker = benchmark(["2101.00001", "10.1103/PhysRevLett.1.1"], transport)
    result = broker.fetch(CITING)
    assert result["status"] == "withheld_contamination_risk"
    assert result["flag"]["reason"] == "blocked_source_key"


def test_unrelated_identifiers_stay_released_after_normalization():
    text = "Compare １２１０１．０００01, 2101.000012 and 10.1103\\/PhysRevLett.1.10."
    transport = FakeTransport({CITING: ok(text.encode(), "text/plain")})
    broker = benchmark(["2101.00001", "10.1103/PhysRevLett.1.1"], transport)
    assert broker.fetch(CITING)["status"] == "ok"


# Defect 2: identifier-bearing entries never become title fragments -------------------------

IDENTIFIER_BEARING = [
    "Smith et al., arXiv:2101.00001",
    "Exact solution of the model (arXiv:2101.00001)",
    "2101.00001 [math-ph] (v3)",
    "arXiv 2101 00001",
    "arXiv 2101.00001 version three",
    "see hep-th/9901001 for the construction",
    "Published as 10.1103/PhysRevLett.1.1 in PRL",
    "doi 10.1103 PhysRevLett 1 1 proof",
    "OpenAlex record W2741809807 of the proof",
]


@pytest.mark.parametrize("entry_text", IDENTIFIER_BEARING)
def test_entries_carrying_an_identifier_must_be_the_identifier(entry_text):
    with pytest.raises(ValueError, match="identifier"):
        classify_blocked_source(entry_text)
    with pytest.raises(HarnessError) as caught:
        benchmark(["2101.00002", entry_text], FakeTransport({}))
    assert caught.value.code == "LITERATURE_POLICY_INVALID"
    assert caught.value.details["entries"] == [1]
    assert "identifier" in caught.value.details["reasons"][0]


def test_titles_with_numbers_but_no_identifier_stay_title_fragments():
    for fragment in (
        "Phys. Rev. X 11, 011001",
        "Kosterlitz widget survey of 1998 2000",
        "SU(2) lattice gauge fields",
        "the O(n) loop model",
    ):
        assert classify_blocked_source(fragment)[0] == "title", fragment


@pytest.mark.parametrize(
    "entry_text",
    [
        "doi:10.1103/PhysRevLett.1.1)",
        "10.1103/PhysRevLett.1.1]",
        '"10.1103/PhysRevLett.1.1"',
        "(doi:10.1103/PhysRevLett.1.1)",
        "[10.1103/PhysRevLett.1.1]",
        "10.1103/PhysRevLett.1.1’",
        "https://doi.org/10.1103/PhysRevLett.1.1).",
    ],
)
def test_dois_lose_unbalanced_trailing_brackets_and_quotes(entry_text):
    assert classify_blocked_source(entry_text) == ("doi", "10.1103/physrevlett.1.1")


def test_balanced_brackets_inside_a_doi_are_kept():
    for doi in (
        "10.1016/0370-2693(85)91166-X",
        "10.1002/(SICI)1097-4636(199705)35:2<199::AID-JBM8>3.0.CO;2-P",
        "10.1000/abc(1)",
    ):
        assert classify_blocked_source(doi) == ("doi", doi.lower()), doi
    assert literature._doi("https://doi.org/10.1000/abc(1))") == "10.1000/abc(1)"


def test_run_plan_names_the_rejected_entry_and_why():
    from pydantic import ValidationError
    from test_run_control import SOCIETY, society_plan

    from physharness.run_control import RunPlan

    literature_policy = {
        "mode": "open",
        "blocked_sources": ["arXiv:2101.00001", "Smith et al., arXiv:2101.00001"],
    }
    with pytest.raises(ValidationError) as caught:
        RunPlan.model_validate(society_plan(society={**SOCIETY, "literature": literature_policy}))
    message = str(caught.value)
    assert "blocked_sources[1]" in message
    assert "Smith et al., arXiv:2101.00001" in message and "identifier" in message


# Defect 3: alternate views of a blocked page share its key ----------------------------------

BLOCKED_PAGES = [
    "https://mathoverflow.net/questions/12345/some-title",
    "https://math.stackexchange.com/q/777",
    "ncatlab.org/nlab/show/foo+bar",
    "https://en.wikipedia.org/wiki/Foo_bar",
]

ALTERNATE_VIEWS = [
    "https://mathoverflow.net/posts/12345/revisions",
    "https://mathoverflow.net/posts/12345/timeline",
    "https://mathoverflow.net/revisions/12345/1",
    "https://math.stackexchange.com/posts/777/revisions",
    "https://math.stackexchange.com/revisions/777/3",
    "https://ncatlab.org/nlab/source/foo+bar",
    "https://ncatlab.org/nlab/revision/foo+bar/3",
    "https://ncatlab.org/nlab/revision/diff/foo+bar/3",
    "https://ncatlab.org/nlab/print/foo+bar",
    "https://ncatlab.org/nlab/history/foo+bar",
    "https://ncatlab.org/nlab/show/diff/foo+bar",
    "https://en.wikipedia.org/w/index.php?title=Foo_bar&action=history",
    "https://en.wikipedia.org/w/index.php?title=Foo_bar&action=raw",
    "https://en.wikipedia.org/w/index.php/Foo_bar",
    "https://en.wikipedia.org/wiki/Unrelated?title=Foo_bar",
    "https://en.wikipedia.org/w/index.php?title=Unrelated&title=Foo_bar",
    "https://en.wikipedia.org/wiki/Foo_bar%23Proof",
    "https://en.wikipedia.org/wiki/Foo_bar_",
]


def test_alternate_views_of_a_blocked_page_are_refused():
    transport = FakeTransport({})
    broker = benchmark(BLOCKED_PAGES, transport)
    for url in ALTERNATE_VIEWS:
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url
    assert transport.calls == []


def test_nlab_page_names_with_slashes_keep_their_full_name():
    transport = FakeTransport({"https://ncatlab.org/nlab/show/foo": ok(b"<p>parent</p>")})
    broker = benchmark(["ncatlab.org/nlab/show/foo/bar"], transport)
    for url in (
        "https://ncatlab.org/nlab/show/foo/bar",
        "https://ncatlab.org/nlab/revision/foo/bar/2",
        "https://ncatlab.org/nlab/source/foo/bar",
    ):
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url
    assert broker.fetch("https://ncatlab.org/nlab/show/foo")["status"] == "ok"


def test_arxiv_abs_with_an_arxiv_prefix_names_the_paper():
    broker = benchmark(["2101.00001"], FakeTransport({}))
    for url in ("https://arxiv.org/abs/arXiv:2101.00001", "https://arxiv.org/bibtex/2101.00001"):
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url


LISTING_OR_OPAQUE = [
    "https://mathoverflow.net/questions/linked/12345",
    "https://mathoverflow.net/questions/related/12345",
    "https://math.stackexchange.com/questions/linked/777",
    "https://arxiv.org/tb/2101.00001",
    "https://arxiv.org/prevnext?id=2101.00000&function=next",
    "https://en.wikipedia.org/w/index.php?oldid=123",
    "https://en.wikipedia.org/w/index.php?curid=12345",
    "https://en.wikipedia.org/?curid=12345",
    "https://en.wikipedia.org/wiki/Mass_gap?oldid=5",
    "https://en.wikipedia.org/w/index.php?title=Mass_gap&diff=prev&oldid=5",
    "https://en.wikipedia.org/w/index.php?diff=123",
]


def test_listing_and_unmappable_views_are_refused_in_benchmark_mode():
    transport = FakeTransport({url: ok(b"<p>page</p>") for url in LISTING_OR_OPAQUE})
    broker = benchmark([], transport)
    for url in LISTING_OR_OPAQUE:
        assert code_of(lambda url=url: broker.fetch(url)) == "LITERATURE_SOURCE_BLOCKED", url
    assert transport.calls == []
    # Open mode logs everything and refuses nothing.
    opened = literature.LiteratureBroker(policy(), transport=transport)
    assert opened.fetch(LISTING_OR_OPAQUE[5])["status"] == "ok"


def test_alternate_views_of_unblocked_pages_stay_available():
    pages = [
        "https://mathoverflow.net/posts/99999/revisions",
        "https://ncatlab.org/nlab/source/gauge+theory",
        "https://en.wikipedia.org/w/index.php?title=Mass_gap&action=raw",
        "https://mathoverflow.net/questions/12346/another",
    ]
    broker = benchmark(BLOCKED_PAGES, FakeTransport({url: ok(b"<p>page</p>") for url in pages}))
    assert [broker.fetch(url)["status"] for url in pages] == ["ok"] * len(pages)


# Defect 4: over-broad title fragments -------------------------------------------------------

TOO_COMMON = [
    "of the model",
    "in the case",
    "quantum field",
    "quantum field theory",
    "on the theory of",
    "existence and uniqueness of solutions",
    "a b c d e f",
    "the XY model",
]


@pytest.mark.parametrize("fragment", TOO_COMMON)
def test_fragments_of_only_common_words_are_rejected(fragment):
    with pytest.raises(ValueError, match="common"):
        classify_blocked_source(fragment)
    assert code_of(lambda: benchmark([fragment], FakeTransport({}))) == (
        "LITERATURE_POLICY_INVALID"
    )


def test_short_or_single_topic_fragments_are_flagged_broad():
    broad = ["the Ising model", "Yang-Mills", "spin chains", "mass gap"]
    distinctive = [
        "Poincaré duality for twisted sheaves",
        "counterexample to the foo conjecture",
        "Phys. Rev. X 11, 011001",
    ]
    for fragment in broad + distinctive:
        classify_blocked_source(fragment)
    entries = ["arXiv:2101.00001", "10.1103/PhysRevX.11.011001", *distinctive, *broad]
    assert broad_title_entries(entries) == [5, 6, 7, 8]
    assert "LITERATURE_BLOCKLIST_BROAD_TITLE" in blocklist_notes(entries)
    assert "LITERATURE_BLOCKLIST_BROAD_TITLE" not in blocklist_notes(entries[:5])


def test_preflight_warns_about_broad_fragments_by_index(lab):
    from physharness.run_control import run_preflight

    operator = Principal(id="controller", project_id="lab", role="operator")
    sources = ["arXiv:2101.00001", "10.1103/PhysRevX.11.011001", "the Ising model"]
    broad = LiteraturePolicy(
        mode="benchmark", masked_reference_artifact_id="ref", blocked_sources=sources
    )
    service, _, exp, _, _ = society_lab(lab, literature=broad)
    report = run_preflight(service, operator, exp["id"], prices={}, environment={})
    assert "LITERATURE_BLOCKLIST_INVALID" not in {b["code"] for b in report["blockers"]}
    notes = [o for o in report["observations"] if o.get("component") == "literature"]
    assert notes == [
        {
            "component": "literature",
            "code": "LITERATURE_BLOCKLIST_BROAD_TITLE",
            "status": "warning",
            "entries": [2],
        }
    ]


# Defect 5: gzip members, bounded queueing, a dedicated pool ---------------------------------


def gzip_handler(data, chunk=65536):
    body = Counted(data, chunk=chunk)

    def handler(request):
        headers = {"Content-Type": "text/plain", "Content-Encoding": "gzip"}
        return httpx.Response(200, headers=headers, stream=body)

    return handler, body


def test_every_gzip_member_is_decoded():
    data = gzip.compress(b"first member. ") + gzip.compress(b"second member.")
    handler, _ = gzip_handler(data, chunk=7)
    assert transport_for(handler)("GET", "https://ncatlab.org/nlab/show/x")[2] == (
        b"first member. second member."
    )


def test_gzip_members_share_one_output_cap():
    bomb = gzip.compress(b"\0" * (8 * 1024 * 1024), compresslevel=9)
    handler, body = gzip_handler(gzip.compress(b"small. ") + bomb)
    status, _, content, _ = transport_for(handler)("GET", "https://ncatlab.org/nlab/show/x")
    assert status == 200 and len(content) == MAX_FETCH_BYTES + 1
    assert body.pulled <= 4


def test_raw_bytes_are_capped_when_output_stays_small():
    handler, body = gzip_handler(gzip.compress(b"tiny") + b"\0" * (32 * 1024 * 1024))
    broker = literature.LiteratureBroker(policy(), transport=transport_for(handler))
    assert code_of(lambda: broker.fetch("https://ncatlab.org/nlab/show/x")) == (
        "LITERATURE_FETCH_TOO_LARGE"
    )
    assert body.pulled <= MAX_FETCH_BYTES // 65536 + 2


def test_limiter_bounds_lock_wait_and_spacing_together():
    """Queueing behind the lock and then the host spacing never exceed max_wait in total."""
    slept = []
    limiter = HostLimiter(
        {"arxiv.org": 0.4}, max_wait=0.5, clock=time.monotonic, sleep=slept.append
    )
    entered = threading.Event()

    def holder():
        with limiter.slot("arxiv.org"):
            entered.set()
            time.sleep(0.3)

    thread = threading.Thread(target=holder)
    thread.start()
    entered.wait()
    started = time.monotonic()
    with pytest.raises(HarnessError) as caught, limiter.slot("arxiv.org"):
        pass
    thread.join()
    assert caught.value.code == "LITERATURE_RATE_LIMITED"
    assert slept == [] and time.monotonic() - started < 0.5


async def test_literature_calls_run_on_their_own_pool():
    marker = contextvars.ContextVar("marker", default=None)
    marker.set("worker-scope")

    def call():
        return threading.current_thread().name, marker.get()

    name, seen = await literature.run_blocking(call)
    assert name.startswith("literature") and seen == "worker-scope"


async def test_queued_literature_calls_fail_fast_after_max_wait(monkeypatch):
    monkeypatch.setattr(literature, "MAX_QUEUE_SECONDS", 0.05)
    monkeypatch.setattr(literature, "EXECUTOR", literature.ThreadPoolExecutor(1))
    gate = threading.Event()
    first = asyncio.ensure_future(literature.run_blocking(gate.wait, 1))
    await asyncio.sleep(0.01)
    second = asyncio.ensure_future(literature.run_blocking(lambda: "ran"))
    await asyncio.sleep(0.1)
    gate.set()
    assert await first is True
    with pytest.raises(HarnessError) as caught:
        await second
    assert caught.value.code == "LITERATURE_RATE_LIMITED"


async def test_society_literature_tools_use_the_literature_pool(lab):
    from test_society_tools import call, profile, running

    service, author, exp, branches, _ = society_lab(lab, literature=LiteraturePolicy(mode="open"))
    alpha, context = running(service, author, exp, branches[0]["id"])
    threads = []

    class Recording:
        def search(self, query):
            threads.append(threading.current_thread().name)
            return {"query": query, "items": [], "errors": [], "authority": "x"}

    await call(
        profile(service, alpha, context, literature=Recording()),
        "search_literature",
        {"query": "gap"},
    )
    assert len(threads) == 1 and threads[0].startswith("literature")
