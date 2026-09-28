import pytest
from agentcore_review_worker.models import Finding
from agentcore_review_worker.summaries import (
    MAX_SUMMARY_BYTES,
    MAX_SUMMARY_CHARS,
    diff_files,
    finding_ids,
    finding_line,
    fit,
    tool_call,
)

JAVA = "src/main/java/com/example/orders/OrderService.java"


def test_a_short_text_is_kept():
    assert fit(JAVA) == JAVA


def test_a_long_path_keeps_its_start_and_its_file_name():
    path = "src/" + "nested/" * 30 + "CustomerService.java"
    summary = fit(path)
    assert len(summary) == MAX_SUMMARY_CHARS
    assert summary.startswith("src/nested/")
    assert summary.endswith("/CustomerService.java")
    assert "…" in summary


def test_a_non_ascii_text_fits_the_byte_limit():
    summary = fit("日本語" * 60)
    assert len(summary.encode()) <= MAX_SUMMARY_BYTES


def test_a_summary_is_a_single_line():
    assert fit("  SQL injection\n\tin the  search query \r\n") == "SQL injection in the search query"


def test_a_finding_title_stays_on_its_bullet_line():
    finding = Finding(
        id="S-01",
        category="security",
        severity="critical",
        path=JAVA,
        line=12,
        title="SQL injection\nin the search query",
        explanation="The query concatenates user input.",
    )
    assert "\n" not in finding_line(finding)


def test_finding_ids_are_listed_whole():
    ids = [f"S-{number:02d}" for number in range(1, 60)]
    summary = finding_ids(ids)
    assert summary.startswith("S-01, S-02, ")
    assert summary.endswith(", …")
    assert len(summary) <= MAX_SUMMARY_CHARS
    listed = summary.removesuffix(", …").split(", ")
    assert listed == ids[: len(listed)]


def test_the_diff_lists_the_paths_that_fit():
    assert diff_files(["src/Order.java", "src/OrderService.java"]) == "2 files: src/Order.java, src/OrderService.java"
    many = diff_files([f"src/Module{number}.java" for number in range(30)])
    assert many.startswith("30 files: src/Module0.java, src/Module1.java")
    assert many.endswith(", …")
    assert len(many) <= MAX_SUMMARY_CHARS


def test_a_single_long_path_is_cut_in_the_middle():
    summary = diff_files(["src/" + "nested/" * 30 + "CustomerService.java"])
    assert summary.startswith("1 file: src/")
    assert summary.endswith("CustomerService.java")


@pytest.mark.parametrize(
    ("tool_input", "summary"),
    [
        ({"file_path": "pom.xml"}, "pom.xml"),
        ({"file_path": "pom.xml", "offset": 1, "limit": 400}, "pom.xml:1-400"),
        ({"file_path": "pom.xml", "offset": "120"}, "pom.xml:120-"),
        ({"file_path": "pom.xml", "limit": 50}, "pom.xml:1-50"),
        ({"file_path": "pom.xml", "offset": "abc", "limit": -3}, "pom.xml"),
        ({"offset": 1}, None),
        ({"file_path": 42}, None),
    ],
)
def test_read_summary(tool_input, summary):
    assert tool_call("Read", tool_input) == summary


@pytest.mark.parametrize(
    ("tool_input", "summary"),
    [
        ({"pattern": r"select\(", "path": "src/", "glob": "*.java"}, r"/select\(/ in src/ (*.java)"),
        ({"pattern": "TODO"}, "/TODO/"),
        ({"path": "src/"}, "in src/"),
        ({"pattern": ["not", "a", "string"]}, None),
    ],
)
def test_grep_summary(tool_input, summary):
    assert tool_call("Grep", tool_input) == summary


@pytest.mark.parametrize(
    ("tool_input", "summary"),
    [
        ({"pattern": "src/**/*.java"}, "src/**/*.java"),
        ({"pattern": "*.java", "path": "src"}, "*.java in src"),
        ({}, None),
    ],
)
def test_glob_summary(tool_input, summary):
    assert tool_call("Glob", tool_input) == summary


def test_arguments_that_are_not_an_object_give_no_summary():
    assert tool_call("Read", "pom.xml") is None
    assert tool_call("Grep", None) is None


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("Read", {"file_path": "pom.xml", "offset": 10**5000}),
        ("Read", {"file_path": {"nested": ["pom.xml"]}, "offset": [1], "limit": {"n": 1}}),
        ("Grep", {"pattern": {"regex": "x"}, "path": ["src"], "glob": None}),
    ],
)
def test_hostile_arguments_never_raise(tool_name, tool_input):
    summary = tool_call(tool_name, tool_input)
    assert summary is None or len(summary) <= MAX_SUMMARY_CHARS
