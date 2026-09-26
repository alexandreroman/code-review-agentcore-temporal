from agentic_review_shared.contract import Finding, FindingDraft
from agentic_review_worker.findings import (
    assign_ids,
    check_conclusion,
    fallback_merge,
    format_finding_id,
    split_inline,
)


def draft(severity="high", path="app/a.py", line=5, category="security", end_line=None) -> FindingDraft:
    return FindingDraft(
        category=category, severity=severity, path=path, line=line, end_line=end_line, title="t", explanation="e"
    )


def finding(fid, **kw) -> Finding:
    return Finding(**draft(**kw).model_dump(), id=fid)


def test_ids_are_sequential_and_continue_across_rounds():
    first, nxt = assign_ids([draft(), draft(line=6)], 1)
    assert [f.id for f in first] == ["F-001", "F-002"] and nxt == 3
    second, nxt = assign_ids([draft(line=7)], nxt)
    assert second[0].id == "F-003" and nxt == 4
    assert format_finding_id(12) == "F-012"


def test_assign_ids_on_empty_list():
    assert assign_ids([], 5) == ([], 5)


def test_check_is_red_only_for_blocking_findings():
    assert check_conclusion([]) == "success"
    assert check_conclusion([finding("F-1", severity="medium"), finding("F-2", severity="low")]) == "success"
    assert check_conclusion([finding("F-1", severity="low"), finding("F-2", severity="high")]) == "failure"
    assert check_conclusion([finding("F-1", severity="critical")]) == "failure"


def test_fallback_merge_dedupes_by_path_and_line_keeping_the_most_severe():
    merged = fallback_merge(
        [
            finding("F-1", severity="medium", line=5, category="maintainability"),
            finding("F-2", severity="critical", line=5, category="security"),
            finding("F-3", severity="low", path="app/b.py", line=1),
            finding("F-4", severity="high", path="app/b.py", line=9),
        ]
    )
    assert [f.id for f in merged] == ["F-2", "F-4", "F-3"]


def test_split_inline_keeps_commentable_findings_up_to_the_cap():
    commentable = {"app/a.py": {5, 6, 7}}
    findings = [
        finding("F-1", severity="low", line=5),
        finding("F-2", severity="critical", line=6),
        finding("F-3", severity="high", line=99),  # outside the diff
        finding("F-4", severity="medium", path="app/other.py", line=1),  # file not in the diff
        finding("F-5", severity="high", line=6, end_line=7),
    ]
    inline, body = split_inline(findings, commentable, max_inline=2)
    assert [f.id for f in inline] == ["F-2", "F-5"]
    assert sorted(f.id for f in body) == ["F-1", "F-3", "F-4"]
