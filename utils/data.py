import streamlit as st
from datetime import date, timedelta
import math

LOCATIONS = [
    {"id": "BRK_SPORT",      "name": "Sporthal Breukelen",        "capacity": 350, "campus": "Breukelen", "primary": True},
    {"id": "BRK_SPORT_HALF", "name": "Sporthal Breukelen (half)", "capacity": 175, "campus": "Breukelen", "primary": True},
    {"id": "AMS_106107",     "name": "Amsterdam 1.06/1.07",       "capacity": 85,  "campus": "Amsterdam", "primary": True},
    {"id": "BRK_DR0203",     "name": "DR02/03 (combizaal)",       "capacity": 30,  "campus": "Breukelen", "primary": False},
    {"id": "BRK_COLJ",       "name": "Collegezaal J",             "capacity": 30,  "campus": "Breukelen", "primary": False},
]

TIME_BLOCKS = {
    "ochtend":  {"label": "Ochtend",  "start": "09:30", "end": "13:00", "color": "#EAF3DE", "text": "#27500A"},
    "middag":   {"label": "Middag",   "start": "14:00", "end": "17:30", "color": "#E6F1FB", "text": "#0C447C"},
    "avond":    {"label": "Avond",    "start": "19:00", "end": "22:30", "color": "#F5EEF1", "text": "#6B1F3A"},
}

# BScBA/FTMScM/PT MScM exam weeks (mornings available). Calendar weeks 2026.
EXAM_WEEKS_WITH_MORNINGS = [42, 50]  # BScBA exam weeks where morning blocks are lifted

SUPERVISORS = [
    {"id": "s1",  "name": "Winie",     "rol": "HS",   "email": "winie@nyenrode.nl"},
    {"id": "s2",  "name": "Ingrid",    "rol": "HS",   "email": "ingrid@nyenrode.nl"},
    {"id": "s3",  "name": "Peter",     "rol": "beide","email": "peter@nyenrode.nl"},
    {"id": "s4",  "name": "Hans",      "rol": "surv", "email": "hans@nyenrode.nl"},
    {"id": "s5",  "name": "Marten",    "rol": "surv", "email": "marten@nyenrode.nl"},
    {"id": "s6",  "name": "Jolanda",   "rol": "surv", "email": "jolanda@nyenrode.nl"},
    {"id": "s7",  "name": "Brigit",    "rol": "surv", "email": "brigit@nyenrode.nl"},
    {"id": "s8",  "name": "Petra",     "rol": "surv", "email": "petra@nyenrode.nl"},
    {"id": "s9",  "name": "Dania",     "rol": "surv", "email": "dania@nyenrode.nl"},
    {"id": "s10", "name": "Wajeeha",   "rol": "surv", "email": "wajeeha@nyenrode.nl"},
    {"id": "s11", "name": "Elizabeth", "rol": "HS",   "email": "elizabeth@nyenrode.nl"},
    {"id": "s12", "name": "Adele",     "rol": "HS",   "email": "adele@nyenrode.nl"},
    {"id": "s13", "name": "Tanya",     "rol": "surv", "email": "tanya@nyenrode.nl"},
    {"id": "s14", "name": "Analia",    "rol": "surv", "email": "analia@nyenrode.nl"},
    {"id": "s15", "name": "Xaverio",   "rol": "surv", "email": "xaverio@nyenrode.nl"},
]

SAMPLE_EXAMS = [
    # Week 38
    {"id":"e1",  "name":"Comptabele Aspecten Management Accounting","program":"Accountancy","type":"H","fau":False,"students":80, "week":38,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e2",  "name":"EV voor Accountants","program":"Accountancy","type":"H","fau":False,"students":150,"week":38,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Marije","budget":"P3900252","notes":"Let op eindtijd in relatie tot avondtentamens","status":"submitted"},
    # Week 39
    {"id":"e3",  "name":"Belastingrecht 2","program":"Accountancy","type":"H","fau":False,"students":80, "week":39,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e4",  "name":"Statistical Estimation & Testing","program":"Accountancy","type":"H","fau":False,"students":90, "week":39,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    # Week 40
    {"id":"e5",  "name":"Comptabele Aspecten Financial Accounting 2","program":"Accountancy","type":"H","fau":False,"students":80, "week":40,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    # Week 41
    {"id":"e6",  "name":"Corporate Governance","program":"Accountancy","type":"C","fau":False,"students":100,"week":41,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Marije","budget":"P3900236","notes":"","status":"submitted"},
    {"id":"e7",  "name":"Comptabele Aspecten Financiering","program":"Accountancy","type":"H","fau":False,"students":70, "week":41,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e8",  "name":"Management Accounting & Control","program":"Accountancy","type":"H","fau":False,"students":15, "week":41,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Denise","budget":"P3900273","notes":"kleine groep","status":"submitted"},
    # Week 42
    {"id":"e9",  "name":"Financiering 2","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":42,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"ochtend ivm diplomauitreiking","status":"submitted"},
    {"id":"e10", "name":"Introductie Boekhouden","program":"Accountancy","type":"C/H","fau":False,"students":60, "week":42,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e11", "name":"Statistical Reasoning","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":42,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e12", "name":"Essentials of Financial Accounting","program":"Accountancy","type":"C/H","fau":False,"students":100,"week":42,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    # Week 43
    {"id":"e13", "name":"Beginselen Accountancy","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":43,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e14", "name":"Auditing Beginselen","program":"Accountancy","type":"C/H","fau":False,"students":220,"week":43,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"4x hetzelfde tentamen — op zelfde tijdstip","status":"submitted"},
    {"id":"e15", "name":"Essentials of Auditing","program":"Accountancy","type":"C/H","fau":False,"students":130,"week":43,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e16", "name":"BIV-Inleiding (non-fin)","program":"Accountancy","type":"C/H","fau":False,"students":60, "week":43,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e17", "name":"Financial Accounting Theory PreMsc","program":"PreMSc Accountancy","type":"C/H","fau":False,"students":175,"week":43,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e18", "name":"Auditing Theory (ENG)","program":"Accountancy (ENG)","type":"C","fau":False,"students":20, "week":43,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Lotte Smeenk","budget":"P3900302","notes":"","status":"submitted"},
    # Week 44
    {"id":"e19", "name":"Management Accounting deeltentamen 1","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":44,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e20", "name":"Law deficientie","program":"Accountancy","type":"C/H","fau":False,"students":60, "week":44,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Denise","budget":"P3900276","notes":"","status":"submitted"},
    # Week 45
    {"id":"e21", "name":"Financial Accounting Theory (oude & nieuwe structuur)","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":45,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e22", "name":"Externe Verslaggeving","program":"Accountancy","type":"C","fau":False,"students":210,"week":45,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Inez","budget":"","notes":"","status":"submitted"},
    {"id":"e23", "name":"BIV deficientie","program":"Accountancy","type":"C/H","fau":False,"students":30, "week":45,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Denise","budget":"P3900217","notes":"","status":"submitted"},
    # Week 46
    {"id":"e24", "name":"Sampling & Regression Analysis","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":46,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e25", "name":"Academic Research in Accountancy","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":46,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Marije","budget":"P3900203","notes":"","status":"submitted"},
    # Week 47
    {"id":"e26", "name":"BIV-Inleiding (oude & nieuwe structuur)","program":"Accountancy","type":"H","fau":False,"students":60, "week":47,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e27", "name":"Ondernemingsrecht","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":47,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e28", "name":"Algemene Economie 1","program":"Accountancy","type":"H","fau":False,"students":60, "week":47,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    # Week 48
    {"id":"e29", "name":"Management Control","program":"Accountancy","type":"H","fau":False,"students":80, "week":48,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    # Week 49
    {"id":"e30", "name":"Financiering 1","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":49,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e31", "name":"Financial Auditing Instellingstoets","program":"Accountancy","type":"C/H","fau":False,"students":285,"week":49,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Marije","budget":"P3900256","notes":"","status":"submitted"},
    {"id":"e32", "name":"Financial Accounting","program":"Accountancy","type":"C/H","fau":False,"students":230,"week":49,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e33", "name":"BIV-Business Information Systems","program":"Accountancy","type":"C/H","fau":False,"students":80, "week":49,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    # Week 50
    {"id":"e34", "name":"Comptabele Aspecten Financial Accounting 1","program":"Accountancy","type":"C/H","fau":False,"students":224,"week":50,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e35", "name":"Belastingrecht 1","program":"Accountancy","type":"C/H","fau":False,"students":220,"week":50,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e36", "name":"Strategic Management","program":"PreMSc Accountancy","type":"C/H","fau":False,"students":114,"week":50,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e37", "name":"BIV-Business Information Systems PreMsc","program":"PreMSc Accountancy","type":"C/H","fau":False,"students":60, "week":50,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"Dit moet in de ochtend","status":"submitted"},
    # Week 51
    {"id":"e38", "name":"Algemene Economie 2","program":"Accountancy","type":"C/H","fau":False,"students":170,"week":51,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e39", "name":"Financial Auditing Landelijk","program":"Accountancy","type":"C","fau":True, "students":286,"week":51,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Marije","budget":"P3900256","notes":"LANDELIJK — datum en tijd niet wijzigbaar. Geen andere tentamens in Breukelen op deze dag.","status":"submitted"},
    {"id":"e40", "name":"Fraude & Witwassen","program":"Accountancy","type":"C/H","fau":False,"students":150,"week":51,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e41", "name":"Management Accounting deeltentamen 2","program":"Accountancy","type":"C/H","fau":False,"students":230,"week":51,"time_pref":"ochtend","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
    {"id":"e42", "name":"Auditing Theory","program":"Accountancy","type":"C/H","fau":False,"students":130,"week":51,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"3x hetzelfde tentamen — op zelfde tijdstip","status":"submitted"},
    {"id":"e43", "name":"Auditing Theory PreMsc","program":"PreMSc Accountancy","type":"C/H","fau":False,"students":271,"week":51,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Wendy","budget":"P3900259","notes":"","status":"submitted"},
    {"id":"e44", "name":"Beginselen Recht","program":"Accountancy","type":"C/H","fau":False,"students":260,"week":51,"time_pref":"middag","loc_pref":"BRK_SPORT","format":"Cirrus","contact":"Iris","budget":"P3900250","notes":"","status":"submitted"},
]

def week_to_monday(year: int, week: int) -> date:
    return date.fromisocalendar(year, week, 1)

def initialize_data():
    if "initialized" in st.session_state:
        return

    st.session_state.initialized = True
    st.session_state.locations = LOCATIONS
    st.session_state.time_blocks = TIME_BLOCKS
    st.session_state.supervisors = SUPERVISORS
    st.session_state.exam_weeks_mornings = EXAM_WEEKS_WITH_MORNINGS

    # Exams
    exams = [e.copy() for e in SAMPLE_EXAMS]
    for e in exams:
        e["slot_id"] = None  # not yet assigned
    st.session_state.exams = exams

    # Pre-generate slots for Aug–Dec 2026 (weeks 33–53)
    slots = []
    slot_id = 1
    start = date(2026, 8, 10)
    end   = date(2026, 12, 31)
    d = start
    while d <= end:
        for tb in ["ochtend", "middag", "avond"]:
            for loc in LOCATIONS:
                slots.append({
                    "id": f"slot_{slot_id}",
                    "date": d.isoformat(),
                    "time_block": tb,
                    "location_id": loc["id"],
                    "assigned_exam_ids": [],
                })
                slot_id += 1
        d += timedelta(days=1)
    st.session_state.slots = slots

    # Availability (empty to start)
    avail = []
    for sup in SUPERVISORS:
        for slot in slots:
            avail.append({
                "supervisor_id": sup["id"],
                "slot_id": slot["id"],
                "status": "open",  # open, hs, surv, nee
            })
    st.session_state.availability = avail

    # HS available per slot (default 3)
    st.session_state.hs_per_slot = {}

def get_location(loc_id: str) -> dict:
    return next((l for l in st.session_state.locations if l["id"] == loc_id), None)

def get_slot(slot_id: str) -> dict:
    return next((s for s in st.session_state.slots if s["id"] == slot_id), None)

def get_exam(exam_id: str) -> dict:
    return next((e for e in st.session_state.exams if e["id"] == exam_id), None)

def get_slots_for_date_time_loc(d: str, time_block: str, loc_id: str) -> dict:
    return next((s for s in st.session_state.slots
                 if s["date"] == d and s["time_block"] == time_block and s["location_id"] == loc_id), None)

def get_assigned_exams(slot: dict) -> list:
    return [get_exam(eid) for eid in slot["assigned_exam_ids"] if get_exam(eid)]

def slot_capacity_used(slot: dict) -> int:
    return sum(e["students"] for e in get_assigned_exams(slot) if e)

def slot_hs_needed(slot: dict) -> int:
    n = len(slot["assigned_exam_ids"])
    return math.ceil(n / 2) if n > 0 else 0

def slot_surv_needed(slot: dict) -> int:
    total = slot_capacity_used(slot)
    return math.ceil(total / 50) if total > 0 else 0

def get_date_iso_for_week(week: int, day_of_week: int = 2, year: int = 2026) -> str:
    """day_of_week: 1=Mon, 7=Sun. Default Wednesday."""
    return date.fromisocalendar(year, week, day_of_week).isoformat()
