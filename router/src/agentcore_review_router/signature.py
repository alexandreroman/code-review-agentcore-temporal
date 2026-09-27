"""GitHub webhook signature verification over the raw request body."""

import base64
import binascii
import hashlib
import hmac


def decode_body(event: dict) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body)
        except binascii.Error:
            return b""
    return body.encode("utf-8")


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.removeprefix("sha256=").encode())
