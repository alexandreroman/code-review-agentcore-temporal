from agentcore_review_worker.hunks import commentable_lines, git_lines, is_commentable, numbered_patch

PATCH = """@@ -1,4 +1,5 @@
 import os
-import sys
+import re
+import json

 def main():
@@ -20,2 +21,3 @@ def helper():
     return 1
+    # added
     pass"""


def test_added_and_context_lines_are_commentable():
    assert commentable_lines(PATCH) == {1, 2, 3, 4, 5, 21, 22, 23}


def test_added_line_that_looks_like_a_header_counts():
    assert commentable_lines("@@ -1 +1,2 @@\n x\n+++i") == {1, 2}


def test_hunk_header_without_counts():
    assert commentable_lines("@@ -1 +1 @@\n-old\n+new") == {1}


def test_no_newline_marker_is_ignored():
    patch = "@@ -1,1 +1,1 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file"
    assert commentable_lines(patch) == {1}


def test_deleted_file_has_no_commentable_lines():
    assert commentable_lines("@@ -1,2 +0,0 @@\n-a\n-b") == set()


def test_missing_patch():
    assert commentable_lines(None) == set() and commentable_lines("") == set()


def test_lines_split_like_git_on_newlines_only():
    # str.splitlines() would also break on the form feed and keep the empty line after the trailing newline.
    assert git_lines("a\x0cb\r\nTARGET\n") == ["a\x0cb", "TARGET"]


def test_numbered_patch_shows_the_commentable_line_numbers():
    gutters = [line[:5] for line in numbered_patch(PATCH).split("\n") if not line.startswith("@@")]
    numbers = {int(gutter) for gutter in gutters if gutter.strip()}
    assert numbers == commentable_lines(PATCH)


def test_numbered_patch_numbers_only_right_side_lines_and_restarts_at_each_hunk():
    patch = "@@ -1,2 +1,2 @@\n a\n-b\n+c\n\\ No newline at end of file\n@@ -9 +10 @@\n x"
    assert numbered_patch(patch).split("\n") == [
        "@@ -1,2 +1,2 @@",
        "    1  a",
        "      -b",
        "    2 +c",
        "      \\ No newline at end of file",
        "@@ -9 +10 @@",
        "   10  x",
    ]


def test_is_commentable_single_and_range():
    lines = commentable_lines(PATCH)
    assert is_commentable(lines, 3)
    assert is_commentable(lines, 2, 4)
    assert not is_commentable(lines, 10)
    assert not is_commentable(lines, 5, 21)  # spans two hunks
    assert not is_commentable(lines, 4, 3)  # inverted range
