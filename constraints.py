from datetime import date, datetime
from database import (
    get_locatie, get_toewijzingen_voor_slot, slot_stats,
    is_examenweek, get_examens
)

OCHTEND_BLOK_DAGEN = [0, 1, 4]  # maandag=0, dinsdag=1, vrijdag=4

# Locaties met deze naamprefix zijn varianten van dezelfde fysieke zaal.
GEDEELDE_ZAAL_PREFIX = "Sporthal Breukelen"


def _zaalgroep_locaties(locatie) -> list:
    """Locaties die fysiek dezelfde zaal delen als `locatie`. Leeg als er geen overlap is."""
    if not locatie or not str(locatie.get("naam", "")).startswith(GEDEELDE_ZAAL_PREFIX):
        return []
    from database import get_locaties
    return [l for l in get_locaties()
            if str(l["naam"]).startswith(GEDEELDE_ZAAL_PREFIX)]


def check_alle_constraints(examen: dict, datum_str: str, tijdblok: str,
                            locatie_id: int, override: bool = False) -> dict:
    """
    Voer alle constraint-checks uit.
    Geeft terug: {"ok": bool, "blokkades": [...], "waarschuwingen": [...]}
    """
    blokkades = []
    waarschuwingen = []
    d = date.fromisoformat(datum_str)
    locatie = get_locatie(locatie_id)

    # ── 1. CAPACITEITSCHECK ──────────────────────────────
    # Overcapaciteit is altijd een blokkade, nooit alleen een waarschuwing.
    slot_info = _get_slot_info(datum_str, tijdblok, locatie_id)
    aantal = examen.get("geschat_aantal") or 0
    cap = locatie["capaciteit"]
    bezet = slot_stats(slot_info["id"])["totaal_studenten"] if slot_info else 0
    nieuw_totaal = bezet + aantal

    if slot_info:
        if nieuw_totaal > cap:
            blokkades.append(
                f"Capaciteit overschreden: {nieuw_totaal} studenten > {cap} plekken. "
                f"Huidige bezetting: {bezet}, examen vraagt {aantal}."
            )
        elif nieuw_totaal > cap * 0.9:
            waarschuwingen.append(
                f"Slot is {round(nieuw_totaal/cap*100)}% vol na plaatsing ({nieuw_totaal}/{cap})."
            )
    else:
        # Nieuw slot
        if aantal > cap:
            blokkades.append(
                f"Examen ({aantal} studenten) past niet in {locatie['naam']} "
                f"(max {cap}). Overweeg splitsing naar programmagroepen."
            )

    # Hele en halve sporthal zijn aparte locatierijen maar dezelfde fysieke ruimte:
    # los geteld passen ze allebei, samen niet.
    groep = _zaalgroep_locaties(locatie)
    if groep:
        bezet_andere_helft = sum(
            slot_stats(si["id"])["totaal_studenten"]
            for l in groep if l["id"] != locatie_id
            for si in [_get_slot_info(datum_str, tijdblok, l["id"])] if si
        )
        if bezet_andere_helft:
            fysieke_cap = max(l["capaciteit"] for l in groep)
            zaal_totaal = nieuw_totaal + bezet_andere_helft
            if zaal_totaal > fysieke_cap:
                blokkades.append(
                    f"Sporthal Breukelen overboekt: {zaal_totaal} studenten > {fysieke_cap} plekken. "
                    f"De hele en halve zaal delen dezelfde ruimte; {bezet_andere_helft} studenten "
                    f"staan al geboekt in een overlappend deel op dit tijdblok."
                )

    # ── 2. FAU-ISOLATIECHECK ─────────────────────────────
    if examen.get("is_fau"):
        # FAU mag alleen als er geen andere examens die dag in Breukelen zijn
        if locatie and locatie["campus"] == "Breukelen":
            andere = _examens_op_dag_campus(datum_str, "Breukelen", uitgezonderd_examen=examen.get("id"))
            if andere:
                blokkades.append(
                    f"FAU-tentamen: op {datum_str} zijn al andere examens gepland in Breukelen. "
                    f"FAU neemt de hele dag in beslag."
                )
    else:
        # Controleer of er al een FAU gepland staat op deze dag in Breukelen
        if locatie and locatie["campus"] == "Breukelen":
            fau_dag = _fau_gepland_op_dag(datum_str, "Breukelen")
            if fau_dag:
                blokkades.append(
                    f"Op {datum_str} staat al een FAU-tentamen gepland in Breukelen. "
                    f"Geen andere examens toegestaan op deze dag in Breukelen."
                )

    # ── 3. OCHTENDBLOK ───────────────────────────────────
    if tijdblok == "ochtend" and locatie and locatie["campus"] == "Breukelen":
        dag_van_week = d.weekday()
        if dag_van_week in OCHTEND_BLOK_DAGEN:
            if not is_examenweek(d):
                if not override:
                    blokkades.append(
                        f"{d.strftime('%A %d %B')} is een {'maandag' if dag_van_week==0 else 'dinsdag' if dag_van_week==1 else 'vrijdag'}-ochtend. "
                        f"De sporthal is niet beschikbaar (geen examenweek). "
                        f"Markeer als override als je dit toch wilt plannen."
                    )
                else:
                    waarschuwingen.append(
                        f"Override actief: ochtend-blokkering genegeerd voor {d.strftime('%A %d %B')}."
                    )

    # ── 4. GEEN SPLITSING ────────────────────────────────
    # Al afgedekt in capaciteitscheck – examen moet volledig passen

    # ── 5. HS-WAARSCHUWING ───────────────────────────────
    if slot_info:
        stats = slot_stats(slot_info["id"])
        n_na_plaatsing = stats["n_examens"] + 1
        hs_nodig = -(-n_na_plaatsing // 2)
        if hs_nodig > 3:
            waarschuwingen.append(
                f"Na plaatsing zijn {hs_nodig} hoofdsurveillanten nodig ({n_na_plaatsing} examens). "
                f"Controleer beschikbaarheid."
            )

    # ── 6. HALVE ZAAL SUGGESTIE ──────────────────────────
    halve_zaal_suggestie = False
    if locatie and locatie["naam"] == "Sporthal Breukelen (heel)":
        if (examen.get("geschat_aantal") or 0) <= 175:
            halve_zaal_suggestie = True
            waarschuwingen.append(
                f"Dit examen heeft {examen.get('geschat_aantal')} studenten (≤175). "
                f"Overweeg halve sporthal te boeken zodat de andere helft beschikbaar blijft."
            )

    ok = len(blokkades) == 0
    return {
        "ok": ok,
        "blokkades": blokkades,
        "waarschuwingen": waarschuwingen,
        "halve_zaal_suggestie": halve_zaal_suggestie,
    }


def _get_slot_info(datum_str, tijdblok, locatie_id):
    from database import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM slots WHERE datum=? AND tijdblok=? AND locatie_id=?",
        (datum_str, tijdblok, locatie_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _examens_op_dag_campus(datum_str: str, campus: str, uitgezonderd_examen=None) -> list:
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.naam FROM toewijzingen t
        JOIN slots s ON t.slot_id = s.id
        JOIN locaties l ON s.locatie_id = l.id
        JOIN examens e ON t.examen_id = e.id
        WHERE s.datum = ? AND l.campus = ?
    """, (datum_str, campus)).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    if uitgezonderd_examen:
        result = [r for r in result if r.get("id") != uitgezonderd_examen]
    return result


def _fau_gepland_op_dag(datum_str: str, campus: str) -> bool:
    from database import get_conn
    conn = get_conn()
    row = conn.execute("""
        SELECT COUNT(*) as n FROM toewijzingen t
        JOIN slots s ON t.slot_id = s.id
        JOIN locaties l ON s.locatie_id = l.id
        JOIN examens e ON t.examen_id = e.id
        WHERE s.datum = ? AND l.campus = ? AND e.is_fau = 1
    """, (datum_str, campus)).fetchone()
    conn.close()
    return row["n"] > 0


def auto_plan(aangemeld_door: str = "Auto-plan") -> dict:
    """
    Greedy planningsalgoritme:
    - Sorteer examens op geschat_aantal desc
    - Probeer elk examen in het vroegste beschikbare slot
    - Alleen middag- en avondslots (tenzij examenweek)
    """
    from database import get_examens, get_locaties, get_or_create_slot, plan_examen, get_conn
    import calendar as cal_module
    from datetime import timedelta

    ongepland = get_ongeplande_examens_sorted()
    locaties = get_locaties()
    brk_heel = next((l for l in locaties if "heel" in l["naam"].lower()), None)
    ams = next((l for l in locaties if "Amsterdam" in l["naam"]), None)

    gepland = 0
    niet_gepland = []
    vandaag = date.today()

    for examen in ongepland:
        geplaatst = False
        # Probeer de komende 180 dagen
        for delta in range(180):
            d = vandaag + timedelta(days=delta)
            datum_str = d.isoformat()

            for tijdblok in ["middag", "avond", "ochtend"]:
                for locatie in [brk_heel, ams]:
                    if not locatie:
                        continue
                    result = check_alle_constraints(examen, datum_str, tijdblok, locatie["id"])
                    if result["ok"]:
                        slot = get_or_create_slot(datum_str, tijdblok, locatie["id"])
                        plan_examen(examen["id"], slot["id"], aangemeld_door)
                        gepland += 1
                        geplaatst = True
                        break
                if geplaatst:
                    break
            if geplaatst:
                break

        if not geplaatst:
            niet_gepland.append(examen["naam"])

    return {"gepland": gepland, "niet_gepland": niet_gepland}


def get_ongeplande_examens_sorted():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.* FROM examens e
        WHERE e.status IN ('ingediend','gepland')
        AND e.id NOT IN (SELECT examen_id FROM toewijzingen)
        ORDER BY e.geschat_aantal DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
