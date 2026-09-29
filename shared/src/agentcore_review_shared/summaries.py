"""Summaries shown in Temporal UI, by the router (a workflow's static summary) and the worker (activities, children).

The Timeline truncates beyond 120 characters and Temporal caps a summary at 200 bytes.
"""

MAX_SUMMARY_CHARS = 120
MAX_SUMMARY_BYTES = 200


def fit(text: str) -> str:
    """Make text a single line that the Timeline shows whole, cutting its middle to keep a file name."""
    single_line = " ".join(text.split())
    limit = MAX_SUMMARY_CHARS
    shortened = _cut_middle(single_line, limit)
    # Non-ASCII characters take up to 4 bytes: shrink until the UTF-8 form fits too.
    while len(shortened.encode()) > MAX_SUMMARY_BYTES:
        limit -= 10
        shortened = _cut_middle(single_line, limit)
    return shortened


def _cut_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return f"{text[:head]}…{text[len(text) - tail :]}"
