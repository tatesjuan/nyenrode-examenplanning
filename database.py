import sqlite3
import os
import re
import threading
from datetime import datetime, date

DB_PATH = "examenplanning.db"

TIJDBLOKKEN = {
    "ochtend": ("09:30", "13:00"),
    "middag":  ("14:00", "17:30"),
    "avond":   ("19:00", "22:30"),
}

EXAMTYPES = ["Exam", "Retake", "Retake 2", "Retake 3", "Exam/Retake"]

# BRK+AMS = examen vindt simultaan op beide campussen plaats.
LOCATIE_VOORKEUREN = ["BRK", "AMS", "BRK+AMS"]

EXAMTYPE_MIGRATIE = {
    "C":   "Exam",
    "H":   "Retake",
    "C/H": "Exam/Retake",
    "H1":  "Retake",
    "H2":  "Retake 2",
    "H3":  "Retake 3",
}

LOCATIE_MIGRATIE = {
    "Breukelen": "BRK",
    "Amsterdam": "AMS",
}

# Extra ruimtes naast de oorspronkelijke seed. (naam, campus, min_capaciteit, capaciteit)
# Worden op naam bijgezet, zodat bestaande installaties niets dubbel krijgen.
EXTRA_LOCATIES = [
    ("DR 101",               "Breukelen", 13, 23),
    ("DR 102",               "Breukelen", 13, 23),
    ("DR 103",               "Breukelen", 13, 23),
    ("DR 104",               "Breukelen", 24, 42),
    ("Collegezaal B",        "Breukelen",  0, 20),
    ("Collegezaal C",        "Breukelen",  0, 20),
    ("Collegezaal H",        "Breukelen", 20, 22),
    ("Collegezaal D",        "Breukelen",  0, 20),
    ("Collegezaal G",        "Breukelen",  0, 24),
    ("AHA Exec 1",           "Amsterdam", 24, 28),
    ("AHA Exec 2",           "Amsterdam", 24, 28),
    ("AHA Exec 3",           "Amsterdam", 24, 28),
    ("DR Theater Executive", "Breukelen",  0, 20),
    ("Pfizer",               "Amsterdam", 48, 66),
]

VERLENGING_PER_BLOK = 5      # minuten extra per 30 minuten examenduur
VERLENGING_BLOK = 30
VERLENGING_MAX = 60

MAX_EXAMENS_PER_SLOT_STANDAARD = 2
SPORTHAL_MAX_EXAMENS = 5
# Sporthalvarianten (Deel C, Facilitor-naamconventie). De drie delen dezelfde fysieke
# ruimte: Geheel (350) = Links (175) + Rechts (175).
SPORTHAL_GEHEEL = "Sporthal Geheel"
SPORTHAL_RECHTS = "Sporthal Rechts"
SPORTHAL_LINKS = "Sporthal Links"
# Deze drie mogen meer gelijktijdige examens aan dan een gewone zaal.
SPORTHAL_NAMEN = (SPORTHAL_GEHEEL, SPORTHAL_RECHTS, SPORTHAL_LINKS)
# Eenmalige hernoeming van de oude namen naar de Facilitor-namen (Deel C).
SPORTHAL_HERNOEM = {
    "Sporthal Breukelen (heel)": SPORTHAL_GEHEEL,
    "Sporthal Breukelen (half)": SPORTHAL_RECHTS,
}
# Auto-plan mag alleen deze Amsterdamse zaal gebruiken (naast de sporthalvarianten).
AMS_AUTOPLAN = "Amsterdam 1.06/1.07"

# ── SURVEILLANTEN: CONTRACT & UREN ───────────────────────
UUR_PER_FTE = 2080                 # 1 FTE = 2080 uur per jaar
SESSIE_UREN = 5.5                  # uren die één surveillance-sessie oplevert
CONTRACT_TYPES = ["nul-uren", "FTE"]
# FTE-contracten die bij een verse of nog niet-gemigreerde database worden gezet.
FTE_CONTRACT_SEED = {"Hans": 0.23, "Winie": 0.45}

# Primaire campus van een surveillant. Het auto-toewijzingsalgoritme zet iemand alleen
# in op slots van deze campus; handmatige toewijzing door de planner is niet beperkt.
SURV_CAMPUSSEN = ["BRK", "AMS"]
SURV_CAMPUS_STANDAARD = "BRK"

# Deel B-personeelsmutaties: eenmalig toegepast als de campus-kolom wordt toegevoegd
# (upgrade van bestaande data) én verwerkt in _seed_surveillanten voor verse databases.
SURV_CAMPUS_AMS = ("Adele", "Tanya", "Xaverio", "Elizabeth")     # rest = BRK
SURV_INACTIEF = ("Analia", "Brigit", "Dania", "Marten")          # historie blijft behouden
SURV_NIEUW = [  # (naam, email, kan_hs, campus) — nul-uren, actief
    ("Marjan", "marjan@nyenrode.nl", 0, "BRK"),
    ("Pratty", "pratty@nyenrode.nl", 0, "BRK"),
]


def campus_code(campus_naam):
    """Zet een locatie-campus ('Breukelen'/'Amsterdam') om naar de surveillant-campuscode ('BRK'/'AMS')."""
    return LOCATIE_MIGRATIE.get(campus_naam, campus_naam)


def bereken_jaardoel(fte_factor) -> float:
    """jaardoel_uren = fte_factor * 2080, op 1 decimaal."""
    try:
        return round(float(fte_factor or 0) * UUR_PER_FTE, 1)
    except (TypeError, ValueError):
        return 0.0


def bepaal_academisch_jaar(datum) -> str:
    """
    Academisch jaar loopt 1 augustus t/m 31 juli.
    2026-10-15 -> '2026-2027', 2027-03-10 -> '2026-2027'.
    """
    d = date.fromisoformat(datum) if isinstance(datum, str) else datum
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{start + 1}"


def bereken_verlenging(duur_minuten) -> int:
    """5 minuten verlenging per volle 30 minuten examenduur, gemaximeerd op 60."""
    try:
        duur = int(duur_minuten or 0)
    except (TypeError, ValueError):
        return 0
    if duur <= 0:
        return 0
    return min(VERLENGING_MAX, (duur // VERLENGING_BLOK) * VERLENGING_PER_BLOK)

# ══ VERBINDINGSLAAG ═══════════════════════════════════════
# Twee modi: lokale SQLite (ontwikkelen, geen credentials nodig) of Turso/libSQL
# (productie op Streamlit Community Cloud, data overleeft herstarts). De keuze valt
# op Turso zodra beide secrets aanwezig zijn; anders altijd terug naar lokale SQLite.
#
# De rest van de code gebruikt de sqlite3-API onveranderd: conn.execute(...).fetchone(),
# row["kolom"], dict(row), conn.executescript/executemany/cursor, row_factory = Row.
# Voor Turso bootst een dunne wrapper die API na bovenop libsql-client (pure Python,
# geen compilatie nodig — libsql-experimental vereiste een Rust-build die op Streamlit
# Community Cloud faalde). libsql-client werkt met create_client_sync() en levert een
# ResultSet met .rows/.columns i.p.v. cursor/fetchone; de wrapper overbrugt dat.

def _turso_config():
    """
    Leest TURSO_DATABASE_URL en TURSO_AUTH_TOKEN defensief uit st.secrets en anders
    uit os.environ. Geeft (url, token) of (None, None). Faalt nooit: als er geen
    secrets-bestand is (StreamlitSecretNotFoundError) of streamlit ontbreekt, gaan
    we door naar os.environ en uiteindelijk naar lokale SQLite.
    """
    url = token = None
    try:
        import streamlit as st
        try:
            url = st.secrets["TURSO_DATABASE_URL"]
            token = st.secrets["TURSO_AUTH_TOKEN"]
        except Exception:
            # KeyError (sleutel ontbreekt) of StreamlitSecretNotFoundError (geen bestand).
            url = token = None
    except Exception:
        url = token = None

    url = url or os.environ.get("TURSO_DATABASE_URL")
    token = token or os.environ.get("TURSO_AUTH_TOKEN")
    return (url or None), (token or None)


def _gebruik_turso():
    url, token = _turso_config()
    return bool(url and token)


class _Row:
    """Dict-achtige rij: ondersteunt row['kolom'], row[0] en dict(row), net als sqlite3.Row."""
    __slots__ = ("_cols", "_vals", "_map")

    def __init__(self, cols, vals):
        self._cols = cols
        self._vals = tuple(vals)
        self._map = {c: v for c, v in zip(cols, self._vals)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._map[key]

    def get(self, key, default=None):
        return self._map.get(key, default)

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


class _Cursor:
    """
    Bootst een sqlite3-cursor na bovenop een libsql-client ResultSet. libsql-client
    voert eager uit en levert alle rijen ineens; wij bufferen ze en geven ze via
    fetchone()/fetchall() als _Row (want dict(libsql_client.Row) faalt).
    """
    def __init__(self, resultset):
        cols = list(getattr(resultset, "columns", ()) or ())
        self._rows = [_Row(cols, r.astuple()) for r in getattr(resultset, "rows", ()) or ()]
        self._cols = cols
        self._i = 0
        self._lastrowid = getattr(resultset, "last_insert_rowid", None)

    def fetchone(self):
        if self._i < len(self._rows):
            r = self._rows[self._i]
            self._i += 1
            return r
        return None

    def fetchall(self):
        rest = self._rows[self._i:]
        self._i = len(self._rows)
        return rest

    def __iter__(self):
        while self._i < len(self._rows):
            yield self.fetchone()

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def description(self):
        # DBAPI-vorm: 7-tuple per kolom, alleen [0] (naam) is betekenisvol.
        return [(c, None, None, None, None, None, None) for c in self._cols]


def _split_sql(script):
    """Splitst een executescript-blok in losse statements (schema bevat geen ';' in literals)."""
    stmts = []
    for raw in script.split(";"):
        regels = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(regels).strip()
        if stmt:
            stmts.append(stmt)
    return stmts


class _TursoConn:
    """
    Dunne sqlite3-compatibele wrapper om een libsql-client ClientSync. Alleen de
    methoden die de rest van de code gebruikt zijn geïmplementeerd. De client voert
    elk statement direct uit (auto-commit), dus commit() is een no-op.
    """
    def __init__(self, client):
        self._client = client
        self.row_factory = None  # genegeerd; we leveren altijd _Row

    @staticmethod
    def _args(params):
        # sqlite3 gebruikt ? met een tuple; libsql-client accepteert een list (of dict).
        # Leeg -> None, zodat parameterloze queries niet struikelen.
        return list(params) if params else None

    def cursor(self):
        # De code doet conn.cursor().execute(...); onze wrapper kan dat zelf al.
        return self

    def execute(self, sql, params=()):
        return _Cursor(self._client.execute(sql, self._args(params)))

    def executemany(self, sql, seq_of_params):
        for params in seq_of_params:
            self._client.execute(sql, self._args(params))
        return self

    def executescript(self, script):
        # libsql-client heeft geen executescript; splits het schema zelf.
        for stmt in _split_sql(script):
            self._client.execute(stmt)
        return self

    def commit(self):
        # libsql-client (sync HTTP) commit per statement; expliciete commit is een no-op.
        pass

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


def _turso_connect(url, token):
    import libsql_client
    client = libsql_client.create_client_sync(url=url, auth_token=token)
    wrapper = _TursoConn(client)
    try:
        wrapper.execute("PRAGMA foreign_keys = ON")
    except Exception:
        # Niet elke libsql-build ondersteunt PRAGMA; geen blokkerend probleem.
        pass
    return wrapper


class _GedeeldeConn:
    """
    Wrappt een verbinding die gedeeld wordt binnen één rerun. Helper-functies doen aan
    het eind `conn.close()`; bij een gedeelde verbinding is dat een no-op, zodat de ene
    verbinding de hele rerun open blijft. De rerun sluit hem zelf via sluit_gedeelde_conn().
    """
    def __init__(self, echt):
        self._echt = echt

    def execute(self, *a, **k):
        return self._echt.execute(*a, **k)

    def executemany(self, *a, **k):
        return self._echt.executemany(*a, **k)

    def executescript(self, *a, **k):
        return self._echt.executescript(*a, **k)

    def cursor(self):
        return self._echt.cursor()

    def commit(self):
        return self._echt.commit()

    def close(self):
        pass  # gedeelde verbinding: niet sluiten per helper-aanroep

    @property
    def row_factory(self):
        return getattr(self._echt, "row_factory", None)

    @row_factory.setter
    def row_factory(self, waarde):
        try:
            self._echt.row_factory = waarde
        except Exception:
            pass

    def _sluit_echt(self):
        try:
            self._echt.close()
        except Exception:
            pass


# Per-thread (dus per Streamlit-sessie) de gedeelde verbinding van de huidige rerun.
_rerun_conn = threading.local()


def _nieuwe_verbinding():
    if _gebruik_turso():
        url, token = _turso_config()
        return _turso_connect(url, token)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn():
    """
    Geeft de gedeelde rerun-verbinding als die er is (Streamlit-pad), anders een verse
    verbinding (tests, scripts, init_db bij het opstarten). De API is identiek, dus geen
    enkele bestaande helper hoeft te veranderen.
    """
    gedeeld = getattr(_rerun_conn, "conn", None)
    if gedeeld is not None:
        return gedeeld
    return _nieuwe_verbinding()


def open_gedeelde_conn():
    """Opent één verbinding voor de duur van een rerun; alle get_conn() hergebruiken die."""
    _rerun_conn.conn = _GedeeldeConn(_nieuwe_verbinding())
    return _rerun_conn.conn


def sluit_gedeelde_conn():
    """Sluit de gedeelde rerun-verbinding en zet het pad terug op verse verbindingen."""
    c = getattr(_rerun_conn, "conn", None)
    _rerun_conn.conn = None
    if c is not None:
        c._sluit_echt()

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS locaties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT NOT NULL,
        campus TEXT NOT NULL,
        min_capaciteit INTEGER DEFAULT 0,
        capaciteit INTEGER NOT NULL,
        max_examens_per_slot INTEGER DEFAULT 2,
        is_primair INTEGER DEFAULT 1,
        voorkeur_volgorde INTEGER DEFAULT 1,
        actief INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS examens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naam TEXT NOT NULL,
        programma TEXT,
        afdeling TEXT,
        examtype TEXT DEFAULT 'Exam',
        is_fau INTEGER DEFAULT 0,
        voorkeur_datum TEXT,
        voorkeur_week INTEGER,
        voorkeur_tijdblok TEXT,
        duur_minuten INTEGER DEFAULT 120,
        verlenging_minuten INTEGER DEFAULT 0,
        geschat_aantal INTEGER DEFAULT 0,
        locatie_voorkeur TEXT DEFAULT 'BRK',
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
        actief INTEGER DEFAULT 1,
        contract_type TEXT DEFAULT 'nul-uren',
        fte_factor REAL DEFAULT 0,
        jaardoel_uren REAL DEFAULT 0,
        campus TEXT DEFAULT 'BRK'
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

    CREATE TABLE IF NOT EXISTS surv_uren_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        surveillant_id INTEGER,
        slot_id INTEGER,
        datum TEXT,
        uren REAL,
        academisch_jaar TEXT,
        UNIQUE(surveillant_id, slot_id),
        FOREIGN KEY (surveillant_id) REFERENCES surveillanten(id),
        FOREIGN KEY (slot_id) REFERENCES slots(id)
    );

    CREATE TABLE IF NOT EXISTS periode_blokkades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        surveillant_id INTEGER,
        datum_van TEXT NOT NULL,
        datum_tot TEXT NOT NULL,
        reden TEXT,
        aangemaakt_op TEXT,
        FOREIGN KEY (surveillant_id) REFERENCES surveillanten(id)
    );

    CREATE TABLE IF NOT EXISTS maandprofiel_handmatig (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        academisch_jaar TEXT NOT NULL,
        maand TEXT NOT NULL,
        categorie TEXT NOT NULL,
        UNIQUE(academisch_jaar, maand)
    );
    """)

    conn.commit()

    _migreer_examens(conn)
    # Kolommen bijzetten vóór het seeden, anders bestaat min_capaciteit nog niet.
    _migreer_locaties(conn)
    _migreer_sporthal(conn)
    _migreer_surveillanten(conn)

    if c.execute("SELECT COUNT(*) FROM locaties").fetchone()[0] == 0:
        _seed_locaties(conn)
    _seed_extra_locaties(conn)
    if c.execute("SELECT COUNT(*) FROM surveillanten").fetchone()[0] == 0:
        _seed_surveillanten(conn)
    if c.execute("SELECT COUNT(*) FROM academische_kalender").fetchone()[0] == 0:
        _seed_kalender(conn)

    conn.close()


def _migreer_examens(conn):
    """
    Zet bestaande rijen om naar het huidige datamodel. Idempotent: geen van de
    nieuwe waarden komt voor als sleutel in de migratietabellen, dus herhaald
    draaien is een no-op.
    """
    kolommen = {r["name"] for r in conn.execute("PRAGMA table_info(examens)").fetchall()}
    if "verlenging_minuten" not in kolommen:
        conn.execute("ALTER TABLE examens ADD COLUMN verlenging_minuten INTEGER DEFAULT 0")

    for oud, nieuw in EXAMTYPE_MIGRATIE.items():
        conn.execute("UPDATE examens SET examtype=? WHERE examtype=?", (nieuw, oud))
    for oud, nieuw in LOCATIE_MIGRATIE.items():
        conn.execute("UPDATE examens SET locatie_voorkeur=? WHERE locatie_voorkeur=?", (nieuw, oud))

    onbekend = conn.execute(
        "SELECT id, duur_minuten FROM examens WHERE verlenging_minuten IS NULL OR verlenging_minuten = 0"
    ).fetchall()
    for row in onbekend:
        conn.execute(
            "UPDATE examens SET verlenging_minuten=? WHERE id=?",
            (bereken_verlenging(row["duur_minuten"]), row["id"])
        )

    conn.commit()


def _migreer_sporthal(conn):
    """
    Deel C: hernoem de oude sporthalvarianten naar de Facilitor-namen en voeg
    'Sporthal Links' toe. Idempotent:
    - de hernoemingen matchen op de OUDE naam, dus na de eerste keer no-op;
    - Links wordt alleen toegevoegd als hij nog niet bestaat (naam-check).
    De hernoeming behoudt de locatie-id, dus bestaande geplande examens (via slots)
    blijven automatisch kloppen.
    """
    for oud, nieuw in SPORTHAL_HERNOEM.items():
        conn.execute("UPDATE locaties SET naam=? WHERE naam=?", (nieuw, oud))
    # Links alleen bijzetten op de UPGRADE-route (Geheel/Rechts bestaan al na de rename).
    # Op een verse database is de locaties-tabel hier nog leeg; _seed_locaties voegt dan
    # alle drie de varianten in. Zonder deze guard zou een losse Links-insert de tabel
    # niet-leeg maken en de COUNT==0-seedcheck in init_db overslaan.
    heeft_hal = conn.execute(
        "SELECT COUNT(*) FROM locaties WHERE naam IN (?, ?)",
        (SPORTHAL_GEHEEL, SPORTHAL_RECHTS)).fetchone()[0]
    heeft_links = conn.execute("SELECT COUNT(*) FROM locaties WHERE naam=?",
                               (SPORTHAL_LINKS,)).fetchone()[0]
    if heeft_hal and not heeft_links:
        # Zelfde eigenschappen als Rechts: 175, Breukelen, max 5 examens/slot.
        conn.execute(
            "INSERT INTO locaties (naam, campus, min_capaciteit, capaciteit, "
            "max_examens_per_slot, is_primair, voorkeur_volgorde, actief) "
            "VALUES (?, 'Breukelen', 0, 175, ?, 0, 3, 1)",
            (SPORTHAL_LINKS, SPORTHAL_MAX_EXAMENS)
        )
    conn.commit()


def _migreer_locaties(conn):
    """Zet min_capaciteit en actief bij op bestaande installaties. Idempotent."""
    kolommen = {r["name"] for r in conn.execute("PRAGMA table_info(locaties)").fetchall()}
    if "min_capaciteit" not in kolommen:
        conn.execute("ALTER TABLE locaties ADD COLUMN min_capaciteit INTEGER DEFAULT 0")
    if "actief" not in kolommen:
        conn.execute("ALTER TABLE locaties ADD COLUMN actief INTEGER DEFAULT 1")
    if "max_examens_per_slot" not in kolommen:
        # DDL laat geen placeholder toe in DEFAULT; de constante is een door ons
        # beheerde int, dus letterlijk interpoleren is veilig.
        conn.execute(
            f"ALTER TABLE locaties ADD COLUMN max_examens_per_slot INTEGER "
            f"DEFAULT {int(MAX_EXAMENS_PER_SLOT_STANDAARD)}"
        )
        # Eénmalig bij het toevoegen van de kolom: sporthallen op 5, rest op de default.
        # Bewust niet elke init_db, zodat latere handmatige aanpassingen blijven staan.
        conn.execute("UPDATE locaties SET max_examens_per_slot=? WHERE max_examens_per_slot IS NULL",
                     (MAX_EXAMENS_PER_SLOT_STANDAARD,))
        # Zowel de nieuwe (Geheel/Rechts/Links) als de oude namen dekken: op een pre-2b
        # upgrade draait deze migratie vóór _migreer_sporthal, dus de rijen dragen dan
        # nog de oude namen. Zo krijgen ze 5 ongeacht of de hernoeming al gebeurd is.
        for naam in tuple(SPORTHAL_NAMEN) + tuple(SPORTHAL_HERNOEM.keys()):
            conn.execute("UPDATE locaties SET max_examens_per_slot=? WHERE naam=?",
                         (SPORTHAL_MAX_EXAMENS, naam))
    # ALTER TABLE vult bestaande rijen met NULL i.p.v. de default.
    conn.execute("UPDATE locaties SET min_capaciteit=0 WHERE min_capaciteit IS NULL")
    conn.execute("UPDATE locaties SET actief=1 WHERE actief IS NULL")
    conn.commit()


def _zet_contract(conn, naam, contract_type, fte_factor):
    """Zet een contract op een surveillant op naam; jaardoel wordt afgeleid."""
    factor = float(fte_factor or 0) if contract_type == "FTE" else 0.0
    conn.execute(
        "UPDATE surveillanten SET contract_type=?, fte_factor=?, jaardoel_uren=? WHERE naam=?",
        (contract_type, factor, bereken_jaardoel(factor), naam)
    )


def _migreer_surveillanten(conn):
    """Zet contract- en campuskolommen bij op bestaande installaties. Idempotent."""
    kolommen = {r["name"] for r in conn.execute("PRAGMA table_info(surveillanten)").fetchall()}
    contract_net = "contract_type" not in kolommen
    campus_net = "campus" not in kolommen

    # DDL laat geen placeholder in DEFAULT toe; letterlijke waarden zijn hier veilig.
    if contract_net:
        conn.execute("ALTER TABLE surveillanten ADD COLUMN contract_type TEXT DEFAULT 'nul-uren'")
    if "fte_factor" not in kolommen:
        conn.execute("ALTER TABLE surveillanten ADD COLUMN fte_factor REAL DEFAULT 0")
    if "jaardoel_uren" not in kolommen:
        conn.execute("ALTER TABLE surveillanten ADD COLUMN jaardoel_uren REAL DEFAULT 0")
    if campus_net:
        conn.execute("ALTER TABLE surveillanten ADD COLUMN campus TEXT DEFAULT 'BRK'")

    # ALTER TABLE vult bestaande rijen met NULL i.p.v. de default.
    conn.execute("UPDATE surveillanten SET contract_type='nul-uren' WHERE contract_type IS NULL")
    conn.execute("UPDATE surveillanten SET fte_factor=0 WHERE fte_factor IS NULL")
    conn.execute("UPDATE surveillanten SET jaardoel_uren=0 WHERE jaardoel_uren IS NULL")
    conn.execute("UPDATE surveillanten SET campus='BRK' WHERE campus IS NULL")

    # Eénmalig bij het toevoegen van de contractkolommen: de bekende FTE-contracten zetten.
    # Bewust niet elke init_db, zodat latere handmatige aanpassingen blijven staan.
    if contract_net:
        for naam, factor in FTE_CONTRACT_SEED.items():
            _zet_contract(conn, naam, "FTE", factor)

    # Deel B-personeelsmutaties: eenmalig bij het toevoegen van de campus-kolom.
    # IN-clausules i.p.v. per-rij UPDATEs -> één round-trip per mutatie (Turso-latency).
    if campus_net:
        ams_ph = ",".join("?" * len(SURV_CAMPUS_AMS))
        conn.execute(f"UPDATE surveillanten SET campus='AMS' WHERE naam IN ({ams_ph})",
                     tuple(SURV_CAMPUS_AMS))
        inact_ph = ",".join("?" * len(SURV_INACTIEF))
        conn.execute(f"UPDATE surveillanten SET actief=0 WHERE naam IN ({inact_ph})",
                     tuple(SURV_INACTIEF))
        # Nieuwe medewerkers alleen toevoegen als ze nog niet bestaan (op naam).
        bestaand = {r["naam"] for r in conn.execute("SELECT naam FROM surveillanten").fetchall()}
        nieuw = [(n, e, kh, c) for (n, e, kh, c) in SURV_NIEUW if n not in bestaand]
        if nieuw:
            conn.executemany(
                "INSERT INTO surveillanten (naam, email, kan_hs, kan_surv, actief, campus, "
                "contract_type, fte_factor, jaardoel_uren) VALUES (?,?,?,1,1,?,'nul-uren',0,0)",
                nieuw
            )

    conn.commit()


def _seed_extra_locaties(conn):
    """Voegt alleen ontbrekende ruimtes toe; bestaande namen blijven onaangeroerd."""
    bestaand = {r["naam"] for r in conn.execute("SELECT naam FROM locaties").fetchall()}
    nieuw = [(n, c, mn, mx) for n, c, mn, mx in EXTRA_LOCATIES if n not in bestaand]
    if not nieuw:
        return 0
    conn.executemany(
        "INSERT INTO locaties (naam, campus, min_capaciteit, capaciteit, is_primair, voorkeur_volgorde, actief) "
        "VALUES (?,?,?,?,0,9,1)",
        nieuw
    )
    conn.commit()
    return len(nieuw)


def _seed_locaties(conn):
    conn.executemany(
        "INSERT INTO locaties (naam, campus, capaciteit, max_examens_per_slot, is_primair, voorkeur_volgorde) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("Sporthal Geheel",           "Breukelen", 350, SPORTHAL_MAX_EXAMENS, 1, 1),
            ("Sporthal Rechts",           "Breukelen", 175, SPORTHAL_MAX_EXAMENS, 0, 2),
            ("Sporthal Links",            "Breukelen", 175, SPORTHAL_MAX_EXAMENS, 0, 3),
            ("Amsterdam 1.06/1.07",       "Amsterdam",  85, MAX_EXAMENS_PER_SLOT_STANDAARD, 1, 1),
            ("DR02/03 Breukelen",          "Breukelen",  30, MAX_EXAMENS_PER_SLOT_STANDAARD, 0, 4),
            ("Collegezaal J Breukelen",    "Breukelen",  30, MAX_EXAMENS_PER_SLOT_STANDAARD, 0, 5),
        ]
    )
    conn.commit()


def _seed_surveillanten(conn):
    # (naam, email, kan_hs, actief, campus) — Deel B: personeelsmutaties zijn hier verwerkt.
    conn.executemany(
        "INSERT INTO surveillanten (naam, email, kan_hs, kan_surv, actief, campus) "
        "VALUES (?,?,?,1,?,?)",
        [
            ("Winie",     "winie@nyenrode.nl",     1, 1, "BRK"),
            ("Ingrid",    "ingrid@nyenrode.nl",    1, 1, "BRK"),
            ("Peter",     "peter@nyenrode.nl",     1, 1, "BRK"),
            ("Hans",      "hans@nyenrode.nl",      0, 1, "BRK"),
            ("Marten",    "marten@nyenrode.nl",    0, 0, "BRK"),
            ("Jolanda",   "jolanda@nyenrode.nl",   0, 1, "BRK"),
            ("Brigit",    "brigit@nyenrode.nl",    0, 0, "BRK"),
            ("Petra",     "petra@nyenrode.nl",     0, 1, "BRK"),
            ("Dania",     "dania@nyenrode.nl",     0, 0, "BRK"),
            ("Elizabeth", "elizabeth@nyenrode.nl", 1, 1, "AMS"),
            ("Adele",     "adele@nyenrode.nl",     0, 1, "AMS"),
            ("Tanya",     "tanya@nyenrode.nl",     0, 1, "AMS"),
            ("Analia",    "analia@nyenrode.nl",    0, 0, "BRK"),
            ("Xaverio",   "xaverio@nyenrode.nl",   0, 1, "AMS"),
            ("Marjan",    "marjan@nyenrode.nl",    0, 1, "BRK"),
            ("Pratty",    "pratty@nyenrode.nl",    0, 1, "BRK"),
        ]
    )
    # Verse database: de contractkolommen bestaan al via CREATE TABLE, dus de
    # eenmalige migratie-seed draait hier niet — zet de FTE-contracten hier.
    for naam, factor in FTE_CONTRACT_SEED.items():
        _zet_contract(conn, naam, "FTE", factor)
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

def get_locaties(alleen_actief: bool = False):
    """alleen_actief=False (standaard) geeft ook inactieve zalen terug."""
    conn = get_conn()
    q = "SELECT * FROM locaties"
    if alleen_actief:
        q += " WHERE actief=1"
    q += " ORDER BY voorkeur_volgorde, naam"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_locatie(naam, campus, min_capaciteit, capaciteit, actief=True,
                max_examens_per_slot=MAX_EXAMENS_PER_SLOT_STANDAARD,
                is_primair=0, voorkeur_volgorde=9):
    conn = get_conn()
    conn.execute(
        "INSERT INTO locaties (naam, campus, min_capaciteit, capaciteit, max_examens_per_slot, "
        "is_primair, voorkeur_volgorde, actief) VALUES (?,?,?,?,?,?,?,?)",
        (naam, campus, int(min_capaciteit), int(capaciteit), int(max_examens_per_slot),
         int(is_primair), int(voorkeur_volgorde), int(actief))
    )
    conn.commit()
    conn.close()


def update_locatie(locatie_id, naam, campus, min_capaciteit, capaciteit, actief,
                   max_examens_per_slot=MAX_EXAMENS_PER_SLOT_STANDAARD):
    conn = get_conn()
    conn.execute(
        "UPDATE locaties SET naam=?, campus=?, min_capaciteit=?, capaciteit=?, actief=?, "
        "max_examens_per_slot=? WHERE id=?",
        (naam, campus, int(min_capaciteit), int(capaciteit), int(actief),
         int(max_examens_per_slot), locatie_id)
    )
    conn.commit()
    conn.close()


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


TE_BEWERKEN_VELDEN = {
    "naam", "programma", "afdeling", "examtype", "is_fau", "voorkeur_datum",
    "voorkeur_week", "voorkeur_tijdblok", "duur_minuten", "verlenging_minuten",
    "geschat_aantal", "locatie_voorkeur", "format", "bijlage_vereist",
    "nieuwe_studenten", "contactpersoon", "budgetnummer", "opmerkingen",
}


def update_examen(examen_id, data: dict):
    velden = {k: v for k, v in data.items() if k in TE_BEWERKEN_VELDEN}
    if not velden:
        return
    zetters = ", ".join(f"{k}=?" for k in velden)
    conn = get_conn()
    conn.execute(f"UPDATE examens SET {zetters} WHERE id=?",
                 list(velden.values()) + [examen_id])
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


def get_toewijzingen_voor_maand(jaar: int, maand: int):
    """
    Alle toewijzingen van alle slots in een maand in één query, gegroepeerd per slot_id.
    Vervangt N losse get_toewijzingen_voor_slot()-aanroepen in de UI. Elke rij heeft
    dezelfde kolommen als get_toewijzingen_voor_slot(). Slots zonder toewijzing komen niet
    voor in de dict; aanroepers gebruiken .get(slot_id, []).
    """
    prefix = f"{jaar:04d}-{maand:02d}"
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.*, e.naam, e.programma, e.examtype, e.geschat_aantal, e.is_fau
        FROM toewijzingen t
        JOIN slots s ON t.slot_id = s.id
        JOIN examens e ON t.examen_id = e.id
        WHERE s.datum LIKE ?
    """, (f"{prefix}%",)).fetchall()
    conn.close()
    per_slot = {}
    for r in rows:
        per_slot.setdefault(r["slot_id"], []).append(dict(r))
    return per_slot


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


def get_toewijzingen_per_examen():
    """
    De toewijzing van álle ingeplande examens in één query, als dict examen_id -> rij
    met dezelfde kolommen als get_toewijzing_voor_examen(). Vervangt de per-examen-lus
    in de examenlijst en de rapportage. Examens zonder toewijzing komen niet voor;
    aanroepers gebruiken .get(examen_id).
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.*, s.datum, s.tijdblok, s.start_tijd, s.eind_tijd, s.locatie_id,
               l.naam as locatie_naam, l.capaciteit
        FROM toewijzingen t
        JOIN slots s ON t.slot_id = s.id
        JOIN locaties l ON s.locatie_id = l.id
    """).fetchall()
    conn.close()
    # Eén examen kan meerdere toewijzingsrijen hebben; net als de losse functie
    # houden we de eerste aan (fetchone-gedrag).
    per_examen = {}
    for r in rows:
        per_examen.setdefault(r["examen_id"], dict(r))
    return per_examen


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


def add_surveillant(naam, email, kan_hs, kan_surv, campus=SURV_CAMPUS_STANDAARD):
    conn = get_conn()
    conn.execute(
        "INSERT INTO surveillanten (naam, email, kan_hs, kan_surv, actief, campus) VALUES (?,?,?,?,1,?)",
        (naam, email, int(kan_hs), int(kan_surv), campus)
    )
    conn.commit()
    conn.close()


def update_surveillant(surveillant_id, campus=None, actief=None):
    """Werkt beheerbare velden bij (campus, actief). Alleen meegegeven velden wijzigen."""
    zetters, params = [], []
    if campus is not None:
        zetters.append("campus=?"); params.append(campus)
    if actief is not None:
        zetters.append("actief=?"); params.append(int(actief))
    if not zetters:
        return
    conn = get_conn()
    conn.execute(f"UPDATE surveillanten SET {', '.join(zetters)} WHERE id=?",
                 params + [surveillant_id])
    conn.commit()
    conn.close()


def update_surveillant_contract(surveillant_id, contract_type, fte_factor):
    """Zet contracttype en FTE-factor; jaardoel_uren wordt automatisch herberekend.
    Bij een nul-urencontract worden factor en jaardoel op 0 gezet."""
    if contract_type == "FTE":
        factor = float(fte_factor or 0)
    else:
        contract_type = "nul-uren"
        factor = 0.0
    conn = get_conn()
    conn.execute(
        "UPDATE surveillanten SET contract_type=?, fte_factor=?, jaardoel_uren=? WHERE id=?",
        (contract_type, factor, bereken_jaardoel(factor), surveillant_id)
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

    # Urenlog bijschrijven. UNIQUE(surveillant_id, slot_id) + DO NOTHING zorgt dat een
    # rolwijziging op hetzelfde slot de sessie niet dubbel telt.
    slot = conn.execute("SELECT datum FROM slots WHERE id=?", (slot_id,)).fetchone()
    if slot and slot["datum"]:
        conn.execute("""
            INSERT INTO surv_uren_log (surveillant_id, slot_id, datum, uren, academisch_jaar)
            VALUES (?,?,?,?,?)
            ON CONFLICT(surveillant_id, slot_id) DO NOTHING
        """, (surveillant_id, slot_id, slot["datum"], SESSIE_UREN,
              bepaal_academisch_jaar(slot["datum"])))

    conn.commit()
    conn.close()


def get_surv_toewijzingen_voor_slot(slot_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT st.*, s.naam, s.kan_hs, s.campus
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
    # Bijbehorende urenregel meeverwijderen, zodat de teller klopt.
    conn.execute(
        "DELETE FROM surv_uren_log WHERE slot_id=? AND surveillant_id=?",
        (slot_id, surveillant_id)
    )
    conn.commit()
    conn.close()


# ── UREN & CONTRACT ───────────────────────────────────────

def get_uren_totaal(surveillant_id, academisch_jaar):
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(uren), 0) AS t FROM surv_uren_log "
        "WHERE surveillant_id=? AND academisch_jaar=?",
        (surveillant_id, academisch_jaar)
    ).fetchone()
    conn.close()
    return round(row["t"] or 0.0, 1)


def get_uren_per_maand(surveillant_id, academisch_jaar):
    """Dict 'YYYY-MM' -> gedraaide uren voor het opgegeven academisch jaar."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT datum, uren FROM surv_uren_log WHERE surveillant_id=? AND academisch_jaar=?",
        (surveillant_id, academisch_jaar)
    ).fetchall()
    conn.close()
    per_maand = {}
    for r in rows:
        if not r["datum"]:
            continue
        maand = r["datum"][:7]  # YYYY-MM
        per_maand[maand] = round(per_maand.get(maand, 0.0) + (r["uren"] or 0.0), 1)
    return per_maand


def get_urenoverzicht(academisch_jaar):
    """Per surveillant: contract, jaardoel, gedraaide uren, verschil en sessies.
    Twee queries in totaal: alle surveillanten + één GROUP BY over de urenlog."""
    conn = get_conn()
    survs = conn.execute("SELECT * FROM surveillanten ORDER BY naam").fetchall()
    agg_rows = conn.execute(
        "SELECT surveillant_id, COALESCE(SUM(uren), 0) AS gedraaid, COUNT(*) AS sessies "
        "FROM surv_uren_log WHERE academisch_jaar=? GROUP BY surveillant_id",
        (academisch_jaar,)
    ).fetchall()
    conn.close()

    agg = {r["surveillant_id"]: r for r in agg_rows}
    overzicht = []
    for s in survs:
        a = agg.get(s["id"])
        gedraaid = round((a["gedraaid"] if a else 0.0) or 0.0, 1)
        sessies = a["sessies"] if a else 0
        jaardoel = round(s["jaardoel_uren"] or 0.0, 1)
        overzicht.append({
            "id": s["id"],
            "naam": s["naam"],
            "contract_type": s["contract_type"] or "nul-uren",
            "fte_factor": s["fte_factor"] or 0,
            "jaardoel_uren": jaardoel,
            "gedraaide_uren": gedraaid,
            "verschil": round(gedraaid - jaardoel, 1),
            "sessies": sessies,
            "actief": s["actief"],
        })
    return overzicht


# ── PERIODE-BLOKKADES ─────────────────────────────────────

def add_periode_blokkade(surveillant_id, datum_van, datum_tot, reden=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO periode_blokkades (surveillant_id, datum_van, datum_tot, reden, aangemaakt_op) "
        "VALUES (?,?,?,?,?)",
        (surveillant_id, datum_van, datum_tot, reden, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_periode_blokkades(surveillant_id=None):
    conn = get_conn()
    if surveillant_id is None:
        rows = conn.execute("SELECT * FROM periode_blokkades ORDER BY datum_van").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM periode_blokkades WHERE surveillant_id=? ORDER BY datum_van",
            (surveillant_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_periode_blokkade(blokkade_id):
    conn = get_conn()
    conn.execute("DELETE FROM periode_blokkades WHERE id=?", (blokkade_id,))
    conn.commit()
    conn.close()


def is_geblokkeerd_in_periode(surveillant_id, datum):
    """True als `datum` binnen een opgegeven blokkadeperiode van de surveillant valt (grenzen inclusief)."""
    d = datum if isinstance(datum, str) else datum.isoformat()
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM periode_blokkades "
        "WHERE surveillant_id=? AND datum_van<=? AND datum_tot>=?",
        (surveillant_id, d, d)
    ).fetchone()
    conn.close()
    return row["n"] > 0


# ── MAANDPROFIEL & AUTO-TOEWIJZING (data) ─────────────────

def get_studenten_per_maand(academisch_jaar):
    """Dict 'YYYY-MM' -> totaal aantal studenten over geplande examens in dat academisch jaar."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.datum, e.geschat_aantal
        FROM toewijzingen t
        JOIN slots s ON t.slot_id = s.id
        JOIN examens e ON t.examen_id = e.id
    """).fetchall()
    conn.close()
    per_maand = {}
    for r in rows:
        if not r["datum"]:
            continue
        if bepaal_academisch_jaar(r["datum"]) != academisch_jaar:
            continue
        maand = r["datum"][:7]
        per_maand[maand] = per_maand.get(maand, 0) + (r["geschat_aantal"] or 0)
    return per_maand


def set_maandprofiel_handmatig(academisch_jaar, maand, categorie):
    conn = get_conn()
    conn.execute("""
        INSERT INTO maandprofiel_handmatig (academisch_jaar, maand, categorie)
        VALUES (?,?,?)
        ON CONFLICT(academisch_jaar, maand) DO UPDATE SET categorie=excluded.categorie
    """, (academisch_jaar, maand, categorie))
    conn.commit()
    conn.close()


def get_maandprofiel_handmatig(academisch_jaar):
    """Dict 'YYYY-MM' -> handmatig gezette categorie."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT maand, categorie FROM maandprofiel_handmatig WHERE academisch_jaar=?",
        (academisch_jaar,)
    ).fetchall()
    conn.close()
    return {r["maand"]: r["categorie"] for r in rows}


def delete_maandprofiel_handmatig(academisch_jaar, maand):
    """Zet een maand terug naar automatische bepaling."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM maandprofiel_handmatig WHERE academisch_jaar=? AND maand=?",
        (academisch_jaar, maand)
    )
    conn.commit()
    conn.close()


def get_beschikbare_surveillanten_voor_slot(slot_id):
    """
    Actieve surveillanten die zich voor dit slot beschikbaar hebben gesteld
    (beschikbaarheid.beschikbaar=1), met hun opgegeven rol_voorkeur.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.*, b.rol_voorkeur
        FROM surveillanten s
        JOIN beschikbaarheid b ON b.surveillant_id = s.id
        WHERE b.slot_id = ? AND b.beschikbaar = 1 AND s.actief = 1
    """, (slot_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def tel_beschikbare_slots_in_jaar(surveillant_id, academisch_jaar):
    """Aantal slots waarvoor de surveillant zich dit academisch jaar beschikbaar stelde."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.datum
        FROM beschikbaarheid b
        JOIN slots s ON b.slot_id = s.id
        WHERE b.surveillant_id = ? AND b.beschikbaar = 1
    """, (surveillant_id,)).fetchall()
    conn.close()
    return sum(1 for r in rows if r["datum"] and bepaal_academisch_jaar(r["datum"]) == academisch_jaar)


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

IMPORT_DUUR_STANDAARD = 120


def _parse_locatie_voorkeur(raw):
    """Leidt BRK / AMS / BRK+AMS af uit een vrije-tekst locatiekolom. None = niets opgegeven."""
    s = str(raw or "").strip().upper()
    if not s or s == "NAN":
        return None
    heeft_brk = "BRK" in s or "BREUKELEN" in s
    heeft_ams = "AMS" in s or "AMSTERDAM" in s
    if heeft_brk and heeft_ams:
        return "BRK+AMS"
    if heeft_ams:
        return "AMS"
    if heeft_brk:
        return "BRK"
    return None


# Kolomherkenning werkt op genormaliseerde namen (alleen letters/cijfers, lowercase),
# zodat hoofdletters, spaties, dubbele spaties en leestekens niet uitmaken.
# Dekt zowel de Chrono-export als EXAM_totaalplanning.
KOLOM_ALIASSEN = {
    "naam":                  ["tentamen", "toets", "tentamentoets", "toetstentamen",
                              "tentamennaam", "examen", "vak"],
    "programma":             ["programma", "program", "opleiding"],
    "geschat_aantal":        ["geschataantal", "aantalstudenten", "aantal", "studenten",
                              "geschataantalstudenten"],
    "duur_raw":              ["tijdsduur", "duur", "duurminuten", "tijdsduurtentamen", "lengte"],
    "voorkeur_tijdblok_raw": ["tijd", "slot", "tijdslot", "tijdblok", "dagdeel"],
    "voorkeur_datum":        ["datum", "date"],
    "week_raw":              ["week", "kalenderweek", "weeknr", "weeknummer"],
    "dag":                   ["dag", "weekdag"],
    "examtype_raw":          ["chretake", "chr", "type", "examtype", "toetstype", "soort"],
    "locatie_raw":           ["locatie", "campus", "zaal", "ruimte"],
    "format":                ["cirrusofpapier", "format", "afnamevorm"],
    "contactpersoon":        ["contactpersoonreserveringsporthal", "contactpersoon", "contact"],
    "budgetnummer":          ["budgetnr", "budgetnummer", "budget"],
    "bijlage_raw":           ["bijlage"],
    "nieuwe_studenten_raw":  ["veelnieuwestudenten"],
    "opmerkingen":           ["aubgeencellensamenvoegen", "opmerkingen", "notities", "notes",
                              "toelichting"],
}


def _norm_kolom(naam) -> str:
    return re.sub(r"[^a-z0-9]", "", str(naam).strip().lower())


def _map_kolommen(df):
    """Hernoemt herkende kolommen naar canonieke namen. Eerste match wint bij duplicaten."""
    naar_canon = {}
    for canon, aliassen in KOLOM_ALIASSEN.items():
        for alias in aliassen:
            naar_canon[alias] = canon

    hernoem = {}
    gebruikt = set()
    for kol in df.columns:
        canon = naar_canon.get(_norm_kolom(kol))
        if canon and canon not in gebruikt:
            hernoem[kol] = canon
            gebruikt.add(canon)
    return df.rename(columns=hernoem)


def _parse_duur(raw, standaard=None):
    """
    Leest een tijdsduur uit vrije tekst: "2 uur", "120", "2:00", "180 min", "1,5 uur".
    Een kaal getal <= 12 wordt als uren gelezen, daarboven als minuten.
    Valt terug op `standaard` als er niets bruikbaars in staat.
    """
    if standaard is None:
        standaard = IMPORT_DUUR_STANDAARD
    s = str(raw if raw is not None else "").strip().lower()
    if not s or s == "nan":
        return standaard

    # "2:00" / "2.30" als uu:mm
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", s)
    if m:
        minuten = int(m.group(1)) * 60 + int(m.group(2))
        return minuten if minuten > 0 else standaard

    m = re.search(r"(\d+(?:[.,]\d+)?)", s)
    if not m:
        return standaard
    getal = float(m.group(1).replace(",", "."))

    if re.search(r"\b(uur|uren|hour|hours|hr|h)\b", s):
        minuten = getal * 60
    elif re.search(r"\b(min|minuten|minutes|m)\b", s):
        minuten = getal
    else:
        minuten = getal * 60 if getal <= 12 else getal

    minuten = int(round(minuten))
    return minuten if minuten > 0 else standaard


def _parse_examtype(raw):
    """Leest C/H/Retake-varianten en zet ze om naar de EXAMTYPES-waarden."""
    s = str(raw if raw is not None else "").strip()
    if not s or s.lower() == "nan":
        return "Exam"

    for t in EXAMTYPES:                       # al een nieuwe waarde
        if s.lower() == t.lower():
            return t
    if s.upper() in EXAMTYPE_MIGRATIE:        # oude code: C, H, C/H, H1..H3
        return EXAMTYPE_MIGRATIE[s.upper()]

    low = s.lower()
    m = re.search(r"retake\s*([123])?", low)
    if m:
        if "c" in low.split("retake")[0] and "/" in low:
            return "Exam/Retake"
        return {"2": "Retake 2", "3": "Retake 3"}.get(m.group(1), "Retake")
    if "exam" in low and "retake" not in low:
        return "Exam"
    return "Exam"


def _parse_datum(raw):
    """Geeft een ISO-datum (YYYY-MM-DD) of None."""
    if raw is None:
        return None
    if isinstance(raw, (datetime, date)):
        return (raw.date() if isinstance(raw, datetime) else raw).isoformat()
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        import pandas as pd
        return pd.to_datetime(s, dayfirst=True).date().isoformat()
    except Exception:
        return None


def _parse_tijdblok(raw, standaard="middag"):
    s = str(raw if raw is not None else "").strip().lower()
    if not s or s == "nan":
        return standaard
    for blok in ("ochtend", "middag", "avond"):
        if blok in s:
            return blok
    if "09" in s:
        return "ochtend"
    if "14" in s:
        return "middag"
    if "18" in s or "19" in s:
        return "avond"
    return standaard


def import_examens_uit_excel(df, alleen_examens: bool = False):
    """
    Importeert examens uit een Chrono-export of een EXAM_totaalplanning-export.

    alleen_examens=True (Programmacoördinator): locatiekolommen in het bestand
    worden genegeerd; elk examen krijgt de standaardlocatie. Geeft terug:
    (aangemaakt, fouten, genegeerde_locatie_overschrijvingen).
    """
    import pandas as pd
    aangemaakt = 0
    fouten = []
    genegeerde_locaties = 0

    df = _map_kolommen(df)

    for _, row in df.iterrows():
        naam = str(row.get("naam", "")).strip()
        if not naam or naam in ("nan", ""):
            continue
        if naam.lower() in ("1e kerstdag", "2e kerstdag", "oudjaarsdag", "nieuwjaarsdag", "suikerfeest"):
            continue

        # Lege slots in EXAM_totaalplanning staan als BESCHIKBAAR; dat zijn geen examens.
        slot_raw = str(row.get("voorkeur_tijdblok_raw", "") or "")
        if "beschikbaar" in slot_raw.lower() or "beschikbaar" in naam.lower():
            continue

        try:
            geschat = int(float(str(row.get("geschat_aantal", 0)).replace("max", "").strip().split()[0]))
        except Exception:
            geschat = 0

        tijdblok = _parse_tijdblok(slot_raw)
        duur = _parse_duur(row.get("duur_raw"))

        fmt = str(row.get("format", "Cirrus")).strip()
        if not fmt or fmt == "nan":
            fmt = "Cirrus"

        opm = str(row.get("opmerkingen", "")).strip()
        if opm == "nan":
            opm = ""

        is_fau = 1 if "landelijk" in naam.lower() or "fau" in naam.lower() else 0

        gevraagde_locatie = _parse_locatie_voorkeur(row.get("locatie_raw"))
        if alleen_examens and gevraagde_locatie:
            genegeerde_locaties += 1
            gevraagde_locatie = None

        try:
            week = int(float(str(row.get("week_raw", "")).strip()))
        except (TypeError, ValueError):
            week = None

        data = {
            "naam": naam,
            "programma": str(row.get("programma", "")).strip(),
            "examtype": _parse_examtype(row.get("examtype_raw")),
            "is_fau": is_fau,
            "voorkeur_datum": _parse_datum(row.get("voorkeur_datum")),
            "voorkeur_week": week,
            "voorkeur_tijdblok": tijdblok,
            "duur_minuten": duur,
            "verlenging_minuten": bereken_verlenging(duur),
            "geschat_aantal": geschat,
            "locatie_voorkeur": gevraagde_locatie or "BRK",
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

    return aangemaakt, fouten, genegeerde_locaties


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
            e.duur_minuten as Duur_minuten,
            e.verlenging_minuten as Verlenging_minuten,
            l.naam as Locatie,
            e.locatie_voorkeur as Locatievoorkeur,
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
