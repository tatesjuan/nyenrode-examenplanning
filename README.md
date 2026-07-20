# Examenplanningstool — Nyenrode Business Universiteit

Centrale planning van examens over tijdslots en locaties, met automatische constraint-handhaving en surveillantenbeheer.

## Installatie lokaal

```bash
pip install -r requirements.txt
streamlit run app.py
```

Lokaal draaien werkt zonder secrets: zonder wachtwoord-secret is de app onbeveiligd
en ga je direct naar het inlogscherm.

## Toegangsbeveiliging

De app kan achter één gedeeld wachtwoord worden gezet, zodat niet iedereen met de URL
naar binnen kan. Het wachtwoord komt uit de secret `APP_WACHTWOORD` — **niet** in de
code, want de repo is publiek.

- **Streamlit Community Cloud:** app → *Settings* → *Secrets*, voeg toe:
  ```toml
  APP_WACHTWOORD = "kies-hier-een-wachtwoord"
  ```
- **Lokaal (optioneel):** zet hem in `.streamlit/secrets.toml` of als omgevingsvariabele
  `APP_WACHTWOORD`. Laat je hem weg, dan is de app onbeveiligd — handig bij ontwikkelen.

Na het wachtwoord kiest de gebruiker zelf naam en rol; het wachtwoord regelt alleen de
toegang tot de app, niet welke rol iemand kiest.

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
