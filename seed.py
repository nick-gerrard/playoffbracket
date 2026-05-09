from sqlmodel import create_engine, Session
from models import Team
import httpx

engine = create_engine("sqlite:///bracket.db")

URL = "https://api-web.nhle.com/v1/playoff-bracket/2026"


def parse_team(team: dict) -> dict:
    return {
        "id": team["id"],
        "name": team["name"]["default"],
        "logo": team["logo"],
        "dark_logo": team["darkLogo"],
        "abbrev": team["abbrev"],
    }


def seed_teams(url):
    r = httpx.get(url)
    r.raise_for_status()
    series = r.json()["series"]
    teams = {}
    for s in series:
        if not s.get("topSeedTeam") or not s.get("bottomSeedTeam"):
            continue
        top_seed = parse_team(s.get("topSeedTeam"))
        bottom_seed = parse_team(s.get("bottomSeedTeam"))
        series_letter = s.get("seriesLetter")
        series_title = s.get("seriesTitle")
        top_seed_team = Team(
            api_id=top_seed["id"],
            name=top_seed["name"],
            abbrev=top_seed["abbrev"],
            logo_url=top_seed["logo"],
            dark_logo_url=top_seed["dark_logo"],
        )
        bottom_seed_team = Team(
            api_id=bottom_seed["id"],
            name=bottom_seed["name"],
            abbrev=bottom_seed["abbrev"],
            logo_url=bottom_seed["logo"],
            dark_logo_url=bottom_seed["dark_logo"],
        )
        teams[top_seed["id"]] = top_seed_team
        teams[bottom_seed["id"]] = bottom_seed_team

    with Session(engine) as session:
        for t in teams.values():
            session.add(t)
        session.commit()
    return


if __name__ == "__main__":
    seed_teams(URL)
