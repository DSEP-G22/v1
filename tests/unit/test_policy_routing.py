from libs.domain.enums import Department
from libs.domain.policy.routing import evaluate

RULES = [
    {"id": "R-OUTAGE", "when": {"keywords_any": ["no internet", "outage"]}, "department": "network_operations"},
    {"id": "R-BILLING", "when": {"keywords_any": ["refund", "invoice"]}, "department": "billing"},
]


def test_first_matching_rule_wins():
    department = evaluate(RULES, {"text": "I have no internet since morning", "classifier_department": Department.general})
    assert department == Department.network_operations


def test_falls_back_to_classifier_department_when_no_rule_matches():
    department = evaluate(RULES, {"text": "just saying hello", "classifier_department": Department.sales})
    assert department == Department.sales


def test_rule_order_determines_precedence():
    department = evaluate(RULES, {"text": "outage caused a refund request", "classifier_department": Department.general})
    assert department == Department.network_operations
