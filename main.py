from sqlmodel import create_engine, SQLModel, Session, select
from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks, Form
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import datetime, timedelta, date, timezone
from seed import (
    get_series_data,
    update_series_results,
    URL,
    get_team_stats_data,
    seed_season,
    seed_teams,
    seed_series,
    seed_scoring_config,
    seed_standings_data,
    STANDINGS,
)
from contextlib import asynccontextmanager
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from services import (
    ET,
    daily_job,
    has_prediction,
    save_prediction,
    score_bracket,
    compute_max_possible,
    build_leaderboard,
    build_bracket_rounds,
    build_compare_rounds,
    build_series_picker,
    get_predictions_map,
    bracket_bonus,
    ingest_games,
    fetch_predictions,
    fetch_all_users,
    fetch_predictions_for_season,
    fetch_series_results,
    fetch_scoring,
    fetch_current_season,
    fetch_season_by_year,
    fetch_todays_games,
    fetch_users_by_balance,
    fetch_recent_transactions,
    fetch_pending_challenges,
    fetch_pending_issued,
    fetch_active_bets,
    count_pending_challenges,
    issue_bet,
    accept_bet,
    decline_bet,
    record_transaction,
    toggle_picks_open,
    get_or_create_user,
)
from pydantic import BaseModel

import os
from dotenv import load_dotenv
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
from models import (
    Bet,
    Team,
    TeamStats,
    Series,
    Season,
    User,
)
from enums import TransactionKind
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()


load_dotenv()
engine = create_engine("sqlite:///bracket.db")
templates = Jinja2Templates(directory="templates")

templates.env.filters["et"] = lambda dt: (
    dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
).astimezone(ET).strftime("%-I:%M %p ET")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")


def challenge_count(user_id: int) -> int:
    with Session(engine) as session:
        return count_pending_challenges(session, user_id)


def user_has_submitted(user_id: int) -> bool:
    with Session(engine) as session:
        season = fetch_current_season(session)
        if not season:
            return False
        return has_prediction(session, user_id, season.id)


def picks_open() -> bool:
    with Session(engine) as session:
        season = fetch_current_season(session)
        return bool(season and season.picks_open)


templates.env.globals["challenge_count"] = challenge_count
templates.env.globals["user_has_submitted"] = user_has_submitted
templates.env.globals["admin_email"] = ADMIN_EMAIL
templates.env.globals["picks_open"] = picks_open


def create_db():
    SQLModel.metadata.create_all(engine)


def run_daily_job():
    with Session(engine) as session:
        daily_job(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    with Session(engine) as session:
        if not session.exec(select(Series)).first():
            series_data = get_series_data(URL)
            season = seed_season()
            seed_teams(series_data)
            seed_series(series_data, season.id)
            seed_scoring_config()
            stats = get_team_stats_data(STANDINGS)
            seed_standings_data(stats)
        ingest_games(session, date.today())
    scheduler.add_job(
        run_daily_job, CronTrigger(hour=7, minute=0, timezone="America/New_York")
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET_KEY"])
secret_key = os.environ["SESSION_SECRET_KEY"]

# Bonus values from env
signup_bonus_val = int(os.environ.get("SIGNUP_BONUS_VAL", 0))
bracket_bonus_val = int(os.environ.get("BRACKET_BONUS_VAL", 0))

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    client_kwargs={"scope": "openid email profile"},
)


def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with Session(engine) as session:
        return session.get(User, user_id)


def require_admin(user: User | None = Depends(get_current_user)):
    if not user or user.email != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


last_synced: datetime | None = None
is_syncing: bool = False
SYNC_INTERVAL = timedelta(minutes=20)


def do_sync() -> None:
    global last_synced, is_syncing
    is_syncing = True
    try:
        series_data = get_series_data(URL)
        with Session(engine) as session:
            season = fetch_current_season(session)
            if season:
                update_series_results(session, series_data, season.id)
        last_synced = datetime.now()
    except Exception:
        pass
    finally:
        is_syncing = False


def sync_if_stale(background_tasks: BackgroundTasks) -> None:
    if is_syncing:
        return
    if last_synced and datetime.now() - last_synced < SYNC_INTERVAL:
        return
    background_tasks.add_task(do_sync)


def resolve_season(session: Session, year: int | None) -> Season:
    season = (
        fetch_season_by_year(session, year) if year else fetch_current_season(session)
    )
    if not season:
        raise HTTPException(status_code=404, detail="Season not found")
    return season



@app.get("/login")
async def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/")
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    info = token["userinfo"]
    with Session(engine) as session:
        user, _ = get_or_create_user(session, email=info["email"], name=info["name"], bonus_amount=signup_bonus_val)
        request.session["user_id"] = user.id
    return RedirectResponse("/bracket")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/")
async def root(
    request: Request,
    background_tasks: BackgroundTasks,
    user: User | None = Depends(get_current_user),
    year: int | None = None,
):
    if not user:
        return RedirectResponse("/login")
    sync_if_stale(background_tasks)
    with Session(engine) as session:
        season = resolve_season(session, year)
        series = session.exec(select(Series).where(Series.season_id == season.id)).all()
        team_map = {t.id: t for t in session.exec(select(Team)).all()}

    bracket = {"West": {}, "East": {}, "Final": None}
    for s in series:
        if s.conference == "Final":
            bracket["Final"] = s
        else:
            bracket[s.conference].setdefault(s.series_abbrev, []).append(s)  # type: ignore

    return templates.TemplateResponse(
        request=request,
        name="bracket.html",
        context={"bracket": bracket, "teams": team_map, "season": season, "user": user},
    )


@app.get("/user_info")
async def user_info(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/")
    with Session(engine) as session:
        return templates.TemplateResponse(
            request=request, name="user.html", context={"user": user}
        )


@app.get("/bracket")
async def bracket(
    request: Request,
    user: User | None = Depends(get_current_user),
    year: int | None = None,
):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        season = resolve_season(session, year)
        predictions = fetch_predictions(session, user.id, season.id)
        if not predictions and not year:
            return RedirectResponse("/predict")
        all_series = list(session.exec(
            select(Series).where(Series.season_id == season.id)
        ).all())
        team_map = {t.id: t for t in session.exec(select(Team)).all()}
        series_results = fetch_series_results(session, season.id)
        scoring = fetch_scoring(session, season.year)
        total_score = score_bracket(predictions, series_results, scoring)
        max_possible = compute_max_possible(predictions, all_series, series_results, scoring)
        rounds = build_bracket_rounds(predictions, all_series, series_results, team_map, scoring)

    return templates.TemplateResponse(
        request=request,
        name="my_bracket.html",
        context={
            "rounds": rounds,
            "total_score": total_score,
            "max_possible": max_possible,
            "user": user,
            "season": season,
        },
    )


@app.get("/teams")
async def teams(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        teams = session.exec(select(Team).where(Team.name != "TBD")).all()
        stats_map = {s.team_id: s for s in session.exec(select(TeamStats)).all()}
    return templates.TemplateResponse(
        request=request,
        name="teams.html",
        context={"teams": teams, "stats": stats_map, "user": user},
    )


class PredictionIn(BaseModel):
    series_id: int
    winner_id: int


@app.get("/predict")
async def predict(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        season = fetch_current_season(session)
        if not season:
            raise HTTPException(status_code=404, detail="No active season")
        if not season.picks_open:
            return RedirectResponse("/")
        if has_prediction(session, user.id, season.id):
            return RedirectResponse("/bracket")
        all_series = list(session.exec(
            select(Series).where(Series.season_id == season.id)
        ).all())
        team_map = {t.id: t for t in session.exec(select(Team)).all()}
        series_data = build_series_picker(all_series, team_map)

    return templates.TemplateResponse(
        request=request,
        name="predict.html",
        context={"series_data": series_data, "user": user},
    )


@app.post("/predict")
async def submit_predictions(
    predictions: list[PredictionIn],
    user: User | None = Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if len(predictions) != 15:
        raise HTTPException(
            status_code=400, detail="Must submit exactly 15 predictions"
        )
    with Session(engine) as session:
        season = fetch_current_season(session)
        if not season:
            raise HTTPException(status_code=404, detail="No active season")
        if not season.picks_open:
            raise HTTPException(status_code=403, detail="Bracket submissions are closed")
        if has_prediction(session, user.id, season.id):
            return RedirectResponse("/bracket", status_code=303)
        save_prediction(session, user.id, [p.model_dump() for p in predictions])
        bracket_bonus(session, payee_id=user.id, amount=bracket_bonus_val)
    return RedirectResponse("/bracket", status_code=303)


@app.get("/leaderboard")
async def leaderboard(
    request: Request,
    user: User | None = Depends(get_current_user),
    year: int | None = None,
):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        season = resolve_season(session, year)
        users = fetch_all_users(session)
        all_predictions = fetch_predictions_for_season(session, season.id)
        series_results = fetch_series_results(session, season.id)
        scoring = fetch_scoring(session, season.year)
        all_series = list(session.exec(select(Series).where(Series.season_id == season.id)).all())
        board = build_leaderboard(users, all_predictions, series_results, scoring, all_series)
    return templates.TemplateResponse(
        request=request,
        name="leaderboard.html",
        context={"board": board, "current_user": user, "user": user, "season": season},
    )


@app.get("/compare")
async def compare(
    request: Request,
    user: User | None = Depends(get_current_user),
    a: int | None = None,
    b: int | None = None,
    year: int | None = None,
):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        season = resolve_season(session, year)
        all_series = list(session.exec(select(Series).where(Series.season_id == season.id)).all())
        team_map = {t.id: t for t in session.exec(select(Team)).all()}
        all_predictions = fetch_predictions_for_season(session, season.id)
        pred_user_ids = {p.user_id for p in all_predictions}
        pred_users = [u for u in fetch_all_users(session) if u.id in pred_user_ids]

        rounds = None
        user_a = user_b = None
        if a and b:
            user_a = session.get(User, a)
            user_b = session.get(User, b)
            if user_a and user_b:
                preds_a = get_predictions_map(session, a, season.id)
                preds_b = get_predictions_map(session, b, season.id)
                rounds = build_compare_rounds(all_series, preds_a, preds_b, team_map)

    return templates.TemplateResponse(
        request=request,
        name="compare.html",
        context={
            "user": user,
            "user_a": user_a,
            "user_b": user_b,
            "pred_users": pred_users,
            "selected_a": a,
            "selected_b": b,
            "rounds": rounds,
            "season": season,
        },
    )


@app.get("/bets")
async def bets_page(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        today_games, bettable_ids = fetch_todays_games(session)
        team_map = {t.id: t for t in session.exec(select(Team)).all()}
        all_users = fetch_all_users(session)
        user_map = {u.id: u for u in all_users}
        open_challenges = fetch_pending_challenges(session, user.id)
        my_pending = fetch_pending_issued(session, user.id)
        active_bets = fetch_active_bets(session, user.id)
    return templates.TemplateResponse(
        request=request,
        name="bets.html",
        context={
            "user": user,
            "games": today_games,
            "bettable_ids": bettable_ids,
            "team_map": team_map,
            "users": [u for u in all_users if u.id != user.id],
            "user_map": user_map,
            "open_challenges": open_challenges,
            "my_pending": my_pending,
            "active_bets": active_bets,
        },
    )


@app.post("/bets/challenge")
async def post_challenge(
    request: Request,
    user: User | None = Depends(get_current_user),
    game_id: int = Form(...),
    challengee_id: int = Form(...),
    winner_id: int = Form(...),
    amount: int = Form(...),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        with Session(engine) as session:
            issue_bet(
                session,
                challenger=user.id,
                challengee=challengee_id,
                amount=amount,
                game_id=game_id,
                winner_id=winner_id,
            )
    except ValueError:
        return RedirectResponse("/bets?error=insufficient_balance", status_code=303)
    return RedirectResponse("/bets", status_code=303)


@app.post("/bets/accept/{bet_id}")
async def post_accept(
    request: Request,
    bet_id: int,
    user: User | None = Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        with Session(engine) as session:
            accept_bet(session, bet_id=bet_id, challengee=user.id)
    except ValueError as e:
        return RedirectResponse(f"/bets?error={e}", status_code=303)
    return RedirectResponse("/bets", status_code=303)


@app.post("/bets/decline/{bet_id}")
async def post_decline(
    request: Request,
    bet_id: int,
    user: User | None = Depends(get_current_user),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    with Session(engine) as session:
        decline_bet(session, bet_id=bet_id, challengee=user.id)
    return RedirectResponse("/bets", status_code=303)


@app.get("/admin")
async def admin_dashboard(request: Request, admin: User = Depends(require_admin)):
    with Session(engine) as session:
        users = fetch_all_users(session)
        recent_transactions = fetch_recent_transactions(session)
        season = fetch_current_season(session)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={"user": admin, "users": users, "transactions": recent_transactions,
                 "season": season},
    )


@app.post("/admin/credit")
async def admin_credit(
    admin: User = Depends(require_admin),
    user_id: int = Form(...),
    amount: int = Form(...),
    desc: str = Form(...),
):
    with Session(engine) as session:
        record_transaction(session, amount=amount, kind=TransactionKind.ADMIN_CREDIT, payee_id=user_id, note=desc)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/bracket-bonus")
async def admin_bracket_bonus(
    admin: User = Depends(require_admin),
    user_id: int = Form(...),
    amount: int = Form(...),
):
    with Session(engine) as session:
        bracket_bonus(session, payee_id=user_id, amount=amount)
    return RedirectResponse("/admin", status_code=303)


@app.get("/vault")
async def vault(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        users = fetch_users_by_balance(session)
    return templates.TemplateResponse(
        request=request,
        name="vault.html",
        context={"user": user, "users": users},
    )


@app.post("/admin/toggle-picks")
async def admin_toggle_picks(admin: User = Depends(require_admin)):
    with Session(engine) as session:
        toggle_picks_open(session)
    return RedirectResponse("/admin", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    try:
        user = get_current_user(request)
    except Exception:
        user = None
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"user": user, "code": exc.status_code, "message": exc.detail},
        status_code=exc.status_code,
    )




@app.get("/about")
async def about(request: Request, user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(
        request=request, name="about.html", context={"user": user}
    )
