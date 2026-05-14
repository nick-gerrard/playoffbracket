# Playoff Bracket — Design & Roadmap

## Overview

A family-facing NHL playoff prediction and competition site. Users submit bracket predictions at the start of the playoffs, compete on a leaderboard, and optionally make per-game side wagers using a fake currency (DucksBucks). Target audience: Nick's family. Target season: 2027 NHL playoffs (built and tested against 2026 data).

## Stack

- **Backend:** FastAPI + SQLModel (SQLite via `bracket.db`)
- **Frontend:** Jinja2 templates + Tailwind CSS (CDN) + Alpine.js + HTMX
- **Auth:** Google OAuth via `authlib` + Starlette `SessionMiddleware`
- **Data source:** NHL public API (`https://api-web.nhle.com/v1/`)

---

## What's Built

### Data layer
- `Season` — year; multi-season support via `?year=` query param
- `Team` — seeded from NHL API; `api_id`, `abbrev`, `logo_url`, `dark_logo_url`
- `TeamStats` — wins, losses, OT losses, points, goal differential; seeded from standings API
- `Series` — `conference`, `series_abbrev` (SeriesRound enum), `series_letter`, `playoff_round`, `top_seed_team`, `bottom_seed_team`, `winner`, `top_seed_wins`, `bottom_seed_wins`, `season_id` FK
- `Game` — `api_id`, `date`, `start_time`, `home_team`, `away_team`, `status` (GameStatus enum: FUT/OFF), `home_team_score`, `away_team_score`, `winner`, `outcome` (GameOutcome enum: REG/OT)
- `User` — `name`, `email` (unique), `balance: int`; upserted by email on Google OAuth callback
- `Prediction` — `user_id`, `series_id`, `predicted_winner_id`; unique on `(user_id, series_id)`; locked on submit
- `ScoringConfig` — `season_year`, `series_abbrev`, `points`; seeded 1/2/3/4 per R1/R2/CF/SCF (26 pts total max)
- `Bet` — `challenger`, `challengee`, `challenger_winner`, `amount`, `status` (BetStatus enum: pending/accepted/settled/cancelled)
- `Transaction` — `payer`, `payee`, `amount`, `desc`, `bet_id`; both sides nullable for escrow/unilateral credits

### Enums (`enums.py`)
All magic strings centralised as `StrEnum` (values ARE strings — SQLite stores them as plain strings, existing rows unaffected):
- `BetStatus` — PENDING / ACCEPTED / SETTLED / CANCELLED
- `GameStatus` — FUT / OFF
- `GameOutcome` — REG / OT
- `SeriesRound` — R1 / R2 / ECF / WCF / SCF
- `TransactionKind` — SIGNUP_BONUS / BET_ESCROW / BET_WIN / BET_REFUND / ADMIN_CREDIT / BRACKET_BONUS

### Services layer (`services.py`)
Split into two categories to prevent N+1 queries:
- **Query functions** (take `session`, touch DB): `fetch_*` family
- **Computation functions** (pure data, no session): `score_bracket`, `build_leaderboard`
- **Mutation functions**: `record_transaction`, `issue_bet`, `accept_bet`, `settle_bets`, `signup_bonus`, `bracket_bonus`

`record_transaction(session, amount, kind, payee_id, payer_id, bet_id, note)` — generates human-readable descriptions automatically from `TransactionKind` via `match`; `note` overrides for admin credits.

### Routes
- `/` — live NHL bracket (horizontal 7-column desktop, stacked round-by-round mobile)
- `/bracket` — user's prediction results with score; redirects to `/predict` if no picks
- `/predict` — Alpine.js cascade bracket picker; single JSON POST of all 15 picks
- `/leaderboard` — ranked by score, links to compare view
- `/compare/{user_id}` — side-by-side pick comparison with agree/disagree row coloring
- `/teams` — flip-card grid (logo → season stats)
- `/bets` — DucksBucks per-game wagering: open challenges, today's games, active bets
- `/admin` — admin dashboard: credit users, award bracket prize, view balances + transactions
- `/about` — how-to-play staggered card layout
- `/login`, `/login/google`, `/auth/callback`, `/logout` — Google OAuth flow

### Background jobs
- Series sync: `do_sync()` polls NHL API every 20 min as a background task
- Game ingestion: `ingest_games(session, date)` runs at startup (today) and via APScheduler at 7AM ET daily (yesterday + today + `settle_bets`)
- `settle_bets`: accepted bets → winner gets 2× pot; pending bets → refunded (escrow is atomic — status update and money movement in one `session.commit()`)

### Frontend
- Glassmorphism: `bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl`
- `base.html` — `{% block navbar %}`, `{% block title %}`, `{% block content %}`
- Jinja2 globals: `challenge_count(user_id)` for notification dots, `admin_email` for admin link gating
- Jinja2 filter: `| et` converts UTC datetime to ET string
- Admin link in profile dropdown, visible only to `ADMIN_EMAIL` env var
- Error pages: `error.html` with glassmorphic card, faded watermark error code; handler on `StarletteHTTPException` (not FastAPI's) to catch unknown routes

### Assets & PWA
- `static/logo.svg` — transparent shield/sticks/trophy (navbar + login)
- `static/icon.svg` — 512×512 rounded-rect app icon (favicon, PWA)
- `static/manifest.json` — `display: standalone`, `theme_color: #1d4ed8`

---

## Template Architecture

### Component reuse
Jinja2 macros are the component equivalent. `series_card(s, teams, delay)` in `bracket.html` is the main example — accepts animation delay for per-card stagger.

### CSS strategy
- Tailwind utility classes for layout/color/spacing
- `fadeIn` keyframe, `.animate-fade-in`, `.delay-*` defined once in `base.html <style>`
- Page-specific `<style>` blocks for non-reusable CSS (card flip in `teams.html`)

---

## Key Design Decisions

**`series_abbrev` and `conference` instead of `playoff_round`**
The NHL API's `playoffRound` field is unreliable — Conference Finals and the Stanley Cup Final both return `playoffRound: 2`. `seriesAbbrev` and `conference` are the reliable signals.

**`team_map` dict instead of SQLModel Relationships**
`Series` has three FK columns pointing at `Team`. SQLAlchemy requires explicit `foreign_keys` disambiguation — more ceremony than it's worth. A `{team.id: team}` dict passed from the route is cleaner.

**Escrow pattern for DucksBucks bets**
Both sides pay into escrow at issue/accept time. Settlement credits winner from escrow. `session.add(bet)` + `record_transaction()` (which calls `session.commit()`) are atomic — one flush covers both status update and money movement.

**StrEnum for all status fields**
`StrEnum` values compare equal to their string equivalents, so SQLite keeps storing plain strings and existing data needs no migration. All magic strings live in `enums.py`.

---

## Roadmap

### ✅ Phase 1 — Predictions
- Per-series `Prediction` model, locked on submit
- `ScoringConfig` table seeded 1/2/3/4 per round
- Scoring logic: compare predictions against actual `winner` field

### ✅ Phase 2 — Users & Auth
- `User` model; Google OAuth; session cookie

### ✅ Phase 3 — Leaderboard & Compare
- Leaderboard ranked by score, current user highlighted
- Compare page: side-by-side picks with agree/disagree row tinting
- Multi-season support via `?year=` query param

### ✅ Phase 4 — Polish & Mobile
- Mobile audit: hamburger nav, stacked bracket, responsive headings
- Glassmorphism redesign across all pages
- SVG logo + PWA manifest + favicon
- Login page, per-card stagger animations

### ✅ Phase 5 — DucksBucks
Moneyline-only P2P wagering on daily NHL games.
- `Game` ingestion from NHL score API; APScheduler daily job at 7AM ET
- `Bet` model with escrow settlement; `Transaction` ledger with auto-generated descriptions via `TransactionKind`
- `/bets` page: issue challenges, accept incoming challenges, view open/active bets
- Admin dashboard: credit users, award bracket bonus, view all balances and recent transactions
- Notification dot on bets nav link (pending challenge count)
- Admin nav link in profile dropdown, gated by `ADMIN_EMAIL` env var
- Error pages for 404/403/500 with glassmorphic design

### Phase 6 — Bracket Intelligence & UX

#### 6a. Hide /predict nav link when bracket is submitted
Currently `/predict` redirects to `/bracket` if predictions exist, but the nav link still shows. Fix: expose a `has_submitted(user_id)` callable as a Jinja2 global (same pattern as `challenge_count`) and conditionally render the predict link in the navbar. Requires passing `season_id` into the global or having it fetch the current season internally.

#### 6b. Show full predicted bracket for TBD series
**Problem:** `/bracket` (my_bracket.html) shows TBD slots for series where actual participants aren't yet determined. But the user made predictions for all 15 series at submission time — they should see their predicted teams regardless of whether those teams have advanced yet.

**Approach:** Build a static `FEEDS_INTO` map (`series_letter → parent_series_letter`, e.g. `"A" → "I"`, `"I" → "M"`, etc.) that encodes the bracket tree. For any series where the actual teams are TBD, reconstruct predicted participants by looking up which earlier series feed into it and using their predicted winners.

Example: Series M (ECF East) — predicted participants = pred[I] vs pred[J]. Series I — predicted participants = pred[A or B winner] vs whatever the user picked from the other R1 matchup feeding into I.

The route builds a `predicted_participants[series_id]` dict for the template alongside the actual series state.

**Open question:** The exact R1→R2 letter pairing (which of A/B/C/D feeds into I vs J) is seeding-dependent. The `child_series` FK on `Series` exists but is currently always `None`. Either populate it during seeding or hardcode the letter map for the known bracket structure.

#### 6c. Max points possible on /bracket
Walk the prediction tree from leaves (R1) upward. A prediction earns points only if the predicted winner is still **alive** — meaning they haven't lost any decided series they participated in.

Algorithm:
```
alive_teams = set of team IDs that have not been eliminated
             (team is eliminated if: they appear in a decided series and winner != them)

for each series in user's predictions:
    if predicted_winner in alive_teams:
        max_possible += points_for_this_round
```

Display alongside current score: `{{ total_score }} pts · {{ max_possible }} possible`

Note: "possible" should also account for downstream impossibility — if you needed Team A to reach series M but Team A was eliminated in R1, series M and O points are both zero regardless of other picks.

#### 6d. Leaderboard: show max possible per user
Same algorithm as 6c, computed in `build_leaderboard` for every user. Adds `max_possible` to each leaderboard entry dict.

Display: score prominently, max possible in a smaller secondary label. Useful for communicating "still in contention" vs "mathematically eliminated from 1st."

Consider sorting: primary sort stays `score`, secondary sort could be `max_possible` as a tiebreaker.

#### 6e. Compare page: any-vs-any with dropdowns
**Current:** `/compare/{user_id}` — always logged-in user vs one other; URL is driven by leaderboard links.

**New:** `/compare?a={id}&b={id}` — two independent user dropdowns, fully open selection (any user vs any user). Leaderboard links become `/compare?a={current_user_id}&b={entry.user.id}` to preserve existing UX as a default state.

Both dropdowns populated with all users who have submitted predictions for the current season. Default state (no params): show the dropdowns with a prompt, no bracket rendered until both are selected. HTMX or a simple form submit (`hx-get="/compare"`) to re-render on selection change works well here.

---

## NHL API Notes

- Bracket: `https://api-web.nhle.com/v1/playoff-bracket/{year}`
- Score/schedule: `https://api-web.nhle.com/v1/score/{date}` — handles both FUT (scheduled) and OFF (final) games in one endpoint
- `playoffRound` is unreliable for later rounds — use `seriesAbbrev` instead
- `seriesLetter` ordering: A–D East R1, E–H West R1, I–J East R2, K–L West R2, M ECF, N WCF, O SCF
- TBD teams have `id: -1` in the API — filter when seeding
- `gameScheduleState != "OK"` games are skipped during ingestion
- Dark logo URL derived from light URL via `.replace("_light", "_dark")`
