from datetime import date, datetime
from database import (
    get_locatie, get_toewijzingen_voor_slot, slot_stats,
    is_examenweek, get_examens,
    SPORTHAL_GEHEEL, SPORTHAL_LINKS, SPORTHAL_RECHTS, SPORTHAL_NAMEN, AMS_AUTOPLAN,
)

# Unified ochtendblokkade (Deel C): geen examenweek-uitzondering meer.
# Maandag/dinsdag: alleen de ochtend geblokkeerd in Breukelen. Vrijdag: de hele dag.
BREUKELEN_OCHTEND_DAGEN = (0, 1)   # ma, di
BREUKELEN_HELE_DAG_DAGEN = (4,)    # vrijdag

# De drie sporthalvarianten delen één fysieke ruimte en sluiten elkaar per slot uit.
SPORTHAL_VARIANTEN = set(SPORTHAL_NAMEN)
SPORTHAL_HELFT_CAP = 175        # boven dit aantal past het niet in een helft -> Geheel

VOLLE_SPORTHAL = SPORTHAL_GEHEEL
SPORTHAL_SPREIDING_DAGEN = 14   # minimale spreiding tussen volle sporthal-bezettingen
ZWARE_SESSIE_GRENS = 250        # vanaf dit aantal telt een sessie als zwaar
TIJDBLOK_VOLGORDE = ["ochtend", "middag", "avond"]


def is_december_examenweek(datum) -> bool:
    """True als de datum in een examenweek valt die in december ligt."""
    d = date.fromisoformat(datum) if isinstance(datum, str) else datum
    return d.month == 12 and is_examenweek(d)


def _breukelen_geblokkeerd(d, tijdblok) -> bool:
    """Unified Breukelen-blokkade (Deel C): ma/di-ochtend en vrijdag (hele dag)."""
    wd = d.weekday()
    if wd in BREUKELEN_HELE_DAG_DAGEN:
        return True
    if wd in BREUKELEN_OCHTEND_DAGEN and tijdblok == "ochtend":
        return True
    return False


def _aangrenzende_tijdblokken(tijdblok: str) -> list:
    if tijdblok not in TIJDBLOK_VOLGORDE:
        return []
    i = TIJDBLOK_VOLGORDE.index(tijdblok)
    buren = []
    if i > 0:
        buren.append(TIJDBLOK_VOLGORDE[i - 1])
    if i < len(TIJDBLOK_VOLGORDE) - 1:
        buren.append(TIJDBLOK_VOLGORDE[i + 1])
    return buren


def _zware_sporthal_sessie_binnen_venster(datum_str: str, locatie):
    """
    Geeft de datum van een bestaande zware sporthal-sessie (>= ZWARE_SESSIE_GRENS
    studenten) in de hele sporthal binnen ±SPORTHAL_SPREIDING_DAGEN, of None.
    Een licht bezette sporthal telt niet mee.
    """
    if not locatie or locatie.get("naam") != VOLLE_SPORTHAL:
        return None

    from datetime import timedelta
    from database import get_conn
    d = date.fromisoformat(datum_str)
    venster_start = (d - timedelta(days=SPORTHAL_SPREIDING_DAGEN)).isoformat()
    venster_eind = (d + timedelta(days=SPORTHAL_SPREIDING_DAGEN)).isoformat()

    conn = get_conn()
    row = conn.execute("""
        SELECT s.datum, SUM(COALESCE(e.geschat_aantal, 0)) AS totaal
        FROM slots s
        JOIN locaties l ON s.locatie_id = l.id
        JOIN toewijzingen t ON t.slot_id = s.id
        JOIN examens e ON t.examen_id = e.id
        WHERE l.naam = ? AND s.datum BETWEEN ? AND ? AND s.datum != ?
        GROUP BY s.id
        HAVING totaal >= ?
        ORDER BY ABS(JULIANDAY(s.datum) - JULIANDAY(?))
        LIMIT 1
    """, (VOLLE_SPORTHAL, venster_start, venster_eind, datum_str,
          ZWARE_SESSIE_GRENS, datum_str)).fetchone()
    conn.close()
    return row["datum"] if row else None


def _sporthal_bezetting_per_variant(datum_str, tijdblok):
    """
    Per sporthalvariant in dit (datum, tijdblok): aantal geboekte examens en studenten.
    Eén query over de drie varianten, gegroepeerd op naam (geen per-rij-lus).
    """
    from database import get_conn
    namen = tuple(SPORTHAL_VARIANTEN)
    ph = ",".join("?" * len(namen))
    conn = get_conn()
    rows = conn.execute(f"""
        SELECT l.naam AS naam, COUNT(t.id) AS n_examens,
               SUM(COALESCE(e.geschat_aantal, 0)) AS studenten
        FROM slots s
        JOIN locaties l ON s.locatie_id = l.id
        JOIN toewijzingen t ON t.slot_id = s.id
        JOIN examens e ON t.examen_id = e.id
        WHERE s.datum = ? AND s.tijdblok = ? AND l.naam IN ({ph})
        GROUP BY l.naam
    """, (datum_str, tijdblok) + namen).fetchall()
    conn.close()
    return {r["naam"]: {"n_examens": r["n_examens"], "studenten": r["studenten"] or 0}
            for r in rows}


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
    naam = locatie["naam"]
    is_sporthal = naam in SPORTHAL_VARIANTEN
    is_helft = naam in (SPORTHAL_LINKS, SPORTHAL_RECHTS)

    # ── 1. CAPACITEITSCHECK ──────────────────────────────
    # Overcapaciteit is altijd een blokkade, nooit alleen een waarschuwing.
    slot_info = _get_slot_info(datum_str, tijdblok, locatie_id)
    aantal = examen.get("geschat_aantal") or 0
    cap = locatie["capaciteit"]
    bezet = slot_stats(slot_info["id"])["totaal_studenten"] if slot_info else 0
    nieuw_totaal = bezet + aantal

    # Een sporthalhelft heeft een eigen harde 175-drempel (zie sporthal-sectie); de
    # generieke capaciteitsmelding wordt daar overgeslagen om dubbele blokkades te
    # voorkomen. Geheel en gewone zalen lopen wel via de generieke check.
    if not is_helft:
        if slot_info:
            if nieuw_totaal > cap:
                blokkades.append(
                    f"Capaciteit overschreden: {nieuw_totaal} studenten > {cap} plekken. "
                    f"Huidige bezetting: {bezet}, examen vraagt {aantal}."
                )
        else:
            if aantal > cap:
                blokkades.append(
                    f"Examen ({aantal} studenten) past niet in {naam} "
                    f"(max {cap}). Overweeg splitsing naar programmagroepen."
                )

    # 90%-waarschuwing: één melding, geldt voor zowel nieuwe als bestaande slots.
    if cap and cap * 0.9 < nieuw_totaal <= cap:
        waarschuwingen.append(
            f"Dit slot komt op {nieuw_totaal} van {cap} studenten "
            f"({round(nieuw_totaal/cap*100)}%). Het maximum wordt bijna bereikt."
        )

    # ── 1a. MAX AANTAL EXAMENS PER SLOT (hard) ───────────
    max_examens = locatie.get("max_examens_per_slot") or 0
    if max_examens:
        reeds = slot_stats(slot_info["id"])["n_examens"] if slot_info else 0
        if reeds + 1 > max_examens:
            blokkades.append(
                f"Maximaal {max_examens} examens per slot in {naam}. "
                f"Dit slot heeft er al {reeds}."
            )

    # ── 1b. SPORTHAL LINKS/RECHTS/GEHEEL (hard) ──────────
    # De drie varianten delen één fysieke ruimte:
    #  - wederzijdse uitsluiting: er mag per slot maar één variant in gebruik zijn;
    #  - een helft (Links/Rechts) is hard begrensd op 175 studenten -> anders Geheel.
    if is_sporthal:
        bez = _sporthal_bezetting_per_variant(datum_str, tijdblok)
        conflict = next((andere for andere, info in bez.items()
                         if andere != naam and info["n_examens"] > 0), None)
        if conflict:
            blokkades.append(
                f"{naam} kan niet: {conflict} is al in gebruik in dit tijdblok. "
                f"De sporthalvarianten (Geheel/Links/Rechts) sluiten elkaar uit."
            )
        if is_helft and nieuw_totaal > SPORTHAL_HELFT_CAP:
            blokkades.append(
                f"Meer dan {SPORTHAL_HELFT_CAP} studenten in de sporthal "
                f"({nieuw_totaal}): gebruik Sporthal Geheel."
            )

    # ── 1c. BEZETTINGSSPREIDING (zacht) ──────────────────
    # Beide checks gelden alleen voor zware sessies en zijn adviserend. Ze worden
    # onderdrukt in een december-examenweek, waarin piek nu eenmaal onvermijdelijk is.
    if nieuw_totaal >= ZWARE_SESSIE_GRENS and not is_december_examenweek(d):
        vorige = _zware_sporthal_sessie_binnen_venster(datum_str, locatie)
        if vorige:
            waarschuwingen.append(
                f"Er staat al een zware sporthal-sessie (250+ studenten) binnen "
                f"{SPORTHAL_SPREIDING_DAGEN} dagen op {vorige}. Overweeg spreiding."
            )

        for buur in _aangrenzende_tijdblokken(tijdblok):
            buur_slot = _get_slot_info(datum_str, buur, locatie_id)
            if not buur_slot:
                continue
            if slot_stats(buur_slot["id"])["totaal_studenten"] >= ZWARE_SESSIE_GRENS:
                waarschuwingen.append(
                    "Twee opeenvolgende sessies met 250+ studenten op dezelfde dag. "
                    "Dit is zwaar voor de surveillanten."
                )
                break

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

    # ── 3. OCHTEND-/DAGBLOKKADE BREUKELEN (unified, Deel C) ──
    # Hele jaar door, geen examenweek-uitzondering meer: maandag- en dinsdagochtend
    # zijn geblokkeerd, en vrijdag de hele dag. Alleen KAN_OVERRULEN (override) passeert.
    # Amsterdam valt hier volledig buiten.
    if locatie and locatie["campus"] == "Breukelen" and _breukelen_geblokkeerd(d, tijdblok):
        wd = d.weekday()
        wanneer = "vrijdag (hele dag)" if wd in BREUKELEN_HELE_DAG_DAGEN else \
                  ("maandagochtend" if wd == 0 else "dinsdagochtend")
        if not override:
            blokkades.append(
                f"{d.strftime('%d %B %Y')} — {wanneer} is in Breukelen geblokkeerd. "
                f"Alleen met override (Head of Operations) te plannen."
            )
        else:
            waarschuwingen.append(
                f"Override actief: blokkade ({wanneer}) genegeerd voor {d.strftime('%d %B %Y')}."
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
    # Een klein examen (≤175) in Geheel kan beter in een helft; Rechts heeft voorrang.
    halve_zaal_suggestie = False
    if naam == SPORTHAL_GEHEEL and (examen.get("geschat_aantal") or 0) <= SPORTHAL_HELFT_CAP:
        halve_zaal_suggestie = True
        waarschuwingen.append(
            f"Dit examen heeft {examen.get('geschat_aantal')} studenten (≤{SPORTHAL_HELFT_CAP}). "
            f"Overweeg {SPORTHAL_RECHTS} te boeken zodat de rest van de sporthal vrij blijft."
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

    Auto-plan mag alleen op de drie sporthalvarianten en Amsterdam 1.06/1.07. Alle
    overige zalen blijven beschikbaar voor HANDMATIG plannen — hun reserveringen lopen
    via Facilitor en worden hier bewust overgeslagen. Rechts krijgt voorrang boven Links;
    Geheel vangt grote groepen (>175) op; de mutual-exclusion in check_alle_constraints
    voorkomt dat twee sporthalvarianten in hetzelfde slot geboekt worden.
    """
    from database import get_locaties, get_or_create_slot, plan_examen
    from datetime import timedelta

    ongepland = get_ongeplande_examens_sorted()
    # Auto-plan kiest zelf een zaal en mag daarbij geen inactieve zaal pakken.
    per_naam = {l["naam"]: l for l in get_locaties(alleen_actief=True)}
    volgorde = [SPORTHAL_RECHTS, SPORTHAL_LINKS, SPORTHAL_GEHEEL, AMS_AUTOPLAN]
    auto_locaties = [per_naam[n] for n in volgorde if n in per_naam]

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
                for locatie in auto_locaties:
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


# ── FRAGMENTATIE-DETECTOR (Deel D, fase 1) ────────────────
#
# Signaleert dat examens versnipperd over een week staan terwijl ze binnen de harde
# regels samengevoegd kunnen worden ("de sporthal staat de hele week maar deels vol").
# ALLEEN signaleren: elk voorstel is advies; de planner voert het handmatig uit via de
# bestaande planningsfunctie. Er is bewust GEEN goedkeuringsworkflow (dat is fase 2).
#
# Heuristiek (per ISO-week, per consolidatiegroep):
#  - een groep is één fysieke ruimte binnen een week: de drie sporthalvarianten samen
#    (zelfde campus) tellen als één ruimte, een gewone zaal als zichzelf;
#  - alleen LAAG BEZETTE slots doen mee (studenten <= drempel * referentiecapaciteit;
#    de sporthal wordt afgezet tegen Geheel = 350, een gewone zaal tegen haar eigen cap);
#  - lukt het om ALLE examens van de groep in ÉÉN doelslot te schuiven zonder enige
#    harde constraint te schenden, dan is dat het voorstel (many->1: de sterkste vorm
#    van "in minder slots"); anders geen voorstel voor die groep (fase 1 is bewust
#    conservatief). Groepen met een FAU-examen worden overgeslagen.
#
# De drempel is instelbaar zodat Marielle hem later op basis van ervaring kan bijstellen.
LAGE_BEZETTING_DREMPEL = 0.5          # slot <= 50% van de referentiecapaciteit = laag bezet
SPORTHAL_REF_CAPACITEIT = 350         # Geheel; referentie voor "laag bezet" in de sporthal


def _iso_week(datum_str):
    y, w, _ = date.fromisoformat(datum_str).isocalendar()
    return (y, w)


def _consolidatie_sleutel(loc):
    """De drie sporthalvarianten (per campus) delen één ruimte; gewone zalen staan op zich."""
    if loc.get("naam") in SPORTHAL_VARIANTEN:
        return ("SPORTHAL", loc.get("campus"))
    return ("ZAAL", loc.get("id"))


def _samenvoeging_hard_ok(examens, target_loc, datum, tijdblok, index, negeer_slot_ids):
    """
    True als de gegeven set examens samen in (datum, tijdblok, target_loc) past zonder
    enige harde constraint te schenden. Rekent volledig uit de in-memory `index` (geen
    query): capaciteit (incl. 175-drempel voor een helft), max examens per slot,
    Breukelen-dagblokkade, FAU-isolatie en de sporthal-uitsluiting. De bronslots die
    leeggehaald worden (negeer_slot_ids) tellen niet mee bij de dag-/slotcontrole.
    Geeft (ok, redenen) terug.
    """
    redenen = []
    naam = target_loc.get("naam")
    campus = target_loc.get("campus")
    is_sporthal = naam in SPORTHAL_VARIANTEN
    is_helft = naam in (SPORTHAL_LINKS, SPORTHAL_RECHTS)

    # 1. Capaciteit (een helft is hard begrensd op 175).
    cap = target_loc.get("capaciteit") or 0
    if is_helft:
        cap = min(cap, SPORTHAL_HELFT_CAP)
    totaal = sum((e.get("geschat_aantal") or 0) for e in examens)
    if cap and totaal > cap:
        redenen.append(f"capaciteit overschreden ({totaal} > {cap})")

    # 2. Max examens per slot.
    max_ex = target_loc.get("max_examens_per_slot") or 0
    if max_ex and len(examens) > max_ex:
        redenen.append(f"te veel examens ({len(examens)} > {max_ex})")

    # 3. Breukelen-dagblokkade (geen override in de detector).
    if campus == "Breukelen" and _breukelen_geblokkeerd(date.fromisoformat(datum), tijdblok):
        redenen.append("Breukelen-dagblokkade")

    # 4. FAU-isolatie. Fase 1 stelt niets voor met een FAU-examen in de set; daarnaast
    #    mag het doel niet op een dag vallen waar (buiten de bronslots) al een FAU staat.
    if any(e.get("is_fau") for e in examens):
        redenen.append("set bevat een FAU-examen")
    elif campus == "Breukelen":
        for sid, s in index["slot_by_id"].items():
            if sid in negeer_slot_ids or s["datum"] != datum:
                continue
            loc = index["loc_by_id"].get(s["locatie_id"], {})
            if loc.get("campus") != "Breukelen":
                continue
            if any(r.get("is_fau") for r in index["exams_by_slot"].get(sid, [])):
                redenen.append("FAU-examen elders in Breukelen op deze dag")
                break

    # 5. Sporthal-uitsluiting: geen ANDERE variant met examens in ditzelfde tijdblok.
    if is_sporthal:
        for sid, s in index["slot_by_id"].items():
            if sid in negeer_slot_ids:
                continue
            if s["datum"] != datum or s["tijdblok"] != tijdblok:
                continue
            loc = index["loc_by_id"].get(s["locatie_id"], {})
            if loc.get("naam") in SPORTHAL_VARIANTEN and loc.get("naam") != naam:
                if index["exams_by_slot"].get(sid):
                    redenen.append(f"andere sporthalvariant ({loc.get('naam')}) is bezet")
                    break

    return (len(redenen) == 0, redenen)


def _bouw_consolidatie(week, sleutel, leden, index):
    """Bouwt één many->1 consolidatievoorstel voor een groep laag bezette slots, of None."""
    # Doelzaal: voor de sporthal altijd Geheel (max capaciteit); anders de zaal zelf.
    if sleutel[0] == "SPORTHAL":
        target_loc = next((l for l in index["loc_by_id"].values()
                           if l.get("naam") == SPORTHAL_GEHEEL and l.get("campus") == sleutel[1]), None)
    else:
        target_loc = index["loc_by_id"].get(sleutel[1])
    if not target_loc:
        return None

    alle_examens = [r for b in leden for r in b["rows"]]
    bron_slot_ids = {b["slot"]["id"] for b in leden}

    # Probeer een bestaand slot als doel; het slot met de meeste studenten eerst (anker),
    # zodat de grootste groep zo mogelijk blijft staan.
    for anker in sorted(leden, key=lambda b: -b["studenten"]):
        datum = anker["slot"]["datum"]
        tijdblok = anker["slot"]["tijdblok"]
        ok, _redenen = _samenvoeging_hard_ok(
            alle_examens, target_loc, datum, tijdblok, index, bron_slot_ids)
        if not ok:
            continue

        verplaatsingen = []
        for b in leden:
            zelfde_doel = (b["slot"]["datum"] == datum
                           and b["slot"]["tijdblok"] == tijdblok
                           and b["slot"]["locatie_id"] == target_loc["id"])
            if zelfde_doel:
                continue
            for r in b["rows"]:
                verplaatsingen.append({
                    "examen_id": r["examen_id"],
                    "naam": r.get("naam"),
                    "geschat_aantal": r.get("geschat_aantal") or 0,
                    "van_slot_id": b["slot"]["id"],
                    "van_datum": b["slot"]["datum"],
                    "van_tijdblok": b["slot"]["tijdblok"],
                    "van_locatie": index["loc_by_id"].get(b["slot"]["locatie_id"], {}).get("naam"),
                })

        vrijgekomen = len(bron_slot_ids) - 1
        if vrijgekomen < 1 or not verplaatsingen:
            return None

        totaal = sum((e.get("geschat_aantal") or 0) for e in alle_examens)
        return {
            "week": week,
            "campus": target_loc.get("campus"),
            "doel": {
                "datum": datum,
                "tijdblok": tijdblok,
                "locatie_id": target_loc["id"],
                "locatie_naam": target_loc.get("naam"),
            },
            "verplaatsingen": verplaatsingen,
            "vrijgekomen_slots": vrijgekomen,
            "aantal_examens": len(alle_examens),
            "totaal_studenten": totaal,
            "toelichting": (
                f"{len(alle_examens)} examens ({totaal} studenten) uit "
                f"{len(bron_slot_ids)} losse slots passen samen in "
                f"{target_loc.get('naam')} op {datum} ({tijdblok}); "
                f"dat maakt {vrijgekomen} slot(s) vrij."
            ),
        }
    return None


def vind_fragmentatie_voorstellen(jaar, maand, drempel=LAGE_BEZETTING_DREMPEL):
    """
    Zoekt binnen een kalendermaand naar samenvoegbare, laag bezette slots (zie de
    module-toelichting hierboven). Geeft een lijst consolidatievoorstellen terug;
    schrijft niets weg. Twee queries (slots + toewijzingen), de rest in-memory.
    """
    from database import get_slots_for_month, get_toewijzingen_voor_maand, get_locaties

    slots = get_slots_for_month(jaar, maand)
    tw_per_slot = get_toewijzingen_voor_maand(jaar, maand)
    loc_by_id = {l["id"]: l for l in get_locaties()}
    slot_by_id = {s["id"]: s for s in slots}
    index = {"slot_by_id": slot_by_id, "exams_by_slot": tw_per_slot, "loc_by_id": loc_by_id}

    # Groepeer laag bezette, bezette slots per (ISO-week, consolidatiegroep).
    groepen = {}
    for s in slots:
        rows = tw_per_slot.get(s["id"])
        if not rows:
            continue
        loc = loc_by_id.get(s["locatie_id"], {})
        studenten = sum((r.get("geschat_aantal") or 0) for r in rows)
        ref_cap = (SPORTHAL_REF_CAPACITEIT if loc.get("naam") in SPORTHAL_VARIANTEN
                   else (loc.get("capaciteit") or 0))
        if not ref_cap or studenten > drempel * ref_cap:
            continue
        if any(r.get("is_fau") for r in rows):   # FAU-slots blijven buiten fase 1
            continue
        key = (_iso_week(s["datum"]), _consolidatie_sleutel(loc))
        groepen.setdefault(key, []).append(
            {"slot": s, "rows": rows, "studenten": studenten})

    voorstellen = []
    for (week, sleutel), leden in groepen.items():
        if len(leden) < 2:
            continue
        v = _bouw_consolidatie(week, sleutel, leden, index)
        if v:
            voorstellen.append(v)

    # Meeste winst (vrijgekomen slots) eerst.
    voorstellen.sort(key=lambda v: (-v["vrijgekomen_slots"], v["week"], v["doel"]["datum"]))
    return voorstellen
