from libs.domain.policy.compliance import check


def test_flags_refund_promise():
    findings = check("Hi there, we will refund your last payment immediately.")
    assert any(f.rule_id == "no_refund_promise" for f in findings)


def test_flags_absolute_guarantee():
    findings = check("Hello, this fix is guaranteed to work 100% of the time.")
    assert any(f.rule_id == "no_absolute_guarantee" for f in findings)


def test_flags_missing_greeting():
    findings = check("Your issue has been logged and will be reviewed.")
    assert any(f.rule_id == "requires_greeting" for f in findings)


def test_flags_pii_echo():
    findings = check("Hi, please confirm your card 4111 1111 1111 1111 is correct.")
    assert any(f.rule_id == "no_pii_echo" for f in findings)


def test_clean_draft_has_no_findings():
    findings = check("Hi Alex, thanks for reaching out, we're looking into the router issue now.")
    assert findings == []
