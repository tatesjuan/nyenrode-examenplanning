import streamlit as st
from datetime import date
from utils.data import initialize_data, get_location, get_assigned_exams, slot_capacity_used, slot_hs_needed, slot_surv_needed

initialize_data()
NY_RED = "#6B1F3A"
st.markdown(f"<style>h1,h2,h3{{color:{NY_RED};}}</style>", unsafe_allow_html=True)

if "role" not in st.session_state:
    st.warning("Log eerst in."); st.stop()

role = st.session_state.role
is_planner = role in ["Planner", "Head of Operations ASC"]
is_surveillant = role == "Surveillant / Hoofdsurveillant"

st.title("👥 Surveillanten")

# ═══ PLANNER VIEW ═══
if is_planner:
    tab1, tab2, tab3 = st.tabs(["Beschikbaarheidsmatrix", "Toewijzing", "Beheer"])

    with tab1:
        st.markdown("### Beschikbaarheidsoverzicht")

        # Filters
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            maand_opties = {}
            for s in st.session_state.slots:
                d = date.fromisoformat(s["date"])
                key = (d.year, d.month)
                maand_opties[key] = d.strftime("%B %Y")
            if not maand_opties:
                st.info("Geen slots beschikbaar."); st.stop()
            gekozen_maand = fc1.selectbox("Maand", list(maand_opties.keys()),
                                           format_func=lambda k: maand_opties[k])
        with fc2:
            alleen_met_examens = st.checkbox("Alleen slots mét examens", value=True)
        with fc3:
            st.metric("Gereageerd", f"{sum(1 for a in st.session_state.availability if a['status'] != 'open')}/{len(st.session_state.availability)}")

        # Haal slots op voor gekozen maand
        y, m = gekozen_maand
        maand_slots = [
            s for s in st.session_state.slots
            if date.fromisoformat(s["date"]).year == y
            and date.fromisoformat(s["date"]).month == m
            and (not alleen_met_examens or s["assigned_exam_ids"])
        ]

        supervisors = st.session_state.supervisors
        avail = st.session_state.availability

        if not maand_slots:
            st.info("Geen (ingeplande) slots in deze maand."); 
        else:
            # Header
            sup_namen = [s["name"] for s in supervisors]
            header = ["Datum", "Tijdblok", "Locatie", "Examens", "Studenten", "HS nodig"] + sup_namen
            kolom_breedte = [1.2, 0.8, 1.5, 2.5, 0.6, 0.6] + [0.5] * len(supervisors)
            
            # Schaal kolombreedtes als er veel surveillanten zijn
            totaal_breedte = sum(kolom_breedte)
            cols_hdr = st.columns(kolom_breedte)
            for i, h in enumerate(header):
                cols_hdr[i].markdown(f"<div style='font-size:10px;font-weight:500;color:{NY_RED};'>{h}</div>", unsafe_allow_html=True)

            st.markdown("<hr style='margin:4px 0;'>", unsafe_allow_html=True)

            for slot in sorted(maand_slots, key=lambda s: (s["date"], s["time_block"])):
                d = date.fromisoformat(slot["date"])
                loc = get_location(slot["location_id"])
                tb = st.session_state.time_blocks.get(slot["time_block"], {})
                exams_in_slot = get_assigned_exams(slot)
                used = slot_capacity_used(slot)
                hs_n = slot_hs_needed(slot)
                hs_avail = st.session_state.hs_per_slot.get(slot["id"], 3)
                hs_kleur = "#27500A" if hs_n <= hs_avail else "#A32D2D"

                rij = st.columns(kolom_breedte)
                rij[0].markdown(f"<div style='font-size:11px;'>{d.strftime('%a %d %b')}</div>", unsafe_allow_html=True)
                rij[1].markdown(f"<div style='font-size:11px;'>{tb.get('label','')}</div>", unsafe_allow_html=True)
                rij[2].markdown(f"<div style='font-size:10px;color:#6B6B6B;'>{loc['name'] if loc else ''}</div>", unsafe_allow_html=True)
                namen = " | ".join(e["name"][:20] for e in exams_in_slot if e)
                rij[3].markdown(f"<div style='font-size:10px;'>{namen}</div>", unsafe_allow_html=True)
                rij[4].markdown(f"<div style='font-size:11px;text-align:center;'>{used}</div>", unsafe_allow_html=True)
                rij[5].markdown(f"<div style='font-size:11px;font-weight:500;text-align:center;color:{hs_kleur};'>{hs_n}</div>", unsafe_allow_html=True)

                for si, sup in enumerate(supervisors):
                    a = next((x for x in avail
                               if x["supervisor_id"] == sup["id"] and x["slot_id"] == slot["id"]), None)
                    status = a["status"] if a else "open"
                    icons = {"hs": "🟢", "surv": "🔵", "nee": "🔴", "open": "⬜"}
                    labels = {"hs": "H", "surv": "S", "nee": "✕", "open": "?"}
                    rij[6 + si].markdown(
                        f"<div style='text-align:center;font-size:12px;' title='{sup[\"name\"]}: {status}'>"
                        f"{icons.get(status,'⬜')}</div>",
                        unsafe_allow_html=True
                    )

            st.markdown("---")
            st.caption("🟢 H = Hoofdsurveillant &nbsp;|&nbsp; 🔵 S = Surveillant &nbsp;|&nbsp; 🔴 ✕ = Niet beschikbaar &nbsp;|&nbsp; ⬜ ? = Nog open")

    with tab2:
        st.markdown("### Toewijzing hoofdsurveillanten per slot")
        st.caption("Stel per slot in hoeveel hoofdsurveillanten beschikbaar zijn.")

        maand_opties2 = {}
        for s in st.session_state.slots:
            d = date.fromisoformat(s["date"])
            key = (d.year, d.month)
            maand_opties2[key] = d.strftime("%B %Y")

        gm2 = st.selectbox("Maand", list(maand_opties2.keys()),
                             format_func=lambda k: maand_opties2[k], key="tw_maand")
        y2, m2 = gm2
        slots_maand = [
            s for s in st.session_state.slots
            if date.fromisoformat(s["date"]).year == y2
            and date.fromisoformat(s["date"]).month == m2
            and s["assigned_exam_ids"]
        ]

        for slot in slots_maand:
            d = date.fromisoformat(slot["date"])
            loc = get_location(slot["location_id"])
            tb = st.session_state.time_blocks.get(slot["time_block"], {})
            hs_nodig = slot_hs_needed(slot)
            huidig = st.session_state.hs_per_slot.get(slot["id"], 3)

            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{d.strftime('%a %d %b')} · {tb.get('label','')}** · {loc['name'] if loc else ''} · HS nodig: {hs_nodig}")
            nieuw = c2.number_input("HS beschikbaar", min_value=0, max_value=10,
                                     value=huidig, key=f"hs_{slot['id']}", label_visibility="collapsed")
            if nieuw != huidig:
                st.session_state.hs_per_slot[slot["id"]] = nieuw

    with tab3:
        st.markdown("### Surveillantenbeheer")
        st.markdown("Overzicht van alle geregistreerde surveillanten.")
        for sup in st.session_state.supervisors:
            st.markdown(f"- **{sup['name']}** · {sup['rol']} · {sup['email']}")

        st.divider()
        st.markdown("### Beschikbaarheid uitvragen")
        st.markdown("Selecteer een maand en verstuur een uitnodiging aan alle surveillanten.")
        col1, col2 = st.columns(2)
        with col1:
            maand_sel = st.selectbox("Maand", ["Oktober 2026","November 2026","December 2026"])
        with col2:
            if st.button("📧 Uitnodiging versturen (simulatie)", type="primary"):
                st.success(f"Uitnodiging voor {maand_sel} verstuurd naar alle {len(st.session_state.supervisors)} surveillanten.")

# ═══ SURVEILLANT PORTAAL ═══
elif is_surveillant:
    st.markdown("### Mijn beschikbaarheid")
    naam = st.session_state.user_name

    # Zoek supervisor op naam
    sup = next((s for s in st.session_state.supervisors
                if naam.lower() in s["name"].lower()), None)

    if not sup:
        st.info(f"Geen surveillantprofiel gevonden voor '{naam}'. Neem contact op met de planner.")
        st.stop()

    st.markdown(f"**{sup['name']}** · Rol: {sup['rol']}")
    avail = st.session_state.availability

    # Toon beschikbare maanden
    maand_opties = {}
    for s in st.session_state.slots:
        if s["assigned_exam_ids"]:
            d = date.fromisoformat(s["date"])
            key = (d.year, d.month)
            maand_opties[key] = d.strftime("%B %Y")

    if not maand_opties:
        st.info("Er zijn nog geen examenslots gepland. Kom later terug."); st.stop()

    gekozen = st.selectbox("Maand", list(maand_opties.keys()), format_func=lambda k: maand_opties[k])
    y, m = gekozen

    slots_maand = [
        s for s in st.session_state.slots
        if date.fromisoformat(s["date"]).year == y
        and date.fromisoformat(s["date"]).month == m
        and s["assigned_exam_ids"]
    ]

    totaal = len(slots_maand)
    ingevuld = sum(1 for sl in slots_maand
                   for a in avail
                   if a["supervisor_id"] == sup["id"] and a["slot_id"] == sl["id"] and a["status"] != "open")

    c1, c2, c3 = st.columns(3)
    c1.metric("Totaal slots", totaal)
    c2.metric("Ingevuld", ingevuld)
    c3.metric("Nog open", totaal - ingevuld)

    st.divider()
    st.info("Geef per slot aan of je beschikbaar bent en in welke rol.")

    for slot in sorted(slots_maand, key=lambda s: (s["date"], s["time_block"])):
        d = date.fromisoformat(slot["date"])
        loc = get_location(slot["location_id"])
        tb = st.session_state.time_blocks.get(slot["time_block"], {})
        exams = get_assigned_exams(slot)
        used = slot_capacity_used(slot)
        hs_nodig = slot_hs_needed(slot)
        sv_nodig = slot_surv_needed(slot)

        a = next((x for x in avail
                  if x["supervisor_id"] == sup["id"] and x["slot_id"] == slot["id"]), None)
        huidige = a["status"] if a else "open"

        keuze_opties = ["hs", "surv", "nee"] if sup["rol"] == "beide" else (
            ["hs", "nee"] if sup["rol"] == "HS" else ["surv", "nee"]
        )
        keuze_labels = {"hs": "✅ Beschikbaar als Hoofdsurveillant",
                        "surv": "🔵 Beschikbaar als Surveillant",
                        "nee": "❌ Niet beschikbaar"}

        with st.container():
            col1, col2 = st.columns([3, 2])
            with col1:
                namen = ", ".join(e["name"][:25] for e in exams if e)
                st.markdown(f"**{d.strftime('%A %d %B')} · {tb.get('label','')}**")
                st.caption(f"{loc['name'] if loc else ''} · {namen}")
                st.caption(f"{used} studenten · {hs_nodig} HS benodigd · {sv_nodig} surv. benodigd")
            with col2:
                keuze = st.radio(
                    "Beschikbaarheid",
                    options=keuze_opties,
                    format_func=lambda x: keuze_labels.get(x, x),
                    index=keuze_opties.index(huidige) if huidige in keuze_opties else 0,
                    horizontal=False,
                    key=f"avail_{sup['id']}_{slot['id']}",
                    label_visibility="collapsed"
                )
                if keuze != huidige and a:
                    a["status"] = keuze
            st.divider()

    if st.button("💾 Opslaan", type="primary"):
        st.success("Beschikbaarheid opgeslagen. De planner kan dit nu inzien.")

else:
    st.info("Deze pagina is beschikbaar voor planners en surveillanten.")
