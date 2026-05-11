from sqlmodel import create_engine, SQLModel, Session, select
from fastapi import FastAPI, Request, Depends
from contextlib import asynccontextmanager
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

import os
from dotenv import load_dotenv
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
from models import Team, TeamStats, Series, Season, User

load_dotenv()
engine = create_engine("sqlite:///bracket.db")
templates = Jinja2Templates(directory="templates")


def create_db():
    SQLModel.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
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


@app.get("/login")
async def login(request: Request):
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
    return RedirectResponse("/login")


@app.get("/")
async def root():
    return RedirectResponse("/about")


@app.get("/bracket")
async def bracket(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        series = session.exec(select(Series)).all()
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
        context={"bracket": bracket, "teams": team_map},
    )


@app.get("/teams")
async def teams(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")
    with Session(engine) as session:
        teams = session.exec(select(Team)).all()
        stats_map = {s.team_id: s for s in session.exec(select(TeamStats)).all()}
    return templates.TemplateResponse(
        request=request, name="teams.html", context={"teams": teams, "stats": stats_map}
    )


@app.get("/hello")
async def hello():
    return HTMLResponse("<p>Hello world!</p>")


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request=request, name="about.html")
