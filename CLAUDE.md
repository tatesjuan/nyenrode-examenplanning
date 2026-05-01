# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
pip install -r requirements.txt
streamlit run app.py
```

Streamlit hot-reloads on file save. The SQLite database (`examenplanning.db`) is created on first run and persists locally.

## Architecture Overview

This is a **Streamlit multi-page app** for exam scheduling at Nyenrode Business University. The UI is in Dutch. All code, variable names, and database columns use Dutch terminology.

### Entry Point & Auth

[app.py](app.py) handles login and role-based access, then renders a monthly calendar view. Five roles exist: `planner`, `hoofd_operations`, `programmacoördinator`, `surveillant`, `examencommissie` — each with different page access and write permissions.

### Page Structure (`pages/`)

| File | Purpose |
|------|---------|
| `1_Planningsoverzicht.py` | Calendar view; drag-and-drop exam assignment; constraint feedback |
| `2_Examens.py` | Exam registry; Excel import (Chrono format); status management |
| `3_Surveillanten.py` | Supervisor availability portal; assignment management |
| `4_Rapporten.py` | CSV/Excel exports for Facilitor and supervisor matrices |

### Domain Model

- **Examens** — course exams with program, duration, student count, preferences, and planning status
- **Locaties** — two campuses: Breukelen (sport hall) and Amsterdam (classrooms), each with room capacities
- **Slots** — 3 daily time blocks: ochtend (09:30–13:00), middag (14:00–17:30), avond (19:00–22:30)
- **Toewijzingen** — assignments linking exams to slots
- **Surveillanten** — supervisors with availability matrices
- **Examenweeks** — weeks 38–51 with calendar metadata used for constraint logic

### Data Layer

[database.py](database.py) is a thin SQLite wrapper (no ORM). [utils/data.py](utils/data.py) manages Streamlit session state and hardcodes reference data (locations, time blocks, sample exams). When modifying the schema, update both files.

### Constraint Engine

Two files cooperate:

- [constraints.py](constraints.py) — core validation: capacity limits, FAU/Landelijk isolation (blocks full day), morning-block restrictions, HS ratio requirements, cohort splits for large groups
- [utils/constraints.py](utils/constraints.py) — UI-facing helpers that return human-readable violation messages

The constraint checker is called both on manual assignment (real-time feedback) and during auto-planning.

### Auto-Planning Algorithm

[utils/algorithm.py](utils/algorithm.py) uses a greedy approach: sort exams by student count descending, place FAU exams first, then find the earliest slot satisfying all constraints for each remaining exam. Returns a list of successes and failures with reasons.

### Exports

[utils/export.py](utils/export.py) generates two Excel outputs:
- **Facilitor export** — full exam detail sheet for the external facility management system
- **Surveillant matrix** — availability and assignment grid

## Key Conventions

- UI labels, database column names, and function names are in **Dutch**
- Streamlit session state (`st.session_state`) is the primary in-memory store; [utils/data.py](utils/data.py) initialises it
- Constraint violations are non-blocking warnings by default; planners with `hoofd_operations` role can override
- Excel import expects the **Chrono** format — column mapping is defined in `2_Examens.py`
