from sqlmodel import create_engine, SQLModel
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
    return templates.TemplateResponse(request=request, name="bracket.html")

@app.get("/hello")
async def hello():
    return HTMLResponse("<p>Hello world!</p>")


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request=request, name="about.html")

