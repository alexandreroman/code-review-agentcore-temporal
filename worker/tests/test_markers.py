from agentcore_review_worker.markers import (
    extract_finding_ids,
    finding_marker,
    fix_trailer,
    last_finding_number,
    last_fix_number,
    last_round,
    round_marker,
)


def test_the_markers_persisted_on_github_keep_their_format():
    """RecoverCounters, idempotency and the e2e skill parse these strings on GitHub: they are a contract."""
    assert finding_marker("F-007") == "<!-- finding:F-007 -->"
    assert round_marker("pr-o-r-3", 2) == "<!-- round:pr-o-r-3:2 -->"
    assert fix_trailer("pr-o-r-3", 1) == "Review-Fix: pr-o-r-3/1"


def test_extract_finding_ids():
    body = f"{finding_marker('F-001')} SQL injection\n\n{finding_marker('F-012')} N+1"
    assert extract_finding_ids(body) == ["F-001", "F-012"]
    assert extract_finding_ids(None) == [] and extract_finding_ids("no marker") == []


def test_the_last_round_counts_only_this_workflow_ids_markers():
    bodies = [round_marker("pr-o-r-3", 1), f"{round_marker('pr-o-r-3', 4)}\n## AI Review", round_marker("pr-o-r-31", 9)]
    assert last_round("pr-o-r-3", bodies) == 4
    assert last_round("pr-o-r-3", [None, "no marker"]) == 0


def test_the_last_finding_number_reads_every_marker():
    texts = [f"{finding_marker('F-002')} a\n\n{finding_marker('F-011')} b", finding_marker("F-007"), None]
    assert last_finding_number(texts) == 11
    assert last_finding_number(["**F-099 stays open.** no marker"]) == 0


def test_the_last_fix_number_reads_whole_trailer_lines_of_this_workflow_id():
    messages = [
        f"Fix the query\n\n{fix_trailer('pr-o-r-3', 2)}",
        f"Fix again\n\n{fix_trailer('pr-o-r-3', 1)}\n",
        fix_trailer("pr-o-r-31", 5),
        "Mention Review-Fix: pr-o-r-3/8 in a sentence",
    ]
    assert last_fix_number("pr-o-r-3", messages) == 2
    assert last_fix_number("pr-o-r-3", ["Initial commit"]) == 0
