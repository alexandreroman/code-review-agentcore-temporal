from agentcore_review_shared.contract import Category, Finding
from agentcore_review_worker.models import BatchPatches, FilePatch, SynthesisInput
from agentcore_review_worker.prompts import (
    fixer_prompt,
    reviewer_prompt,
    synthesis_prompt,
)

PATCHES = BatchPatches(
    patches=[FilePatch(path="app/search.py", status="added", patch="@@ -0,0 +1 @@\n+run(f'{name}')")],
    tree=["app/", "README.md"],
)


def finding(finding_id: str, suggestion: str | None = None) -> Finding:
    return Finding(
        id=finding_id,
        category="security",
        severity="high",
        path="app/search.py",
        line=1,
        title="SQL injection",
        explanation="why",
        suggestion=suggestion,
    )


def test_reviewers_share_everything_before_their_focus():
    prompts = {category: reviewer_prompt(category, PATCHES, []) for category in Category}
    assert len({p[0]["text"] for p in prompts.values()}) == 1
    assert all(p[1] == {"cachePoint": {"type": "default"}} for p in prompts.values())
    assert len({p[2]["text"] for p in prompts.values()}) == 3


def test_the_diff_comes_before_the_focus():
    shared, _, focus = reviewer_prompt(Category.PERFORMANCE, PATCHES, [])
    assert "run(f'{name}')" in shared["text"] and "README.md" in shared["text"]
    assert "performance" not in shared["text"].lower()
    assert "performance" in focus["text"]


def test_open_findings_appear_only_in_incremental_rounds():
    assert "F-001" not in reviewer_prompt(Category.SECURITY, PATCHES, [])[2]["text"]
    focus = reviewer_prompt(Category.SECURITY, PATCHES, [finding("F-001")])[2]["text"]
    assert "F-001" in focus and "resolved_ids" in focus


def test_synthesis_prompt_lists_findings_without_comment_ids():
    new = [finding("F-001").model_copy(update={"comment_id": 42})]
    text = synthesis_prompt(SynthesisInput(new_findings=new, resolved_ids=["F-000"], unavailable=["performance"]))
    assert '"F-001"' in text and "comment_id" not in text
    assert "F-000" in text and "performance" in text


def test_fixer_prompt_carries_suggestions():
    assert "Use parameters" in fixer_prompt([finding("F-001", suggestion="Use parameters")])
