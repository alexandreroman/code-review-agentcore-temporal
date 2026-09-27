"""PullRequestWorkflow: one entity workflow per pull request, alive from the first push until the close.

It handles metadata only (paths, SHAs, snapshot keys, findings); patches and file contents stay in the
agents' child workflows. Continue-as-new happens between two rounds only, since it would terminate
running children, and carries the pending push and fix request over.
"""

import asyncio

from temporalio import workflow
from temporalio.exceptions import ActivityError, ChildWorkflowError

from agentcore_review_worker.workflows import policies
from agentcore_review_worker.workflows.fixer import FixerWorkflow
from agentcore_review_worker.workflows.reviewer import ReviewerWorkflow
from agentcore_review_worker.workflows.synthesis import SynthesisWorkflow

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import (
        PULL_REQUEST_WORKFLOW,
        SIGNAL_FIX_REQUESTED,
        SIGNAL_PR_CLOSED,
        SIGNAL_PR_UPDATED,
        Category,
        FixRequested,
        PrClosed,
        PrUpdated,
        PullRequestInput,
    )

    from agentcore_review_worker import lifecycle, publishing
    from agentcore_review_worker.batching import make_batches
    from agentcore_review_worker.models import (
        BatchInput,
        ChangeSet,
        CheckInput,
        ClosingInput,
        CommitResult,
        FixerInput,
        ListFilesInput,
        PublishInput,
        PullRequestOutcome,
        ResolveInput,
        ReviewContent,
        ReviewerInput,
        ReviewerReport,
        ReviewSummary,
        SnapshotInput,
        SnapshotRef,
        SynthesisInput,
    )


def _reviewer_workflow_id(pr_id: str, round_number: int, category: str, batch: int | None = None) -> str:
    suffix = f"-b{batch}" if batch is not None else ""
    return f"{pr_id}-r{round_number}-{category}{suffix}"


def _synthesis_workflow_id(pr_id: str, round_number: int) -> str:
    return f"{pr_id}-r{round_number}-synthesis"


def _fixer_workflow_id(pr_id: str, fix_number: int) -> str:
    return f"{pr_id}-fix{fix_number}"


@workflow.defn(name=PULL_REQUEST_WORKFLOW)
class PullRequestWorkflow:
    @workflow.init
    def __init__(self, input: PullRequestInput) -> None:
        # Signal-with-start delivers pr_updated before run() starts: the state must exist already.
        self._pr = input.pr
        self._state = input.state
        self._closed: PrClosed | None = None
        self._reviewing_sha: str | None = None

    @workflow.run
    async def run(self, input: PullRequestInput) -> PullRequestOutcome:
        self._memo("waiting for changes")
        while True:
            # Right after a round: moves to a newly deployed version, freeing old endpoints for make prune.
            await self._continue_as_new_if_needed()
            await workflow.wait_condition(lambda: self._next() is not None)
            await self._continue_as_new_if_needed()  # a deploy may have happened while waiting
            action = self._next()
            if action == "close":
                return await self._finish()
            if action == "review":
                await self._review()
            else:
                await self._fix()

    @workflow.signal(name=SIGNAL_PR_UPDATED)
    def pr_updated(self, update: PrUpdated) -> None:
        if not lifecycle.record_head(self._state, update.head_sha, self._reviewing_sha):
            workflow.logger.info("head %s ignored (delivery %s)", update.head_sha, update.delivery_id)

    @workflow.signal(name=SIGNAL_FIX_REQUESTED)
    def fix_requested(self, request: FixRequested) -> None:
        if not lifecycle.record_fix_request(self._state, request):
            workflow.logger.info("fix request ignored: delivery %s already seen", request.delivery_id)

    @workflow.signal(name=SIGNAL_PR_CLOSED)
    def pr_closed(self, closed: PrClosed) -> None:
        self._closed = self._closed or closed

    @property
    def _id(self) -> str:
        return workflow.info().workflow_id

    def _next(self) -> lifecycle.Action | None:
        return lifecycle.next_action(self._state, self._closed is not None)

    def _memo(self, phase: str) -> None:
        workflow.upsert_memo(lifecycle.memo(phase, self._state))

    async def _continue_as_new_if_needed(self) -> None:
        """Between rounds only: on a long history, or to move to a newly deployed worker version."""
        if self._closed is not None:
            return
        info = workflow.info()
        if not (info.is_continue_as_new_suggested() or info.is_target_worker_deployment_version_changed()):
            return
        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(
            PullRequestInput(pr=self._pr, state=self._state),
            initial_versioning_behavior=workflow.ContinueAsNewVersioningBehavior.AUTO_UPGRADE,
        )

    # --- review round ---

    async def _review(self) -> None:
        state = self._state
        state.pending_head_sha = None
        check: CheckInput | None = None
        phase = "waiting for changes"
        try:
            change = await workflow.execute_activity(
                "list_changed_files",
                ListFilesInput(pr=self._pr, since_sha=state.last_reviewed_sha),
                result_type=ChangeSet,
                **policies.LIST_CHANGED_FILES,
            )
            if change.head_sha == state.last_reviewed_sha:
                return  # a late signal for a head already reviewed
            state.round += 1
            self._reviewing_sha = change.head_sha
            self._memo(f"reviewing round {state.round}")
            check = CheckInput(
                pr=self._pr, head_sha=change.head_sha, external_id=f"{self._id}:{state.round}", status="in_progress"
            )
            reviewed = await self._run_round(change, check)
            if not reviewed:
                phase = f"round {state.round} unavailable, waiting for changes"
        # Child failures never reach this point: reviewers and synthesis handle their own.
        except ActivityError as error:
            if check is None:
                workflow.logger.error("changed files not listed: %s", error.cause or error)
                phase = "listing the changed files failed, waiting for changes"
            else:
                workflow.logger.error("round %d failed: %s", state.round, error.cause or error)
                phase = f"round {state.round} failed, waiting for changes"
                reason = f"Round {state.round} failed: {error.cause or error}. Push a commit to retry."
                try:
                    await self._complete_check(check, "failure", "AI Review failed", reason)
                except ActivityError as failure:
                    workflow.logger.warning(
                        "could not report the failed round on the check: %s", failure.cause or failure
                    )
        finally:
            self._reviewing_sha = None
            self._memo(phase)

    async def _run_round(self, change: ChangeSet, check: CheckInput) -> bool:
        """Review the change; False when no reviewer completed, which leaves the head unreviewed."""
        state, number = self._state, self._state.round
        if not change.files:
            state.last_reviewed_sha = change.head_sha
            await self._complete_check(check, *publishing.check_output(state.open_findings, []))
            return True
        snapshot = await self._snapshot(change.head_sha)
        title = f"Round {number}: reviewing {len(change.files)} files"
        await self._set_check(check.model_copy(update={"title": title}))
        reports, unavailable = await self._run_reviewers(change, snapshot)
        if not reports:
            # Publishing "no new finding" would pass a head nobody reviewed: the check fails instead.
            await self._complete_check(check, "failure", *publishing.unavailable_check_output(number, unavailable))
            return False
        # IDs are committed to the state only once the review is published.
        new, next_finding_number = lifecycle.number_findings(reports, state.next_finding_number)
        resolved = lifecycle.resolved_ids(reports)
        still_open = [f for f in state.open_findings if f.id not in resolved]
        summary = await self._summarize(
            SynthesisInput(
                new_findings=new,
                still_open=still_open,
                resolved_ids=resolved,
                unavailable=unavailable,
            )
        )
        kept = lifecycle.apply_summary(new, summary)
        content = ReviewContent(
            round=number,
            summary_markdown=summary.summary_markdown,
            findings=kept,
            resolved_ids=resolved,
            still_open=still_open,
            excluded=change.excluded,
            unavailable=unavailable,
        )
        comment_ids = await self._publish(
            PublishInput(pr=self._pr, head_sha=change.head_sha, workflow_id=self._id, content=content)
        )
        state.next_finding_number = next_finding_number
        state.open_findings = still_open + [f.model_copy(update={"comment_id": comment_ids.get(f.id)}) for f in kept]
        state.last_reviewed_sha = change.head_sha
        if resolved:
            await self._resolve(resolved)
        await self._complete_check(check, *publishing.check_output(state.open_findings, unavailable))
        return True

    async def _run_reviewers(self, change: ChangeSet, snapshot: SnapshotRef) -> tuple[list[ReviewerReport], list[str]]:
        """One reviewer per (category, batch), at most max_parallel_agents at a time; a failed one is skipped."""
        number = self._state.round
        batches = make_batches(change.files)
        jobs: list[tuple[str, str, ReviewerInput]] = []
        for category in Category:
            open_in_category = [f for f in self._state.open_findings if f.category == category]
            for index, batch in enumerate(batches, start=1):
                batch_number = index if len(batches) > 1 else None
                label = str(category) if batch_number is None else f"{category} (batch {index})"
                reviewer = ReviewerInput(
                    category=category,
                    snapshot=snapshot,
                    batch=BatchInput(
                        pr=self._pr, diff_base=change.diff_base, head_sha=change.head_sha, paths=[f.path for f in batch]
                    ),
                    open_findings=open_in_category,
                )
                jobs.append((_reviewer_workflow_id(self._id, number, category, batch_number), label, reviewer))
        slots = asyncio.Semaphore(change.max_parallel_agents)

        async def review(child_id: str, label: str, reviewer: ReviewerInput) -> ReviewerReport:
            async with slots:
                return await workflow.execute_child_workflow(
                    ReviewerWorkflow.run,
                    reviewer,
                    id=child_id,
                    run_timeout=policies.CHILD_RUN_TIMEOUT,
                    static_summary=f"{label} reviewer",
                )

        results = await asyncio.gather(*(review(*job) for job in jobs), return_exceptions=True)
        reports: list[ReviewerReport] = []
        unavailable: list[str] = []
        for (_, label, _), result in zip(jobs, results, strict=True):
            if isinstance(result, ChildWorkflowError):
                workflow.logger.warning("%s reviewer unavailable: %s", label, result.cause or result)
                unavailable.append(label)
            elif isinstance(result, BaseException):
                raise result
            else:
                reports.append(result)
        return reports, unavailable

    async def _summarize(self, input: SynthesisInput) -> ReviewSummary:
        if not input.new_findings:
            return lifecycle.fallback_summary(input)
        try:
            return await workflow.execute_child_workflow(
                SynthesisWorkflow.run,
                input,
                id=_synthesis_workflow_id(self._id, self._state.round),
                run_timeout=policies.CHILD_RUN_TIMEOUT,
                static_summary="synthesis",
            )
        except ChildWorkflowError as error:
            workflow.logger.warning("synthesis failed, deterministic merge instead: %s", error.cause or error)
            return lifecycle.fallback_summary(input)

    async def _publish(self, input: PublishInput) -> dict[str, int]:
        """The IDs of the inline comments, by finding ID."""
        try:
            return await workflow.execute_activity(
                "publish_review", input, result_type=dict[str, int], **policies.PUBLISH_REVIEW
            )
        except ActivityError as error:
            if not policies.failed_with(error, "GitHubUnprocessable"):
                raise
            workflow.logger.warning("GitHub refused the inline comments: every finding goes into the review body")
            return await workflow.execute_activity(
                "publish_review",
                input.model_copy(update={"inline": False}),
                result_type=dict[str, int],
                **policies.PUBLISH_REVIEW,
            )

    async def _resolve(self, finding_ids: list[str]) -> None:
        try:
            await workflow.execute_activity(
                "resolve_threads",
                ResolveInput(pr=self._pr, finding_ids=finding_ids),
                result_type=int,
                **policies.RESOLVE_THREADS,
            )
        except ActivityError as error:
            workflow.logger.warning("threads of %s not resolved: %s", finding_ids, error.cause or error)

    async def _snapshot(self, sha: str) -> SnapshotRef:
        try:
            return await workflow.execute_activity(
                "snapshot_repo", SnapshotInput(pr=self._pr, sha=sha), result_type=SnapshotRef, **policies.SNAPSHOT_REPO
            )
        except ActivityError as error:
            if not policies.failed_with(error, "SnapshotTooLarge"):
                raise
            # No snapshot: the tools read through the GitHub API instead.
            pr = self._pr
            return SnapshotRef(owner=pr.owner, repo=pr.repo, installation_id=pr.installation_id, sha=sha)

    async def _set_check(self, check: CheckInput) -> None:
        await workflow.execute_activity("set_check", check, **policies.SET_CHECK)

    async def _complete_check(self, check: CheckInput, conclusion: str, title: str, summary: str) -> None:
        update = {"status": "completed", "conclusion": conclusion, "title": title, "summary": summary}
        await self._set_check(check.model_copy(update=update))

    # --- fix ---

    async def _fix(self) -> None:
        state = self._state
        request, state.pending_fix = state.pending_fix, None
        assert request is not None
        if not state.open_findings or state.last_reviewed_sha is None:
            workflow.logger.info("fix requested by %s ignored: no open finding", request.requested_by)
            return
        state.fix_count += 1
        self._memo(f"fixing for @{request.requested_by}")
        try:
            snapshot = await self._snapshot(state.last_reviewed_sha)
            fixer = FixerInput(
                pr=self._pr,
                workflow_id=self._id,
                fix_number=state.fix_count,
                expected_head_sha=state.last_reviewed_sha,
                snapshot=snapshot,
                findings=state.open_findings,
            )
            result: CommitResult = await workflow.execute_child_workflow(
                FixerWorkflow.run,
                fixer,
                id=_fixer_workflow_id(self._id, state.fix_count),
                run_timeout=policies.CHILD_RUN_TIMEOUT,
                static_summary="fixer",
            )
            # The commit's synchronize webhook brings the incremental round; the bot's commit never asks for a fix.
            workflow.logger.info("fix %d pushed as %s (rejected: %s)", state.fix_count, result.sha, result.rejected)
            self._memo("fix pushed, waiting for its review")
        except (ActivityError, ChildWorkflowError) as error:
            workflow.logger.error("fix %d failed: %s", state.fix_count, error.cause or error)
            self._memo("fix failed, waiting for changes")

    # --- end ---

    async def _finish(self) -> PullRequestOutcome:
        closed = self._closed
        assert closed is not None
        self._memo("merged" if closed.merged else "closed")
        if closed.merged and self._state.open_findings:
            body = publishing.closing_comment(closed.closed_by, self._state.open_findings)
            try:
                await workflow.execute_activity(
                    "post_closing_comment",
                    ClosingInput(pr=self._pr, workflow_id=self._id, body=body),
                    **policies.POST_CLOSING_COMMENT,
                )
            except ActivityError as error:
                workflow.logger.warning("closing comment not posted: %s", error.cause or error)
        try:
            await workflow.execute_activity("delete_snapshots", self._pr, result_type=int, **policies.DELETE_SNAPSHOTS)
        except ActivityError as error:
            workflow.logger.warning("snapshots not deleted (the S3 lifecycle rule will): %s", error.cause or error)
        return PullRequestOutcome(
            merged=closed.merged,
            closed_by=closed.closed_by,
            open_findings=self._state.open_findings,
            rounds=self._state.round,
        )
