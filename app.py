import streamlit as st
import pandas as pd
import calendar
import os
import hmac
from datetime import date, datetime, timedelta
from database import (
    init_db, get_locaties, get_locatie, add_locatie, update_locatie,
    EXAMTYPES, LOCATIE_VOORKEUREN, bereken_verlenging,
    get_examens, get_examen, add_examen, update_examen, update_examen_status, delete_examen,
    get_ongeplande_examens, get_toewijzingen_voor_slot, get_toewijzingen_voor_maand,
    get_toewijzing_voor_examen, get_toewijzingen_per_examen,
    get_or_create_slot, plan_examen, verwijder_toewijzing, bevestig_examen,
    open_gedeelde_conn, sluit_gedeelde_conn,
    slot_stats, get_surveillanten, add_surveillant,
    sla_beschikbaarheid_op, get_beschikbaarheid_matrix,
    get_beschikbaarheid_voor_surveillant, wijs_surveillant_toe,
    get_surv_toewijzingen_voor_slot, verwijder_surv_toewijzing,
    get_slots_for_month, get_slot, export_naar_csv,
    get_examenweeks, add_examenweek, delete_examenweek,
    import_examens_uit_excel,
    CONTRACT_TYPES, update_surveillant_contract, get_urenoverzicht,
    SURV_CAMPUSSEN, update_surveillant, campus_code,
    bepaal_academisch_jaar,
    add_periode_blokkade, get_periode_blokkades, delete_periode_blokkade,
    set_maandprofiel_handmatig, delete_maandprofiel_handmatig,
)
from constraints import check_alle_constraints, auto_plan
from toewijzing import (
    bepaal_maandprofiel, wijs_automatisch_toe, voorstel_voor_maand,
    genereer_tekort_mail,
)

st.set_page_config(
    page_title="Examenplanning — Nyenrode",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

@st.cache_resource
def _init_db_eenmalig():
    """
    Draait init_db() één keer per serverproces i.p.v. bij elke rerun. st.cache_resource
    bewaart het resultaat over reruns en sessies binnen hetzelfde proces. Bij een verse
    (Turso-)database bouwt de eerste run het schema volledig op; faalt die run, dan is er
    niets gecachet en probeert de volgende rerun het opnieuw.
    """
    init_db()
    return True

_init_db_eenmalig()

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

HEAD_OF_OPERATIONS = "Head of Operations"


def heeft_rol(rol, benodigd):
    """
    Centrale permissiecheck. Head of Operations is superuser en krijgt overal toegang;
    elke andere rol moet lid zijn van de benodigde permissieset. Gebruik dit voor
    FEATURE-poorten (KAN_PLANNEN, KAN_AANMELDEN, KAN_IMPORTEREN, KAN_OVERRULEN, ...),
    zodat een nieuwe afgeschermde functie automatisch óók voor Head of Operations opengaat.

    Let op: ALLEEN_LEZEN en KAN_BESCHIKBAAR worden in main() gebruikt als exclusieve
    rol-identiteit (welke dedicated weergave een rol krijgt), niet als poort — die blijven
    daarom bewust exacte set-membership, anders zou Head of Operations vastzitten in de
    rapportage- of beschikbaarheidsweergave.
    """
    if rol == HEAD_OF_OPERATIONS:
        return True
    return rol in benodigd


TIJDBLOK_LABELS = {"ochtend": "09:30–13:00", "middag": "14:00–17:30", "avond": "19:00–22:30"}
TIJDBLOK_KLEUR = {"ochtend": "#EAF3DE", "middag": "#E6F1FB", "avond": "#F5EEF1"}
MAANDEN_NL = ["","Januari","Februari","Maart","April","Mei","Juni",
               "Juli","Augustus","September","Oktober","November","December"]
DAG_NL = ["Ma","Di","Wo","Do","Vr","Za","Zo"]

VELDFOUT_CSS = """<style>
.veldfout{color:#A32D2D;font-size:12px;line-height:1.3;margin:-10px 0 8px 2px;}
</style>"""

MAX_INLOG_POGINGEN = 5   # brute-force rem: na dit aantal foute pogingen is de sessie geblokkeerd


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
             ("pagina", "Kalender"),
             ("toegang_verleend", False), ("inlog_pogingen", 0)]:
    if k not in st.session_state:
        st.session_state[k] = v


# ── TOEGANG (gedeeld wachtwoord) ──────────────────────────
def _app_wachtwoord():
    """
    Leest APP_WACHTWOORD defensief uit st.secrets en anders uit os.environ, net als
    de Turso-secrets. Geeft het wachtwoord terug, of None als er niets is ingesteld —
    dan is de app onbeveiligd, zodat lokaal ontwikkelen zonder secrets blijft werken.
    """
    pw = None
    try:
        pw = st.secrets["APP_WACHTWOORD"]
    except Exception:
        # KeyError (sleutel ontbreekt) of StreamlitSecretNotFoundError (geen bestand).
        pw = None
    pw = pw or os.environ.get("APP_WACHTWOORD")
    return pw or None


def toon_wachtwoordscherm(wachtwoord):
    """Toegangsscherm vóór het inlogscherm; zelfde huisstijl. Blokkeert na te veel pogingen."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("""
        <div style='text-align:center;padding:40px 0 20px;'>
            <div style='font-size:48px;'>📅</div>
            <h1 style='color:#6B1F3A;font-size:26px;margin:8px 0 4px;'>Examenplanningstool</h1>
            <p style='color:#6B6B6B;font-size:13px;margin:0;'>Nyenrode Business Universiteit</p>
        </div>""", unsafe_allow_html=True)

        if st.session_state.inlog_pogingen >= MAX_INLOG_POGINGEN:
            st.error("Te veel mislukte pogingen. Sluit dit tabblad en probeer het later opnieuw.")
            return

        with st.form("wachtwoord", clear_on_submit=True):
            invoer = st.text_input("Wachtwoord", type="password")
            if st.form_submit_button("Toegang", width="stretch"):
                # compare_digest voorkomt een timing-side-channel bij het vergelijken.
                if hmac.compare_digest(str(invoer), str(wachtwoord)):
                    st.session_state.toegang_verleend = True
                    st.session_state.inlog_pogingen = 0
                    st.rerun()
                else:
                    st.session_state.inlog_pogingen += 1
                    st.rerun()

        # Foutmelding na een rerun, zonder details over waarom het misging.
        if 0 < st.session_state.inlog_pogingen < MAX_INLOG_POGINGEN:
            resterend = MAX_INLOG_POGINGEN - st.session_state.inlog_pogingen
            st.error(f"Onjuist wachtwoord. Nog {resterend} poging(en).")


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
            if st.form_submit_button("Inloggen", width="stretch"):
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
        # Identity: een pure surveillant krijgt géén planningspagina's; Head of Operations
        # (niet in KAN_BESCHIKBAAR) valt hier vanzelf aan de goede kant.
        if rol not in KAN_BESCHIKBAAR:
            paginas += ["📅 Kalender", "📋 Examens"]
        if heeft_rol(rol, KAN_AANMELDEN):
            paginas.append("➕ Aanmelden")
        if heeft_rol(rol, KAN_PLANNEN):
            paginas += ["👁️ Surveillanten", "🏫 Zaalbeheer", "🗓️ Kalender beheer"]
        if heeft_rol(rol, KAN_IMPORTEREN):
            paginas.append("⬇️ Import & Export")
        if heeft_rol(rol, KAN_BESCHIKBAAR):
            paginas.append("✅ Beschikbaarheid")

        for p in paginas:
            label = p.split(" ", 1)[1]
            if st.button(p, width="stretch",
                         type="primary" if st.session_state.pagina == label else "secondary"):
                st.session_state.pagina = label
                st.rerun()

        st.divider()
        if st.button("🚪 Uitloggen", width="stretch"):
            # Terug naar naam/rol-scherm; toegang tot de app blijft behouden.
            st.session_state.rol = None
            st.session_state.gebruiker = ""
            st.session_state.surveillant_id = None
            st.session_state.pagina = "Kalender"
            st.rerun()

        # Alleen zinvol als er een wachtwoord is ingesteld: sessie volledig beëindigen
        # op een gedeelde computer (ook de toegang intrekken).
        if _app_wachtwoord():
            if st.button("🔒 Afsluiten", width="stretch"):
                st.session_state.toegang_verleend = False
                st.session_state.inlog_pogingen = 0
                st.session_state.rol = None
                st.session_state.gebruiker = ""
                st.session_state.surveillant_id = None
                st.session_state.pagina = "Kalender"
                st.rerun()


def toon_auto_toewijzing_maand(jaar, maand):
    """Maandbrede auto-toewijzing van surveillanten met een expliciete bevestigingsstap."""
    with st.expander("👁️ Auto-toewijzing surveillanten (hele maand)"):
        st.caption("Maakt een voorstel voor alle slots met examens deze maand. "
                   "Wegschrijven gebeurt pas na bevestiging; handmatig afwijken blijft mogelijk.")
        mk = f"maandvoorstel_{jaar}_{maand}"

        if st.button("🔍 Voorstel maken voor deze maand"):
            st.session_state[mk] = voorstel_voor_maand(jaar, maand, uitvoeren=False)
            st.rerun()

        res = st.session_state.get(mk)
        if res:
            if res["totaal_slots"] == 0:
                st.info("Geen slots met examens in deze maand.")
            else:
                m1, m2, m3 = st.columns(3)
                m1.metric("Slots", res["totaal_slots"])
                m2.metric("Volledig te vullen", res["volledig_gevuld"])
                m3.metric("Met tekort", res["met_tekort"])

                locs = {l["id"]: l for l in get_locaties()}
                for v in res["voorstellen"]:
                    lab = (f"{v['datum']} · {v['tijdblok'].capitalize()} · "
                           f"{locs.get(v['locatie_id'],{}).get('naam','')}")
                    vlag = " — 🚨 tekort" if v["tekorten"] else ""
                    with st.expander(lab + vlag):
                        toon_toewijzingsvoorstel(v)

                st.warning("Bevestig om het voorstel voor **alle** slots weg te schrijven.")
                if st.button("✅ Voorstel hele maand overnemen", type="primary"):
                    uitgevoerd = voorstel_voor_maand(jaar, maand, uitvoeren=True)
                    st.session_state.pop(mk, None)
                    st.success(f"✅ {uitgevoerd['totaal_slots']} slots verwerkt "
                               f"({uitgevoerd['met_tekort']} met resterend tekort).")
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
        if heeft_rol(st.session_state.rol, KAN_PLANNEN):
            if st.button("⚡ Auto-plan", type="primary"):
                with st.spinner("Plannen..."):
                    res = auto_plan(st.session_state.gebruiker)
                if res["gepland"]:
                    st.success(f"✅ {res['gepland']} examens ingepland.")
                if res["niet_gepland"]:
                    st.warning("Niet ingepland: " + ", ".join(res["niet_gepland"]))
                st.rerun()

    if heeft_rol(st.session_state.rol, KAN_PLANNEN):
        toon_auto_toewijzing_maand(jaar, maand)

    slots_maand = get_slots_for_month(jaar, maand)
    slots_per_dag = {}
    for s in slots_maand:
        slots_per_dag.setdefault(s["datum"], []).append(s)
    tw_per_slot = get_toewijzingen_voor_maand(jaar, maand)  # één query i.p.v. per slot
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
            # Breukelen jaarrond geblokkeerd: ma/di ochtend + vrijdag hele dag (geen
            # examenweek-uitzondering meer). Alleen met override (Head of Operations).
            hele_dag_blok = di == 4 and not is_wknd
            blokkade = di in [0, 1, 4] and not is_wknd
            dag_slots = slots_per_dag.get(ds, [])
            heeft_fau = any(any(t.get("is_fau") for t in tw_per_slot.get(s["id"],[])) for s in dag_slots)

            kl = "kd"
            if is_vandaag: kl += " heden"
            elif heeft_fau: kl += " fau"
            elif blokkade: kl += " blok"
            elif is_wknd: kl += " wknd"

            html += f"<div class='{kl}'><div class='kdn'>{dag}"
            if blokkade and not is_wknd:
                tekst = "hele dag geblokkeerd" if hele_dag_blok else "ocht. geblokkeerd"
                html += f"<span class='bt'>{tekst}</span>"
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
    st.caption("🟩 Ochtend  🟦 Middag  🟪 Avond  🔴 FAU-dag  🟥 Breukelen geblokkeerd (ma/di ochtend, vr hele dag)  |  balk = bezettingsgraad")
    st.divider()

    if heeft_rol(st.session_state.rol, KAN_PLANNEN):
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
        # Alleen actieve zalen zijn inzetbaar; inactieve horen niet in de keuzelijst.
        locs = get_locaties(alleen_actief=True)
        if not locs:
            st.error("Geen actieve zalen. Activeer er minstens één via Zaalbeheer.")
            return
        loc_opties = {l["naam"]: l for l in locs}
        gl = st.selectbox("Locatie", list(loc_opties.keys()))
        locatie = loc_opties[gl]

    override = False
    if heeft_rol(st.session_state.rol, KAN_OVERRULEN):
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

    mag_overrulen = override and heeft_rol(st.session_state.rol, KAN_OVERRULEN)
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
    tw_per_examen = get_toewijzingen_per_examen()  # één query i.p.v. per examen
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
                        tw = tw_per_examen.get(e["id"])
                        if tw:
                            st.write(f"**Gepland:** {tw['datum']} · {tw['tijdblok'].capitalize()}")
                            st.write(f"**Locatie:** {tw.get('locatie_naam','')}")
                            if e["status"] == "gepland" and heeft_rol(st.session_state.rol, KAN_PLANNEN):
                                if st.button("✅ Bevestigen", key=f"bev_{tabkey}_{e['id']}"):
                                    with st.spinner("Bevestigen…"):
                                        bevestig_examen(e["id"])
                                    st.toast(f"'{e['naam']}' bevestigd.", icon="✅")
                                    st.rerun()
                            if heeft_rol(st.session_state.rol, KAN_PLANNEN):
                                if st.button("🗑️ Toewijzing verwijderen", key=f"dtw_{tabkey}_{e['id']}"):
                                    verwijder_toewijzing(e["id"]); st.rerun()
                        else:
                            st.write("**Nog niet ingepland**")
                        if heeft_rol(st.session_state.rol, KAN_PLANNEN) and e["status"] == "concept":
                            if st.button("👍 Goedkeuren", key=f"gk_{tabkey}_{e['id']}"):
                                update_examen_status(e["id"], "ingediend"); st.rerun()
                    if e.get("opmerkingen"):
                        st.caption(f"📝 {e['opmerkingen']}")

                    if heeft_rol(st.session_state.rol, KAN_PLANNEN):
                        st.divider()
                        toon_bewerkformulier(e, tabkey)


# ── AANMELDEN ─────────────────────────────────────────────
AANMELD_KEYS = ["am_naam","am_prog","am_type","am_duur","am_aantal","am_fau",
                "am_tb","am_loc","am_fmt","am_nieuw","am_datum","am_cp","am_bud","am_opm"]


def _capaciteit_voorkeur(loc_pref: str) -> int:
    """
    Grootste bruikbare capaciteit voor een locatievoorkeur, afgeleid uit de
    locatietabel. Alleen actieve zalen tellen mee: een inactieve zaal is niet
    inzetbaar en mag de capaciteitsverwachting dus niet ophogen.
    """
    locs = get_locaties(alleen_actief=True)
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
    if max_cap == 0:
        st.warning(f"⚠️ Er zijn geen actieve zalen voor {loc_pref}. Neem contact op met de planner.")
    elif geschat > max_cap:
        st.warning(f"⚠️ {geschat} studenten overschrijdt capaciteit {loc_pref} ({max_cap}). Overweeg splitsing.")

    if st.button("📨 Indienen bij planner", type="primary", width="stretch",
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


def toon_toewijzingsvoorstel(voorstel):
    """Rendert één slot-voorstel: voorgestelde personen, tekorten, blokkades en mailtekst."""
    if voorstel.get("toewijzingen"):
        rijen = []
        for t in voorstel["toewijzingen"]:
            if t["contract_type"] == "FTE":
                saldo = (f"achterstand {t['achterstand']:+.1f} u" if t["achterstand"] is not None
                         else "")
            else:
                saldo = f"{t['gedraaide_uren']:.1f} u dit jaar"
            rijen.append({
                "Surveillant": t["naam"],
                "Rol": t["rol"],
                "Contract": t["contract_type"],
                "Score": t["score"],
                "Saldo": saldo,
                "Blokkade": "🚫 ja" if t["geblokkeerd"] else "",
            })
        st.dataframe(pd.DataFrame(rijen), width="stretch", hide_index=True)

    for w in voorstel.get("waarschuwingen", []):
        st.warning(f"⚠️ {w}")

    mail = genereer_tekort_mail(voorstel)
    if mail:
        st.error("🚨 Tekort of geblokkeerde inzet — meld dit bij het toetsbureau.")
        st.caption("Kant-en-klare mailtekst (kopieer met de knop rechtsboven het blok):")
        st.code(mail, language="text")


# ── SURVEILLANTEN ─────────────────────────────────────────
def pagina_surveillanten():
    st.header("👁️ Surveillantenbeheer")
    jaar = st.session_state.kalender_jaar
    maand = st.session_state.kalender_maand
    slots = get_slots_for_month(jaar, maand)
    survs = get_surveillanten()

    # st.radio i.p.v. st.tabs: alleen de gekozen sectie rendert, dus alleen díe sectie
    # doet database-aanroepen (st.tabs rendert alle vijf tegelijk en query't dus alles).
    SECTIES = ["Beschikbaarheidsmatrix", "Toewijzen per slot", "Surveillanten beheren",
               "Urenoverzicht", "Maandprofiel"]
    sectie = st.radio("Weergave", SECTIES, horizontal=True,
                      label_visibility="collapsed", key="surv_sectie")
    st.divider()

    if sectie == "Beschikbaarheidsmatrix":
        st.markdown(f"**{MAANDEN_NL[maand]} {jaar}**")
        tw_per_slot = get_toewijzingen_voor_maand(jaar, maand)  # één query i.p.v. per slot
        slots_met = [s for s in slots if tw_per_slot.get(s["id"])]
        if not slots_met:
            st.info("Geen slots met examens in deze maand.")
        else:
            matrix = get_beschikbaarheid_matrix([s["id"] for s in slots_met])
            locs = {l["id"]: l for l in get_locaties()}

            # Compacte tabel
            tabel_data = []
            for s in slots_met:
                tw = tw_per_slot.get(s["id"], [])
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
                st.dataframe(df, width="stretch", hide_index=True)
                st.caption("H = Hoofdsurveillant beschikbaar · S = Surveillant · ✖ = Niet beschikbaar · ? = Geen reactie")

    elif sectie == "Toewijzen per slot":
        tw_per_slot = get_toewijzingen_voor_maand(jaar, maand)
        slots_met = [s for s in slots if tw_per_slot.get(s["id"])]
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
            slot_campus = campus_code(locs.get(slot["locatie_id"], {}).get("campus"))

            c1,c2,c3 = st.columns(3)
            c1.metric("Examens", stats["n_examens"])
            c2.metric("HS nodig", stats["hs_nodig"])
            c3.metric("Surv. nodig", stats["surv_nodig"])
            st.caption(f"📍 Campus **{slot_campus}** — de automatische toewijzing kiest alleen "
                       f"surveillanten van deze campus. Handmatig toewijzen kan campusoverstijgend.")

            st.write("**Ingeplande examens:**")
            for t in stats["toewijzingen"]:
                st.write(f"- {t['naam']} ({t.get('geschat_aantal',0)} st.)")

            st.write("**Toegewezen toezicht:**")
            toegewezen = get_surv_toewijzingen_voor_slot(slot["id"])
            reeds = {t["surveillant_id"] for t in toegewezen}
            for t in toegewezen:
                ca, cb = st.columns([4,1])
                andere = t.get("campus") and t["campus"] != slot_campus
                markering = "  ⚠️ andere campus" if andere else ""
                ca.write(f"{t['naam']} ({t.get('campus','?')}) — {t['rol']}{markering}")
                if cb.button("🗑️", key=f"dsurv_{t['surveillant_id']}_{slot['id']}"):
                    verwijder_surv_toewijzing(slot["id"], t["surveillant_id"])
                    st.rerun()

            # ── Automatisch voorstel ──────────────────────────
            st.divider()
            st.write("**🤖 Automatische toewijzing**")
            st.caption("Het voorstel is adviserend; je kunt altijd handmatig afwijken.")
            vk = f"voorstel_{slot['id']}"
            av1, av2 = st.columns(2)
            if av1.button("🤖 Automatisch voorstel", key=f"gen_{slot['id']}"):
                st.session_state[vk] = wijs_automatisch_toe(slot["id"], uitvoeren=False)
                st.rerun()
            voorstel = st.session_state.get(vk)
            if voorstel and voorstel.get("slot_id") == slot["id"]:
                toon_toewijzingsvoorstel(voorstel)
                if not voorstel["toewijzingen"]:
                    st.info("Geen beschikbare kandidaten om voor te stellen.")
                elif av2.button("✅ Voorstel overnemen", key=f"ov_{slot['id']}", type="primary"):
                    wijs_automatisch_toe(slot["id"], uitvoeren=True)
                    st.session_state.pop(vk, None)
                    st.success("✅ Voorstel overgenomen.")
                    st.rerun()

            st.divider()
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

    elif sectie == "Surveillanten beheren":
        st.caption("Klap een surveillant uit om contract, campus of status aan te passen. "
                   "Inactieve surveillanten tellen niet mee in de automatische toewijzing en "
                   "verschijnen niet in keuzelijsten; hun historie en urenlog blijven behouden.")
        # Alle surveillanten (ook inactieve), zodat de planner iemand kan reactiveren.
        for surv in get_surveillanten(alleen_actief=False):
            hs_txt = "HS + Surv." if surv.get("kan_hs") else "Surv."
            ct = surv.get("contract_type") or "nul-uren"
            ct_txt = f"{ct} · {surv.get('fte_factor') or 0} FTE" if ct == "FTE" else ct
            camp = surv.get("campus") or "BRK"
            status = "✅ Actief" if surv.get("actief") else "❌ Inactief"
            with st.expander(f"{surv['naam']} ({camp}) — {hs_txt} · {ct_txt} · {status}"):
                st.write(f"**E-mail:** {surv.get('email','')}")
                st.write(f"**Jaardoel:** {round(surv.get('jaardoel_uren') or 0, 1)} uur")

                sk = surv["id"]
                # Campus + actief (beheergegevens).
                bc1, bc2, bc3 = st.columns([2, 2, 2])
                with bc1:
                    campus = st.selectbox("Campus", SURV_CAMPUSSEN,
                                          index=_keuze_index(SURV_CAMPUSSEN, camp),
                                          key=f"camp_{sk}")
                with bc2:
                    actief = st.checkbox("Actief", value=bool(surv.get("actief")), key=f"act_{sk}")
                with bc3:
                    st.write("")
                    if st.button("💾 Gegevens opslaan", key=f"beheersave_{sk}"):
                        update_surveillant(sk, campus=campus, actief=actief)
                        st.toast(f"{surv['naam']} bijgewerkt.", icon="✅")
                        st.rerun()

                st.divider()
                # Contract (los opslaan).
                cc1, cc2 = st.columns(2)
                with cc1:
                    ctype = st.selectbox("Contracttype", CONTRACT_TYPES,
                                         index=_keuze_index(CONTRACT_TYPES, ct),
                                         key=f"ct_{sk}")
                with cc2:
                    factor = st.number_input("FTE-factor", min_value=0.0, max_value=1.0, step=0.01,
                                             value=float(surv.get("fte_factor") or 0),
                                             disabled=(ctype != "FTE"), key=f"fte_{sk}")
                voorbeeld = round((factor if ctype == "FTE" else 0) * 2080, 1)
                st.caption(f"Jaardoel bij deze instelling: **{voorbeeld} uur** "
                           f"(1 FTE = 2080 uur/jaar).")
                if st.button("💾 Contract opslaan", key=f"ctsave_{sk}", type="primary"):
                    update_surveillant_contract(sk, ctype, factor if ctype == "FTE" else 0)
                    st.toast(f"Contract van {surv['naam']} opgeslagen.", icon="✅")
                    st.rerun()

        st.divider()
        with st.form("nieuw_surv", clear_on_submit=True):
            c1,c2,c3,c4 = st.columns(4)
            n_naam = c1.text_input("Naam")
            n_email = c2.text_input("E-mail")
            n_campus = c3.selectbox("Campus", SURV_CAMPUSSEN)
            n_hs = c4.checkbox("Kan als HS")
            if st.form_submit_button("➕ Toevoegen"):
                if n_naam.strip():
                    add_surveillant(n_naam.strip(), n_email.strip(), n_hs, True, campus=n_campus)
                    st.toast(f"{n_naam} toegevoegd.", icon="✅")
                    st.rerun()

    elif sectie == "Urenoverzicht":
        st.markdown("**Gedraaide uren per academisch jaar**")
        st.caption("Academisch jaar loopt van 1 augustus t/m 31 juli. Eén sessie telt als "
                   f"5,5 uur. FTE-medewerkers staan bovenaan; een tekort staat in het rood.")

        # Academische jaren afgeleid van vandaag, ruim genomen zodat er altijd keuze is.
        hj = bepaal_academisch_jaar(date.today())
        start = int(hj.split("-")[0])
        jaar_opties = [f"{y}-{y+1}" for y in range(start + 1, start - 3, -1)]
        gekozen_jaar = st.selectbox("Academisch jaar", jaar_opties,
                                    index=jaar_opties.index(hj) if hj in jaar_opties else 0)

        overzicht = get_urenoverzicht(gekozen_jaar)
        # FTE bovenaan, daarbinnen grootste tekort eerst; nul-uren daaronder op naam.
        overzicht.sort(key=lambda r: (r["contract_type"] != "FTE", r["verschil"], r["naam"]))

        if not overzicht:
            st.info("Nog geen surveillanten.")
        else:
            rijen = []
            for r in overzicht:
                is_tekort = r["contract_type"] == "FTE" and r["verschil"] < 0
                rijen.append({
                    "Surveillant": r["naam"],
                    "Contract": (f"FTE {r['fte_factor']}" if r["contract_type"] == "FTE"
                                 else "nul-uren"),
                    "Jaardoel (u)": r["jaardoel_uren"],
                    "Gedraaid (u)": r["gedraaide_uren"],
                    "Verschil (u)": r["verschil"],
                    "Sessies": r["sessies"],
                    "": "🔴 tekort" if is_tekort else "",
                })
            df = pd.DataFrame(rijen)

            def _markeer_tekort(row):
                rood = row[""] == "🔴 tekort"
                return ['background-color: #FCEBEB' if rood else '' for _ in row]

            st.dataframe(df.style.apply(_markeer_tekort, axis=1),
                         width="stretch", hide_index=True)

            fte_tekort = [r for r in overzicht
                          if r["contract_type"] == "FTE" and r["verschil"] < 0]
            if fte_tekort:
                namen = ", ".join(f"{r['naam']} ({r['verschil']} u)" for r in fte_tekort)
                st.warning(f"⚠️ FTE-medewerkers onder hun jaardoel: {namen}")

    elif sectie == "Maandprofiel":
        st.markdown("**Maandprofiel per academisch jaar**")
        st.caption("Piek/normaal/dal wordt automatisch bepaald uit het aantal studenten per "
                   "maand. Je kunt een maand handmatig overschrijven; dat gaat vóór de "
                   "automatische bepaling en weegt mee in de FTE-spreiding.")

        hj = bepaal_academisch_jaar(date.today())
        start = int(hj.split("-")[0])
        jaar_opties = [f"{y}-{y+1}" for y in range(start + 1, start - 3, -1)]
        mp_jaar = st.selectbox("Academisch jaar", jaar_opties,
                               index=jaar_opties.index(hj) if hj in jaar_opties else 0,
                               key="mp_jaar")

        profiel = bepaal_maandprofiel(mp_jaar)
        if not profiel:
            st.info("Nog geen geplande examens in dit academisch jaar.")
        else:
            KLEUR = {"piek": "#FCEBEB", "normaal": "#EAF3DE", "dal": "#E6F1FB"}
            for maand in sorted(profiel.keys()):
                info = profiel[maand]
                mc1, mc2, mc3, mc4 = st.columns([2, 2, 3, 2])
                with mc1:
                    st.markdown(
                        f"<div style='background:{KLEUR.get(info['categorie'],'#EEE')};"
                        f"border-radius:6px;padding:6px 10px;font-weight:500;'>{maand} — "
                        f"{info['categorie'].upper()}</div>", unsafe_allow_html=True)
                mc2.caption(f"{info['studenten']} studenten · factor {info['factor']}"
                            + ("  ✋ handmatig" if info["handmatig"] else ""))
                with mc3:
                    keuze = st.selectbox(
                        "Overschrijf", ["— automatisch —", "piek", "normaal", "dal"],
                        index=(["piek", "normaal", "dal"].index(info["categorie"]) + 1
                               if info["handmatig"] else 0),
                        key=f"mp_sel_{maand}", label_visibility="collapsed")
                with mc4:
                    if st.button("Opslaan", key=f"mp_save_{maand}"):
                        if keuze == "— automatisch —":
                            delete_maandprofiel_handmatig(mp_jaar, maand)
                        else:
                            set_maandprofiel_handmatig(mp_jaar, maand, keuze)
                        st.rerun()


# ── BESCHIKBAARHEID ───────────────────────────────────────
def pagina_beschikbaarheid():
    surv_id = st.session_state.surveillant_id
    namens_ander = False
    if not surv_id:
        # Planner / Head of Operations mag de beschikbaarheid van een surveillant beheren
        # zonder zelf als surveillant ingelogd te zijn: laat kiezen wie.
        if heeft_rol(st.session_state.rol, KAN_PLANNEN):
            # Alleen actieve surveillanten; label toont de campus, bijv. "Adele (AMS)".
            survs_kandidaat = get_surveillanten(alleen_actief=True)
            if not survs_kandidaat:
                st.header("✅ Beschikbaarheid")
                st.info("Er zijn nog geen actieve surveillanten.")
                return
            keuze = st.selectbox(
                "Beheer beschikbaarheid van", [s["id"] for s in survs_kandidaat],
                format_func=lambda sid: next(
                    f"{s['naam']} ({s.get('campus','?')})" for s in survs_kandidaat if s["id"] == sid),
                key="besch_surv_keuze")
            surv_id = keuze
            namens_ander = True
        else:
            st.header("✅ Mijn beschikbaarheid")
            st.error("Geen koppeling gevonden. Log opnieuw in als surveillant.")
            return

    surv = next((s for s in get_surveillanten(alleen_actief=False) if s["id"] == surv_id), None)
    kan_hs = bool(surv and surv.get("kan_hs"))

    if namens_ander:
        st.header(f"✅ Beschikbaarheid — {surv['naam'] if surv else ''}")
        st.caption("Je bekijkt en bewerkt de beschikbaarheid namens deze surveillant.")
    else:
        st.header("✅ Mijn beschikbaarheid")

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
    tw_per_slot = get_toewijzingen_voor_maand(jaar, maand)  # één query voor de hele maand
    slots_met = [s for s in slots if tw_per_slot.get(s["id"])]
    if not slots_met:
        st.info(f"Geen examenslots in {MAANDEN_NL[maand]} {jaar}.")
        toon_periode_blokkades(surv_id)
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
        tw = tw_per_slot.get(slot["id"], [])
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
                rol_v = b.get("rol_voorkeur", "surv") if b else "surv"
                hs_act = huidig and rol_v == "HS"
                sv_act = huidig and rol_v != "HS"
                no_act = huidig == False

                # Twee knoppen: HS-surveillanten geven zich als HS op (nooit als S),
                # gewone surveillanten als S. De opslag mapt op het bestaande datamodel
                # (rol_voorkeur "HS"/"surv"); de HS-als-S regel in toewijzing.py bepaalt
                # los daarvan of een HS'er alsnog als S wordt ingezet.
                k1, k2 = st.columns(2)
                if kan_hs:
                    if k1.button(f"{'✅ ' if hs_act else ''}HS", key=f"bhs_{slot['id']}",
                                 width="stretch"):
                        sla_beschikbaarheid_op(surv_id, slot["id"], True, "HS")
                        st.rerun()
                else:
                    if k1.button(f"{'✅ ' if sv_act else ''}Surv.", key=f"bsv_{slot['id']}",
                                 width="stretch"):
                        sla_beschikbaarheid_op(surv_id, slot["id"], True, "surv")
                        st.rerun()
                if k2.button(f"{'✅ ' if no_act else ''}Niet", key=f"bno_{slot['id']}",
                             width="stretch"):
                    sla_beschikbaarheid_op(surv_id, slot["id"], False, "")
                    st.rerun()
        st.divider()

    toon_periode_blokkades(surv_id)


def toon_periode_blokkades(surv_id):
    """Sectie waarin een surveillant periodes van niet-beschikbaarheid beheert."""
    st.subheader("🚫 Periodes waarin ik niet beschikbaar ben")
    st.caption(
        "Dit is **adviserend**: de planner houdt hier rekening mee, maar kan er in "
        "uitzonderingsgevallen van afwijken. Geef bijvoorbeeld vakanties of langere "
        "afwezigheid door."
    )

    blokkades = get_periode_blokkades(surv_id)
    if blokkades:
        for bl in blokkades:
            cA, cB = st.columns([5, 1])
            reden = f" — {bl['reden']}" if bl.get("reden") else ""
            cA.write(f"📅 **{bl['datum_van']}** t/m **{bl['datum_tot']}**{reden}")
            if cB.button("🗑️", key=f"delblok_{bl['id']}"):
                delete_periode_blokkade(bl["id"])
                st.rerun()
    else:
        st.caption("Nog geen periodes opgegeven.")

    with st.form("nieuwe_periode_blokkade", clear_on_submit=True):
        st.markdown("**Nieuwe periode toevoegen**")
        p1, p2 = st.columns(2)
        with p1:
            van = st.date_input("Van", value=date.today())
        with p2:
            tot = st.date_input("Tot en met", value=date.today())
        reden = st.text_input("Reden (optioneel)", placeholder="bijv. vakantie, studie, ...")
        if st.form_submit_button("➕ Periode toevoegen", type="primary"):
            if tot < van:
                st.error("De einddatum ligt vóór de begindatum.")
            else:
                add_periode_blokkade(surv_id, van.isoformat(), tot.isoformat(), reden.strip())
                st.success("✅ Periode opgeslagen.")
                st.rerun()


# ── ZAALBEHEER ────────────────────────────────────────────
def valideer_zaal(naam, min_cap, max_cap) -> dict:
    """Eén foutmelding per veld. Lege dict betekent: alles geldig."""
    fouten = {}
    n = (naam or "").strip()
    if not n:
        fouten["naam"] = "Zaalnaam is verplicht."
    elif len(n) > 80:
        fouten["naam"] = f"Zaalnaam is te lang ({len(n)} van maximaal 80 tekens)."
    if int(max_cap) < 1:
        fouten["capaciteit"] = "Maximale capaciteit moet minstens 1 zijn."
    if int(min_cap) < 0:
        fouten["min_capaciteit"] = "Minimale capaciteit kan niet negatief zijn."
    elif int(min_cap) > int(max_cap):
        fouten["min_capaciteit"] = (
            f"Minimum ({min_cap}) mag niet groter zijn dan het maximum ({max_cap})."
        )
    return fouten


def pagina_zaalbeheer():
    st.header("🏫 Zaalbeheer")
    st.caption("Beheer de zalen, hun capaciteitsgrenzen en of ze inzetbaar zijn.")

    locaties = get_locaties()
    actief_n = len([l for l in locaties if l.get("actief")])
    c1, c2, c3 = st.columns(3)
    c1.metric("Zalen totaal", len(locaties))
    c2.metric("Actief", actief_n)
    c3.metric("Inactief", len(locaties) - actief_n)
    st.divider()

    for l in locaties:
        k = l["id"]
        vlag = "" if l.get("actief") else " — 🚫 inactief"
        titel = (f"{l['naam']} · {l['campus']} · {l.get('min_capaciteit', 0)}–{l['capaciteit']} plekken · "
                 f"max {l.get('max_examens_per_slot', 2)} examens/slot{vlag}")
        with st.expander(titel):
            a1, a2, a3, a4 = st.columns([3, 2, 2, 2])
            with a1:
                naam = st.text_input("Naam", value=l["naam"], key=f"zb_naam_{k}")
                plek_naam = st.empty()
                campus = st.selectbox("Campus", ["Breukelen", "Amsterdam"],
                                      index=_keuze_index(["Breukelen", "Amsterdam"], l["campus"]),
                                      key=f"zb_campus_{k}")
            with a2:
                min_cap = st.number_input("Min. capaciteit", min_value=0, max_value=1000,
                                          value=int(l.get("min_capaciteit") or 0), key=f"zb_min_{k}")
                plek_min = st.empty()
            with a3:
                max_cap = st.number_input("Max. capaciteit", min_value=1, max_value=1000,
                                          value=int(l["capaciteit"]), key=f"zb_max_{k}")
                plek_max = st.empty()
            with a4:
                max_ex = st.number_input("Max. examens/slot", min_value=1, max_value=20,
                                         value=int(l.get("max_examens_per_slot") or 2), key=f"zb_maxex_{k}")

            actief = st.checkbox("Actief (inzetbaar voor planning)",
                                 value=bool(l.get("actief")), key=f"zb_act_{k}")

            fouten = valideer_zaal(naam, min_cap, max_cap)
            _toon_veldfout(plek_naam, fouten, "naam")
            _toon_veldfout(plek_min, fouten, "min_capaciteit")
            _toon_veldfout(plek_max, fouten, "capaciteit")

            if st.button("💾 Opslaan", key=f"zb_save_{k}", type="primary", disabled=bool(fouten)):
                update_locatie(k, naam.strip(), campus, int(min_cap), int(max_cap), int(actief),
                               max_examens_per_slot=int(max_ex))
                st.success(f"✅ '{naam.strip()}' opgeslagen.")
                st.rerun()

    st.divider()
    st.subheader("➕ Nieuwe zaal toevoegen")

    n1, n2, n3, n4 = st.columns([3, 2, 2, 2])
    with n1:
        nz_naam = st.text_input("Naam", key="zb_nieuw_naam")
        plek_nz_naam = st.empty()
        nz_campus = st.selectbox("Campus", ["Breukelen", "Amsterdam"], key="zb_nieuw_campus")
    with n2:
        nz_min = st.number_input("Min. capaciteit", min_value=0, max_value=1000, value=0,
                                 key="zb_nieuw_min")
        plek_nz_min = st.empty()
    with n3:
        nz_max = st.number_input("Max. capaciteit", min_value=1, max_value=1000, value=30,
                                 key="zb_nieuw_max")
        plek_nz_max = st.empty()
    with n4:
        nz_maxex = st.number_input("Max. examens/slot", min_value=1, max_value=20, value=2,
                                   key="zb_nieuw_maxex")
    nz_actief = st.checkbox("Actief", value=True, key="zb_nieuw_act")

    nz_fouten = valideer_zaal(nz_naam, nz_min, nz_max)
    _toon_veldfout(plek_nz_naam, nz_fouten, "naam")
    _toon_veldfout(plek_nz_min, nz_fouten, "min_capaciteit")
    _toon_veldfout(plek_nz_max, nz_fouten, "capaciteit")

    bestaande_namen = {l["naam"].strip().lower() for l in locaties}
    if nz_naam.strip() and nz_naam.strip().lower() in bestaande_namen:
        st.warning(f"⚠️ Er bestaat al een zaal met de naam '{nz_naam.strip()}'.")

    if st.button("➕ Zaal toevoegen", type="primary", disabled=bool(nz_fouten)):
        if nz_naam.strip().lower() in bestaande_namen:
            st.error("Er bestaat al een zaal met deze naam. Kies een andere naam.")
        else:
            add_locatie(nz_naam.strip(), nz_campus, int(nz_min), int(nz_max), int(nz_actief),
                        max_examens_per_slot=int(nz_maxex))
            st.success(f"✅ Zaal '{nz_naam.strip()}' toegevoegd.")
            for key in ["zb_nieuw_naam", "zb_nieuw_campus", "zb_nieuw_min",
                        "zb_nieuw_max", "zb_nieuw_maxex", "zb_nieuw_act"]:
                st.session_state.pop(key, None)
            st.rerun()


# ── KALENDER BEHEER ───────────────────────────────────────
def pagina_kalender_beheer():
    st.header("🗓️ Academische kalender")
    st.caption("Examenweeks bepalen wanneer ochtendslots in Breukelen beschikbaar zijn (ma/di/vr).")
    weeks = get_examenweeks()
    if weeks:
        df = pd.DataFrame(weeks)[["programma","week_start","week_eind","academisch_jaar"]]
        df.columns = ["Programma","Week start","Week einde","Jaar"]
        st.dataframe(df, width="stretch", hide_index=True)

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
    mag_overschrijven = heeft_rol(rol, KAN_LOCATIE_OVERSCHRIJVEN)

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
    # Resultaat van een vorige import; blijft staan na de rerun die het importeren afsluit.
    imp = st.session_state.pop("import_resultaat", None)
    if imp:
        st.success(f"✅ {imp['n']} examens geïmporteerd.")
        if imp.get("genegeerd"):
            st.warning(
                f"⚠️ Bij {imp['genegeerd']} examen(s) is een locatie in het bestand genegeerd; "
                f"de standaardlocatie is gebruikt."
            )
        for f in imp.get("fouten", []):
            st.error(f)
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
            st.dataframe(df.head(3), width="stretch")
            if st.button("✅ Importeren", type="primary"):
                with st.spinner("Bezig met importeren…"):
                    n, fouten, genegeerd = import_examens_uit_excel(
                        df, alleen_examens=not mag_overschrijven
                    )
                st.session_state["import_resultaat"] = {
                    "n": n, "fouten": list(fouten), "genegeerd": genegeerd,
                }
                st.toast(f"{n} examens geïmporteerd.", icon="✅")
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
        tw_per_examen = get_toewijzingen_per_examen()  # één query i.p.v. per examen
        rows = []
        for e in gepland:
            tw = tw_per_examen.get(e["id"])
            rows.append({"Tentamen":e["naam"],"Programma":e.get("programma",""),
                         "Type":e.get("examtype",""),"Studenten":e.get("geschat_aantal",0),
                         "Datum":tw["datum"] if tw else "","Tijdblok":tw["tijdblok"].capitalize() if tw else "",
                         "Locatie":tw.get("locatie_naam","") if tw else "","Status":e["status"].capitalize()})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ── MAIN ──────────────────────────────────────────────────
def main():
    # Eén gedeelde databaseverbinding voor de hele rerun: alle get_conn()-aanroepen
    # hergebruiken die i.p.v. per query een nieuwe (Turso-)verbinding te openen.
    open_gedeelde_conn()
    try:
        _main_router()
    finally:
        sluit_gedeelde_conn()


def _main_router():
    # Toegangspoort: is er een wachtwoord ingesteld, dan eerst het toegangsscherm.
    # Geen wachtwoord ingesteld (lokaal ontwikkelen) → direct door naar het inlogscherm.
    wachtwoord = _app_wachtwoord()
    if wachtwoord and not st.session_state.toegang_verleend:
        toon_wachtwoordscherm(wachtwoord)
        return

    if not st.session_state.rol:
        toon_login()
        return

    st.markdown(VELDFOUT_CSS, unsafe_allow_html=True)
    toon_sidebar()
    pagina = st.session_state.pagina
    rol = st.session_state.rol

    # ALLEEN_LEZEN en KAN_BESCHIKBAAR zijn hier exclusieve rol-identiteit (welke enige
    # weergave die rol krijgt), geen feature-poort — daarom bewust géén heeft_rol().
    # Head of Operations zit in geen van beide en valt door naar de paginakeuze hieronder,
    # waardoor het alle schermen kan openen (inclusief Beschikbaarheid).
    if rol in ALLEEN_LEZEN:
        pagina_rapportage()
    elif rol in KAN_BESCHIKBAAR:
        pagina_beschikbaarheid()
    elif pagina == "Kalender":
        pagina_kalender()
    elif pagina == "Examens":
        pagina_examens()
    elif pagina == "Aanmelden" and heeft_rol(rol, KAN_AANMELDEN):
        pagina_aanmelden()
    elif pagina == "Surveillanten" and heeft_rol(rol, KAN_PLANNEN):
        pagina_surveillanten()
    elif pagina == "Zaalbeheer" and heeft_rol(rol, KAN_PLANNEN):
        pagina_zaalbeheer()
    elif pagina == "Kalender beheer" and heeft_rol(rol, KAN_PLANNEN):
        pagina_kalender_beheer()
    elif pagina == "Import & Export" and heeft_rol(rol, KAN_IMPORTEREN):
        pagina_export()
    elif pagina == "Beschikbaarheid" and heeft_rol(rol, KAN_BESCHIKBAAR):
        pagina_beschikbaarheid()
    else:
        pagina_kalender()

if __name__ == "__main__":
    main()
