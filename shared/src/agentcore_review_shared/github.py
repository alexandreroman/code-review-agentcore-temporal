"""Minimal GitHub App client: app JWT, cached installation tokens, REST and GraphQL calls."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx2 as httpx
import jwt

from agentcore_review_shared.github_errors import DEFAULT_RATE_LIMIT_WAIT, Classification, classify

API_URL = "https://api.github.com"
TOKEN_REFRESH_MARGIN = 300.0


class GitHubError(Exception):
    def __init__(self, status: int, classification: Classification, body: str) -> None:
        super().__init__(f"GitHub API {status} ({classification.error_type}): {body[:300]}")
        self.status = status
        self.classification = classification
        self.body = body


@dataclass
class _CachedToken:
    token: str
    expires_at: float


class GitHubApp:
    def __init__(
        self,
        client_id: str,
        private_key_pem: str,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client_id = client_id
        self._private_key = private_key_pem
        self._http = http or httpx.AsyncClient(base_url=API_URL, timeout=20.0)
        self._clock = clock
        self._tokens: dict[int, _CachedToken] = {}

    def jwt(self) -> str:
        now = int(self._clock())
        claims = {"iat": now - 60, "exp": now + 540, "iss": self._client_id}
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    async def installation_token(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached and cached.expires_at - TOKEN_REFRESH_MARGIN > self._clock():
            return cached.token
        resp = await self._http.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self.jwt()}", "Accept": "application/vnd.github+json"},
        )
        _raise_for_status(resp)
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
        _raise_for_status(resp)
        return resp

    async def graphql(self, installation_id: int, query: str, variables: dict) -> dict:
        resp = await self.request(installation_id, "POST", "/graphql", json={"query": query, "variables": variables})
        payload = resp.json()
        errors = payload.get("errors")
        if errors:
            raise GitHubError(resp.status_code, _graphql_classification(errors), str(errors))
        return payload["data"]


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    raise GitHubError(resp.status_code, classify(resp.status_code, resp.headers, resp.text), resp.text)


def _graphql_classification(errors: list[dict]) -> Classification:
    # GitHub reports GraphQL rate limits with HTTP 200 and an error of type RATE_LIMITED.
    if any(error.get("type") == "RATE_LIMITED" for error in errors):
        return Classification("GitHubRateLimited", True, DEFAULT_RATE_LIMIT_WAIT)
    return Classification("GitHubGraphQLError", False)
