# SOP: Billing disputes

## Symptoms
- Customer disputes a charge on their invoice as incorrect or unexpected.
- Customer reports a payment was made but not reflected on the account.
- Customer was charged after cancelling service.

## Diagnosis
1. Pull the invoice history and payment ledger for the account before responding, never
   confirm or deny a charge without checking the ledger first.
2. Distinguish a genuine billing error (duplicate charge, pricing mismatch with the signed plan)
   from a misunderstood but correct charge (pro-rated final month, equipment fee).
3. Charges after a confirmed cancellation date are always refundable; verify the cancellation
   effective date in the account system first.

## Procedure: Issue billing credit
1. Confirm the dispute is a genuine billing error per the ledger.
2. Issue a credit via `issue_billing_credit` for the disputed amount, using reason code that
   matches the ledger finding (e.g. `duplicate_charge`, `post_cancellation_charge`).
3. Credits above the pre-approved threshold require lead approval before sending, do not
   promise a credit amount to the customer until the credit action has been recorded.

## Procedure: Resend invoice
If the dispute is a "payment not reflected" case with no ledger discrepancy, resend the invoice
and payment confirmation via `resend_invoice` and explain the reflected balance.

## Compliance note
Never promise a specific refund amount or timeline in a draft reply before the corresponding
`agent_decision` and action execution exist, see `policy/compliance.py`.
