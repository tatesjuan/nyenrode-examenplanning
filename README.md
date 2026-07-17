# Examenplanningstool — Nyenrode Business Universiteit

Centrale planning van examens over tijdslots en locaties, met automatische constraint-handhaving en surveillantenbeheer.

## Installatie lokaal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Rollen
- **Planner** — volledige planning en beheer
- **Head of Operations** — zelfde als planner + override-bevoegdheid
- **Programmacoördinator** — examens aanmelden
- **Surveillant** — beschikbaarheid opgeven
- **Examencommissie** — alleen lezen

## Functies
- Maandkalender met slotoverzicht
- Constraint-checks (capaciteit, FAU, ochtendblokkeringen, HS-ratio)
- Auto-planningsalgoritme
- Excel-import (Chrono tentamens format)
- Surveillantenbeschikbaarheid portal
- Export naar CSV voor Facilitor
