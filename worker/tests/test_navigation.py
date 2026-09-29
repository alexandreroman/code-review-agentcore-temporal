import os
import time
from pathlib import Path

import pytest
from agentcore_review_worker import navigation
from agentcore_review_worker.models import FileChange
from agentcore_review_worker.navigation import (
    MAX_FILE_BYTES,
    MAX_GLOB_RESULTS,
    MAX_GREP_RESULTS,
    MAX_READ_BYTES,
    MAX_READ_LINES,
    glob_files,
    glob_paths,
    grep_files,
    read_file,
    split_changes,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "search.py").write_text("from app.db import run\n\ndef search(name):\n    return run(f'{name}')\n")
    (root / "app" / "db.py").write_text("def run(query):\n    return query\n")
    (root / "README.md").write_text("# demo\n")
    (root / "logo.bin").write_bytes(b"\x89PNG\x00\x01run(")
    (tmp_path / "secret.txt").write_text("run( outside\n")
    return root


def test_glob_lists_relative_paths(repo):
    assert glob_files(repo, "**/*.py") == "app/db.py\napp/search.py"
    assert glob_files(repo, "*.py", path="app") == "app/db.py\napp/search.py"
    assert glob_files(repo, "*.go") == "No files found."


def test_glob_is_capped(tmp_path):
    root = tmp_path / "many"
    root.mkdir()
    for i in range(MAX_GLOB_RESULTS + 7):
        (root / f"f{i:04d}.txt").write_text("x")
    out = glob_files(root, "*.txt").splitlines()
    assert len(out) == MAX_GLOB_RESULTS + 1 and out[-1] == "... truncated: 7 more files"


@pytest.mark.parametrize("path", ["..", "../", "/etc", "app/../.."])
def test_glob_refuses_paths_outside_the_repository(repo, path):
    assert glob_files(repo, "*", path=path).startswith("Error:")


def test_grep_finds_matches_with_line_numbers(repo):
    assert grep_files(repo, r"def run") == "app/db.py:1: def run(query):"
    out = grep_files(repo, r"run\(")
    assert "app/search.py:4: return run(f'{name}')" in out and "app/db.py:2" not in out


@pytest.fixture
def nested_repo(tmp_path: Path) -> Path:
    root = tmp_path / "nested"
    (root / "app" / "sub" / "deep").mkdir(parents=True)
    (root / "top.py").write_text("top\n")
    (root / "app" / "a.py").write_text("a\n")
    (root / "app" / "sub" / "b.py").write_text("b\n")
    (root / "app" / "sub" / "deep" / "c.py").write_text("c\n")
    return root


def test_grep_glob_filter_matches_recursive_patterns_like_glob(nested_repo):
    def files_matched(glob):
        return {line.split(":", 1)[0] for line in grep_files(nested_repo, ".", glob=glob).splitlines()}

    assert files_matched("**/*.py") == {"top.py", "app/a.py", "app/sub/b.py", "app/sub/deep/c.py"}
    assert files_matched("app/**/*.py") == {"app/a.py", "app/sub/b.py", "app/sub/deep/c.py"}
    assert files_matched("*.py") == {"top.py", "app/a.py", "app/sub/b.py", "app/sub/deep/c.py"}


def test_grep_filters_by_glob_and_path(repo):
    assert grep_files(repo, "demo", glob="*.md") == "README.md:1: # demo"
    assert grep_files(repo, "demo", glob="*.py") == "No matches found."
    assert grep_files(repo, "def", path="app/db.py") == "app/db.py:1: def run(query):"


def test_grep_skips_binary_files(repo):
    assert "logo.bin" not in grep_files(repo, r"run\(")


def test_grep_invalid_regex_returns_an_error(repo):
    assert grep_files(repo, "(").startswith("Error: invalid regular expression")


def test_grep_is_capped_and_clips_long_lines(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    (root / "a.txt").write_text("\n".join(["match " + "x" * 1000] * (MAX_GREP_RESULTS + 5)))
    out = grep_files(root, "match").splitlines()
    assert len(out) == MAX_GREP_RESULTS + 1 and out[-1] == "... truncated: more matches not shown"
    assert len(out[0]) < 400


def test_read_small_file_without_header(repo):
    assert read_file(repo, "app/db.py") == "     1\tdef run(query):\n     2\t    return query"


def test_read_large_file_shows_a_window_and_a_header(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    (root / "big.py").write_text("\n".join(f"line {i}" for i in range(1, 1001)))
    out = read_file(root, "big.py").splitlines()
    assert out[0].startswith("[big.py: 1000 lines") and "showing lines 1-400" in out[0]
    assert len(out) == 1 + MAX_READ_LINES and out[-1] == "   400\tline 400"
    tail = read_file(root, "big.py", offset=950, limit=100).splitlines()
    assert "showing lines 950-1000" in tail[0] and tail[-1] == "  1000\tline 1000"
    capped = read_file(root, "big.py", offset=1, limit=5000).splitlines()
    assert len(capped) == 1 + MAX_READ_LINES


def test_read_respects_the_byte_budget(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    (root / "wide.txt").write_text("\n".join("y" * 1000 for _ in range(300)))
    out = read_file(root, "wide.txt")
    assert len(out.encode()) <= MAX_READ_BYTES + 200 and "showing lines 1-" in out.splitlines()[0]


def test_read_errors(repo):
    assert read_file(repo, "missing.py").startswith("Error:")
    assert read_file(repo, "logo.bin").startswith("Error:")
    assert read_file(repo, "../secret.txt").startswith("Error:")
    assert read_file(repo, "/etc/passwd").startswith("Error:")
    assert read_file(repo, "app/db.py", offset=99).startswith("Error:")


def test_symlink_pointing_outside_is_refused(repo, tmp_path):
    os.symlink(tmp_path / "secret.txt", repo / "link.txt")
    assert read_file(repo, "link.txt").startswith("Error:")
    assert "link.txt" not in glob_files(repo, "*.txt")
    assert "outside" not in grep_files(repo, "outside")


def test_tools_report_malformed_paths_instead_of_raising(repo):
    bad_path = "a\x00b"
    for result in (
        read_file(repo, bad_path),
        grep_files(repo, "x", path=bad_path),
        glob_files(repo, "*", path=bad_path),
    ):
        assert result.startswith("Error:") and repr(bad_path) in result


def test_empty_file(tmp_path):
    root = tmp_path / "e"
    root.mkdir()
    (root / "empty.py").write_text("")
    assert read_file(root, "empty.py") == "(empty file)"


def test_read_accepts_numeric_strings_for_offset_and_limit(tmp_path):
    root = tmp_path / "r2"
    root.mkdir()
    (root / "big.py").write_text("\n".join(f"line {i}" for i in range(1, 1001)))
    assert read_file(root, "big.py", offset="950", limit="100") == read_file(root, "big.py", offset=950, limit=100)


def test_read_rejects_non_integer_offset_and_limit(repo):
    assert read_file(repo, "app/db.py", offset="abc").startswith("Error:")
    assert read_file(repo, "app/db.py", limit="ten").startswith("Error:")


def test_grep_stops_a_catastrophic_regular_expression(tmp_path, monkeypatch):
    monkeypatch.setattr(navigation, "GREP_TIME_BUDGET", 0.5)
    root = tmp_path / "slow"
    root.mkdir()
    (root / "a.txt").write_text("a" * 60 + "b\n")
    started = time.monotonic()
    out = grep_files(root, r"(a|aa)+$")
    assert time.monotonic() - started < 5
    assert out.splitlines()[0] == "No matches found." and "search stopped after 0.5 s" in out


def test_grep_skips_files_larger_than_the_bound(tmp_path):
    root = tmp_path / "large"
    root.mkdir()
    (root / "big.txt").write_text("needle\n" * (MAX_FILE_BYTES // 7 + 10))
    (root / "small.txt").write_text("needle\n")
    out = grep_files(root, "needle").splitlines()
    assert out == ["small.txt:1: needle", f"... skipped 1 files larger than {MAX_FILE_BYTES} bytes"]


def test_missing_paths_and_non_directories_are_reported(repo):
    assert glob_files(repo, "*", path="nope") == "Error: path 'nope' not found."
    assert grep_files(repo, "x", path="nope") == "Error: path 'nope' not found."
    assert glob_files(repo, "*", path="README.md") == "Error: path 'README.md' is not a directory."


def test_read_explains_directories_small_limits_and_large_files(repo, tmp_path):
    assert read_file(repo, "app") == "Error: 'app' is a directory: use Glob to list its files."
    assert read_file(repo, "app/db.py", limit=0) == "Error: limit must be at least 1."
    assert read_file(repo, "app/db.py", limit="-3") == "Error: limit must be at least 1."
    (repo / "huge.txt").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    assert read_file(repo, "huge.txt").startswith("Error: 'huge.txt' is too large to read")


@pytest.mark.parametrize(
    ("pattern", "path"), [("**/*.py", None), ("*.py", None), ("*.py", "app"), ("**/*.py", "app/sub"), ("*.go", None)]
)
def test_glob_paths_answers_like_glob_files(nested_repo, pattern, path):
    paths = [p.relative_to(nested_repo).as_posix() for p in nested_repo.rglob("*") if p.is_file()]
    assert glob_paths(paths, pattern, path) == glob_files(nested_repo, pattern, path)


def test_glob_paths_errors():
    assert glob_paths(["app/a.py"], "*", "../x").startswith("Error: path '../x' is outside the repository")
    assert glob_paths(["app/a.py"], "*", "/etc").startswith("Error:")
    assert glob_paths(["app/a.py"], "*", "nope") == "Error: path 'nope' not found."
    for path in ("app/a.py", "./app/a.py", "app/a.py/"):
        assert glob_paths(["app/a.py"], "*", path) == f"Error: path {path!r} is not a directory."
    assert glob_paths(["app/a.py"], "").startswith("Error: invalid glob pattern")


@pytest.mark.parametrize("pattern", ["../*", "app/../../*", "/etc/*"])
def test_glob_refuses_patterns_outside_the_repository(repo, pattern):
    expected = f"Error: glob pattern {pattern!r} reaches outside the repository."
    assert glob_files(repo, pattern) == expected
    assert glob_paths(["app/a.py"], pattern) == expected


def test_split_changes_rejects_protected_and_escaping_paths():
    paths = [
        "src/A.java",
        "./src//B.java",
        ".github/workflows/ci.yml",
        ".GitHub/x",
        "../etc/passwd",
        "/Abs.java",
        "",
        "src/A.java",
    ]
    accepted, rejected = split_changes([FileChange(path=p, new_content=f"{i}") for i, p in enumerate(paths)])
    assert [(c.path, c.new_content) for c in accepted] == [("src/A.java", "7"), ("src/B.java", "1")]
    assert rejected == [".github/workflows/ci.yml", ".GitHub/x", "../etc/passwd", "/Abs.java", ""]
