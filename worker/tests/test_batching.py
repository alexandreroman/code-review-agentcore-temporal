from agentcore_review_worker.batching import MAX_BATCH_FILES, MAX_BATCH_PATCH_BYTES, make_batches, partition
from agentcore_review_worker.models import ChangedFile


def cf(path: str, patch_bytes: int | None = 100) -> ChangedFile:
    return ChangedFile(path=path, patch_bytes=patch_bytes)


def test_lock_generated_and_binary_files_are_excluded_in_order():
    files = [
        cf("src/main/java/com/example/orders/OrderService.java"),
        cf("uv.lock"),
        cf("README.md"),
        cf("poetry.lock"),
        cf("OrderLock.java"),
        cf("web/package-lock.json"),
        cf("app.js"),
        cf("static/app.min.js"),
        cf("img.png", None),
    ]
    reviewed, excluded = partition(files)
    assert [f.path for f in reviewed] == [
        "src/main/java/com/example/orders/OrderService.java",
        "README.md",
        "OrderLock.java",
        "app.js",
    ]
    assert [f.path for f in excluded] == [
        "uv.lock",
        "poetry.lock",
        "web/package-lock.json",
        "static/app.min.js",
        "img.png",
    ]


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
