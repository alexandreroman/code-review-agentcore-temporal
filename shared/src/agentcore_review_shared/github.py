"""Minimal GitHub App client: app JWT, cached installation tokens, REST and GraphQL calls, error classification."""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import httpx2 as httpx
import jwt

API_URL = "https://api.github.com"
TOKEN_REFRESH_MARGIN = 300.0
DEFAULT_RATE_LIMIT_WAIT = 60.0


@dataclass(frozen=True)
class Classification:
    error_type: str
    retryable: bool
    retry_after: float | None = None


class GitHubError(Exception):
    def __init__(self, status: int, classification: Classification, body: str) -> None:
        super().__init__(f"GitHub API {status} ({classification.error_type}): {body[:300]}")
        self.status = status
        self.classification = classification


def classify(status: int, headers: Mapping[str, str], body: str = "", now: float | None = None) -> Classification:
    """Classify a non-2xx GitHub response."""
    h = {k.lower(): v for k, v in headers.items()}
    if status >= 500:
        return Classification("GitHubServerError", True)
    rate_limited = status == 429 or (
        status == 403
        and ("retry-after" in h or h.get("x-ratelimit-remaining") == "0" or "secondary rate limit" in body.lower())
    )
    if rate_limited:
        return Classification("GitHubRateLimited", True, _wait_seconds(h, time.time() if now is None else now))
    if status in (401, 403):
        return Classification("GitHubAuthError", False)
    if status == 404:
        return Classification("GitHubNotFound", False)
    if status == 422:
        return Classification("GitHubUnprocessable", False)
    return Classification("GitHubClientError", False)


def _wait_seconds(headers: dict[str, str], now: float) -> float:
    try:
        if "retry-after" in headers:
            return max(1.0, float(headers["retry-after"]))
        if headers.get("x-ratelimit-remaining") == "0" and "x-ratelimit-reset" in headers:
            return max(1.0, float(headers["x-ratelimit-reset"]) - now)
    except ValueError:
        pass
    return DEFAULT_RATE_LIMIT_WAIT


def raise_for_status(resp: httpx.Response) -> None:
    """Raise a classified GitHubError for a non-2xx response; a streamed response must be read first."""
    if resp.is_success:
        return
    raise GitHubError(resp.status_code, classify(resp.status_code, resp.headers, resp.text), resp.text)


def app_jwt(client_id: str, private_key_pem: str) -> str:
    """A short-lived JWT that authenticates as the GitHub App itself."""
    now = int(time.time())
    # Backdated by a minute against clock drift; GitHub caps the lifetime at ten minutes.
    claims = {"iat": now - 60, "exp": now + 540, "iss": client_id}
    return jwt.encode(claims, private_key_pem, algorithm="RS256")


@dataclass
class _CachedToken:
    token: str
    expires_at: float


class GitHubApp:
    def __init__(self, client_id: str, private_key_pem: str, *, timeout: float = 20.0) -> None:
        self._client_id = client_id
        self._private_key = private_key_pem
        self._http = httpx.AsyncClient(base_url=API_URL, timeout=timeout)
        self._tokens: dict[int, _CachedToken] = {}

    async def installation_token(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached and cached.expires_at - TOKEN_REFRESH_MARGIN > time.time():
            return cached.token
        resp = await self._http.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt(self._client_id, self._private_key)}",
                "Accept": "application/vnd.github+json",
            },
        )
        raise_for_status(resp)
        data = resp.json()
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        self._tokens[installation_id] = _CachedToken(data["token"], expires_at)
        return data["token"]

    async def request(
        self,
        installation_id: int,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: dict | None = None,
        accept: str = "application/vnd.github+json",
    ) -> httpx.Response:
        token = await self.installation_token(installation_id)
        resp = await self._http.request(
            method, path, json=json, params=params, headers={"Authorization": f"Bearer {token}", "Accept": accept}
        )
        raise_for_status(resp)
        return resp

    async def graphql(self, installation_id: int, query: str, variables: dict) -> dict:
        resp = await self.request(installation_id, "POST", "/graphql", json={"query": query, "variables": variables})
        payload = resp.json()
        errors = payload.get("errors")
        if errors:
            raise GitHubError(resp.status_code, _graphql_classification(errors), str(errors))
        return payload["data"]


def _graphql_classification(errors: list[dict]) -> Classification:
    # GitHub reports GraphQL rate limits with HTTP 200 and an error of type RATE_LIMITED.
    if any(error.get("type") == "RATE_LIMITED" for error in errors):
        return Classification("GitHubRateLimited", True, DEFAULT_RATE_LIMIT_WAIT)
    return Classification("GitHubGraphQLError", False)
