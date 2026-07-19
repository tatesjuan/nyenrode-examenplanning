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

[app.py](app.py) is self-contained and imports only from `database` and `constraints`. Each screen is a function (`pagina_kalender`, `pagina_examens`, `pagina_aanmelden`, `pagina_surveillanten`, `pagina_zaalbeheer`, `pagina_beschikbaarheid`, `pagina_kalender_beheer`, `pagina_export`, `pagina_rapportage`), dispatched by `main()` from `st.session_state.pagina`.

Session state holds `rol`, `gebruiker`, `surveillant_id`, `pagina`, and the calendar cursor. Note it is `rol`, not `role`.

### Roles & Permissions

Five roles, keyed by their exact display string: `Planner`, `Head of Operations`, `Programmacoördinator`, `Surveillant`, `Examencommissie`. Access is expressed as sets in [app.py](app.py) rather than per-role conditionals:

| Set | Grants |
|-----|--------|
| `KAN_PLANNEN` | Assign exams to slots, edit exams, manage supervisors, rooms and the calendar |
| `KAN_OVERRULEN` | Override blocking constraints (Head of Operations only; requires a reason) |
| `KAN_AANMELDEN` | Submit new exams |
| `KAN_IMPORTEREN` | Reach the Excel import page |
| `KAN_LOCATIE_OVERSCHRIJVEN` | Let an imported file set the location; coordinators may not |
| `KAN_BESCHIKBAAR` | Supervisor availability portal |
| `ALLEEN_LEZEN` | Read-only reporting view |

### Domain Model

- **Examens** — exams with program, examtype, duration, auto-derived extension, student count, preferences, and status (`concept` → `ingediend` → `gepland` → `bevestigd`)
- **Locaties** — 19 rows across two campuses, each with `min_capaciteit` / `capaciteit` bounds, a `max_examens_per_slot` cap (default 2; the two sport-hall rows are 5) and an `actief` flag. Breukelen's sport hall exists as both a whole (350) and half (175) row; these are the **same physical space**, which [constraints.py](constraints.py) accounts for
- **Slots** — a (date, time block, location) triple; three blocks: ochtend (09:30–13:00), middag (14:00–17:30), avond (19:00–22:30)
- **Toewijzingen** — links an exam to a slot
- **Surveillanten** / **beschikbaarheid** / **surv_toewijzingen** — supervisors, their availability per slot, and assignments
- **academische_kalender** — exam weeks as date ranges per program; drives the morning-block rule

### Enumerated Values

Defined once in [database.py](database.py) and imported by [app.py](app.py) — never hardcode these in the UI:

- `EXAMTYPES` — `Exam`, `Retake`, `Retake 2`, `Retake 3`, `Exam/Retake`
- `LOCATIE_VOORKEUREN` — `BRK`, `AMS`, `BRK+AMS` (`BRK+AMS` means simultaneously on both campuses)

`bereken_verlenging(duur)` derives the exam extension: 5 minutes per full 30 minutes, capped at 60. It is the single source of truth — the UI shows it read-only and stores the result in `verlenging_minuten`.

### Rooms & the `actief` flag

`pagina_zaalbeheer()` (Planner and Head of Operations only) edits every room's name, campus, capacity bounds, `max_examens_per_slot` cap and `actief` flag, and adds new ones. It backs onto `add_locatie()` / `update_locatie()` — both take `max_examens_per_slot` as a keyword defaulting to 2, so a caller that omits it silently resets the cap; the screen always passes the current value.

`get_locaties(alleen_actief=False)` defaults to **all** rooms. Which one you want depends on what you are doing, and getting it wrong is silent:

- **Choosing a room to plan into** → `alleen_actief=True`. This covers `toon_planformulier()`, `auto_plan()` (it picks a room itself), and `_capaciteit_voorkeur()` (an inactive room must not inflate the expected capacity).
- **Looking a room up for display** → all rooms. The calendar, supervisor and availability screens resolve `locatie_id` → name/capacity for *existing* assignments; filtering would blank out any exam already booked into a since-deactivated room. `_zaalgroep_locaties()` likewise must see inactive rooms, since they can still hold bookings.
- **Zaalbeheer itself** → all rooms, otherwise a deactivated room could never be switched back on.

### Migrations

Two idempotent functions run inside `init_db()`; when adding a schema change, extend both the `CREATE TABLE` block and the matching function.

- `_migreer_examens()` — adds missing columns via `ALTER TABLE` and rewrites legacy values (`C`/`H`/`C/H`/`H1`/`H2`/`H3` → the `EXAMTYPES` names; `Breukelen`/`Amsterdam` → `BRK`/`AMS`).
- `_migreer_locaties()` — adds `min_capaciteit`, `actief` and `max_examens_per_slot`. `_seed_extra_locaties()` then adds any missing rooms **by name**, so re-running never duplicates.

Two SQLite traps, both hit during round 2b — do not reintroduce either:

- `ALTER TABLE ... ADD COLUMN ... DEFAULT` leaves *existing* rows `NULL` rather than applying the default, so backfill explicitly after adding a column.
- That same `DEFAULT` clause is DDL and does **not** accept a bound `?` parameter — `ADD COLUMN ... DEFAULT ?` raises `OperationalError: near "?"`. Inline the literal (`f"... DEFAULT {int(CONST)}"`); parameters are only for the follow-up `UPDATE`. A fresh database never exercises this branch (the column already exists from `CREATE TABLE`), so it only fails on the **upgrade path** — test migrations against a pre-existing schema, not just a fresh one.

`max_examens_per_slot` is a special case: the one-off "sport halls → 5" write lives **inside** the `if column-absent` block, so it runs exactly once when the column is first added and never overwrites a planner's later manual edit. A fresh install gets the 5 from `_seed_locaties()` instead.

### Constraint Engine

[constraints.py](constraints.py) exposes `check_alle_constraints()`, returning `{"ok", "blokkades", "waarschuwingen", "halve_zaal_suggestie"}`. The distinction matters:

- **blokkades** prevent planning. `ok` is simply `len(blokkades) == 0`. Only `KAN_OVERRULEN` can bypass them, and only with a recorded reason.
- **waarschuwingen** are advisory and never block.

**Blocking:** capacity (including the shared whole/half sport hall), the per-room `max_examens_per_slot` cap (placing an exam that would push the slot's exam count over the room's cap), FAU/Landelijk isolation (a FAU exam claims all of Breukelen for the day), and the morning-block rule (Breukelen mornings on Mon/Tue/Fri are unavailable outside exam weeks).

**Advisory:** supervisor ratios, the half-hall suggestion, and three occupancy warnings:

| Warning | Fires when |
|---------|-----------|
| Nearing capacity | The slot lands above 90% of room capacity but still within it (`cap*0.9 < nieuw_totaal <= cap`). A single check covering both new and existing slots — it replaced an older round-1 warning, so do not add a second one. |
| Sport-hall spread | The slot reaches `ZWARE_SESSIE_GRENS` (250+) in the **whole** sport hall *and* another 250+ session already sits in it within ±`SPORTHAL_SPREIDING_DAGEN` (14) days. Both sides must be heavy — a lightly booked hall is not a spread problem. |
| Back-to-back heavy sessions | The slot reaches 250+ *and* an adjacent time block that same day and room is also 250+. Adjacency is ochtend↔middag and middag↔avond; ochtend and avond do not touch. |

The two spread warnings are suppressed by `is_december_examenweek(datum)` — an exam week that falls in December — where peak load is unavoidable; the nearing-capacity warning is not.

`min_capaciteit` is still stored and editable in Zaalbeheer but is purely informational — a round-2 warning for exams below it was removed in round 2b at the users' request. Do not re-add it without a new decision.

`check_alle_constraints()` is called on manual assignment for live feedback and by `auto_plan()`, a greedy planner that sorts by student count descending and takes the earliest slot satisfying every constraint.

### Import & Export

Both live in [database.py](database.py):

- `import_examens_uit_excel(df, alleen_examens=False)` — reads both the **Chrono** and **EXAM_totaalplanning** exports. Returns `(aangemaakt, fouten, genegeerde_locaties)`. `alleen_examens=True` ignores any location column in the file and counts the dropped overrides.
- `export_naar_csv()` — the Facilitor Excel sheet (requires `openpyxl`).

Column recognition runs on **normalised** headers (`_norm_kolom()` strips everything but letters and digits, lowercased), so case, spacing and punctuation do not matter — `C/H/Retake`, `TENTAMEN ` and `geschat aantal` all resolve. Add new spellings to `KOLOM_ALIASSEN` rather than to the call site.

Row-level parsing:

- `_parse_duur()` — reads `TIJDSDUUR` from free text (`"2 uur"`, `"120"`, `"2:00"`, `"180 min"`, `"1,5 uur"`), falling back to `IMPORT_DUUR_STANDAARD` (120). A bare number ≤ 12 is read as hours, above that as minutes. The result feeds `bereken_verlenging()`, so imported exams get the same extension as manually entered ones.
- `_parse_examtype()` — maps C/H/Retake variants onto `EXAMTYPES`.
- `_parse_locatie_voorkeur()` / `_parse_datum()` — free-text location → `BRK`/`AMS`/`BRK+AMS`, and any date → ISO.
- Rows whose slot reads `BESCHIKBAAR` are empty slots, not exams, and are skipped.

## Key Conventions

- UI labels, database columns, and function names are in **Dutch**
- SQLite is the source of truth; `st.session_state` holds only UI state
- Forms that must react while typing (inline validation, the computed extension field) deliberately avoid `st.form`, which only re-runs on submit
- `st.tabs` renders every tab body in the same run, so widget keys must include a tab prefix — otherwise the same exam appears twice and Streamlit raises a duplicate-key error
- Never trust a `disabled` button as the only guard: re-check constraints server-side before writing
- A keyed Streamlit widget takes its value from `session_state` over its `value=` argument, so a computed read-only field must be written to `session_state` *before* the widget renders — otherwise it freezes at its first value
- New enumerated values, thresholds and parsers belong in [database.py](database.py) / [constraints.py](constraints.py) as named constants (`EXAMTYPES`, `ZWARE_SESSIE_GRENS`, `SPORTHAL_SPREIDING_DAGEN`, `KOLOM_ALIASSEN`), never inline in a screen
