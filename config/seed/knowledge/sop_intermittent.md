# SOP: Intermittent connectivity

## Symptoms
- Internet LED green but blinking irregularly, connection drops for seconds at a time.
- Customer reports the connection working "on and off" throughout the day.
- Drops correlate with time of day (evening congestion) or weather (outdoor cabling).

## Diagnosis
1. Ask when drops occur, congestion-pattern drops (evenings, weekends) point to a capacity
   fault; random all-day drops point to cabling or hardware.
2. Run a remote line diagnostic (`run_line_diagnostic`) to check for repeated re-sync events in
   the last 24h, which corroborate an intermittent line fault.
3. If diagnostics are clean and drops persist, the fault is most likely on-premises wiring or a
   failing router, schedule a technician visit.

## Procedure: Run remote line diagnostic
See `sop_line_sync.md`, same action, interpreted here for intermittent (not total) loss
patterns.

## Procedure: Escalate to field service for on-site repair
1. Book the earliest available technician slot against the customer's address ID.
2. Attach the line diagnostic history and any router self-test logs to the visit ticket.
3. On-site technician checks external cabling, connectors, and signal splitters.

## Escalation
Repeated intermittent drops with three or more diagnostics run in 30 days and no on-premises
fault found escalate to network operations engineering for exchange-side capacity review.
