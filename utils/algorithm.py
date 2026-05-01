import streamlit as st
from utils.data import get_location, slot_capacity_used
from utils.constraints import check_constraints, assign_exam_to_slot


def auto_plan() -> dict:
    """
    Greedy auto-plan algoritme:
    1. Sorteert examens op studentaantal (groot → klein)
    2. Per examen: zoek het vroegste slot dat aan alle constraints voldoet
    3. Examens die niet passen: rapporteer als mislukt
    """
    # Reset alle toewijzingen
    for exam in st.session_state.exams:
        if exam.get("slot_id"):
            slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
            if slot and exam["id"] in slot["assigned_exam_ids"]:
                slot["assigned_exam_ids"].remove(exam["id"])
        exam["slot_id"] = None
        exam["status"] = "submitted"

    ingepland = []
    mislukt = []

    # Sorteer op studentaantal desc
    sorted_exams = sorted(st.session_state.exams, key=lambda e: e["students"], reverse=True)

    # FAU-examens eerst en apart
    fau = [e for e in sorted_exams if e.get("fau")]
    overig = [e for e in sorted_exams if not e.get("fau")]

    for exam in fau + overig:
        geplaatst = False
        # Filter slots op voorkeur
        voorkeur_slots = [
            s for s in st.session_state.slots
            if s["time_block"] == exam.get("time_pref", "middag")
            and s["location_id"] == exam.get("loc_pref", "BRK_SPORT")
        ]
        # Daarna alle slots als fallback
        alle_slots = [s for s in st.session_state.slots if s not in voorkeur_slots]
        kandidaten = voorkeur_slots + alle_slots

        for slot in kandidaten:
            result = check_constraints(exam, slot, override=False)
            if result["ok"]:
                assign_exam_to_slot(exam, slot)
                ingepland.append(exam["name"])
                geplaatst = True
                break

        if not geplaatst:
            mislukt.append({
                "naam": exam["name"],
                "studenten": exam["students"],
                "reden": "Geen geschikt slot gevonden dat aan alle constraints voldoet."
            })

    return {"ingepland": ingepland, "mislukt": mislukt}
