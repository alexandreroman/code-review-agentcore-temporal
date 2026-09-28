"""GitHub App tooling behind the Makefile.

- register: creates the app through the manifest flow (make github-app)
- sync-webhook: points the app's webhook at the router (make github, make up)
- installation-id: prints the app's installation ID on a repository, or its install link
  (make github, make up, make review-pr)
"""

import argparse
import html
import json
import secrets
import sys
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import boto3
import httpx2 as httpx
from agentcore_review_shared.github import API_URL, app_jwt
from agentcore_review_shared.secrets import GITHUB_APP_SECRET, GitHubAppSecret
from botocore.exceptions import ClientError

PERMISSIONS = {
    "pull_requests": "write",
    "checks": "write",
    "contents": "write",
    "issues": "read",
    "metadata": "read",
}
EVENTS = ["pull_request", "issue_comment", "pull_request_review_comment"]
ACCEPT = {"Accept": "application/vnd.github+json"}
SECRET_TAGS = [{"Key": "Project", "Value": "code-review-agentcore-temporal"}]


def build_manifest(name: str, webhook_url: str, callback_url: str) -> dict:
    return {
        "name": name,
        "url": "https://temporal.io",
        "hook_attributes": {"url": webhook_url, "active": True},
        "redirect_url": callback_url,
        "public": False,
        "default_permissions": PERMISSIONS,
        "default_events": EVENTS,
    }


def new_app_url(owner: str, owner_is_org: bool, state: str) -> str:
    base = (
        f"https://github.com/organizations/{owner}/settings/apps/new"
        if owner_is_org
        else "https://github.com/settings/apps/new"
    )
    return f"{base}?state={state}"


def form_page(action_url: str, manifest: dict) -> str:
    """A page that posts the manifest to GitHub as soon as it loads."""
    return (
        '<html><body onload="document.forms[0].submit()">'
        f'<form action="{html.escape(action_url)}" method="post">'
        f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(manifest))}">'
        '<noscript><button type="submit">Create the GitHub App</button></noscript>'
        "</form></body></html>"
    )


def callback_code(path: str, expected_state: str) -> str | None:
    """The code GitHub sends back, or None unless the path, the state and the code are all right."""
    url = urlparse(path)
    if url.path != "/callback":
        return None
    query = parse_qs(url.query)
    code = query.get("code", [""])[0]
    state = query.get("state", [""])[0]
    if not code or not secrets.compare_digest(state, expected_state):
        return None
    return code


def convert(http: httpx.Client, code: str) -> GitHubAppSecret:
    """Exchange the manifest code (valid for one hour) for the app credentials."""
    response = http.post(f"{API_URL}/app-manifests/{code}/conversions", headers=ACCEPT)
    response.raise_for_status()
    data = response.json()
    return GitHubAppSecret(
        app_id=data["id"],
        slug=data["slug"],
        client_id=data["client_id"],
        private_key=data["pem"],
        webhook_secret=data["webhook_secret"],
    )


def install_url(app: GitHubAppSecret) -> str:
    return f"https://github.com/apps/{app.slug}/installations/new"


def is_organization(http: httpx.Client, owner: str) -> bool:
    response = http.get(f"{API_URL}/users/{owner}", headers=ACCEPT)
    response.raise_for_status()
    return response.json().get("type") == "Organization"


def app_headers(app: GitHubAppSecret) -> dict[str, str]:
    """Headers that authenticate as the app itself (not as one of its installations)."""
    return {**ACCEPT, "Authorization": f"Bearer {app_jwt(app.client_id, app.private_key)}"}


def installation_id(http: httpx.Client, app: GitHubAppSecret, owner: str, repo: str) -> int | None:
    response = http.get(f"{API_URL}/repos/{owner}/{repo}/installation", headers=app_headers(app))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["id"]


def serve_once(
    port: int, page: str, expected_state: str, on_code: Callable[[str], str], on_ready: Callable[[], None]
) -> None:
    """Serve the form page until a valid callback has been handled."""
    done: list[BaseException | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlparse(self.path).path == "/":
                self._reply(200, page)
                return
            code = callback_code(self.path, expected_state)
            if code is None:
                self._reply(400, "<p>Invalid callback: unknown state or missing code.</p>")
                return
            try:
                self._reply(200, on_code(code))
                done.append(None)
            except Exception as error:
                self._reply(500, f"<p>App creation failed: {html.escape(str(error))}</p>")
                done.append(error)

        def log_message(self, format: str, *args: object) -> None:
            pass

        def _reply(self, status: int, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

    with HTTPServer(("localhost", port), Handler) as server:
        on_ready()
        while not done:
            server.handle_request()
    if done[0] is not None:
        raise done[0]


def _registered_app(client) -> GitHubAppSecret | None:
    try:
        value = client.get_secret_value(SecretId=GITHUB_APP_SECRET)["SecretString"]
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise
    return GitHubAppSecret.model_validate_json(value)


def _store_app(client, app: GitHubAppSecret) -> None:
    """Create the secret on the first registration, else store a new version of it."""
    # The secret lives outside the aws stack, so make destroy keeps it and the next make up reuses the app.
    try:
        client.create_secret(Name=GITHUB_APP_SECRET, SecretString=app.model_dump_json(), Tags=SECRET_TAGS)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceExistsException":
            raise
        client.put_secret_value(SecretId=GITHUB_APP_SECRET, SecretString=app.model_dump_json())


def _require_registered_app() -> GitHubAppSecret:
    app = _registered_app(boto3.client("secretsmanager"))
    if app is None:
        sys.exit("The GitHub App is not registered yet: run make github-app")
    return app


def register(args: argparse.Namespace) -> None:
    client = boto3.client("secretsmanager")
    existing = _registered_app(client)
    if existing and not args.force:
        sys.exit(
            f"GitHub App {existing.slug} is already registered. To register a new one, delete it in the GitHub "
            "settings, then run make github-app FORCE=1."
        )
    state = secrets.token_urlsafe(24)
    local_url = f"http://localhost:{args.port}/"
    with httpx.Client(timeout=20) as http:
        manifest = build_manifest(args.name, args.webhook_url, f"{local_url}callback")
        page = form_page(new_app_url(args.owner, is_organization(http, args.owner), state), manifest)

        def on_code(code: str) -> str:
            app = convert(http, code)
            _store_app(client, app)
            print(f"Registered GitHub App {app.slug} (stored in {GITHUB_APP_SECRET}).")
            print("Next: make up creates the demo repository and prints the link to install the app on it.")
            slug = html.escape(app.slug)
            return f"<p>GitHub App <b>{slug}</b> created. Back to the terminal: run <code>make up</code>.</p>"

        def on_ready() -> None:
            print(f"Opening {local_url}: click 'Create GitHub App' in the browser (Ctrl-C to abort).")
            webbrowser.open(local_url)

        try:
            serve_once(args.port, page, state, on_code, on_ready)
        except OSError as error:
            sys.exit(
                f"make github-app: cannot listen on localhost:{args.port} ({error}); change GITHUB_APP_CALLBACK_PORT"
            )


def sync_webhook(args: argparse.Namespace) -> None:
    """Point the app's webhook at the router's current URL (Function URL or custom domain)."""
    app = _require_registered_app()
    headers = app_headers(app)
    with httpx.Client(timeout=20) as http:
        response = http.get(f"{API_URL}/app/hook/config", headers=headers)
        response.raise_for_status()
        current = response.json().get("url")
        if current == args.url:
            print(f"GitHub App {app.slug} webhook is up to date: {current}")
            return
        response = http.patch(f"{API_URL}/app/hook/config", headers=headers, json={"url": args.url})
        response.raise_for_status()
    print(f"GitHub App {app.slug} webhook: {current} -> {args.url}")


def print_installation_id(args: argparse.Namespace) -> None:
    app = _require_registered_app()
    with httpx.Client(timeout=20) as http:
        found = installation_id(http, app, args.owner, args.repo)
    if found is None:
        sys.exit(f"Action needed: install GitHub App {app.slug} on {args.owner}/{args.repo}: {install_url(app)}")
    print(found)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentcore_review_tools.github_app")
    commands = parser.add_subparsers(dest="command", required=True)
    reg = commands.add_parser("register", help="register the app through the manifest flow")
    reg.add_argument("--owner", required=True)
    reg.add_argument("--name", required=True)
    reg.add_argument("--port", type=int, required=True)
    reg.add_argument("--webhook-url", required=True)
    reg.add_argument("--force", action="store_true")
    reg.set_defaults(handler=register)
    sync = commands.add_parser("sync-webhook", help="point the app's webhook at the given URL if it differs")
    sync.add_argument("--url", required=True)
    sync.set_defaults(handler=sync_webhook)
    installation = commands.add_parser("installation-id", help="print the app's installation ID on a repository")
    installation.add_argument("--owner", required=True)
    installation.add_argument("--repo", required=True)
    installation.set_defaults(handler=print_installation_id)
    args = parser.parse_args()
    try:
        args.handler(args)
    except KeyboardInterrupt:
        sys.exit("aborted")


if __name__ == "__main__":
    main()
