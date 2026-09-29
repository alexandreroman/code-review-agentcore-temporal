"""GitHub App tooling behind the Makefile.

- register: creates the app through the manifest flow, unless one is already registered (make up; make github-app
  FORCE=1 registers a new one)
- sync: refreshes the stored slug after a rename in the app settings, and points the app's webhook at the
  router (make up)
- installation-id: prints the app's installation ID on a repository; when the app is not installed there, prints
  its install link and exits with status 2 (make up, make review-pr). With --wait, it opens the install link in
  the browser and waits for the installation instead (make up)
"""

import argparse
import html
import json
import secrets
import sys
import time
import webbrowser
from collections.abc import Callable
from functools import cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
import httpx2 as httpx
from agentcore_review_shared.github import API_URL, GITHUB_JSON, app_jwt
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
# scripts/github.sh reads this exit status as "the app is not installed on the repository".
NOT_INSTALLED_EXIT_STATUS = 2
INSTALL_POLL_SECONDS = 5
INSTALL_WAIT_SECONDS = 600
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
    response = http.post(f"{API_URL}/app-manifests/{code}/conversions", headers={"Accept": GITHUB_JSON})
    response.raise_for_status()
    data = response.json()
    return GitHubAppSecret(
        app_id=data["id"],
        slug=data["slug"],
        client_id=data["client_id"],
        private_key=data["pem"],
        webhook_secret=data["webhook_secret"],
    )


def is_organization(http: httpx.Client, owner: str) -> bool:
    response = http.get(f"{API_URL}/users/{owner}", headers={"Accept": GITHUB_JSON})
    response.raise_for_status()
    return response.json().get("type") == "Organization"


def app_headers(app: GitHubAppSecret) -> dict[str, str]:
    """Headers that authenticate as the app itself (not as one of its installations)."""
    return {"Accept": GITHUB_JSON, "Authorization": f"Bearer {app_jwt(app.client_id, app.private_key)}"}


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
                self.reply(200, page)
                return
            code = callback_code(self.path, expected_state)
            if code is None:
                self.reply(400, "<p>Invalid callback: unknown state or missing code.</p>")
                return
            try:
                self.reply(200, on_code(code))
                done.append(None)
            except Exception as error:
                self.reply(500, f"<p>App creation failed: {html.escape(str(error))}</p>")
                done.append(error)

        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, body: str) -> None:
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


@cache
def secretsmanager() -> Any:
    return boto3.client("secretsmanager")


def registered_app() -> GitHubAppSecret | None:
    try:
        value = secretsmanager().get_secret_value(SecretId=GITHUB_APP_SECRET)["SecretString"]
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise
    return GitHubAppSecret.model_validate_json(value)


def store_app(app: GitHubAppSecret) -> None:
    """Create the secret on the first registration, else store a new version of it."""
    # The secret lives outside the aws stack, so make destroy keeps it and the next make up reuses the app.
    try:
        secretsmanager().create_secret(Name=GITHUB_APP_SECRET, SecretString=app.model_dump_json(), Tags=SECRET_TAGS)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceExistsException":
            raise
        secretsmanager().put_secret_value(SecretId=GITHUB_APP_SECRET, SecretString=app.model_dump_json())


def require_registered_app() -> GitHubAppSecret:
    app = registered_app()
    if app is None:
        sys.exit(
            "The GitHub App is not registered yet: make up registers it (make github-app FORCE=1 registers a new one)."
        )
    return app


def register(args: argparse.Namespace) -> None:
    existing = registered_app()
    if existing and not args.force:
        print(f"GitHub App {existing.slug} is already registered.")
        return
    state = secrets.token_urlsafe(24)
    local_url = f"http://localhost:{args.port}/"
    with httpx.Client(timeout=20) as http:
        manifest = build_manifest(args.name, args.webhook_url, f"{local_url}callback")
        page = form_page(new_app_url(args.owner, is_organization(http, args.owner), state), manifest)

        def on_code(code: str) -> str:
            app = convert(http, code)
            store_app(app)
            print(f"Registered GitHub App {app.slug} (stored in {GITHUB_APP_SECRET}).")
            slug = html.escape(app.slug)
            return f"<p>GitHub App <b>{slug}</b> created. You can close this page and go back to the terminal.</p>"

        def on_ready() -> None:
            print(f"Opening {local_url}: click 'Create GitHub App' in the browser (Ctrl-C to abort).")
            webbrowser.open(local_url)

        try:
            serve_once(args.port, page, state, on_code, on_ready)
        except OSError as error:
            sys.exit(f"Cannot listen on localhost:{args.port} ({error}): change GITHUB_APP_CALLBACK_PORT in .env.")


def sync_slug(http: httpx.Client, app: GitHubAppSecret) -> GitHubAppSecret:
    """Store the app's current slug: renaming the app in its settings changes the slug, and GitHub offers no rename API.

    The router and the worker build the bot login "<slug>[bot]" from the stored secret.
    """
    response = http.get(f"{API_URL}/app", headers=app_headers(app))
    response.raise_for_status()
    slug = response.json()["slug"]
    if slug == app.slug:
        return app
    renamed = app.model_copy(update={"slug": slug})
    store_app(renamed)
    print(f"GitHub App slug: {app.slug} -> {slug}")
    return renamed


def sync_webhook(http: httpx.Client, app: GitHubAppSecret, url: str) -> None:
    """Point the app's webhook at the router's current URL (Function URL or custom domain)."""
    headers = app_headers(app)
    response = http.get(f"{API_URL}/app/hook/config", headers=headers)
    response.raise_for_status()
    current = response.json().get("url")
    if current == url:
        print(f"GitHub App {app.slug} webhook is up to date: {current}")
        return
    response = http.patch(f"{API_URL}/app/hook/config", headers=headers, json={"url": url})
    response.raise_for_status()
    print(f"GitHub App {app.slug} webhook: {current} -> {url}")


def sync(args: argparse.Namespace) -> None:
    app = require_registered_app()
    with httpx.Client(timeout=20) as http:
        app = sync_slug(http, app)
        sync_webhook(http, app, args.url)


def wait_for_installation(http: httpx.Client, app: GitHubAppSecret, owner: str, repo: str) -> int | None:
    """Poll until the app is installed on the repository; None when the wait times out."""
    deadline = time.monotonic() + INSTALL_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(INSTALL_POLL_SECONDS)
        found = installation_id(http, app, owner, repo)
        if found is not None:
            return found
    return None


def print_installation_id(args: argparse.Namespace) -> None:
    app = require_registered_app()
    install_url = f"https://github.com/apps/{app.slug}/installations/new"
    with httpx.Client(timeout=20) as http:
        found = installation_id(http, app, args.owner, args.repo)
        if found is None and args.wait:
            print(
                f"Action needed: install GitHub App {app.slug} on {args.owner}/{args.repo}. Opening {install_url} "
                f"(waiting up to {INSTALL_WAIT_SECONDS // 60} minutes, Ctrl-C to abort).",
                file=sys.stderr,
            )
            webbrowser.open(install_url)
            found = wait_for_installation(http, app, args.owner, args.repo)
    if found is None:
        if args.wait:
            notice = (
                f"GitHub App {app.slug} is still not installed on {args.owner}/{args.repo}: install it "
                f"({install_url}), then run make up again."
            )
        else:
            notice = f"Action needed: install GitHub App {app.slug} on {args.owner}/{args.repo}: {install_url}"
        print(notice, file=sys.stderr)
        sys.exit(NOT_INSTALLED_EXIT_STATUS)
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
    synchronize = commands.add_parser(
        "sync", help="store the app's current slug, and point its webhook at the given URL, when either differs"
    )
    synchronize.add_argument("--url", required=True)
    synchronize.set_defaults(handler=sync)
    installation = commands.add_parser("installation-id", help="print the app's installation ID on a repository")
    installation.add_argument("--owner", required=True)
    installation.add_argument("--repo", required=True)
    installation.add_argument(
        "--wait", action="store_true", help="when the app is not installed, open its install link and wait for it"
    )
    installation.set_defaults(handler=print_installation_id)
    args = parser.parse_args()
    try:
        args.handler(args)
    except KeyboardInterrupt:
        sys.exit("aborted")


if __name__ == "__main__":
    main()
