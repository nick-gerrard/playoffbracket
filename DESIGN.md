# Playoff Bracket — Design & Roadmap

## Overview

A family-facing NHL playoff prediction and competition site. Users submit bracket predictions at the start of the playoffs, compete on a leaderboard, and optionally make per-game side wagers using a fake currency (DucksBucks). Target audience: Nick's family. Target season: 2027 NHL playoffs (built and tested against 2026 data).

## Stack

- **Backend:** FastAPI + SQLModel (SQLite via `bracket.db`)
- **Frontend:** Jinja2 templates + Tailwind CSS (CDN) + Alpine.js + HTMX
- **Auth:** Google OAuth via `authlib` + Starlette `SessionMiddleware`
- **Data source:** NHL public API (`https://api-web.nhle.com/v1/playoff-bracket/{year}`)

---

## What's Built

### Data layer
- `Season` — year, is_current; multi-season support via `?year=` query param
- `Team` — seeded from NHL API; has `api_id`, `abbrev`, `logo_url`, `dark_logo_url`
- `TeamStats` — wins, losses, OT losses, points, goal differential; seeded from standings API
- `Series` — `conference`, `series_abbrev`, `series_letter`, `playoff_round`, `top_seed_team`, `bottom_seed_team`, `winner`, `top_seed_wins`, `bottom_seed_wins`, `season_id` FK
- `User` — `name`, `email` (unique); upserted by email on Google OAuth callback
- `Prediction` — `user_id`, `series_id`, `predicted_winner_id`; unique on `(user_id, series_id)`; locked on submit (no editing)
- `ScoringConfig` — `season_year`, `series_abbrev`, `points`; seeded 1/2/3/4 per R1/R2/CF/SCF (26 pts total)

### Services layer (`services.py`)
Split into two categories to prevent N+1 queries:
- **Query functions** (take `session`, touch DB): `fetch_current_season`, `fetch_season_by_year`, `fetch_all_users`, `fetch_predictions`, `fetch_predictions_for_season`, `fetch_series_results`, `fetch_scoring`, `get_predictions_map`, `has_prediction`, `save_prediction`
- **Computation functions** (pure data, no session): `score_bracket`, `build_leaderboard`

### Routes
- `/` — live NHL bracket (horizontal 7-column desktop, stacked round-by-round mobile)
- `/bracket` — user's own prediction results with score; redirects to `/predict` if no picks yet
- `/predict` — Alpine.js cascade bracket picker; single JSON POST of all 15 picks
- `/leaderboard` — ranked by score, links to compare view for other users
- `/compare/{user_id}` — side-by-side pick comparison with agree/disagree coloring
- `/teams` — flip-card grid (logo → season stats)
- `/about` — how-to-play staggered card layout
- `/login` — login page (renders template, no auto-redirect)
- `/login/google` — initiates Google OAuth flow
- `/auth/callback` — OAuth callback; upserts User, sets session
- `/logout` — clears session, redirects to `/about`

### Background sync
- `do_sync()` polls NHL API and calls `update_series_results()` as a background task
- Runs on first request after startup or after 20-minute stale interval
- `is_syncing` flag prevents duplicate concurrent syncs
- Full seed runs at startup lifespan if `Series` table is empty

### Frontend
- Glassmorphism design: `bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl`
- `base.html` exposes `{% block navbar %}`, `{% block title %}`, `{% block content %}`
- Login page overrides `{% block navbar %}` to hide nav entirely
- Fade-in animations (`animate-fade-in`, `delay-150/300/500`) defined in `base.html`
- Alpine.js for interactive state (bracket picker cascade, mobile hamburger menu, flip cards)
- Mobile hamburger nav with `x-transition` dropdown; desktop icon nav with hover tooltips
- Bracket: `lg:hidden` stacked list view + `hidden lg:block` horizontal tree that fits viewport height (`calc(100vh - 7rem)`)

### Assets & PWA
- `static/logo.svg` — transparent-background shield/sticks/trophy logo (navbar, login page)
- `static/icon.svg` — 512×512 dark rounded-rect app icon (favicon, apple-touch-icon, PWA)
- `static/manifest.json` — PWA manifest; `display: standalone`, `theme_color: #1d4ed8`
- `base.html` includes `<link rel="manifest">`, `<link rel="icon">`, `<meta name="apple-mobile-web-app-capable">`, `theme-color`

---

## Template Architecture

### Component reuse (macros)
Jinja2 macros are the Svelte-component equivalent — parameterized, reusable HTML chunks. The `series_card(s, teams, delay)` macro in `bracket.html` is the main example, accepting an animation delay for per-card stagger.

### CSS strategy
- Tailwind utility classes for everything layout/color/spacing
- Animations (`fadeIn` keyframe, `.animate-fade-in`, `.delay-*`) defined once in `base.html <style>`
- Page-specific `<style>` blocks acceptable for non-reusable CSS (e.g. card flip in `teams.html`)

---

## Key Design Decisions

**`series_abbrev` and `conference` instead of `playoff_round`**
The NHL API's `playoffRound` field is unreliable — Conference Finals and the Stanley Cup Final both return `playoffRound: 2`. `seriesAbbrev` (R1/R2/CF/SCF) and `conference` are the reliable signals.

**`team_map` dict instead of SQLModel Relationships**
`Series` has three FK columns pointing at `Team` (top seed, bottom seed, winner). SQLAlchemy requires explicit `foreign_keys` disambiguation for multiple FKs to the same table — more ceremony than it's worth. A simple `{team.id: team}` dict passed from the route is cleaner.

**Per-series prediction rows**
One row per user per series (rather than one row per complete bracket) makes scoring, leaderboard queries, and the compare-brackets feature clean and simple.

**Services split: query vs computation**
All DB access is explicit in route handlers via query functions. Computation functions take plain data and have no session — this makes N+1 bugs visible at the call site and keeps the functions easily testable.

---

## Roadmap

### ✅ Phase 1 — Predictions
- Per-series `Prediction` model, locked on submit
- `ScoringConfig` table seeded 1/2/3/4 per round
- Scoring logic compares predictions against actual `winner` field

### ✅ Phase 2 — Users & Auth
- `User` model; Google OAuth; session cookie
- Predictions associated with users and season

### ✅ Phase 3 — Leaderboard & Compare
- Leaderboard ranked by score, current user highlighted
- Compare page: side-by-side picks with agree/disagree row tinting
- Multi-season support via `?year=` query param

### ✅ Phase 4 — Polish & Mobile
- Full mobile audit and rewrite: hamburger nav, stacked bracket, responsive headings
- Glassmorphism redesign across all pages
- SVG logo + PWA manifest + favicon
- Login page (no more auto-OAuth redirect)
- Per-card stagger fade-in animations on bracket

### Phase 5 — DucksBucks (fake wagering)

Independent from the bracket leaderboard. See detailed design below.

#### Balance & Ledger
- Add `ducksbucks: int = 0` to `User` model
- Add `Transaction` model: `user_id`, `amount` (positive = credit, negative = debit), `description`, `created_at`
- Transaction types (string or enum): `SIGNUP_BONUS`, `BRACKET_BONUS`, `SEASON_WIN`, `CHALLENGE_WIN`, `CHALLENGE_LOSS`, `CHALLENGE_REFUND`
- Award hooks: signup bonus in `auth_callback`, bracket bonus in `submit_predictions`, season prize via a manual admin endpoint gated to admin user

#### Game Ingestion
- `Game` model: `game_id` (NHL API id), `home_team_id`, `away_team_id`, `date`, `status` (scheduled/live/final), `home_score`, `away_score`, `home_sog`, `away_sog` (nullable — for props bets, worth adding now to avoid a migration later)
- Background task on the same pattern as series sync — daily refresh of that day's schedule
- Settlement job: when a game goes final, find all `accepted` challenges for that game and resolve them, crediting the winner and debiting the loser via `Transaction` rows

#### Challenge Model
Single `Challenge` table — no polymorphism needed:
- `challenger_id`, `challenged_id` — FK to `User`
- `game_id` — FK to `Game`
- `wager` — integer DucksBucks amount
- `status` — `pending` / `accepted` / `rejected` / `settled`
- `bet_type` — enum: `MONEYLINE` | `SPREAD` | `TOTAL_GOALS` | `TOTAL_SOG`
- `line` — decimal (null for moneyline); the spread margin or over/under threshold
- `challenger_side` — which way the challenger is taking (home/away for moneyline; over/under for totals; team + direction for spread)
- `challenged_side` — auto-set to the opposite on accept
- `created_at`

#### Bet Types
1. **Moneyline** — pick home or away to win; trivial to settle
2. **Spread** — pick a team to win by more than N goals; use .5 lines always to avoid push (e.g. "EDM -1.5" means EDM must win by 2+)
3. **Total Goals** — over/under N total goals in game; use .5 lines
4. **Total SOG** — over/under N total shots; validate NHL API provides this reliably before building

All bets pay 1:1 (challenger wins → gets `wager` DucksBucks from challenged, and vice versa). No fractional odds to start.

#### UX Notes
- Validate balance on **accept** not propose — prevents a user proposing challenges they can't cover while waiting for another to settle
- `.5` lines everywhere eliminates push edge case
- Challenge indicator: inject `pending_challenge_count` into every authenticated template context; show a red dot badge on a "Challenges" nav icon when > 0
- HTMX polling: `hx-get="/challenges/count" hx-trigger="every 60s"` on the badge element keeps it live
- Email (optional): Resend free tier (3k/month), single `requests.post()` call; daily digest preferred over per-challenge noise

#### Build Order
1. `ducksbucks` field + `Transaction` model + award hooks in existing routes
2. `Game` model + daily ingestion task + settlement background task
3. Moneyline challenges — propose/accept/reject UI + settle on game final
4. Spread bets (small addition once moneyline works)
5. Props bets — only after confirming NHL API SOG data quality
6. Notification badge + HTMX polling

---

## NHL API Notes

- Bracket endpoint: `https://api-web.nhle.com/v1/playoff-bracket/{year}`
- Schedule endpoint (for game ingestion): `https://api-web.nhle.com/v1/schedule/{date}` (date format: YYYY-MM-DD)
- `playoffRound` is unreliable for later rounds (all return 2); use `seriesAbbrev` instead
- `seriesLetter` ordering: A–D East R1, E–H West R1, I–J East R2, K–L West R2, M East CF, N West CF, O SCF
- TBD teams have `id: -1` in the API — filter these out when seeding
- SOG data availability in schedule API: verify before building props bets
