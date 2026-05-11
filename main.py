from sqlmodel import create_engine, SQLModel, Session, select
from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks
from datetime import datetime, timedelta
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
from services import (
    has_prediction,
    save_prediction,
    score_bracket,
    build_leaderboard,
    get_predictions_map,
    fetch_predictions,
    fetch_all_users,
    fetch_predictions_for_season,
    fetch_series_results,
    fetch_scoring,
    fetch_current_season,
    fetch_season_by_year,
)
from pydantic import BaseModel

import os
from dotenv import load_dotenv
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
from models import Team, TeamStats, Series, Season, User, Prediction, ScoringConfig

load_dotenv()
engine = create_engine("sqlite:///bracket.db")
templates = Jinja2Templates(directory="templates")


def create_db():
    SQLModel.metadata.create_all(engine)


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
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET_KEY"])
secret_key = os.environ["SESSION_SECRET_KEY"]

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
async def login_page(request: Request):
    if request.session.get("user_id"):
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
        context={"bracket": bracket, "teams": team_map, "season": season},
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
        request=request, name="teams.html", context={"teams": teams, "stats": stats_map}
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
        request=request, name="predict.html", context={"series_data": series_data}
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
        context={"board": board, "current_user": user, "season": season},
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
        context={"rounds": rounds, "me": user, "them": other_user, "season": season},
    )


@app.get("/hello")
async def hello():
    return HTMLResponse("<p>Hello world!</p>")


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request=request, name="about.html")
