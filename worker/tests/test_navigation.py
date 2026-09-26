import os
from pathlib import Path

import pytest
from tar_worker.navigation import (
    MAX_GLOB_RESULTS,
    MAX_GREP_RESULTS,
    MAX_READ_LINES,
    glob_files,
    grep_files,
    read_file,
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


def test_glob_refuses_absolute_patterns(repo):
    assert glob_files(repo, "/etc/*").startswith("Error:")


def test_grep_finds_matches_with_line_numbers(repo):
    assert grep_files(repo, r"def run") == "app/db.py:1: def run(query):"
    out = grep_files(repo, r"run\(")
    assert "app/search.py:4: return run(f'{name}')" in out and "app/db.py:2" not in out


def test_grep_filters_by_glob_and_path(repo):
    assert grep_files(repo, "demo", glob="*.md") == "README.md:1: # demo"
    assert grep_files(repo, "demo", glob="*.py") == "No matches found."
    assert grep_files(repo, "def", path="app/db.py") == "app/db.py:1: def run(query):"


def test_grep_skips_binary_files_and_stays_inside(repo):
    out = grep_files(repo, r"run\(")
    assert "logo.bin" not in out and "secret.txt" not in out


def test_grep_invalid_regex_returns_an_error(repo):
    assert grep_files(repo, "(").startswith("Error: invalid regular expression")


def test_grep_is_capped_and_clips_long_lines(tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    (root / "a.txt").write_text("\n".join(["match " + "x" * 1000] * (MAX_GREP_RESULTS + 5)))
    out = grep_files(root, "match").splitlines()
    assert len(out) == MAX_GREP_RESULTS + 1 and out[-1] == "... truncated: 5 more matches"
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
    assert len(out.encode()) <= 40_000 + 200 and "showing lines 1-" in out.splitlines()[0]


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
    assert read_file(repo, "app/db.py", limit=1.5).startswith("Error:")
    assert read_file(repo, "app/db.py", offset=True).startswith("Error:")
