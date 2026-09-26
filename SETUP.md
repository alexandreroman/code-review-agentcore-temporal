# Setup

Step-by-step installation of **Agentic Code Review with AgentCore x
Temporal**, from empty accounts to a first reviewed pull request. Plan about
an hour; most of it is the first image push and the waits for AWS.

Commands run from the repository root unless stated otherwise. Values in
angle brackets (`<owner>`, `<profile>`) and `your-namespace.a1b2c` are
placeholders for your own identifiers.

## 1. Accounts and tools

Accounts:

- A **Temporal Cloud** namespace with Serverless Workers enabled (a
  prerelease feature: ask your Temporal contact to enable it), and access
  to its settings.
- An **AWS** account where you can create IAM roles, Lambda functions, S3
  buckets, ECR repositories and Bedrock AgentCore runtimes, in a region
  where AgentCore is available (`ca-central-1` by default).
- An **Anthropic** API key.
- A **GitHub** account (personal or organization) to own the demo
  repository.

Tools:

| Tool                               | Version       | Check                |
|------------------------------------|---------------|----------------------|
| [uv](https://docs.astral.sh/uv/)   | 0.12.19       | `uv --version`       |
| GNU Make                           | 3.81 or later | `make --version`     |
| [OpenTofu](https://opentofu.org/)  | 1.12.6        | `tofu version`       |
| AWS CLI                            | v2            | `aws --version`      |
| Temporal CLI                       | 1.9 or later  | `temporal --version` |
| tcld                               | latest        | `tcld version`       |
| GitHub CLI                         | 2.x           | `gh --version`       |
| jq                                 | 1.7           | `jq --version`       |
| Docker or a compatible CLI         | arm64 builds  | `docker info`        |

The worker image targets `linux/arm64`. Docker Desktop builds it on any
host; on a Linux x86 host, install QEMU and binfmt support first.

## 2. Clone and install

```bash
git clone https://github.com/<owner>/temporal-agentcore-review-demo.git
cd temporal-agentcore-review-demo
make install
make check
```

## 3. mTLS certificates

Every component authenticates to Temporal Cloud with an mTLS client
certificate. By default one certificate serves the local worker, the
`temporal` CLI, the AgentCore worker and the router.

Generate a CA and a client certificate, valid for one year at most, at the
default paths (`certs/` is git-ignored):

```bash
mkdir -p certs
tcld gen ca --org <your-org> --validity-period 365d \
  --ca-cert certs/ca.pem --ca-key certs/ca.key
tcld gen leaf --org <your-org> --common-name agentcore-review-demo \
  --validity-period 364d --ca-cert certs/ca.pem --ca-key certs/ca.key \
  --cert certs/client.pem --key certs/client.key
```

Move `certs/ca.key` somewhere safe once you are done: only new leaf
certificates need it.

Optional: separate certificates for the AgentCore worker and the router.
Generate two more leaves from the same CA (`--common-name
agentcore-review-demo-worker`, then `agentcore-review-demo-router`) into
`certs/worker.pem` / `certs/worker.key` and `certs/router.pem` /
`certs/router.key`, then set `TEMPORAL_WORKER_CERT_PATH`,
`TEMPORAL_WORKER_KEY_PATH`, `TEMPORAL_ROUTER_CERT_PATH` and
`TEMPORAL_ROUTER_KEY_PATH` in `.env` (step 4).

Add the CA to the namespace, **appending** it to the accepted bundle:

1. In the Temporal Cloud UI, open **Namespaces**, your namespace, then
   **Edit**.
2. In **CA Certificates**, paste the content of `certs/ca.pem` **after**
   the certificates already there, then save.

`tcld namespace accepted-client-ca set` replaces the whole bundle and cuts
off every client of the other CAs: prefer the UI. A namespace accepts at
most 16 CAs and 32 KB. Optionally, add a certificate filter on the common
name `agentcore-review-demo` so that only these identities get in.

The change takes a few minutes. Check it:

```bash
temporal workflow list --limit 1 \
  --address your-namespace.a1b2c.tmprl.cloud:7233 \
  --namespace your-namespace.a1b2c \
  --tls-cert-path certs/client.pem --tls-key-path certs/client.key
```

Pass the TLS flags explicitly, as above: this CLI does not reliably pick
them up from environment variables.

## 4. Configuration (`.env`)

```bash
cp .env.example .env
```

Set at least:

- `TEMPORAL_NAMESPACE`: your namespace (`your-namespace.a1b2c` is the
  placeholder);
- `ANTHROPIC_API_KEY`: your API key.

Optional: `GITHUB_OWNER` when the demo repository belongs to an
organization (the default is the account logged in to `gh`),
`AWS_REGION` for another region, the certificate paths of step 3. Plain
`KEY=value` lines, no quotes: the Makefile includes the file.
[`.env.example`](.env.example) documents every variable and its default.

## 5. AWS credentials

With IAM Identity Center (SSO):

```bash
aws configure sso                   # once: creates a profile
aws sso login --profile <profile>
export AWS_PROFILE=<profile>
aws sts get-caller-identity
```

Export `AWS_PROFILE` in your shell: the AWS CLI does not read `.env`. SSO
sessions expire after a few hours; log in again before a deployment or a
talk.

## 6. GitHub CLI

```bash
gh auth login
gh auth refresh --scopes workflow
gh auth setup-git
```

The `workflow` scope lets you push the demo repository, which contains the
"Reset demo" workflow (step 10). `gh auth setup-git` makes `git push` use
the `gh` credentials.

## 7. First deployment

Start Docker, then:

```bash
make up
```

`make up` chains `bootstrap` (OpenTofu state bucket and KMS key), `infra`
(Lambda router, AgentCore runtime, IAM, secrets, snapshots bucket),
`secrets` (Anthropic key and certificates into Secrets Manager) and
`deploy` (image build and push, AgentCore endpoint, Temporal Worker
Deployment Version). The first image push uploads about 95 MB: on a slow
uplink it takes a long time; later pushes only send the changed layers.

This first run stops on purpose:

```text
The GitHub App is not registered yet: run make github-app, then make up again.
```

## 8. Register the GitHub App

```bash
make github-app
```

A browser page opens: click **Create GitHub App** (you may rename the app).
The terminal then prints `Registered GitHub App <slug> ...`. The app has
the permissions `pull_requests: write`, `checks: write`, `contents: write`,
`issues: read` and `metadata: read`, listens to `pull_request` and
`issue_comment`, and sends its webhooks to the router's Function URL. Its
credentials go straight to Secrets Manager.

## 9. Second deployment and app installation

```bash
make up
```

This run creates the public repository `agentcore-review-demo-app`, its
ruleset on `main` (required `AI Review` check, admin and app bypass) and
the Actions secrets of the reset workflow, then prints (on one line):

```text
Action needed: install GitHub App <slug> on <owner>/agentcore-review-demo-app:
https://github.com/apps/<slug>/installations/new
```

Open the link, choose **Only select repositories**, pick
`agentcore-review-demo-app`, and install. Run `make up` once more: it ends
with `GitHub App <slug> is installed on <owner>/agentcore-review-demo-app.`

## 10. Push the demo repository

The demo application (FastAPI, SQLAlchemy, SQLite), its tags and the
"Reset demo" workflow come from the upstream demo repository. Copy them
into yours, next to this repository:

```bash
cd ..
git clone https://github.com/<upstream-owner>/agentcore-review-demo-app.git
cd agentcore-review-demo-app
git fetch origin 'refs/tags/*:refs/tags/*'
git remote set-url origin https://github.com/<owner>/agentcore-review-demo-app.git
git push origin 'baseline^{commit}:refs/heads/main'
git push origin refs/tags/baseline refs/tags/scenario/customer-search
cd ../temporal-agentcore-review-demo
```

GitHub may report a bypassed rule on `main`: you are an admin, a bypass
actor of the ruleset. Then run the reset once; it creates the scenario
branches:

```bash
gh workflow run reset-demo.yml --repo <owner>/agentcore-review-demo-app
gh run list --repo <owner>/agentcore-review-demo-app --workflow reset-demo.yml --limit 1
gh api repos/<owner>/agentcore-review-demo-app/branches --jq '.[].name'
```

Expected branches: `dev/customer-search`, `feature/customer-search`,
`main`.

## 11. Check the installation

Scale-from-zero:

```bash
make ping
```

Expected: `pong: hello (worker agentcore:b_…:…)`. No worker ran before:
AgentCore started a session for this workflow.

Then a real review. Open a pull request from `feature/customer-search` to
`main` in the demo repository: a review with inline comments and a red
`AI Review` check arrives in under three minutes. With
[Claude Code](https://claude.com/claude-code), the `e2e-validation`
project skill runs the whole lifecycle and reports each step:
`/e2e-validation` (6 to 8 minutes) or `/e2e-validation full` (about 30
minutes, before a talk). Close the PR, or run the reset, when you are done.

## 12. Local development worker

```bash
make dev
```

The local worker connects to the same Temporal Cloud namespace and polls
the `review-dev` task queue. The router sends every pull request opened
from a `dev/` branch there, so a PR from `dev/customer-search` is reviewed
by your laptop, with hot reload, without deploying anything.

## Troubleshooting

- **No review, no workflow in Temporal UI**: the webhook was lost or
  rejected. Open the app settings (`https://github.com/settings/apps/<slug>`,
  **Advanced**, **Recent Deliveries**) and click **Redeliver**; GitHub
  never redelivers by itself, and keeps deliveries for 3 days. The router
  log shows what it received:
  `aws logs tail /aws/lambda/agentcore-review-demo-router --since 15m`.
- **`context deadline exceeded` or a TLS EOF** from `make deploy` or
  `make kill-sessions`: the Temporal CLI fails on unstable networks while
  the service is fine. Run the target again on a stable connection.
- **`task queue review never attached`** from `make deploy`: the new
  worker crashed at startup. The error names the CloudWatch log group to
  read.
- **`Docker is not running`**: start Docker, then run the target again.
- **AWS `ExpiredToken` or SSO errors**: `aws sso login --profile
  <profile>`.
- **A workflow waits and no worker starts**: in Temporal UI, **Worker
  Deployments**, `agentcore-review-demo-worker` must have a current version
  with the `review` task queue. `make deploy` restores it.

## Updating and tearing down

- After a code change, `make deploy` builds a new version (build ID
  `b_…`), creates its AgentCore endpoint and makes it current. Open pull
  requests stay pinned to the version that started them; after a reset,
  `make prune` removes the endpoints no workflow uses any more.
- `make destroy` removes the AWS resources, after a confirmation, and
  deletes the GitHub App secret. The OpenTofu state bucket, its KMS key,
  the demo repository and the GitHub App remain: delete the app in the
  GitHub settings, and register a new one with `make github-app` the next
  time.
