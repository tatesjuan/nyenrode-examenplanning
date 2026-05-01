import streamlit as st
from datetime import date
from utils.data import get_location, get_assigned_exams, slot_capacity_used, slot_hs_needed


def get_calendar_week(d: str) -> int:
    return date.fromisoformat(d).isocalendar()[1]

def get_weekday(d: str) -> int:
    """1=Mon, 7=Sun"""
    return date.fromisoformat(d).isoweekday()


def is_morning_blocked(d: str) -> bool:
    """Ma/Di/Vr ochtend is geblokkeerd, tenzij het een BScBA examenweek is."""
    weekday = get_weekday(d)
    if weekday not in [1, 2, 5]:  # Mon, Tue, Fri
        return False
    cw = get_calendar_week(d)
    exam_weeks = st.session_state.get("exam_weeks_mornings", [42, 50])
    return cw not in exam_weeks


def is_fau_day_breukelen(d: str) -> bool:
    """Controleer of er op deze dag een FAU-examen in Breukelen is ingepland."""
    for exam in st.session_state.exams:
        if not exam.get("fau"):
            continue
        if exam.get("slot_id") is None:
            continue
        slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
        if slot and slot["date"] == d:
            loc = get_location(slot["location_id"])
            if loc and loc["campus"] == "Breukelen":
                return True
    return False


def get_fau_exam_on_date(d: str) -> dict | None:
    """Geeft het FAU-examen terug als dat op deze datum gepland staat."""
    for exam in st.session_state.exams:
        if not exam.get("fau") or exam.get("slot_id") is None:
            continue
        slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
        if slot and slot["date"] == d:
            return exam
    return None


def check_constraints(exam: dict, slot: dict, override: bool = False) -> dict:
    """
    Controleert alle constraints voor het plannen van een examen in een slot.
    Geeft een dict terug met 'ok' (bool) en 'fouten' (lijst van foutmeldingen).
    """
    fouten = []
    waarschuwingen = []

    d = slot["date"]
    tb = slot["time_block"]
    loc = get_location(slot["location_id"])

    # Al ingepland in dit slot?
    if exam["id"] in slot["assigned_exam_ids"]:
        fouten.append("Dit examen staat al in dit slot.")

    # Al ingepland ergens anders?
    if exam.get("slot_id") and exam["slot_id"] != slot["id"]:
        fouten.append(f"Dit examen is al ingepland in een ander slot.")

    # FAU-constraint: als het examen zelf FAU is
    if exam.get("fau") and loc and loc["campus"] == "Breukelen":
        # FAU mag, maar blokkeer de rest van de dag in Breukelen
        if len(slot["assigned_exam_ids"]) > 0:
            fouten.append("FAU-examen moet als enige examen in dit slot staan.")

    # FAU-constraint: als er al een FAU op deze dag in Breukelen staat
    if not exam.get("fau") and loc and loc["campus"] == "Breukelen":
        if is_fau_day_breukelen(d):
            if not override:
                fouten.append("Op deze dag staat een FAU-tentamen gepland. Geen andere tentamens mogelijk in Breukelen.")
            else:
                waarschuwingen.append("OVERRIDE: FAU-dagblokkade omzeild door planner.")

    # Ochtend-blokkering
    if tb == "ochtend" and is_morning_blocked(d):
        if not override:
            fouten.append("Maandag-, dinsdag- en vrijdagochtend zijn geblokkeerd buiten BScBA-examenweken.")
        else:
            waarschuwingen.append("OVERRIDE: Ochtend-blokkering omzeild door planner.")

    # Capaciteitscheck
    if loc:
        used = slot_capacity_used(slot)
        if used + exam["students"] > loc["capacity"]:
            restant = loc["capacity"] - used
            fouten.append(
                f"Capaciteit overschreden: {restant} plekken beschikbaar, examen vraagt {exam['students']}."
            )

        # Overloopruimtes: alleen voor kleine aantallen
        if not loc["primary"] and exam["students"] > loc["capacity"]:
            fouten.append(
                f"{loc['name']} is een overloopruimte (max {loc['capacity']} st.). "
                f"Dit examen heeft {exam['students']} studenten."
            )

    # HS-constraint
    hs_avail = st.session_state.hs_per_slot.get(slot["id"], 3)
    new_n_exams = len(slot["assigned_exam_ids"]) + 1
    import math
    hs_nodig = math.ceil(new_n_exams / 2)
    if hs_nodig > hs_avail:
        if not override:
            fouten.append(
                f"Onvoldoende HS: {hs_nodig} hoofdsurveillant(en) nodig bij {new_n_exams} examens, "
                f"{hs_avail} beschikbaar in dit slot."
            )
        else:
            waarschuwingen.append(f"OVERRIDE: HS-tekort ({hs_nodig} nodig, {hs_avail} beschikbaar) omzeild.")

    return {
        "ok": len(fouten) == 0,
        "fouten": fouten,
        "waarschuwingen": waarschuwingen,
    }


def assign_exam_to_slot(exam: dict, slot: dict):
    """Plant een examen in een slot (na constraint-check)."""
    # Verwijder uit vorig slot indien van toepassing
    if exam.get("slot_id"):
        old_slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
        if old_slot and exam["id"] in old_slot["assigned_exam_ids"]:
            old_slot["assigned_exam_ids"].remove(exam["id"])

    slot["assigned_exam_ids"].append(exam["id"])
    exam["slot_id"] = slot["id"]
    exam["status"] = "gepland"


def unassign_exam(exam: dict):
    """Verwijder een examen uit zijn slot."""
    if exam.get("slot_id"):
        slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
        if slot and exam["id"] in slot["assigned_exam_ids"]:
            slot["assigned_exam_ids"].remove(exam["id"])
    exam["slot_id"] = None
    exam["status"] = "submitted"
