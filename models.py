from sqlmodel import SQLModel, Field


class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    api_id: int
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
    wins: int
    losses: int
    ot_losses: int
    goals: int
    goals_against: int


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
