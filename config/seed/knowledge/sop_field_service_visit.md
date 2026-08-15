# SOP: Scheduling a field service visit

## When to use
- Hardware fault confirmed (router will not power on with a known-good PSU).
- Cabling fault outside the customer premises entry point.
- Any fault where remote diagnostics and procedures have been exhausted.

## Procedure: Schedule technician visit
1. Confirm the customer's service address ID is current in the account system.
2. Offer the earliest available slot; field visits are not same-day unless flagged `critical`
   priority band.
3. Book via `schedule_technician_visit` with `address_id` and `earliest_date`.
4. Summarise, in the draft reply, what the technician will check and roughly how long the visit
   takes (typically 30-60 minutes), do not promise an exact arrival time, only a window.

## Escalation
If a second visit is required for the same fault within 14 days, flag the ticket `critical`
priority band and route to the field service lead for manual review rather than auto-scheduling
a third visit.
