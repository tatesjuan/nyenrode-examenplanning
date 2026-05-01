import streamlit as st
from datetime import date
from utils.data import initialize_data, get_location, slot_capacity_used, slot_hs_needed, slot_surv_needed, get_assigned_exams
from utils.export import export_facilitor, export_surveillanten_matrix

initialize_data()
NY_RED = "#6B1F3A"
st.markdown(f"<style>h1,h2,h3{{color:{NY_RED};}}</style>", unsafe_allow_html=True)

if "role" not in st.session_state:
    st.warning("Log eerst in."); st.stop()

role = st.session_state.role
st.title("📊 Rapporten & Export")

exams = st.session_state.exams
gepland = [e for e in exams if e.get("slot_id")]
ongepland = [e for e in exams if not e.get("slot_id")]

# ── Samenvatting ──
st.markdown("### Samenvatting")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Totaal examens", len(exams))
c2.metric("Ingepland", len(gepland))
c3.metric("Te plannen", len(ongepland))
c4.metric("FAU-examens", len([e for e in exams if e.get("fau")]))
c5.metric("Totaal studenten", sum(e["students"] for e in gepland))

st.divider()

tab1, tab2, tab3 = st.tabs(["Examenrooster", "Locatiebezetting", "Export"])

# ═══ TAB 1: Rooster ═══
with tab1:
    st.markdown("### Examenrooster — alle ingeplande examens")
    if not gepland:
        st.info("Nog geen examens ingepland.")
    else:
        # Groepeer per datum
        per_datum = {}
        for exam in gepland:
            slot = next((s for s in st.session_state.slots if s["id"] == exam["slot_id"]), None)
            if slot:
                d = slot["date"]
                per_datum.setdefault(d, []).append((exam, slot))

        for d_iso in sorted(per_datum.keys()):
            d = date.fromisoformat(d_iso)
            dag_exams = per_datum[d_iso]
            with st.expander(f"**{d.strftime('%A %d %B %Y')}** — {len(dag_exams)} examen(s)"):
                for exam, slot in sorted(dag_exams, key=lambda x: x[1]["time_block"]):
                    loc = get_location(slot["location_id"])
                    tb = st.session_state.time_blocks.get(slot["time_block"], {})
                    fau_tag = " 🔴 FAU" if exam.get("fau") else ""
                    c1, c2, c3, c4 = st.columns([3, 1.5, 1, 1])
                    c1.markdown(f"**{exam['name']}**{fau_tag}")
                    c2.caption(f"{tb.get('label','')} · {loc['name'] if loc else ''}")
                    c3.caption(f"{exam['students']} st.")
                    c4.caption(f"{exam['program']}")

                    if role in ["Planner", "Head of Operations ASC"]:
                        if exam["status"] == "gepland":
                            if st.button("✓ Bevestig", key=f"bev2_{exam['id']}", use_container_width=False):
                                exam["status"] = "bevestigd"
                                st.rerun()

# ═══ TAB 2: Locatiebezetting ═══
with tab2:
    st.markdown("### Bezetting per locatie en maand")

    maand_opties = {}
    for s in st.session_state.slots:
        if s["assigned_exam_ids"]:
            d = date.fromisoformat(s["date"])
            key = (d.year, d.month)
            maand_opties[key] = d.strftime("%B %Y")

    if not maand_opties:
        st.info("Nog geen examens ingepland.")
    else:
        gm = st.selectbox("Maand", list(maand_opties.keys()), format_func=lambda k: maand_opties[k])
        y, m = gm

        for loc in st.session_state.locations:
            slots_loc = [
                s for s in st.session_state.slots
                if s["location_id"] == loc["id"]
                and date.fromisoformat(s["date"]).year == y
                and date.fromisoformat(s["date"]).month == m
                and s["assigned_exam_ids"]
            ]
            if not slots_loc:
                continue

            totaal_exams = sum(len(s["assigned_exam_ids"]) for s in slots_loc)
            totaal_studenten = sum(slot_capacity_used(s) for s in slots_loc)
            gem_bezetting = round(totaal_studenten / (len(slots_loc) * loc["capacity"]) * 100) if slots_loc else 0

            with st.expander(f"**{loc['name']}** — {len(slots_loc)} slots · {totaal_exams} examens · gem. bezetting {gem_bezetting}%"):
                for slot in sorted(slots_loc, key=lambda s: s["date"]):
                    d = date.fromisoformat(slot["date"])
                    tb = st.session_state.time_blocks.get(slot["time_block"], {})
                    used = slot_capacity_used(slot)
                    pct = round(used / loc["capacity"] * 100)
                    hs_n = slot_hs_needed(slot)
                    sv_n = slot_surv_needed(slot)
                    bar_kleur = "#1D9E75" if pct < 65 else "#BA7517" if pct < 90 else "#A32D2D"

                    cc1, cc2, cc3 = st.columns([2, 2, 1])
                    cc1.markdown(f"{d.strftime('%a %d %b')} · {tb.get('label','')}")
                    cc2.markdown(f"""
                    <div style='height:8px;background:#E0DDD8;border-radius:4px;'>
                      <div style='height:8px;width:{min(pct,100)}%;background:{bar_kleur};border-radius:4px;'></div>
                    </div>
                    <span style='font-size:10px;'>{used}/{loc['capacity']} ({pct}%)</span>
                    """, unsafe_allow_html=True)
                    cc3.caption(f"HS:{hs_n} · Sv:{sv_n}")

# ═══ TAB 3: Export ═══
with tab3:
    st.markdown("### Facilitor-export")
    st.markdown("Download alle ingeplande examens in het Facilitor-formaat voor General Services.")

    gepland_n = len(gepland)
    st.info(f"{gepland_n} ingeplande examens beschikbaar voor export.")

    if gepland_n > 0:
        excel_data = export_facilitor()
        st.download_button(
            label="⬇ Download Facilitor-export (Excel)",
            data=excel_data,
            file_name=f"Facilitor_export_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

    st.divider()
    st.markdown("### Surveillantenrooster-export")
    st.markdown("Download de beschikbaarheidsmatrix voor archivering.")

    slots_met_exams = [s for s in st.session_state.slots if s["assigned_exam_ids"]]
    if slots_met_exams:
        surv_data = export_surveillanten_matrix()
        st.download_button(
            label="⬇ Download surveillantenmatrix (Excel)",
            data=surv_data,
            file_name=f"Surveillanten_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.divider()
    st.markdown("### Niet-ingeplande examens")
    if not ongepland:
        st.success("Alle examens zijn ingepland.")
    else:
        st.warning(f"{len(ongepland)} examens nog niet ingepland:")
        for e in sorted(ongepland, key=lambda x: x["students"], reverse=True):
            st.markdown(f"- **{e['name']}** · {e['program']} · {e['students']} st · week {e['week']}")
