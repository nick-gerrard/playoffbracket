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
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from services import (
    daily_job,
    has_prediction,
    save_prediction,
    score_bracket,
    build_leaderboard,
    get_predictions_map,
    signup_bonus,
    bracket_bonus,
    ingest_games,
    fetch_predictions,
    fetch_all_users,
    fetch_all_transactions,
    fetch_predictions_for_season,
    fetch_series_results,
    fetch_scoring,
    fetch_current_season,
    fetch_season_by_year,
    fetch_games,
    fetch_bets_for_user,
    issue_bet,
    accept_bet,
    transaction,
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()


load_dotenv()
engine = create_engine("sqlite:///bracket.db")
templates = Jinja2Templates(directory="templates")

ET = timezone(timedelta(hours=-4))
templates.env.filters["et"] = lambda dt: dt.astimezone(ET).strftime("%-I:%M %p ET")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")


def challenge_count(user_id: int) -> int:
    with Session(engine) as session:
        return len(list(session.exec(
            select(Bet).where(Bet.challengee == user_id, Bet.status == "pending")
        ).all()))


templates.env.globals["challenge_count"] = challenge_count
templates.env.globals["admin_email"] = ADMIN_EMAIL


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


ROUND_LABELS = {
    1: "First Round",
    2: "Second Round",
    3: "Conference Finals",
    4: "Stanley Cup Final",
}


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
        user = session.exec(select(User).where(User.email == info["email"])).first()
        if not user:
            user = User(name=info["name"], email=info["email"])
            session.add(user)
            session.commit()
            session.refresh(user)
            signup_bonus(session=session, payee_id=user.id, amount=signup_bonus_val)
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
        all_series = session.exec(
            select(Series).where(Series.season_id == season.id)
        ).all()
        team_map = {t.id: t for t in session.exec(select(Team)).all()}
        series_results = fetch_series_results(session, season.id)
        scoring = fetch_scoring(session, season.year)
        pred_map = {p.series_id: p.predicted_winner_id for p in predictions}
        total_score = score_bracket(predictions, series_results, scoring)

    rounds: dict = {}
    for s in sorted(all_series, key=lambda x: (x.playoff_round, x.series_letter)):
        entry = {
            "title": s.title,
            "letter": s.series_letter,
            "top_team": team_map.get(s.top_seed_team),
            "bottom_team": team_map.get(s.bottom_seed_team),
            "predicted_winner": team_map.get(pred_map.get(s.id)),  # type: ignore
            "actual_winner": team_map.get(s.winner) if s.winner else None,
            "status": (
                "correct"
                if s.winner and s.winner == pred_map.get(s.id)
                else "wrong"
                if s.winner and s.winner != pred_map.get(s.id)
                else "pending"
            ),
            "points": scoring.get(s.series_abbrev, 0),
        }
        rounds.setdefault(ROUND_LABELS[s.playoff_round], []).append(entry)

    return templates.TemplateResponse(
        request=request,
        name="my_bracket.html",
        context={
            "rounds": rounds,
            "total_score": total_score,
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
        if has_prediction(session, user.id, season.id):
            return RedirectResponse("/bracket")
        all_series = session.exec(
            select(Series).where(Series.season_id == season.id)
        ).all()
        team_map = {t.id: t for t in session.exec(select(Team)).all()}

    series_data = {}
    for s in all_series:
        top = team_map.get(s.top_seed_team)
        bottom = team_map.get(s.bottom_seed_team)
        series_data[s.series_letter] = {
            "id": s.id,
            "letter": s.series_letter,
            "top": {"id": top.id, "abbrev": top.abbrev, "logo": top.dark_logo_url}
            if top
            else None,
            "bottom": {
                "id": bottom.id,
                "abbrev": bottom.abbrev,
                "logo": bottom.dark_logo_url,
            }
            if bottom
            else None,
        }

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
        if has_prediction(session, user.id, season.id):
            return RedirectResponse("/bracket", status_code=303)
        save_prediction(session, user.id, [p.model_dump() for p in predictions])
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
        board = build_leaderboard(users, all_predictions, series_results, scoring)
    return templates.TemplateResponse(
        request=request,
        name="leaderboard.html",
        context={"board": board, "current_user": user, "user": user, "season": season},
    )


@app.get("/compare/{other_user_id}")
async def compare(
    request: Request,
    other_user_id: int,
    user: User | None = Depends(get_current_user),
    year: int | None = None,
):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        season = resolve_season(session, year)
        other_user = session.get(User, other_user_id)
        if not other_user:
            return RedirectResponse("/leaderboard")
        my_preds = get_predictions_map(session, user.id, season.id)
        their_preds = get_predictions_map(session, other_user_id, season.id)
        if not my_preds or not their_preds:
            return RedirectResponse("/leaderboard")
        all_series = session.exec(
            select(Series).where(Series.season_id == season.id)
        ).all()
        team_map = {t.id: t for t in session.exec(select(Team)).all()}

    rounds: dict = {}
    for s in sorted(all_series, key=lambda x: (x.playoff_round, x.series_letter)):
        my_pick_id = my_preds.get(s.id)
        their_pick_id = their_preds.get(s.id)
        entry = {
            "letter": s.series_letter,
            "top_team": team_map.get(s.top_seed_team),
            "bottom_team": team_map.get(s.bottom_seed_team),
            "my_pick": team_map.get(my_pick_id),
            "their_pick": team_map.get(their_pick_id),
            "match": (my_pick_id == their_pick_id)
            if (my_pick_id and their_pick_id)
            else None,
            "actual_winner": team_map.get(s.winner) if s.winner else None,
        }
        rounds.setdefault(ROUND_LABELS[s.playoff_round], []).append(entry)

    return templates.TemplateResponse(
        request=request,
        name="compare.html",
        context={
            "rounds": rounds,
            "me": user,
            "them": other_user,
            "user": user,
            "season": season,
        },
    )


@app.get("/bets")
async def bets_page(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        today_games = fetch_games(session, date.today())
        team_map = {t.id: t for t in session.exec(select(Team)).all()}
        all_users = fetch_all_users(session)
        user_map = {u.id: u for u in all_users}
        open_challenges = list(
            session.exec(
                select(Bet).where(Bet.challengee == user.id, Bet.status == "pending")
            ).all()
        )
        my_pending = list(
            session.exec(
                select(Bet).where(Bet.challenger == user.id, Bet.status == "pending")
            ).all()
        )
        active_bets = [
            b for b in fetch_bets_for_user(session, user.id) if b.status == "accepted"
        ]
    return templates.TemplateResponse(
        request=request,
        name="bets.html",
        context={
            "user": user,
            "games": today_games,
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
    except ValueError:
        return RedirectResponse("/bets?error=insufficient_balance", status_code=303)
    return RedirectResponse("/bets", status_code=303)


@app.get("/admin")
async def admin_dashboard(request: Request, admin: User = Depends(require_admin)):
    with Session(engine) as session:
        users = fetch_all_users(session)
        recent_transactions = list(reversed(fetch_all_transactions(session)))[:20]
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={"user": admin, "users": users, "transactions": recent_transactions},
    )


@app.post("/admin/credit")
async def admin_credit(
    admin: User = Depends(require_admin),
    user_id: int = Form(...),
    amount: int = Form(...),
    desc: str = Form(...),
):
    with Session(engine) as session:
        transaction(session, amount=amount, payee_id=user_id, desc=desc)
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
