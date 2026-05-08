from sqlmodel import create_engine, SQLModel
from fastapi import FastAPI
from contextlib import asynccontextmanager
from models import Team, TeamStats, Series, Season

engine = create_engine("sqlite:///bracket.db")


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
