from libs.domain.enums import PriorityBand
from libs.domain.policy.priority import score


def test_all_zero_signals_score_low():
    s, band, signals = score({})
    assert s == 0
    assert band == PriorityBand.low
    assert len(signals) == 6


def test_all_max_signals_score_critical():
    s, band, _ = score(
        {
            "sentiment_score": 1.0,
            "urgency_keyword_hit": True,
            "customer_segment_score": 1.0,
            "outage_scope_score": 1.0,
            "prior_contacts_score": 1.0,
            "sla_age_score": 1.0,
        }
    )
    assert s == 100
    assert band == PriorityBand.critical


def test_score_is_clamped_and_banded():
    s, band, _ = score({"sentiment_score": 1.0, "outage_scope_score": 1.0})
    assert 0 <= s <= 100
    assert band in (PriorityBand.high, PriorityBand.normal)
