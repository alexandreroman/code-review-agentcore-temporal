# Demo run-through

A 15-minute demo with two screens only: **GitHub** and **Temporal UI**.
Four moments, in this order:

| # | Moment            | What the demo shows                                  |
|---|-------------------|------------------------------------------------------|
| 1 | Scale from zero   | No worker at rest; Temporal starts one on AgentCore  |
| 2 | Parallel agents   | Three reviewers as child workflows, then a synthesis |
| 3 | Durability        | `/kill` stops the sessions; the review resumes       |
| 4 | Human in the loop | Agent answers in a thread; `/fix` turns check green  |

The demo runs in the demo repository, `<owner>/agentcore-review-demo-app`
(unless `DEMO_REPO` names another one), that `make up` creates: a Spring
Boot order management application, the code the agents review. Every pull
request, comment and reset below happens there, not in this repository.

## The day before

> [!IMPORTANT]
> Deploy the day before, on a stable network, never on a shared event
> Wi-Fi: a first image push takes tens of minutes on a slow uplink, and
> during the demo nothing big must travel.

1. `aws sso login --profile <profile>` and `export AWS_PROFILE=<profile>`
   in the demo terminal, start Docker.
2. `make up`: deploy everything now.
3. Validate: `/e2e-validation full` in Claude Code (about 30 minutes). It
   checks all four moments, the reset, the dev mode and the return to zero.
4. Check the Bedrock quotas of the region (Service Quotas, Amazon
   Bedrock, the global cross-region tokens and requests per minute of
   Claude Opus 5): enough for a few reviews.

> [!WARNING]
> Once deployed, leave `pyproject.toml`, `uv.lock`, the member
> `pyproject.toml` files, `shared/src/`, `worker/src/` and
> `worker/Dockerfile` untouched, committed or not: the build ID hashes
> these paths, so any change makes the next `make up` build and push a new
> image. Docs and tests are safe to edit, and so is `demo/`: it reaches a
> filled demo repository only through `make demo-reset`, which builds no
> image. The deployment is done: no `make up` before the demo. After a new
> build anyway, demo on a fresh PR only: an open PR moves to the new build
> only after its next action or idle timer (see
> [Updating and tearing down](SETUP.md#updating-and-tearing-down)).

## Pre-demo checklist (30 minutes before)

1. **Network**: connect, and keep a phone hotspot at hand, tested with
   `make ping`; disconnect VPNs if the network is unstable.
2. **Credentials**: log in to AWS again (the session must outlast the
   demo), `gh auth status`.
3. **Reset** the demo repository: its **Actions** tab, **Reset demo**,
   **Run workflow**, or
   `gh workflow run reset-demo.yml --repo <owner>/agentcore-review-demo-app`.
   Wait for the green run. For a **New pull request** page that shows no
   earlier PR, run `make demo-reset` instead: it rebuilds the repository
   from `demo/` with new commits, then runs the same workflow.
4. **Back to zero**: `make kill-sessions`, so no worker runs when the demo
   starts.
5. **Tabs**, in this order:
   - GitHub, in the demo repository: **Pull requests**, **New pull
     request**, compare `feature/customer-search` into `main` (the page the
     PR is opened from);
   - Temporal UI: the namespace's workflows, filtered with
     `WorkflowType="PullRequestWorkflow"`;
   - Temporal UI: **Worker Deployments**, `agentcore-review-demo-worker`.

> [!IMPORTANT]
> Open the demo PR live, not before: the bot warns on a pull request idle
> for 10 minutes and closes it at 15. For a PR prepared in advance, raise
> `PR_IDLE_WARNING_SECONDS` and `PR_IDLE_CLOSE_SECONDS` in `.env` and run
> `make up` the day before (a router-only change, no new image); a PR keeps
> the durations its workflow started with.

## Run-through (15 minutes)

| Time  | Do                 | Show                                | Moment |
|-------|--------------------|-------------------------------------|--------|
| 0:00  | README diagram     | GitHub, router, Temporal, AgentCore | —      |
| 2:00  | Open the PR        | Workflow starts, then a session     | 1      |
| 3:00  | Open the workflow  | Three reviewers in parallel         | 2      |
| 4:00  | Comment `/kill`    | Sessions stop, work resumes         | 3      |
| 5:30  | Back to GitHub     | Review, red `AI Review`, idle queue | 4, 1   |
| 6:30  | Reply to a finding | Cold start, an answer in the thread | 4, 1   |
| 7:30  | Comment `/fix`     | The fixer pushes a commit           | 4      |
| 8:30  | Watch the commit   | Round 2, threads resolved, green    | —      |
| 10:00 | Merge the PR       | Workflow completes with its outcome | —      |
| 10:30 | Buffer             | Code tour, questions                | —      |

Key points:

- **2:00, scale from zero.** From the compare tab, title "Add customer
  search & order history", **Create pull request**. In Temporal UI, the
  `pr-…` workflow starts; in Worker Deployments, no poller existed before
  the PR, then Temporal starts an AgentCore session within seconds.
- **3:00, parallel agents.** The parent starts `…-r1-security`,
  `…-r1-performance` and `…-r1-maintainability`. Open one: each model
  call is an activity; `Grep`, `Glob` and `Read` tool calls explore the
  whole repository snapshot, not only the diff. The Timeline shows the file
  or pattern of every `Read`, `Grep` and `Glob` next to its name.
- **4:00, durability.** The bot replies "N AgentCore sessions stopped".
  The running activity times out on its heartbeat and resumes on a new
  session (attempt 2) about 10 to 25 seconds later; finished model calls
  are not repeated and not billed again.
- **5:30, human in the loop.** One review, inline comments tagged by
  category (`S-01` for security, `P-01` for performance, `M-01` for
  maintainability), a summary, and a red `AI Review` check.
  The workflow waits for a signal; its memo shows its state without any
  worker. After a minute without activity, the worker in the AgentCore
  session drains and stops: it leaves the **Workers** tab of Temporal UI,
  and no worker listens on the queue any more. AgentCore ends the idle
  session 2 minutes later. Its pending `idle warning` timer is durable:
  in 10 minutes, Temporal starts a worker just to post the warning, and
  closes the PR 5 minutes later. Reopening it starts a new review,
  numbered after the previous one: the bot says so in a comment right
  away, since the new round takes a few minutes.
- **6:30, discussion.** Reply in the thread of the SQL injection finding:
  "Why is this a problem? The input is validated upstream." 👀 on the
  reply. A worker starts on demand; in Temporal UI, a `…-discussion-1`
  child workflow checks the claim against the code with the same tools.
  The bot answers in the thread with evidence, starting with
  "**S-0x stays open.**"
- **7:30, `/fix`.** Post it as a PR comment: the fixer handles every open
  finding (in a finding's thread, `/fix` fixes that finding only;
  `/fix S-01 P-02` fixes the findings it names, and nothing at all if
  one of them is not open). 👀 on the comment. The fixer child workflow
  plans the smallest local change and the bot pushes one commit; a
  finding that needs a design decision is skipped, with its reason in the
  commit message.
- **8:30, long-lived workflow.** The commit triggers round 2 on the fix
  only: fixed threads are resolved, only a critical or high problem the
  fix introduces is reported, the check turns green.
- **10:00, lifecycle.** Merge: the workflow ends with its
  `PullRequestOutcome` (merged, by whom, rounds, findings still open) and
  deletes the PR's snapshots.

> [!IMPORTANT]
> The ruleset on `main` requires the `AI Review` check: the merge stays
> blocked as long as a critical or high finding is open. Lower findings
> leave the check green.

> [!TIP]
> In the discussion, question a real defect, such as the SQL injection:
> the answer stays predictable. An agent may also dismiss a finding when
> the code proves the human right.

## After the demo

Reset the demo repository. Nothing else: sessions drain by themselves.

## Recovery

| Symptom                        | Action                                     |
|--------------------------------|--------------------------------------------|
| No workflow after the PR       | App settings, Recent Deliveries: Redeliver |
| `/kill` answers nothing        | Carry on: the review completes anyway      |
| No answer to the reply in 90 s | Skip it: comment `/fix` on the PR          |
| A "Fix N" comment after `/fix` | Comment `/fix` again, or admin merge       |
| Check red after `/fix`         | Admin merge: the outcome records it        |
| Review slower than 3 minutes   | Tour the history meanwhile                 |
| PR closed for inactivity       | Reopen it: a new review starts             |
