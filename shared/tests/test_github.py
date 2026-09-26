import json

import httpx2 as httpx
import jwt
import pytest
from agentic_review_shared.github import API_URL, GitHubApp, GitHubError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="module")
def key_pair() -> tuple[str, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_app(key_pair, handler, clock) -> tuple[GitHubApp, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(base_url=API_URL, transport=httpx.MockTransport(record))
    return GitHubApp("Iv23client", key_pair[0], http=http, clock=clock), seen


def token_response(expires_at: str = "2026-09-25T12:00:00Z") -> httpx.Response:
    return httpx.Response(201, json={"token": "ghs_token", "expires_at": expires_at})


def test_jwt_claims(key_pair):
    app, _ = make_app(key_pair, lambda r: token_response(), FakeClock(1_000_000.0))
    claims = jwt.decode(app.jwt(), key_pair[1], algorithms=["RS256"], options={"verify_exp": False})
    assert claims["iss"] == "Iv23client"
    assert claims["iat"] == 1_000_000 - 60 and claims["exp"] == 1_000_000 + 540


async def test_installation_token_is_cached_until_near_expiry(key_pair):
    clock = FakeClock(1_790_000_000.0)  # 2026-09-21
    expires = "2026-09-25T12:00:00Z"  # epoch 1790337600
    app, seen = make_app(key_pair, lambda r: token_response(expires), clock)
    assert await app.installation_token(42) == "ghs_token"
    assert await app.installation_token(42) == "ghs_token"
    assert len(seen) == 1
    assert seen[0].url.path == "/app/installations/42/access_tokens"
    assert seen[0].headers["authorization"].startswith("Bearer ")
    clock.now = 1_790_337_600.0 - 299  # inside the 300 s refresh margin
    await app.installation_token(42)
    assert len(seen) == 2


async def test_request_uses_the_installation_token(key_pair):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response("2099-01-01T00:00:00Z")
        return httpx.Response(200, json={"ok": True})

    app, seen = make_app(key_pair, handler, FakeClock(1_790_000_000.0))
    resp = await app.request(42, "GET", "/repos/o/r/pulls/1", params={"per_page": 100})
    assert resp.json() == {"ok": True}
    assert seen[1].headers["authorization"] == "Bearer ghs_token"
    assert seen[1].headers["accept"] == "application/vnd.github+json"
    assert seen[1].url.params["per_page"] == "100"


async def test_non_2xx_raises_a_classified_error(key_pair):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response("2099-01-01T00:00:00Z")
        return httpx.Response(
            403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000030"}, text="rate"
        )

    app, _ = make_app(key_pair, handler, FakeClock(1_790_000_000.0))
    with pytest.raises(GitHubError) as exc:
        await app.request(42, "GET", "/x")
    assert exc.value.status == 403
    assert exc.value.classification.error_type == "GitHubRateLimited"
    assert exc.value.classification.retryable


async def test_graphql_errors_raise(key_pair):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response("2099-01-01T00:00:00Z")
        assert json.loads(request.content)["variables"] == {"n": 1}
        return httpx.Response(200, json={"errors": [{"message": "boom"}]})

    app, _ = make_app(key_pair, handler, FakeClock(1_790_000_000.0))
    with pytest.raises(GitHubError) as exc:
        await app.graphql(42, "query { x }", {"n": 1})
    assert exc.value.classification.error_type == "GitHubGraphQLError"
    assert not exc.value.classification.retryable


async def test_graphql_returns_data(key_pair):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response("2099-01-01T00:00:00Z")
        return httpx.Response(200, json={"data": {"viewer": {"login": "bot"}}})

    app, _ = make_app(key_pair, handler, FakeClock(1_790_000_000.0))
    assert await app.graphql(42, "query { viewer { login } }", {}) == {"viewer": {"login": "bot"}}
