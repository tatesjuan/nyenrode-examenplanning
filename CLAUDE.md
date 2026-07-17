# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
pip install -r requirements.txt
streamlit run app.py
```

Streamlit hot-reloads on file save. `init_db()` runs on every start: it creates the SQLite database (`examenplanning.db`) if absent, seeds reference data, and migrates existing rows. `DB_PATH` is relative, so always run from the project root.

## Architecture Overview

A **Streamlit single-page app** for exam scheduling at Nyenrode Business University. The UI is in Dutch, and code, function names, and database columns use Dutch terminology.

There are exactly three modules. There is no `pages/` directory and no `utils/` package — an earlier parallel implementation using those was removed (see git history for commit `d8213de` if you need it). Do not reintroduce a `pages/` directory without reading the note at the bottom of this file.

| File | Purpose |
|------|---------|
| [app.py](app.py) | Login, role gating, sidebar navigation, and every screen |
| [database.py](database.py) | SQLite data layer, schema, migrations, Excel import/export |
| [constraints.py](constraints.py) | Constraint validation and the auto-planning algorithm |

### Entry Point & Navigation

[app.py](app.py) is self-contained and imports only from `database` and `constraints`. Each screen is a function (`pagina_kalender`, `pagina_examens`, `pagina_aanmelden`, `pagina_surveillanten`, `pagina_beschikbaarheid`, `pagina_kalender_beheer`, `pagina_export`, `pagina_rapportage`), dispatched by `main()` from `st.session_state.pagina`.

Session state holds `rol`, `gebruiker`, `surveillant_id`, `pagina`, and the calendar cursor. Note it is `rol`, not `role`.

### Roles & Permissions

Five roles, keyed by their exact display string: `Planner`, `Head of Operations`, `Programmacoördinator`, `Surveillant`, `Examencommissie`. Access is expressed as sets in [app.py](app.py) rather than per-role conditionals:

| Set | Grants |
|-----|--------|
| `KAN_PLANNEN` | Assign exams to slots, edit exams, manage supervisors and the calendar |
| `KAN_OVERRULEN` | Override blocking constraints (Head of Operations only; requires a reason) |
| `KAN_AANMELDEN` | Submit new exams |
| `KAN_IMPORTEREN` | Reach the Excel import page |
| `KAN_LOCATIE_OVERSCHRIJVEN` | Let an imported file set the location; coordinators may not |
| `KAN_BESCHIKBAAR` | Supervisor availability portal |
| `ALLEEN_LEZEN` | Read-only reporting view |

### Domain Model

- **Examens** — exams with program, examtype, duration, auto-derived extension, student count, preferences, and status (`concept` → `ingediend` → `gepland` → `bevestigd`)
- **Locaties** — five rows across two campuses. Breukelen's sport hall exists as both a whole (350) and half (175) row; these are the **same physical space**, which [constraints.py](constraints.py) accounts for
- **Slots** — a (date, time block, location) triple; three blocks: ochtend (09:30–13:00), middag (14:00–17:30), avond (19:00–22:30)
- **Toewijzingen** — links an exam to a slot
- **Surveillanten** / **beschikbaarheid** / **surv_toewijzingen** — supervisors, their availability per slot, and assignments
- **academische_kalender** — exam weeks as date ranges per program; drives the morning-block rule

### Enumerated Values

Defined once in [database.py](database.py) and imported by [app.py](app.py) — never hardcode these in the UI:

- `EXAMTYPES` — `Exam`, `Retake`, `Retake 2`, `Retake 3`, `Exam/Retake`
- `LOCATIE_VOORKEUREN` — `BRK`, `AMS`, `BRK+AMS` (`BRK+AMS` means simultaneously on both campuses)

`bereken_verlenging(duur)` derives the exam extension: 5 minutes per full 30 minutes, capped at 60. It is the single source of truth — the UI shows it read-only and stores the result in `verlenging_minuten`.

### Migrations

`_migreer_examens()` runs inside `init_db()` and is idempotent: it adds missing columns via `ALTER TABLE` and rewrites legacy values (`C`/`H`/`C/H`/`H1`/`H2`/`H3` → the `EXAMTYPES` names; `Breukelen`/`Amsterdam` → `BRK`/`AMS`). When adding a schema change, extend both the `CREATE TABLE` block and this function.

### Constraint Engine

[constraints.py](constraints.py) exposes `check_alle_constraints()`, returning `{"ok", "blokkades", "waarschuwingen", "halve_zaal_suggestie"}`. The distinction matters:

- **blokkades** prevent planning. `ok` is simply `len(blokkades) == 0`. Only `KAN_OVERRULEN` can bypass them, and only with a recorded reason.
- **waarschuwingen** are advisory and never block.

Checks: capacity (including the shared whole/half sport hall), FAU/Landelijk isolation (a FAU exam claims all of Breukelen for the day), the morning-block rule (Breukelen mornings on Mon/Tue/Fri are unavailable outside exam weeks), supervisor ratios, and a half-hall suggestion.

It is called on manual assignment for live feedback and by `auto_plan()`, a greedy planner that sorts by student count descending and takes the earliest slot satisfying every constraint.

### Import & Export

Both live in [database.py](database.py):

- `import_examens_uit_excel(df, alleen_examens=False)` — expects the **Chrono** format; the column mapping is at the top of the function. `alleen_examens=True` ignores any location column in the file and reports how many overrides were dropped.
- `export_naar_csv()` — the Facilitor Excel sheet (requires `openpyxl`).

## Key Conventions

- UI labels, database columns, and function names are in **Dutch**
- SQLite is the source of truth; `st.session_state` holds only UI state
- Forms that must react while typing (inline validation, the computed extension field) deliberately avoid `st.form`, which only re-runs on submit
- `st.tabs` renders every tab body in the same run, so widget keys must include a tab prefix — otherwise the same exam appears twice and Streamlit raises a duplicate-key error
- Never trust a `disabled` button as the only guard: re-check constraints server-side before writing
