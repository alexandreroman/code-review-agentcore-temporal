import json
from datetime import UTC, datetime, timedelta

from agentcore_review_router.dashboard import active_sessions, review_queries, snapshot_json
from agentcore_review_router.temporal_ops import Poller

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def seen(identity: str, seconds_ago: float) -> Poller:
    return Poller(identity, NOW - timedelta(seconds=seconds_ago))


def test_a_session_polling_both_task_types_counts_once():
    pollers = [seen("agentcore:build-1:session-a", 2), seen("agentcore:build-1:session-a", 4)]
    assert active_sessions(pollers, NOW) == 1


def test_stale_and_non_agentcore_pollers_do_not_count():
    pollers = [
        seen("agentcore:build-1:session-a", 5),
        seen("agentcore:build-1:session-b", 90),  # seen 90 s ago: gone, the server keeps pollers ~5 minutes
        seen("12345@laptop", 1),  # the local dev worker
    ]
    assert active_sessions(pollers, NOW) == 1


def test_review_queries_read_the_production_queue():
    queries = review_queries("review", NOW)
    assert set(queries) == {"running", "agents_running", "completed_24h"}
    assert all("TaskQueue = 'review'" in query for query in queries.values())
    assert "WorkflowType = 'PullRequestWorkflow' AND ExecutionStatus = 'Running'" in queries["running"]
    for name in (
        "ReviewerWorkflow",
        "FixerWorkflow",
        "SynthesisWorkflow",
        "DiscussionWorkflow",
        "ConversationWorkflow",
    ):
        assert f"'{name}'" in queries["agents_running"]


def test_completed_reviews_cover_the_last_24_hours_and_skip_continue_as_new():
    query = review_queries("review", NOW)["completed_24h"]
    assert "ExecutionStatus = 'Completed'" in query
    assert "CloseTime > '2026-09-30T12:00:00Z'" in query


def test_a_full_snapshot_carries_both_blocks():
    reviews = {"running": 1, "agents_running": 3, "completed_24h": 5}
    assert json.loads(snapshot_json(True, 2, reviews)) == {
        "deployed": True,
        "sessions": {"active": 2},
        "reviews": reviews,
    }


def test_a_failed_block_is_null():
    reviews = {"running": 0, "agents_running": 0, "completed_24h": 0}
    assert json.loads(snapshot_json(True, None, reviews)) == {"deployed": True, "sessions": None, "reviews": reviews}


def test_before_the_first_deployment_both_blocks_are_null():
    assert json.loads(snapshot_json(False, None, None)) == {"deployed": False, "sessions": None, "reviews": None}
