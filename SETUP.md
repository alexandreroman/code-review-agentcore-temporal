# Setup

Step-by-step installation of **Code Review with AgentCore x Temporal**, from
empty accounts to a first reviewed pull request. Plan about an hour; most of
it is the first image push and the waits for AWS.

Commands run from the repository root unless stated otherwise. Values in
angle brackets and `your-namespace.a1b2c` are placeholders for your own
identifiers: `<this-repo-owner>` owns the copy of this repository you
clone, `<owner>` owns your demo repository, `<your-org>` names your
organization in the certificates, `<upstream-owner>` owns the upstream demo
repository and `<profile>` is your AWS CLI profile.

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
git clone https://github.com/<this-repo-owner>/code-review-agentcore-temporal.git
cd code-review-agentcore-temporal
make install
make check
```

## 3. mTLS certificates

Every component authenticates to Temporal Cloud with an mTLS client
certificate. One certificate serves the local worker, the `temporal` CLI,
the AgentCore worker and the router.

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
`AWS_REGION` for another region, `TEMPORAL_TLS_CERT_PATH` and
`TEMPORAL_TLS_KEY_PATH` for certificates outside `certs/`,
`PR_IDLE_WARNING_SECONDS` and `PR_IDLE_CLOSE_SECONDS` for when an idle pull
request is warned, then closed (10 and 15 minutes), and the settings of a
[custom domain](#custom-domain-cloudflare-optional) for the webhook.
Plain `KEY=value` lines, no quotes: the Makefile includes the file.
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
(Lambda router, ECR repository, IAM roles, secret containers, snapshots
bucket, optional custom domain, and the AgentCore Identity workload identity
and API key provider through which the worker reads the Anthropic key),
`secrets` (Anthropic key and certificates into Secrets Manager) and `deploy`
(image build and push, AgentCore runtime and endpoint, Temporal Worker
Deployment Version). The AgentCore runtime only exists once there is a
build to run: `infra` alone never creates it. The first image push uploads
about 95 MB: on a slow uplink it takes a long time; later pushes only send
the changed layers.

This first run stops on purpose:

```text
The GitHub App is not registered yet: run make github-app, then make up again.
```

## 8. Register the GitHub App

```bash
make github-app
```

A browser page opens: click **Create GitHub App**. The app is named
*Code Review AgentCore x Temporal* by default, with the slug
`code-review-agentcore-x-temporal` (you may rename the app, or set
`GITHUB_APP_NAME` in `.env`; GitHub caps the name at 34 characters).
The terminal then prints `Registered GitHub App <slug> ...`. The app has
the permissions `pull_requests: write`, `checks: write`, `contents: write`,
`issues: read` and `metadata: read`, listens to `pull_request`,
`issue_comment` and `pull_request_review_comment` (replies to a finding),
and sends its webhooks to the router: its Lambda Function URL, or the
[custom domain](#custom-domain-cloudflare-optional) when one is set. Its
credentials go straight to Secrets Manager, in a secret that `make destroy`
keeps.

## 9. Second deployment and app installation

```bash
make up
```

This run creates the public repository `agentcore-review-demo-app` and
the Actions secrets of the reset workflow, then prints (on one line):

```text
Action needed: install GitHub App <slug> on <owner>/agentcore-review-demo-app:
https://github.com/apps/<slug>/installations/new
```

GitHub only accepts an app as a ruleset bypass actor once it is installed
on the repository, so the rulesets wait for the next run.

Open the link, choose **Only select repositories**, pick
`agentcore-review-demo-app`, and install. Run `make up` once more: it adds
the ruleset on `main` (required `AI Review` check, admin and app bypass)
and the ruleset on the `baseline` and `scenario/*` tags, then ends with
`GitHub App is installed on <owner>/agentcore-review-demo-app.`

## 10. Push the demo repository

The demo application (Spring Boot, Spring Data JPA, H2), its tags and
the "Reset demo" workflow come from the upstream demo repository. Copy
them into yours, next to this repository:

```bash
cd ..
git clone https://github.com/<upstream-owner>/agentcore-review-demo-app.git
cd agentcore-review-demo-app
git fetch origin 'refs/tags/*:refs/tags/*'
git remote set-url origin https://github.com/<owner>/agentcore-review-demo-app.git
git push origin 'baseline^{commit}:refs/heads/main'
git push origin refs/tags/baseline refs/tags/scenario/customer-search
cd ../code-review-agentcore-temporal
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
Temporal started one on AgentCore for this workflow.

Then a real review. Open a pull request from `feature/customer-search` to
`main` in the demo repository: a review with inline comments and a red
`AI Review` check arrives in under three minutes. To check the whole
lifecycle, see [Validation](README.md#validation). Close the PR, or run the
reset, when you are done.

## 12. Local development worker

```bash
make dev
```

The local worker connects to the same Temporal Cloud namespace and polls
the `review-dev` task queue. The router sends every pull request opened
from a `dev/` branch there, so a PR from `dev/customer-search` is reviewed
by your laptop, with hot reload, without deploying anything.

## Custom domain (Cloudflare, optional)

By default, GitHub sends the webhooks to the router's Lambda Function URL,
a generated `https://<id>.lambda-url.<region>.on.aws/` address. To use your
own hostname instead, such as `codereview.example.com`, you need a zone on
your Cloudflare account and a Cloudflare API token with the **Zone > DNS >
Edit** permission on that zone. Add to `.env`:

```text
DOMAIN_NAME=example.com
SUBDOMAIN=codereview
CLOUDFLARE_ZONE_ID=<zone-id>
CLOUDFLARE_API_TOKEN=<api-token>
```

`SUBDOMAIN` defaults to `codereview`; the zone ID is on the zone's overview
page in the Cloudflare dashboard. The next `make up` creates, in the aws
stack:

- an ACM certificate for the hostname, validated through a DNS record in
  the Cloudflare zone;
- an API Gateway HTTP API in front of the router, with a custom domain on
  that certificate (a Function URL only answers to its own hostname);
- a DNS-only CNAME record (Cloudflare proxy off) from the hostname to API
  Gateway.

`make up` then points the app's webhook at the new URL by itself: an app
registered earlier switches over without a visit to its settings, and
emptying `DOMAIN_NAME` switches it back to the Function URL the same way.
While `DOMAIN_NAME` is set, the deployment targets stop at once if
`CLOUDFLARE_ZONE_ID` or `CLOUDFLARE_API_TOKEN` is missing.

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
- `make destroy` stops the sessions, removes the AWS resources after a
  confirmation, then deletes the Temporal Worker Deployment and the
  AgentCore log groups. The OpenTofu state bucket, its KMS key, the demo
  repository, the GitHub App and its credentials in Secrets Manager
  remain, so the next `make up` redeploys with the same app. With a custom
  domain, the certificate and the DNS records go too and come back under
  the same hostname; without one, the recreated Function URL gets a new
  address. Either way, `make up` repoints the app's webhook if its URL
  differs.
- Renaming the GitHub App in its settings changes its slug, which the
  router and the worker use to recognize the bot's own comments. The next
  `make github` (or `make up`) stores the new slug and prints
  `GitHub App slug: <old> -> <new>`. Then run `make kill-sessions`: the
  running worker sessions keep the old slug until they stop. The router
  picks up the new slug on its next cold start; until then, replies in a
  finding's thread go unanswered.
- To delete the GitHub App for good, delete it in the GitHub settings
  (`https://github.com/settings/apps/<slug>`, **Advanced**), then its
  credentials; `make github-app` registers a new app afterwards:

  ```bash
  aws secretsmanager delete-secret \
    --secret-id code-review-agentcore-temporal/github-app \
    --force-delete-without-recovery
  ```
