import streamlit as st
import pandas as pd
import calendar
from datetime import date, datetime, timedelta
from database import (
    init_db, get_locaties, get_locatie,
    EXAMTYPES, LOCATIE_VOORKEUREN, bereken_verlenging,
    get_examens, get_examen, add_examen, update_examen, update_examen_status, delete_examen,
    get_ongeplande_examens, get_toewijzingen_voor_slot, get_toewijzing_voor_examen,
    get_or_create_slot, plan_examen, verwijder_toewijzing, bevestig_examen,
    slot_stats, get_surveillanten, add_surveillant,
    sla_beschikbaarheid_op, get_beschikbaarheid_matrix,
    get_beschikbaarheid_voor_surveillant, wijs_surveillant_toe,
    get_surv_toewijzingen_voor_slot, verwijder_surv_toewijzing,
    get_slots_for_month, get_slot, export_naar_csv,
    get_examenweeks, add_examenweek, delete_examenweek, is_examenweek,
    import_examens_uit_excel,
)
from constraints import check_alle_constraints, auto_plan

st.set_page_config(
    page_title="Examenplanning — Nyenrode",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

ROLLEN = {
    "Planner": {"kleur": "#6B1F3A", "icon": "📅"},
    "Head of Operations": {"kleur": "#4A1228", "icon": "🔑"},
    "Programmacoördinator": {"kleur": "#185FA5", "icon": "📝"},
    "Surveillant": {"kleur": "#1D9E75", "icon": "👁️"},
    "Examencommissie": {"kleur": "#6B6B6B", "icon": "📋"},
}
KAN_PLANNEN = {"Planner", "Head of Operations"}
KAN_OVERRULEN = {"Head of Operations"}
KAN_AANMELDEN = {"Planner", "Head of Operations", "Programmacoördinator"}
KAN_IMPORTEREN = {"Planner", "Head of Operations", "Programmacoördinator"}
# Coördinatoren importeren alleen examens: locatiekolommen in het bestand worden genegeerd.
KAN_LOCATIE_OVERSCHRIJVEN = {"Planner", "Head of Operations"}
KAN_BESCHIKBAAR = {"Surveillant"}
ALLEEN_LEZEN = {"Examencommissie"}
TIJDBLOK_LABELS = {"ochtend": "09:30–13:00", "middag": "14:00–17:30", "avond": "19:00–22:30"}
TIJDBLOK_KLEUR = {"ochtend": "#EAF3DE", "middag": "#E6F1FB", "avond": "#F5EEF1"}
MAANDEN_NL = ["","Januari","Februari","Maart","April","Mei","Juni",
               "Juli","Augustus","September","Oktober","November","December"]
DAG_NL = ["Ma","Di","Wo","Do","Vr","Za","Zo"]

VELDFOUT_CSS = """<style>
.veldfout{color:#A32D2D;font-size:12px;line-height:1.3;margin:-10px 0 8px 2px;}
</style>"""


def valideer_examen(naam, programma, geschat, duur) -> dict:
    """Eén foutmelding per veld. Lege dict betekent: alles geldig."""
    fouten = {}

    n = (naam or "").strip()
    if not n:
        fouten["naam"] = "Examennaam is verplicht."
    elif len(n) < 3:
        fouten["naam"] = "Examennaam moet minstens 3 tekens bevatten."
    elif len(n) > 120:
        fouten["naam"] = f"Examennaam is te lang ({len(n)} van maximaal 120 tekens)."

    if not (programma or "").strip():
        fouten["programma"] = "Programma is verplicht."

    if geschat is None or int(geschat) < 1:
        fouten["geschat_aantal"] = "Vul minimaal 1 student in."
    elif int(geschat) > 500:
        fouten["geschat_aantal"] = "Maximaal 500 studenten per examen."

    if duur is None:
        fouten["duur_minuten"] = "Duur is verplicht."
    elif int(duur) < 30 or int(duur) > 480:
        fouten["duur_minuten"] = "Duur moet tussen 30 en 480 minuten liggen."
    elif int(duur) % 30 != 0:
        fouten["duur_minuten"] = "Duur moet een veelvoud van 30 minuten zijn."

    return fouten


def _toon_veldfout(plek, fouten: dict, veld: str):
    """Rendert de foutmelding van één veld op zijn gereserveerde plek onder het invoerveld."""
    if veld in fouten:
        plek.markdown(f"<div class='veldfout'>⚠ {fouten[veld]}</div>", unsafe_allow_html=True)
    else:
        plek.empty()


def _keuze_index(opties: list, huidig, standaard=0):
    """Index van `huidig` in `opties`; valt terug op `standaard` als het er niet in staat."""
    return opties.index(huidig) if huidig in opties else standaard


def _opties_met_legacy(opties: list, huidig):
    """Houdt een onbekende (niet-gemigreerde) waarde zichtbaar i.p.v. hem stil te overschrijven."""
    if huidig and huidig not in opties:
        return [huidig] + opties
    return opties

for k, v in [("rol", None), ("gebruiker", ""), ("surveillant_id", None),
             ("kalender_jaar", date.today().year), ("kalender_maand", date.today().month),
             ("pagina", "Kalender")]:
    if k not in st.session_state:
        st.session_state[k] = v


# ── LOGIN ─────────────────────────────────────────────────
def toon_login():
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("""
        <div style='text-align:center;padding:40px 0 20px;'>
            <div style='font-size:48px;'>📅</div>
            <h1 style='color:#6B1F3A;font-size:26px;margin:8px 0 4px;'>Examenplanningstool</h1>
            <p style='color:#6B6B6B;font-size:13px;margin:0;'>Nyenrode Business Universiteit</p>
        </div>""", unsafe_allow_html=True)
        with st.form("login"):
            naam = st.text_input("Naam")
            rol = st.selectbox("Rol", list(ROLLEN.keys()))
            surv_keuze = None
            if rol == "Surveillant":
                survs = get_surveillanten()
                surv_keuze = st.selectbox("Kies je naam", [s["naam"] for s in survs])
            if st.form_submit_button("Inloggen", use_container_width=True):
                if not naam.strip():
                    st.error("Voer je naam in.")
                else:
                    st.session_state.rol = rol
                    st.session_state.gebruiker = naam.strip()
                    if rol == "Surveillant" and surv_keuze:
                        survs = get_surveillanten()
                        m = next((s for s in survs if s["naam"] == surv_keuze), None)
                        if m:
                            st.session_state.surveillant_id = m["id"]
                            st.session_state.gebruiker = m["naam"]
                    st.rerun()


# ── SIDEBAR ───────────────────────────────────────────────
def toon_sidebar():
    rol = st.session_state.rol
    info = ROLLEN[rol]
    with st.sidebar:
        st.markdown(f"""<div style='background:{info["kleur"]};padding:14px;border-radius:8px;margin-bottom:14px;'>
            <div style='font-size:20px;'>{info["icon"]}</div>
            <div style='color:white;font-weight:500;font-size:14px;margin-top:3px;'>{st.session_state.gebruiker}</div>
            <div style='color:rgba(255,255,255,.7);font-size:11px;'>{rol}</div>
        </div>""", unsafe_allow_html=True)

        paginas = []
        if rol not in KAN_BESCHIKBAAR:
            paginas += ["📅 Kalender", "📋 Examens"]
        if rol in KAN_AANMELDEN:
            paginas.append("➕ Aanmelden")
        if rol in KAN_PLANNEN:
            paginas += ["👁️ Surveillanten", "🗓️ Kalender beheer"]
        if rol in KAN_IMPORTEREN:
            paginas.append("⬇️ Import & Export")
        if rol in KAN_BESCHIKBAAR:
            paginas.append("✅ Beschikbaarheid")

        for p in paginas:
            label = p.split(" ", 1)[1]
            if st.button(p, use_container_width=True,
                         type="primary" if st.session_state.pagina == label else "secondary"):
                st.session_state.pagina = label
                st.rerun()

        st.divider()
        if st.button("🚪 Uitloggen", use_container_width=True):
            st.session_state.rol = None
            st.session_state.gebruiker = ""
            st.session_state.surveillant_id = None
            st.session_state.pagina = "Kalender"
            st.rerun()


# ── KALENDER ──────────────────────────────────────────────
def pagina_kalender():
    jaar = st.session_state.kalender_jaar
    maand = st.session_state.kalender_maand

    c1, c2, c3, _, c4 = st.columns([1, 3, 1, 2, 2])
    with c1:
        if st.button("◀"):
            st.session_state.kalender_maand = 12 if maand == 1 else maand - 1
            if maand == 1: st.session_state.kalender_jaar -= 1
            st.rerun()
    with c2:
        st.markdown(f"### {MAANDEN_NL[maand]} {jaar}")
    with c3:
        if st.button("▶"):
            st.session_state.kalender_maand = 1 if maand == 12 else maand + 1
            if maand == 12: st.session_state.kalender_jaar += 1
            st.rerun()
    with c4:
        if st.session_state.rol in KAN_PLANNEN:
            if st.button("⚡ Auto-plan", type="primary"):
                with st.spinner("Plannen..."):
                    res = auto_plan(st.session_state.gebruiker)
                if res["gepland"]:
                    st.success(f"✅ {res['gepland']} examens ingepland.")
                if res["niet_gepland"]:
                    st.warning("Niet ingepland: " + ", ".join(res["niet_gepland"]))
                st.rerun()

    slots_maand = get_slots_for_month(jaar, maand)
    slots_per_dag = {}
    for s in slots_maand:
        slots_per_dag.setdefault(s["datum"], []).append(s)
    tw_per_slot = {s["id"]: get_toewijzingen_voor_slot(s["id"]) for s in slots_maand}
    locs = {l["id"]: l for l in get_locaties()}
    cal_grid = calendar.monthcalendar(jaar, maand)
    vandaag = date.today()

    html = """<style>
    .kg{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;font-family:sans-serif;}
    .kh{text-align:center;font-size:10px;font-weight:500;color:#6B6B6B;padding:4px;background:#F5EEF1;border-radius:4px;}
    .kd{border:0.5px solid #E0DDD8;border-radius:6px;padding:5px;min-height:86px;background:white;font-size:10px;}
    .kd.wknd{background:#F8F6F4;}.kd.blok{background:#F9F3F5;border-color:#D4A8B8;}
    .kd.fau{background:#FCEBEB;border-color:#F09595;}.kd.heden{border:1.5px solid #6B1F3A;}
    .kdn{font-size:10px;font-weight:500;color:#1A1A1A;margin-bottom:3px;}
    .bt{font-size:7px;background:#F5EEF1;color:#6B1F3A;padding:1px 3px;border-radius:2px;margin-left:2px;}
    .ft{font-size:7px;background:#FCEBEB;color:#A32D2D;padding:1px 3px;border-radius:2px;margin-left:2px;}
    .sp{font-size:8px;border-radius:3px;padding:2px 4px;margin-bottom:1px;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;display:block;}
    .cw{height:2px;background:#E0DDD8;border-radius:1px;margin-top:2px;}
    .cb{height:2px;border-radius:1px;}
    .le{font-size:8px;color:#9B9B9B;font-style:italic;}
    </style><div class='kg'>"""

    for h in ["Ma","Di","Wo","Do","Vr","Za","Zo"]:
        html += f"<div class='kh'>{h}</div>"

    for week in cal_grid:
        for di, dag in enumerate(week):
            if dag == 0:
                html += "<div class='kd wknd'></div>"
                continue
            d = date(jaar, maand, dag)
            ds = d.isoformat()
            is_wknd = di >= 5
            is_vandaag = d == vandaag
            blokkade = di in [0,1,4] and not is_wknd and not is_examenweek(d)
            dag_slots = slots_per_dag.get(ds, [])
            heeft_fau = any(any(t.get("is_fau") for t in tw_per_slot.get(s["id"],[])) for s in dag_slots)

            kl = "kd"
            if is_vandaag: kl += " heden"
            elif heeft_fau: kl += " fau"
            elif blokkade: kl += " blok"
            elif is_wknd: kl += " wknd"

            html += f"<div class='{kl}'><div class='kdn'>{dag}"
            if blokkade and not is_wknd:
                html += "<span class='bt'>ocht. geblokkeerd</span>"
            if heeft_fau:
                html += "<span class='ft'>FAU</span>"
            html += "</div>"

            if dag_slots:
                for s in sorted(dag_slots, key=lambda x: ["ochtend","middag","avond"].index(x["tijdblok"])):
                    tw = tw_per_slot.get(s["id"], [])
                    if not tw: continue
                    loc = locs.get(s["locatie_id"], {})
                    cap = loc.get("capaciteit", 350)
                    bezet = sum(t.get("geschat_aantal") or 0 for t in tw)
                    pct = min(100, round(bezet/cap*100)) if cap else 0
                    bc = "#1D9E75" if pct < 65 else "#BA7517" if pct < 90 else "#A32D2D"
                    bg = TIJDBLOK_KLEUR.get(s["tijdblok"], "#EEE")
                    for t in tw[:2]:
                        html += f"<span class='sp' style='background:{bg};'>{t['naam'][:24]}</span>"
                    if len(tw) > 2:
                        html += f"<span class='le'>+{len(tw)-2} meer</span>"
                    html += f"<div class='cw'><div class='cb' style='width:{pct}%;background:{bc};'></div></div>"
            elif not is_wknd:
                html += "<div class='le'>beschikbaar</div>"
            html += "</div>"

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
    st.caption("🟩 Ochtend  🟦 Middag  🟪 Avond  🔴 FAU-dag  🟥 Ochtend geblokkeerd  |  balk = bezettingsgraad")
    st.divider()

    if st.session_state.rol in KAN_PLANNEN:
        toon_planformulier()


def toon_planformulier():
    st.subheader("Examen inplannen")
    alle = [e for e in get_examens() if e["status"] in ("ingediend","gepland","concept")]
    if not alle:
        st.info("Geen examens om in te plannen. Importeer of voeg examens toe.")
        return

    c1,c2,c3,c4 = st.columns(4)
    with c1:
        opties = {e["naam"]: e for e in alle}
        keuze = st.selectbox("Examen", list(opties.keys()))
        examen = opties[keuze]
        st.caption(f"{examen.get('geschat_aantal')} studenten · {examen.get('examtype','')}")
    with c2:
        datum = st.date_input("Datum", value=date.today(), min_value=date.today())
    with c3:
        tijdblok = st.selectbox("Tijdblok", list(TIJDBLOK_LABELS.keys()),
                                format_func=lambda x: f"{x.capitalize()} ({TIJDBLOK_LABELS[x]})")
    with c4:
        locs = get_locaties()
        loc_opties = {l["naam"]: l for l in locs}
        gl = st.selectbox("Locatie", list(loc_opties.keys()))
        locatie = loc_opties[gl]

    override = False
    if st.session_state.rol in KAN_OVERRULEN:
        override = st.checkbox("Override constraints (Head of Operations)")

    res = check_alle_constraints(examen, datum.isoformat(), tijdblok, locatie["id"], override=override)
    for b in res["blokkades"]: st.error(f"🚫 {b}")
    for w in res["waarschuwingen"]: st.warning(f"⚠️ {w}")
    if res["ok"] and not res["waarschuwingen"]: st.success("✅ Alle constraints OK.")

    override_reden = None
    if override and not res["ok"]:
        override_reden = st.text_input("Override-reden (verplicht)")

    halve_zaal = False
    if res.get("halve_zaal_suggestie"):
        halve_zaal = st.checkbox("Halve sporthal boeken", value=True)

    mag_overrulen = override and st.session_state.rol in KAN_OVERRULEN
    kan = res["ok"] or mag_overrulen
    if st.button("✅ Inplannen", type="primary", disabled=not kan):
        # De knopstatus komt uit een vorige rerun en mag niet de enige waarborg zijn.
        # Hercontroleer daarom vlak voor het wegschrijven.
        hercheck = check_alle_constraints(examen, datum.isoformat(), tijdblok,
                                          locatie["id"], override=override)
        if hercheck["blokkades"] and not mag_overrulen:
            for b in hercheck["blokkades"]:
                st.error(f"🚫 {b}")
            st.error("Inplannen geweigerd: er staan blokkades open.")
        elif hercheck["blokkades"] and not override_reden:
            st.error("Voer override-reden in.")
        else:
            slot = get_or_create_slot(datum.isoformat(), tijdblok, locatie["id"])
            plan_examen(examen["id"], slot["id"], st.session_state.gebruiker,
                        halve_zaal=halve_zaal, override_reden=override_reden if override else None)
            st.success(f"✅ '{examen['naam']}' ingepland.")
            st.rerun()


# ── EXAMENS ───────────────────────────────────────────────
def toon_bewerkformulier(e, tabkey=""):
    """
    Live bewerkformulier: geen st.form, zodat elke wijziging meteen een rerun geeft
    en de veldfouten direct onder het betreffende veld verschijnen.

    `tabkey` houdt de widgetkeys uniek: hetzelfde examen wordt in meerdere tabbladen
    gerenderd en gedeelde keys laten Streamlit crashen.
    """
    k = f"{tabkey}_{e['id']}"
    st.markdown("**✏️ Examen bewerken**")

    b1, b2 = st.columns(2)
    with b1:
        naam = st.text_input("Examennaam *", value=e.get("naam") or "", key=f"ed_naam_{k}")
        plek_naam = st.empty()
        programma = st.text_input("Programma / afdeling *", value=e.get("programma") or "", key=f"ed_prog_{k}")
        plek_prog = st.empty()
        type_opties = _opties_met_legacy(EXAMTYPES, e.get("examtype"))
        examtype = st.selectbox("Examtype *", type_opties,
                                index=_keuze_index(type_opties, e.get("examtype")),
                                key=f"ed_type_{k}")
        is_fau = st.checkbox("🚨 FAU — Landelijk tentamen", value=bool(e.get("is_fau")), key=f"ed_fau_{k}")

    with b2:
        geschat = st.number_input("Geschat aantal studenten *", min_value=1, max_value=500,
                                  value=int(e.get("geschat_aantal") or 1), key=f"ed_aantal_{k}")
        plek_aantal = st.empty()
        duur = st.number_input("Duur (minuten) *", min_value=30, max_value=480, step=30,
                               value=int(e.get("duur_minuten") or 120), key=f"ed_duur_{k}")
        plek_duur = st.empty()
        st.session_state[f"ed_verl_{k}"] = f"{bereken_verlenging(duur)} min"
        st.text_input("Verlenging (automatisch berekend)", disabled=True, key=f"ed_verl_{k}")
        loc_opties = _opties_met_legacy(LOCATIE_VOORKEUREN, e.get("locatie_voorkeur"))
        loc_pref = st.selectbox("Locatievoorkeur *", loc_opties,
                                index=_keuze_index(loc_opties, e.get("locatie_voorkeur")),
                                key=f"ed_loc_{k}")

    b3, b4 = st.columns(2)
    with b3:
        tijdblok = st.selectbox("Voorkeurstijdblok", list(TIJDBLOK_LABELS.keys()),
                                index=_keuze_index(list(TIJDBLOK_LABELS.keys()), e.get("voorkeur_tijdblok"), 1),
                                format_func=lambda x: f"{x.capitalize()} ({TIJDBLOK_LABELS[x]})",
                                key=f"ed_tb_{k}")
        contactpersoon = st.text_input("Contactpersoon", value=e.get("contactpersoon") or "", key=f"ed_cp_{k}")
    with b4:
        fmt = st.selectbox("Format", ["Cirrus", "Papier"],
                           index=_keuze_index(["Cirrus", "Papier"], e.get("format")),
                           key=f"ed_fmt_{k}")
        budgetnummer = st.text_input("Budgetnummer", value=e.get("budgetnummer") or "", key=f"ed_bud_{k}")

    opmerkingen = st.text_area("Opmerkingen", value=e.get("opmerkingen") or "", height=80, key=f"ed_opm_{k}")

    fouten = valideer_examen(naam, programma, geschat, duur)
    _toon_veldfout(plek_naam, fouten, "naam")
    _toon_veldfout(plek_prog, fouten, "programma")
    _toon_veldfout(plek_aantal, fouten, "geschat_aantal")
    _toon_veldfout(plek_duur, fouten, "duur_minuten")

    if loc_pref == "BRK+AMS":
        st.caption("ℹ️ BRK+AMS: dit examen vindt simultaan op beide campussen plaats.")

    if fouten:
        st.caption(f"🚫 Opslaan geblokkeerd: {len(fouten)} veld(en) met een fout.")

    if st.button("💾 Wijzigingen opslaan", key=f"ed_save_{k}", type="primary", disabled=bool(fouten)):
        update_examen(e["id"], {
            "naam": naam.strip(),
            "programma": programma.strip(),
            "examtype": examtype,
            "is_fau": int(is_fau),
            "voorkeur_tijdblok": tijdblok,
            "duur_minuten": int(duur),
            "verlenging_minuten": bereken_verlenging(duur),
            "geschat_aantal": int(geschat),
            "locatie_voorkeur": loc_pref,
            "format": fmt,
            "contactpersoon": contactpersoon.strip(),
            "budgetnummer": budgetnummer.strip(),
            "opmerkingen": opmerkingen.strip(),
        })
        st.success(f"✅ '{naam.strip()}' opgeslagen.")
        st.rerun()


def pagina_examens():
    st.header("📋 Examenlijst")
    tabs = st.tabs(["Alle","Concept","Ingediend","Gepland","Bevestigd"])
    status_map = [None,"concept","ingediend","gepland","bevestigd"]
    for i, tab in enumerate(tabs):
        with tab:
            examens = get_examens(status_map[i])
            if not examens:
                st.info("Geen examens.")
                continue
            # st.tabs rendert álle tabbladen in dezelfde run en een examen staat zowel
            # in "Alle" als in zijn statustab. Zonder tabprefix levert dat twee widgets
            # met dezelfde key op en crasht de pagina.
            tabkey = status_map[i] or "alle"
            for e in examens:
                with st.expander(f"{'🚨 ' if e.get('is_fau') else ''}{e['naam']} — {e.get('programma','')} | {e.get('geschat_aantal',0)} st. | {e['status'].upper()}"):
                    c1,c2,c3 = st.columns(3)
                    with c1:
                        st.write(f"**Type:** {e.get('examtype','')}  |  **FAU:** {'Ja 🚨' if e.get('is_fau') else 'Nee'}")
                        st.write(f"**Studenten:** {e.get('geschat_aantal')}  |  **Duur:** {e.get('duur_minuten')} min")
                        st.write(f"**Verlenging:** {e.get('verlenging_minuten', 0)} min")
                        st.write(f"**Format:** {e.get('format','')}  |  **Locatie pref.:** {e.get('locatie_voorkeur','')}")
                    with c2:
                        st.write(f"**Tijdblok pref.:** {(e.get('voorkeur_tijdblok') or '').capitalize()}")
                        st.write(f"**Contactpersoon:** {e.get('contactpersoon','')}")
                        st.write(f"**Budgetnummer:** {e.get('budgetnummer','')}")
                    with c3:
                        tw = get_toewijzing_voor_examen(e["id"])
                        if tw:
                            st.write(f"**Gepland:** {tw['datum']} · {tw['tijdblok'].capitalize()}")
                            st.write(f"**Locatie:** {tw.get('locatie_naam','')}")
                            if e["status"] == "gepland" and st.session_state.rol in KAN_PLANNEN:
                                if st.button("✅ Bevestigen", key=f"bev_{tabkey}_{e['id']}"):
                                    bevestig_examen(e["id"]); st.rerun()
                            if st.session_state.rol in KAN_PLANNEN:
                                if st.button("🗑️ Toewijzing verwijderen", key=f"dtw_{tabkey}_{e['id']}"):
                                    verwijder_toewijzing(e["id"]); st.rerun()
                        else:
                            st.write("**Nog niet ingepland**")
                        if st.session_state.rol in KAN_PLANNEN and e["status"] == "concept":
                            if st.button("👍 Goedkeuren", key=f"gk_{tabkey}_{e['id']}"):
                                update_examen_status(e["id"], "ingediend"); st.rerun()
                    if e.get("opmerkingen"):
                        st.caption(f"📝 {e['opmerkingen']}")

                    if st.session_state.rol in KAN_PLANNEN:
                        st.divider()
                        toon_bewerkformulier(e, tabkey)


# ── AANMELDEN ─────────────────────────────────────────────
AANMELD_KEYS = ["am_naam","am_prog","am_type","am_duur","am_aantal","am_fau",
                "am_tb","am_loc","am_fmt","am_nieuw","am_datum","am_cp","am_bud","am_opm"]


def _capaciteit_voorkeur(loc_pref: str) -> int:
    """Grootste bruikbare capaciteit voor een locatievoorkeur, afgeleid uit de locatietabel."""
    locs = get_locaties()
    brk = max((l["capaciteit"] for l in locs if l["campus"] == "Breukelen"), default=0)
    ams = max((l["capaciteit"] for l in locs if l["campus"] == "Amsterdam"), default=0)
    return {"BRK": brk, "AMS": ams, "BRK+AMS": brk + ams}.get(loc_pref, brk)


def pagina_aanmelden():
    st.header("➕ Examen aanmelden")

    ingediend = st.session_state.pop("am_succes", None)
    if ingediend:
        st.success(f"✅ '{ingediend}' ingediend.")

    # Bewust geen st.form: het verlengingsveld en de veldfouten moeten meelopen
    # met wat er getypt wordt, en een form voert pas bij submit opnieuw uit.
    st.subheader("Examengegevens")
    c1,c2 = st.columns(2)
    with c1:
        naam = st.text_input("Examennaam *", key="am_naam")
        plek_naam = st.empty()
        programma = st.text_input("Programma / afdeling *", key="am_prog")
        plek_prog = st.empty()
        examtype = st.selectbox("Examtype *", EXAMTYPES, key="am_type")
        duur = st.number_input("Duur (minuten) *", min_value=30, max_value=480, value=120, step=30, key="am_duur")
        plek_duur = st.empty()
        # Waarde via session_state zetten i.p.v. value=: een keyed widget geeft
        # session_state voorrang, waardoor value= na de eerste render genegeerd wordt.
        st.session_state["am_verl"] = f"{bereken_verlenging(duur)} min"
        st.text_input("Verlenging (automatisch berekend)", disabled=True, key="am_verl")
        geschat = st.number_input("Geschat aantal studenten *", min_value=1, max_value=500, value=50, key="am_aantal")
        plek_aantal = st.empty()
    with c2:
        is_fau = st.checkbox("🚨 FAU — Landelijk tentamen", key="am_fau")
        tijdblok = st.selectbox("Voorkeurstijdblok",["middag","ochtend","avond"],
                                format_func=lambda x: f"{x.capitalize()} ({TIJDBLOK_LABELS[x]})",
                                key="am_tb")
        loc_pref = st.selectbox("Locatievoorkeur *", LOCATIE_VOORKEUREN, key="am_loc")
        if loc_pref == "BRK+AMS":
            st.caption("ℹ️ Simultaan op beide campussen.")
        fmt = st.selectbox("Format", ["Cirrus","Papier"], key="am_fmt")
        nieuwe_studenten = st.checkbox("Veel nieuwe studenten?", key="am_nieuw")

    c3,c4 = st.columns(2)
    with c3:
        voorkeur_datum = st.date_input("Voorkeursdatum (optioneel)", value=None, key="am_datum")
        contactpersoon = st.text_input("Contactpersoon", key="am_cp")
    with c4:
        budgetnummer = st.text_input("Budgetnummer", key="am_bud")
        opmerkingen = st.text_area("Opmerkingen", height=80, key="am_opm")

    fouten = valideer_examen(naam, programma, geschat, duur)
    _toon_veldfout(plek_naam, fouten, "naam")
    _toon_veldfout(plek_prog, fouten, "programma")
    _toon_veldfout(plek_duur, fouten, "duur_minuten")
    _toon_veldfout(plek_aantal, fouten, "geschat_aantal")

    max_cap = _capaciteit_voorkeur(loc_pref)
    if geschat > max_cap:
        st.warning(f"⚠️ {geschat} studenten overschrijdt capaciteit {loc_pref} ({max_cap}). Overweeg splitsing.")

    if st.button("📨 Indienen bij planner", type="primary", use_container_width=True,
                 disabled=bool(fouten)):
        add_examen({
            "naam": naam.strip(), "programma": programma.strip(),
            "examtype": examtype, "is_fau": int(is_fau),
            "voorkeur_datum": voorkeur_datum.isoformat() if voorkeur_datum else None,
            "voorkeur_tijdblok": tijdblok, "duur_minuten": int(duur),
            "verlenging_minuten": bereken_verlenging(duur),
            "geschat_aantal": int(geschat), "locatie_voorkeur": loc_pref,
            "format": fmt, "nieuwe_studenten": int(nieuwe_studenten),
            "contactpersoon": contactpersoon.strip(), "budgetnummer": budgetnummer.strip(),
            "opmerkingen": opmerkingen.strip(), "status": "ingediend",
            "ingediend_door": st.session_state.gebruiker,
            "aangemaakt_op": datetime.now().isoformat(),
        })
        st.session_state["am_succes"] = naam.strip()
        for key in AANMELD_KEYS:
            st.session_state.pop(key, None)
        st.rerun()


# ── SURVEILLANTEN ─────────────────────────────────────────
def pagina_surveillanten():
    st.header("👁️ Surveillantenbeheer")
    jaar = st.session_state.kalender_jaar
    maand = st.session_state.kalender_maand
    slots = get_slots_for_month(jaar, maand)
    slot_ids = [s["id"] for s in slots]
    survs = get_surveillanten()

    tab1, tab2, tab3 = st.tabs(["Beschikbaarheidsmatrix", "Toewijzen per slot", "Surveillanten beheren"])

    with tab1:
        st.markdown(f"**{MAANDEN_NL[maand]} {jaar}**")
        slots_met = [s for s in slots if get_toewijzingen_voor_slot(s["id"])]
        if not slots_met:
            st.info("Geen slots met examens in deze maand.")
        else:
            matrix = get_beschikbaarheid_matrix([s["id"] for s in slots_met])
            locs = {l["id"]: l for l in get_locaties()}

            # Compacte tabel
            tabel_data = []
            for s in slots_met:
                tw = get_toewijzingen_voor_slot(s["id"])
                loc = locs.get(s["locatie_id"], {})
                rij = {
                    "Datum": s["datum"],
                    "Tijdblok": s["tijdblok"].capitalize(),
                    "Locatie": loc.get("naam","")[:16],
                    "Studenten": sum(t.get("geschat_aantal",0) for t in tw),
                    "Examens": len(tw),
                }
                for surv in survs:
                    b = matrix.get((surv["id"], s["id"]))
                    if b is None:
                        rij[surv["naam"][:6]] = "?"
                    elif not b.get("beschikbaar"):
                        rij[surv["naam"][:6]] = "✖"
                    elif b.get("rol_voorkeur") == "HS":
                        rij[surv["naam"][:6]] = "H"
                    else:
                        rij[surv["naam"][:6]] = "S"
                tabel_data.append(rij)

            if tabel_data:
                df = pd.DataFrame(tabel_data)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.caption("H = Hoofdsurveillant beschikbaar · S = Surveillant · ✖ = Niet beschikbaar · ? = Geen reactie")

    with tab2:
        slots_met = [s for s in slots if get_toewijzingen_voor_slot(s["id"])]
        if not slots_met:
            st.info("Geen slots met examens.")
        else:
            locs = {l["id"]: l for l in get_locaties()}
            slot_opties = {
                f"{s['datum']} · {s['tijdblok'].capitalize()} · {locs.get(s['locatie_id'],{}).get('naam','')}": s
                for s in slots_met
            }
            gl = st.selectbox("Kies slot", list(slot_opties.keys()))
            slot = slot_opties[gl]
            stats = slot_stats(slot["id"])

            c1,c2,c3 = st.columns(3)
            c1.metric("Examens", stats["n_examens"])
            c2.metric("HS nodig", stats["hs_nodig"])
            c3.metric("Surv. nodig", stats["surv_nodig"])

            st.write("**Ingeplande examens:**")
            for t in stats["toewijzingen"]:
                st.write(f"- {t['naam']} ({t.get('geschat_aantal',0)} st.)")

            st.write("**Toegewezen toezicht:**")
            toegewezen = get_surv_toewijzingen_voor_slot(slot["id"])
            reeds = {t["surveillant_id"] for t in toegewezen}
            for t in toegewezen:
                ca, cb = st.columns([4,1])
                ca.write(f"{t['naam']} — {t['rol']}")
                if cb.button("🗑️", key=f"dsurv_{t['surveillant_id']}_{slot['id']}"):
                    verwijder_surv_toewijzing(slot["id"], t["surveillant_id"])
                    st.rerun()

            st.write("**Nieuwe toewijzing:**")
            beschikbaar_survs = [s for s in survs if s["id"] not in reeds]
            if beschikbaar_survs:
                matrix = get_beschikbaarheid_matrix([slot["id"]])
                ca, cb, cc = st.columns([3,2,1])
                with ca:
                    def surv_label(s):
                        b = matrix.get((s["id"], slot["id"]))
                        if b is None: return f"{s['naam']} (geen reactie)"
                        if not b.get("beschikbaar"): return f"{s['naam']} ✖"
                        return f"{s['naam']} ✅ ({b.get('rol_voorkeur','')})"
                    keuze_naam = st.selectbox("Surveillant",
                        [s["naam"] for s in beschikbaar_survs],
                        format_func=lambda n: surv_label(next(s for s in beschikbaar_survs if s["naam"]==n)))
                with cb:
                    rol_keuze = st.selectbox("Rol", ["Surveillant","Hoofdsurveillant"])
                with cc:
                    st.write("")
                    if st.button("➕"):
                        m = next((s for s in survs if s["naam"]==keuze_naam), None)
                        if m:
                            wijs_surveillant_toe(slot["id"], m["id"], rol_keuze, st.session_state.gebruiker)
                            st.rerun()

    with tab3:
        for surv in survs:
            c1,c2,c3 = st.columns([4,2,2])
            c1.write(f"**{surv['naam']}** — {surv.get('email','')}")
            c2.write("HS + Surv." if surv.get("kan_hs") else "Surv.")
            c3.write("✅ Actief" if surv.get("actief") else "❌ Inactief")

        st.divider()
        with st.form("nieuw_surv", clear_on_submit=True):
            c1,c2,c3 = st.columns(3)
            n_naam = c1.text_input("Naam")
            n_email = c2.text_input("E-mail")
            n_hs = c3.checkbox("Kan als HS")
            if st.form_submit_button("➕ Toevoegen"):
                if n_naam.strip():
                    add_surveillant(n_naam.strip(), n_email.strip(), n_hs, True)
                    st.success(f"✅ {n_naam} toegevoegd.")
                    st.rerun()


# ── BESCHIKBAARHEID ───────────────────────────────────────
def pagina_beschikbaarheid():
    st.header("✅ Mijn beschikbaarheid")
    surv_id = st.session_state.surveillant_id
    if not surv_id:
        st.error("Geen koppeling gevonden. Log opnieuw in als surveillant.")
        return

    jaar = st.session_state.kalender_jaar
    maand = st.session_state.kalender_maand

    c1,c2,c3 = st.columns([1,3,1])
    with c1:
        if st.button("◀"):
            st.session_state.kalender_maand = 12 if maand==1 else maand-1
            if maand==1: st.session_state.kalender_jaar -= 1
            st.rerun()
    with c2:
        st.markdown(f"### {MAANDEN_NL[maand]} {jaar}")
    with c3:
        if st.button("▶"):
            st.session_state.kalender_maand = 1 if maand==12 else maand+1
            if maand==12: st.session_state.kalender_jaar += 1
            st.rerun()

    slots = get_slots_for_month(jaar, maand)
    slots_met = [s for s in slots if get_toewijzingen_voor_slot(s["id"])]
    if not slots_met:
        st.info(f"Geen examenslots in {MAANDEN_NL[maand]} {jaar}.")
        return

    slot_ids = [s["id"] for s in slots_met]
    bk = get_beschikbaarheid_voor_surveillant(surv_id, slot_ids)
    locs = {l["id"]: l for l in get_locaties()}

    c1,c2,c3 = st.columns(3)
    c1.metric("Slots", len(slots_met))
    c2.metric("Ingevuld", len(bk))
    c3.metric("Open", len(slots_met)-len(bk))

    st.divider()
    for slot in slots_met:
        tw = get_toewijzingen_voor_slot(slot["id"])
        loc = locs.get(slot["locatie_id"], {})
        totaal = sum(t.get("geschat_aantal",0) for t in tw)
        b = bk.get(slot["id"])
        d = date.fromisoformat(slot["datum"])

        with st.container():
            ca, cb, cc = st.columns([1,3,3])
            with ca:
                st.markdown(f"""
                <div style='text-align:center;background:#F5EEF1;border-radius:6px;padding:8px 4px;'>
                    <div style='font-size:10px;font-weight:500;color:#6B1F3A;'>{DAG_NL[d.weekday()]}</div>
                    <div style='font-size:20px;font-weight:500;'>{d.day}</div>
                    <div style='font-size:9px;color:#6B6B6B;'>{MAANDEN_NL[d.month][:3]}</div>
                </div>""", unsafe_allow_html=True)
            with cb:
                st.write(f"**{slot['start_tijd']} – {slot['eind_tijd']}**")
                st.caption(f"{loc.get('naam','')} · {totaal} studenten")
                for t in tw[:2]:
                    st.caption(f"• {t['naam']}")
            with cc:
                huidig = b.get("beschikbaar") if b else None
                rol = b.get("rol_voorkeur","surv") if b else "surv"
                hs_act = huidig and rol == "HS"
                sv_act = huidig and rol != "HS"
                no_act = huidig == False

                k1,k2,k3 = st.columns(3)
                if k1.button(f"{'✅ ' if hs_act else ''}HS", key=f"bhs_{slot['id']}", use_container_width=True):
                    sla_beschikbaarheid_op(surv_id, slot["id"], True, "HS")
                    st.rerun()
                if k2.button(f"{'✅ ' if sv_act else ''}Surv.", key=f"bsv_{slot['id']}", use_container_width=True):
                    sla_beschikbaarheid_op(surv_id, slot["id"], True, "surv")
                    st.rerun()
                if k3.button(f"{'✅ ' if no_act else ''}Niet", key=f"bno_{slot['id']}", use_container_width=True):
                    sla_beschikbaarheid_op(surv_id, slot["id"], False, "")
                    st.rerun()
        st.divider()


# ── KALENDER BEHEER ───────────────────────────────────────
def pagina_kalender_beheer():
    st.header("🗓️ Academische kalender")
    st.caption("Examenweeks bepalen wanneer ochtendslots in Breukelen beschikbaar zijn (ma/di/vr).")
    weeks = get_examenweeks()
    if weeks:
        df = pd.DataFrame(weeks)[["programma","week_start","week_eind","academisch_jaar"]]
        df.columns = ["Programma","Week start","Week einde","Jaar"]
        st.dataframe(df, use_container_width=True, hide_index=True)

        with st.expander("Verwijderen"):
            keuze = st.selectbox("Kies week", [f"{w['programma']} — {w['week_start']}" for w in weeks])
            if st.button("🗑️ Verwijderen"):
                idx = [f"{w['programma']} — {w['week_start']}" for w in weeks].index(keuze)
                delete_examenweek(weeks[idx]["id"]); st.rerun()

    st.divider()
    with st.form("nieuw_week", clear_on_submit=True):
        c1,c2,c3 = st.columns(3)
        prog = c1.selectbox("Programma", ["BScBA","FTMScM","PT MScM","Overig"])
        ws = c2.date_input("Start (maandag)")
        we = c3.date_input("Einde (vrijdag)")
        if st.form_submit_button("➕ Toevoegen"):
            add_examenweek(prog, ws.isoformat(), we.isoformat())
            st.success("✅ Toegevoegd.")
            st.rerun()


# ── IMPORT & EXPORT ───────────────────────────────────────
def pagina_export():
    rol = st.session_state.rol
    mag_overschrijven = rol in KAN_LOCATIE_OVERSCHRIJVEN

    st.header("⬇️ Import & Export" if mag_overschrijven else "⬇️ Examens importeren")

    if mag_overschrijven:
        st.subheader("Export naar Facilitor (Excel)")
        data = export_naar_csv()
        st.download_button("📥 Download planning als Excel", data=data,
            file_name=f"examenplanning_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary")
        st.divider()

    st.subheader("Import vanuit Excel")
    st.caption("Format: Chrono_tentamens_jaar kolommen (Dag, Datum, TENTAMEN, tijd, geschat aantal, Programma, ...)")
    if not mag_overschrijven:
        st.info(
            "ℹ️ Als programmacoördinator importeer je alleen de examens zelf. "
            "Een eventuele locatiekolom in het bestand wordt genegeerd — elk examen "
            "krijgt de standaardlocatie en de planner bepaalt de definitieve locatie."
        )

    up = st.file_uploader("Upload Excel", type=["xlsx","xls"])
    if up:
        try:
            df = pd.read_excel(up)
            st.write(f"{len(df)} rijen · {len(df.columns)} kolommen")
            st.dataframe(df.head(3), use_container_width=True)
            if st.button("✅ Importeren", type="primary"):
                n, fouten, genegeerd = import_examens_uit_excel(
                    df, alleen_examens=not mag_overschrijven
                )
                st.success(f"✅ {n} examens geïmporteerd.")
                if genegeerd:
                    st.warning(
                        f"⚠️ Bij {genegeerd} examen(s) is een locatie in het bestand genegeerd; "
                        f"de standaardlocatie is gebruikt."
                    )
                for f in fouten:
                    st.error(f)
                st.rerun()
        except Exception as ex:
            st.error(f"Fout: {ex}")

    if mag_overschrijven:
        st.divider()
        st.subheader("Demo-data")
        if st.button("🎲 Laad voorbeelddata"):
            laad_demo_data(); st.success("✅ Demo-data geladen."); st.rerun()


def laad_demo_data():
    demo = [
        ("Statistical Reasoning","Accountancy","Exam",0,"middag",120,10,"BRK"),
        ("Essentials of Auditing","Accountancy","Exam",0,"middag",210,20,"BRK"),
        ("Financial Auditing, Landelijk","Accountancy","Exam",1,"ochtend",480,286,"BRK"),
        ("Auditing Beginselen","Accountancy","Exam",0,"middag",210,220,"BRK"),
        ("FAT PreMaster","Accountancy","Exam/Retake",0,"middag",120,175,"BRK"),
        ("FAT Master","Accountancy","Exam",0,"middag",120,150,"BRK"),
        ("Ondernemingsrecht","Accountancy","Exam/Retake",0,"middag",180,150,"BRK"),
        ("Belastingrecht 1","Accountancy","Exam/Retake",0,"middag",180,220,"BRK"),
        ("Belastingrecht 2","Accountancy","Exam/Retake",0,"middag",180,80,"BRK"),
        ("BIV-Inleiding","Accountancy","Exam/Retake",0,"middag",180,60,"BRK"),
        ("Managerial Finance","MSc34","Exam",0,"middag",180,66,"AMS"),
        ("RBAI retake","MSc34","Retake",0,"ochtend",120,9,"AMS"),
        ("Leadership","MBA","Exam",0,"avond",120,45,"BRK"),
        ("Corporate Governance","Accountancy","Exam",0,"ochtend",120,100,"BRK"),
        ("Fraude & Witwassen","Accountancy","Exam/Retake",0,"middag",120,150,"BRK"),
    ]
    for naam, prog, etype, is_fau, tb, duur, st_n, loc in demo:
        add_examen({"naam":naam,"programma":prog,"examtype":etype,"is_fau":is_fau,
                    "voorkeur_tijdblok":tb,"duur_minuten":duur,
                    "verlenging_minuten":bereken_verlenging(duur),"geschat_aantal":st_n,
                    "locatie_voorkeur":loc,"format":"Cirrus","status":"ingediend",
                    "ingediend_door":"Demo","aangemaakt_op":datetime.now().isoformat()})


# ── RAPPORTAGE ────────────────────────────────────────────
def pagina_rapportage():
    st.header("📊 Planningsoverzicht")
    examens = get_examens()
    gepland = [e for e in examens if e["status"] in ("gepland","bevestigd")]
    ongepland = [e for e in examens if e["status"] == "ingediend"]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Totaal", len(examens))
    c2.metric("Gepland / bevestigd", len(gepland))
    c3.metric("Wachtend", len(ongepland))
    c4.metric("Concept", len([e for e in examens if e["status"]=="concept"]))

    if gepland:
        st.divider()
        rows = []
        for e in gepland:
            tw = get_toewijzing_voor_examen(e["id"])
            rows.append({"Tentamen":e["naam"],"Programma":e.get("programma",""),
                         "Type":e.get("examtype",""),"Studenten":e.get("geschat_aantal",0),
                         "Datum":tw["datum"] if tw else "","Tijdblok":tw["tijdblok"].capitalize() if tw else "",
                         "Locatie":tw.get("locatie_naam","") if tw else "","Status":e["status"].capitalize()})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── MAIN ──────────────────────────────────────────────────
def main():
    if not st.session_state.rol:
        toon_login()
        return

    st.markdown(VELDFOUT_CSS, unsafe_allow_html=True)
    toon_sidebar()
    pagina = st.session_state.pagina
    rol = st.session_state.rol

    if rol in ALLEEN_LEZEN:
        pagina_rapportage()
    elif rol in KAN_BESCHIKBAAR:
        pagina_beschikbaarheid()
    elif pagina == "Kalender":
        pagina_kalender()
    elif pagina == "Examens":
        pagina_examens()
    elif pagina == "Aanmelden" and rol in KAN_AANMELDEN:
        pagina_aanmelden()
    elif pagina == "Surveillanten" and rol in KAN_PLANNEN:
        pagina_surveillanten()
    elif pagina == "Kalender beheer" and rol in KAN_PLANNEN:
        pagina_kalender_beheer()
    elif pagina == "Import & Export" and rol in KAN_IMPORTEREN:
        pagina_export()
    else:
        pagina_kalender()

if __name__ == "__main__":
    main()
