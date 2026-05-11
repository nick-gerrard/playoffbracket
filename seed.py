from sqlmodel import create_engine, Session, select
from models import Team, Series
import httpx
from datetime import datetime
from models import Team, Series, Season, TeamStats, User, ScoringConfig, Prediction
from sqlmodel import SQLModel


engine = create_engine("sqlite:///bracket.db")

YEAR = datetime.now().year

URL = f"https://api-web.nhle.com/v1/playoff-bracket/{YEAR}"
STANDINGS = f"https://api-web.nhle.com/v1/standings/now"

SERIES_LOOKUP = {
    "A": ("East", "R1"),
    "B": ("East", "R1"),
    "C": ("East", "R1"),
    "D": ("East", "R1"),
    "E": ("West", "R1"),
    "F": ("West", "R1"),
    "G": ("West", "R1"),
    "H": ("West", "R1"),
    "I": ("East", "R2"),
    "J": ("East", "R2"),
    "K": ("West", "R2"),
    "L": ("West", "R2"),
    "M": ("East", "ECF"),
    "N": ("West", "WCF"),
    "O": ("Final", "SCF"),
}


def get_series_data(url):
    r = httpx.get(url)
    r.raise_for_status()
    return r.json()["series"]


def get_team_stats_data(url):
    r = httpx.get(url, follow_redirects=True)
    r.raise_for_status()
    return r.json()["standings"]


def parse_team(team: dict) -> dict:
    return {
        "api_id": team["id"],
        "name": team["name"]["default"],
        "logo_url": team["logo"],
        "dark_logo_url": team["darkLogo"],
        "abbrev": team["abbrev"],
    }


def parse_series(series):
    top = series.get("topSeedTeam")
    ts = top["id"] if top else None
    bottom = series.get("bottomSeedTeam")
    bs = bottom["id"] if bottom else None
    letter = series.get("seriesLetter")
    return {
        "title": series.get("seriesTitle"),
        "series_letter": letter,
        "conference": SERIES_LOOKUP[letter][0],
        "series_abbrev": SERIES_LOOKUP[letter][1],
        "top_seed_team": ts,
        "bottom_seed_team": bs,
        "top_seed_wins": series.get("topSeedWins"),
        "bottom_seed_wins": series.get("bottomSeedWins"),
        "winner": series.get("winningTeamId"),
        "child_series": None,
        "playoff_round": series.get("playoffRound"),
    }


def parse_standings(standings):
    return {
        "name": standings["teamName"]["default"],
        "year": YEAR,
        "wins": standings["regulationPlusOtWins"],
        "points": standings["points"],
        "losses": standings["losses"],
        "ot_losses": standings["otLosses"],
        "goal_diff": standings["goalDifferential"],
    }


def seed_season() -> Season:
    with Session(engine) as session:
        season = Season(year=datetime.now().year)
        session.add(season)
        session.commit()
        session.refresh(season)
        return season


def seed_teams(series):
    with Session(engine) as session:
        teams = {}
        for s in series:
            if not s.get("topSeedTeam") or not s.get("bottomSeedTeam"):
                continue
            top_seed = parse_team(s.get("topSeedTeam"))
            bottom_seed = parse_team(s.get("bottomSeedTeam"))
            teams[top_seed["api_id"]] = top_seed
            teams[bottom_seed["api_id"]] = bottom_seed

        for t in teams.values():
            t_obj = Team(**t)
            session.add(t_obj)
        session.commit()


def seed_series(series, season_id: int):
    with Session(engine) as session:
        team_id_map = {t.api_id: t.id for t in session.exec(select(Team)).all()}
        for s in series:
            vals = parse_series(s)
            vals["top_seed_team"] = team_id_map.get(vals["top_seed_team"]) or None
            vals["bottom_seed_team"] = team_id_map.get(vals["bottom_seed_team"]) or None
            vals["winner"] = team_id_map.get(vals["winner"]) or None
            vals["season_id"] = season_id
            session.add(Series(**vals))
        session.commit()


def seed_scoring_config():
    with Session(engine) as session:
        configs = [
            ScoringConfig(season_year=YEAR, series_abbrev="R1", points=1),
            ScoringConfig(season_year=YEAR, series_abbrev="R2", points=2),
            ScoringConfig(season_year=YEAR, series_abbrev="ECF", points=3),
            ScoringConfig(season_year=YEAR, series_abbrev="WCF", points=3),
            ScoringConfig(season_year=YEAR, series_abbrev="SCF", points=4),
        ]
        session.add_all(configs)
        session.commit()


def update_series_results(session: Session, series_data: list, season_id: int) -> None:
    team_id_map = {t.api_id: t.id for t in session.exec(select(Team)).all()}
    series_map = {s.series_letter: s for s in session.exec(select(Series).where(Series.season_id == season_id)).all()}

    for s_data in series_data:
        letter = s_data.get("seriesLetter")
        if not letter or letter not in series_map:
            continue
        s = series_map[letter]
        s.top_seed_wins = s_data.get("topSeedWins", 0)
        s.bottom_seed_wins = s_data.get("bottomSeedWins", 0)
        winner_api_id = s_data.get("winningTeamId")
        s.winner = team_id_map.get(winner_api_id) if winner_api_id else None
        top = s_data.get("topSeedTeam")
        if top and top.get("id", -1) != -1:
            s.top_seed_team = team_id_map.get(top["id"])
        bottom = s_data.get("bottomSeedTeam")
        if bottom and bottom.get("id", -1) != -1:
            s.bottom_seed_team = team_id_map.get(bottom["id"])
        session.add(s)
    session.commit()


def seed_standings_data(standings):
    with Session(engine) as session:
        result = []
        team_map = {t.name: t for t in session.exec(select(Team))}
        season = session.exec(select(Season).where(Season.year == YEAR)).first()
        for s in standings:
            parsed_standings = parse_standings(s)
            name = parsed_standings["name"]
            if name in team_map:
                team_id = team_map[name].id
                parsed_standings["team_id"] = team_id
                parsed_standings["season"] = season.id
                result.append(TeamStats(**parsed_standings))
        for team in result:
            session.add(team)
        session.commit()


if __name__ == "__main__":
    SQLModel.metadata.create_all(engine)
    series = get_series_data(URL)
    season = seed_season()
    seed_teams(series)
    seed_series(series, season.id)
    seed_scoring_config()
    stats = get_team_stats_data(STANDINGS)
    seed_standings_data(stats)
