import hashlib
import hmac

import pytest
from agentcore_review_router.signature import verify_signature

SECRET = "webhook-secret"
BODY = b'{"action":"opened","number":1}'
GOOD = "sha256=" + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()


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
