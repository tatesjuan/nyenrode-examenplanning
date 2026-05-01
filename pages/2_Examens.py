import streamlit as st
from utils.data import initialize_data
from utils.constraints import unassign_exam

initialize_data()
NY_RED = "#6B1F3A"
st.markdown(f"<style>h1,h2,h3{{color:{NY_RED};}}</style>", unsafe_allow_html=True)

if "role" not in st.session_state:
    st.warning("Log eerst in."); st.stop()

role = st.session_state.role
can_edit = role in ["Planner", "Head of Operations ASC", "Programmacoördinator"]
is_coordinator = role == "Programmacoördinator"

st.title("📝 Examens")

tab1, tab2 = st.tabs(["Overzicht", "Examen aanmelden"])

# ═══ TAB 1: Overzicht ═══
with tab1:
    exams = st.session_state.exams

    # Filters
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        status_filter = st.selectbox("Status", ["Alle", "Te plannen", "Gepland", "Bevestigd"])
    with f2:
        prog_options = ["Alle"] + sorted(set(e["program"] for e in exams))
        prog_filter = st.selectbox("Programma", prog_options)
    with f3:
        week_options = ["Alle"] + sorted(set(str(e["week"]) for e in exams))
        week_filter = st.selectbox("Week", week_options)
    with f4:
        fau_filter = st.selectbox("FAU", ["Alle", "Alleen FAU", "Geen FAU"])

    gefilterd = exams
    if status_filter == "Te plannen":
        gefilterd = [e for e in gefilterd if not e.get("slot_id")]
    elif status_filter == "Gepland":
        gefilterd = [e for e in gefilterd if e.get("slot_id") and e["status"] == "gepland"]
    elif status_filter == "Bevestigd":
        gefilterd = [e for e in gefilterd if e["status"] == "bevestigd"]
    if prog_filter != "Alle":
        gefilterd = [e for e in gefilterd if e["program"] == prog_filter]
    if week_filter != "Alle":
        gefilterd = [e for e in gefilterd if str(e["week"]) == week_filter]
    if fau_filter == "Alleen FAU":
        gefilterd = [e for e in gefilterd if e.get("fau")]
    elif fau_filter == "Geen FAU":
        gefilterd = [e for e in gefilterd if not e.get("fau")]

    # Statistieken
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gefilterd", len(gefilterd))
    c2.metric("Te plannen", len([e for e in gefilterd if not e.get("slot_id")]))
    c3.metric("Gepland", len([e for e in gefilterd if e.get("slot_id")]))
    c4.metric("Totaal studenten", sum(e["students"] for e in gefilterd))

    st.divider()

    # Tabel
    for exam in sorted(gefilterd, key=lambda e: (e["week"], -e["students"])):
        slot = None
        slot_info = "—"
        if exam.get("slot_id"):
            slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
            if slot:
                from utils.data import get_location
                from datetime import date
                loc = get_location(slot["location_id"])
                tb = st.session_state.time_blocks.get(slot["time_block"], {})
                d = date.fromisoformat(slot["date"])
                slot_info = f"{d.strftime('%d %b')} · {tb.get('label','')} · {loc['name'] if loc else ''}"

        status_kleur = {
            "submitted": "#E6F1FB",
            "gepland": "#EAF3DE",
            "bevestigd": "#F5EEF1",
        }.get(exam["status"], "#F1EFE8")

        fau_badge = " 🔴 **FAU**" if exam.get("fau") else ""

        with st.expander(f"**{exam['name']}**{fau_badge} — {exam['program']} · {exam['students']} st · week {exam['week']}"):
            col1, col2, col3 = st.columns(3)
            col1.markdown(f"**Type:** {exam['type']}")
            col1.markdown(f"**Studenten:** {exam['students']}")
            col1.markdown(f"**Week:** {exam['week']}")
            col2.markdown(f"**Tijdvoorkeur:** {exam.get('time_pref','')}")
            col2.markdown(f"**Locatievoorkeur:** {exam.get('loc_pref','')}")
            col2.markdown(f"**Format:** {exam['format']}")
            col3.markdown(f"**Contactpersoon:** {exam['contact']}")
            col3.markdown(f"**Budget:** {exam.get('budget','')}")
            col3.markdown(f"**Status:** `{exam['status']}`")

            if exam.get("notes"):
                st.info(f"📌 {exam['notes']}")

            st.markdown(f"**Ingepland:** {slot_info}")

            if can_edit:
                bc1, bc2, bc3 = st.columns(3)
                if exam.get("slot_id") and bc1.button("📌 Bevestigen", key=f"bev_{exam['id']}"):
                    exam["status"] = "bevestigd"
                    st.rerun()
                if exam.get("slot_id") and bc2.button("↩ Verwijder uit slot", key=f"rm2_{exam['id']}"):
                    unassign_exam(exam)
                    st.rerun()
                if bc3.button("🗑 Verwijder examen", key=f"del_{exam['id']}"):
                    if exam.get("slot_id"):
                        unassign_exam(exam)
                    st.session_state.exams = [e for e in st.session_state.exams if e["id"] != exam["id"]]
                    st.rerun()

# ═══ TAB 2: Aanmelden ═══
with tab2:
    if not can_edit:
        st.error("Je hebt geen rechten om examens aan te melden."); st.stop()

    st.markdown("### Nieuw examen aanmelden")
    st.caption("Velden met * zijn verplicht")

    with st.form("nieuw_examen"):
        naam = st.text_input("Examennaam *")
        c1, c2 = st.columns(2)
        with c1:
            programma = st.selectbox("Programma *", [
                "Accountancy","PreMSc Accountancy","Accountancy (ENG)",
                "BScBA","FTMScM","PT MScM","MBA","EMBA",
                "MFR","IPM Accountancy","MSc Finance","Overig"
            ])
            exam_type = st.selectbox("Examtype *", ["C", "H", "C/H", "H1", "H2", "H3"])
            studenten = st.number_input("Geschat aantal studenten *", min_value=1, max_value=400, value=50)
            week = st.number_input("Voorkeur kalenderweek *", min_value=33, max_value=53, value=42)
        with c2:
            tijdvoorkeur = st.selectbox("Voorkeur tijdblok *", ["ochtend", "middag", "avond"])
            locatievoorkeur = st.selectbox("Locatievoorkeur *", [l["id"] for l in st.session_state.locations],
                                           format_func=lambda x: next((l["name"] for l in st.session_state.locations if l["id"] == x), x))
            formaat = st.selectbox("Format", ["Cirrus", "Papier"])
            fau = st.checkbox("FAU — Landelijk tentamen")

        c3, c4 = st.columns(2)
        with c3:
            contact = st.text_input("Contactpersoon *")
            budget = st.text_input("Budgetnummer")
        with c4:
            nieuwe_studenten = st.checkbox("Veel nieuwe studenten")
            bijlage = st.checkbox("Bijlage vereist")

        opmerkingen = st.text_area("Opmerkingen")

        # Capaciteitswaarschuwing live
        loc_obj = next((l for l in st.session_state.locations if l["id"] == locatievoorkeur), None)
        if loc_obj and studenten > loc_obj["capacity"]:
            st.warning(f"⚠ Het aantal studenten ({studenten}) overschrijdt de capaciteit van {loc_obj['name']} ({loc_obj['capacity']}). Overweeg opsplitsing naar programma.")

        if fau:
            st.info("🔴 FAU-examen: neemt een hele dag in de Breukelen sporthal in beslag. Geen andere examens mogelijk in Breukelen op die dag.")

        submitted = st.form_submit_button("Indienen bij planner →", type="primary")

        if submitted:
            if not naam or not contact:
                st.error("Vul naam en contactpersoon in.")
            else:
                new_id = f"e{len(st.session_state.exams) + 100}"
                st.session_state.exams.append({
                    "id": new_id,
                    "name": naam,
                    "program": programma,
                    "type": exam_type,
                    "fau": fau,
                    "students": studenten,
                    "week": week,
                    "time_pref": tijdvoorkeur,
                    "loc_pref": locatievoorkeur,
                    "format": formaat,
                    "contact": contact,
                    "budget": budget,
                    "notes": opmerkingen,
                    "status": "submitted",
                    "slot_id": None,
                })
                st.success(f"✅ Examen '{naam}' ingediend bij de planner.")
