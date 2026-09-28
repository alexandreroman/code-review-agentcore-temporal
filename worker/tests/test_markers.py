from datetime import UTC, datetime

from agentcore_review_worker.markers import (
    closing_marker,
    extract_finding_ids,
    finding_marker,
    fix_refusal_marker,
    fix_trailer,
    idle_close_marker,
    idle_warning_marker,
    reply_marker,
    round_marker,
)


def test_marker_formats_match_the_spec():
    assert finding_marker("F-007") == "<!-- finding:F-007 -->"
    assert round_marker("pr-o-r-3", 2) == "<!-- round:pr-o-r-3:2 -->"
    assert closing_marker("pr-o-r-3") == "<!-- closing:pr-o-r-3 -->"
    assert fix_trailer("pr-o-r-3", 1) == "Review-Fix: pr-o-r-3/1"
    assert reply_marker("pr-o-r-3", 777) == "<!-- reply:pr-o-r-3:777 -->"
    assert fix_refusal_marker("pr-o-r-3", "d-1") == "<!-- fix-refused:pr-o-r-3:d-1 -->"
    idle_since = datetime(2026, 9, 28, 14, 0, 30, tzinfo=UTC)
    assert idle_warning_marker("pr-o-r-3", idle_since) == "<!-- idle-warning:pr-o-r-3:1790604030 -->"
    assert idle_close_marker("pr-o-r-3", idle_since) == "<!-- idle-close:pr-o-r-3:1790604030 -->"


def test_extract_finding_ids():
    body = f"{finding_marker('F-001')} SQL injection\n\n{finding_marker('F-012')} N+1"
    assert extract_finding_ids(body) == ["F-001", "F-012"]
    assert extract_finding_ids(None) == [] and extract_finding_ids("no marker") == []
