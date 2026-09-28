import pytest
from agentcore_review_shared.contract import Category
from agentcore_review_worker.models import FindingDraft, Severity
from pydantic import ValidationError


def draft(**overrides) -> FindingDraft:
    values = {
        "category": "security",
        "severity": "high",
        "path": "src/main/java/com/example/orders/OrderService.java",
        "line": 5,
        "title": "SQL injection",
        "explanation": "String concatenation in a JPQL query",
    }
    values.update(overrides)
    return FindingDraft(**values)


def test_only_critical_and_high_findings_are_blocking():
    assert Severity.CRITICAL.blocking and Severity.HIGH.blocking
    assert not Severity.MEDIUM.blocking and not Severity.LOW.blocking


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("category", "Security", Category.SECURITY),
        ("category", " PERFORMANCE ", Category.PERFORMANCE),
        ("severity", "Critical", Severity.CRITICAL),
        ("severity", " low ", Severity.LOW),
    ],
)
def test_enums_tolerate_case_and_spaces(field, raw, expected):
    finding = draft(**{field: raw})
    assert getattr(finding, field) is expected


def test_unknown_enum_values_are_still_rejected():
    with pytest.raises(ValidationError):
        draft(category="style")
