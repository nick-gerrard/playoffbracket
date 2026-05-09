from sqlmodel import create_engine, SQLModel, Session, select
from fastapi import FastAPI
from contextlib import asynccontextmanager
from models import Team, TeamStats, Series, Season
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi import Request

engine = create_engine("sqlite:///bracket.db")
templates = Jinja2Templates(directory="templates")


def create_db():
    SQLModel.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "hello world"}


@app.get("/bracket")
async def bracket(request: Request):
    with Session(engine) as session:
        series = session.exec(select(Series)).all()
    return templates.TemplateResponse(
        request=request, name="bracket.html", context={"series": series}
    )


@app.get("/teams")
async def teams(request: Request):
    with Session(engine) as session:
        teams = session.exec(select(Team)).all()
    return templates.TemplateResponse(
        request=request, name="teams.html", context={"teams": teams}
    )


@app.get("/hello")
async def hello():
    return HTMLResponse("<p>Hello world!</p>")


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request=request, name="about.html")
