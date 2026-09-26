import importlib


def test_workspace_packages_are_importable():
    for name in ("agentic_review_shared", "agentic_review_router", "agentic_review_worker"):
        assert importlib.import_module(name).__name__ == name
