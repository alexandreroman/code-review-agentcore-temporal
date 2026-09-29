from agentcore_review_shared.summaries import MAX_SUMMARY_BYTES, MAX_SUMMARY_CHARS, fit

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
