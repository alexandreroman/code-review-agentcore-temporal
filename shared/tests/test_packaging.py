import importlib


def test_workspace_packages_are_importable():
    for name in ("tar_shared", "tar_router", "tar_worker"):
        assert importlib.import_module(name).__name__ == name
