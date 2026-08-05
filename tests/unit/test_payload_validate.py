import pytest

from libs.domain.contracts.payload import PayloadInvalid, Provenance, UnifiedTicketPayload, validate_payload
from libs.domain.enums import Modality


def _payload(fused_text: str, spans: list[tuple[int, int]]) -> UnifiedTicketPayload:
    return UnifiedTicketPayload(
        ticket_id="t1",
        customer_id="c1",
        channel="web_portal",
        original_text="hello",
        fused_text=fused_text,
        provenance=[
            Provenance(modality=Modality.text, source="original_text", span=s, confidence=1.0)
            for s in spans
        ],
    )


def test_valid_payload_passes():
    fused = "[CUSTOMER_TEXT] hello"
    validate_payload(_payload(fused, [(0, len(fused))]))


def test_empty_fused_text_raises():
    with pytest.raises(PayloadInvalid):
        validate_payload(_payload("", []))


def test_span_exceeding_length_raises():
    fused = "short"
    with pytest.raises(PayloadInvalid):
        validate_payload(_payload(fused, [(0, 100)]))


def test_overlapping_spans_raise():
    fused = "0123456789"
    with pytest.raises(PayloadInvalid):
        validate_payload(_payload(fused, [(0, 5), (3, 8)]))
