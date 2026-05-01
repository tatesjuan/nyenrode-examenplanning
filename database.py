import sqlite3
import os
from datetime import datetime, date

DB_PATH = "examenplanning.db"

TIJDBLOKKEN = {
    "ochtend": ("09:30", "13:00"),
    "middag":  ("14:00", "17:30"),
    "avond":   ("19:00", "22:30"),
}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS locaties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT NOT NULL,
        campus TEXT NOT NULL,
        capaciteit INTEGER NOT NULL,
        is_primair INTEGER DEFAULT 1,
        voorkeur_volgorde INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS examens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT NOT NULL,
        programma TEXT,
        afdeling TEXT,
        examtype TEXT DEFAULT 'C',
        is_fau INTEGER DEFAULT 0,
        voorkeur_datum TEXT,
        voorkeur_week INTEGER,
        voorkeur_tijdblok TEXT,
        duur_minuten INTEGER DEFAULT 120,
        geschat_aantal INTEGER DEFAULT 0,
        locatie_voorkeur TEXT DEFAULT 'Breukelen',
        format TEXT DEFAULT 'Cirrus',
        bijlage_vereist INTEGER DEFAULT 0,
        nieuwe_studenten INTEGER DEFAULT 0,
        contactpersoon TEXT,
        budgetnummer TEXT,
        opmerkingen TEXT,
        status TEXT DEFAULT 'concept',
        ingediend_door TEXT,
        aangemaakt_op TEXT
    );

    CREATE TABLE IF NOT EXISTS slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        datum TEXT NOT NULL,
        tijdblok TEXT NOT NULL,
        start_tijd TEXT NOT NULL,
        eind_tijd TEXT NOT NULL,
        locatie_id INTEGER,
        geblokkeerd INTEGER DEFAULT 0,
        blok_reden TEXT,
        FOREIGN KEY (locatie_id) REFERENCES locaties(id)
    );

    CREATE TABLE IF NOT EXISTS toewijzingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        examen_id INTEGER,
        slot_id INTEGER,
        halve_zaal INTEGER DEFAULT 0,
        aangemeld_door TEXT,
        aangemeld_op TEXT,
        override_reden TEXT,
        FOREIGN KEY (examen_id) REFERENCES examens(id),
        FOREIGN KEY (slot_id) REFERENCES slots(id)
    );

    CREATE TABLE IF NOT EXISTS surveillanten (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT NOT NULL,
        email TEXT,
        kan_hs INTEGER DEFAULT 0,
        kan_surv INTEGER DEFAULT 1,
        actief INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS beschikbaarheid (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        surveillant_id INTEGER,
        slot_id INTEGER,
        beschikbaar INTEGER,
        rol_voorkeur TEXT,
        tijdstip_opgave TEXT,
        UNIQUE(surveillant_id, slot_id),
        FOREIGN KEY (surveillant_id) REFERENCES surveillanten(id),
        FOREIGN KEY (slot_id) REFERENCES slots(id)
    );

    CREATE TABLE IF NOT EXISTS surv_toewijzingen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        surveillant_id INTEGER,
        slot_id INTEGER,
        rol TEXT,
        toegewezen_door TEXT,
        toegewezen_op TEXT,
        FOREIGN KEY (surveillant_id) REFERENCES surveillanten(id),
        FOREIGN KEY (slot_id) REFERENCES slots(id)
    );

    CREATE TABLE IF NOT EXISTS academische_kalender (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        programma TEXT NOT NULL,
        week_start TEXT NOT NULL,
        week_eind TEXT NOT NULL,
        academisch_jaar TEXT DEFAULT '2026-2027'
    );
    """)

    conn.commit()

    if c.execute("SELECT COUNT(*) FROM locaties").fetchone()[0] == 0:
        _seed_locaties(conn)
    if c.execute("SELECT COUNT(*) FROM surveillanten").fetchone()[0] == 0:
        _seed_surveillanten(conn)
    if c.execute("SELECT COUNT(*) FROM academische_kalender").fetchone()[0] == 0:
        _seed_kalender(conn)

    conn.close()


def _seed_locaties(conn):
    conn.executemany(
        "INSERT INTO locaties (naam, campus, capaciteit, is_primair, voorkeur_volgorde) VALUES (?,?,?,?,?)",
        [
            ("Sporthal Breukelen (heel)", "Breukelen", 350, 1, 1),
            ("Sporthal Breukelen (half)", "Breukelen", 175, 0, 2),
            ("Amsterdam 1.06/1.07",       "Amsterdam",  85, 1, 1),
            ("DR02/03 Breukelen",          "Breukelen",  30, 0, 3),
            ("Collegezaal J Breukelen",    "Breukelen",  30, 0, 4),
        ]
    )
    conn.commit()


def _seed_surveillanten(conn):
    conn.executemany(
        "INSERT INTO surveillanten (naam, email, kan_hs, kan_surv, actief) VALUES (?,?,?,?,1)",
        [
            ("Winie",     "winie@nyenrode.nl",     1, 1),
            ("Ingrid",    "ingrid@nyenrode.nl",    1, 1),
            ("Peter",     "peter@nyenrode.nl",     1, 1),
            ("Hans",      "hans@nyenrode.nl",      0, 1),
            ("Marten",    "marten@nyenrode.nl",    0, 1),
            ("Jolanda",   "jolanda@nyenrode.nl",   0, 1),
            ("Brigit",    "brigit@nyenrode.nl",    0, 1),
            ("Petra",     "petra@nyenrode.nl",     0, 1),
            ("Dania",     "dania@nyenrode.nl",     0, 1),
            ("Elizabeth", "elizabeth@nyenrode.nl", 1, 1),
            ("Adele",     "adele@nyenrode.nl",     0, 1),
            ("Tanya",     "tanya@nyenrode.nl",     0, 1),
            ("Analia",    "analia@nyenrode.nl",    0, 1),
            ("Xaverio",   "xaverio@nyenrode.nl",   0, 1),
        ]
    )
    conn.commit()


def _seed_kalender(conn):
    # BScBA examenweeks 2026-2027 (periods from calendar)
    conn.executemany(
        "INSERT INTO academische_kalender (programma, week_start, week_eind, academisch_jaar) VALUES (?,?,?,?)",
        [
            ("BScBA",   "2026-10-19", "2026-10-23", "2026-2027"),
            ("BScBA",   "2026-12-14", "2026-12-18", "2026-2027"),
            ("BScBA",   "2027-01-25", "2027-01-29", "2026-2027"),
            ("BScBA",   "2027-03-22", "2027-03-26", "2026-2027"),
            ("BScBA",   "2027-05-17", "2027-05-21", "2026-2027"),
            ("FTMScM",  "2026-10-05", "2026-10-09", "2026-2027"),
            ("FTMScM",  "2026-12-14", "2026-12-18", "2026-2027"),
            ("FTMScM",  "2027-02-22", "2027-02-26", "2026-2027"),
            ("FTMScM",  "2027-05-10", "2027-05-14", "2026-2027"),
            ("PT MScM", "2026-10-05", "2026-10-09", "2026-2027"),
            ("PT MScM", "2026-12-07", "2026-12-11", "2026-2027"),
        ]
    )
    conn.commit()


# ── LOCATIES ─────────────────────────────────────────────

def get_locaties():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM locaties ORDER BY voorkeur_volgorde").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_locatie(locatie_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM locaties WHERE id=?", (locatie_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── EXAMENS ───────────────────────────────────────────────

def get_examens(status=None):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM examens WHERE status=? ORDER BY geschat_aantal DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM examens ORDER BY geschat_aantal DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_examen(examen_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM examens WHERE id=?", (examen_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_examen(data: dict):
    conn = get_conn()
    data.setdefault("aangemaakt_op", datetime.now().isoformat())
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    conn.execute(f"INSERT INTO examens ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    conn.close()


def update_examen_status(examen_id, status):
    conn = get_conn()
    conn.execute("UPDATE examens SET status=? WHERE id=?", (status, examen_id))
    conn.commit()
    conn.close()


def delete_examen(examen_id):
    conn = get_conn()
    conn.execute("DELETE FROM toewijzingen WHERE examen_id=?", (examen_id,))
    conn.execute("DELETE FROM examens WHERE id=?", (examen_id,))
    conn.commit()
    conn.close()


def get_ongeplande_examens():
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.* FROM examens e
        WHERE e.status IN ('ingediend','gepland') 
        AND e.id NOT IN (SELECT examen_id FROM toewijzingen)
        ORDER BY e.geschat_aantal DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── SLOTS ─────────────────────────────────────────────────

def get_or_create_slot(datum: str, tijdblok: str, locatie_id: int):
    start, eind = TIJDBLOKKEN[tijdblok]
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM slots WHERE datum=? AND tijdblok=? AND locatie_id=?",
        (datum, tijdblok, locatie_id)
    ).fetchone()
    if row:
        conn.close()
        return dict(row)
    conn.execute(
        "INSERT INTO slots (datum, tijdblok, start_tijd, eind_tijd, locatie_id) VALUES (?,?,?,?,?)",
        (datum, tijdblok, start, eind, locatie_id)
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM slots WHERE datum=? AND tijdblok=? AND locatie_id=?",
        (datum, tijdblok, locatie_id)
    ).fetchone()
    conn.close()
    return dict(row)


def get_slots_for_month(jaar: int, maand: int):
    conn = get_conn()
    prefix = f"{jaar:04d}-{maand:02d}"
    rows = conn.execute(
        "SELECT * FROM slots WHERE datum LIKE ? ORDER BY datum, tijdblok",
        (f"{prefix}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_slot(slot_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── TOEWIJZINGEN ──────────────────────────────────────────

def get_toewijzingen_voor_slot(slot_id: int):
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.*, e.naam, e.programma, e.examtype, e.geschat_aantal, e.is_fau
        FROM toewijzingen t
        JOIN examens e ON t.examen_id = e.id
        WHERE t.slot_id = ?
    """, (slot_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_toewijzing_voor_examen(examen_id: int):
    conn = get_conn()
    row = conn.execute("""
        SELECT t.*, s.datum, s.tijdblok, s.start_tijd, s.eind_tijd, s.locatie_id,
               l.naam as locatie_naam, l.capaciteit
        FROM toewijzingen t
        JOIN slots s ON t.slot_id = s.id
        JOIN locaties l ON s.locatie_id = l.id
        WHERE t.examen_id = ?
    """, (examen_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def plan_examen(examen_id: int, slot_id: int, aangemeld_door: str,
                halve_zaal: bool = False, override_reden: str = None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO toewijzingen (examen_id, slot_id, halve_zaal, aangemeld_door, aangemeld_op, override_reden)
        VALUES (?,?,?,?,?,?)
    """, (examen_id, slot_id, int(halve_zaal), aangemeld_door,
          datetime.now().isoformat(), override_reden))
    conn.execute("UPDATE examens SET status='gepland' WHERE id=?", (examen_id,))
    conn.commit()
    conn.close()


def verwijder_toewijzing(examen_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM toewijzingen WHERE examen_id=?", (examen_id,))
    conn.execute("UPDATE examens SET status='ingediend' WHERE id=?", (examen_id,))
    conn.commit()
    conn.close()


def bevestig_examen(examen_id: int):
    conn = get_conn()
    conn.execute("UPDATE examens SET status='bevestigd' WHERE id=?", (examen_id,))
    conn.commit()
    conn.close()


# ── SLOT-STATISTIEKEN ─────────────────────────────────────

def slot_stats(slot_id: int):
    tw = get_toewijzingen_voor_slot(slot_id)
    totaal_studenten = sum(t["geschat_aantal"] or 0 for t in tw)
    n_examens = len(tw)
    hs_nodig = -(-n_examens // 2) if n_examens > 0 else 0
    surv_nodig = -(-totaal_studenten // 50) if totaal_studenten > 0 else 0
    return {
        "n_examens": n_examens,
        "totaal_studenten": totaal_studenten,
        "hs_nodig": hs_nodig,
        "surv_nodig": surv_nodig,
        "toewijzingen": tw,
    }


# ── SURVEILLANTEN ─────────────────────────────────────────

def get_surveillanten(alleen_actief=True):
    conn = get_conn()
    q = "SELECT * FROM surveillanten"
    if alleen_actief:
        q += " WHERE actief=1"
    q += " ORDER BY naam"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_surveillant(naam, email, kan_hs, kan_surv):
    conn = get_conn()
    conn.execute(
        "INSERT INTO surveillanten (naam, email, kan_hs, kan_surv, actief) VALUES (?,?,?,?,1)",
        (naam, email, int(kan_hs), int(kan_surv))
    )
    conn.commit()
    conn.close()


def sla_beschikbaarheid_op(surveillant_id, slot_id, beschikbaar, rol_voorkeur):
    conn = get_conn()
    conn.execute("""
        INSERT INTO beschikbaarheid (surveillant_id, slot_id, beschikbaar, rol_voorkeur, tijdstip_opgave)
        VALUES (?,?,?,?,?)
        ON CONFLICT(surveillant_id, slot_id) DO UPDATE SET
            beschikbaar=excluded.beschikbaar,
            rol_voorkeur=excluded.rol_voorkeur,
            tijdstip_opgave=excluded.tijdstip_opgave
    """, (surveillant_id, slot_id, int(beschikbaar), rol_voorkeur, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_beschikbaarheid_matrix(slot_ids: list):
    if not slot_ids:
        return {}
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM beschikbaarheid WHERE slot_id IN ({})
    """.format(",".join("?" * len(slot_ids))), slot_ids).fetchall()
    conn.close()
    matrix = {}
    for r in rows:
        matrix[(r["surveillant_id"], r["slot_id"])] = dict(r)
    return matrix


def get_beschikbaarheid_voor_surveillant(surveillant_id, slot_ids):
    if not slot_ids:
        return {}
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM beschikbaarheid
        WHERE surveillant_id=? AND slot_id IN ({})
    """.format(",".join("?" * len(slot_ids))), [surveillant_id] + list(slot_ids)).fetchall()
    conn.close()
    return {r["slot_id"]: dict(r) for r in rows}


def wijs_surveillant_toe(slot_id, surveillant_id, rol, toegewezen_door):
    conn = get_conn()
    # Check if already assigned
    existing = conn.execute(
        "SELECT id FROM surv_toewijzingen WHERE slot_id=? AND surveillant_id=?",
        (slot_id, surveillant_id)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE surv_toewijzingen SET rol=?, toegewezen_door=?, toegewezen_op=? WHERE id=?",
            (rol, toegewezen_door, datetime.now().isoformat(), existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO surv_toewijzingen (slot_id, surveillant_id, rol, toegewezen_door, toegewezen_op) VALUES (?,?,?,?,?)",
            (slot_id, surveillant_id, rol, toegewezen_door, datetime.now().isoformat())
        )
    conn.commit()
    conn.close()


def get_surv_toewijzingen_voor_slot(slot_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT st.*, s.naam, s.kan_hs
        FROM surv_toewijzingen st
        JOIN surveillanten s ON st.surveillant_id = s.id
        WHERE st.slot_id = ?
    """, (slot_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def verwijder_surv_toewijzing(slot_id, surveillant_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM surv_toewijzingen WHERE slot_id=? AND surveillant_id=?",
        (slot_id, surveillant_id)
    )
    conn.commit()
    conn.close()


# ── ACADEMISCHE KALENDER ──────────────────────────────────

def get_examenweeks():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM academische_kalender ORDER BY week_start").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_examenweek(programma, week_start, week_eind, jaar="2026-2027"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO academische_kalender (programma, week_start, week_eind, academisch_jaar) VALUES (?,?,?,?)",
        (programma, week_start, week_eind, jaar)
    )
    conn.commit()
    conn.close()


def delete_examenweek(week_id):
    conn = get_conn()
    conn.execute("DELETE FROM academische_kalender WHERE id=?", (week_id,))
    conn.commit()
    conn.close()


def is_examenweek(check_date: date) -> bool:
    weeks = get_examenweeks()
    for w in weeks:
        start = date.fromisoformat(w["week_start"])
        eind = date.fromisoformat(w["week_eind"])
        if start <= check_date <= eind:
            return True
    return False


# ── IMPORT / EXPORT ───────────────────────────────────────

def import_examens_uit_excel(df):
    import pandas as pd
    aangemaakt = 0
    fouten = []

    kolommap = {
        "TENTAMEN ": "naam",
        "TENTAMEN": "naam",
        "Programma": "programma",
        "geschat aantal": "geschat_aantal",
        "tijd": "voorkeur_tijdblok_raw",
        "TIJDSDUUR": "duur_raw",
        "Dag": "dag",
        "Datum": "voorkeur_datum",
        "cirrus of  papier": "format",
        "cirrus of papier": "format",
        "contactpersoon reservering sporthal": "contactpersoon",
        "budgetnr": "budgetnummer",
        "Bijlage": "bijlage_raw",
        "veel nieuwe studenten???": "nieuwe_studenten_raw",
        "A.U.B. GEEN CELLEN SAMENVOEGEN": "opmerkingen",
    }

    df = df.rename(columns={k: v for k, v in kolommap.items() if k in df.columns})

    for _, row in df.iterrows():
        naam = str(row.get("naam", "")).strip()
        if not naam or naam in ("nan", ""):
            continue
        if naam.lower() in ("1e kerstdag", "2e kerstdag", "oudjaarsdag", "nieuwjaarsdag", "suikerfeest"):
            continue

        try:
            geschat = int(float(str(row.get("geschat_aantal", 0)).replace("max", "").strip().split()[0]))
        except Exception:
            geschat = 0

        tijdblok_raw = str(row.get("voorkeur_tijdblok_raw", "")).strip()
        if "09" in tijdblok_raw:
            tijdblok = "ochtend"
        elif "14" in tijdblok_raw:
            tijdblok = "middag"
        elif "18" in tijdblok_raw or "19" in tijdblok_raw:
            tijdblok = "avond"
        else:
            tijdblok = "middag"

        fmt = str(row.get("format", "Cirrus")).strip()
        if not fmt or fmt == "nan":
            fmt = "Cirrus"

        opm = str(row.get("opmerkingen", "")).strip()
        if opm == "nan":
            opm = ""

        is_fau = 1 if "landelijk" in naam.lower() or "fau" in naam.lower() else 0

        data = {
            "naam": naam,
            "programma": str(row.get("programma", "")).strip(),
            "examtype": "C",
            "is_fau": is_fau,
            "voorkeur_tijdblok": tijdblok,
            "geschat_aantal": geschat,
            "locatie_voorkeur": "Breukelen",
            "format": fmt,
            "contactpersoon": str(row.get("contactpersoon", "")).strip(),
            "budgetnummer": str(row.get("budgetnummer", "")).strip(),
            "opmerkingen": opm,
            "status": "ingediend",
            "ingediend_door": "Import",
            "aangemaakt_op": datetime.now().isoformat(),
        }

        add_examen(data)
        aangemaakt += 1

    return aangemaakt, fouten


def export_naar_csv():
    import io
    import pandas as pd
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            e.naam as Tentamen,
            e.programma as Programma,
            e.examtype as Type,
            e.geschat_aantal as Studenten,
            s.datum as Datum,
            s.start_tijd as Start,
            s.eind_tijd as Eind,
            l.naam as Locatie,
            e.format as Format,
            e.contactpersoon as Contactpersoon,
            e.budgetnummer as Budgetnummer,
            e.opmerkingen as Opmerkingen,
            e.status as Status
        FROM examens e
        LEFT JOIN toewijzingen t ON e.id = t.examen_id
        LEFT JOIN slots s ON t.slot_id = s.id
        LEFT JOIN locaties l ON s.locatie_id = l.id
        ORDER BY s.datum, s.start_tijd, e.naam
    """).fetchall()
    conn.close()
    df = pd.DataFrame([dict(r) for r in rows])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()
