"""Generates data/telecom_supplement.csv — hand-authored template rows covering
network_operations and field_service, the two departments Bitext has zero coverage for (see
notebooks/01_data_preparation.ipynb and config/department_map.yaml).

Same column schema as the Bitext CSV: flags, instruction, category, intent, response.
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

random.seed(22)

_OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "telecom_supplement.csv"

# category is a free label here (not one of Bitext's 11); config/department_map.yaml maps
# NETWORK -> network_operations and FIELDSERVICE -> field_service.

_ROUTER_NOUNS = ["router", "modem", "gateway", "ONT box", "home hub"]
_TIMEFRAMES = ["this morning", "since last night", "for the past hour", "since yesterday", "all week", "since I woke up"]
_LED_COLOURS = ["red", "solid red", "blinking red", "amber", "orange"]

NETWORK_TEMPLATES: list[tuple[str, str]] = [
    ("i have no internet connection {tf}", "no_internet_connection"),
    ("my internet has been down {tf}, please help", "no_internet_connection"),
    ("there is no internet at my house {tf}", "no_internet_connection"),
    ("we lost internet access {tf} and nothing i try fixes it", "no_internet_connection"),
    ("the {router} power light is {led}", "router_led_issue"),
    ("my {router} shows a {led} light and wont connect", "router_led_issue"),
    ("the internet light on my {router} is off", "router_led_issue"),
    ("my {router} keeps rebooting on its own", "router_led_issue"),
    ("my internet speed is way slower than what i pay for", "slow_internet_speed"),
    ("downloads are extremely slow {tf}", "slow_internet_speed"),
    ("the connection speed dropped a lot {tf}", "slow_internet_speed"),
    ("streaming keeps buffering because the speed is too low", "slow_internet_speed"),
    ("my connection keeps dropping every few minutes", "intermittent_connection"),
    ("the wifi disconnects randomly throughout the day", "intermittent_connection"),
    ("internet cuts out intermittently {tf}", "intermittent_connection"),
    ("the line keeps losing sync and reconnecting", "intermittent_connection"),
    ("there is no dial tone on my landline", "no_dial_tone"),
    ("my phone line has no dial tone {tf}", "no_dial_tone"),
    ("i pick up the phone and hear nothing, no dial tone at all", "no_dial_tone"),
    ("the line status shows still synchronising and never finishes", "line_synchronization_issue"),
    ("my {router} has been stuck syncing {tf}", "line_synchronization_issue"),
    ("the connection never finishes synchronising with the exchange", "line_synchronization_issue"),
    ("is there an outage in my area, no one on my street has internet", "area_outage_report"),
    ("my whole neighbourhood seems to be without internet {tf}", "area_outage_report"),
    ("several of my neighbours also lost service {tf}", "area_outage_report"),
]

NETWORK_RESPONSES: dict[str, str] = {
    "no_internet_connection": "I'm sorry your internet is down. Let's start by power-cycling your {router}: unplug it for 30 seconds, then plug it back in and wait 2 minutes. Let me know if the internet light comes back on.",
    "router_led_issue": "Thanks for describing the light on your {router}. That colour usually points to a specific fault — I'll run a remote diagnostic on your line now and follow up with next steps.",
    "slow_internet_speed": "I understand slow speeds are frustrating. I'll run a line diagnostic to check your sync rate against your plan speed and let you know what I find.",
    "intermittent_connection": "Intermittent drops are usually a line-sync or cabling issue. I'll check your connection history for repeated re-sync events over the last 24 hours.",
    "no_dial_tone": "I'm sorry about the phone line. I'll trigger a remote line diagnostic to check for a dial-tone fault on your circuit.",
    "line_synchronization_issue": "A line stuck synchronising usually clears after a power-cycle, but if it persists I'll escalate to a line diagnostic on our end.",
    "area_outage_report": "Thanks for flagging this — I'll check our outage map for your area right away and update you as soon as I have more information.",
}

FIELDSERVICE_TEMPLATES: list[tuple[str, str]] = [
    ("can you send a technician to fix my {router}", "schedule_technician_visit"),
    ("i need someone to come look at my connection in person", "schedule_technician_visit"),
    ("please book a technician visit for my address", "schedule_technician_visit"),
    ("the remote fixes didn't work, i need an engineer on site", "schedule_technician_visit"),
    ("the technician never showed up for my appointment", "missed_technician_appointment"),
    ("i waited all day and no one came for the scheduled visit", "missed_technician_appointment"),
    ("my technician appointment was missed {tf}", "missed_technician_appointment"),
    ("i need to install a new internet connection at my new address", "equipment_installation_request"),
    ("please schedule an installation for my new house", "equipment_installation_request"),
    ("i just moved in and need the {router} installed", "equipment_installation_request"),
    ("the cable running into my house looks damaged", "cabling_issue_onsite"),
    ("there is a loose cable outside near the wall box", "cabling_issue_onsite"),
    ("the wiring to my house was damaged during storm work nearby", "cabling_issue_onsite"),
    ("can i get an update on when the technician will arrive", "technician_visit_status"),
    ("what time will the engineer come today", "technician_visit_status"),
    ("how long until the field technician gets to my address", "technician_visit_status"),
]

FIELDSERVICE_RESPONSES: dict[str, str] = {
    "schedule_technician_visit": "I can arrange an on-site visit. Let me check the earliest available slot for your address and confirm the appointment window with you.",
    "missed_technician_appointment": "I'm really sorry the technician didn't arrive as scheduled. I'll escalate this and get you rebooked for the earliest available slot, with priority handling.",
    "equipment_installation_request": "Happy to help set up service at your new address. I'll get an installation appointment booked and confirm what our technician will bring on the day.",
    "cabling_issue_onsite": "Thanks for reporting this — damaged cabling needs an on-site inspection. I'll schedule a technician to check and repair the wiring.",
    "technician_visit_status": "Let me check the current status of your scheduled visit and give you an updated arrival window.",
}


def _fill(template: str) -> str:
    return template.format(
        tf=random.choice(_TIMEFRAMES), router=random.choice(_ROUTER_NOUNS), led=random.choice(_LED_COLOURS)
    )


def _generate_rows(templates: list[tuple[str, str]], responses: dict[str, str], category: str, per_template: int) -> list[dict]:
    rows = []
    for template, intent in templates:
        for _ in range(per_template):
            instruction = _fill(template)
            response = _fill(responses[intent])
            rows.append(
                {"flags": "B", "instruction": instruction, "category": category, "intent": intent, "response": response}
            )
    return rows


def main() -> None:
    rows = _generate_rows(NETWORK_TEMPLATES, NETWORK_RESPONSES, "NETWORK", per_template=10)
    rows += _generate_rows(FIELDSERVICE_TEMPLATES, FIELDSERVICE_RESPONSES, "FIELDSERVICE", per_template=10)
    random.shuffle(rows)

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["flags", "instruction", "category", "intent", "response"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {_OUT_PATH}")


if __name__ == "__main__":
    main()
