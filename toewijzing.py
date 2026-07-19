"""
Automatische surveillanttoewijzing (ronde 3, deel 2).

Bouwt voort op de contract- en urengegevens uit deel 1. Alle publieke functies
geven een VOORSTEL terug; wegschrijven gebeurt alleen bij uitvoeren=True en loopt
via wijs_surveillant_toe(), zodat de urenlog uit deel 1 automatisch meeklopt.

Handmatige overschrijving gaat altijd vóór de automatische bepaling — dat principe
geldt voor het hele traject (maandprofiel én de toewijzing zelf blijven adviserend).
"""
from math import ceil

from database import (
    get_slot, get_toewijzingen_voor_slot, slot_stats,
    get_surv_toewijzingen_voor_slot, get_beschikbare_surveillanten_voor_slot,
    get_studenten_per_maand, get_maandprofiel_handmatig,
    get_uren_per_maand, get_uren_totaal, tel_beschikbare_slots_in_jaar,
    is_geblokkeerd_in_periode, bepaal_academisch_jaar,
    wijs_surveillant_toe, get_slots_for_month, get_locatie,
)

# Scoreparameters (zie STAP C/D van de opdracht).
FTE_BASIS = 1000          # tilt elke FT'er boven elk nul-urencontract
# Straf > FTE_BASIS, zodat een geblokkeerde FTE'er onder een vrije nul-urenkracht zakt:
# een opgegeven vakantieperiode weegt zwaarder dan het contracttype. De kandidaat
# blijft wel scoorbaar en komt alsnog in beeld als er geen alternatief is.
BLOKKADE_STRAF = 1500     # aftrek bij een adviserende periode-blokkade
STUDENTEN_PER_SURV = 50   # 1 surveillant per 50 studenten
PIEK_DREMPEL = 1.5        # maandfactor > 1.5x gemiddelde = piek
DAL_DREMPEL = 0.5         # maandfactor < 0.5x gemiddelde = dal


# ── MAANDPROFIEL ──────────────────────────────────────────

def bepaal_maandprofiel(academisch_jaar):
    """
    Per maand een categorie op basis van het totaal aantal studenten in de geplande
    examens. Handmatige regels (maandprofiel_handmatig) overschrijven de categorie.

    Geeft: dict 'YYYY-MM' -> {"categorie", "studenten", "factor", "handmatig"}.
    """
    studenten = get_studenten_per_maand(academisch_jaar)
    handmatig = get_maandprofiel_handmatig(academisch_jaar)

    gemiddelde = (sum(studenten.values()) / len(studenten)) if studenten else 0

    profiel = {}
    for maand, n in studenten.items():
        factor = (n / gemiddelde) if gemiddelde else 0.0
        if factor > PIEK_DREMPEL:
            auto = "piek"
        elif factor < DAL_DREMPEL:
            auto = "dal"
        else:
            auto = "normaal"
        profiel[maand] = {
            "categorie": handmatig.get(maand, auto),
            "auto_categorie": auto,
            "studenten": n,
            "factor": round(factor, 2),
            "handmatig": maand in handmatig,
        }

    # Handmatige regels voor maanden zonder examens blijven zichtbaar.
    for maand, cat in handmatig.items():
        if maand not in profiel:
            profiel[maand] = {
                "categorie": cat, "auto_categorie": None,
                "studenten": 0, "factor": 0.0, "handmatig": True,
            }
    return profiel


def _verwacht_saldo(jaardoel, slot_maand, profiel):
    """
    Het deel van het jaardoel dat op deze maand behaald zou moeten zijn, gewogen
    naar de maandfactor: piekmaanden tellen zwaarder, dalmaanden lichter.
    Maandstrings ('YYYY-MM') sorteren chronologisch én in academisch-jaar-volgorde.
    """
    if not profiel or not jaardoel:
        return 0.0
    totaal_gewicht = sum(m["factor"] for m in profiel.values())
    if totaal_gewicht <= 0:
        return 0.0
    cumulatief = sum(m["factor"] for maand, m in profiel.items() if maand <= slot_maand)
    return jaardoel * (cumulatief / totaal_gewicht)


# ── SCORE PER KANDIDAAT ───────────────────────────────────

def _scoor_kandidaat(surv, slot_maand, academisch_jaar, profiel, datum):
    """Bouwt het kandidaat-record met score, achterstand en blokkade-status."""
    sid = surv["id"]
    contract = surv.get("contract_type") or "nul-uren"
    geblokkeerd = is_geblokkeerd_in_periode(sid, datum)

    achterstand = None
    if contract == "FTE":
        jaardoel = surv.get("jaardoel_uren") or 0.0
        maanden = get_uren_per_maand(sid, academisch_jaar)
        gedraaid_tot = round(sum(u for m, u in maanden.items() if m <= slot_maand), 1)
        verwacht = _verwacht_saldo(jaardoel, slot_maand, profiel)
        achterstand = round(verwacht - gedraaid_tot, 1)
        score = FTE_BASIS + achterstand
        gedraaid_jaar = get_uren_totaal(sid, academisch_jaar)
        reden = f"FTE, achterstand {achterstand:+.1f} u"
    else:
        gedraaid_jaar = get_uren_totaal(sid, academisch_jaar)
        score = -1.0 * gedraaid_jaar
        reden = f"nul-uren, {gedraaid_jaar:.1f} u gedraaid dit jaar"

    if geblokkeerd:
        score -= BLOKKADE_STRAF
        reden += " — LET OP: periode-blokkade"

    return {
        "surveillant_id": sid,
        "naam": surv["naam"],
        "contract_type": contract,
        "mag_hs": (surv.get("rol_voorkeur") == "HS"),
        "score": round(score, 1),
        "achterstand": achterstand,
        "gedraaide_uren": round(gedraaid_jaar, 1),
        "beschikbare_slots": tel_beschikbare_slots_in_jaar(sid, academisch_jaar),
        "geblokkeerd": geblokkeerd,
        "reden": reden,
    }


def _sorteersleutel(k):
    # Hoogste score eerst; bij gelijke stand wie meer beschikbaarheid opgaf; dan naam.
    return (-k["score"], -k["beschikbare_slots"], k["naam"])


# ── HET ALGORITME ─────────────────────────────────────────

def wijs_automatisch_toe(slot_id, uitvoeren=False):
    """
    Bouwt een toewijzingsvoorstel voor één slot. Bij uitvoeren=True worden de
    voorgestelde toewijzingen ook echt weggeschreven via wijs_surveillant_toe().
    """
    slot = get_slot(slot_id)
    if not slot:
        return {"slot_id": slot_id, "fout": "Slot bestaat niet."}

    datum = slot["datum"]
    slot_maand = datum[:7]
    academisch_jaar = bepaal_academisch_jaar(datum)
    profiel = bepaal_maandprofiel(academisch_jaar)

    # STAP A — behoefte.
    stats = slot_stats(slot_id)
    hs_nodig = ceil(stats["n_examens"] / 2) if stats["n_examens"] else 0
    surv_nodig = ceil(stats["totaal_studenten"] / STUDENTEN_PER_SURV) if stats["totaal_studenten"] else 0

    # Reeds (handmatig) toegewezen personen tellen mee en worden overgeslagen.
    reeds = get_surv_toewijzingen_voor_slot(slot_id)
    reeds_ids = {r["surveillant_id"] for r in reeds}
    al_hs = sum(1 for r in reeds if r["rol"] == "Hoofdsurveillant")
    al_s = sum(1 for r in reeds if r["rol"] == "Surveillant")
    hs_te_vullen = max(0, hs_nodig - al_hs)
    s_te_vullen = max(0, surv_nodig - al_s)

    # STAP B — kandidaten.
    beschikbaar = [s for s in get_beschikbare_surveillanten_voor_slot(slot_id)
                   if s["id"] not in reeds_ids]
    kandidaten = [_scoor_kandidaat(s, slot_maand, academisch_jaar, profiel, datum)
                  for s in beschikbaar]

    # STAP E — vullen. Eerst HS uit wie HS mag, daarna S uit de rest (incl. HS'ers).
    gekozen_ids = set()
    toewijzingen = []

    hs_kandidaten = sorted([k for k in kandidaten if k["mag_hs"]], key=_sorteersleutel)
    for k in hs_kandidaten:
        if len([t for t in toewijzingen if t["rol"] == "Hoofdsurveillant"]) >= hs_te_vullen:
            break
        toewijzingen.append(_maak_toewijzing(k, "Hoofdsurveillant"))
        gekozen_ids.add(k["surveillant_id"])

    rest = sorted([k for k in kandidaten if k["surveillant_id"] not in gekozen_ids],
                  key=_sorteersleutel)
    for k in rest:
        if len([t for t in toewijzingen if t["rol"] == "Surveillant"]) >= s_te_vullen:
            break
        toewijzingen.append(_maak_toewijzing(k, "Surveillant"))
        gekozen_ids.add(k["surveillant_id"])

    # STAP F — tekorten en waarschuwingen.
    geplaatst_hs = len([t for t in toewijzingen if t["rol"] == "Hoofdsurveillant"])
    geplaatst_s = len([t for t in toewijzingen if t["rol"] == "Surveillant"])
    tekorten = []
    if hs_te_vullen - geplaatst_hs > 0:
        tekorten.append({"rol": "Hoofdsurveillant", "aantal": hs_te_vullen - geplaatst_hs})
    if s_te_vullen - geplaatst_s > 0:
        tekorten.append({"rol": "Surveillant", "aantal": s_te_vullen - geplaatst_s})

    waarschuwingen = []
    for t in toewijzingen:
        if t["geblokkeerd"]:
            waarschuwingen.append(
                f"{t['naam']} is voorgesteld ondanks een periode-blokkade op {datum}.")
    for tk in tekorten:
        waarschuwingen.append(
            f"Tekort van {tk['aantal']} {tk['rol'].lower()}(en): niet genoeg beschikbare kandidaten.")

    if uitvoeren:
        for t in toewijzingen:
            wijs_surveillant_toe(slot_id, t["surveillant_id"], t["rol"], "Auto-toewijzing")

    return {
        "slot_id": slot_id,
        "datum": datum,
        "tijdblok": slot["tijdblok"],
        "locatie_id": slot["locatie_id"],
        "hs_nodig": hs_nodig,
        "surv_nodig": surv_nodig,
        "reeds_toegewezen": {"HS": al_hs, "S": al_s},
        "toewijzingen": toewijzingen,
        "tekorten": tekorten,
        "waarschuwingen": waarschuwingen,
        "uitgevoerd": uitvoeren,
    }


def _maak_toewijzing(kandidaat, rol):
    return {
        "surveillant_id": kandidaat["surveillant_id"],
        "naam": kandidaat["naam"],
        "rol": rol,
        "contract_type": kandidaat["contract_type"],
        "score": kandidaat["score"],
        "achterstand": kandidaat["achterstand"],
        "gedraaide_uren": kandidaat["gedraaide_uren"],
        "geblokkeerd": kandidaat["geblokkeerd"],
        "reden": kandidaat["reden"],
    }


# ── MAANDVOORSTEL (kalenderknop) ──────────────────────────

def voorstel_voor_maand(jaar, maand, uitvoeren=False):
    """
    Maakt (of voert uit) een voorstel voor alle slots met examens in de kalendermaand.
    Geeft een aggregaat plus de losse voorstellen terug.
    """
    slots = get_slots_for_month(jaar, maand)
    slots_met = [s for s in slots if get_toewijzingen_voor_slot(s["id"])]

    voorstellen = []
    volledig = 0
    met_tekort = 0
    for s in slots_met:
        v = wijs_automatisch_toe(s["id"], uitvoeren=uitvoeren)
        voorstellen.append(v)
        if v.get("tekorten"):
            met_tekort += 1
        else:
            volledig += 1

    return {
        "jaar": jaar,
        "maand": maand,
        "totaal_slots": len(slots_met),
        "volledig_gevuld": volledig,
        "met_tekort": met_tekort,
        "voorstellen": voorstellen,
        "uitgevoerd": uitvoeren,
    }


# ── MAILTEKST BIJ TEKORT ──────────────────────────────────

TOETSBUREAU_EMAIL = "toetsbureau@nyenrode.nl"


def genereer_tekort_mail(voorstel):
    """
    Kant-en-klare mailtekst voor het toetsbureau bij een tekort of bij inzet van een
    geblokkeerde surveillant. Geeft None als er niets te melden is.
    """
    heeft_tekort = bool(voorstel.get("tekorten"))
    geblokkeerd_ingezet = [t for t in voorstel.get("toewijzingen", []) if t["geblokkeerd"]]
    if not heeft_tekort and not geblokkeerd_ingezet:
        return None

    loc = get_locatie(voorstel.get("locatie_id")) or {}
    tw = get_toewijzingen_voor_slot(voorstel["slot_id"])
    examens = ", ".join(t["naam"] for t in tw) or "(geen examens gevonden)"

    regels = [
        f"Aan: {TOETSBUREAU_EMAIL}",
        f"Onderwerp: Surveillance-tekort {voorstel['datum']} ({voorstel['tijdblok']})",
        "",
        "Beste toetsbureau,",
        "",
        f"Voor het volgende tentamenmoment lukt het niet om de surveillance volledig rond te krijgen:",
        "",
        f"  Datum:    {voorstel['datum']}",
        f"  Tijdblok: {voorstel['tijdblok']}",
        f"  Locatie:  {loc.get('naam', 'onbekend')}",
        f"  Examens:  {examens}",
        "",
    ]
    if heeft_tekort:
        regels.append("Tekort:")
        for tk in voorstel["tekorten"]:
            regels.append(f"  - {tk['aantal']} x {tk['rol']}")
        regels.append("")
    if geblokkeerd_ingezet:
        namen = ", ".join(t["naam"] for t in geblokkeerd_ingezet)
        regels.append(f"Let op: ingezet ondanks een doorgegeven afwezigheid: {namen}.")
        regels.append("")
    regels += [
        "Kunnen jullie meedenken over een oplossing?",
        "",
        "Met vriendelijke groet,",
        "De examenplanning",
    ]
    return "\n".join(regels)
