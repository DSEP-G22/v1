# SOP: Line synchronisation faults

## Symptoms
- Internet LED amber/solid but never turns green.
- Internet LED off entirely (no WAN link detected).
- Speed test reports far below the provisioned plan speed.

## Diagnosis
1. An amber, non-blinking internet LED for more than 5 minutes after boot indicates the modem
   is failing to synchronise with the exchange/OLT, treat as a line synchronisation fault, not
   a router fault.
2. An internet LED that stays fully off usually means no WAN link is detected at all: check
   physical cabling before opening a line ticket.

## Procedure: Inspect and reseat WAN/coax cabling
1. Verify the WAN/coax cable is fully seated at both the router and the wall termination point.
2. Check for visible cable damage or a loose F-connector.
3. Reseat and retest before escalating further.

## Procedure: Run remote line diagnostic
1. Trigger the `run_line_diagnostic` action against the customer's circuit ID.
2. The diagnostic reports attenuation, SNR margin, and sync state from the DSLAM/OLT.
3. SNR margin below 6 dB or repeated sync loss in the last 24h indicates a line-side fault
   requiring a network operations ticket, not a customer-premises fix.

## Escalation
Persistent sync failure after a clean line diagnostic and confirmed-good cabling escalates to
network operations for exchange-side investigation.
