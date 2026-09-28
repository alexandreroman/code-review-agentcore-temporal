import pytest
from agentcore_review_shared.contract import Finding
from agentcore_review_worker.summaries import (
    MAX_SUMMARY_BYTES,
    MAX_SUMMARY_CHARS,
    diff_files,
    finding_ids,
    finding_line,
    fit,
    tool_call,
)


def test_a_short_text_is_kept():
    assert fit("app/main.py") == "app/main.py"


def test_a_long_path_keeps_its_start_and_its_file_name():
    path = "app/" + "nested/" * 30 + "customers.py"
    summary = fit(path)
    assert len(summary) == MAX_SUMMARY_CHARS
    assert summary.startswith("app/nested/")
    assert summary.endswith("/customers.py")
    assert "…" in summary


def test_a_non_ascii_text_fits_the_byte_limit():
    summary = fit("日本語" * 60)
    assert len(summary.encode()) <= MAX_SUMMARY_BYTES


def test_a_summary_is_a_single_line():
    assert fit("  SQL injection\n\tin the  search query \r\n") == "SQL injection in the search query"


def test_a_finding_title_stays_on_its_bullet_line():
    finding = Finding(
        id="F-001",
        category="security",
        severity="critical",
        path="app/search.py",
        line=12,
        title="SQL injection\nin the search query",
        explanation="The query concatenates user input.",
    )
    assert "\n" not in finding_line(finding)


def test_finding_ids_are_listed_whole():
    ids = [f"F-{number:03d}" for number in range(1, 60)]
    summary = finding_ids(ids)
    assert summary.startswith("F-001, F-002, ")
    assert summary.endswith(", …")
    assert len(summary) <= MAX_SUMMARY_CHARS
    listed = summary.removesuffix(", …").split(", ")
    assert listed == ids[: len(listed)]


def test_the_diff_lists_the_paths_that_fit():
    assert diff_files(["app/main.py", "app/models.py"]) == "2 files: app/main.py, app/models.py"
    many = diff_files([f"app/module_{number}.py" for number in range(30)])
    assert many.startswith("30 files: app/module_0.py, app/module_1.py")
    assert many.endswith(", …")
    assert len(many) <= MAX_SUMMARY_CHARS


def test_a_single_long_path_is_cut_in_the_middle():
    summary = diff_files(["app/" + "nested/" * 30 + "customers.py"])
    assert summary.startswith("1 file: app/")
    assert summary.endswith("customers.py")


@pytest.mark.parametrize(
    ("tool_input", "summary"),
    [
        ({"file_path": "app/main.py"}, "app/main.py"),
        ({"file_path": "app/main.py", "offset": 1, "limit": 400}, "app/main.py:1-400"),
        ({"file_path": "app/main.py", "offset": "120"}, "app/main.py:120-"),
        ({"file_path": "app/main.py", "limit": 50}, "app/main.py:1-50"),
        ({"file_path": "app/main.py", "offset": "abc", "limit": -3}, "app/main.py"),
        ({"offset": 1}, None),
        ({"file_path": 42}, None),
    ],
)
def test_read_summary(tool_input, summary):
    assert tool_call("Read", tool_input) == summary


@pytest.mark.parametrize(
    ("tool_input", "summary"),
    [
        ({"pattern": r"select\(", "path": "app/", "glob": "*.py"}, r"/select\(/ in app/ (*.py)"),
        ({"pattern": "TODO"}, "/TODO/"),
        ({"path": "app/"}, "in app/"),
        ({"pattern": ["not", "a", "string"]}, None),
    ],
)
def test_grep_summary(tool_input, summary):
    assert tool_call("Grep", tool_input) == summary


@pytest.mark.parametrize(
    ("tool_input", "summary"),
    [
        ({"pattern": "app/**/*.py"}, "app/**/*.py"),
        ({"pattern": "*.py", "path": "app"}, "*.py in app"),
        ({}, None),
    ],
)
def test_glob_summary(tool_input, summary):
    assert tool_call("Glob", tool_input) == summary


def test_arguments_that_are_not_an_object_give_no_summary():
    assert tool_call("Read", "app/main.py") is None
    assert tool_call("Grep", None) is None


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("Read", {"file_path": "app/main.py", "offset": "²"}),
        ("Read", {"file_path": "app/main.py", "limit": "9" * 5000}),
        ("Read", {"file_path": "app/main.py", "offset": 10**5000}),
        ("Read", {"file_path": "app/main.py", "offset": True, "limit": False}),
        ("Read", {"file_path": "app/main.py", "offset": 2.5, "limit": float("inf")}),
        ("Read", {"file_path": {"nested": ["app/main.py"]}, "offset": [1], "limit": {"n": 1}}),
        ("Read", {"file_path": None, "offset": None, "limit": None}),
        ("Grep", {"pattern": {"regex": "x"}, "path": ["app"], "glob": None}),
        ("Glob", {"pattern": None, "path": {"dir": "app"}}),
        ("Unknown", {"file_path": "app/main.py"}),
    ],
)
def test_hostile_arguments_never_raise(tool_name, tool_input):
    summary = tool_call(tool_name, tool_input)
    assert summary is None or len(summary) <= MAX_SUMMARY_CHARS
