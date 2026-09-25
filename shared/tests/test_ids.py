from tar_shared.ids import (
    fixer_workflow_id,
    pr_workflow_id,
    reviewer_workflow_id,
    snapshot_key,
    snapshot_prefix,
    synthesis_workflow_id,
)


def test_pr_workflow_id_format():
    assert pr_workflow_id("octocat", "temporal-agentic-review-demo", 7) == (
        "pr-octocat-temporal-agentic-review-demo-7"
    )


def test_pr_workflow_id_ignores_case_differences_between_events():
    assert pr_workflow_id("OctoCat", "Temporal-Agentic-Review-Demo", 7) == pr_workflow_id(
        "octocat", "temporal-agentic-review-demo", 7
    )


def test_child_workflow_ids():
    pr_id = "pr-o-r-3"
    assert reviewer_workflow_id(pr_id, 2, "security") == "pr-o-r-3-r2-security"
    assert reviewer_workflow_id(pr_id, 2, "performance", batch=1) == "pr-o-r-3-r2-performance-b1"
    assert synthesis_workflow_id(pr_id, 2) == "pr-o-r-3-r2-synthesis"
    assert fixer_workflow_id(pr_id, 1) == "pr-o-r-3-fix1"


def test_snapshot_key_lives_under_the_pr_prefix():
    prefix = snapshot_prefix("Owner", "Repo", 12)
    key = snapshot_key("Owner", "Repo", 12, "abc123")
    assert prefix == "owner/repo/pr-12/"
    assert key == "owner/repo/pr-12/abc123.tar.gz"
    assert key.startswith(prefix)
