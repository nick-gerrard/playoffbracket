from datetime import datetime, timezone, date
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    api_id: int = Field(unique=True)
    name: str
    abbrev: str
    logo_url: str
    dark_logo_url: str


class Season(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    year: int


class TeamStats(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    season: int = Field(foreign_key="season.id")
    points: int
    wins: int
    losses: int
    ot_losses: int
    goal_diff: int


class Series(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    series_letter: str
    conference: str | None = None
    series_abbrev: str | None = None
    top_seed_team: int | None = Field(foreign_key="team.id")
    bottom_seed_team: int | None = Field(foreign_key="team.id")
    top_seed_wins: int = 0
    bottom_seed_wins: int = 0
    winner: int | None = Field(foreign_key="team.id")
    child_series: int | None = Field(foreign_key="series.id")
    playoff_round: int
    season_id: int | None = Field(default=None, foreign_key="season.id")


class Game(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    api_id: int = Field(unique=True)
    date: date
    start_time: datetime
    home_team: int | None = Field(foreign_key="team.id")
    away_team: int | None = Field(foreign_key="team.id")
    status: str = "FUT"
    home_team_score: int | None = None
    away_team_score: int | None = None
    winner: int | None = Field(default=None, foreign_key="team.id")
    outcome: str | None = None  # OT/REG


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True)
    balance: int = 0


class ScoringConfig(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    season_year: int
    series_abbrev: str  # R1/R2/ECF/WCF/SCF
    points: int


class Prediction(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "series_id"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    series_id: int = Field(foreign_key="series.id")
    predicted_winner_id: int = Field(foreign_key="team.id")


class Bet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    game_id: int | None = Field(foreign_key="game.id")
    challenger: int | None = Field(foreign_key="user.id")
    challengee: int | None = Field(foreign_key="user.id")
    challenger_winner: int | None = Field(foreign_key="team.id")
    amount: int
    status: str = "pending"


class Transaction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    bet_id: int | None = Field(default=None, foreign_key="bet.id")
    payer: int | None = Field(foreign_key="user.id")
    payee: int | None = Field(foreign_key="user.id")
    transaction_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    amount: int
    desc: str | None = Field(nullable=True)
