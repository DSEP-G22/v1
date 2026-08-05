from libs.domain.policy.action_selection import ActionRegistryEntry, select

RESTART_ROUTER = ActionRegistryEntry(
    action_id="restart_router",
    mapped_faults=["router_offline"],
    requires_fields=["device_id"],
)
ISSUE_CREDIT = ActionRegistryEntry(
    action_id="issue_billing_credit",
    mapped_faults=["billing_dispute"],
    requires_fields=["amount_cents", "reason_code"],
    impact_limits={"max_amount_cents": 5000},
)


def test_select_returns_recommendation_when_permitted():
    rec = select("router_offline", [RESTART_ROUTER], {"device_id": "dev-1", "ticket_id": "t1"})
    assert rec is not None
    assert rec.action_id == "restart_router"


def test_select_returns_none_when_required_field_missing():
    rec = select("router_offline", [RESTART_ROUTER], {"ticket_id": "t1"})
    assert rec is None


def test_select_returns_none_when_over_impact_limit():
    rec = select(
        "billing_dispute",
        [ISSUE_CREDIT],
        {"amount_cents": 9000, "reason_code": "duplicate_charge", "ticket_id": "t1"},
    )
    assert rec is None


def test_select_returns_none_when_no_fault_match():
    rec = select("unmapped_fault", [RESTART_ROUTER], {"device_id": "dev-1"})
    assert rec is None
