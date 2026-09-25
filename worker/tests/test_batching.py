import pytest
from tar_worker.batching import MAX_BATCH_FILES, MAX_BATCH_PATCH_BYTES, is_excluded, make_batches, partition
from tar_worker.models import ChangedFile


def cf(path: str, patch_bytes: int | None = 100, status: str = "modified") -> ChangedFile:
    return ChangedFile(path=path, status=status, additions=1, deletions=0, patch_bytes=patch_bytes)


@pytest.mark.parametrize("path", ["uv.lock", "poetry.lock", "web/package-lock.json", "static/app.min.js"])
def test_lock_and_generated_files_are_excluded(path):
    assert is_excluded(cf(path))


def test_files_without_patch_are_excluded():
    assert is_excluded(cf("logo.png", patch_bytes=None))


@pytest.mark.parametrize("path", ["app/search.py", "README.md", "lockfile.py", "app.js"])
def test_regular_files_are_reviewed(path):
    assert not is_excluded(cf(path))


def test_partition_keeps_order():
    files = [cf("a.py"), cf("uv.lock"), cf("b.py"), cf("img.png", None)]
    reviewed, excluded = partition(files)
    assert [f.path for f in reviewed] == ["a.py", "b.py"]
    assert [f.path for f in excluded] == ["uv.lock", "img.png"]


def test_small_change_is_a_single_batch():
    files = [cf(f"f{i}.py") for i in range(3)]
    assert make_batches(files) == [files]


def test_no_files_no_batch():
    assert make_batches([]) == []


def test_file_count_threshold():
    files = [cf(f"f{i}.py") for i in range(MAX_BATCH_FILES + 1)]
    batches = make_batches(files)
    assert [len(b) for b in batches] == [MAX_BATCH_FILES, 1]


def test_patch_size_threshold():
    files = [cf("a.py", 40_000), cf("b.py", 30_000), cf("c.py", 10_000)]
    assert [[f.path for f in b] for b in make_batches(files)] == [["a.py"], ["b.py", "c.py"]]


def test_oversized_file_gets_its_own_batch():
    files = [cf("a.py", 100), cf("big.py", MAX_BATCH_PATCH_BYTES * 2), cf("c.py", 100)]
    assert [[f.path for f in b] for b in make_batches(files)] == [["a.py"], ["big.py"], ["c.py"]]
