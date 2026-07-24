# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
pip install -r requirements.txt
streamlit run app.py
```

Streamlit hot-reloads on file save. `init_db()` runs on every start: it creates the tables if absent, seeds reference data, and migrates existing rows. It targets whichever backend `get_conn()` selects (see **Connection Layer** below). Locally that is the SQLite file `examenplanning.db`; `DB_PATH` is relative, so run from the project root.

## Architecture Overview

A **Streamlit single-page app** for exam scheduling at Nyenrode Business University. The UI is in Dutch, and code, function names, and database columns use Dutch terminology.

There are exactly four modules. There is no `pages/` directory and no `utils/` package — an earlier parallel implementation using those was removed (see git history for commit `d8213de` if you need it). Do not reintroduce a `pages/` directory without reading the note at the bottom of this file.

| File | Purpose |
|------|---------|
| [app.py](app.py) | Login, role gating, sidebar navigation, and every screen |
| [database.py](database.py) | Data layer, schema, migrations, Excel import/export, and the dual-mode connection layer |
| [constraints.py](constraints.py) | Exam-placement constraint validation and the exam auto-planning algorithm |
| [toewijzing.py](toewijzing.py) | Supervisor auto-assignment: month profile, scoring, proposals, shortage mail |

### Entry Point & Navigation

[app.py](app.py) is self-contained and imports only from `database`, `constraints` and `toewijzing`. Each screen is a function (`pagina_kalender`, `pagina_examens`, `pagina_aanmelden`, `pagina_surveillanten`, `pagina_zaalbeheer`, `pagina_beschikbaarheid`, `pagina_kalender_beheer`, `pagina_export`, `pagina_rapportage`), dispatched by `main()` from `st.session_state.pagina`.

Session state holds `rol`, `gebruiker`, `surveillant_id`, `pagina`, the calendar cursor, and the access-gate flags `toegang_verleend` / `inlog_pogingen`. Note it is `rol`, not `role`.

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

**Central permission helper `heeft_rol(rol, benodigd)`.** All *feature* gates go through this one function: it returns `True` for `Head of Operations` unconditionally (superuser), otherwise `rol in benodigd`. So a newly-added gated feature that checks `heeft_rol(rol, KAN_X)` automatically opens for Head of Operations too — no separate wiring. `KAN_OVERRULEN` still resolves the same way (only HoO passes it), so the constraint-override right is unchanged. The role display string stays `Head of Operations`; it was **not** renamed (that would ripple through the `ROLLEN` dict, every set, and `st.session_state.rol`).

**Two sets are deliberately *not* routed through the helper.** In `main()`, `rol in ALLEEN_LEZEN` (Examencommissie → only the report view) and `rol in KAN_BESCHIKBAAR` (Surveillant → only their own availability portal) are **exclusive role identity**, not feature gates — they decide which single screen a role is locked to. Passing HoO through `heeft_rol` there would trap it in the report or availability view, so those two stay exact set-membership. HoO is in neither set, so it falls through to the normal page dispatch and can open every screen. Head of Operations also reaches the availability portal: `pagina_beschikbaarheid()` shows a **surveillant picker** when `surveillant_id` is unset but the user has `KAN_PLANNEN`, so a planner/HoO can view and edit availability on a supervisor's behalf (a real supervisor keeps their own `surveillant_id` and skips the picker). The picker lists **active supervisors only** and labels each with campus, e.g. `Adele (AMS)`; the proxy still respects the Deel A `kan_hs` button logic (an HS-capable supervisor shows the HS variant).

### Access Gate (shared password)

A single shared password gates the whole app, so a stranger with the URL cannot open it. It is **not** an identity system: after the password, the user still picks their own name and role on the existing login screen exactly as before. The password controls *entry to the app*, not *which role* you may choose — that stays deliberately open.

- **Secret `APP_WACHTWOORD`**, read by `_app_wachtwoord()` with the same defensive pattern as the Turso secrets: `st.secrets` first (swallowing `StreamlitSecretNotFoundError` / `KeyError`), then `os.environ`. Never hardcode it — the repo is public.
- **No password set → gate is skipped.** If the secret is absent or empty, `main()` goes straight to the login screen, so local development works without any secret (mirroring the Turso → local-SQLite fallback).
- **Flow:** `main()` shows `toon_wachtwoordscherm()` and stops while a password is set and `st.session_state.toegang_verleend` is not `True`. On the correct password (compared with `hmac.compare_digest`) it sets `toegang_verleend = True` and falls through to the normal login/routing. Wrong entries reveal no detail about why.
- **Brute-force brake:** `inlog_pogingen` counts failures; after `MAX_INLOG_POGINGEN` (5) the input is hidden and the session is blocked until the tab is closed.
- **Sidebar buttons:** "Uitloggen" clears the name/role but keeps `toegang_verleend` (back to the login screen). "Afsluiten" — shown only when a password is set — also clears `toegang_verleend`, ending the session fully on a shared computer.

### Domain Model

- **Examens** — exams with program, examtype, duration, auto-derived extension, student count, preferences, and status (`concept` → `ingediend` → `gepland` → `bevestigd`)
- **Locaties** — 19 rows across two campuses, each with `min_capaciteit` / `capaciteit` bounds, a `max_examens_per_slot` cap (default 2; the two sport-hall rows are 5) and an `actief` flag. Breukelen's sport hall exists as both a whole (350) and half (175) row; these are the **same physical space**, which [constraints.py](constraints.py) accounts for
- **Slots** — a (date, time block, location) triple; three blocks: ochtend (09:30–13:00), middag (14:00–17:30), avond (19:00–22:30)
- **Toewijzingen** — links an exam to a slot
- **Surveillanten** / **beschikbaarheid** / **surv_toewijzingen** — supervisors, their availability per slot, and assignments. Each supervisor also carries `contract_type` (`nul-uren` / `FTE`), `fte_factor`, a derived `jaardoel_uren`, an `actief` flag, and a primary **`campus`** (`BRK`/`AMS`, from `SURV_CAMPUSSEN`, default `BRK`). The seed roster is **16**: Elizabeth/Adele/Tanya/Xaverio are `AMS`, everyone else `BRK`; Analia/Brigit/Dania/Marten are seeded **inactive**; Marjan and Pratty are the two newest (`BRK`, nul-uren, `kan_hs=0`). In the **own-availability portal** (`pagina_beschikbaarheid`) a supervisor sees only two buttons per slot, driven by their `kan_hs`: an HS-capable supervisor gets **HS / Niet**, a non-HS supervisor gets **Surv. / Niet** — there is no HS-vs-S choice to make. Storage is unchanged (`rol_voorkeur` `"HS"`/`"surv"`, `beschikbaar` 0/1); the planner's matrix/assignment views still read both values, and the **HS-als-S** rule in [toewijzing.py](toewijzing.py) independently decides whether an HS-capable person fills an S post
- **surv_uren_log** — one row per worked session, keyed `UNIQUE(surveillant_id, slot_id)`, tagged with `academisch_jaar`; feeds the hours counter
- **periode_blokkades** — date ranges a supervisor marks as unavailable (advisory; see below)
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

### Connection Layer

`get_conn()` is **dual-mode**, and it is the only place that knows which backend is live. Everything else uses the sqlite3 API unchanged (`conn.execute(...).fetchone()`, `row["kolom"]`, `dict(row)`, `cursor()`, `executemany`, `executescript`, `row_factory = Row`).

- **Turso / libSQL** (production on Streamlit Community Cloud, so data survives restarts) when **both** secrets `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are present. `_turso_config()` reads them defensively — `st.secrets` first (wrapped in try/except so a missing secrets file's `StreamlitSecretNotFoundError` or a missing key's `KeyError` is swallowed), then `os.environ`. Empty strings count as absent.
- **Local SQLite** (`examenplanning.db`) otherwise — this branch is byte-for-byte the original code, so local development needs no credentials. `_gebruik_turso()` decides; the decision is separated from the actual connect so it can be tested without a network call.

**The client: `libsql-client` (pure Python).** We first used `libsql-experimental`, but it has **no prebuilt wheel for Python 3.14 on Streamlit Community Cloud** and falls back to compiling itself from Rust via maturin/cargo — which fails there with "Failed building wheel" because that environment has no Rust toolchain. `libsql-client` is pure Python (only aiohttp and friends as deps, all with prebuilt wheels), so it installs without any compilation. That fixed the deploy.

**Why the wrapper exists.** `libsql-client` is *not* sqlite3-compatible: you call `client.execute(stmt, args)` and get back a `ResultSet` with `.rows`, `.columns` and `.last_insert_rowid` — no cursor, no `fetchone`, no `row_factory`. Rather than touch a single query, a thin wrapper mimics the sqlite3 API for the Turso path only:

- `_Row` — dict-like row supporting `row["kolom"]`, `row[0]` and `dict(row)`. This conversion is **required**, not cosmetic: a raw `libsql_client.Row` supports `row[0]` and `row["kolom"]` but `dict(row)` raises `ValueError`, and the codebase relies on `dict(row)` everywhere.
- `_Cursor` — wraps a `ResultSet`, buffers `.rows` as `_Row` objects (via `Row.astuple()`), and exposes `fetchone()`/`fetchall()`/iteration plus `lastrowid` (from `last_insert_rowid`) and `description`.
- `_TursoConn` — implements `execute`, `executemany` (loop), `cursor()` (returns self, since callers do `conn.cursor().execute(...)`), `close`, an ignored `row_factory` setter, and `executescript()` which splits the schema into individual statements itself (`_split_sql`, safe because the schema has no `;` inside literals). Two client-specific details: **parameters are passed as a `list`** — `_args()` turns sqlite3's `?`+tuple into a list, and an empty tuple into `None` — and **`commit()` is a no-op** because the sync client commits every statement immediately. `PRAGMA foreign_keys = ON` is set on connect, guarded for builds that reject it.

**`TURSO_DATABASE_URL` must start with `https://`, not `libsql://`.** This is the single most important deployment detail, confirmed against the real Turso database in production. Although `create_client_sync()` *accepts* a `libsql://` URL, that scheme makes `libsql-client` open a **WebSocket connection using the hrana2 protocol**, which Turso rejects with `WSServerHandshakeError: 400, message='Invalid response status'` — the app then crashes on the first query. With an `https://` URL the client uses the **HTTP route**, which works. Turso gives you the `libsql://` form by default, so convert it: same host, just swap the scheme to `https://` (e.g. `libsql://db-org.turso.io` → `https://db-org.turso.io`). The code passes the URL through unchanged, so this must be fixed in the secret value itself.

**First run against Turso starts empty.** A new Turso database has no tables; `init_db()` builds the full schema, runs the migrations and seeds on first app start — so you begin with a fresh database (Hans/Winie FTE contracts, 19 rooms, etc.). Your local `examenplanning.db` is **not** copied over; migrating existing local data is a separate manual step. The migrations run identically against Turso because they go through the same `get_conn()`. Expect that first start to be noticeably slower: every statement is a separate network round-trip, and `init_db()` issues many (schema + migrations + dozens of seed inserts). It is a one-time cost per fresh database.

**Persistence is verified.** With the `https://` URL in place, data written on Turso survives a reboot of the Streamlit app — the whole point of the migration off local SQLite (which Streamlit Community Cloud wipes on restart). Confirmed in production: create records, reboot the app, records are still there.

### Performance — the round-trip is the enemy

**On Turso every statement is a separate network round-trip of roughly ~100 ms.** Local SQLite hides this (a call is microseconds), so the danger is invisible in development and only bites in production. The rule: **never loop a per-row query.** A page that ran ~10 s per click was doing 50–130 statements, almost all from `get_...voor_slot`/`voor_examen` calls inside `for`-loops. The fixes that took it to ~1–2 s:

- **`init_db()` runs once per process, not per rerun.** It sits behind `@st.cache_resource` (`_init_db_eenmalig()` in [app.py](app.py)); `init_db()` itself is unchanged, so tests that call it directly still work. Against a fully-built database it does ~32 no-op statements, and Streamlit reruns module-level code on *every* interaction — so this alone was ~3 s of waste per click. A fresh Turso database is still built correctly on the first run (a failed run isn't cached, so the next rerun retries).
- **One shared connection per rerun.** `main()` calls `open_gedeelde_conn()` / `sluit_gedeelde_conn()` (in [database.py](database.py)) around the whole render. `get_conn()` returns that shared connection (stored in a `threading.local`, so per Streamlit session), wrapped in `_GedeeldeConn` whose `close()` is a **no-op** — so the many helpers that each do `get_conn(); …; close()` no longer open a new `create_client_sync` every call. Outside Streamlit (tests, scripts, the `init_db` at startup) there is no shared connection, so `get_conn()` falls back to a fresh `_nieuwe_verbinding()` — behaviour is identical, no helper changed.
- **Batch the N+1 loops.** `get_toewijzingen_voor_maand(jaar, maand)` fetches every slot's assignments for a month in one JOIN, grouped by `slot_id`; it replaced the per-slot loops in `pagina_kalender`, the Surveillanten sections and `pagina_beschikbaarheid`. `get_toewijzingen_per_examen()` does the same across all exams (dict keyed by `examen_id`); it replaced the per-exam loop in `pagina_examens` and `pagina_rapportage`. Both return the same columns as the single-row versions, and callers use `.get(id, [])` / `.get(id)`. `get_urenoverzicht()` likewise went from 1 + N queries to two (all supervisors + one `GROUP BY`).
- **Only the visible section queries.** The Surveillanten page uses `st.radio` (key `surv_sectie`), **not** `st.tabs` — because `st.tabs` renders *all* tab bodies on every run, so all five sections queried even though the user sees one. With the radio, only the selected section's code (and queries) runs.

Measured effect per page render (connections / statements, with the realistic 30-slot / 15-exam month): Surveillanten 87/132 → 1/5, Kalender 50/96 → 1/20, Beschikbaarheid 50/81 → 1/5, Examens 36/67 → 1/6, Rapportage 17/48 → 1/2. Every page now opens exactly one connection. When adding a screen, apply the same discipline: one connection per render, and never a query inside a per-row loop.

### Migrations

Two idempotent functions run inside `init_db()`; when adding a schema change, extend both the `CREATE TABLE` block and the matching function.

- `_migreer_examens()` — adds missing columns via `ALTER TABLE` and rewrites legacy values (`C`/`H`/`C/H`/`H1`/`H2`/`H3` → the `EXAMTYPES` names; `Breukelen`/`Amsterdam` → `BRK`/`AMS`).
- `_migreer_locaties()` — adds `min_capaciteit`, `actief` and `max_examens_per_slot`. `_seed_extra_locaties()` then adds any missing rooms **by name**, so re-running never duplicates.
- `_migreer_surveillanten()` — adds `contract_type`, `fte_factor`, `jaardoel_uren`, and (Deel B) `campus`. New tables (`surv_uren_log`, `periode_blokkades`, `maandprofiel_handmatig`) need no migration — `CREATE TABLE IF NOT EXISTS` in the schema block covers both fresh and upgrade paths.

Two SQLite traps, both hit during round 2b — do not reintroduce either:

- `ALTER TABLE ... ADD COLUMN ... DEFAULT` leaves *existing* rows `NULL` rather than applying the default, so backfill explicitly after adding a column.
- That same `DEFAULT` clause is DDL and does **not** accept a bound `?` parameter — `ADD COLUMN ... DEFAULT ?` raises `OperationalError: near "?"`. Inline the literal (`f"... DEFAULT {int(CONST)}"`); parameters are only for the follow-up `UPDATE`. A fresh database never exercises this branch (the column already exists from `CREATE TABLE`), so it only fails on the **upgrade path** — test migrations against a pre-existing schema, not just a fresh one.

`max_examens_per_slot` is a special case: the one-off "sport halls → 5" write lives **inside** the `if column-absent` block, so it runs exactly once when the column is first added and never overwrites a planner's later manual edit. A fresh install gets the 5 from `_seed_locaties()` instead. `_migreer_surveillanten()` uses the identical one-off pattern for the seeded FTE contracts (Hans 0.23, Winie 0.45): set once when the columns are first added, so a later manual contract change survives re-init. A fresh install gets them from `_seed_surveillanten()`.

**Deel B personnel mutations run once, inside the `if "campus" not in kolommen` block.** On the live Turso data (which has the 14-person roster, all active, no campus column) that first upgrade: backfills every campus to `BRK`, then sets `AMS` for the four AMS names, sets the four (`SURV_INACTIEF`) to `actief=0`, and inserts Marjan/Pratty if absent — all via batched `IN`-clauses / one `executemany`, not per-row loops (Turso round-trips). Because it is gated on the column being new, a later re-init never re-applies it, so a planner who reactivates someone keeps that change. Inactivation **never deletes**: the row, its `surv_uren_log` history and past `surv_toewijzingen` stay; the person just drops out of `get_surveillanten(alleen_actief=True)`, the auto-planner, and every picker/dropdown. A fresh install gets the same end state from `_seed_surveillanten()`.

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

### Supervisor Hours & Contracts

Added in round 3 part 1. There is deliberately **no assignment algorithm** here yet — that is round 3 part 2. This part is data + counters only.

**Contracts.** Each supervisor has `contract_type` (`nul-uren` or `FTE`), an `fte_factor` (0–1), and a derived `jaardoel_uren`. Two constants in [database.py](database.py) are the source of truth:

- `UUR_PER_FTE = 2080` — one FTE is 2080 hours/year. `bereken_jaardoel(fte_factor)` returns `fte_factor * 2080`.
- `SESSIE_UREN = 5.5` — hours credited per supervised session.

`update_surveillant_contract(id, contract_type, fte_factor)` recomputes `jaardoel_uren` and forces factor and target to 0 for a `nul-uren` contract. Seeded FTE contracts: Hans 0.23, Winie 0.45; everyone else `nul-uren`.

**Academic year.** `bepaal_academisch_jaar(datum)` maps a date to its academic year, which runs **1 August – 31 July**: both `2026-10-15` and `2027-03-10` return `"2026-2027"`. Every hours-log row is tagged with this, and all counters are per academic year.

**Hours log.** `surv_uren_log` is written **automatically** by `wijs_surveillant_toe()` (one row, `SESSIE_UREN` hours) and deleted by `verwijder_surv_toewijzing()`. The `UNIQUE(surveillant_id, slot_id)` constraint plus `ON CONFLICT DO NOTHING` means re-assigning the same person to the same slot (e.g. a role change) never double-counts. Counters: `get_uren_totaal()`, `get_uren_per_maand()`, and `get_urenoverzicht(academisch_jaar)` (feeds the planner's **Urenoverzicht** tab on the Surveillanten page — FTE first, shortfalls flagged red). Contract editing lives on the same page's "Surveillanten beheren" tab.

Two things to keep in mind:

- **The log fills only from now on.** Assignments made before round 3 are not backfilled into `surv_uren_log`; the counters start empty and grow as new assignments are made.
- **`periode_blokkades` is advisory.** Supervisors manage their unavailable date ranges under "Mijn beschikbaarheid". `is_geblokkeerd_in_periode(surveillant_id, datum)` is now consumed by the assignment algorithm (round 3 part 2, below) as a heavy score penalty rather than a hard exclusion — a block can still be overridden when there is no alternative.

### Supervisor Auto-Assignment ([toewijzing.py](toewijzing.py))

Round 3 part 2. Every public function returns a **proposal**; nothing is written unless `uitvoeren=True`, and writes always go through `wijs_surveillant_toe()` so the hours log stays in sync. Manual override wins throughout — a proposal is never binding.

**Month profile.** `bepaal_maandprofiel(academisch_jaar)` classifies each month from the total student load of its planned exams: **piek** when the month's factor (`month_total / average`) is > 1.5, **dal** when < 0.5, otherwise **normaal**. A row in `maandprofiel_handmatig` overrides the category for that month and takes precedence over the automatic result.

**Interpretation choice — a manual month override changes the label, not the compute weight.** The FTE hour-spreading below always uses the continuous numeric `factor` (student-load based), because the spec defines the weighting as "naar rato van de maandfactor". A manual override sets the displayed/stored *category* (piek/normaal/dal) but does not redefine that factor. So overriding a month to "piek" changes what the planner sees and any category-based logic, but does not by itself make FTE hours spread more heavily into that month. Changing that would need an agreed category→weight mapping.

**`wijs_automatisch_toe(slot_id, uitvoeren=False)`** — per slot, in the order A–F from the spec:

- **A. Need:** `hs_nodig = ceil(exams / 2)`, `surv_nodig = ceil(students / 50)`. Existing manual assignments on the slot reduce what remains to fill.
- **B. Candidates:** active supervisors who marked themselves available (`beschikbaarheid.beschikbaar = 1`) **and whose `campus` matches the slot's campus** (`campus_code()` maps the slot location's `Breukelen`/`Amsterdam` → `BRK`/`AMS`). The auto-planner never places anyone cross-campus; if a shortage remains while available supervisors sit on the *other* campus, it adds a `waarschuwing` naming them. `rol_voorkeur == "HS"` can fill HS or S, `"surv"` fills S only; anyone already on the slot is skipped. **Manual assignment by the planner is not campus-bound** — it goes straight through `wijs_surveillant_toe()`, not this function.
- **C. Score** (higher = assigned sooner):
  - **FTE:** `score = 1000 + achterstand`, where `achterstand = verwacht_saldo − gedraaide_uren` up to and including the slot's month. `verwacht_saldo` distributes `jaardoel_uren` across the year's exam-months proportional to each month's `factor` (peak months weigh more), summed up to the current month. The `1000` base keeps FTE above every nul-uren contract.
  - **nul-uren:** `score = −gedraaide_uren` this academic year (least-worked first); ties broken by who offered more availability this year.
  - **Blocked:** `is_geblokkeerd_in_periode` true → subtract `BLOKKADE_STRAF = 1500`. This is deliberately **larger than the FTE base of 1000**, so a blocked FTE sinks below a free nul-uren worker — a declared holiday outweighs contract type. The candidate is not removed, so they still surface when there is no alternative.
- **E. Fill:** HS posts first from HS-capable candidates by score; then S posts from everyone remaining by score — including HS-capable people not used for HS (the **HS-als-S** rule: a high-scoring HS can take an S post over a lower-scoring nul-uren S).
- **F. Return:** `{slot_id, hs_nodig, surv_nodig, toewijzingen[], tekorten[], waarschuwingen[], ...}`; each proposed person carries `score`, `achterstand`, `geblokkeerd` and a short `reden`.

**`voorstel_voor_maand(jaar, maand, uitvoeren=False)`** runs every exam slot in the calendar month and aggregates fully-fillable vs shortage counts (the calendar page's "Auto-toewijzing hele maand" button, behind an explicit confirm).

**`genereer_tekort_mail(voorstel)`** returns a ready-to-copy plain-text mail to `toetsbureau@nyenrode.nl` (date, block, location, shortage, exams) when a proposal has a shortage or places a blocked person — otherwise `None`. No mail is ever sent automatically; the UI shows it in an `st.code()` block.

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
- Gate features with `heeft_rol(rol, KAN_X)`, never a bare `rol in KAN_X` — that keeps Head of Operations a superuser for free. The only exceptions are the two exclusive-identity routes in `main()` (`ALLEEN_LEZEN`, `KAN_BESCHIKBAAR`), which stay exact set-membership on purpose
- A write or upload action that ends in `st.rerun()` loses any `st.success()` you show just before it. For **visible feedback**: wrap the work in `st.spinner(...)` (shows *that it is running*), then use `st.toast(...)` (survives the rerun) and/or stash a result dict in `session_state` to render after the rerun. The Excel import and the "Bevestigen" action do this; apply the same to any new long/writing button
