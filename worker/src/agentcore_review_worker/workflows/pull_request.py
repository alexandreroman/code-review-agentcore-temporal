"""PullRequestWorkflow: one entity workflow per pull request, alive from the first push until the close.

It handles metadata only (paths, SHAs, snapshot keys, findings); patches and file contents stay in the
agents' child workflows. Continue-as-new happens between two rounds only, since it would terminate
running children, and carries the pending push, fix requests and thread replies over.

An idle pull request gets a warning comment, then is closed: a durable timer waits for the next deadline,
counted from the start of the idle period kept in the state.

A new run under the same workflow ID (a reopened pull request, or after a failed run) takes over the earlier run's
numbering and finding threads.

With TRACING=on, each action (a round, a fix, a reply, an idle step, the close) is a trace of its own, linked to
the signals that queued it: in the run's context, every action would join the trace of the webhook that started the
run, open as long as the pull request.
"""

import asyncio
import contextlib
from collections import defaultdict
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

from agentcore_review_worker.workflows import policies
from agentcore_review_worker.workflows.discussion import DiscussionWorkflow
from agentcore_review_worker.workflows.fixer import FixerWorkflow
from agentcore_review_worker.workflows.reviewer import ReviewerWorkflow
from agentcore_review_worker.workflows.synthesis import SynthesisWorkflow

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import (
        PULL_REQUEST_WORKFLOW,
        SIGNAL_COMMENT_POSTED,
        SIGNAL_FIX_REQUESTED,
        SIGNAL_PR_CLOSED,
        SIGNAL_PR_UPDATED,
        Category,
        CommentPosted,
        FixRequested,
        PrClosed,
        PrUpdated,
    )

    # The process's own opentelemetry, shared with Strands and the plugin (a sandboxed copy has its own context and
    # provider), with or without OpenTelemetryPlugin, which passes it through only when tracing is on.
    from opentelemetry import trace
    from opentelemetry.context import Context

    from agentcore_review_worker import lifecycle, markers, publishing, summaries
    from agentcore_review_worker.batching import make_batches
    from agentcore_review_worker.models import (
        BatchInput,
        ChangeSet,
        CheckInput,
        CheckOutput,
        CommentInput,
        CommitResult,
        DiscussionInput,
        DiscussionReply,
        FixerInput,
        ListFilesInput,
        PublishInput,
        PullRequestOutcome,
        PullRequestRunInput,
        RecoveredCounters,
        RecoveryInput,
        ResolveInput,
        ReviewContent,
        ReviewerInput,
        ReviewerReport,
        ReviewSummary,
        SnapshotInput,
        SnapshotRef,
        SynthesisInput,
        ThreadInput,
        ThreadRead,
        ThreadReplyInput,
    )

# A no-op tracer unless OpenTelemetryPlugin's replay-safe provider is installed. Spans add no command to the history.
tracer = trace.get_tracer(__name__)


def _error_type(error: BaseException) -> str | None:
    """The type of the first ApplicationError behind a failure: GitHubUnprocessable, or BranchMoved behind a child's."""
    cause = error.__cause__
    while cause is not None and not isinstance(cause, ApplicationError):
        cause = cause.__cause__
    return cause.type if cause is not None else None


@workflow.defn(name=PULL_REQUEST_WORKFLOW)
class PullRequestWorkflow:
    @workflow.init
    def __init__(self, input: PullRequestRunInput) -> None:
        # Signal-with-start delivers pr_updated before run() starts: the state must exist already.
        self._input = input
        self._pr = input.pr
        self._state = input.state
        self._closed: PrClosed | None = None
        self._reviewing_sha: str | None = None
        self._phase = ""  # shown in Temporal UI, restored once a reply is answered
        # The spans of the signals behind the pending work, by action ("reply <comment ID>" for a reply). Worker
        # memory only, never in the state: a replay captures them again, a continue-as-new drops them.
        self._signal_links: defaultdict[str, list[trace.Link]] = defaultdict(list)

    @workflow.run
    async def run(self, input: PullRequestRunInput) -> PullRequestOutcome:
        # A started run has an empty state; a continued one carries its counters over, and must not recover them.
        if workflow.info().continued_run_id is None:
            await self._take_over_earlier_run()
        self._set_phase("waiting for changes")
        if self._state.idle_since is None:  # a start without the pr_updated signal (e.g. a manual start)
            lifecycle.start_idle(self._state, workflow.now())
        while True:
            # After an action or an idle timer: moves to a newly deployed version, freeing old endpoints for
            # make prune.
            await self._continue_as_new_if_needed()
            action = self._next()
            if action is None:
                outcome = await self._idle()
                if outcome is not None:
                    return outcome
                continue
            if action == "close":
                with self._trace_action("Close", "close"):
                    return await self._finish()
            if action == "review":
                with self._trace_action("Review", "review"):
                    await self._review()
            elif action == "fix":
                with self._trace_action("Fix", "fix"):
                    await self._fix()
            else:
                reply_key = f"reply {self._state.pending_replies[0].comment_id}"
                with self._trace_action("Reply", reply_key):
                    await self._reply()
            # Time spent in an action is never idle: the countdown starts when it ends.
            lifecycle.start_idle(self._state, workflow.now())

    @workflow.signal(name=SIGNAL_PR_UPDATED)
    def pr_updated(self, update: PrUpdated) -> None:
        lifecycle.start_idle(self._state, workflow.now())
        if lifecycle.record_head(self._state, update.head_sha, self._reviewing_sha):
            self._link_signal("review")
        else:
            workflow.logger.info("head %s ignored (delivery %s)", update.head_sha, update.delivery_id)

    @workflow.signal(name=SIGNAL_FIX_REQUESTED)
    def fix_requested(self, request: FixRequested) -> None:
        lifecycle.start_idle(self._state, workflow.now())
        if lifecycle.record_fix_request(self._state, request):
            self._link_signal("fix")
        else:
            workflow.logger.info("fix request ignored: delivery %s already seen", request.delivery_id)

    @workflow.signal(name=SIGNAL_COMMENT_POSTED)
    def comment_posted(self, reply: CommentPosted) -> None:
        lifecycle.start_idle(self._state, workflow.now())
        queue_full = len(self._state.pending_replies) >= lifecycle.MAX_PENDING_REPLIES
        if lifecycle.record_reply(self._state, reply):
            self._link_signal(f"reply {reply.comment_id}")
            if queue_full:
                workflow.logger.warning("reply queue full: the oldest queued reply is dropped")
            workflow.logger.info("reply by %s queued (thread %d)", reply.author, reply.thread_root_id)
        else:
            workflow.logger.info("reply ignored: delivery %s already seen", reply.delivery_id)

    @workflow.signal(name=SIGNAL_PR_CLOSED)
    def pr_closed(self, closed: PrClosed) -> None:
        if self._closed is None:
            self._closed = closed
            self._link_signal("close")

    @property
    def _id(self) -> str:
        return workflow.info().workflow_id

    def _next(self) -> lifecycle.Action | None:
        return lifecycle.next_action(self._state, self._closed is not None)

    def _link_signal(self, key: str) -> None:
        """Keep the span of the signal being handled (HandleSignal, under the router's webhook) for the action."""
        self._signal_links[key].append(trace.Link(trace.get_current_span().get_span_context()))

    def _trace_action(self, name: str, key: str | None = None) -> contextlib.AbstractContextManager[trace.Span]:
        """A root span, linked to the signals kept under key; the action may rename it once it knows its number."""
        links = self._signal_links.pop(key, []) if key is not None else []
        return tracer.start_as_current_span(
            name, context=Context(), links=links, attributes={"temporalWorkflowID": self._id}
        )

    def _set_phase(self, phase: str) -> None:
        """Show the phase in Temporal UI: in the memo, readable without a worker, and in the current details.

        A continue-as-new drops the current details: the new run sets them again when it starts.
        """
        self._phase = phase
        workflow.upsert_memo(lifecycle.memo(phase, self._state))
        self._show_details()

    def _show_details(self) -> None:
        """Show the open findings as they change within a phase (a published round, a dismissal).

        Current details only: they add no command to the history, unlike a memo upsert, so they can change anywhere
        within a phase.
        """
        workflow.set_current_details(lifecycle.current_details(self._phase, self._state))

    async def _continue_as_new_if_needed(self) -> None:
        """Between rounds only: on a long history, or to move to a newly deployed worker version."""
        if self._closed is not None:
            return
        info = workflow.info()
        if not (info.is_continue_as_new_suggested() or info.is_target_worker_deployment_version_changed()):
            return
        # A safeguard: the handlers are synchronous, but a running one would lose its work to the continue-as-new.
        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(
            self._input.model_copy(update={"state": self._state}),
            # The next run starts on the task queue's current deployment version, not on the one this run is pinned to.
            initial_versioning_behavior=workflow.ContinueAsNewVersioningBehavior.AUTO_UPGRADE,
        )

    async def _take_over_earlier_run(self) -> None:
        """Continue the numbering an earlier run of this workflow ID left on GitHub, then close its open threads.

        A reopen is announced in between, before the slow part: closing the threads and the new round.

        Numbering from 1 again would collide with that run's round markers, finding IDs and Review-Fix trailers.
        """
        await self._recover_counters()
        # Only a reopen is announced: a run that replaces a failed one takes over silently.
        if self._input.reopened:
            await self._announce_reopen()
        # Without an earlier round there is no earlier finding thread: a new pull request skips the closing.
        if self._state.round > 0:
            await self._close_earlier_threads()

    async def _recover_counters(self) -> None:
        try:
            recovered: RecoveredCounters = await workflow.execute_activity(
                "RecoverCounters",
                RecoveryInput(pr=self._pr, workflow_id=self._id),
                result_type=RecoveredCounters,
                summary=summaries.pull_request(self._pr.number),
                **policies.MULTI_CALL,
            )
        except ActivityError as error:
            # The review goes on, numbered from 1. On a reopened pull request, round 1 then finds the earlier run's
            # review by its marker and publishes nothing, and its new findings are linked to the earlier threads.
            workflow.logger.warning("earlier numbering not recovered: %s", error.cause or error)
            return
        self._state.round = recovered.last_round
        self._state.last_finding_numbers = recovered.last_finding_numbers
        self._state.fix_count = recovered.last_fix_number
        workflow.logger.info("numbering continues after %s", recovered)

    async def _announce_reopen(self) -> None:
        """Best effort: closing the earlier threads and the new round take minutes, the author learns why at once."""
        # Keyed on the run: a retry posts nothing more, and each reopen gets its own comment.
        marker = markers.reopen_marker(self._id, workflow.info().run_id)
        body = publishing.reopen_comment(self._state.round, marker)
        try:
            await self._post_comment(body, marker, "reopen")
        except ActivityError as error:
            workflow.logger.warning("reopen comment not posted: %s", error.cause or error)

    async def _close_earlier_threads(self) -> None:
        """Best effort: an earlier finding thread left open only misleads a reader, the new review goes on."""
        try:
            closed: int = await workflow.execute_activity(
                "CloseEarlierThreads",
                RecoveryInput(pr=self._pr, workflow_id=self._id),
                result_type=int,
                summary=summaries.pull_request(self._pr.number),
                **policies.GITHUB_THREADS,
            )
        except ActivityError as error:
            workflow.logger.warning("earlier finding threads not closed: %s", error.cause or error)
            return
        workflow.logger.info("%d earlier finding threads closed", closed)

    # --- idle pull request ---

    async def _idle(self) -> PullRequestOutcome | None:
        """Wait for the next action until the idle timer's next deadline; once due, warn, or close.

        None when the loop goes on: an action is pending, a deadline has come, or the close failed.
        """
        timer = lifecycle.idle_timer(
            self._state, workflow.now(), self._input.idle_warning_seconds, self._input.idle_close_seconds
        )
        if timer.left > timedelta(0):
            # A timeout means the deadline has passed: the next turn of the loop acts on it.
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self._next() is not None, timeout=timer.left, timeout_summary=f"idle {timer.step}"
                )
            return None
        if timer.step == "warning":
            with self._trace_action("Idle warning"):
                await self._warn_idle(timer.since)
            return None
        with self._trace_action("Idle close"):
            return await self._close_idle(timer.since)

    async def _warn_idle(self, since: datetime) -> None:
        # Marked before the comment: a signal during the post starts a new period, which gets its own warning.
        self._state.idle_warned = True
        marker = markers.idle_warning_marker(self._id, since)
        body = publishing.idle_warning_comment(self._input.idle_warning_seconds, self._input.idle_close_seconds, marker)
        try:
            await self._post_comment(body, marker, "idle warning")
        except ActivityError as error:
            workflow.logger.warning("idle warning not posted: %s", error.cause or error)

    async def _close_idle(self, since: datetime) -> PullRequestOutcome | None:
        """Close the idle pull request and end; None when GitHub refused, which starts a new idle period."""
        state = self._state
        try:
            await workflow.execute_activity("ClosePR", self._pr, summary="inactivity", **policies.GITHUB_CALL)
        except ActivityError as error:
            workflow.logger.error("pull request not closed for inactivity: %s", error.cause or error)
            lifecycle.start_idle(state, workflow.now())
            return None
        # GitHub's closed webhook signals this run while it ends, or finds none: harmless either way.
        self._set_phase("closed for inactivity")
        marker = markers.idle_close_marker(self._id, since)
        body = publishing.idle_close_comment(self._input.idle_close_seconds, marker)
        try:
            await self._post_comment(body, marker, "idle close")
        except ActivityError as error:
            workflow.logger.warning("inactivity comment not posted: %s", error.cause or error)
        await self._delete_snapshots()
        return PullRequestOutcome(
            merged=False,
            closed_by=None,
            open_findings=state.open_findings,
            rounds=state.round,
            closed_for_inactivity=True,
        )

    # --- review round ---

    async def _review(self) -> None:
        state = self._state
        state.pending_head_sha = None
        phase = "waiting for changes"
        try:
            change = await workflow.execute_activity(
                "ListFiles",
                ListFilesInput(pr=self._pr, since_sha=state.last_reviewed_sha),
                result_type=ChangeSet,
                summary=summaries.list_files(state.last_reviewed_sha),
                **policies.MULTI_CALL,
            )
            if change.head_sha == state.last_reviewed_sha:
                return  # a late signal for a head already reviewed
            state.round += 1
            trace.get_current_span().update_name(f"Review round {state.round}")
            self._reviewing_sha = change.head_sha
            self._set_phase(f"reviewing round {state.round}")
            reviewed = await self._run_round(change)
            if not reviewed:
                phase = f"round {state.round} unavailable, waiting for changes"
        # Child failures never reach this point: reviewers and synthesis handle their own. Neither does a failure
        # after the review is published: the round stands.
        except ActivityError as error:
            if self._reviewing_sha is None:  # the round has not started
                workflow.logger.error("changed files not listed: %s", error.cause or error)
                phase = "listing the changed files failed, waiting for changes"
            else:
                workflow.logger.error("round %d failed: %s", state.round, error.cause or error)
                phase = f"round {state.round} failed, waiting for changes"
                reason = f"Round {state.round} failed: {error.cause or error}. Push a commit to retry."
                output = CheckOutput(conclusion="failure", title="AI Review failed", summary=reason)
                try:
                    await self._complete_check(self._reviewing_sha, state.round, output)
                except ActivityError as failure:
                    workflow.logger.warning(
                        "could not report the failed round on the check: %s", failure.cause or failure
                    )
        finally:
            self._reviewing_sha = None
            self._set_phase(phase)

    async def _run_round(self, change: ChangeSet) -> bool:
        """Review the change; False when no reviewer completed, which leaves the head unreviewed."""
        state, number = self._state, self._state.round
        if not change.files:
            # No review is published for this round: only the check can report the files GitHub did not list.
            state.last_reviewed_sha = change.head_sha
            state.last_reviewed_round = number
            output = publishing.check_output(state.open_findings, unlisted=change.unlisted)
            await self._complete_check_best_effort(change.head_sha, number, output)
            return True
        snapshot = await self._snapshot(change.head_sha)
        title = f"Round {number}: reviewing {summaries.count(len(change.files), 'file')}"
        in_progress = CheckInput(
            pr=self._pr, head_sha=change.head_sha, external_id=self._check_id(number), status="in_progress", title=title
        )
        await self._update_check(in_progress, number)
        reports, unavailable = await self._run_reviewers(change, snapshot)
        if not reports:
            # Publishing "no new finding" would pass a head nobody reviewed: the check fails instead.
            output = publishing.unavailable_check_output(number, unavailable)
            await self._complete_check(change.head_sha, number, output)
            return False
        # IDs are committed to the state only once the review is published.
        new, last_finding_numbers = lifecycle.number_findings(reports, state.last_finding_numbers)
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
            unlisted=change.unlisted,
            unavailable=unavailable,
        )
        comment_ids = await self._publish(
            PublishInput(
                pr=self._pr,
                pr_base_sha=change.pr_base_sha,
                head_sha=change.head_sha,
                workflow_id=self._id,
                content=content,
            )
        )
        state.last_finding_numbers = last_finding_numbers
        lifecycle.record_resolved(state, resolved)
        state.open_findings = still_open + [f.model_copy(update={"comment_id": comment_ids.get(f.id)}) for f in kept]
        self._show_details()
        state.last_reviewed_sha = change.head_sha
        state.last_reviewed_round = number
        if resolved:
            await self._resolve(resolved)
        output = publishing.check_output(state.open_findings, unavailable=unavailable, unlisted=change.unlisted)
        await self._complete_check_best_effort(change.head_sha, number, output)
        return True

    async def _run_reviewers(self, change: ChangeSet, snapshot: SnapshotRef) -> tuple[list[ReviewerReport], list[str]]:
        """One reviewer per (category, batch), at most max_parallel_agents at a time; a failed one is skipped."""
        number = self._state.round
        batches = make_batches(change.files)
        fix_round = lifecycle.is_fix_round(self._state, change)
        if fix_round:
            workflow.logger.info("round %d reviews fix commit %s", number, change.head_sha)
        jobs: list[tuple[str, str, ReviewerInput]] = []
        for category in Category:
            open_in_category = [f for f in self._state.open_findings if f.category == category]
            dismissed_in_category = [d for d in self._state.dismissed_findings if d.finding.category == category]
            for index, batch in enumerate(batches, start=1):
                if len(batches) > 1:
                    child_id = f"{self._id}-r{number}-{category}-b{index}"
                    label = f"{category} (batch {index})"
                else:
                    child_id = f"{self._id}-r{number}-{category}"
                    label = str(category)
                reviewer = ReviewerInput(
                    category=category,
                    snapshot=snapshot,
                    batch=BatchInput(
                        pr=self._pr, diff_base=change.diff_base, head_sha=change.head_sha, paths=[f.path for f in batch]
                    ),
                    open_findings=open_in_category,
                    dismissed_findings=dismissed_in_category,
                    fix_round=fix_round,
                )
                jobs.append((child_id, label, reviewer))
        slots = asyncio.Semaphore(change.max_parallel_agents)

        async def review(child_id: str, label: str, reviewer: ReviewerInput) -> ReviewerReport:
            async with slots:
                return await workflow.execute_child_workflow(
                    ReviewerWorkflow.run,
                    reviewer,
                    id=child_id,
                    run_timeout=policies.CHILD_RUN_TIMEOUT,
                    static_summary=label,
                    static_details=summaries.file_list(reviewer.batch.paths),
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
                id=f"{self._id}-r{self._state.round}-synthesis",
                run_timeout=policies.CHILD_RUN_TIMEOUT,
                static_summary=f"round {self._state.round}",
                static_details=summaries.synthesis_details(input),
            )
        except ChildWorkflowError as error:
            workflow.logger.warning("synthesis failed, deterministic merge instead: %s", error.cause or error)
            return lifecycle.fallback_summary(input)

    async def _publish(self, input: PublishInput) -> dict[str, int]:
        """The IDs of the inline comments, by finding ID."""

        async def publish(attempt: PublishInput) -> dict[str, int]:
            content = attempt.content
            return await workflow.execute_activity(
                "PublishReview",
                attempt,
                result_type=dict[str, int],
                summary=summaries.publish(content.round, len(content.findings), inline=attempt.inline),
                **policies.SLOW_TRANSFER,
            )

        try:
            return await publish(input)
        except ActivityError as error:
            if _error_type(error) != "GitHubUnprocessable":
                raise
            workflow.logger.warning("GitHub refused the inline comments: every finding goes into the review body")
            return await publish(input.model_copy(update={"inline": False}))

    async def _resolve(self, finding_ids: list[str]) -> None:
        try:
            await workflow.execute_activity(
                "ResolveThreads",
                ResolveInput(pr=self._pr, finding_ids=finding_ids),
                summary=summaries.finding_ids(finding_ids),
                **policies.GITHUB_THREADS,
            )
        except ActivityError as error:
            workflow.logger.warning("threads of %s not resolved: %s", finding_ids, error.cause or error)

    async def _snapshot(self, sha: str) -> SnapshotRef:
        try:
            return await workflow.execute_activity(
                "Snapshot",
                SnapshotInput(pr=self._pr, sha=sha),
                result_type=SnapshotRef,
                summary=summaries.short_sha(sha),
                **policies.SLOW_TRANSFER,
            )
        except ActivityError as error:
            if _error_type(error) != "SnapshotTooLarge":
                raise
            # No snapshot: the tools read through the GitHub API instead.
            return SnapshotRef(pr=self._pr, sha=sha)

    def _check_id(self, round_number: int) -> str:
        """The external ID that finds the check run of a round again."""
        return f"{self._id}:{round_number}"

    async def _update_check(self, check: CheckInput, round_number: int) -> None:
        summary = summaries.check(round_number, check.status, check.conclusion)
        await workflow.execute_activity("UpdateCheck", check, summary=summary, **policies.GITHUB_CALL)

    async def _complete_check(self, head_sha: str, round_number: int, output: CheckOutput) -> None:
        check = CheckInput(
            pr=self._pr,
            head_sha=head_sha,
            external_id=self._check_id(round_number),
            status="completed",
            conclusion=output.conclusion,
            title=output.title,
            summary=output.summary,
        )
        await self._update_check(check, round_number)

    async def _complete_check_best_effort(self, head_sha: str, round_number: int, output: CheckOutput) -> None:
        """Once the round is recorded in the state: a check left in progress misleads, but the round stands."""
        try:
            await self._complete_check(head_sha, round_number, output)
        except ActivityError as error:
            workflow.logger.warning("check of round %d not completed: %s", round_number, error.cause or error)

    # --- fix ---

    async def _fix(self) -> None:
        """One fixer run for every accepted /fix request; each refused one gets its own explanation."""
        state = self._state
        requests, state.pending_fixes = state.pending_fixes, []
        triage = lifecycle.triage_fixes(state, requests)
        for root in triage.closed_threads:
            # Keyed on the thread: a /fix in a closed thread gets this answer once.
            await self._answer_closed_thread(root, markers.reply_marker(self._id, root))
        for refusal in triage.refusals:
            await self._refuse_fix(refusal)
        if not triage.findings:
            if triage.accepted:
                accepted_by = [r.requested_by for r in triage.accepted]
                workflow.logger.info("fix requests of %s ignored: no open finding", accepted_by)
            return
        assert state.last_reviewed_sha is not None  # a finding is open only after a published round
        requested_by = triage.accepted[-1].requested_by
        state.fix_count += 1
        trace.get_current_span().update_name(f"Fix {state.fix_count}")
        self._set_phase(f"fixing for @{requested_by}")
        try:
            snapshot = await self._snapshot(state.last_reviewed_sha)
            fixer = FixerInput(
                pr=self._pr,
                workflow_id=self._id,
                fix_number=state.fix_count,
                expected_head_sha=state.last_reviewed_sha,
                snapshot=snapshot,
                findings=triage.findings,
            )
            result: CommitResult = await workflow.execute_child_workflow(
                FixerWorkflow.run,
                fixer,
                id=f"{self._id}-fix{state.fix_count}",
                run_timeout=policies.CHILD_RUN_TIMEOUT,
                static_summary=summaries.finding_ids([f.id for f in triage.findings]),
                static_details=summaries.finding_list(triage.findings),
            )
            # The commit's synchronize webhook starts the next round, which reviews this fix alone.
            state.last_fix_sha = result.sha
            workflow.logger.info("fix %d pushed as %s (rejected: %s)", state.fix_count, result.sha, result.rejected)
            self._set_phase("fix pushed, waiting for its review")
        except (ActivityError, ChildWorkflowError) as error:
            workflow.logger.error("fix %d failed: %s", state.fix_count, error.cause or error)
            await self._explain_failed_fix(state.fix_count, _error_type(error))
            self._set_phase("fix failed, waiting for changes")

    async def _explain_failed_fix(self, fix_number: int, error_type: str | None) -> None:
        """Tell in the Conversation that the fix pushed nothing, and how to retry when a retry can help."""
        marker = markers.fix_failure_marker(self._id, workflow.info().first_execution_run_id, fix_number)
        body = publishing.failed_fix_comment(fix_number, error_type, marker)
        try:
            await self._post_comment(body, marker, f"fix {fix_number} failed")
        except ActivityError as error:
            workflow.logger.warning("fix failure not posted: %s", error.cause or error)

    async def _refuse_fix(self, refusal: lifecycle.FixRefusal) -> None:
        """Explain a refused /fix where it was posted: in its thread, or in the Conversation."""
        request = refusal.request
        marker = markers.fix_refusal_marker(self._id, request.delivery_id)
        workflow.logger.info("fix request of %s refused (delivery %s)", request.requested_by, request.delivery_id)
        try:
            if refusal.thread_finding_id is not None and request.thread_root_id is not None:
                body = publishing.off_thread_fix_reply(refusal.thread_finding_id, request.finding_ids, marker)
                await self._post_reply(request.thread_root_id, body, marker, refusal.thread_finding_id)
            else:
                body = publishing.not_open_fix_comment(refusal.not_open_ids, self._state.open_findings, marker)
                await self._post_comment(body, marker, "fix refused")
        except ActivityError as error:
            workflow.logger.warning("fix refusal not posted: %s", error.cause or error)

    # --- discussion in a finding's thread ---

    async def _reply(self) -> None:
        """Answer the oldest queued reply; a dismissal also resolves the thread and recomputes the check."""
        state = self._state
        reply = state.pending_replies.pop(0)
        marker = markers.reply_marker(self._id, reply.comment_id)
        finding = lifecycle.open_finding_in_thread(state, reply.thread_root_id)
        if finding is None:
            await self._answer_closed_thread(reply.thread_root_id, marker)
            return
        trace.get_current_span().update_name(f"Reply {finding.id}")
        phase = self._phase
        self._set_phase(f"answering @{reply.author} on {finding.id}")
        try:
            thread: ThreadRead = await workflow.execute_activity(
                "ReadThread",
                ThreadInput(pr=self._pr, thread_root_id=reply.thread_root_id),
                result_type=ThreadRead,
                summary=finding.id,
                **policies.GITHUB_CALL,
            )
            if publishing.bot_answers(thread.comments, thread.bot_login) >= lifecycle.MAX_BOT_REPLIES_PER_THREAD:
                await self._post_reply(reply.thread_root_id, publishing.budget_reply(marker), marker, finding.id)
                return
            assert state.last_reviewed_sha is not None  # a finding is open only after a published round
            snapshot = await self._snapshot(state.last_reviewed_sha)
            comments = lifecycle.discussion_thread(thread.comments, thread.bot_login, reply.author, reply.comment_id)
            state.discussion_count += 1
            number = state.discussion_count
            try:
                answer: DiscussionReply = await workflow.execute_child_workflow(
                    DiscussionWorkflow.run,
                    DiscussionInput(finding=finding, thread=comments, author=reply.author, snapshot=snapshot),
                    id=f"{self._id}-discussion-{number}",
                    run_timeout=policies.CHILD_RUN_TIMEOUT,
                    static_summary=finding.id,
                    static_details=f"{summaries.finding_line(finding)}\n\nReply by @{reply.author}",
                )
            except ChildWorkflowError as error:
                workflow.logger.error("discussion %d failed: %s", number, error.cause or error)
                await self._post_reply(reply.thread_root_id, publishing.failed_reply(marker), marker, finding.id)
                return
            body = publishing.reply_body(finding.id, answer, marker)
            await self._post_reply(reply.thread_root_id, body, marker, finding.id)
            if answer.verdict == "dismiss":
                lifecycle.dismiss(state, finding.id, answer.answer, reply.author)
                self._show_details()
                await self._resolve([finding.id])
                await self._refresh_check()
        except ActivityError as error:
            workflow.logger.error("reply to %s on %s failed: %s", reply.author, finding.id, error.cause or error)
        finally:
            self._set_phase(phase)

    async def _answer_closed_thread(self, thread_root_id: int, marker: str) -> None:
        """A reply or /fix in the thread of a dismissed or resolved finding: a short answer, no agent.

        Any other thread is not a finding of this pull request: it is left alone.
        """
        finding_id = lifecycle.closed_finding_id(self._state, thread_root_id)
        if finding_id is None:
            return
        try:
            body = publishing.no_longer_open_reply(finding_id, marker)
            await self._post_reply(thread_root_id, body, marker, finding_id)
        except ActivityError as error:
            workflow.logger.warning("no-longer-open answer not posted: %s", error.cause or error)

    async def _post_reply(self, thread_root_id: int, body: str, marker: str, finding_id: str) -> None:
        """Reply in the thread of finding_id, which labels the activity in Temporal UI."""
        await workflow.execute_activity(
            "ReplyInThread",
            ThreadReplyInput(pr=self._pr, thread_root_id=thread_root_id, body=body, marker=marker),
            summary=finding_id,
            **policies.GITHUB_CALL,
        )

    async def _post_comment(self, body: str, marker: str, label: str) -> None:
        """Comment in the Conversation; label names the comment in Temporal UI (e.g. "idle warning")."""
        await workflow.execute_activity(
            "PostComment",
            CommentInput(pr=self._pr, body=body, marker=marker),
            summary=label,
            **policies.GITHUB_CALL,
        )

    async def _refresh_check(self) -> None:
        """Recompute the last round's check after a dismissal: it turns green once no blocking finding is left."""
        state = self._state
        # A finding is open only after a published round.
        assert state.last_reviewed_sha is not None and state.last_reviewed_round is not None
        # The round's notes on unavailable reviewers and unlisted files drop out of the check here: accepted,
        # for simplicity, even in the rare round where every listed file was excluded and the check was the
        # only place reporting the unlisted files.
        output = publishing.check_output(state.open_findings)
        await self._complete_check(state.last_reviewed_sha, state.last_reviewed_round, output)

    # --- end ---

    async def _finish(self) -> PullRequestOutcome:
        closed = self._closed
        assert closed is not None
        self._set_phase("merged" if closed.merged else "closed")
        if closed.merged and self._state.open_findings:
            marker = markers.closing_marker(self._id)
            body = publishing.closing_comment(closed.closed_by, self._state.open_findings, marker)
            try:
                await self._post_comment(body, marker, "closing")
            except ActivityError as error:
                workflow.logger.warning("closing comment not posted: %s", error.cause or error)
        await self._delete_snapshots()
        return PullRequestOutcome(
            merged=closed.merged,
            closed_by=closed.closed_by,
            open_findings=self._state.open_findings,
            rounds=self._state.round,
        )

    async def _delete_snapshots(self) -> None:
        try:
            await workflow.execute_activity(
                "DeleteSnapshots",
                self._pr,
                summary=summaries.pull_request(self._pr.number),
                **policies.DELETE_SNAPSHOTS,
            )
        except ActivityError as error:
            workflow.logger.warning("snapshots not deleted (the S3 lifecycle rule will): %s", error.cause or error)
