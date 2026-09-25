from tar_worker.hunks import commentable_lines, is_commentable

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


def test_removed_lines_do_not_advance_the_new_file():
    assert 2 in commentable_lines(PATCH)  # "+import re" takes line 2 after "-import sys"


def test_file_headers_are_skipped():
    patch = "--- a/x.py\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+a\n+b"
    assert commentable_lines(patch) == {1, 2}


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


def test_is_commentable_single_and_range():
    lines = commentable_lines(PATCH)
    assert is_commentable(lines, 3)
    assert is_commentable(lines, 2, 4)
    assert not is_commentable(lines, 10)
    assert not is_commentable(lines, 5, 21)  # spans two hunks
    assert not is_commentable(lines, 4, 3)  # inverted range
