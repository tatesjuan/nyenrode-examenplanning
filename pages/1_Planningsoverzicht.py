import streamlit as st
from datetime import date, timedelta
import calendar
import math
from utils.data import initialize_data, get_location, get_slot, slot_capacity_used, slot_hs_needed, slot_surv_needed, get_assigned_exams
from utils.constraints import check_constraints, assign_exam_to_slot, unassign_exam, is_morning_blocked, is_fau_day_breukelen
from utils.algorithm import auto_plan

initialize_data()

NY_RED = "#6B1F3A"
st.markdown(f"<style>h1,h2,h3{{color:{NY_RED};}}</style>", unsafe_allow_html=True)

if "role" not in st.session_state:
    st.warning("Log eerst in via de hoofdpagina.")
    st.stop()

role = st.session_state.role
can_edit = role in ["Planner", "Head of Operations ASC"]
can_override = role == "Head of Operations ASC"

# ── State ──
if "sel_exam_id" not in st.session_state:
    st.session_state.sel_exam_id = None
if "view_month" not in st.session_state:
    st.session_state.view_month = (2026, 10)
if "assign_result" not in st.session_state:
    st.session_state.assign_result = None

# ── Header ──
st.title("📅 Planningsoverzicht")

# ── Toolbar ──
tb_col1, tb_col2, tb_col3, tb_col4 = st.columns([2, 2, 2, 3])
with tb_col1:
    year, month = st.session_state.view_month
    month_name = date(year, month, 1).strftime("%B %Y")
    c1, c2, c3 = st.columns([1, 3, 1])
    with c1:
        if st.button("◀"):
            m, y = month - 1, year
            if m == 0:
                m, y = 12, y - 1
            st.session_state.view_month = (y, m)
            st.rerun()
    with c2:
        st.markdown(f"<div style='text-align:center;font-weight:500;padding-top:6px;'>{month_name}</div>", unsafe_allow_html=True)
    with c3:
        if st.button("▶"):
            m, y = month + 1, year
            if m == 13:
                m, y = 1, y + 1
            st.session_state.view_month = (y, m)
            st.rerun()

with tb_col2:
    loc_filter = st.selectbox("Locatie", ["Alle"] + [l["name"] for l in st.session_state.locations], label_visibility="collapsed")

with tb_col3:
    if can_edit and st.button("⚡ Auto-plan", type="primary"):
        result = auto_plan()
        n_ok = len(result["ingepland"])
        n_fail = len(result["mislukt"])
        if n_fail == 0:
            st.success(f"Auto-plan geslaagd: {n_ok} examens ingepland.")
        else:
            st.warning(f"{n_ok} ingepland, {n_fail} niet geplaatst: {', '.join(r['naam'] for r in result['mislukt'])}")
        st.rerun()

with tb_col4:
    exams = st.session_state.exams
    gepland = len([e for e in exams if e.get("slot_id")])
    st.markdown(f"**{gepland}/{len(exams)}** ingepland &nbsp;|&nbsp; Bezetting gem. per dag")

st.divider()

# ── Main layout: inbox left + calendar right ──
left, right = st.columns([1, 4])

# ═══ INBOX (left) ═══
with left:
    ongepland = [e for e in st.session_state.exams if not e.get("slot_id")]
    st.markdown(f"### Te plannen ({len(ongepland)})")
    if not ongepland:
        st.success("Alle examens ingepland ✓")
    else:
        search = st.text_input("Zoeken", placeholder="Naam of programma…", label_visibility="collapsed")
        gefilterd = [e for e in ongepland if not search or
                     search.lower() in e["name"].lower() or
                     search.lower() in e["program"].lower()]

        for exam in sorted(gefilterd, key=lambda e: e["students"], reverse=True):
            is_sel = st.session_state.sel_exam_id == exam["id"]
            kleur = NY_RED if is_sel else "#E0DDD8"
            achtergrond = "#F5EEF1" if is_sel else "white"
            fau_badge = " 🔴 FAU" if exam.get("fau") else ""
            st.markdown(f"""
            <div style='border:1.5px solid {kleur};border-radius:6px;padding:8px 10px;
                        margin-bottom:6px;background:{achtergrond};cursor:pointer;'>
              <div style='font-size:12px;font-weight:500;color:#1A1A1A;'>{exam['name']}{fau_badge}</div>
              <div style='font-size:11px;color:#6B6B6B;'>{exam['program']} · {exam['type']}</div>
              <div style='font-size:10px;margin-top:3px;'>
                <span style='background:#F1EFE8;padding:1px 6px;border-radius:8px;'>
                  {exam['students']} st · wk {exam['week']}
                </span>
              </div>
            </div>
            """, unsafe_allow_html=True)
            if can_edit:
                if st.button(
                    "✓ Geselecteerd" if is_sel else "Selecteer",
                    key=f"sel_{exam['id']}",
                    type="primary" if is_sel else "secondary",
                    use_container_width=True
                ):
                    st.session_state.sel_exam_id = None if is_sel else exam["id"]
                    st.session_state.assign_result = None
                    st.rerun()

# ═══ KALENDER (right) ═══
with right:
    year, month = st.session_state.view_month
    first_day = date(year, month, 1)
    _, n_days = calendar.monthrange(year, month)
    last_day = date(year, month, n_days)

    dag_namen = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
    cols_header = st.columns(7)
    for i, d in enumerate(dag_namen):
        cols_header[i].markdown(
            f"<div style='text-align:center;font-size:12px;font-weight:500;"
            f"color:{'#9B9B9B' if i>=5 else NY_RED};'>{d}</div>",
            unsafe_allow_html=True
        )

    # Kalender grid
    start_weekday = first_day.weekday()  # 0=Mon
    dag = first_day - timedelta(days=start_weekday)

    while dag <= last_day or dag.weekday() != 0:
        if dag > last_day and dag.weekday() == 0:
            break
        week_cols = st.columns(7)
        for wi in range(7):
            cel_dag = dag + timedelta(days=wi)
            with week_cols[wi]:
                if cel_dag.month != month:
                    st.markdown("<div style='min-height:90px;'></div>", unsafe_allow_html=True)
                    continue

                d_iso = cel_dag.isoformat()
                is_weekend = cel_dag.weekday() >= 5
                is_fau = is_fau_day_breukelen(d_iso)

                # Achtergrond bepalen
                if is_fau:
                    bg = "#FCEBEB"; border = "1.5px solid #F09595"
                elif is_weekend:
                    bg = "#F8F6F4"; border = "0.5px solid #E0DDD8"
                else:
                    bg = "white"; border = "0.5px solid #E0DDD8"

                # Examens op deze dag ophalen (alle time_blocks, alle locaties)
                dag_slots = [s for s in st.session_state.slots
                             if s["date"] == d_iso and s["assigned_exam_ids"]]

                fau_tag = " <span style='font-size:7px;background:#FCEBEB;color:#A32D2D;padding:1px 3px;border-radius:2px;'>FAU</span>" if is_fau else ""
                dag_html = f"""
                <div style='min-height:90px;border:{border};border-radius:6px;
                            padding:4px 5px;background:{bg};'>
                  <div style='font-size:10px;font-weight:500;color:{"#9B9B9B" if is_weekend else "#1A1A1A"};
                              margin-bottom:3px;'>{cel_dag.day}{fau_tag}</div>
                """

                # Pills per time_block
                tb_colors = {
                    "ochtend":  ("#EAF3DE", "#27500A"),
                    "middag":   ("#E6F1FB", "#0C447C"),
                    "avond":    ("#F5EEF1", NY_RED),
                }
                blocked_morning = is_morning_blocked(d_iso) and not is_weekend

                for tb in ["ochtend", "middag", "avond"]:
                    tb_slots = [s for s in dag_slots if s["time_block"] == tb]
                    if blocked_morning and tb == "ochtend":
                        dag_html += f"<div style='font-size:8px;color:#D4A8B8;font-style:italic;'>ochtend geblokkeerd</div>"
                    elif tb_slots:
                        bg_c, txt_c = tb_colors.get(tb, ("#F1EFE8", "#444"))
                        for slot in tb_slots:
                            used = slot_capacity_used(slot)
                            cap = get_location(slot["location_id"])
                            cap_max = cap["capacity"] if cap else 350
                            pct = min(100, round(used / cap_max * 100))
                            bar_color = "#1D9E75" if pct < 65 else "#BA7517" if pct < 90 else "#A32D2D"
                            n_ex = len(slot["assigned_exam_ids"])
                            dag_html += f"""
                            <div style='background:{bg_c};border-radius:3px;padding:2px 4px;
                                        margin-bottom:2px;font-size:8px;color:{txt_c};'>
                              {n_ex} ex · {used}st
                              <div style='height:2px;background:#D3D1C7;border-radius:1px;margin-top:1px;'>
                                <div style='height:2px;width:{pct}%;background:{bar_color};border-radius:1px;'></div>
                              </div>
                            </div>"""
                dag_html += "</div>"
                st.markdown(dag_html, unsafe_allow_html=True)

                # Klikknop voor slot-beheer
                if can_edit and not is_weekend:
                    if st.button("＋", key=f"btn_{d_iso}", help=f"Beheer slots {cel_dag.strftime('%d %b')}", use_container_width=True):
                        st.session_state.open_dag = d_iso
                        st.rerun()

        dag += timedelta(days=7)

    # ── Slot-detail paneel ──
    if "open_dag" in st.session_state and st.session_state.open_dag:
        d_iso = st.session_state.open_dag
        d = date.fromisoformat(d_iso)
        st.divider()
        st.markdown(f"### 📋 Slots — {d.strftime('%A %d %B %Y')}")

        if st.button("✕ Sluiten"):
            st.session_state.open_dag = None
            st.rerun()

        sel_exam = None
        if st.session_state.sel_exam_id:
            sel_exam = next((e for e in st.session_state.exams
                             if e["id"] == st.session_state.sel_exam_id), None)

        if sel_exam:
            st.info(f"Geselecteerd examen: **{sel_exam['name']}** ({sel_exam['students']} studenten)")

        for tb_key, tb_info in st.session_state.time_blocks.items():
            st.markdown(f"**{tb_info['label']} · {tb_info['start']} – {tb_info['end']}**")
            if tb_key == "ochtend" and is_morning_blocked(d_iso):
                st.warning("Ochtend geblokkeerd (ma/di/vr buiten BScBA-examenweken)")
                if not can_override:
                    continue

            tb_cols = st.columns(len(st.session_state.locations))
            for li, loc in enumerate(st.session_state.locations):
                with tb_cols[li]:
                    slot = next((s for s in st.session_state.slots
                                 if s["date"] == d_iso and s["time_block"] == tb_key
                                 and s["location_id"] == loc["id"]), None)
                    if not slot:
                        continue

                    used = slot_capacity_used(slot)
                    pct = round(used / loc["capacity"] * 100) if loc["capacity"] else 0
                    hs_n = slot_hs_needed(slot)
                    sv_n = slot_surv_needed(slot)
                    hs_avail = st.session_state.hs_per_slot.get(slot["id"], 3)

                    kleur_cap = "#1D9E75" if pct < 65 else "#BA7517" if pct < 90 else "#A32D2D"
                    kleur_hs = "#1D9E75" if hs_n <= hs_avail else "#A32D2D"

                    st.markdown(f"""
                    <div style='border:0.5px solid #E0DDD8;border-radius:8px;padding:10px;background:white;'>
                      <div style='font-size:11px;font-weight:500;color:{NY_RED};margin-bottom:6px;'>{loc['name']}</div>
                      <div style='font-size:10px;color:#6B6B6B;'>Cap: <b style='color:{kleur_cap};'>{used}/{loc['capacity']}</b></div>
                      <div style='height:3px;background:#E0DDD8;border-radius:2px;margin:3px 0;'>
                        <div style='height:3px;width:{min(pct,100)}%;background:{kleur_cap};border-radius:2px;'></div>
                      </div>
                      <div style='font-size:10px;color:#6B6B6B;'>HS: <b style='color:{kleur_hs};'>{hs_n}/{hs_avail}</b> &nbsp;|&nbsp; Surv: {sv_n}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Ingeplande examens tonen
                    ass_exams = get_assigned_exams(slot)
                    for ae in ass_exams:
                        if not ae:
                            continue
                        c1, c2 = st.columns([4, 1])
                        c1.caption(f"📌 {ae['name']} ({ae['students']} st)")
                        if can_edit and c2.button("✕", key=f"rm_{ae['id']}_{slot['id']}"):
                            unassign_exam(ae)
                            st.rerun()

                    # Examen toewijzen
                    if can_edit and sel_exam:
                        override = can_override
                        result = check_constraints(sel_exam, slot, override=override)

                        if result["ok"] or (can_override and not result["ok"]):
                            btn_label = "Plan hier in" if result["ok"] else "⚠ Override: plan in"
                            btn_type = "primary" if result["ok"] else "secondary"
                            if st.button(btn_label, key=f"ass_{sel_exam['id']}_{slot['id']}", type=btn_type, use_container_width=True):
                                assign_exam_to_slot(sel_exam, slot)
                                st.session_state.sel_exam_id = None
                                st.session_state.assign_result = f"✅ {sel_exam['name']} ingepland in {loc['name']} · {tb_info['label']}"
                                st.rerun()

                            if result["fouten"]:
                                for f in result["fouten"]:
                                    st.caption(f"⚠ {f}")
                        else:
                            for f in result["fouten"]:
                                st.caption(f"🚫 {f}")

        if st.session_state.assign_result:
            st.success(st.session_state.assign_result)
            st.session_state.assign_result = None

# ── Legenda ──
st.divider()
st.markdown("""
<div style='display:flex;gap:20px;font-size:11px;color:#6B6B6B;flex-wrap:wrap;'>
  <span><span style='display:inline-block;width:10px;height:10px;background:#EAF3DE;border-radius:2px;'></span> Ochtendslot</span>
  <span><span style='display:inline-block;width:10px;height:10px;background:#E6F1FB;border-radius:2px;'></span> Middagslot</span>
  <span><span style='display:inline-block;width:10px;height:10px;background:#F5EEF1;border-radius:2px;'></span> Avondslot</span>
  <span><span style='display:inline-block;width:10px;height:10px;background:#FCEBEB;border:1px solid #F09595;border-radius:2px;'></span> FAU-dag</span>
  <span>Capaciteitsbalk: 🟢 &lt;65% · 🟡 65-90% · 🔴 &gt;90%</span>
</div>
""", unsafe_allow_html=True)
