import pandas as pd
import io
from datetime import date
import streamlit as st
from utils.data import get_location, get_slot, slot_capacity_used, slot_hs_needed, slot_surv_needed


def export_facilitor() -> bytes:
    """Genereert een Excel-export in het Facilitor-formaat."""
    rows = []
    planned = [e for e in st.session_state.exams if e.get("slot_id")]
    planned.sort(key=lambda e: (e["slot_id"] or "", e["name"]))

    for exam in planned:
        slot = get_slot(exam["slot_id"])
        if not slot:
            continue
        loc = get_location(slot["location_id"])
        tb = st.session_state.time_blocks.get(slot["time_block"], {})
        d = date.fromisoformat(slot["date"])
        hs_n = slot_hs_needed(slot)
        sv_n = slot_surv_needed(slot)
        rows.append({
            "Datum":              d.strftime("%d-%m-%Y"),
            "Dag":                ["Ma","Di","Wo","Do","Vr","Za","Zo"][d.weekday()],
            "Tijdstip":           f"{tb.get('start','')} - {tb.get('end','')}",
            "Tijdblok":           tb.get("label",""),
            "Tentamen":           exam["name"],
            "Programma":          exam["program"],
            "Type":               exam["type"],
            "Verwacht aantal":    exam["students"],
            "Locatie":            loc["name"] if loc else "",
            "Campus":             loc["campus"] if loc else "",
            "Format":             exam["format"],
            "Contactpersoon":     exam["contact"],
            "Budgetnummer":       exam.get("budget",""),
            "HS benodigd":        hs_n,
            "Surveillanten":      sv_n,
            "FAU":                "Ja" if exam.get("fau") else "Nee",
            "Opmerkingen":        exam.get("notes",""),
        })

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Facilitor export")
        ws = writer.sheets["Facilitor export"]
        ws.set_column("A:A", 12)
        ws.set_column("C:C", 18)
        ws.set_column("E:E", 40)
        ws.set_column("F:F", 22)
        ws.set_column("M:M", 18)
    return buf.getvalue()


def export_surveillanten_matrix() -> bytes:
    """Exporteert de beschikbaarheidsmatrix van surveillanten als Excel."""
    supervisors = st.session_state.supervisors
    avail = st.session_state.availability
    slots_with_exams = [s for s in st.session_state.slots if s["assigned_exam_ids"]]

    from utils.data import get_assigned_exams
    rows = []
    for slot in slots_with_exams:
        d = date.fromisoformat(slot["date"])
        loc = get_location(slot["location_id"])
        tb = st.session_state.time_blocks.get(slot["time_block"], {})
        exams = get_assigned_exams(slot)
        row = {
            "Datum":    d.strftime("%d-%m-%Y"),
            "Tijdstip": f"{tb.get('start','')}–{tb.get('end','')}",
            "Locatie":  loc["name"] if loc else "",
            "Tentamens": " | ".join(e["name"] for e in exams if e),
            "Studenten": slot_capacity_used(slot),
            "HS nodig":  slot_hs_needed(slot),
        }
        for sup in supervisors:
            a = next((x for x in avail
                      if x["supervisor_id"] == sup["id"] and x["slot_id"] == slot["id"]), None)
            status = a["status"] if a else "open"
            label = {"hs": "X/H", "surv": "X", "nee": "", "open": "?"}.get(status, "?")
            row[sup["name"]] = label
        rows.append(row)

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Surveillanten")
    return buf.getvalue()
