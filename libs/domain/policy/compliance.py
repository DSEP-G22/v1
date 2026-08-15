"""Draft-response compliance checks, regex-based, pure function."""

from __future__ import annotations

import re

from libs.domain.contracts.analysis import PolicyFinding

_REFUND_PROMISE = re.compile(
    r"\b(we will|we'll|you will receive|you'll get)\b[^.]{0,40}\b(refund|credit|compensation)\b",
    re.IGNORECASE,
)
_ABSOLUTE_GUARANTEE = re.compile(
    r"\b(guarantee(d)?|100%|never fail|always works|no matter what)\b", re.IGNORECASE
)
_GREETING = re.compile(r"^\s*(hi|hello|dear|good (morning|afternoon|evening))\b", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_NIC = re.compile(r"\b\d{9}[vVxX]\b|\b\d{12}\b")

DEFAULT_RULES: dict[str, bool] = {
    "no_refund_promise": True,
    "no_absolute_guarantee": True,
    "requires_greeting": True,
    "no_pii_echo": True,
}


def check(draft_text: str, policy_rules: dict[str, bool] = DEFAULT_RULES) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []

    if policy_rules.get("no_refund_promise", True):
        for m in _REFUND_PROMISE.finditer(draft_text):
            findings.append(
                PolicyFinding(
                    rule_id="no_refund_promise",
                    severity="high",
                    message="Draft promises a refund/credit outside an approved action.",
                    span=(m.start(), m.end()),
                )
            )

    if policy_rules.get("no_absolute_guarantee", True):
        for m in _ABSOLUTE_GUARANTEE.finditer(draft_text):
            findings.append(
                PolicyFinding(
                    rule_id="no_absolute_guarantee",
                    severity="medium",
                    message="Draft makes an absolute guarantee.",
                    span=(m.start(), m.end()),
                )
            )

    if policy_rules.get("requires_greeting", True) and not _GREETING.match(draft_text.strip()):
        findings.append(
            PolicyFinding(
                rule_id="requires_greeting",
                severity="low",
                message="Draft is missing an opening greeting.",
            )
        )

    if policy_rules.get("no_pii_echo", True):
        for pattern, label in ((_EMAIL, "email"), (_PHONE, "phone"), (_CARD, "card"), (_NIC, "nic")):
            for m in pattern.finditer(draft_text):
                findings.append(
                    PolicyFinding(
                        rule_id="no_pii_echo",
                        severity="high",
                        message=f"Draft echoes back apparent {label} PII.",
                        span=(m.start(), m.end()),
                    )
                )

    return findings
