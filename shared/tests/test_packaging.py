import importlib


def test_workspace_packages_are_importable():
    for name in ("agentcore_review_shared", "agentcore_review_router", "agentcore_review_worker"):
        assert importlib.import_module(name).__name__ == name
