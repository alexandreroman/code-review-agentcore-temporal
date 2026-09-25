import logging

from tar_worker.__main__ import main


def test_main_logs_namespace_and_task_queue(monkeypatch, caplog):
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "test-namespace")
    monkeypatch.setenv("DEV_TASK_QUEUE", "test-queue")

    with caplog.at_level(logging.INFO):
        main()

    assert "namespace=test-namespace" in caplog.text
    assert "task_queue=test-queue" in caplog.text
