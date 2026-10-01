import pytest
from agentcore_review_router.pages import (
    etag_of,
    json_document,
    max_age,
    not_found,
    page_for,
    respond,
)


def request(method: str, path: str) -> dict:
    return {"rawPath": path, "requestContext": {"http": {"method": method}}}


@pytest.mark.parametrize(
    ("method", "path", "page"),
    [
        ("GET", "/", "dashboard"),
        ("HEAD", "/", "dashboard"),
        ("GET", "/dashboard.json", "dashboard_json"),
        ("HEAD", "/dashboard.json", "dashboard_json"),
        ("GET", "/dashboard.html", "not_found"),
        ("GET", "/favicon.ico", "not_found"),
        ("POST", "/", None),
        ("POST", "/dashboard.json", None),
        ("PUT", "/", None),
    ],
)
def test_page_for(method, path, page):
    assert page_for(request(method, path)) == page


def test_an_event_without_request_context_is_not_a_page():
    assert page_for({"body": "{}"}) is None


DOC = json_document(b'{"deployed":true}', etag_of(b'{"deployed":true}'), 12)


@pytest.mark.parametrize(
    "header",
    [DOC.headers["ETag"], f"W/{DOC.headers['ETag']}", f'"other", {DOC.headers["ETag"]}', "*"],
)
def test_a_matching_if_none_match_answers_304_without_body(header):
    response = respond(DOC, "GET", header)
    assert response["statusCode"] == 304
    assert "body" not in response
    assert response["headers"]["ETag"] == DOC.headers["ETag"]


@pytest.mark.parametrize("header", [None, "", '"other"'])
def test_a_stale_or_missing_if_none_match_answers_200(header):
    response = respond(DOC, "GET", header)
    assert response["statusCode"] == 200
    assert response["body"] == '{"deployed":true}'
    assert response["headers"]["Cache-Control"] == "public, max-age=12"


def test_head_answers_the_headers_with_an_empty_body():
    response = respond(DOC, "HEAD", None)
    assert response["statusCode"] == 200
    assert response["body"] == ""


@pytest.mark.parametrize(("age", "expected"), [(0, 15), (3.5, 11), (14.2, 0), (15, 0), (40, 0)])
def test_max_age_counts_down_and_never_goes_negative(age, expected):
    assert max_age(age, 15) == expected


def test_not_found_has_a_body_for_get_and_none_for_head():
    get, head = not_found("GET"), not_found("HEAD")
    assert get["statusCode"] == head["statusCode"] == 404
    assert get["body"]
    assert head["body"] == ""
