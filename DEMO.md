# Demo run-through

A 15-minute talk with two screens only: **GitHub** and **Temporal UI**.
Four moments, in this order:

| # | Moment            | What the audience sees                               |
|---|-------------------|------------------------------------------------------|
| 1 | Scale from zero   | No worker at rest; Temporal starts one on AgentCore  |
| 2 | Parallel agents   | Three reviewers as child workflows, then a synthesis |
| 3 | Durability        | `/kill` stops the sessions; the review resumes       |
| 4 | Human in the loop | Agent answers in a thread; `/fix` turns check green  |

`<owner>` below is the owner of the demo repository
`agentcore-review-demo-app`.

## The day before

On a stable network, never on conference Wi-Fi:

1. `aws sso login --profile <profile>`, start Docker.
2. `make up`: deploy everything now. A first image push takes tens of
   minutes on a slow uplink; on stage, nothing big must travel.
3. Validate: `/e2e-validation full` in Claude Code (about 30 minutes). It
   checks all four moments, the reset, the dev mode and the return to zero.
4. Check the Bedrock quotas of the region (Service Quotas, Amazon
   Bedrock, the global cross-region tokens and requests per minute of
   Claude Opus 5): enough for a few reviews.
5. Afterwards, leave `pyproject.toml`, `uv.lock`, the member
   `pyproject.toml` files, `shared/src/`, `worker/src/` and
   `worker/Dockerfile` untouched, committed or not: the build ID hashes
   these paths, so any change makes the next `make up` build and push a
   new image. Docs and tests are safe to edit.

## Pre-stage checklist (30 minutes before)

1. **Network**: connect, and keep a tested phone hotspot at hand.
2. **Credentials**: `aws sso login --profile <profile>` (the session must
   outlast the talk), `gh auth status`.
3. **`make up`**: it must be a no-op ("already in ECR", "already the
   current version"). If it starts building an image, stop it (`Ctrl-C`)
   and keep the deployed build. After any `make deploy`, demo on a fresh
   PR only: a PR whose workflow started on an older build keeps the older
   behaviour until its workflow moves to the new build.
4. **Reset**: Actions, **Reset demo**, **Run workflow**, or
   `gh workflow run reset-demo.yml --repo <owner>/agentcore-review-demo-app`.
   Wait for the green run.
5. **Blank PR** to check the keys and quotas end to end (webhook, AgentCore,
   Bedrock access, GitHub App): in the demo repository, edit `README.md` in
   the browser, commit to a new branch `warmup/check`, open the PR, and wait
   for the `AI Review` check (a minute or two). Then close the PR and delete
   the branch.
6. **Idle pull requests**: the bot warns on a PR idle for 10 minutes and
   closes it at 15. Open the demo PR on stage, not before. For a PR
   prepared in advance, raise `PR_IDLE_WARNING_SECONDS` and
   `PR_IDLE_CLOSE_SECONDS` in `.env` and run `make up` the day before (a
   router-only change, no new image); a PR keeps the durations its
   workflow started with.
7. **Back to zero**: `make kill-sessions`, so no worker runs when the talk
   starts.
8. **Tabs**, in this order:
   - GitHub: **Pull requests**, **New pull request**, compare
     `feature/customer-search` into `main` (the page the PR is opened from);
   - Temporal UI: the namespace's workflows, filtered with
     `WorkflowType="PullRequestWorkflow"`;
   - Temporal UI: **Worker Deployments**, `agentcore-review-demo-worker`;
   - hidden, for plan B: the same compare page with `dev/customer-search`,
     and a terminal at the repository root (run `make dev` once, then stop
     it, so that its next start is fast).
9. **Readability**: browser zoom at 150 to 175 %, terminal font at 20 pt
   or more, bookmarks bar hidden, notifications off (Do Not Disturb), chat
   and mail closed.

## Run-through (15 minutes)

| Time  | Do                 | Show                                | Moment |
|-------|--------------------|-------------------------------------|--------|
| 0:00  | Architecture slide | GitHub, router, Temporal, AgentCore | —      |
| 2:00  | Open the PR        | Workflow starts, then a session     | 1      |
| 3:00  | Open the workflow  | Three reviewers in parallel         | 2      |
| 4:00  | Comment `/kill`    | Sessions stop, work resumes         | 3      |
| 5:30  | Back to GitHub     | Review, red `AI Review`, idle queue | 4, 1   |
| 6:30  | Reply to a finding | Cold start, an answer in the thread | 4, 1   |
| 7:30  | Comment `/fix`     | The fixer pushes a commit           | 4      |
| 8:30  | Watch the commit   | Round 2, threads resolved, green    | —      |
| 10:00 | Merge the PR       | Workflow completes with its outcome | —      |
| 10:30 | Buffer             | Code tour, questions                | —      |

Talking points:

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
  maintainability), a summary, and a red `AI Review` check that blocks the
  merge.
  The workflow waits for a signal; its memo shows its state without any
  worker, and a minute later no worker listens on the queue. Its pending
  `idle warning` timer is durable: in 10 minutes, Temporal starts a worker
  just to post the warning, and closes the PR 5 minutes later. Reopening
  it starts a new review, numbered after the previous one.
- **6:30, discussion.** Reply in the thread of the SQL injection finding:
  "Why is this a problem? The input is validated upstream." 👀 on the
  reply. A worker starts on demand; in Temporal UI, a `…-discussion-1`
  child workflow checks the claim against the code with the same tools.
  The bot answers in the thread with evidence, starting with
  "**S-0x stays open.**" An agent may also dismiss a finding when the
  code proves the human right; on stage, a question on a real defect keeps
  the answer predictable.
- **7:30, `/fix`.** Post it as a PR comment: the fixer handles every open
  finding (in a finding's thread, `/fix` fixes that finding only;
  `/fix S-01 P-02` fixes the findings it names, and nothing at all if
  one of them is not open). 👀 on the comment. The fixer child workflow
  plans the change and the bot pushes one commit.
- **8:30, long-lived workflow.** The commit triggers round 2 on the delta
  only: fixed threads are resolved, the check turns green.
- **10:00, lifecycle.** Merge: the workflow ends with its
  `PullRequestOutcome` (merged, by whom, rounds, findings still open) and
  deletes the PR's snapshots.

## After the talk

Run the reset. Nothing else: sessions drain by themselves, and the
infrastructure costs nothing at rest beyond storage.

## Plan B: AgentCore fails

Symptoms: no session 30 seconds after the PR, or AgentCore errors in the
workflow. Switch to the local worker, same Temporal Cloud namespace:

1. In the terminal: `make dev`, and wait for `polling review-dev`.
2. Open the PR from the hidden `dev/customer-search` compare tab: the `dev/`
   prefix routes it to the `review-dev` queue, served by the laptop.
3. Play the same scenario. Instead of `/kill`, press `Ctrl-C` on the local
   worker during the review, then run `make dev` again: the interrupted
   activity resumes on the new worker. A `/kill` comment on this PR only
   answers "Dev worker: Ctrl-C is your friend."
4. Scale-from-zero and the session kill are lost; everything else is
   identical.

## Network

- **Slow uplinks.** Conference and hotel Wi-Fi can upload as slowly as
  80 KB/s. Deploy the day before; on stage only webhooks and API calls
  travel.
- **Temporal CLI on unstable networks.** `make deploy` and
  `make kill-sessions` can fail with "context deadline exceeded" or a TLS
  EOF: retry, or switch to the hotspot.
- **Hotspot.** Test it with `make ping` before the talk. VPNs can make
  things worse: disconnect them if the network is unstable.

## Recovery

| Symptom                        | Action                                     |
|--------------------------------|--------------------------------------------|
| No workflow after the PR       | App settings, Recent Deliveries: Redeliver |
| No worker 30 s after the start | Plan B                                     |
| `/kill` answers nothing        | Carry on: the review completes anyway      |
| No answer to the reply in 90 s | Skip it: comment `/fix` on the PR          |
| Check red after `/fix`         | Admin merge: the outcome records it        |
| Review slower than 3 minutes   | Tour the history meanwhile                 |
