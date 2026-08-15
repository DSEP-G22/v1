# SOP: Router power issues

## Symptoms
- Router will not power on (no LEDs lit at all).
- Power LED solid red.
- Power LED blinking red, router stuck in a reboot loop.

## Diagnosis
1. Confirm the power adapter is the original unit rated for this router model, third-party
   adapters under-supply current and cause a solid red power LED.
2. If the power LED blinks red continuously and the router never reaches a steady state within
   3 minutes, suspect a firmware crash loop rather than a hardware fault.

## Procedure: Power-cycle the router
1. Unplug the router's power adapter from the wall outlet (not just the router).
2. Wait 30 seconds.
3. Plug the adapter back in and wait 2 minutes for full boot.
4. Confirm the power LED goes solid green/blue and the internet LED begins syncing.

## Procedure: Factory reset router
1. Locate the recessed reset button on the rear panel.
2. Hold for 10 seconds until all LEDs flash simultaneously.
3. Router reboots to factory defaults; reconfigure WAN credentials from the customer's saved
   backup profile in the provisioning system.

## Procedure: Dispatch replacement power supply
If power-cycling does not resolve a solid red power LED and the adapter output tests below
spec, dispatch a replacement PSU (same part number as printed on the router base plate). Do not
substitute a higher-voltage adapter.

## Escalation
If the router still will not power on after a confirmed-good power supply, escalate to field
service for on-site hardware inspection.
