import base64
import hashlib
import hmac

import pytest
from agentic_review_router.signature import decode_body, verify_signature

SECRET = "webhook-secret"
BODY = b'{"action":"opened","number":1}'
GOOD = "sha256=" + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()


def test_plain_body_is_encoded_as_utf8():
    assert decode_body({"body": BODY.decode(), "isBase64Encoded": False}) == BODY


def test_base64_body_is_decoded():
    assert decode_body({"body": base64.b64encode(BODY).decode(), "isBase64Encoded": True}) == BODY


def test_missing_body_is_empty():
    assert decode_body({}) == b""


def test_valid_signature():
    assert verify_signature(SECRET, BODY, GOOD)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        GOOD.removeprefix("sha256="),
        "sha1=" + GOOD.removeprefix("sha256="),
        "sha256=deadbeef",
        "sha256=" + "0" * 64,
        "sha256=é…",
    ],
)
def test_invalid_or_malformed_signatures_are_rejected(header):
    assert verify_signature(SECRET, BODY, header) is False


def test_signature_depends_on_the_exact_bytes():
    assert not verify_signature(SECRET, BODY + b" ", GOOD)


def test_malformed_base64_body_decodes_to_empty():
    assert decode_body({"body": "not base64!", "isBase64Encoded": True}) == b""
