from test_sharing import approaches, artifact


def test_invisible_events_do_not_hide_later_branch_events(lab):
    service, _, _, _, (alpha, beta) = approaches(lab, "none")
    for i in range(8):
        artifact(service, beta, f"hidden-{i}")
    own = artifact(service, alpha, "own-after-hidden")
    page = service.event_page(alpha, limit=1)
    found = []
    while True:
        found.extend(page["items"])
        if not page["has_more"]:
            break
        page = service.event_page(alpha, after=page["next_cursor"], limit=1)
    assert any(e["aggregate_id"] == own["id"] for e in found)
    assert all("hidden-" not in str(e) for e in found)


def test_event_tail_returns_recent_activity_not_oldest_window(lab):
    service, author, _, _, (_, beta) = approaches(lab, "ideas")
    recent = [artifact(service, beta, f"event-{i}") for i in range(5)]
    result = service.event_page(author, limit=2, tail=True)
    assert [e["aggregate_id"] for e in result["items"]] == [r["id"] for r in recent[-2:]]
    assert result["window"] == "latest"
    assert result["next_cursor"] == result["items"][-1]["sequence"]
