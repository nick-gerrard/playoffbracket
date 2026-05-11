# Playoff Bracket — Design & Roadmap

## Overview

A family-facing NHL playoff prediction and competition site. Users submit bracket predictions at the start of the playoffs, compete on a leaderboard, and optionally make per-game side wagers using a fake currency (DucksBucks). Target audience: Nick's family. Target season: 2027 NHL playoffs (built and tested against 2026 data).

## Stack

- **Backend:** FastAPI + SQLModel (SQLite via `bracket.db`)
- **Frontend:** Jinja2 templates + Tailwind CSS (CDN) + HTMX
- **Data source:** NHL public API (`https://api-web.nhle.com/v1/playoff-bracket/{year}`)

---

## What's Built

### Data layer
- `Team` model — seeded from NHL API, has `api_id` (NHL's id) and `id` (db PK)
- `Series` model — seeded from NHL API, fields include:
  - `conference` (East / West / Final)
  - `series_abbrev` (R1 / R2 / ECF / WCF / SCF)
  - `top_seed_team`, `bottom_seed_team`, `winner` — FK to `team.id`
  - `top_seed_wins`, `bottom_seed_wins`
  - `child_series` — exists on model but not needed (bracket structure inferred from conference/abbrev)
- `seed.py` — fetches from NHL API, deduplicates teams, maps NHL api_ids to db PKs for FK fields

### Routes
- `/` — hello world placeholder
- `/about` — how-to-play staggered card layout
- `/teams` — 4-column grid of team cards with logos
- `/bracket` — main bracket view (see below)

### Bracket page
- 7-column flex layout: West R1 → R2 → WCF | SCF | ECF → R2 → R1 East
- Series pre-grouped in route into `bracket.West`, `bracket.East`, `bracket.Final` dicts keyed by abbrev
- `team_map` dict (`{team.id: Team}`) passed to template for FK → object lookups
- `justify-around` on each column — spacing doubles automatically as series count halves each round
- Series card: team logo, abbrev, win count; winning team row highlighted gold when wins == 4

---

## Template Architecture

### Component reuse (macros)
Jinja2 macros are the Svelte-component equivalent — parameterized, reusable HTML chunks. Convention: define macros in `templates/components/<name>.html`, import where needed:
```html
{% from "components/card.html" import team_card %}
{{ team_card(team, stats=stats.get(team.id)) }}
```

### CSS strategy
- `static/css/components.css` — styles tied to a macro (e.g. card flip animation). Linked once in `base.html`.
- `{% block styles %}{% endblock %}` in `base.html <head>` — page-specific styles that don't belong globally.
- Tailwind utility classes — everything else (layout, color, spacing).
- Rule of thumb: if a `<style>` block lives in a page template, ask "does any other page need this?" If yes → `components.css`. If no → `{% block styles %}`.

### Base template blocks
`base.html` exposes: `{% block title %}`, `{% block styles %}`, `{% block content %}`. Add `{% block scripts %}` before `</body>` if page-specific JS is ever needed.

---

## Key Design Decisions

**Why `series_abbrev` and `conference` instead of `playoff_round`**
The NHL API's `playoffRound` field is unreliable — Conference Finals and the Stanley Cup Final all return `playoffRound: 2`. `seriesAbbrev` (R1/R2/CF/SCF) and inferred conference (from `series_letter` A–D=East, E–H=West, etc.) are the reliable signals.

**Why a `team_map` dict instead of SQLModel Relationships**
`Series` has three FK columns pointing at `Team` (top seed, bottom seed, winner). SQLAlchemy requires explicit `foreign_keys` disambiguation for each `Relationship()` when multiple FKs point at the same table — more ceremony than it's worth. A simple `{team.id: team}` dict passed from the route is cleaner.

**Why per-series prediction rows (planned)**
Storing one row per user per series (rather than one row per complete bracket) makes scoring, leaderboard queries, and the compare-brackets feature much cleaner to implement.

---

## Roadmap

### Phase 1 — Predictions
- [ ] Design `Prediction` model — one row per user per series, stores the user's predicted winner
- [ ] Scoring logic — compare predictions against actual `winner` field as series resolve
- [ ] Picks UI — allow users to click a team in each series card to register a pick

### Phase 2 — Users & Auth
- [ ] User model
- [ ] SSO auth (family-friendly login, bot protection)
- [ ] Associate predictions with users

### Phase 3 — Leaderboard & Compare
- [ ] Leaderboard page — ranked by correct predictions
- [ ] Compare page — side-by-side view of two users' brackets

### Phase 4 — DucksBucks (fake wagering)
Independent from the bracket leaderboard. Each user who submits a bracket gets a starting DucksBucks balance.
- [ ] Per-user balance ledger
- [ ] `Proposition` model — per-game bet offer with terms, creator, challenger, stake, status
- [ ] Challenge flow — user proposes a bet, specific other user accepts/declines
- [ ] Resolution — manual (Nick resolves) vs automated (poll NHL game score API). Start manual.

### Phase 5 — Polish
- [ ] Full app audit — spacing, typography, color consistency
- [ ] Tailwind component refinement (dedicated practice sessions)
- [ ] Mobile layout
- [ ] Add `primary_color` (hex string) field to `Team` model — used for team-specific accents (card glows, pick highlights, bracket row colors). Source via `colorthief` library extracting dominant color from `logo_url`, with manual overrides for any obviously wrong results.

---

## NHL API Notes

- Bracket endpoint: `https://api-web.nhle.com/v1/playoff-bracket/{year}`
- Returns `series[]` — each has team objects nested inline (not just IDs)
- `playoffRound` is unreliable for later rounds (all return 2)
- `seriesLetter` ordering: A–D East R1, E–H West R1, I–J East R2, K–L West R2, M East CF, N West CF, O SCF
- TBD teams have `id: -1` in the API — filter these out when seeding
