from sqlmodel import create_engine, Session, select
from models import Team, Series
import httpx
from datetime import datetime

engine = create_engine("sqlite:///bracket.db")

YEAR = datetime.now().year

URL = f"https://api-web.nhle.com/v1/playoff-bracket/{YEAR}"

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


def get_data(url):
    r = httpx.get(url)
    r.raise_for_status()
    return r.json()["series"]


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


def seed_series(series):
    with Session(engine) as session:
        team_id_map = {t.api_id: t.id for t in session.exec(select(Team)).all()}
        for s in series:
            vals = parse_series(s)
            vals["top_seed_team"] = team_id_map.get(vals["top_seed_team"]) or None
            vals["bottom_seed_team"] = team_id_map.get(vals["bottom_seed_team"]) or None
            vals["winner"] = team_id_map.get(vals["winner"]) or None
            session.add(Series(**vals))
        session.commit()


if __name__ == "__main__":
    series = get_data(URL)
    seed_teams(series)
    seed_series(series)
