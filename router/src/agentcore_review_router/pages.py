"""The status page's HTTP side: which requests it serves, and cache-aware responses (pure, except dashboard_html()).

GET or HEAD on / serves the page and on /dashboard.json the Temporal snapshot; any other GET or HEAD is a 404. Every
other request is a webhook. Function URLs and API Gateway (payload 2.0) carry the method and path the same way.
"""

import hashlib
import math
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Literal

Page = Literal["dashboard", "dashboard_json", "not_found"]

PATHS: dict[str, Page] = {"/": "dashboard", "/dashboard.json": "dashboard_json"}
COMMON_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        # Inline scripts, and the Alpine standard build evaluates its expressions.
        "script-src https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/dist/index.global.js"
        " https://cdn.jsdelivr.net/npm/alpinejs@3.17.4/dist/cdn.min.js 'unsafe-inline' 'unsafe-eval'",
        # Tailwind's browser build injects a style element.
        "style-src 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)


@dataclass(frozen=True)
class Resource:
    body: bytes
    headers: dict[str, str]


def page_for(event: dict) -> Page | None:
    """The page a request asks for, or None when it is a webhook."""
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method")
    if method not in ("GET", "HEAD"):
        return None
    return PATHS.get(event.get("rawPath") or "/", "not_found")


def etag_of(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'


def max_age(age: float, ttl: float) -> int:
    """Whole seconds left before a snapshot taken `age` seconds ago expires; 0 once expired."""
    return max(0, math.floor(ttl - age))


@cache
def dashboard_html() -> Resource:
    """The page, read once per container. no-cache: a reload revalidates, and a new deployment shows at once."""
    body = files(__package__).joinpath("dashboard.html").read_bytes()
    return Resource(
        body,
        {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-cache",
            "ETag": etag_of(body),
            "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        },
    )


def json_document(body: bytes, etag: str, seconds: int) -> Resource:
    """The snapshot, fresh in the browser for `seconds`, then revalidated with its ETag."""
    return Resource(
        body, {"Content-Type": "application/json", "Cache-Control": f"public, max-age={seconds}", "ETag": etag}
    )


def respond(resource: Resource, method: str, if_none_match: str | None) -> dict:
    """A Lambda proxy response: 304 when the client already holds this ETag, else 200 (empty body for HEAD)."""
    headers = COMMON_HEADERS | resource.headers
    if _matches(if_none_match, resource.headers["ETag"]):
        return {"statusCode": 304, "headers": headers}
    return {"statusCode": 200, "headers": headers, "body": "" if method == "HEAD" else resource.body.decode()}


def not_found(method: str) -> dict:
    """A 404, never cached (empty body for HEAD)."""
    headers = COMMON_HEADERS | {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}
    return {"statusCode": 404, "headers": headers, "body": "" if method == "HEAD" else "not found"}


def _matches(if_none_match: str | None, etag: str) -> bool:
    """If-None-Match uses the weak comparison: W/ prefixes are ignored, and * matches any ETag."""
    tags = {tag.strip().removeprefix("W/") for tag in (if_none_match or "").split(",")}
    return "*" in tags or etag in tags
