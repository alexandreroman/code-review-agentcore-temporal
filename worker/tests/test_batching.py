import pytest
from agentcore_review_worker.batching import (
    MAX_BATCH_FILES,
    MAX_BATCH_PATCH_BYTES,
    is_excluded,
    make_batches,
    partition,
)
from agentcore_review_worker.models import ChangedFile


def cf(path: str, patch_bytes: int | None = 100) -> ChangedFile:
    return ChangedFile(path=path, patch_bytes=patch_bytes)


@pytest.mark.parametrize("path", ["uv.lock", "poetry.lock", "web/package-lock.json", "static/app.min.js"])
def test_lock_and_generated_files_are_excluded(path):
    assert is_excluded(cf(path))


@pytest.mark.parametrize(
    "path", ["src/main/java/com/example/orders/OrderService.java", "README.md", "OrderLock.java", "app.js"]
)
def test_regular_files_are_reviewed(path):
    assert not is_excluded(cf(path))


def test_partition_keeps_order():
    files = [cf("A.java"), cf("uv.lock"), cf("B.java"), cf("img.png", None)]
    reviewed, excluded = partition(files)
    assert [f.path for f in reviewed] == ["A.java", "B.java"]
    assert [f.path for f in excluded] == ["uv.lock", "img.png"]


def test_file_count_threshold():
    files = [cf(f"F{i}.java") for i in range(MAX_BATCH_FILES + 1)]
    batches = make_batches(files)
    assert [len(b) for b in batches] == [MAX_BATCH_FILES, 1]


def test_patch_size_threshold():
    files = [cf("A.java", 40_000), cf("B.java", 30_000), cf("C.java", 10_000)]
    assert [[f.path for f in b] for b in make_batches(files)] == [["A.java"], ["B.java", "C.java"]]


def test_oversized_file_gets_its_own_batch():
    files = [cf("A.java", 100), cf("Big.java", MAX_BATCH_PATCH_BYTES * 2), cf("C.java", 100)]
    assert [[f.path for f in b] for b in make_batches(files)] == [["A.java"], ["Big.java"], ["C.java"]]
